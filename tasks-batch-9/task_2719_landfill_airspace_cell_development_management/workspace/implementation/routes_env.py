"""Special-waste profiles, leachate treatment contracts and the tanker
shipment lifecycle."""
from decimal import Decimal

from core import (Body, ALL_ROLES, D, clock, created, date_part, endpoint, err,
                  filtered, fk_or_404, get_or_404, new_row, obj_response, paged,
                  public, q2, rows, touch)
import services as S


def _second(iso):
    """Windows are compared at whole-second resolution (PRD 3.10)."""
    return iso[:19]


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end): windows that merely touch do not overlap."""
    return _second(a_start) < _second(b_end) and _second(b_start) < _second(a_end)


def _lazy_expire(agreement):
    """The one lazy-expiry producer path, shared by booking and single reads."""
    if agreement["status"] in ("ACTIVE", "SUSPENDED") \
            and agreement["expires_on"] < clock():
        agreement["status"] = "EXPIRED"
        touch(agreement)
        return True
    return False


def _agreement_view(agreement):
    """scheduled_gallons_today is a derivation of the current logical clock, so
    it is recomputed whenever the row is serialized (no version bump)."""
    agreement["scheduled_gallons_today"] = S.scheduled_gallons_today(agreement)
    return public(agreement)


def _gallons_on(agreement, day_iso, exclude_id=None):
    total = Decimal("0")
    for s in S.shipments_of_agreement(agreement["id"]):
        if s["id"] == exclude_id:
            continue
        if s["status"] in ("SCHEDULED", "DISPATCHED", "ACCEPTED") \
                and date_part(s["window_start"]) == date_part(day_iso):
            total += D(s["gallons"])
    return q2(total)


def register(app):
    # ------------------------------------------------ special-waste profiles ---
    @endpoint(app, "/special-waste-approvals", ["POST"], ["EnvironmentalManager"])
    def request_approval(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        generator_name = b.string("generator_name", minlen=1, maxlen=120)
        waste_code = b.string("waste_code", minlen=1, maxlen=30)
        profile_stream = b.enum("profile_stream", S.SPECIAL_STREAMS)
        approved_tons_cap = b.number("approved_tons_cap", gt=0)
        effective_from = b.timestamp("effective_from")
        expires_on = b.timestamp("expires_on")
        if not expires_on > effective_from:
            raise err("ERR_INVALID_REQUEST",
                      "expires_on must be strictly after effective_from.")
        fk_or_404("landfill", landfill_id)
        row = new_row("special_waste_approval", {
            "landfill_id": landfill_id,
            "generator_name": generator_name,
            "waste_code": waste_code,
            "profile_stream": profile_stream,
            "approved_tons_cap": approved_tons_cap,
            "effective_from": effective_from,
            "expires_on": expires_on,
            "consumed_tons": 0.0,
            "decision_reason": None,
            "status": "REQUESTED",
        })
        return created(public(row))

    @endpoint(app, "/special-waste-approvals/<special_waste_approval_id>", ["GET"],
              ALL_ROLES)
    def read_approval(user_id, role, special_waste_approval_id):
        return obj_response(public(get_or_404("special_waste_approval",
                                              special_waste_approval_id)))

    @endpoint(app, "/special-waste-approvals", ["GET"], ALL_ROLES)
    def list_approvals(user_id, role):
        return paged(filtered(rows("special_waste_approval"), {
            "landfill_id": "landfill_id",
            "status": "status",
        }))

    @endpoint(app, "/special-waste-approvals/<special_waste_approval_id>/approve",
              ["POST"], ["EnvironmentalManager"])
    def approve_approval(user_id, role, special_waste_approval_id):
        b = Body()
        reason = b.string("decision_reason")
        approval = get_or_404("special_waste_approval", special_waste_approval_id)
        if approval["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a REQUESTED profile may be approved.")
        lf = S.landfill_of(approval["landfill_id"])
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A closed site may not take on new special waste.")
        approval["decision_reason"] = reason
        approval["status"] = "APPROVED"
        touch(approval)
        return obj_response(public(approval))

    @endpoint(app, "/special-waste-approvals/<special_waste_approval_id>/deny",
              ["POST"], ["EnvironmentalManager"])
    def deny_approval(user_id, role, special_waste_approval_id):
        b = Body()
        reason = b.string("decision_reason")
        approval = get_or_404("special_waste_approval", special_waste_approval_id)
        if approval["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a REQUESTED profile may be denied.")
        approval["decision_reason"] = reason
        approval["status"] = "DENIED"
        touch(approval)
        return obj_response(public(approval))

    @endpoint(app, "/special-waste-approvals/<special_waste_approval_id>/revoke",
              ["POST"], ["EnvironmentalManager"])
    def revoke_approval(user_id, role, special_waste_approval_id):
        b = Body()
        reason = b.string("decision_reason")
        approval = get_or_404("special_waste_approval", special_waste_approval_id)
        if approval["status"] not in ("APPROVED", "SUSPENDED", "EXHAUSTED"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a live profile may be revoked.")
        approval["decision_reason"] = reason
        approval["status"] = "REVOKED"
        touch(approval)
        return obj_response(public(approval))

    # -------------------------------------------------- treatment agreements ---
    @endpoint(app, "/treatment-agreements", ["POST"], ["EnvironmentalManager"])
    def register_agreement(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        facility_name = b.string("facility_name", minlen=1, maxlen=120)
        daily_gallon_cap = b.integer("daily_gallon_cap", minimum=1)
        base_haul_fee = b.number("base_haul_fee", ge=0)
        treatment_rate_per_kgal = b.number("treatment_rate_per_kgal", gt=0)
        effective_from = b.timestamp("effective_from")
        expires_on = b.timestamp("expires_on")
        slots = b.integer("concurrent_slot_capacity", required=False,
                          minimum=1, maximum=10, default=2)
        if not expires_on > effective_from:
            raise err("ERR_INVALID_REQUEST",
                      "expires_on must be strictly after effective_from.")
        fk_or_404("landfill", landfill_id)
        row = new_row("treatment_agreement", {
            "landfill_id": landfill_id,
            "facility_name": facility_name,
            "daily_gallon_cap": daily_gallon_cap,
            "concurrent_slot_capacity": slots,
            "base_haul_fee": base_haul_fee,
            "treatment_rate_per_kgal": treatment_rate_per_kgal,
            "effective_from": effective_from,
            "expires_on": expires_on,
            "scheduled_gallons_today": 0.0,
            "suspension_reason": None,
            "status": "ACTIVE",
        })
        return created(public(row))

    @endpoint(app, "/treatment-agreements/<treatment_agreement_id>", ["GET"],
              ALL_ROLES)
    def read_agreement(user_id, role, treatment_agreement_id):
        agreement = get_or_404("treatment_agreement", treatment_agreement_id)
        _lazy_expire(agreement)
        return obj_response(_agreement_view(agreement))

    @endpoint(app, "/treatment-agreements", ["GET"], ALL_ROLES)
    def list_agreements(user_id, role):
        return paged(filtered(rows("treatment_agreement"), {
            "landfill_id": "landfill_id",
            "status": "status",
        }), serializer=_agreement_view)

    @endpoint(app, "/treatment-agreements/<treatment_agreement_id>/suspend",
              ["POST"], ["EnvironmentalManager"])
    def suspend_agreement(user_id, role, treatment_agreement_id):
        b = Body()
        reason = b.string("suspension_reason")
        agreement = get_or_404("treatment_agreement", treatment_agreement_id)
        if agreement["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only an ACTIVE agreement may be suspended.")
        agreement["suspension_reason"] = reason
        agreement["status"] = "SUSPENDED"
        touch(agreement)
        return obj_response(public(agreement))

    @endpoint(app, "/treatment-agreements/<treatment_agreement_id>/reinstate",
              ["POST"], ["EnvironmentalManager"])
    def reinstate_agreement(user_id, role, treatment_agreement_id):
        agreement = get_or_404("treatment_agreement", treatment_agreement_id)
        if agreement["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a SUSPENDED agreement may be reinstated.")
        if agreement["expires_on"] < clock():
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The agreement window has already passed.")
        agreement["suspension_reason"] = None
        agreement["status"] = "ACTIVE"
        touch(agreement)
        return obj_response(public(agreement))

    @endpoint(app,
              "/treatment-agreements/<treatment_agreement_id>/leachate-shipments",
              ["GET"], ALL_ROLES)
    def list_agreement_shipments(user_id, role, treatment_agreement_id):
        get_or_404("treatment_agreement", treatment_agreement_id)
        pool = [s for s in rows("leachate_shipment")
                if s["treatment_agreement_id"] == treatment_agreement_id]
        return paged(filtered(pool, {"status": "status"}))

    # ------------------------------------------------- leachate shipments -----
    @endpoint(app, "/leachate-shipments", ["POST"], ["SiteOperator"])
    def book_shipment(user_id, role):
        b = Body()
        agreement_id = b.fk("treatment_agreement_id")
        gallons = b.number("gallons", gt=0)
        window_start = b.timestamp("window_start")
        window_end = b.timestamp("window_end")
        if not window_end > window_start:
            raise err("ERR_INVALID_REQUEST",
                      "window_end must be strictly after window_start.")
        if date_part(window_start) != date_part(window_end):
            raise err("ERR_INVALID_REQUEST",
                      "The delivery window must fall on one UTC calendar date.")
        agreement = fk_or_404("treatment_agreement", agreement_id)
        S.scope(user_id, agreement["landfill_id"])
        _lazy_expire(agreement)
        if agreement["status"] != "ACTIVE":
            raise err("ERR_AGREEMENT_NOT_ACTIVE",
                      "The treatment agreement is not accepting bookings.")
        occupied = 1
        for s in S.shipments_of_agreement(agreement["id"]):
            if s["status"] not in ("SCHEDULED", "DISPATCHED", "ACCEPTED"):
                continue
            if _overlaps(window_start, window_end,
                         s["window_start"], s["window_end"]):
                occupied += 1
        if occupied > agreement["concurrent_slot_capacity"]:
            raise err("ERR_SLOT_CAPACITY_EXCEEDED",
                      "The receiving gate has no free slot in that window.")
        if _gallons_on(agreement, window_start) + D(gallons) \
                > D(agreement["daily_gallon_cap"]):
            raise err("ERR_DAILY_GALLON_CAP_EXCEEDED",
                      "The facility's daily gallon cap would be exceeded.")
        treatment_fee, pre = S.leachate_pre_surcharge(gallons, agreement)
        row = new_row("leachate_shipment", {
            "treatment_agreement_id": agreement["id"],
            "gallons": gallons,
            "window_start": window_start,
            "window_end": window_end,
            "hauler_ref": None,
            "gate_reason": None,
            "treatment_fee": float(treatment_fee),
            "surcharge_pct": float(S.surcharge_for(pre)),
            "invoice_total": None,
            "status": "SCHEDULED",
        })
        agreement["scheduled_gallons_today"] = S.scheduled_gallons_today(agreement)
        touch(agreement)
        return created(public(row))

    @endpoint(app, "/leachate-shipments/<leachate_shipment_id>", ["GET"], ALL_ROLES)
    def read_shipment(user_id, role, leachate_shipment_id):
        return obj_response(public(get_or_404("leachate_shipment",
                                              leachate_shipment_id)))

    @endpoint(app, "/leachate-shipments", ["GET"], ALL_ROLES)
    def list_shipments(user_id, role):
        return paged(filtered(rows("leachate_shipment"), {
            "treatment_agreement_id": "treatment_agreement_id",
            "status": "status",
        }))

    @endpoint(app, "/leachate-shipments/<leachate_shipment_id>/dispatch", ["POST"],
              ["SiteOperator"])
    def dispatch_shipment(user_id, role, leachate_shipment_id):
        b = Body()
        hauler_ref = b.string("hauler_ref")
        shipment = get_or_404("leachate_shipment", leachate_shipment_id)
        agreement = S.agreement_of(shipment)
        S.scope(user_id, agreement["landfill_id"])
        if shipment["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a SCHEDULED shipment may be dispatched.")
        if agreement["status"] != "ACTIVE":
            raise err("ERR_AGREEMENT_NOT_ACTIVE",
                      "The treatment agreement is not accepting deliveries.")
        shipment["hauler_ref"] = hauler_ref
        shipment["status"] = "DISPATCHED"
        touch(shipment)
        return obj_response(public(shipment))

    @endpoint(app, "/leachate-shipments/<leachate_shipment_id>/confirm-acceptance",
              ["POST"], ["SiteOperator"])
    def accept_shipment(user_id, role, leachate_shipment_id):
        shipment = get_or_404("leachate_shipment", leachate_shipment_id)
        agreement = S.agreement_of(shipment)
        S.scope(user_id, agreement["landfill_id"])
        if shipment["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a DISPATCHED shipment may be accepted.")
        shipment["status"] = "ACCEPTED"
        shipment["invoice_total"] = S.leachate_invoice_total(shipment, agreement)
        touch(shipment)
        return obj_response(public(shipment))

    @endpoint(app, "/leachate-shipments/<leachate_shipment_id>/reject-at-gate",
              ["POST"], ["SiteOperator"])
    def reject_shipment(user_id, role, leachate_shipment_id):
        b = Body()
        gate_reason = b.string("gate_reason")
        shipment = get_or_404("leachate_shipment", leachate_shipment_id)
        agreement = S.agreement_of(shipment)
        S.scope(user_id, agreement["landfill_id"])
        if shipment["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a DISPATCHED shipment may be turned away at the gate.")
        shipment["gate_reason"] = gate_reason
        shipment["status"] = "REJECTED_AT_GATE"
        touch(shipment)
        agreement["scheduled_gallons_today"] = S.scheduled_gallons_today(agreement)
        touch(agreement)
        return obj_response(public(shipment))

    @endpoint(app, "/leachate-shipments/<leachate_shipment_id>/cancel", ["POST"],
              ["SiteOperator"])
    def cancel_shipment(user_id, role, leachate_shipment_id):
        b = Body()
        gate_reason = b.string("gate_reason")
        shipment = get_or_404("leachate_shipment", leachate_shipment_id)
        agreement = S.agreement_of(shipment)
        S.scope(user_id, agreement["landfill_id"])
        if shipment["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a SCHEDULED shipment may be cancelled.")
        shipment["gate_reason"] = gate_reason
        shipment["status"] = "CANCELLED"
        touch(shipment)
        agreement["scheduled_gallons_today"] = S.scheduled_gallons_today(agreement)
        touch(agreement)
        return obj_response(public(shipment))
