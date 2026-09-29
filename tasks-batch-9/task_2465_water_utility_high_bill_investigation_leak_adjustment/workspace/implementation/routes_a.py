"""Clock, rate schedules, billing periods, service accounts, meters and reads."""

from datetime import timedelta

from flask import Blueprint, g

import domain
from core import (
    ACCURACY_STATUSES,
    CREDIT_STATUSES,
    METER_TYPES,
    PERIOD_STATUSES,
    READ_TYPES,
    SEASONS,
    SERVICE_STATUSES,
    SHUTOFF_NOTICE_DAYS,
    Body,
    D,
    ENTRY_TYPES,
    SOURCE_KINDS,
    add_days,
    as_date,
    as_dt,
    base_record,
    clock_date,
    clock_now,
    created_response,
    date_str,
    err,
    endpoint,
    get_or_404,
    insert,
    iso,
    is_customer,
    list_result,
    maybe,
    object_response,
    parse_date,
    parse_dt,
    q_bool,
    q_enum,
    q_str,
    register_new,
    require_own_account,
    rows,
    serialize,
    store,
    touch,
)

bp = Blueprint("routes_a", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = Body()
    value = body.datetime("current_utc")
    store.clock = parse_dt(value)
    return object_response({"current_utc": value})


# ---------------------------------------------------------------------------
# RateSchedule
# ---------------------------------------------------------------------------
@bp.route("/rate-schedules", methods=["POST"])
@endpoint("SystemAdmin")
def create_rate_schedule():
    body = Body()
    code = body.string("code")
    base_charge_cents = body.integer("base_charge_cents", minimum=0)
    tier1_limit_gallons = body.integer("tier1_limit_gallons", minimum=1)
    tier1_rate = body.integer("tier1_rate_cents_per_kgal", minimum=1)
    tier2_limit_gallons = body.integer("tier2_limit_gallons", minimum=1)
    tier2_rate = body.integer("tier2_rate_cents_per_kgal", minimum=1)
    tier3_rate = body.integer("tier3_rate_cents_per_kgal", minimum=1)
    summer_surcharge_bp = body.integer("summer_surcharge_bp", minimum=0)
    sewer_rate = body.integer("sewer_rate_cents_per_kgal", minimum=1)
    sewer_cap_gallons = body.integer("sewer_cap_gallons", minimum=1)
    submeter_cap = body.integer("submeter_sewer_credit_cap_gallons", minimum=0)
    admin_fee_cents = body.integer("admin_fee_cents", minimum=0)
    waiver_threshold = body.integer("admin_fee_waiver_threshold_cents", minimum=0)

    if tier2_limit_gallons <= tier1_limit_gallons:
        err("ERR_INVALID_REQUEST", "tier2_limit_gallons must exceed tier1_limit_gallons")
    for existing in rows("rate_schedules"):
        if existing["code"] == code:
            err("ERR_INVALID_REQUEST", "code '%s' is already in use" % code)

    rec = base_record()
    rec.update(
        {
            "code": code,
            "base_charge_cents": base_charge_cents,
            "tier1_limit_gallons": tier1_limit_gallons,
            "tier1_rate_cents_per_kgal": tier1_rate,
            "tier2_limit_gallons": tier2_limit_gallons,
            "tier2_rate_cents_per_kgal": tier2_rate,
            "tier3_rate_cents_per_kgal": tier3_rate,
            "summer_surcharge_bp": summer_surcharge_bp,
            "sewer_rate_cents_per_kgal": sewer_rate,
            "sewer_cap_gallons": sewer_cap_gallons,
            "submeter_sewer_credit_cap_gallons": submeter_cap,
            "admin_fee_cents": admin_fee_cents,
            "admin_fee_waiver_threshold_cents": waiver_threshold,
        }
    )
    insert("rate_schedules", register_new(rec))
    return created_response(serialize(rec))


@bp.route("/rate-schedules", methods=["GET"])
@endpoint("SystemAdmin", "BillingSupervisor", "CustomerServiceRep")
def list_rate_schedules():
    code = q_str("code")
    result = [r for r in rows("rate_schedules") if code is None or r["code"] == code]
    return list_result(result)


@bp.route("/rate-schedules/<rid>", methods=["GET"])
@endpoint("SystemAdmin", "BillingSupervisor", "CustomerServiceRep")
def get_rate_schedule(rid):
    return object_response(serialize(get_or_404("rate_schedules", rid)))


# ---------------------------------------------------------------------------
# BillingPeriod
# ---------------------------------------------------------------------------
@bp.route("/billing-periods", methods=["POST"])
@endpoint("SystemAdmin")
def create_billing_period():
    body = Body()
    period_code = body.string("period_code")
    start_date = body.date("start_date")
    end_date = body.date("end_date")
    season = body.enum("season", SEASONS)
    rebilling_deadline_date = body.date("rebilling_deadline_date")

    if parse_date(end_date) < parse_date(start_date):
        err("ERR_INVALID_REQUEST", "end_date must not precede start_date")
    for existing in rows("billing_periods"):
        if existing["period_code"] == period_code:
            err("ERR_INVALID_REQUEST", "period_code '%s' is already in use" % period_code)

    start = parse_date(start_date)
    end = parse_date(end_date)
    for existing in rows("billing_periods"):
        if start <= as_date(existing["end_date"]) and as_date(existing["start_date"]) <= end:
            err(
                "ERR_BILLING_PERIOD_OVERLAP",
                "the date interval intersects billing period '%s'" % existing["period_code"],
            )

    rec = base_record()
    rec.update(
        {
            "period_code": period_code,
            "start_date": start_date,
            "end_date": end_date,
            "season": season,
            "rebilling_deadline_date": rebilling_deadline_date,
            "status": "OPEN",
        }
    )
    insert("billing_periods", register_new(rec))
    return created_response(serialize(rec))


@bp.route("/billing-periods", methods=["GET"])
@endpoint("SystemAdmin", "BillingSupervisor", "CustomerServiceRep", "Customer")
def list_billing_periods():
    season = q_enum("season", SEASONS)
    status = q_enum("status", PERIOD_STATUSES)
    period_code = q_str("period_code")
    result = []
    for rec in rows("billing_periods"):
        if season is not None and rec["season"] != season:
            continue
        if status is not None and rec["status"] != status:
            continue
        if period_code is not None and rec["period_code"] != period_code:
            continue
        result.append(rec)
    return list_result(result)


@bp.route("/billing-periods/<rid>", methods=["GET"])
@endpoint("SystemAdmin", "BillingSupervisor", "CustomerServiceRep", "Customer")
def get_billing_period(rid):
    return object_response(serialize(get_or_404("billing_periods", rid)))


@bp.route("/billing-periods/<rid>/close", methods=["POST"])
@endpoint("SystemAdmin")
def close_billing_period(rid):
    period = get_or_404("billing_periods", rid)
    if period["status"] != "OPEN":
        err("ERR_INVALID_STATE_TRANSITION", "only an OPEN period may be closed")
    period["status"] = "CLOSED"
    touch(period)
    return object_response(serialize(period))


@bp.route("/billing-periods/<rid>/lock", methods=["POST"])
@endpoint("SystemAdmin")
def lock_billing_period(rid):
    period = get_or_404("billing_periods", rid)
    if period["status"] != "CLOSED":
        err("ERR_INVALID_STATE_TRANSITION", "only a CLOSED period may be locked")
    period["status"] = "LOCKED"
    touch(period)
    return object_response(serialize(period))


# ---------------------------------------------------------------------------
# ServiceAccount
# ---------------------------------------------------------------------------
@bp.route("/service-accounts", methods=["POST"])
@endpoint("SystemAdmin", "CustomerServiceRep")
def create_service_account():
    body = Body()
    account_number = body.string("account_number")
    customer_name = body.string("customer_name")
    service_address = body.string("service_address")
    rate_schedule_id = body.string("rate_schedule_id")

    for existing in rows("service_accounts"):
        if existing["account_number"] == account_number:
            err(
                "ERR_INVALID_REQUEST",
                "account_number '%s' is already in use" % account_number,
            )
    get_or_404("rate_schedules", rate_schedule_id)

    rec = base_record()
    rec.update(
        {
            "account_number": account_number,
            "customer_name": customer_name,
            "service_address": service_address,
            "rate_schedule_id": rate_schedule_id,
            "service_status": "ACTIVE",
            "credit_status": "CURRENT",
            "balance_cents": 0,
            "shutoff_scheduled_for": None,
            "open_investigation_hold_count": 0,
            "open_rebill_count": 0,
        }
    )
    insert("service_accounts", register_new(rec))
    return created_response(serialize(rec))


@bp.route("/service-accounts", methods=["GET"])
@endpoint("SystemAdmin", "CustomerServiceRep", "BillingSupervisor")
def list_service_accounts():
    rate_schedule_id = q_str("rate_schedule_id")
    account_number = q_str("account_number")
    service_status = q_enum("service_status", SERVICE_STATUSES)
    credit_status = q_enum("credit_status", CREDIT_STATUSES)
    result = []
    for rec in rows("service_accounts"):
        if rate_schedule_id is not None and rec["rate_schedule_id"] != rate_schedule_id:
            continue
        if account_number is not None and rec["account_number"] != account_number:
            continue
        if service_status is not None and rec["service_status"] != service_status:
            continue
        if credit_status is not None and rec["credit_status"] != credit_status:
            continue
        result.append(rec)
    return list_result(result)


@bp.route("/service-accounts/<rid>", methods=["GET"])
@endpoint("SystemAdmin", "CustomerServiceRep", "BillingSupervisor", "Customer")
def get_service_account(rid):
    account = get_or_404("service_accounts", rid)
    require_own_account(account["id"])
    return object_response(serialize(account))


@bp.route("/service-accounts/<rid>/ledger-entries", methods=["GET"])
@endpoint("SystemAdmin", "CustomerServiceRep", "BillingSupervisor", "Customer")
def list_account_ledger(rid):
    account = get_or_404("service_accounts", rid)
    require_own_account(account["id"])
    entry_type = q_enum("entry_type", ENTRY_TYPES)
    source_kind = q_enum("source_kind", SOURCE_KINDS)
    result = []
    for entry in domain.ledger_of_account(account["id"]):
        if entry_type is not None and entry["entry_type"] != entry_type:
            continue
        if source_kind is not None and entry["source_kind"] != source_kind:
            continue
        result.append(entry)
    return list_result(result, key=domain.ledger_sort_key)


@bp.route("/service-accounts/<rid>/schedule-shutoff", methods=["POST"])
@endpoint("BillingSupervisor")
def schedule_shutoff(rid):
    account = get_or_404("service_accounts", rid)
    if account["service_status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "service_status must be ACTIVE")
    if account["credit_status"] not in ("PAST_DUE", "ARRANGEMENT_DEFAULTED"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "credit_status must be PAST_DUE or ARRANGEMENT_DEFAULTED",
        )
    account["service_status"] = "SHUTOFF_SCHEDULED"
    account["shutoff_scheduled_for"] = iso(
        clock_now() + timedelta(days=SHUTOFF_NOTICE_DAYS)
    )
    touch(account)
    return object_response(serialize(account))


@bp.route("/service-accounts/<rid>/execute-shutoff", methods=["POST"])
@endpoint("BillingSupervisor")
def execute_shutoff(rid):
    account = get_or_404("service_accounts", rid)
    if account["service_status"] != "SHUTOFF_SCHEDULED":
        err("ERR_INVALID_STATE_TRANSITION", "service_status must be SHUTOFF_SCHEDULED")
    if account["credit_status"] not in ("PAST_DUE", "ARRANGEMENT_DEFAULTED"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "credit_status must be PAST_DUE or ARRANGEMENT_DEFAULTED",
        )
    if (account["open_investigation_hold_count"] or 0) > 0 or (
        account["open_rebill_count"] or 0
    ) > 0:
        err("ERR_SHUTOFF_HOLD_ACTIVE", "an investigation or rebill hold is open")
    scheduled = as_dt(account["shutoff_scheduled_for"])
    if scheduled is not None and clock_now() < scheduled:
        err("ERR_SHUTOFF_NOTICE_NOT_ELAPSED", "the notice period has not elapsed")
    account["service_status"] = "SHUTOFF_EXECUTED"
    account["shutoff_scheduled_for"] = None
    touch(account)
    return object_response(serialize(account))


@bp.route("/service-accounts/<rid>/payments", methods=["POST"])
@endpoint("Customer", "CustomerServiceRep")
def record_account_payment(rid):
    body = Body()
    amount_cents = body.integer("amount_cents")
    memo = body.string("memo", required=False)
    account = get_or_404("service_accounts", rid)
    require_own_account(account["id"])
    if amount_cents <= 0:
        err("ERR_PAYMENT_AMOUNT_INVALID", "amount_cents must be greater than zero")

    entry = domain.add_ledger_entry(
        account,
        "PAYMENT",
        "CUSTOMER_PAYMENT",
        -amount_cents,
        bill_id=None,
        source_id=None,
        memo=memo,
    )
    domain.refresh_account(account)
    return created_response(serialize(entry))


# ---------------------------------------------------------------------------
# Meter
# ---------------------------------------------------------------------------
@bp.route("/meters", methods=["POST"])
@endpoint("SystemAdmin", "MeterTechnician")
def create_meter():
    body = Body()
    account_id = body.string("account_id")
    meter_serial = body.string("meter_serial")
    meter_type = body.enum("meter_type", METER_TYPES)
    size_inches = body.number("size_inches", exclusive_min=0)
    initial_register_value = body.integer("initial_register_value", minimum=0)
    parent_meter_id = body.string("parent_meter_id", required=False)

    for existing in rows("meters"):
        if existing["meter_serial"] == meter_serial:
            err("ERR_INVALID_REQUEST", "meter_serial '%s' is already in use" % meter_serial)

    account = get_or_404("service_accounts", account_id)
    parent = None
    if parent_meter_id is not None:
        parent = get_or_404("meters", parent_meter_id)

    if meter_type == "POTABLE_MASTER":
        if parent_meter_id is not None:
            err(
                "ERR_SUBMETER_PARENT_INVALID",
                "parent_meter_id must be null for a POTABLE_MASTER meter",
            )
    else:
        if parent is None:
            err(
                "ERR_SUBMETER_PARENT_INVALID",
                "parent_meter_id is required for %s" % meter_type,
            )
        if parent["meter_type"] != "POTABLE_MASTER":
            err("ERR_SUBMETER_PARENT_INVALID", "parent must be a POTABLE_MASTER meter")
        if parent["account_id"] != account_id:
            err(
                "ERR_SUBMETER_PARENT_INVALID",
                "parent meter must belong to the same service account",
            )

    rec = base_record()
    rec.update(
        {
            "account_id": account["id"],
            "meter_serial": meter_serial,
            "meter_type": meter_type,
            "size_inches": size_inches,
            "initial_register_value": initial_register_value,
            "parent_meter_id": parent_meter_id,
            "accuracy_status": "UNTESTED",
            "accuracy_pct": None,
            "correction_factor": None,
            "last_test_completed_at": None,
        }
    )
    insert("meters", register_new(rec))
    return created_response(serialize(rec))


@bp.route("/meters", methods=["GET"])
@endpoint("SystemAdmin", "MeterTechnician", "CustomerServiceRep", "BillingSupervisor", "Customer")
def list_meters():
    account_id = q_str("account_id")
    parent_meter_id = q_str("parent_meter_id")
    meter_type = q_enum("meter_type", METER_TYPES)
    accuracy_status = q_enum("accuracy_status", ACCURACY_STATUSES)
    if account_id is not None:
        require_own_account(account_id)
    if parent_meter_id is not None:
        parent = maybe("meters", parent_meter_id)
        if parent is not None:
            require_own_account(parent["account_id"])
    result = []
    for rec in rows("meters"):
        if account_id is not None and rec["account_id"] != account_id:
            continue
        if parent_meter_id is not None and rec.get("parent_meter_id") != parent_meter_id:
            continue
        if meter_type is not None and rec["meter_type"] != meter_type:
            continue
        if accuracy_status is not None and rec["accuracy_status"] != accuracy_status:
            continue
        result.append(rec)
    if is_customer():
        result = [r for r in result if r["account_id"] == g.user_id]
    return list_result(result)


@bp.route("/meters/<rid>", methods=["GET"])
@endpoint("SystemAdmin", "MeterTechnician", "CustomerServiceRep", "BillingSupervisor", "Customer")
def get_meter(rid):
    meter = get_or_404("meters", rid)
    require_own_account(meter["account_id"])
    return object_response(serialize(meter))


# ---------------------------------------------------------------------------
# MeterReading
# ---------------------------------------------------------------------------
@bp.route("/meter-readings", methods=["POST"])
@endpoint("MeterTechnician", "SystemAdmin")
def create_meter_reading():
    body = Body()
    meter_id = body.string("meter_id")
    read_date = body.date("read_date")
    read_type = body.enum("read_type", READ_TYPES)
    reading_value = body.integer("reading_value", minimum=0)
    corrects_reading_id = body.string("corrects_reading_id", required=False)

    if read_type == "CORRECTED" and corrects_reading_id is None:
        err("ERR_INVALID_REQUEST", "corrects_reading_id is required when read_type is CORRECTED")
    if read_type != "CORRECTED" and corrects_reading_id is not None:
        err(
            "ERR_INVALID_REQUEST",
            "corrects_reading_id is only permitted when read_type is CORRECTED",
        )

    meter = get_or_404("meters", meter_id)
    corrected = None
    if corrects_reading_id is not None:
        corrected = get_or_404("meter_readings", corrects_reading_id)

    day = parse_date(read_date)
    if read_type == "CORRECTED":
        period = domain.period_containing(day)
        if period is not None:
            if period["status"] == "LOCKED":
                err(
                    "ERR_BILLING_PERIOD_LOCKED",
                    "the billing period containing the affected bill is LOCKED",
                )
            if clock_date() > as_date(period["rebilling_deadline_date"]):
                err(
                    "ERR_REBILL_WINDOW_EXPIRED",
                    "the rebilling deadline for that period has passed",
                )
    if day > clock_date():
        err("ERR_READ_DATE_IN_FUTURE", "read_date must not be in the future")

    if read_type != "CORRECTED":
        latest = domain.latest_live_read(meter_id)
        floor_value = (
            int(latest["reading_value"]) if latest else int(meter["initial_register_value"])
        )
        if reading_value < floor_value:
            err(
                "ERR_NEGATIVE_CONSUMPTION",
                "reading_value must not regress below the latest live read",
            )

    consumption = domain.consumption_since_prior(meter, read_date, reading_value)

    rec = base_record()
    rec.update(
        {
            "meter_id": meter["id"],
            "read_date": read_date,
            "read_type": read_type,
            "reading_value": reading_value,
            "corrects_reading_id": corrects_reading_id,
            "superseded_by_reading_id": None,
            "consumption_since_prior_gallons": consumption,
        }
    )
    insert("meter_readings", register_new(rec))

    if corrected is not None:
        corrected["superseded_by_reading_id"] = rec["id"]
        touch(corrected)
        bill = domain.trigger_rebill_pending(meter, day)
        if bill is not None:
            account = maybe("service_accounts", bill["account_id"])
            if account is not None:
                domain.refresh_account(account)

    return created_response(serialize(rec))


@bp.route("/meter-readings", methods=["GET"])
@endpoint("MeterTechnician", "SystemAdmin", "CustomerServiceRep", "BillingSupervisor", "Customer")
def list_meter_readings():
    meter_id = q_str("meter_id")
    corrects_reading_id = q_str("corrects_reading_id")
    superseded_by_reading_id = q_str("superseded_by_reading_id")
    read_type = q_enum("read_type", READ_TYPES)
    live_only = q_bool("live_only")
    if meter_id is not None:
        meter = maybe("meters", meter_id)
        if meter is not None:
            require_own_account(meter["account_id"])

    result = []
    for rec in rows("meter_readings"):
        if meter_id is not None and rec["meter_id"] != meter_id:
            continue
        if corrects_reading_id is not None and rec.get("corrects_reading_id") != corrects_reading_id:
            continue
        if (
            superseded_by_reading_id is not None
            and rec.get("superseded_by_reading_id") != superseded_by_reading_id
        ):
            continue
        if read_type is not None and rec["read_type"] != read_type:
            continue
        if live_only is True and rec.get("superseded_by_reading_id") is not None:
            continue
        if live_only is False and rec.get("superseded_by_reading_id") is None:
            continue
        result.append(rec)
    if is_customer():
        owned = set(m["id"] for m in rows("meters") if m["account_id"] == g.user_id)
        result = [r for r in result if r["meter_id"] in owned]
    return list_result(result, key=domain.reading_sort_key)


@bp.route("/meter-readings/<rid>", methods=["GET"])
@endpoint("MeterTechnician", "SystemAdmin", "CustomerServiceRep", "BillingSupervisor", "Customer")
def get_meter_reading(rid):
    reading = get_or_404("meter_readings", rid)
    meter = maybe("meters", reading["meter_id"])
    if meter is not None:
        require_own_account(meter["account_id"])
    return object_response(serialize(reading))
