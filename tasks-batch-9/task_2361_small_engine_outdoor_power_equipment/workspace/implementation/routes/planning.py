"""Assembly lines, seasonal build orders, channel positioning and line audits."""

from collections import OrderedDict
from datetime import timedelta

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES, user_id
from errors import ApiError
from response import list_response, object_response
from store import db, bump, set_fields

bp = Blueprint("planning", __name__)

SEASONS = ("PRE_SEASON", "IN_SEASON")
ORDER_STATUSES = ("PLANNED", "RELEASED", "IN_PRODUCTION", "HELD", "COMPLETED")
LINE_STATUSES = ("RUNNING", "DOWN")


def _weeks_of(production_week, week_span):
    return [production_week + timedelta(days=7 * i) for i in range(week_span)]


def _order_weeks(order):
    monday = v.date_field({"production_week": order["production_week"]}, "production_week")
    return _weeks_of(monday, order["week_span"])


# ------------------------------------------------------------- assembly lines

@bp.route("/assembly-lines", methods=["POST"])
@endpoint(["PlantAdmin"])
def create_line():
    payload = v.body()
    line_code = v.string_field(payload, "line_code", 1, 20)
    supported = v.array_field(payload, "supported_product_lines", 1)
    for entry in supported:
        if not isinstance(entry, str) or entry not in calc.PRODUCT_LINES:
            v.bad("Each entry of 'supported_product_lines' must be one of %s."
                  % list(calc.PRODUCT_LINES))
    weekly_capacity_units = v.int_field(payload, "weekly_capacity_units", 1, 100000)
    changeover_gap_weeks = v.int_field(
        payload, "changeover_gap_weeks", 0, 4, required=False, default=1
    )
    status = v.enum_field(payload, "status", LINE_STATUSES, required=False, default="RUNNING")

    svc.require_unique(db.assembly_lines, "line_code", line_code)

    line = store.new_record(OrderedDict([
        ("line_code", line_code),
        ("supported_product_lines", list(supported)),
        ("weekly_capacity_units", weekly_capacity_units),
        ("changeover_gap_weeks", changeover_gap_weeks),
        ("status", status),
    ]))
    db.assembly_lines[line["id"]] = line
    return object_response(store.public(line), 201)


# --------------------------------------------------------------- build orders

@bp.route("/build-orders", methods=["POST"])
@endpoint(["ProductionPlanner"])
def plan_order():
    payload = v.body()
    model_id = v.id_field(payload, "product_model_id")
    line_id = v.id_field(payload, "assembly_line_id")
    season = v.enum_field(payload, "season", SEASONS)
    production_week = v.date_field(payload, "production_week")
    if not v.is_monday(production_week):
        v.bad("production_week must fall on a Monday.")
    week_span = v.int_field(payload, "week_span", 1, 8)
    planned_quantity = v.int_field(payload, "planned_quantity", 1, 100000)

    model = svc.get_model(model_id)
    line = svc.get_assembly_line(line_id)

    if model["status"] != "RELEASED":
        raise ApiError(
            "ERR_MODEL_STATE_INVALID",
            "Only a RELEASED product model may be planned for production.",
        )
    product_line = model["product_line"]
    if product_line not in line["supported_product_lines"]:
        raise ApiError(
            "ERR_LINE_PRODUCT_LINE_UNSUPPORTED",
            "The assembly line does not support the model's product line.",
        )

    weeks = _weeks_of(production_week, week_span)
    gap = line["changeover_gap_weeks"]
    for other in store.sort_created_asc(list(db.build_orders.values())):
        if other["assembly_line_id"] != line["id"]:
            continue
        if other["status"] not in ("PLANNED", "RELEASED", "IN_PRODUCTION"):
            continue
        other_model = svc.order_model(other)
        if other_model is None or other_model["product_line"] == product_line:
            continue
        for other_week in _order_weeks(other):
            for week in weeks:
                separation = abs((other_week - week).days) // 7
                if separation <= gap:
                    raise ApiError(
                        "ERR_LINE_CHANGEOVER_CONFLICT",
                        "The line requires %d whole week(s) of changeover separation "
                        "between different product lines." % gap,
                    )

    season_start = calc.SEASON_START[product_line]
    if season == "PRE_SEASON" and not production_week < season_start:
        raise ApiError(
            "ERR_SEASON_WINDOW_MISMATCH",
            "A PRE_SEASON order must be produced strictly before the season start.",
        )
    if season == "IN_SEASON" and production_week < season_start:
        raise ApiError(
            "ERR_SEASON_WINDOW_MISMATCH",
            "An IN_SEASON order must be produced on or after the season start.",
        )

    load = calc.per_week_load(planned_quantity, week_span)
    capacity = line["weekly_capacity_units"]
    for week in weeks:
        total = load
        for other in db.build_orders.values():
            if other["assembly_line_id"] != line["id"]:
                continue
            if other["status"] not in ("PLANNED", "RELEASED", "IN_PRODUCTION"):
                continue
            if week not in _order_weeks(other):
                continue
            total += calc.per_week_load(other["planned_quantity"], other["week_span"])
        if total > capacity:
            raise ApiError(
                "ERR_LINE_CAPACITY_EXCEEDED",
                "The line's weekly capacity is exceeded in week %s." % week.isoformat(),
            )

    (build_value_cents, carry_rate, carry_weeks, carry_cost_cents,
     total_committed_cents) = calc.build_carry_cost(
        planned_quantity, model["standard_cost_cents"], season, product_line,
        production_week,
    )

    order = store.new_record(OrderedDict([
        ("product_model_id", model["id"]),
        ("assembly_line_id", line["id"]),
        ("season", season),
        ("production_week", production_week.isoformat()),
        ("week_span", week_span),
        ("planned_quantity", planned_quantity),
        ("build_value_cents", build_value_cents),
        ("carry_weeks", carry_weeks),
        ("carry_rate", carry_rate),
        ("carry_cost_cents", carry_cost_cents),
        ("total_committed_cents", total_committed_cents),
        ("staged_quantity", 0),
        ("built_quantity", 0),
        ("allocated_dealer_units", 0),
        ("allocated_mass_retail_units", 0),
        ("unallocated_units", 0),
        ("allocation_status", "UNALLOCATED"),
        ("allocation_run_at", None),
        ("status", "PLANNED"),
        ("held_reason", None),
        ("status_before_hold", None),
        ("released_at", None),
    ]))
    db.build_orders[order["id"]] = order
    return object_response(store.public(order), 201)


@bp.route("/build-orders/<order_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_order(order_id):
    order = svc.get_build_order(order_id)
    return object_response(store.public(order), 200)


@bp.route("/build-orders", methods=["GET"])
@endpoint(READ_ROLES)
def list_orders():
    limit, offset = v.pagination()
    model_id = v.query_string("product_model_id")
    line_id = v.query_string("assembly_line_id")
    status = v.query_enum("status", ORDER_STATUSES)
    season = v.query_enum("season", SEASONS)
    rows = store.sort_created_asc(list(db.build_orders.values()))
    if model_id is not None:
        rows = [r for r in rows if r["product_model_id"] == model_id]
    if line_id is not None:
        rows = [r for r in rows if r["assembly_line_id"] == line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if season is not None:
        rows = [r for r in rows if r["season"] == season]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/build-orders/<order_id>/release", methods=["POST"])
@endpoint(["ProductionPlanner"])
def release_order(order_id):
    v.body()
    order = svc.get_build_order(order_id)
    model = svc.order_model(order)

    if model is None or model["status"] != "RELEASED":
        raise ApiError(
            "ERR_MODEL_STATE_INVALID",
            "The order's product model is no longer RELEASED.",
        )
    if order["status"] != "PLANNED":
        raise ApiError(
            "ERR_BUILD_ORDER_NOT_PLANNED",
            "Only a PLANNED build order may be released to the floor.",
        )
    svc.check_safety_certification(model)

    line = db.assembly_lines.get(order["assembly_line_id"])
    if line is None or line["status"] != "RUNNING":
        raise ApiError("ERR_ASSEMBLY_LINE_DOWN", "The assembly line is not RUNNING.")

    platform = svc.model_platform(model)
    if platform is None or platform["certification_posture"] != "OPEN":
        raise ApiError(
            "ERR_FAMILY_NOT_CERTIFIED",
            "The model's platform is not certified for production.",
        )

    set_fields(order, status="RELEASED", released_at=store.now_clock())
    return object_response(store.public(order), 200)


# ---------------------------------------------------------------- allocations

@bp.route("/build-orders/<order_id>/allocations/run", methods=["POST"])
@endpoint(["ProductionPlanner"])
def run_allocation(order_id):
    payload = v.body()
    expected_version = v.int_field(payload, "expected_build_order_version")

    order = svc.get_build_order(order_id)
    if expected_version != order["version"]:
        raise ApiError(
            "ERR_STALE_BUILD_ORDER_VERSION",
            "The build order has advanced since it was read.",
        )

    pool = order["built_quantity"]
    if pool <= 0:
        raise ApiError(
            "ERR_NO_ALLOCATABLE_UNITS",
            "The order has no released units to position.",
        )

    model = svc.order_model(order)
    dealer, mass, unallocated = calc.allocation_waterfall(
        pool, model["dealer_share_pct"], model["dealer_cap_units"],
        model["mass_retail_cap_units"],
    )
    order["allocated_dealer_units"] = dealer
    order["allocated_mass_retail_units"] = mass
    order["unallocated_units"] = unallocated
    order["allocation_status"] = "ALLOCATED"
    order["allocation_run_at"] = store.now_clock()
    bump(order)
    return object_response(store.public(order), 200)


@bp.route("/build-orders/<order_id>/allocations/reset", methods=["POST"])
@endpoint(["ProductionPlanner"])
def reset_allocation(order_id):
    v.body()
    order = svc.get_build_order(order_id)
    set_fields(
        order,
        allocated_dealer_units=0,
        allocated_mass_retail_units=0,
        unallocated_units=order["built_quantity"],
        allocation_status="UNALLOCATED",
        allocation_run_at=None,
    )
    return object_response(store.public(order), 200)


# --------------------------------------------------------------- line audits

@bp.route("/build-orders/<order_id>/line-audits", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def schedule_audit(order_id):
    payload = v.body()
    audit_week = v.date_field(payload, "audit_week")
    if not v.is_monday(audit_week):
        v.bad("audit_week must fall on a Monday.")

    order = svc.get_build_order(order_id)
    for audit in svc.audits_of_order(order["id"]):
        if audit["status"] == "SCHEDULED":
            raise ApiError(
                "ERR_AUDIT_ALREADY_OPEN",
                "The order already carries a SCHEDULED production line audit.",
            )

    family = svc.order_family(order)
    audit = store.new_record(OrderedDict([
        ("build_order_id", order["id"]),
        ("certification_family_id", family["id"] if family else None),
        ("audit_week", audit_week.isoformat()),
        ("required_sample_size", calc.required_sample_size(order["built_quantity"])),
        ("units_tested", None),
        ("units_failed", None),
        ("max_measured_emission_g_per_kwh", None),
        ("failure_rate", None),
        ("failure_reason", None),
        ("status", "SCHEDULED"),
        ("recorded_by_user_id", None),
    ]))
    db.line_audits[audit["id"]] = audit
    return object_response(store.public(audit), 201)


@bp.route("/build-orders/<order_id>/line-audits", methods=["GET"])
@endpoint(READ_ROLES)
def list_order_audits(order_id):
    limit, offset = v.pagination()
    order = svc.get_build_order(order_id)
    rows = svc.audits_of_order(order["id"])
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/line-audits/<audit_id>/record", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def record_audit(audit_id):
    payload = v.body()
    units_tested = v.int_field(payload, "units_tested", 1)
    units_failed = v.int_field(payload, "units_failed", 0)
    if units_failed > units_tested:
        v.bad("units_failed may not exceed units_tested.")
    max_emission = v.number_field(payload, "max_measured_emission_g_per_kwh", exclusive_min=0)

    audit = svc.get_line_audit(audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_AUDIT_STATE_INVALID",
            "Only a SCHEDULED production line audit may be recorded.",
        )
    if units_tested < audit["required_sample_size"]:
        raise ApiError(
            "ERR_AUDIT_SAMPLE_TOO_SMALL",
            "The sample is smaller than the audit's frozen required sample size.",
        )
    order = svc.get_build_order(audit["build_order_id"])
    if units_tested > order["built_quantity"]:
        raise ApiError(
            "ERR_AUDIT_SAMPLE_EXCEEDS_POPULATION",
            "The sample exceeds the order's released population.",
        )

    family = db.families.get(audit["certification_family_id"])
    failure_rate, status, failure_reason = calc.audit_outcome(
        units_tested, units_failed, max_emission,
        family["family_emission_limit_g_per_kwh"],
    )

    set_fields(
        audit,
        units_tested=units_tested,
        units_failed=units_failed,
        max_measured_emission_g_per_kwh=max_emission,
        failure_rate=failure_rate,
        failure_reason=failure_reason,
        status=status,
        recorded_by_user_id=user_id(),
    )

    if status == "FAILED":
        svc.audit_failure_cascade(family)

    return object_response(store.public(audit), 200)
