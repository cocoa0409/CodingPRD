"""Lift plans: creation, survey, configure, approve, release, cancel, field status."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
from core import (fail, hours_between, new_record, ordered, parse_dt, respond_list,
                  respond_object, rhu, store, touch)
from guards import Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str
from routes_setup import CONFIGURATIONS

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ["DRAFT", "SURVEYED", "CONFIGURED", "PENDING_ENGINEERING", "APPROVED",
                 "RELEASED", "CLOSED", "CANCELLED"]
FIELD_STATUSES = ["NOT_MOBILIZED", "MOBILIZED", "LIFTING", "WIND_HOLD", "SECURED", "DEMOBILIZED"]
FIELD_ACTIONS = ["MOBILIZE", "START_LIFT", "RESUME", "SECURE", "DEMOBILIZE"]
CONFIGURABLE_FROM = ("SURVEYED", "CONFIGURED", "PENDING_ENGINEERING")


@bp.post("/lift-plans")
def create_plan():
    auth(["Dispatcher"])
    b = Body(body())
    site_id = b.string("site_id")
    job_reference = b.string("job_reference")
    window_start_raw, window_start = b.datetime("window_start")
    window_end_raw, window_end = b.datetime("window_end")
    load_weight_lb = b.integer("load_weight_lb", exclusive_min=0)
    sail_area_sqft = b.number("sail_area_sqft", required=False, default=0, minimum=0)
    personnel_lift = b.boolean("personnel_lift", required=False, default=False)
    multi_crane = b.boolean("multi_crane", required=False, default=False)
    road_closure_requested = b.boolean("road_closure_requested", required=False, default=False)
    site = fk("sites", site_id)

    if window_end <= window_start or window_start < store.now:
        fail("ERR_INVALID_WINDOW",
             "window_end must be strictly after window_start and window_start may not precede "
             "the logical clock.")

    rec = new_record({
        "site_id": site_id,
        "customer_id": site["customer_id"],
        "crane_id": None,
        "operator_id": None,
        "rigger_id": None,
        "job_reference": job_reference,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "load_weight_lb": load_weight_lb,
        "sail_area_sqft": sail_area_sqft,
        "personnel_lift": personnel_lift,
        "multi_crane": multi_crane,
        "road_closure_requested": road_closure_requested,
        "configuration": None,
        "boom_length_ft": None,
        "radius_ft": None,
        "parts_of_line": None,
        "block_weight_lb": 0,
        "jib_weight_lb": 0,
        "aux_head_weight_lb": 0,
        "chart_gross_capacity_lb": 0,
        "hoist_line_capacity_lb": 0,
        "net_capacity_lb": 0,
        "rigging_weight_lb": 0,
        "total_load_lb": 0,
        "utilization_pct": 0,
        "lift_class": "NOT_CLASSIFIED",
        "bearing_variant": "NONE",
        "per_outrigger_load_lb": 0,
        "bearing_pressure_psf": 0,
        "matting_required": False,
        "mat_area_required_sqft": 0,
        "mat_count": 0,
        "allowable_wind_mph": 0,
        "escort_required": False,
        "permit_required": False,
        "rigging_verified": False,
        "standby_hours_billable": 0,
        "plan_status": "DRAFT",
        "field_status": "NOT_MOBILIZED",
        "cancellation_reason": None,
    })
    store.lift_plans[rec["id"]] = rec
    return respond_object(derive.plan_json(rec), 201)


@bp.get("/lift-plans/<pid>")
def read_plan(pid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager", "BillingClerk",
          "Customer"])
    rec = must_exist("lift_plans", pid)
    return respond_object(derive.plan_json(rec))


@bp.get("/lift-plans")
def list_plans():
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager", "BillingClerk"])
    limit, offset = pagination()
    filters = {
        "site_id": q_str("site_id"),
        "customer_id": q_str("customer_id"),
        "crane_id": q_str("crane_id"),
        "operator_id": q_str("operator_id"),
        "rigger_id": q_str("rigger_id"),
    }
    plan_status = q_enum("plan_status", PLAN_STATUSES)
    field_status = q_enum("field_status", FIELD_STATUSES)
    rows = ordered(store.lift_plans)
    for key, value in filters.items():
        if value:
            rows = [r for r in rows if r[key] == value]
    if plan_status:
        rows = [r for r in rows if r["plan_status"] == plan_status]
    if field_status:
        rows = [r for r in rows if r["field_status"] == field_status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.plan_json)
    return respond_list(items, limit, offset, total)


@bp.post("/lift-plans/<pid>/site-survey")
def site_survey(pid):
    auth(["Dispatcher"])
    plan = must_exist("lift_plans", pid)
    b = Body(body())
    confirmed = b.integer("confirmed_soil_bearing_capacity_psf", exclusive_min=0)
    access_notes = b.string("access_notes", allow_empty=True)
    mat_inventory_available = b.boolean("mat_inventory_available")

    if plan["plan_status"] != "DRAFT":
        fail("ERR_INVALID_PLAN_STATE", "A site survey is only legal while the plan is DRAFT.")

    site = store.sites[plan["site_id"]]
    site["soil_bearing_capacity_psf"] = confirmed
    site["access_notes"] = access_notes
    site["mat_inventory_available"] = mat_inventory_available
    site["survey_status"] = "SURVEYED"
    site["last_surveyed_at"] = store.now_iso()
    touch(site)

    plan["plan_status"] = "SURVEYED"
    touch(plan)
    return respond_object(derive.plan_json(plan))


@bp.post("/lift-plans/<pid>/configure")
def configure_plan(pid):
    auth(["Dispatcher"])
    plan = must_exist("lift_plans", pid)
    b = Body(body())
    crane_id = b.string("crane_id")
    operator_id = b.string("operator_id")
    rigger_id = b.string("rigger_id")
    configuration = b.enum("configuration", CONFIGURATIONS)
    boom_length_ft = b.integer("boom_length_ft", exclusive_min=0)
    radius_ft = b.integer("radius_ft", exclusive_min=0)
    parts_of_line = b.integer("parts_of_line", minimum=1)
    expected_version = b.integer("expected_lift_plan_version")
    block_weight_lb = b.integer("block_weight_lb", required=False, default=0, minimum=0)
    jib_weight_lb = b.integer("jib_weight_lb", required=False, default=0, minimum=0)
    aux_head_weight_lb = b.integer("aux_head_weight_lb", required=False, default=0, minimum=0)

    crane = fk("cranes", crane_id)
    operator = fk("personnel", operator_id)
    rigger = fk("personnel", rigger_id)

    # step 8 — optimistic concurrency, before the plan's own state check
    if expected_version != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION",
             "expected_lift_plan_version does not match the plan's current version.")

    # step 9 — own state
    if plan["plan_status"] not in CONFIGURABLE_FROM:
        fail("ERR_INVALID_PLAN_STATE",
             "A plan may only be configured from SURVEYED, CONFIGURED or PENDING_ENGINEERING.")

    # step 10 — cross-entity state gate
    if derive.crane_status(crane) == "OUT_OF_SERVICE":
        fail("ERR_CRANE_OUT_OF_SERVICE", "The assigned crane is out of service.")

    # step 11 — personnel discriminators
    if operator["role_type"] != "OPERATOR" or rigger["role_type"] != "RIGGER":
        fail("ERR_PERSONNEL_ROLE_MISMATCH",
             "operator_id must name an OPERATOR and rigger_id must name a RIGGER.")

    # step 13 — rigging and capacity, in the PRD's four-step order
    candidates = [r for r in ordered(store.load_chart_entries)
                  if r["crane_id"] == crane_id and r["configuration"] == configuration
                  and r["boom_length_ft"] == boom_length_ft and r["radius_ft"] >= radius_ft]
    if not candidates:
        fail("ERR_LOAD_CHART_NO_ROW", "No charted row covers that configuration and radius.")
    candidates.sort(key=lambda r: (r["radius_ft"], r["_seq"]))
    chart_row = candidates[0]
    chart_gross_capacity_lb = chart_row["gross_capacity_lb"]

    hoist_line_capacity_lb = crane["max_line_pull_lb"] * parts_of_line
    deductions = block_weight_lb + jib_weight_lb + aux_head_weight_lb
    net_capacity_lb = min(chart_gross_capacity_lb, hoist_line_capacity_lb) - deductions
    if net_capacity_lb <= 0:
        fail("ERR_CAPACITY_EXCEEDED", "Net capacity is not positive.")

    active = derive.plan_active_assignments(plan["id"])
    if not active:
        fail("ERR_NO_RIGGING_ASSIGNED", "The plan holds no ACTIVE gear commitment.")
    rigging_weight_lb = sum(store.rigging_gear[a["gear_id"]]["weight_lb"] for a in active)
    total_load_lb = plan["load_weight_lb"] + rigging_weight_lb

    utilization_pct = rhu(Decimal(total_load_lb) / Decimal(net_capacity_lb) * Decimal(100), 2)
    if utilization_pct > Decimal("100.00"):
        fail("ERR_CAPACITY_EXCEEDED", "Utilisation exceeds 100.00 percent.")

    tensions = {}
    for a in active:
        factor = calc.LOAD_ANGLE_FACTORS[a["sling_angle_deg"]]
        tension = int(rhu(Decimal(total_load_lb) / Decimal(a["leg_count"]) * factor, 0))
        if tension > a["effective_wll_lb"]:
            fail("ERR_SLING_WLL_EXCEEDED",
                 "A sling leg tension exceeds its snapshotted working load limit.")
        tensions[a["id"]] = (float(factor), tension)

    # step 15 — crane effective-window exclusivity
    window_start = parse_dt(plan["window_start"])
    window_end = parse_dt(plan["window_end"])
    for other in ordered(store.lift_plans):
        if other["id"] == plan["id"] or other["crane_id"] != crane_id:
            continue
        if other["plan_status"] not in derive.RESERVING_PLAN_STATES:
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"]) + timedelta(hours=12)
        if window_start < other_end and other_start < window_end:
            fail("ERR_CRANE_WINDOW_CONFLICT",
                 "The requested window collides with another plan on this crane.")

    # step 16 — operator daily hour cap
    day_hours = derive.operator_day_hours(operator_id, extra_plan=(window_start, window_end),
                                          exclude_plan_id=plan["id"])
    for hours in day_hours.values():
        if hours > Decimal("12.0"):
            fail("ERR_OPERATOR_HOURS_EXCEEDED",
                 "The operator would exceed 12.0 assigned hours on a single UTC day.")

    # ---- everything passed; commit ----
    site = store.sites[plan["site_id"]]
    lift_class = calc.lift_class(utilization_pct, plan, site)

    plan["crane_id"] = crane_id
    plan["operator_id"] = operator_id
    plan["rigger_id"] = rigger_id
    plan["configuration"] = configuration
    plan["boom_length_ft"] = boom_length_ft
    plan["radius_ft"] = radius_ft
    plan["parts_of_line"] = parts_of_line
    plan["block_weight_lb"] = block_weight_lb
    plan["jib_weight_lb"] = jib_weight_lb
    plan["aux_head_weight_lb"] = aux_head_weight_lb
    plan["chart_gross_capacity_lb"] = chart_gross_capacity_lb
    plan["hoist_line_capacity_lb"] = hoist_line_capacity_lb
    plan["net_capacity_lb"] = net_capacity_lb
    plan["rigging_weight_lb"] = rigging_weight_lb
    plan["total_load_lb"] = total_load_lb
    plan["utilization_pct"] = float(utilization_pct)
    plan["lift_class"] = lift_class
    plan.update(calc.ground_bearing(total_load_lb, crane, site, "PROVISIONAL_SURVEY"))
    plan["allowable_wind_mph"] = calc.allowable_wind(plan["sail_area_sqft"],
                                                     plan["load_weight_lb"], crane)
    plan["escort_required"] = crane["class_tons"] >= calc.ESCORT_CLASS_TONS_THRESHOLD
    plan["permit_required"] = bool(plan["road_closure_requested"]) or plan["escort_required"]
    plan["rigging_verified"] = True
    plan["plan_status"] = "CONFIGURED" if lift_class == "STANDARD" else "PENDING_ENGINEERING"

    for a in active:
        factor, tension = tensions[a["id"]]
        a["load_angle_factor"] = factor
        a["leg_tension_lb"] = tension
        touch(a)

    cascades.supersede_reviews(plan["id"])
    touch(plan)
    return respond_object(derive.plan_json(plan))


@bp.post("/lift-plans/<pid>/approve")
def approve_plan(pid):
    auth(["LiftDirector"])
    plan = must_exist("lift_plans", pid)
    if plan["plan_status"] != "CONFIGURED":
        fail("ERR_INVALID_PLAN_STATE", "Only a CONFIGURED plan may be approved.")
    if plan["lift_class"] != "STANDARD":
        fail("ERR_INVALID_PLAN_STATE",
             "Only a STANDARD lift may be approved without an engineering stamp.")
    if not plan["rigging_verified"]:
        fail("ERR_INVALID_PLAN_STATE", "The plan's rigging has not been verified.")
    plan["plan_status"] = "APPROVED"
    touch(plan)
    return respond_object(derive.plan_json(plan))


@bp.post("/lift-plans/<pid>/release")
def release_plan(pid):
    auth(["LiftDirector"])
    plan = must_exist("lift_plans", pid)

    if plan["plan_status"] != "APPROVED":
        fail("ERR_INVALID_PLAN_STATE", "Only an APPROVED plan may be released.")

    crane = store.cranes.get(plan["crane_id"]) if plan["crane_id"] else None
    if crane is not None and derive.crane_status(crane) == "OUT_OF_SERVICE":
        fail("ERR_CRANE_OUT_OF_SERVICE", "The assigned crane is out of service.")

    for a in derive.plan_active_assignments(plan["id"]):
        gear = store.rigging_gear[a["gear_id"]]
        if derive.gear_status(gear) != "SERVICEABLE":
            fail("ERR_GEAR_NOT_SERVICEABLE",
                 "An active gear commitment references gear that is not serviceable.")

    if plan["permit_required"]:
        approved = [p for p in store.permits.values()
                    if p["lift_plan_id"] == plan["id"] and p["status"] == "APPROVED"]
        if not approved:
            fail("ERR_PERMIT_NOT_APPROVED", "The plan requires an approved permit.")

    operator = store.personnel.get(plan["operator_id"]) if plan["operator_id"] else None
    rigger = store.personnel.get(plan["rigger_id"]) if plan["rigger_id"] else None
    window_start = parse_dt(plan["window_start"])

    if operator is not None:
        cert_expires = parse_dt(operator["certification_expires_on"])
        if cert_expires is None or cert_expires <= window_start:
            fail("ERR_OPERATOR_CERT_EXPIRED",
                 "The operator's certification does not outlast the lift window's start.")
        if crane is not None and operator["endorsement_class_tons"] < crane["class_tons"]:
            fail("ERR_OPERATOR_ENDORSEMENT_INSUFFICIENT",
                 "The operator's endorsement does not cover this crane class.")

    if rigger is not None:
        required = derive.REQUIRED_RIGGER_LEVEL.get(plan["lift_class"], "NONE")
        if (derive.RIGGER_LADDER.index(rigger["rigger_level"])
                < derive.RIGGER_LADDER.index(required)):
            fail("ERR_RIGGER_QUALIFICATION_INSUFFICIENT",
                 "The rigger's qualification is below the level this lift class demands.")

    customer = store.customers.get(plan["customer_id"])
    if customer is not None and customer["credit_hold"]:
        fail("ERR_CUSTOMER_CREDIT_HOLD", "The owning account is on credit hold.")

    plan["plan_status"] = "RELEASED"
    touch(plan)
    return respond_object(derive.plan_json(plan))


@bp.post("/lift-plans/<pid>/cancel")
def cancel_plan_route(pid):
    auth(["Dispatcher", "LiftDirector"])
    plan = must_exist("lift_plans", pid)
    b = Body(body())
    reason = b.string("reason")
    if plan["plan_status"] in ("CLOSED", "CANCELLED"):
        fail("ERR_INVALID_PLAN_STATE", "A closed or cancelled plan cannot be cancelled.")
    cascades.cancel_plan(plan, reason)
    return respond_object(derive.plan_json(plan))


@bp.post("/lift-plans/<pid>/field-status")
def field_status(pid):
    user_id, _role = auth(["Operator"])
    plan = must_exist("lift_plans", pid)
    b = Body(body())
    action = b.enum("action", FIELD_ACTIONS)

    if plan["operator_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_OPERATOR", "Only the plan's assigned operator may drive it.")

    legal_from = {"MOBILIZE": "NOT_MOBILIZED", "START_LIFT": "MOBILIZED",
                  "RESUME": "WIND_HOLD", "SECURE": "LIFTING", "DEMOBILIZE": "SECURED"}
    if plan["field_status"] != legal_from[action]:
        fail("ERR_INVALID_FIELD_STATE",
             "%s is not legal from field status %s." % (action, plan["field_status"]))

    if action == "MOBILIZE" and plan["plan_status"] != "RELEASED":
        fail("ERR_INVALID_PLAN_STATE", "The plan must be RELEASED before the crew mobilises.")

    if action in ("START_LIFT", "RESUME", "SECURE"):
        open_events = [e for e in store.standby_events.values()
                       if e["lift_plan_id"] == plan["id"] and e["status"] == "OPEN"]
        if open_events:
            fail("ERR_INVALID_FIELD_STATE", "An open standby event blocks this action.")

    if action == "MOBILIZE":
        crane = store.cranes.get(plan["crane_id"]) if plan["crane_id"] else None
        if crane is not None and derive.crane_status(crane) == "OUT_OF_SERVICE":
            fail("ERR_CRANE_OUT_OF_SERVICE", "The assigned crane is out of service.")

    target = {"MOBILIZE": "MOBILIZED", "START_LIFT": "LIFTING", "RESUME": "LIFTING",
              "SECURE": "SECURED", "DEMOBILIZE": "DEMOBILIZED"}[action]
    plan["field_status"] = target

    if action == "DEMOBILIZE":
        if plan["plan_status"] == "RELEASED":
            plan["plan_status"] = "CLOSED"
        cascades.recompute_plan_standby(plan)

    touch(plan)
    return respond_object(derive.plan_json(plan))
