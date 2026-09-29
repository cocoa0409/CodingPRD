"""Reservation intake, matching, confirmation and delivery outcomes."""

import random
import string
from datetime import date, timedelta

from flask import Blueprint

from db import clock, db
from errors import ApiError
from middleware import (
    assert_employee_scope,
    assert_provider_scope,
    auth,
    json_body,
)
from response import ok, paginate
from util import (
    D,
    hours_between,
    opt_str,
    parse_dt_value,
    present,
    req_enum,
    req_int_field,
    req_str,
    utc_date,
)

from services.calc import (
    billable_hours,
    cancellation_penalty,
    center_capacity_ok,
    charge_money,
    day_charge,
    entitlement_split,
    in_home_caregiver_ok,
    window_contained,
)
from services.cascade import apply_no_show
from services.core import (
    CENTER,
    CHECK_IN_LEAD_MINUTES,
    RESERVATION_TERMINAL,
    append_ledger,
    block_status,
    ledger_sorted,
    new_row,
    s_ledger,
    s_offer,
    s_reservation,
    sort_created,
    touch,
)
from services.invoice import invoice_lines
from services.matching import (
    credentials_ok_for_care_date,
    expire_offers,
    required_seats_for,
    run_match,
    selected_offer,
)
from services.core import s_invoice_line
from routes._common import (
    BILLING_STATUSES,
    FULFILLMENT_STATUSES,
    LEDGER_ENTRY_TYPES,
    LINE_TYPES,
    OFFER_STATUSES,
    REQUESTED_CARE_MODES,
    keep,
    need,
    qs_date,
    qs_enum,
    qs_str,
)

bp = Blueprint("reservations", __name__)

MAX_CARE_WINDOW_HOURS = D(14)
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _confirmation_code():
    return "CONF-" + "".join(random.choice(_CODE_ALPHABET) for _ in range(8))


def _assert_not_terminal(reservation):
    if reservation["fulfillment_status"] in RESERVATION_TERMINAL:
        raise ApiError("ERR_RESERVATION_TERMINAL")


def _plan(reservation):
    return db.benefit_plans.get(reservation["benefit_plan_id"])


def _provider(reservation):
    return db.providers.get(reservation["matched_provider_id"])


def _charge_pass(reservation, window_start, window_end):
    """Stages one to four of the charge arithmetic. Pure: writes nothing."""
    provider = _provider(reservation)
    plan = _plan(reservation)
    mode = provider["care_mode"]
    hours = billable_hours(mode, plan, window_start, window_end)
    days = day_charge(mode, reservation["dependent_count"], hours)
    covered, overage, multiplier = entitlement_split(reservation, days)
    money = charge_money(mode, plan, hours, covered, overage, days, multiplier)
    return {
        "hours": hours,
        "days": days,
        "covered_days": covered,
        "overage_days": overage,
        "multiplier": multiplier,
        "money": money,
    }


def _store_money(reservation, result):
    money = result["money"]
    reservation["covered_days"] = result["covered_days"]
    reservation["overage_days"] = result["overage_days"]
    reservation["overage_tier_multiplier"] = result["multiplier"]
    reservation["copay_cents"] = money["copay_cents"]
    reservation["overage_cents"] = money["overage_cents"]
    reservation["_covered_qty"] = money["covered_qty"]
    reservation["_overage_qty"] = money["overage_qty"]
    reservation["_copay_unit"] = money["copay_unit"]
    reservation["_overage_unit"] = money["overage_unit"]


# --------------------------------------------------------------------------- #
# intake
# --------------------------------------------------------------------------- #

def _dependent_ids(body):
    if "dependent_ids" not in body or body["dependent_ids"] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    value = body["dependent_ids"]
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_INVALID_REQUEST")
    seen = set()
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise ApiError("ERR_INVALID_REQUEST")
        if item in seen:
            raise ApiError("ERR_INVALID_REQUEST")
        seen.add(item)
    return list(value)


@bp.post("/reservations")
def create_reservation():
    body = json_body()
    employee_id = req_str(body, "employee_id")
    requested_care_mode = req_enum(body, "requested_care_mode", REQUESTED_CARE_MODES)
    market_code = req_str(body, "market_code", 16)
    if not present(body, "care_start_utc") or not present(body, "care_end_utc"):
        raise ApiError("ERR_INVALID_REQUEST")
    care_start = parse_dt_value(body["care_start_utc"])
    care_end = parse_dt_value(body["care_end_utc"])
    dependent_ids = _dependent_ids(body)
    if not care_end > care_start:
        raise ApiError("ERR_INVALID_WINDOW")

    user_id, role = auth("care_coordinator", "benefits_admin", "employee_user")
    assert_employee_scope(user_id, role, employee_id)

    employee = need(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    dependents = [
        need(db.dependents, dependent_id, "ERR_DEPENDENT_NOT_FOUND")
        for dependent_id in dependent_ids
    ]

    plan = db.benefit_plans.get(employee["benefit_plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    if not care_start > clock():
        raise ApiError("ERR_CARE_WINDOW_IN_PAST")
    if utc_date(care_start) != utc_date(care_end):
        raise ApiError("ERR_CARE_WINDOW_SPANS_DAYS")
    if hours_between(care_start, care_end) > MAX_CARE_WINDOW_HOURS:
        raise ApiError("ERR_CARE_WINDOW_SPANS_DAYS")

    for dependent in dependents:
        if dependent["employee_id"] != employee["id"]:
            raise ApiError("ERR_DEPENDENT_NOT_OWNED")

    from services.core import employee_eligibility

    if employee_eligibility(employee) != "ELIGIBLE":
        raise ApiError("ERR_EMPLOYEE_NOT_ELIGIBLE")

    if len(dependents) > plan["max_dependents_per_reservation"]:
        raise ApiError("ERR_TOO_MANY_DEPENDENTS")

    employer = db.employers.get(employee["employer_id"])
    for dependent in dependents:
        if dependent["status"] != "ACTIVE":
            raise ApiError("ERR_DEPENDENT_NOT_ELIGIBLE")
        if dependent["dependent_type"] not in plan["eligible_dependent_types"]:
            raise ApiError("ERR_DEPENDENT_NOT_ELIGIBLE")
        if dependent["dependent_type"] == "ADULT_ELDER" and not (
            employer is not None and employer["adult_elder_extension_enabled"]
        ):
            raise ApiError("ERR_DEPENDENT_NOT_ELIGIBLE")

    types = set(d["dependent_type"] for d in dependents)
    if types == {"CHILD"}:
        mix = "CHILD_ONLY"
    elif types == {"ADULT_ELDER"}:
        mix = "ADULT_ELDER_ONLY"
    else:
        mix = "MIXED"

    reservation = new_row(
        {
            "employee_id": employee["id"],
            "benefit_plan_id": plan["id"],
            "plan_version_pinned": plan["version"],
            "requested_care_mode": requested_care_mode,
            "market_code": market_code,
            "care_start_utc": care_start,
            "care_end_utc": care_end,
            "care_date": utc_date(care_start).isoformat(),
            "dependent_ids": list(dependent_ids),
            "dependent_count": len(dependent_ids),
            "dependent_type_mix": mix,
            "required_seats": required_seats_for(
                requested_care_mode if requested_care_mode == "CENTER_BASED" else "IN_HOME",
                len(dependent_ids),
            ),
            "fulfillment_status": "INTAKE",
            "billing_status": "NOT_BILLABLE",
            "matched_provider_id": None,
            "matched_capacity_block_id": None,
            "excluded_provider_ids": [],
            "billable_hours_provisional": D(0),
            "billable_hours_final": None,
            "days_charged_provisional": D(0),
            "days_charged_final": None,
            "covered_days": D(0),
            "overage_days": D(0),
            "overage_tier_multiplier": D(1),
            "copay_cents": 0,
            "overage_cents": 0,
            "penalty_cents": 0,
            "cancellation_deadline_utc": care_start
            - timedelta(hours=plan["cancellation_window_hours"]),
            "actual_start_utc": None,
            "actual_end_utc": None,
            "confirmation_code": None,
            "unfulfilled_reason_code": None,
            "cancel_reason_code": None,
        }
    )
    db.reservations[reservation["id"]] = reservation
    return ok(s_reservation(reservation), 201)


@bp.get("/reservations/<row_id>")
def get_reservation(row_id):
    user_id, role = auth(
        "network_admin",
        "benefits_admin",
        "care_coordinator",
        "provider_manager",
        "employee_user",
    )
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_employee_scope(user_id, role, reservation["employee_id"])
    return ok(s_reservation(reservation))


@bp.get("/reservations")
def list_reservations():
    auth("network_admin", "benefits_admin", "care_coordinator")
    employee_id = qs_str("employee_id")
    benefit_plan_id = qs_str("benefit_plan_id")
    matched_provider_id = qs_str("matched_provider_id")
    matched_capacity_block_id = qs_str("matched_capacity_block_id")
    dependent_id = qs_str("dependent_id")
    fulfillment_status = qs_enum("fulfillment_status", FULFILLMENT_STATUSES)
    billing_status = qs_enum("billing_status", BILLING_STATUSES)
    care_date = qs_date("care_date")
    market_code = qs_str("market_code")

    rows = sort_created(list(db.reservations.values()))
    rows = keep(rows, "employee_id", employee_id)
    rows = keep(rows, "benefit_plan_id", benefit_plan_id)
    rows = keep(rows, "matched_provider_id", matched_provider_id)
    rows = keep(rows, "matched_capacity_block_id", matched_capacity_block_id)
    rows = keep(rows, "fulfillment_status", fulfillment_status)
    rows = keep(rows, "billing_status", billing_status)
    rows = keep(rows, "care_date", care_date)
    rows = keep(rows, "market_code", market_code)
    if dependent_id is not None:
        rows = [r for r in rows if dependent_id in r["dependent_ids"]]
    return paginate(rows, s_reservation)


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #

@bp.post("/reservations/<row_id>/match")
def match_reservation(row_id):
    json_body()
    auth("care_coordinator")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    _assert_not_terminal(reservation)

    origin = reservation["fulfillment_status"]
    if origin not in ("INTAKE", "MATCHING", "UNFULFILLED"):
        raise ApiError("ERR_RESERVATION_STATE_INVALID")

    if origin in ("INTAKE", "MATCHING"):
        from services.core import employee_eligibility

        employee = db.employees.get(reservation["employee_id"])
        if employee is None or employee_eligibility(employee) != "ELIGIBLE":
            raise ApiError("ERR_EMPLOYEE_NOT_ELIGIBLE")
        plan = _plan(reservation)
        if plan is None or plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_NOT_ACTIVE")

    if not reservation["care_start_utc"] > clock():
        raise ApiError("ERR_CARE_WINDOW_IN_PAST")

    run_match(reservation)
    return ok(s_reservation(reservation))


@bp.post("/reservations/<row_id>/reject-offer")
def reject_offer(row_id):
    body = json_body()
    match_offer_id = req_str(body, "match_offer_id")
    reason_code = req_str(body, "reason_code", 80)

    user_id, role = auth("care_coordinator", "employee_user")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_employee_scope(user_id, role, reservation["employee_id"])
    offer = need(db.match_offers, match_offer_id, "ERR_MATCHOFFER_NOT_FOUND")

    _assert_not_terminal(reservation)
    if reservation["fulfillment_status"] != "OFFERED":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")

    if offer["offer_status"] == "EXPIRED" or clock() > offer["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED")
    if offer["reservation_id"] != reservation["id"]:
        raise ApiError("ERR_OFFER_RESERVATION_MISMATCH")
    if offer["offer_status"] != "SELECTED":
        raise ApiError("ERR_OFFER_NOT_SELECTED")

    offer["offer_status"] = "REJECTED"
    offer["reason_code"] = reason_code
    touch(offer)

    if offer["provider_id"] not in reservation["excluded_provider_ids"]:
        reservation["excluded_provider_ids"].append(offer["provider_id"])
    expire_offers(reservation["id"], ("PROPOSED",), "OFFER_BATCH_CLOSED")

    reservation["matched_provider_id"] = None
    reservation["fulfillment_status"] = "MATCHING"
    touch(reservation)
    return ok(s_reservation(reservation))


# --------------------------------------------------------------------------- #
# confirmation
# --------------------------------------------------------------------------- #

@bp.post("/reservations/<row_id>/confirm")
def confirm_reservation(row_id):
    body = json_body()
    capacity_block_id = req_str(body, "capacity_block_id")
    expected_version = req_int_field(body, "expected_capacity_block_version")

    auth("care_coordinator")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    block = need(db.capacity_blocks, capacity_block_id, "ERR_CAPACITYBLOCK_NOT_FOUND")

    if expected_version != block["version"]:
        raise ApiError("ERR_STALE_CAPACITY_BLOCK_VERSION")

    _assert_not_terminal(reservation)
    if reservation["fulfillment_status"] != "OFFERED":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    if block_status(block) != "OPEN":
        raise ApiError("ERR_BLOCK_NOT_OPEN")

    offer = selected_offer(reservation["id"])
    if offer is None or clock() > offer["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED")

    if block["provider_id"] != reservation["matched_provider_id"]:
        raise ApiError("ERR_BLOCK_PROVIDER_MISMATCH")

    provider = _provider(reservation)
    employee = db.employees.get(reservation["employee_id"])
    employer = db.employers.get(employee["employer_id"]) if employee else None

    result = _charge_pass(
        reservation, reservation["care_start_utc"], reservation["care_end_utc"]
    )
    if (
        employer is not None
        and not employer["overage_billing_enabled"]
        and result["overage_days"] > 0
    ):
        raise ApiError("ERR_OVERAGE_NOT_PERMITTED")

    if provider["care_mode"] == CENTER and not center_capacity_ok(block, reservation):
        raise ApiError("ERR_CAPACITY_EXHAUSTED")
    if block["service_date"] != reservation["care_date"] or not window_contained(
        block, reservation
    ):
        raise ApiError("ERR_WINDOW_OUTSIDE_BLOCK")
    if provider["care_mode"] != CENTER and not in_home_caregiver_ok(
        provider, reservation
    ):
        raise ApiError("ERR_CAREGIVER_WINDOW_CONFLICT")

    for other in db.reservations.values():
        if other["id"] == reservation["id"]:
            continue
        if other["employee_id"] != reservation["employee_id"]:
            continue
        if other["care_date"] != reservation["care_date"]:
            continue
        if other["fulfillment_status"] in ("CONFIRMED", "IN_SERVICE"):
            raise ApiError("ERR_DUPLICATE_CARE_DATE")

    care_date = date.fromisoformat(reservation["care_date"])
    if not credentials_ok_for_care_date(provider["id"], care_date):
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if provider["network_status"] not in ("CREDENTIALED", "PROBATION"):
        raise ApiError("ERR_PROVIDER_NOT_IN_NETWORK")
    if care_date == utc_date(clock()) and not provider["same_day_available"]:
        raise ApiError("ERR_SAME_DAY_UNAVAILABLE")

    reservation["matched_capacity_block_id"] = block["id"]
    reservation["confirmation_code"] = _confirmation_code()
    reservation["billable_hours_provisional"] = result["hours"]
    reservation["days_charged_provisional"] = result["days"]
    _store_money(reservation, result)
    reservation["fulfillment_status"] = "CONFIRMED"
    touch(reservation)

    append_ledger(
        reservation["employee_id"],
        reservation["id"],
        "RESERVE",
        result["days"],
        0,
        "CONFIRM",
    )
    expire_offers(reservation["id"], ("PROPOSED",), "CONFIRMED_ELSEWHERE")
    touch(block)
    return ok(s_reservation(reservation))


# --------------------------------------------------------------------------- #
# delivery outcomes
# --------------------------------------------------------------------------- #

@bp.post("/reservations/<row_id>/cancel")
def cancel_reservation(row_id):
    body = json_body()
    cancel_reason_code = req_str(body, "cancel_reason_code", 80)

    user_id, role = auth("care_coordinator", "benefits_admin", "employee_user")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_employee_scope(user_id, role, reservation["employee_id"])

    _assert_not_terminal(reservation)
    origin = reservation["fulfillment_status"]
    if origin not in ("INTAKE", "MATCHING", "OFFERED", "UNFULFILLED", "CONFIRMED"):
        raise ApiError("ERR_RESERVATION_STATE_INVALID")

    penalty, is_late = cancellation_penalty(reservation, origin)
    late_from_confirmed = is_late and origin == "CONFIRMED"

    reservation["cancel_reason_code"] = cancel_reason_code
    reservation["fulfillment_status"] = "CANCELLED"

    if origin == "OFFERED":
        expire_offers(
            reservation["id"], ("PROPOSED", "SELECTED"), "RESERVATION_CANCELLED"
        )
        reservation["matched_provider_id"] = None

    if origin == "CONFIRMED":
        reservation["penalty_cents"] = penalty
        if late_from_confirmed:
            reservation["billing_status"] = "ACCRUED"
        touch(reservation)
        append_ledger(
            reservation["employee_id"],
            reservation["id"],
            "RELEASE",
            -D(reservation["days_charged_provisional"]),
            0,
            "CANCEL",
        )
        if late_from_confirmed:
            append_ledger(
                reservation["employee_id"],
                reservation["id"],
                "LATE_CANCEL_CHARGE",
                0,
                penalty,
                "LATE_CANCEL",
            )
        block = db.capacity_blocks.get(reservation["matched_capacity_block_id"])
        if block is not None:
            touch(block)
    else:
        touch(reservation)

    return ok(s_reservation(reservation))


@bp.post("/reservations/<row_id>/check-in")
def check_in(row_id):
    json_body()
    user_id, role = auth("care_coordinator", "provider_manager")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_provider_scope(user_id, role, reservation["matched_provider_id"])

    _assert_not_terminal(reservation)
    if reservation["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")

    now = clock()
    opens = reservation["care_start_utc"] - timedelta(minutes=CHECK_IN_LEAD_MINUTES)
    if now < opens or now >= reservation["care_end_utc"]:
        raise ApiError("ERR_CHECK_IN_TOO_EARLY")

    provider = _provider(reservation)
    if provider is None or provider["network_status"] not in (
        "CREDENTIALED",
        "PROBATION",
    ):
        raise ApiError("ERR_PROVIDER_NOT_IN_NETWORK")

    reservation["fulfillment_status"] = "IN_SERVICE"
    touch(reservation)
    return ok(s_reservation(reservation))


@bp.post("/reservations/<row_id>/complete")
def complete_reservation(row_id):
    body = json_body()
    if not present(body, "actual_start_utc") or not present(body, "actual_end_utc"):
        raise ApiError("ERR_INVALID_REQUEST")
    actual_start = parse_dt_value(body["actual_start_utc"])
    actual_end = parse_dt_value(body["actual_end_utc"])

    user_id, role = auth("care_coordinator", "provider_manager")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_provider_scope(user_id, role, reservation["matched_provider_id"])

    _assert_not_terminal(reservation)
    if reservation["fulfillment_status"] != "IN_SERVICE":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")

    care_date = date.fromisoformat(reservation["care_date"])
    if not actual_end > actual_start:
        raise ApiError("ERR_INVALID_ACTUAL_WINDOW")
    if utc_date(actual_start) != care_date or utc_date(actual_end) != care_date:
        raise ApiError("ERR_INVALID_ACTUAL_WINDOW")
    if clock() < actual_end:
        raise ApiError("ERR_INVALID_ACTUAL_WINDOW")

    result = _charge_pass(reservation, actual_start, actual_end)

    provisional_days = D(reservation["days_charged_provisional"])
    reservation["actual_start_utc"] = actual_start
    reservation["actual_end_utc"] = actual_end
    reservation["billable_hours_final"] = result["hours"]
    reservation["days_charged_final"] = result["days"]
    _store_money(reservation, result)
    reservation["fulfillment_status"] = "COMPLETED"
    reservation["billing_status"] = "ACCRUED"
    touch(reservation)

    append_ledger(
        reservation["employee_id"],
        reservation["id"],
        "RELEASE",
        -provisional_days,
        0,
        "COMPLETE_RELEASE",
    )
    append_ledger(
        reservation["employee_id"],
        reservation["id"],
        "COMMIT",
        result["days"],
        0,
        "COMPLETE_COMMIT",
    )
    if result["overage_days"] > 0:
        append_ledger(
            reservation["employee_id"],
            reservation["id"],
            "OVERAGE_ACCRUE",
            0,
            result["money"]["overage_cents"],
            "COMPLETE_OVERAGE",
        )

    block = db.capacity_blocks.get(reservation["matched_capacity_block_id"])
    if block is not None:
        touch(block)
    return ok(s_reservation(reservation))


@bp.post("/reservations/<row_id>/no-show")
def no_show(row_id):
    body = json_body()
    reason_code = opt_str(body, "reason_code", 80)

    user_id, role = auth("care_coordinator", "provider_manager")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    assert_provider_scope(user_id, role, reservation["matched_provider_id"])

    _assert_not_terminal(reservation)
    if reservation["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    if clock() < reservation["care_start_utc"]:
        raise ApiError("ERR_NO_SHOW_TOO_EARLY")

    apply_no_show(reservation, reason_code)
    return ok(s_reservation(reservation))


# --------------------------------------------------------------------------- #
# reverse lookups
# --------------------------------------------------------------------------- #

@bp.get("/reservations/<row_id>/ledger-entries")
def reservation_ledger(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    entry_type = qs_enum("entry_type", LEDGER_ENTRY_TYPES)
    rows = ledger_sorted(
        [
            e
            for e in db.ledger_entries.values()
            if e["reservation_id"] == reservation["id"]
        ]
    )
    rows = keep(rows, "entry_type", entry_type)
    return paginate(rows, s_ledger)


@bp.get("/reservations/<row_id>/invoice-lines")
def reservation_invoice_lines(row_id):
    auth("network_admin", "benefits_admin")
    reservation = need(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND")
    line_type = qs_enum("line_type", LINE_TYPES)
    rows = sort_created(
        [
            l
            for l in db.invoice_lines.values()
            if l["reservation_id"] == reservation["id"]
        ]
    )
    rows = keep(rows, "line_type", line_type)
    return paginate(rows, s_invoice_line)


# --------------------------------------------------------------------------- #
# MatchOffer
# --------------------------------------------------------------------------- #

@bp.get("/match-offers/<row_id>")
def get_offer(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator", "employee_user")
    offer = need(db.match_offers, row_id, "ERR_MATCHOFFER_NOT_FOUND")
    return ok(s_offer(offer))


@bp.get("/match-offers")
def list_offers():
    auth("network_admin", "benefits_admin", "care_coordinator")
    reservation_id = qs_str("reservation_id")
    provider_id = qs_str("provider_id")
    offer_status = qs_enum("offer_status", OFFER_STATUSES)
    rows = sorted(
        db.match_offers.values(),
        key=lambda o: (o["rank_position"], o["created_at"], o["_seq"]),
    )
    rows = keep(rows, "reservation_id", reservation_id)
    rows = keep(rows, "provider_id", provider_id)
    rows = keep(rows, "offer_status", offer_status)
    return paginate(rows, s_offer)
