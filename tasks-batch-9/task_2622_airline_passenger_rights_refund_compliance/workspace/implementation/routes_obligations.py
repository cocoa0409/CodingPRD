"""Refund obligations: valuation, headroom, election and settlement (PRD 3.6, 3.7)."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, PASSENGER, authorize, own_obligation
from envelope import created, listing, ok
from errors import ApiError
from store import S, serialize, touch
from validation import (
    body_fk,
    field,
    json_body,
    must_exist,
    page,
    pagination,
    validate,
)

bp = Blueprint("obligations", __name__)

BASES = ["FARE", "ANCILLARY", "BAGGAGE_FEE", "DENIED_BOARDING", "GOODWILL_GRANT"]
ISSUANCE_MODES = ["PROACTIVE", "REQUEST_BASED"]

# basis -> (source body field, entity kind for existence lookup)
BASIS_SOURCE = {
    "FARE": ("flight_segment_id", "flight_segment"),
    "BAGGAGE_FEE": ("checked_bag_id", "checked_bag"),
    "ANCILLARY": ("ancillary_purchase_id", "ancillary_purchase"),
    "DENIED_BOARDING": ("denied_boarding_record_id", "denied_boarding_record"),
    "GOODWILL_GRANT": (None, None),
}

CREATE_SPEC = [
    field("booking_id", "string", True),
    field("basis", "enum", True, values=BASES),
    field("issuance_mode", "enum", True, values=ISSUANCE_MODES),
    field("expected_booking_version", "int", True, min=0),
    field("flight_segment_id", "string", False),
    field("checked_bag_id", "string", False),
    field("ancillary_purchase_id", "string", False),
    field("denied_boarding_record_id", "string", False),
    # PRD 3.6 names this instant for a request-based create; the scaffold input list
    # omits it, so it is accepted as optional and falls back to the logical clock.
    field("request_received_utc", "datetime", False),
]


def _source_start(basis, source_row):
    """obligation_start_utc by basis (PRD 3.6 / refund_deadline_resolution)."""
    if source_row is None:
        return None
    if basis == "FARE":
        return source_row["disruption_declared_at_utc"]
    if basis == "BAGGAGE_FEE":
        if source_row["delivered_at_utc"] is not None:
            return source_row["delivered_at_utc"]
        return source_row["loss_declared_at_utc"]
    if basis == "ANCILLARY":
        return source_row.get("_occurred_at_utc")
    if basis == "DENIED_BOARDING":
        return source_row["finalized_at_utc"]
    return None


def _gross_and_variant(basis, issuance_mode, booking, source_row):
    if basis == "FARE":
        if issuance_mode == "PROACTIVE":
            return calc.fare_gross_proactive(booking), "PROACTIVE_FULL_ITINERARY"
        return calc.fare_gross_request_based(booking), "REQUEST_BASED_UNUSED_PRORATION"
    if basis == "ANCILLARY":
        return source_row["amount_cents"], "FEE_FACE_VALUE"
    if basis == "BAGGAGE_FEE":
        return source_row["fee_cents"], "FEE_FACE_VALUE"
    if basis == "DENIED_BOARDING":
        variant = (
            "VOLUNTARY_NEGOTIATED"
            if source_row["effective_category"] == "VOLUNTARY"
            else "INVOLUNTARY_STATUTORY"
        )
        return source_row["compensation_cents"], variant
    # GOODWILL_GRANT has no source charge on a direct create.
    return 0, "GOODWILL_GRANT_AMOUNT"


@bp.post("/compliance/refund-obligations")
def create_obligation():
    user_id, role = authorize([OFFICER, ADMIN])
    body = json_body()

    # Step 5: body foreign keys, in the order the endpoint lists them.
    booking = body_fk(body, "booking_id", "booking")
    resolved = {
        "flight_segment_id": body_fk(body, "flight_segment_id", "flight_segment"),
        "checked_bag_id": body_fk(body, "checked_bag_id", "checked_bag"),
        "ancillary_purchase_id": body_fk(body, "ancillary_purchase_id", "ancillary_purchase"),
        "denied_boarding_record_id": body_fk(
            body, "denied_boarding_record_id", "denied_boarding_record"
        ),
    }
    data = validate(body, CREATE_SPEC)

    # Step 9: the ledger-parent version guard (PRD 2.6).
    if data["expected_booking_version"] != booking["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION")

    basis = data["basis"]
    issuance_mode = data["issuance_mode"]
    source_field, source_kind = BASIS_SOURCE[basis]
    source_id = data.get(source_field) if source_field else None

    # Step 15: at most one non-voided obligation per (basis, source row).
    if source_field is not None and source_id is not None:
        if ledger.any_live_obligation_for_source(basis, source_field, source_id) is not None:
            raise ApiError("ERR_DUPLICATE_OBLIGATION_FOR_SOURCE")

    # Step 16: referential consistency, narrowest first.
    segment = resolved["flight_segment_id"]
    if segment is not None and segment["booking_id"] != booking["id"]:
        raise ApiError("ERR_SEGMENT_BOOKING_MISMATCH")

    supplied = [name for name in ledger.SOURCE_FIELDS if data.get(name) is not None]
    if source_field is None:
        if supplied:
            raise ApiError("ERR_BASIS_REFERENCE_MISMATCH")
    elif supplied != [source_field]:
        raise ApiError("ERR_BASIS_REFERENCE_MISMATCH")

    source_row = resolved[source_field] if source_field else None
    if source_row is not None and source_row["booking_id"] != booking["id"]:
        raise ApiError("ERR_BASIS_REFERENCE_MISMATCH")

    gross, variant = _gross_and_variant(basis, issuance_mode, booking, source_row)
    start = _source_start(basis, source_row)
    if start is None:
        start = data.get("request_received_utc")

    # Step 17: fiscal checks last.
    row = ledger.mint_obligation(
        booking,
        basis,
        issuance_mode,
        variant,
        gross,
        start,
        source_field=source_field,
        source_id=source_id,
        created_by_user_id=user_id,
    )
    ledger.bump_booking(booking)
    return created(serialize(row))


LIST_FILTERS = (
    "booking_id",
    "flight_segment_id",
    "checked_bag_id",
    "ancillary_purchase_id",
    "denied_boarding_record_id",
    "basis",
    "issuance_mode",
    "election_status",
    "settlement_status",
)


@bp.get("/compliance/refund-obligations")
def list_obligations():
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    limit, offset = pagination()
    rows = sorted(S.refund_obligations.values(), key=lambda r: r["_seq"])
    if role == PASSENGER:
        own = set(
            b["id"] for b in S.bookings.values() if b["passenger_id"] == user_id
        )
        rows = [r for r in rows if r["booking_id"] in own]
    for param in LIST_FILTERS:
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/refund-obligations/<obligation_id>")
def read_obligation(obligation_id):
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    own_obligation(user_id, role, obligation_id)
    return ok(serialize(must_exist("refund_obligation", obligation_id)))


ELECT_SPEC = [
    field("election", "enum", True, values=["CASH", "TRAVEL_CREDIT"]),
    field("consent_complaint_id", "string", False),
]


@bp.post("/compliance/refund-obligations/<obligation_id>/elect")
def elect(obligation_id):
    user_id, role = authorize([PASSENGER, OFFICER, ADMIN])
    own_obligation(user_id, role, obligation_id)
    obligation = must_exist("refund_obligation", obligation_id)
    body = json_body()
    consent = body_fk(body, "consent_complaint_id", "consumer_complaint")
    data = validate(body, ELECT_SPEC)

    if (
        obligation["election_status"] != "PENDING_ELECTION"
        or obligation["settlement_status"] != "UNSETTLED"
    ):
        raise ApiError("ERR_OBLIGATION_STATE_INVALID")

    election = data["election"]
    if election == "TRAVEL_CREDIT" and role != PASSENGER and consent is None:
        raise ApiError("ERR_CREDIT_CONSENT_REQUIRED")
    if consent is not None and consent["booking_id"] != obligation["booking_id"]:
        raise ApiError("ERR_CONSENT_REFERENCE_MISMATCH")

    booking = S.bookings[obligation["booking_id"]]
    policy = calc.policy_of(booking)

    if election == "CASH":
        obligation["election_status"] = "ELECTED_CASH"
        obligation["credit_bonus_cents"] = 0
        obligation["payable_total_cents"] = obligation["amount_cents"]
        obligation["settlement_method"] = calc.settlement_method_for("CASH", booking)
    else:
        bonus = calc.credit_bonus(obligation["amount_cents"], policy)
        obligation["election_status"] = "ELECTED_CREDIT"
        obligation["credit_bonus_cents"] = bonus
        obligation["payable_total_cents"] = obligation["amount_cents"] + bonus
        obligation["settlement_method"] = "TRAVEL_CREDIT"

    obligation["election_source"] = (
        "PASSENGER" if role == PASSENGER else "OFFICER_ON_BEHALF"
    )
    if consent is not None:
        obligation["credit_consent_reference"] = consent["id"]
    touch(obligation)
    return ok(serialize(obligation))


INITIATE_SPEC = [field("processor_reference", "string", True, min_len=1, max_len=200)]


@bp.post("/compliance/refund-obligations/<obligation_id>/initiate-settlement")
def initiate_settlement(obligation_id):
    user_id, role = authorize([OFFICER])
    obligation = must_exist("refund_obligation", obligation_id)
    body = json_body()
    validate(body, INITIATE_SPEC)

    if obligation["settlement_status"] not in ("UNSETTLED", "FAILED"):
        raise ApiError("ERR_OBLIGATION_STATE_INVALID")
    if obligation["election_status"] == "PENDING_ELECTION":
        raise ApiError("ERR_ELECTION_REQUIRED")

    if obligation["basis"] == "FARE":
        segment = S.flight_segments.get(obligation["flight_segment_id"])
        if segment is not None:
            still_disrupted = segment["status"] in ("CANCELLED", "DISRUPTED_UNUSED") or (
                segment["status"] == "DELAYED" and segment["is_significant_delay"]
            )
            if not still_disrupted:
                raise ApiError("ERR_SOURCE_DISRUPTION_RESCINDED")

    if obligation["created_by_user_id"] is not None and (
        user_id == obligation["created_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    obligation["settlement_status"] = "INITIATED"
    obligation["settlement_attempt_count"] += 1
    obligation["settlement_initiated_at_utc"] = S.now()
    obligation["settlement_initiated_by_user_id"] = user_id
    touch(obligation)
    return ok(serialize(obligation))


COMPLETE_SPEC = [
    field("outcome", "enum", True, values=["SUCCEEDED", "FAILED"]),
    field(
        "failure_reason",
        "enum",
        False,
        values=["CARD_DECLINED", "ACCOUNT_CLOSED", "PROCESSOR_TIMEOUT"],
    ),
]


@bp.post("/compliance/refund-obligations/<obligation_id>/complete-settlement")
def complete_settlement(obligation_id):
    user_id, role = authorize([OFFICER, ADMIN])
    obligation = must_exist("refund_obligation", obligation_id)
    body = json_body()
    data = validate(body, COMPLETE_SPEC)

    outcome = data["outcome"]
    if outcome == "FAILED" and data.get("failure_reason") is None:
        raise ApiError("ERR_FAILURE_REASON_REQUIRED")

    if obligation["settlement_status"] != "INITIATED":
        raise ApiError("ERR_OBLIGATION_STATE_INVALID")

    if obligation["settlement_initiated_by_user_id"] is not None and (
        user_id == obligation["settlement_initiated_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    booking = S.bookings[obligation["booking_id"]]

    if outcome == "SUCCEEDED":
        obligation["settlement_status"] = "SETTLED"
        obligation["settled_at_utc"] = S.now()
        touch(obligation)
        if obligation["settlement_method"] == "TRAVEL_CREDIT":
            passenger = ledger.passenger_of(booking)
            if passenger is not None:
                ledger.recompute_credit_balance(passenger)
                touch(passenger)
        ledger.bump_booking(booking)
    else:
        obligation["settlement_status"] = "FAILED"
        obligation["last_failure_reason"] = data["failure_reason"]
        obligation["settlement_initiated_by_user_id"] = None
        touch(obligation)
        # Failing to pay does not extinguish the debt, so no booking field moves
        # and the booking's version is left alone (PRD 3.7).

    return ok(serialize(obligation))


VOID_SPEC = [
    field(
        "void_reason",
        "enum",
        True,
        values=["CREATED_IN_ERROR", "DUPLICATE", "PASSENGER_WITHDREW", "SETTLEMENT_REVERSED"],
    )
]

ORDINARY_VOID_REASONS = ("CREATED_IN_ERROR", "DUPLICATE", "PASSENGER_WITHDREW")


@bp.post("/compliance/refund-obligations/<obligation_id>/void")
def void_obligation(obligation_id):
    authorize([ADMIN])
    obligation = must_exist("refund_obligation", obligation_id)
    body = json_body()
    data = validate(body, VOID_SPEC)
    reason = data["void_reason"]
    prior = obligation["settlement_status"]

    if prior == "INITIATED":
        raise ApiError("ERR_OBLIGATION_STATE_INVALID")
    if prior == "VOIDED":
        raise ApiError("ERR_OBLIGATION_NOT_VOIDABLE")
    if prior == "SETTLED" and reason != "SETTLEMENT_REVERSED":
        raise ApiError("ERR_OBLIGATION_NOT_VOIDABLE")
    if prior in ("UNSETTLED", "FAILED") and reason == "SETTLEMENT_REVERSED":
        raise ApiError("ERR_OBLIGATION_NOT_VOIDABLE")

    booking = S.bookings[obligation["booking_id"]]
    obligation["settlement_status"] = "VOIDED"
    obligation["void_reason"] = reason
    touch(obligation)

    if reason == "CREATED_IN_ERROR" and obligation["basis"] == "ANCILLARY":
        purchase = S.ancillary_purchases.get(obligation["ancillary_purchase_id"])
        if purchase is not None:
            purchase["delivery_status"] = "PENDING_DELIVERY"
            purchase["non_provision_reason"] = None
            purchase["refund_obligation_created"] = False
            purchase["_occurred_at_utc"] = None
            touch(purchase)

    if obligation["basis"] == "BAGGAGE_FEE":
        bag = S.checked_bags.get(obligation["checked_bag_id"])
        if bag is not None:
            bag["fee_refund_obligated"] = False
            touch(bag)

    if (
        reason == "SETTLEMENT_REVERSED"
        and prior == "SETTLED"
        and obligation["settlement_method"] == "TRAVEL_CREDIT"
    ):
        passenger = ledger.passenger_of(booking)
        if passenger is not None:
            ledger.recompute_credit_balance(passenger)
            touch(passenger)

    ledger.bump_booking(booking)
    return ok(serialize(obligation))
