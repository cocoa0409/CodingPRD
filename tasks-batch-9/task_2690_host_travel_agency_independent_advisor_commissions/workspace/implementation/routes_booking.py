"""Booking submission, pricing and fulfilment (PRD 3.5, 3.6, 3.7)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import (authenticate, field_dt, field_enum, field_int, field_str,
                    read_body)
from listing import list_response
from lookup import get_advisor, get_booking, get_client, get_supplier
from routes_client import append_trust_entry
from store import date_of, new_row, ordered, serialize, store, touch

bp = Blueprint("booking", __name__)

ALL_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor",
             "SupplierPortal")

CHANNELS = ("SUPPLIER_DIRECT", "CONSORTIUM", "INTERNAL_TOOL")
PAYMENT_METHODS = ("CLIENT_TRUST", "MERCHANT_DIRECT", "HOST_MERCHANT")
CANCELLATION_REASONS = ("CLIENT_INITIATED", "ADVISOR_ERROR", "SUPPLIER_INITIATED")

LIVE_BOOKING_STATUSES = ("SUBMITTED", "CONFIRMED", "TRAVELED")


@bp.post("/bookings")
def submit_booking():
    caller = authenticate(("Advisor",))
    body = read_body(("advisor_id", "supplier_id", "client_id", "channel",
                      "payment_method", "gross_sale_cents",
                      "deposit_amount_cents", "travel_start_date",
                      "travel_end_date", "non_commissionable_cents"))
    advisor_id = field_str(body, "advisor_id")
    supplier_id = field_str(body, "supplier_id")
    client_id = field_str(body, "client_id")
    channel = field_enum(body, "channel", CHANNELS)
    payment_method = field_enum(body, "payment_method", PAYMENT_METHODS)
    gross_sale = field_int(body, "gross_sale_cents", minimum=1)
    deposit = field_int(body, "deposit_amount_cents", minimum=0,
                        maximum=gross_sale)
    travel_start = field_dt(body, "travel_start_date")
    travel_end = field_dt(body, "travel_end_date")
    non_commissionable = field_int(body, "non_commissionable_cents",
                                  required=False, default=0, minimum=0,
                                  maximum=gross_sale)

    advisor = get_advisor(advisor_id)
    supplier = get_supplier(supplier_id)
    client = get_client(client_id)

    if advisor["id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if advisor["status"] != "ACTIVE":
        raise ApiError("ERR_ADVISOR_NOT_ACTIVE")

    if not calc.has_seller_of_travel(advisor, store.clock):
        raise ApiError("ERR_SELLER_OF_TRAVEL_INVALID")
    if not calc.has_eo_coverage(advisor, store.clock):
        raise ApiError("ERR_EO_COVERAGE_INSUFFICIENT")

    if advisor["trust_account_required"]:
        if payment_method != "CLIENT_TRUST":
            raise ApiError("ERR_TRUST_ACCOUNT_REQUIRED")
    else:
        if payment_method == "CLIENT_TRUST":
            raise ApiError("ERR_TRUST_ACCOUNT_NOT_PERMITTED")

    if not calc.has_supplier_accreditation(advisor, supplier["id"], store.clock):
        raise ApiError("ERR_SUPPLIER_ACCREDITATION_MISSING")

    occupants = 0
    for existing in ordered(store.bookings.values()):
        if existing["client_id"] != client["id"]:
            continue
        if existing["booking_status"] not in LIVE_BOOKING_STATUSES:
            continue
        if (existing["travel_start_date"] < travel_end
                and travel_start < existing["travel_end_date"]):
            occupants += 1
    if occupants + 1 > client["max_concurrent_trips"]:
        raise ApiError("ERR_TRAVEL_WINDOW_CONFLICT")

    if not travel_end > travel_start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    agreement = calc.active_agreement(advisor["id"])

    row = new_row({
        "advisor_id": advisor["id"],
        "supplier_id": supplier["id"],
        "client_id": client["id"],
        "agreement_id": agreement["id"] if agreement else None,
        "statement_id": None,
        "channel": channel,
        "payment_method": payment_method,
        "gross_sale_cents": gross_sale,
        "non_commissionable_cents": non_commissionable,
        "deposit_amount_cents": deposit,
        "travel_start_date": travel_start,
        "travel_end_date": travel_end,
        "booking_status": "SUBMITTED",
        "commission_status": "PENDING",
        "commissionable_base_cents": 0,
        "applied_commission_rate": 0,
        "expected_commission_cents": 0,
        "received_commission_cents": 0,
        "shortfall_cents": 0,
        "commission_received_on": None,
        "settled_share_cents": 0,
        "settled_tier_level": None,
        "chargeback_amount_cents": 0,
        "chargeback_recognized_at": None,
        "cancellation_reason": None,
    })
    calc.price_booking(row, advisor, supplier)

    store.bookings[row["id"]] = row
    snapshot = (advisor["production_ytd_provisional_cents"],
                advisor["split_tier_provisional"])
    try:
        calc.recompute_provisional(advisor)
    except ApiError:
        # A rejected request has no effect whatsoever (PRD 2.8).
        del store.bookings[row["id"]]
        advisor["production_ytd_provisional_cents"] = snapshot[0]
        advisor["split_tier_provisional"] = snapshot[1]
        raise

    return created(serialize(row))


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    authenticate(ALL_ROLES)
    return ok(serialize(get_booking(booking_id)))


@bp.get("/bookings")
def list_bookings():
    authenticate(ALL_ROLES)
    return list_response(store.bookings.values(),
                         (("advisor_id", "advisor_id"),
                          ("supplier_id", "supplier_id"),
                          ("client_id", "client_id"),
                          ("agreement_id", "agreement_id"),
                          ("statement_id", "statement_id"),
                          ("booking_status", "booking_status"),
                          ("commission_status", "commission_status")))


# --------------------------------------------------------------------------
# fulfilment
# --------------------------------------------------------------------------

@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    caller = authenticate(("SupplierPortal",))
    read_body((), required_body=False)
    booking = get_booking(booking_id)

    if booking["supplier_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if booking["booking_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    advisor = store.advisors.get(booking["advisor_id"])
    if advisor is None or advisor["status"] not in ("ACTIVE", "SUSPENDED", "DEPARTING"):
        raise ApiError("ERR_ADVISOR_NOT_ACTIVE")

    client = store.clients.get(booking["client_id"])
    if booking["payment_method"] == "CLIENT_TRUST":
        balance = calc.recompute_client_balance(client) if client else 0
        if balance < booking["deposit_amount_cents"]:
            raise ApiError("ERR_TRUST_DEPOSIT_SHORTFALL")

    booking["booking_status"] = "CONFIRMED"
    if booking["expected_commission_cents"] > 0:
        booking["commission_status"] = "EXPECTED"
        if advisor is not None:
            calc.recompute_provisional(advisor)
    else:
        # A booking that earns nothing never joins the receivable lifecycle.
        booking["commission_status"] = "WRITTEN_OFF"

    if (booking["payment_method"] == "CLIENT_TRUST" and client is not None
            and booking["deposit_amount_cents"] > 0):
        append_trust_entry(client, "DISBURSEMENT", booking["deposit_amount_cents"],
                           "Deposit swept to supplier on booking confirmation.",
                           booking["id"], caller.user_id)

    calc.recompute_aging_for_booking(booking)
    touch(booking)
    return ok(serialize(booking))


@bp.post("/bookings/<booking_id>/traveled")
def travel_booking(booking_id):
    authenticate(("HostOperations",))
    read_body((), required_body=False)
    booking = get_booking(booking_id)

    if booking["booking_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if store.clock < booking["travel_end_date"]:
        raise ApiError("ERR_TRAVELED_TOO_EARLY")

    booking["booking_status"] = "TRAVELED"
    calc.recompute_aging_for_booking(booking)
    touch(booking)
    return ok(serialize(booking))


def _cascade_chargeback(booking):
    """CASCADE-A, four links deep, each caused by the link before it."""
    # LEVEL 1 — the money axis closes out and the claw-back amount is computed.
    booking["commission_status"] = "CHARGED_BACK"
    booking["chargeback_amount_cents"] = calc.cancellation_chargeback(booking)

    supplier = store.suppliers.get(booking["supplier_id"])
    if supplier is None:
        return

    # LEVEL 2 — caused by level 1.
    count = calc.recompute_supplier_chargeback_count(supplier)
    demoted = False
    if (count >= supplier["probation_chargeback_threshold"]
            and supplier["program_status"] == "PREFERRED"):
        supplier["program_status"] = "PROBATION"
        touch(supplier)
        demoted = True

    # LEVEL 3 — caused specifically by level 2's change of program_status.
    if demoted:
        touched_advisors = []
        for other in calc.supplier_bookings(supplier["id"]):
            if other["commission_status"] != "PENDING":
                continue
            owner = store.advisors.get(other["advisor_id"])
            if owner is None:
                continue
            calc.price_booking(other, owner, supplier)
            touch(other)
            if owner["id"] not in [a["id"] for a in touched_advisors]:
                touched_advisors.append(owner)
        # LEVEL 4 — caused by level 3's rewrite of expected amounts.
        for owner in touched_advisors:
            calc.recompute_provisional(owner)
            touch(owner)

    calc.recompute_supplier_aging(supplier)


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    caller = authenticate(("Advisor", "HostOperations"))
    body = read_body(("cancellation_reason",))
    reason = field_enum(body, "cancellation_reason", CANCELLATION_REASONS)

    booking = get_booking(booking_id)
    if caller.is_advisor and booking["advisor_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if booking["booking_status"] not in ("SUBMITTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    advisor = store.advisors.get(booking["advisor_id"])
    booking["booking_status"] = "CANCELLED"
    booking["cancellation_reason"] = reason

    money = booking["commission_status"]
    if money == "EXPECTED":
        booking["commission_status"] = "WRITTEN_OFF"
        calc.recompute_aging_for_booking(booking)
        if advisor is not None:
            calc.recompute_provisional(advisor)
    elif money == "RECEIVED":
        _cascade_chargeback(booking)
        if advisor is not None:
            calc.recompute_provisional(advisor)
    else:
        # PENDING stays PENDING: nothing was ever expected.
        calc.recompute_aging_for_booking(booking)
        if advisor is not None:
            calc.recompute_provisional(advisor)

    touch(booking)
    return ok(serialize(booking))


@bp.post("/bookings/<booking_id>/commission-receipt")
def record_commission_receipt(booking_id):
    caller = authenticate(("SupplierPortal",))
    body = read_body(("amount_cents", "received_on"))
    amount_cents = field_int(body, "amount_cents", minimum=0)
    received_on = field_dt(body, "received_on")

    booking = get_booking(booking_id)
    if booking["supplier_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if (booking["commission_status"] != "EXPECTED"
            or booking["booking_status"] not in ("CONFIRMED", "TRAVELED")):
        raise ApiError("ERR_INVALID_COMMISSION_STATE")

    if received_on < booking["created_at"]:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    if amount_cents > booking["expected_commission_cents"]:
        raise ApiError("ERR_RECEIPT_EXCEEDS_EXPECTED")

    booking["received_commission_cents"] = amount_cents
    booking["commission_received_on"] = received_on
    booking["shortfall_cents"] = (booking["expected_commission_cents"]
                                  - amount_cents)
    booking["commission_status"] = "RECEIVED"
    touch(booking)

    advisor = store.advisors.get(booking["advisor_id"])
    if advisor is not None:
        calc.recompute_final(advisor)
    calc.recompute_aging_for_booking(booking)
    return ok(serialize(booking))
