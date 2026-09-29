"""Commission claims: filing, the denial cycle and resolution (PRD 3.7)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import authenticate, field_enum, field_int, field_str, read_body
from listing import list_response
from lookup import get_booking, get_claim
from store import date_of, new_row, serialize, store, touch

bp = Blueprint("claim", __name__)

ALL_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor",
             "SupplierPortal")


@bp.post("/bookings/<booking_id>/commission-claims")
def file_claim(booking_id):
    caller = authenticate(("Advisor",))
    body = read_body(("claimed_amount_cents",))
    claimed = field_int(body, "claimed_amount_cents")

    booking = get_booking(booking_id)
    if booking["advisor_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    money = booking["commission_status"]
    if money not in ("EXPECTED", "RECEIVED"):
        raise ApiError("ERR_INVALID_COMMISSION_STATE")

    supplier = store.suppliers.get(booking["supplier_id"])
    from_received = money == "RECEIVED"

    if not from_received:
        if booking["booking_status"] != "TRAVELED":
            raise ApiError("ERR_INVALID_BOOKING_STATE")
        due_date = calc.booking_due_date(booking, supplier)
        if date_of(store.clock) < due_date:
            raise ApiError("ERR_INVALID_COMMISSION_STATE",
                           "The supplier's remittance due date has not arrived.")
        outstanding = (booking["expected_commission_cents"]
                       - booking["received_commission_cents"])
        if claimed != outstanding:
            raise ApiError("ERR_CLAIM_AMOUNT_MISMATCH")
    else:
        if (booking["shortfall_cents"] <= 0
                or booking["statement_id"] is not None
                or claimed != booking["shortfall_cents"]):
            raise ApiError("ERR_CLAIM_AMOUNT_MISMATCH")

    row = new_row({
        "booking_id": booking["id"],
        "advisor_id": booking["advisor_id"],
        "claimed_amount_cents": claimed,
        "status": "SUBMITTED",
        "round_count": 1,
        "denial_reason": None,
        "aging_days": 0,
        "escalation_level": "NORMAL",
        "resolved_amount_cents": 0,
    })
    calc.refresh_claim_aging(row)
    store.claims[row["id"]] = row

    booking["commission_status"] = "CLAIMED"
    touch(booking)

    if from_received:
        advisor = store.advisors.get(booking["advisor_id"])
        if advisor is not None:
            calc.recompute_final(advisor)
    calc.recompute_aging_for_booking(booking)
    return created(serialize(row))


@bp.get("/commission-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(ALL_ROLES)
    claim = get_claim(claim_id)
    if claim["status"] in ("SUBMITTED", "DENIED"):
        calc.refresh_claim_aging(claim)
    return ok(serialize(claim))


@bp.get("/commission-claims")
def list_claims():
    authenticate(ALL_ROLES)
    for claim in store.claims.values():
        if claim["status"] in ("SUBMITTED", "DENIED"):
            calc.refresh_claim_aging(claim)
    return list_response(store.claims.values(),
                         (("booking_id", "booking_id"),
                          ("advisor_id", "advisor_id"),
                          ("status", "status"),
                          ("escalation_level", "escalation_level")))


@bp.post("/commission-claims/<claim_id>/deny")
def deny_claim(claim_id):
    caller = authenticate(("SupplierPortal",))
    body = read_body(("denial_reason",))
    reason = field_str(body, "denial_reason", max_len=2000)

    claim = get_claim(claim_id)
    booking = store.bookings.get(claim["booking_id"])
    if booking is None or booking["supplier_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    claim["status"] = "DENIED"
    claim["denial_reason"] = reason
    calc.refresh_claim_aging(claim)
    touch(claim)
    return ok(serialize(claim))


@bp.post("/commission-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    caller = authenticate(("Advisor",))
    body = read_body(("note",), required_body=False)
    field_str(body, "note", required=False, allow_empty=True, max_len=2000)

    claim = get_claim(claim_id)
    if claim["advisor_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if claim["round_count"] >= calc.MAX_CLAIM_ROUNDS:
        raise ApiError("ERR_CLAIM_ROUND_LIMIT")

    claim["status"] = "SUBMITTED"
    claim["round_count"] += 1
    claim["denial_reason"] = None
    calc.refresh_claim_aging(claim)
    touch(claim)
    return ok(serialize(claim))


@bp.post("/commission-claims/<claim_id>/resolve")
def resolve_claim(claim_id):
    authenticate(("HostOperations",))
    body = read_body(("resolution", "recovered_amount_cents"))
    resolution = field_enum(body, "resolution", ("PAID", "WRITTEN_OFF"))
    recovered = field_int(body, "recovered_amount_cents", required=False)

    claim = get_claim(claim_id)
    if claim["status"] not in ("SUBMITTED", "DENIED"):
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    if resolution == "PAID":
        if (recovered is None or recovered <= 0
                or recovered > claim["claimed_amount_cents"]):
            raise ApiError("ERR_CLAIM_RESOLUTION_INVALID")
    else:
        if recovered not in (None, 0):
            raise ApiError("ERR_CLAIM_RESOLUTION_INVALID")

    booking = store.bookings.get(claim["booking_id"])
    advisor = store.advisors.get(claim["advisor_id"])

    if resolution == "PAID":
        claim["status"] = "RESOLVED_PAID"
        claim["resolved_amount_cents"] = recovered
        if booking is not None:
            booking["received_commission_cents"] += recovered
            booking["shortfall_cents"] = (booking["expected_commission_cents"]
                                          - booking["received_commission_cents"])
            booking["commission_received_on"] = store.clock
            booking["commission_status"] = "RECEIVED"
            touch(booking)
    else:
        claim["status"] = "RESOLVED_WRITTEN_OFF"
        claim["resolved_amount_cents"] = 0
        if booking is not None:
            booking["commission_status"] = "WRITTEN_OFF"
            touch(booking)

    calc.refresh_claim_aging(claim)
    touch(claim)

    if booking is not None:
        calc.recompute_aging_for_booking(booking)
    if advisor is not None:
        calc.recompute_final(advisor)
        calc.recompute_provisional(advisor)
    return ok(serialize(claim))
