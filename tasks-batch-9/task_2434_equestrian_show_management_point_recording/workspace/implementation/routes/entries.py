"""Entry processing (the two parallel dimensions), class entries and compliance."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import serializers as ser
import services
import validate as v
from auth import endpoint, resolve_actor
from core import (
    CASE_TYPES,
    FINDINGS,
    class_entries_of_entry,
    db,
    find,
    new_row,
    now_clock,
    touch,
)
from errors import ApiError
from response import object_response

bp = Blueprint("entries", __name__)

TERMINAL_BLOCKING_CLASS_STATUSES = ("RESULTS_POSTED", "POINTS_SUBMITTED", "VOIDED")


def _owned(entry):
    """Ladder band 7."""
    if entry["rider_id"] != g.user_id:
        raise ApiError("ERR_ENTRY_NOT_OWNED")


def _coggins_and_eligibility(entry, show):
    horse = db.horses.get(entry["horse_id"])
    if horse is None:
        return
    if horse["coggins_expires_on"] < show["start_utc"]:
        raise ApiError("ERR_COGGINS_EXPIRED")
    if horse["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_HORSE_SUSPENDED")


@bp.post("/shows/<show_id>/entries")
@endpoint("Exhibitor")
def create_entry(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()

    raw = v.raw_body()
    rider_key = v.fk_candidate(raw, "rider_id")
    if rider_key is not None:
        find(db.riders, rider_key, "ERR_RIDER_NOT_FOUND")
    horse_key = v.fk_candidate(raw, "horse_id")
    if horse_key is not None:
        find(db.horses, horse_key, "ERR_HORSE_NOT_FOUND")

    payload = v.body()
    rider_id = v.req_str(payload, "rider_id")
    horse_id = v.req_str(payload, "horse_id")
    requested_stall_count = v.opt_int(payload, "requested_stall_count", default=0, minimum=0)

    find(db.riders, rider_id, "ERR_RIDER_NOT_FOUND")
    find(db.horses, horse_id, "ERR_HORSE_NOT_FOUND")

    if rider_id != g.user_id:
        raise ApiError("ERR_ENTRY_NOT_OWNED")
    if show["license_status"] != "APPROVED":
        raise ApiError("ERR_SHOW_LICENSE_NOT_APPROVED")
    if now_clock() >= show["entry_close_utc"]:
        raise ApiError("ERR_ENTRY_WINDOW_CLOSED")

    entry = new_row(
        db.entries,
        show_id=show["id"],
        rider_id=rider_id,
        horse_id=horse_id,
        verification_status="RECEIVED",
        settlement_status="UNBILLED",
        requested_stall_count=requested_stall_count,
        assigned_stall_count=0,
        class_fee_cents_total=0,
        stall_fee_cents=0,
        preliminary_subtotal_cents=0,
        office_fee_cents=0,
        total_due_cents=0,
        refunded_cents=0,
    )
    return object_response(ser.ser_entry(entry), 201)


@bp.post("/entries/<entry_id>/verify")
@endpoint("ShowSecretary")
def verify_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if entry["verification_status"] != "RECEIVED":
        raise ApiError("ERR_ENTRY_NOT_RECEIVED")

    show = db.shows.get(entry["show_id"])
    rider = db.riders.get(entry["rider_id"])
    if rider is not None and now_clock() >= rider["membership_expires_on"]:
        raise ApiError("ERR_RIDER_MEMBERSHIP_LAPSED")
    if show is not None:
        _coggins_and_eligibility(entry, show)

    entry["verification_status"] = "VERIFIED"
    touch(entry)
    return object_response(ser.ser_entry(entry))


@bp.post("/entries/<entry_id>/accept")
@endpoint("ShowSecretary")
def accept_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if entry["verification_status"] != "VERIFIED":
        raise ApiError("ERR_ENTRY_NOT_VERIFIED")

    show = db.shows.get(entry["show_id"])
    if show is not None:
        available = int(show["stall_capacity"]) - int(show["reserved_stall_count"])
        if int(entry["requested_stall_count"]) > available:
            raise ApiError("ERR_STALL_CAPACITY_EXCEEDED")

    entry["verification_status"] = "ACCEPTED"
    entry["assigned_stall_count"] = int(entry["requested_stall_count"])
    touch(entry)
    if show is not None:
        services.recompute_show_stalls(show)
        touch(show)
    services.confirmation_join(entry)
    return object_response(ser.ser_entry(entry))


@bp.post("/entries/<entry_id>/invoice")
@endpoint("ShowSecretary")
def invoice_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if entry["verification_status"] == "WITHDRAWN":
        raise ApiError("ERR_ENTRY_ALREADY_TERMINAL")
    if entry["settlement_status"] != "UNBILLED":
        raise ApiError("ERR_ENTRY_ALREADY_INVOICED")

    show = db.shows.get(entry["show_id"])
    class_fee_total = 0
    for class_entry in class_entries_of_entry(entry["id"]):
        if class_entry["status"] not in calc.BILLABLE_CLASS_ENTRY_STATUSES:
            continue
        cls = db.classes.get(class_entry["class_id"])
        if cls is not None:
            class_fee_total += int(cls["entry_fee_cents"])

    stall_fee = int(entry["requested_stall_count"]) * (
        int(show["stall_fee_cents"]) if show is not None else 0
    )
    preliminary = class_fee_total + stall_fee
    office_fee = calc.office_fee_for(preliminary)

    entry["class_fee_cents_total"] = class_fee_total
    entry["stall_fee_cents"] = stall_fee
    entry["preliminary_subtotal_cents"] = preliminary
    entry["office_fee_cents"] = office_fee
    entry["total_due_cents"] = preliminary + office_fee
    entry["settlement_status"] = "INVOICED"
    touch(entry)
    return object_response(ser.ser_entry(entry))


@bp.post("/entries/<entry_id>/payment")
@endpoint("Exhibitor")
def pay_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    resolve_actor()
    payload = v.body()
    amount_cents = v.req_int(payload, "amount_cents", minimum=0)
    _owned(entry)

    if entry["settlement_status"] != "INVOICED":
        raise ApiError("ERR_ENTRY_NOT_INVOICED")
    if amount_cents != int(entry["total_due_cents"]):
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    entry["settlement_status"] = "PAID"
    touch(entry)
    services.confirmation_join(entry)
    return object_response(ser.ser_entry(entry))


@bp.post("/entries/<entry_id>/withdrawal")
@endpoint("Exhibitor")
def withdraw_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    resolve_actor()
    _owned(entry)

    if entry["verification_status"] not in ("RECEIVED", "VERIFIED", "ACCEPTED"):
        raise ApiError("ERR_ENTRY_ALREADY_TERMINAL")
    for class_entry in class_entries_of_entry(entry["id"]):
        if class_entry["status"] == "DISQUALIFIED":
            raise ApiError("ERR_ENTRY_ALREADY_TERMINAL")
        if class_entry["status"] == "COMPLETED":
            cls = db.classes.get(class_entry["class_id"])
            if cls is not None and cls["status"] in TERMINAL_BLOCKING_CLASS_STATUSES:
                raise ApiError("ERR_ENTRY_ALREADY_TERMINAL")

    entry["verification_status"] = "WITHDRAWN"
    entry["assigned_stall_count"] = 0
    if entry["settlement_status"] == "PAID":
        entry["settlement_status"] = "REFUNDED"
        entry["refunded_cents"] = int(entry["total_due_cents"])
    touch(entry)

    show = db.shows.get(entry["show_id"])
    if show is not None:
        services.recompute_show_stalls(show)
        touch(show)
    services.scratch_class_entries(entry)
    return object_response(ser.ser_entry(entry))


@bp.post("/class-entries")
@endpoint("Exhibitor")
def create_class_entry():
    resolve_actor()

    raw = v.raw_body()
    entry_key = v.fk_candidate(raw, "entry_id")
    if entry_key is not None:
        find(db.entries, entry_key, "ERR_ENTRY_NOT_FOUND")
    class_key = v.fk_candidate(raw, "class_id")
    if class_key is not None:
        find(db.classes, class_key, "ERR_CLASS_NOT_FOUND")

    payload = v.body()
    entry_id = v.req_str(payload, "entry_id")
    class_id = v.req_str(payload, "class_id")

    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    _owned(entry)

    if cls["status"] != "OPEN":
        raise ApiError("ERR_CLASS_NOT_OPEN")

    show = db.shows.get(entry["show_id"])
    if show is not None:
        _coggins_and_eligibility(entry, show)
        if now_clock() >= show["entry_close_utc"]:
            raise ApiError("ERR_ENTRY_WINDOW_CLOSED")

    if int(cls["entry_count"]) >= int(cls["max_entries"]):
        raise ApiError("ERR_CLASS_FULL")
    for existing in class_entries_of_entry(entry["id"]):
        if existing["class_id"] == cls["id"] and existing["status"] in (
            "ENTERED",
            "CONFIRMED",
            "COMPLETED",
            "DISQUALIFIED",
        ):
            raise ApiError("ERR_DUPLICATE_CLASS_ENTRY")

    confirmed = (
        entry["verification_status"] == "ACCEPTED" and entry["settlement_status"] == "PAID"
    )
    class_entry = new_row(
        db.class_entries,
        entry_id=entry["id"],
        class_id=cls["id"],
        status="CONFIRMED" if confirmed else "ENTERED",
        placing=None,
        round_seconds=None,
        prize_cents=0,
        points_national=Decimal("0.0"),
        points_regional=0,
    )
    touch(cls)
    services.recompute_class_counts(cls)
    return object_response(ser.ser_class_entry(class_entry), 201)


@bp.post("/entries/<entry_id>/compliance-cases")
@endpoint("Steward")
def open_compliance_case(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    resolve_actor()

    raw = v.raw_body()
    official_key = v.fk_candidate(raw, "opened_by_official_id")
    if official_key is not None:
        find(db.officials, official_key, "ERR_OFFICIAL_NOT_FOUND")

    payload = v.body()
    opened_by_official_id = v.req_str(payload, "opened_by_official_id")
    case_type = v.req_enum(payload, "case_type", CASE_TYPES)
    sample_code = v.opt_str(payload, "sample_code")
    welfare_rule_code = v.opt_str(payload, "welfare_rule_code")

    find(db.officials, opened_by_official_id, "ERR_OFFICIAL_NOT_FOUND")

    if case_type == "DRUG_TEST":
        if not sample_code:
            raise ApiError("ERR_INVALID_REQUEST", "A drug test requires 'sample_code'.")
        if welfare_rule_code is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "A drug test must not carry 'welfare_rule_code'."
            )
    else:
        if not welfare_rule_code:
            raise ApiError(
                "ERR_INVALID_REQUEST", "A welfare citation requires 'welfare_rule_code'."
            )
        if sample_code is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "A welfare citation must not carry 'sample_code'."
            )

    case = new_row(
        db.cases,
        entry_id=entry["id"],
        opened_by_official_id=opened_by_official_id,
        case_type=case_type,
        sample_code=sample_code,
        welfare_rule_code=welfare_rule_code,
        finding=None,
        status="OPEN",
    )
    return object_response(ser.ser_case(case), 201)


@bp.post("/compliance-cases/<case_id>/finding")
@endpoint("FederationOfficer")
def adjudicate_case(case_id):
    case = find(db.cases, case_id, "ERR_COMPLIANCE_CASE_NOT_FOUND")
    payload = v.body()
    finding = v.req_enum(payload, "finding", FINDINGS)

    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_ALREADY_ADJUDICATED")

    if finding == "WARNING" and case["case_type"] != "WELFARE_CITATION":
        raise ApiError("ERR_FINDING_NOT_APPLICABLE")

    entry = db.entries.get(case["entry_id"])
    show = db.shows.get(entry["show_id"]) if entry is not None else None

    case["finding"] = finding
    if finding == "NEGATIVE":
        case["status"] = "DISMISSED"
        touch(case)
        return object_response(ser.ser_case(case))

    case["status"] = "SUBSTANTIATED"
    touch(case)

    if finding == "WARNING":
        if show is not None:
            services.recompute_welfare_strikes(show)
            touch(show)
        return object_response(ser.ser_case(case))

    if entry is not None and show is not None:
        services.positive_finding_cascade(entry, show)
        if case["case_type"] == "WELFARE_CITATION":
            services.recompute_welfare_strikes(show)
        touch(show)
    return object_response(ser.ser_case(case))
