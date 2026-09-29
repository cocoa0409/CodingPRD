"""Reference data, dealer enrollment, analytics and the logical clock."""

import re

import db
import response
import util
from middleware import (
    ADJUDICATION_MANAGER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    DEALER_WARRANTY_ADMIN,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
    auth,
    fetch,
    scope,
)
from routes.common import (
    ALL_ROLES,
    MANUFACTURER_ROLES,
    apply_filters,
    one_decimal,
    resolve_fk,
    str_filter,
    two_decimals,
    unique_or_reject,
)
from services import calc

from flask import Blueprint

bp = Blueprint("reference", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------- state law profiles
@bp.post("/warranty/state-law-profiles")
def create_state_law_profile():
    auth(WARRANTY_ADMIN)
    data = util.body()
    state_code = util.get_str(data, "state_code")
    if not STATE_CODE_RE.match(state_code):
        util.bad("Field 'state_code' must be exactly two uppercase letters.")
    markup_cap_pct = two_decimals(util.get_dec(data, "markup_cap_pct", minimum=0, maximum=1), "markup_cap_pct")
    labor_rate_method = util.get_enum(data, "labor_rate_method", ("RETAIL_SAMPLE", "TIME_AND_PRICE"))
    min_sample_repair_orders = util.get_int(data, "min_sample_repair_orders", minimum=0)
    max_labor_rate_cents = util.get_int(data, "max_labor_rate_cents", minimum=1)
    deemed_approved_days = util.get_int(data, "deemed_approved_days", minimum=1)
    appeal_window_days = util.get_int(data, "appeal_window_days", minimum=1)
    unique_or_reject(db.state_law_profiles, "state_code", state_code)
    record = db.new_record(
        db.state_law_profiles,
        versioned=False,
        state_code=state_code,
        markup_cap_pct=markup_cap_pct,
        labor_rate_method=labor_rate_method,
        min_sample_repair_orders=min_sample_repair_orders,
        max_labor_rate_cents=max_labor_rate_cents,
        deemed_approved_days=deemed_approved_days,
        appeal_window_days=appeal_window_days,
    )
    return response.created(record)


@bp.get("/warranty/state-law-profiles/<profile_id>")
def read_state_law_profile(profile_id):
    auth(*MANUFACTURER_ROLES)
    record = fetch(db.state_law_profiles, profile_id, "ERR_STATE_LAW_PROFILE_NOT_FOUND")
    return response.ok(record)


# ---------------------------------------------------------------- dealers
@bp.post("/warranty/dealers")
def create_dealer():
    auth(WARRANTY_ADMIN)
    data = util.body()
    resolve_fk(data, "state_law_profile_id", db.state_law_profiles, "ERR_STATE_LAW_PROFILE_NOT_FOUND")
    dealer_code = util.get_str(data, "dealer_code")
    name = util.get_str(data, "name")
    state_law_profile_id = util.get_str(data, "state_law_profile_id")
    vehicles_in_operation = util.get_int(data, "vehicles_in_operation", minimum=0)
    initial_labor_rate_cents = util.get_int(data, "initial_labor_rate_cents", minimum=1)
    initial_parts_markup_pct = two_decimals(
        util.get_dec(data, "initial_parts_markup_pct", minimum=0, maximum=1), "initial_parts_markup_pct"
    )
    unique_or_reject(db.dealers, "dealer_code", dealer_code)
    record = db.new_record(
        db.dealers,
        dealer_code=dealer_code,
        name=name,
        state_law_profile_id=state_law_profile_id,
        approved_labor_rate_cents=initial_labor_rate_cents,
        approved_parts_markup_pct=initial_parts_markup_pct,
        labor_rate_effective_date=None,
        vehicles_in_operation=vehicles_in_operation,
        status="ACTIVE",
        chargeback_balance_cents=0,
        open_parts_return_count=0,
        audit_hold=False,
        outlier_flag=False,
    )
    return response.created(record)


@bp.get("/warranty/dealers/<dealer_id>")
def read_dealer(dealer_id):
    actor = auth(*ALL_ROLES)
    scope(actor, dealer_id)
    record = fetch(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")
    return response.ok(record)


@bp.get("/warranty/dealers")
def list_dealers():
    auth(WARRANTY_ADMIN, CLAIM_ADJUDICATOR, ADJUDICATION_MANAGER, FIELD_AUDITOR, AUDIT_MANAGER)
    limit, offset = util.pagination()
    rows = db.ordered(db.dealers)
    rows = apply_filters(
        rows,
        [
            (str_filter("state_law_profile_id"), "state_law_profile_id"),
            (str_filter("status"), "status"),
            (util.bool_filter("outlier_flag"), "outlier_flag"),
            (util.bool_filter("audit_hold"), "audit_hold"),
        ],
    )
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.get("/warranty/dealers/<dealer_id>/ledger-entries")
def list_ledger_entries(dealer_id):
    actor = auth(WARRANTY_ADMIN, FIELD_AUDITOR, AUDIT_MANAGER, DEALER_WARRANTY_ADMIN)
    scope(actor, dealer_id)
    fetch(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")
    limit, offset = util.pagination()
    rows = [row for row in db.ordered(db.ledger_entries) if row["dealer_id"] == dealer_id]
    rows = apply_filters(rows, [(str_filter("source_type"), "source_type"), (str_filter("claim_id"), "claim_id")])
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.get("/warranty/dealers/<dealer_id>/expense-analytics")
def dealer_expense_analytics(dealer_id):
    actor = auth(WARRANTY_ADMIN, ADJUDICATION_MANAGER, FIELD_AUDITOR, AUDIT_MANAGER, DEALER_WARRANTY_ADMIN)
    scope(actor, dealer_id)
    dealer = fetch(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")
    clock_date = db.now().date()
    window_start = util.date_filter("window_start")
    window_end = util.date_filter("window_end")
    if window_start is None:
        window_start = db.add_days(db.now(), -calc.ANALYTICS_WINDOW_DAYS).date()
    if window_end is None:
        window_end = clock_date
    paid_total, paid_count, incurred_total, incurred_count = calc.expense_bases(dealer_id, window_start, window_end)
    paid_per_vehicle = calc.per_vehicle(paid_total, dealer["vehicles_in_operation"])
    incurred_per_vehicle = calc.per_vehicle(incurred_total, dealer["vehicles_in_operation"])
    median = calc.peer_median_paid(window_start, window_end)
    ratio = calc.outlier_ratio_of(paid_per_vehicle, median)
    flag = ratio >= calc.OUTLIER_RATIO_THRESHOLD
    if dealer["outlier_flag"] != flag:
        dealer["outlier_flag"] = flag
        db.touch(dealer)
    payload = {
        "dealer_id": dealer_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "vehicles_in_operation": dealer["vehicles_in_operation"],
        "paid_numerator_cents": paid_total,
        "incurred_numerator_cents": incurred_total,
        "warranty_expense_per_vehicle_paid_cents": paid_per_vehicle,
        "warranty_expense_per_vehicle_incurred_cents": incurred_per_vehicle,
        "peer_median_paid_cents": median,
        "outlier_ratio": float(ratio),
        "outlier_flag": flag,
        "paid_claim_count": paid_count,
        "incurred_claim_count": incurred_count,
    }
    return response.raw(payload)


# ---------------------------------------------------------------- vehicles
@bp.post("/warranty/vehicles")
def create_vehicle():
    auth(WARRANTY_ADMIN)
    data = util.body()
    vin = util.get_str(data, "vin")
    if len(vin) != 17:
        util.bad("Field 'vin' must be exactly 17 characters long.")
    model_year = util.get_int(data, "model_year", minimum=1980, maximum=2100)
    warranty_start_date = util.get_date(data, "warranty_start_date")
    in_service_odometer = util.get_int(data, "in_service_odometer", minimum=0)
    basic_months = util.get_int(data, "basic_months", minimum=1)
    basic_miles = util.get_int(data, "basic_miles", minimum=1)
    powertrain_months = util.get_int(data, "powertrain_months", minimum=basic_months)
    powertrain_miles = util.get_int(data, "powertrain_miles", minimum=basic_miles)
    unique_or_reject(db.vehicles, "vin", vin)
    record = db.new_record(
        db.vehicles,
        versioned=False,
        vin=vin,
        model_year=model_year,
        warranty_start_date=warranty_start_date.isoformat(),
        in_service_odometer=in_service_odometer,
        basic_months=basic_months,
        basic_miles=basic_miles,
        powertrain_months=powertrain_months,
        powertrain_miles=powertrain_miles,
    )
    return response.created(record)


@bp.get("/warranty/vehicles/<vehicle_id>")
def read_vehicle(vehicle_id):
    auth(
        WARRANTY_ADMIN,
        CLAIM_ADJUDICATOR,
        ADJUDICATION_MANAGER,
        FIELD_AUDITOR,
        AUDIT_MANAGER,
        DEALER_WARRANTY_ADMIN,
    )
    record = fetch(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    return response.ok(record)


# ---------------------------------------------------------------- labor operations
@bp.post("/warranty/labor-operations")
def create_labor_operation():
    auth(WARRANTY_ADMIN)
    data = util.body()
    op_code = util.get_str(data, "op_code")
    description = util.get_str(data, "description")
    standard_time_hours = one_decimal(util.get_dec(data, "standard_time_hours"), "standard_time_hours")
    if standard_time_hours <= 0:
        util.bad("Field 'standard_time_hours' must be strictly positive.")
    max_time_hours = one_decimal(util.get_dec(data, "max_time_hours"), "max_time_hours")
    if max_time_hours < standard_time_hours:
        util.bad("Field 'max_time_hours' must be at least standard_time_hours.")
    category = util.get_enum(data, "category", ("BASIC", "POWERTRAIN"))
    requires_causal_part = util.get_bool(data, "requires_causal_part")
    causal_failure_group = util.get_str(data, "causal_failure_group", required=False)
    if requires_causal_part and not causal_failure_group:
        util.bad("Field 'causal_failure_group' must be non-empty when requires_causal_part is true.")
    if not requires_causal_part and causal_failure_group is not None:
        util.bad("Field 'causal_failure_group' must be null when requires_causal_part is false.")
    overlap_group = util.get_str(data, "overlap_group")
    unique_or_reject(db.labor_operations, "op_code", op_code)
    record = db.new_record(
        db.labor_operations,
        versioned=False,
        op_code=op_code,
        description=description,
        standard_time_hours=standard_time_hours,
        max_time_hours=max_time_hours,
        category=category,
        requires_causal_part=requires_causal_part,
        causal_failure_group=causal_failure_group,
        overlap_group=overlap_group,
    )
    return response.created(record)


@bp.get("/warranty/labor-operations/<operation_id>")
def read_labor_operation(operation_id):
    auth(
        WARRANTY_ADMIN,
        CLAIM_ADJUDICATOR,
        ADJUDICATION_MANAGER,
        FIELD_AUDITOR,
        AUDIT_MANAGER,
        DEALER_WARRANTY_ADMIN,
    )
    record = fetch(db.labor_operations, operation_id, "ERR_LABOR_OPERATION_NOT_FOUND")
    return response.ok(record)


# ---------------------------------------------------------------- catalog parts
@bp.post("/warranty/parts")
def create_part():
    auth(WARRANTY_ADMIN)
    data = util.body()
    part_number = util.get_str(data, "part_number")
    description = util.get_str(data, "description")
    dealer_net_cents = util.get_int(data, "dealer_net_cents", minimum=1)
    failure_group = util.get_str(data, "failure_group")
    return_required = util.get_bool(data, "return_required")
    retention_days = util.get_int(data, "retention_days", minimum=0)
    if not return_required and retention_days != 0:
        util.bad("Field 'retention_days' must be 0 when return_required is false.")
    unique_or_reject(db.parts, "part_number", part_number)
    record = db.new_record(
        db.parts,
        versioned=False,
        part_number=part_number,
        description=description,
        dealer_net_cents=dealer_net_cents,
        failure_group=failure_group,
        return_required=return_required,
        retention_days=retention_days,
    )
    return response.created(record)


@bp.get("/warranty/parts/<part_id>")
def read_part(part_id):
    auth(
        WARRANTY_ADMIN,
        CLAIM_ADJUDICATOR,
        ADJUDICATION_MANAGER,
        FIELD_AUDITOR,
        AUDIT_MANAGER,
        DEALER_WARRANTY_ADMIN,
    )
    record = fetch(db.parts, part_id, "ERR_CATALOG_ITEM_NOT_FOUND")
    return response.ok(record)


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(WARRANTY_ADMIN)
    data = util.body()
    if not util.present(data, "current_utc"):
        util.bad("Field 'current_utc' is required.")
    instant = util.parse_datetime(data["current_utc"], "current_utc")
    db.set_clock(instant)
    return response.raw({"current_utc": db.iso3(instant)})
