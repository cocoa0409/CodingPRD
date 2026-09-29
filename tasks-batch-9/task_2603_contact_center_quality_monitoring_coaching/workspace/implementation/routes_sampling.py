"""Sampling plans and selections (PRD 3.4)."""
from flask import Blueprint

import calc
import derive
import shape
from common import (body, created, fail, get, new_row, ok, ok_list, parse_dt,
                    require, rows, sorted_rows, touch)
from authz import endpoint
from listing import page
from serial import view, views

bp = Blueprint("sampling", __name__)

PLAN_STATUSES = ("DRAFT", "OPEN", "CLOSED")
SELECTION_STATUSES = ("SELECTED", "ASSIGNED", "EVALUATED", "EXCLUDED")
SOURCES = ("RANDOM", "TARGETED", "CUSTOMER_FLAGGED")
EXCLUSION_REASONS = ("CONSENT_DENIED", "DUPLICATE_INTERACTION",
                     "EVALUATOR_UNAVAILABLE", "PLAN_CLOSED_SWEEP")
MIX_KEYS = ("random_pct", "targeted_pct", "customer_flagged_pct")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")
CONSENT_OK = ("VERIFIED", "NOT_REQUIRED")


def consent_gate(interaction):
    if interaction["recording_consent_status"] not in CONSENT_OK:
        fail("ERR_CONSENT_NOT_VERIFIED",
             "the interaction's recording consent is not VERIFIED or NOT_REQUIRED")


def periods_collide(a_start, a_end, b_start, b_end):
    """Closed-interval semantics: touching endpoints collide (PRD 3.4)."""
    return a_start <= b_end and b_start <= a_end


def check_period_overlap(form_id, start, end, exclude_id=None):
    for other in rows("plans"):
        if other["id"] == exclude_id or other["form_id"] != form_id:
            continue
        if other["status"] not in ("DRAFT", "OPEN"):
            continue
        if periods_collide(start, end, parse_dt(other["period_start"]),
                           parse_dt(other["period_end"])):
            fail("ERR_PLAN_PERIOD_OVERLAP",
                 "the period collides with a sibling plan of the same form")


# --- sample plans ---------------------------------------------------------

@bp.post("/sample-plans")
@endpoint("QualityManager")
def create_plan():
    payload = body()
    form_id = shape.want_string(payload, "form_id")
    start_raw, start = shape.want_datetime(payload, "period_start")
    end_raw, end = shape.want_datetime(payload, "period_end")
    volume = shape.want_int(payload, "per_agent_target_volume", minimum=1, maximum=50)
    mix = shape.want_object(payload, "source_mix")

    form = require("forms", form_id, "ERR_FORM_NOT_FOUND")
    if form["status"] != "ACTIVE":
        fail("ERR_FORM_NOT_ACTIVE", "the referenced form is not ACTIVE")

    if set(mix.keys()) != set(MIX_KEYS):
        fail("ERR_SOURCE_MIX_INVALID",
             "source_mix must carry exactly random_pct, targeted_pct and "
             "customer_flagged_pct")
    total = 0
    for key in MIX_KEYS:
        value = mix[key]
        if not shape.is_int(value) or value < 0:
            fail("ERR_SOURCE_MIX_INVALID",
                 "source_mix percentages must be non-negative integers")
        total += value
    if total != 100:
        fail("ERR_SOURCE_MIX_INVALID", "source_mix percentages must sum to exactly 100")

    if not end > start:
        fail("ERR_INVALID_TIME_RANGE", "period_end must be strictly after period_start")

    check_period_overlap(form["id"], start, end)

    plan = new_row("plans", {
        "form_id": form["id"],
        "period_start": start_raw,
        "period_end": end_raw,
        "per_agent_target_volume": volume,
        "source_mix": {key: mix[key] for key in MIX_KEYS},
        "status": "DRAFT",
        "pinned_form_guidance_version": None,
        "selections_count": 0,
        "excluded_count": 0,
        "targeted_reserved_count": 0,
        "targeted_reserve_by_agent": {},
        "agent_volume_attainment": {},
    })
    return created(view(plan))


@bp.post("/sample-plans/<plan_id>/open")
@endpoint("QualityManager")
def open_plan(plan_id):
    plan = require("plans", plan_id, "ERR_PLAN_NOT_FOUND")
    form = get("forms", plan["form_id"])
    if form is None or form["status"] != "ACTIVE":
        fail("ERR_FORM_NOT_ACTIVE", "the plan's form is no longer ACTIVE")
    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_NOT_DRAFT", "only a DRAFT plan may be opened")
    check_period_overlap(plan["form_id"], parse_dt(plan["period_start"]),
                         parse_dt(plan["period_end"]), exclude_id=plan["id"])
    plan["status"] = "OPEN"
    plan["pinned_form_guidance_version"] = form["guidance_version"]
    touch(plan)
    return ok(view(plan))


@bp.post("/sample-plans/<plan_id>/close")
@endpoint("QualityManager")
def close_plan(plan_id):
    plan = require("plans", plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "OPEN":
        fail("ERR_PLAN_NOT_OPEN", "only an OPEN plan may be closed")

    swept = [s for s in sorted_rows(rows("selections"))
             if s["plan_id"] == plan["id"] and s["status"] in ("SELECTED", "ASSIGNED")]
    evaluator_ids = []
    interaction_ids = []
    for selection in swept:
        evaluator_id = selection.get("assigned_evaluator_id")
        selection["status"] = "EXCLUDED"
        selection["exclusion_reason"] = "PLAN_CLOSED_SWEEP"
        selection["assigned_evaluator_id"] = None
        selection["review_window_start"] = None
        selection["review_window_end"] = None
        touch(selection)
        if evaluator_id is not None and evaluator_id not in evaluator_ids:
            evaluator_ids.append(evaluator_id)
        if selection["interaction_id"] not in interaction_ids:
            interaction_ids.append(selection["interaction_id"])

    for evaluator_id in evaluator_ids:
        derive.recompute_evaluator(evaluator_id)

    updates = calc.sample_quota_attainment(plan)
    updates["status"] = "CLOSED"
    plan.update(updates)
    touch(plan)

    for interaction_id in interaction_ids:
        derive.recompute_interaction_sampled(interaction_id)

    return ok(view(plan))


@bp.get("/sample-plans/<plan_id>")
@endpoint(*READ_ROLES)
def read_plan(plan_id):
    return ok(view(require("plans", plan_id, "ERR_PLAN_NOT_FOUND")))


@bp.get("/sample-plans")
@endpoint(*READ_ROLES)
def list_plans():
    limit, offset = shape.pagination()
    form_id = shape.query_str("form_id")
    status = shape.query_enum("status", PLAN_STATUSES)
    items = sorted_rows(rows("plans"))
    if form_id is not None:
        items = [p for p in items if p["form_id"] == form_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)


# --- sample selections ----------------------------------------------------

@bp.post("/sample-selections")
@endpoint("QualityManager")
def create_selection():
    payload = body()
    plan_id = shape.want_string(payload, "plan_id")
    interaction_id = shape.want_string(payload, "interaction_id")
    source = shape.want_enum(payload, "source", SOURCES)

    plan = require("plans", plan_id, "ERR_PLAN_NOT_FOUND")
    interaction = require("interactions", interaction_id, "ERR_INTERACTION_NOT_FOUND")

    if plan["status"] != "OPEN":
        fail("ERR_PLAN_NOT_OPEN", "selections may only be pulled into an OPEN plan")

    consent_gate(interaction)

    if source == "CUSTOMER_FLAGGED":
        if not interaction["customer_flagged"]:
            fail("ERR_SOURCE_NOT_ELIGIBLE",
                 "CUSTOMER_FLAGGED requires the interaction to be customer_flagged")
    elif source == "TARGETED":
        eligible = any(s["interaction_id"] == interaction["id"]
                       and s["status"] == "CURRENT"
                       and s["priority_tier"] in ("P1", "P2")
                       for s in rows("scans"))
        if not eligible:
            fail("ERR_SOURCE_NOT_ELIGIBLE",
                 "TARGETED requires a CURRENT analytics scan in tier P1 or P2")

    for other in rows("selections"):
        if (other["plan_id"] == plan["id"]
                and other["interaction_id"] == interaction["id"]
                and other["status"] in calc.LIVE_SELECTION_STATUSES):
            fail("ERR_DUPLICATE_INTERACTION_SELECTION",
                 "the interaction is already held by a live selection of this plan")

    agent_id = interaction["agent_id"]
    caps, reserve = calc.plan_source_caps(plan, agent_id)
    counts = calc.consumed_by_source(plan["id"], agent_id)
    consumed = sum(counts.values())
    if consumed >= int(plan["per_agent_target_volume"]) + reserve:
        fail("ERR_AGENT_QUOTA_EXCEEDED",
             "the agent's per-plan volume is already fully consumed")
    if counts[source] >= caps[source]:
        fail("ERR_SOURCE_MIX_EXCEEDED",
             "the effective cap for source %s is already consumed" % source)

    selection = new_row("selections", {
        "plan_id": plan["id"],
        "interaction_id": interaction["id"],
        "agent_id": agent_id,
        "assigned_evaluator_id": None,
        "source": source,
        "status": "SELECTED",
        "review_window_start": None,
        "review_window_end": None,
        "exclusion_reason": None,
    })
    derive.recompute_plan(plan)
    derive.recompute_interaction_sampled(interaction["id"])
    return created(view(selection))


@bp.post("/sample-selections/<selection_id>/assign")
@endpoint("QualityManager")
def assign_selection(selection_id):
    payload = body()
    evaluator_id = shape.want_string(payload, "assigned_evaluator_id")
    start_raw, start = shape.want_datetime(payload, "review_window_start")
    end_raw, end = shape.want_datetime(payload, "review_window_end")

    selection = require("selections", selection_id, "ERR_SELECTION_NOT_FOUND")
    evaluator = require("evaluators", evaluator_id, "ERR_EVALUATOR_NOT_FOUND")

    plan = get("plans", selection["plan_id"])
    if plan is None or plan["status"] != "OPEN":
        fail("ERR_PLAN_NOT_OPEN", "the selection's plan is not OPEN")
    if selection["status"] != "SELECTED":
        fail("ERR_SELECTION_NOT_ASSIGNABLE", "only a SELECTED selection may be assigned")

    interaction = get("interactions", selection["interaction_id"])
    consent_gate(interaction)

    if evaluator["calibration_status"] == "SUSPENDED":
        fail("ERR_EVALUATOR_NOT_CALIBRATED",
             "a SUSPENDED evaluator may not receive an assignment")

    if not end > start:
        fail("ERR_INVALID_TIME_RANGE",
             "review_window_end must be strictly after review_window_start")

    for other in rows("selections"):
        if other["id"] == selection["id"]:
            continue
        if other.get("assigned_evaluator_id") != evaluator["id"]:
            continue
        if other["status"] != "ASSIGNED":
            continue
        other_start = parse_dt(other["review_window_start"])
        other_end = parse_dt(other["review_window_end"])
        if other_start is None or other_end is None:
            continue
        # half-open [start, end): touching endpoints are legal (PRD 3.4)
        if start < other_end and other_start < end:
            fail("ERR_EVALUATOR_WINDOW_CONFLICT",
                 "the requested window overlaps a window this evaluator already holds")

    if calc.open_assignment_count(evaluator["id"]) >= int(evaluator["max_open_assignments"]):
        fail("ERR_EVALUATOR_CAPACITY_EXCEEDED",
             "the evaluator already holds their maximum open assignments")

    selection["status"] = "ASSIGNED"
    selection["assigned_evaluator_id"] = evaluator["id"]
    selection["review_window_start"] = start_raw
    selection["review_window_end"] = end_raw
    touch(selection)
    derive.recompute_evaluator(evaluator["id"])
    return ok(view(selection))


@bp.post("/sample-selections/<selection_id>/exclude")
@endpoint("QualityManager")
def exclude_selection(selection_id):
    payload = body()
    reason = shape.want_enum(payload, "exclusion_reason", EXCLUSION_REASONS)
    selection = require("selections", selection_id, "ERR_SELECTION_NOT_FOUND")

    plan = get("plans", selection["plan_id"])
    if plan is None or plan["status"] != "OPEN":
        fail("ERR_PLAN_NOT_OPEN", "the selection's plan is not OPEN")
    if selection["status"] in ("EVALUATED", "EXCLUDED"):
        fail("ERR_SELECTION_TERMINAL", "the selection has already reached a terminal state")

    evaluator_id = selection.get("assigned_evaluator_id")
    selection["status"] = "EXCLUDED"
    selection["exclusion_reason"] = reason
    selection["assigned_evaluator_id"] = None
    selection["review_window_start"] = None
    selection["review_window_end"] = None
    touch(selection)

    derive.recompute_plan(plan)
    derive.recompute_interaction_sampled(selection["interaction_id"])
    if evaluator_id is not None:
        derive.recompute_evaluator(evaluator_id)
    return ok(view(selection))


@bp.get("/sample-selections/<selection_id>")
@endpoint(*READ_ROLES)
def read_selection(selection_id):
    return ok(view(require("selections", selection_id, "ERR_SELECTION_NOT_FOUND")))


@bp.get("/sample-selections")
@endpoint(*READ_ROLES)
def list_selections():
    limit, offset = shape.pagination()
    plan_id = shape.query_str("plan_id")
    interaction_id = shape.query_str("interaction_id")
    agent_id = shape.query_str("agent_id")
    evaluator_id = shape.query_str("assigned_evaluator_id")
    status = shape.query_enum("status", SELECTION_STATUSES)
    source = shape.query_enum("source", SOURCES)
    items = sorted_rows(rows("selections"))
    if plan_id is not None:
        items = [s for s in items if s["plan_id"] == plan_id]
    if interaction_id is not None:
        items = [s for s in items if s["interaction_id"] == interaction_id]
    if agent_id is not None:
        items = [s for s in items if s["agent_id"] == agent_id]
    if evaluator_id is not None:
        items = [s for s in items if s.get("assigned_evaluator_id") == evaluator_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if source is not None:
        items = [s for s in items if s["source"] == source]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
