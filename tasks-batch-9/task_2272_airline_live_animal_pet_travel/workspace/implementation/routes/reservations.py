"""Reservations: creation, reads, charge summary, confirm, cancel, compliance sweep."""
from db import base_row, parse_iso, sorted_rows, store, touch
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_ACCEPTANCE_AGENT, ROLE_COMPLIANCE_OFFICER,
                        ROLE_PROGRAM_ADMIN, ROLE_RESERVATIONS_AGENT,
                        ROLE_VETERINARY_REVIEWER, register)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import ROUTING_TYPES, listing

AGENT = [ROLE_RESERVATIONS_AGENT]
VET = [ROLE_VETERINARY_REVIEWER]
SUMMARY_ROLES = [ROLE_PROGRAM_ADMIN, ROLE_RESERVATIONS_AGENT, ROLE_ACCEPTANCE_AGENT,
                 ROLE_COMPLIANCE_OFFICER]

RESERVATION_SCHEMA = {
    "passenger_name": {"type": "string", "required": True, "min_length": 1},
    "contact_email": {"type": "string", "required": True, "min_length": 3},
    "routing_type": {"type": "enum", "required": True, "values": ROUTING_TYPES},
    "is_service_animal_booking": {"type": "boolean"},
}

REASON_SCHEMA = {"reason": {"type": "string", "nullable": True}}


def _confirm_slot_gate(reservation):
    """Preconditions of the three confirm edges that carry no dedicated error id."""
    animals = [a for a in domain.animals_of_reservation(reservation)
               if a["status"] != "DENIED"]
    if reservation["animal_count"] < 1 or not animals:
        raise ApiError("ERR_RESERVATION_INVALID_STATE",
                       "the reservation carries no animal record")
    status = reservation["booking_status"]
    for animal in animals:
        slots = [s for s in domain.segments_of_animal(animal)
                 if s["status"] == "RESERVED"]
        if not slots:
            raise ApiError("ERR_RESERVATION_INVALID_STATE",
                           "animal %s holds no reserved routing slot" % animal["id"])
        if status == "REBOOK_REQUIRED":
            open_slots = [s for s in slots
                          if domain.leg_of_segment(s)["posture"] in ("OPEN", "RESTRICTED")]
            if not open_slots:
                raise ApiError("ERR_RESERVATION_INVALID_STATE",
                               "animal %s holds no slot on an open leg" % animal["id"])
        if status == "HOLD_PARTIAL":
            indexes = sorted(s["sequence_index"] for s in slots)
            if indexes != list(range(1, len(indexes) + 1)):
                raise ApiError("ERR_RESERVATION_INVALID_STATE",
                               "animal %s has no contiguous reserved chain from "
                               "sequence_index 1" % animal["id"])


def init(app):
    @register(app, "/reservations", "POST", AGENT, schema=RESERVATION_SCHEMA)
    def create_reservation(ctx):
        body = ctx.body
        row = base_row()
        row.update({
            "passenger_name": body["passenger_name"],
            "contact_email": body["contact_email"],
            "routing_type": body["routing_type"],
            "is_service_animal_booking": body.get("is_service_animal_booking", False),
            "booked_by_agent_id": ctx.user_id,
            "booking_status": "PENDING",
            "compliance_status": "UNVERIFIED",
            "animal_count": 0,
            "subtotal_amount": 0,
            "irops_fee_total": 0,
            "loyalty_tier_pct": 0,
            "loyalty_discount_amount": 0,
            "refunded_amount": 0,
            "net_payable_amount": 0,
        })
        store.reservations[row["id"]] = row
        return created_response(serialize.dump("reservation", row))

    @register(app, "/reservations/<rid>", "GET", ALL_ROLES, path_entity="reservation")
    def get_reservation(ctx):
        return object_response(serialize.dump("reservation", ctx.row))

    @register(app, "/reservations", "GET", ALL_ROLES, paginated=True)
    def list_reservations(ctx):
        return listing("reservation", sorted_rows(store.reservations), ctx,
                       [("booking_status", "booking_status", "str"),
                        ("compliance_status", "compliance_status", "str")])

    @register(app, "/reservations/<rid>/charge-summary", "GET", SUMMARY_ROLES,
              path_entity="reservation")
    def charge_summary(ctx):
        row = ctx.row
        holds = row["subtotal_amount"] == (row["net_payable_amount"]
                                           + row["loyalty_discount_amount"]
                                           + row["refunded_amount"])
        return object_response({
            "reservation_id": row["id"],
            "subtotal_amount": row["subtotal_amount"],
            "irops_fee_total": row["irops_fee_total"],
            "loyalty_tier_pct": row["loyalty_tier_pct"],
            "loyalty_discount_amount": row["loyalty_discount_amount"],
            "refunded_amount": row["refunded_amount"],
            "net_payable_amount": row["net_payable_amount"],
            "invariant_holds": holds,
        })

    @register(app, "/reservations/<rid>/confirm", "POST", AGENT, schema={},
              path_entity="reservation")
    def confirm_reservation(ctx):
        reservation = ctx.row
        domain.require(reservation["booking_status"]
                       in ("PENDING", "HOLD_PARTIAL", "REBOOK_REQUIRED"),
                       "ERR_RESERVATION_INVALID_STATE",
                       "a %s reservation cannot be confirmed"
                       % reservation["booking_status"])
        for animal in domain.animals_of_reservation(reservation):
            if animal["status"] == "DENIED":
                continue
            domain.require(animal["status"] == "TRAVEL_READY", "ERR_ANIMAL_INVALID_STATE",
                           "animal %s is %s, not TRAVEL_READY"
                           % (animal["id"], animal["status"]))
        domain.require(reservation["compliance_status"] == "VERIFIED",
                       "ERR_COMPLIANCE_NOT_VERIFIED",
                       "the compliance dimension is %s"
                       % reservation["compliance_status"])
        _confirm_slot_gate(reservation)
        reservation["booking_status"] = "CONFIRMED"
        touch(reservation)
        domain.run_charge_assembly(reservation)
        return object_response(serialize.dump("reservation", reservation))

    @register(app, "/reservations/<rid>/cancel", "POST", AGENT, schema=REASON_SCHEMA,
              path_entity="reservation")
    def cancel_reservation(ctx):
        reservation = ctx.row
        domain.require(reservation["booking_status"]
                       in ("PENDING", "CONFIRMED", "HOLD_PARTIAL", "REBOOK_REQUIRED"),
                       "ERR_RESERVATION_INVALID_STATE",
                       "a %s reservation cannot be cancelled"
                       % reservation["booking_status"])
        for segment in domain.segments_of_reservation(reservation):
            if segment["status"] == "RESERVED":
                domain.release_segment(segment, refund=False, recompute_booking=False)
        for animal in domain.animals_of_reservation(reservation):
            for allocation in domain.allocations_of_animal(animal):
                if allocation["status"] in ("RESERVED", "OCCUPIED"):
                    domain.release_allocation(allocation)
        reservation["refunded_amount"] += calc.cancellation_refund(
            reservation["subtotal_amount"])
        reservation["booking_status"] = "CANCELLED"
        touch(reservation)
        domain.run_charge_assembly(reservation)
        return object_response(serialize.dump("reservation", reservation))

    @register(app, "/reservations/<rid>/verify-compliance", "POST", VET, schema={},
              path_entity="reservation")
    def verify_compliance(ctx):
        reservation = ctx.row
        animals = [a for a in domain.animals_of_reservation(reservation)
                   if a["status"] != "DENIED"]
        error_id, backing = domain.check_documents(animals)
        if error_id is not None:
            raise ApiError(error_id, "the destination document set is incomplete")
        clock = store.clock
        expired = [d for d in backing if parse_iso(d["expires_at"]) <= clock]
        if expired:
            for document in expired:
                document["status"] = "EXPIRED"
                touch(document)
            reservation["compliance_status"] = "EXPIRED"
        else:
            reservation["compliance_status"] = "VERIFIED"
        touch(reservation)
        return object_response(serialize.dump("reservation", reservation))
