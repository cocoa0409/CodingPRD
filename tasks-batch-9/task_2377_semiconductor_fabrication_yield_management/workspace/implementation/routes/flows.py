"""Process flows, steps, recipes, engineering change notices and SPC charts."""
from flask import Blueprint, g

import calc
import clock
from auth import ALL_ROLES, require
from db import db, need, new_row, ordered, touch
from errors import fail
from response import ok
from routes.common import matches, paged
from services import cascades
from util import r2
from validate import (PRODUCT_FAMILIES, TOOL_TYPES, body, q_enum, q_str, v_bool,
                      v_enum, v_int, v_num, v_str)

bp = Blueprint("flows", __name__)

FLOW_STATUSES = ("DRAFT", "RELEASED", "OBSOLETE")
RECIPE_STATUSES = ("QUALIFIED", "RESTRICTED")
CHANGE_CLASSES = ("MINOR", "MAJOR", "CRITICAL")
CR_STATUSES = ("SUBMITTED", "REVISION_REQUESTED", "APPROVED", "IMPLEMENTED", "REJECTED")
CHART_STATUSES = ("MONITORING", "SUSPENDED")


def flow_steps(flow_id):
    return [s for s in ordered(db.process_steps.values()) if s["flow_id"] == flow_id]


def recompute_flow(flow):
    steps = flow_steps(flow["id"])
    flow["step_count"] = len(steps)
    flow["total_standard_hours"] = r2(sum(s["standard_hours"] for s in steps))


# ------------------------------------------------------------- process flows

@bp.post("/fab/process-flows")
@require("ProcessEngineer")
def create_flow():
    data = body()
    flow_code = v_str(data, "flow_code", min_len=1, max_len=32)
    product_family = v_enum(data, "product_family", PRODUCT_FAMILIES)
    if any(f["flow_code"] == flow_code for f in db.process_flows.values()):
        fail("ERR_DUPLICATE_CODE", "flow_code '%s' already exists" % flow_code)
    row = new_row({
        "flow_code": flow_code,
        "product_family": product_family,
        "revision": 1,
        "status": "DRAFT",
        "step_count": 0,
        "total_standard_hours": 0.0,
        "released_at": None,
        "superseded_by_flow_id": None,
        "_release_rejected": False,
    })
    db.process_flows[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/process-flows")
@require(*ALL_ROLES)
def list_flows():
    filters = {
        "product_family": q_enum("product_family", PRODUCT_FAMILIES),
        "status": q_enum("status", FLOW_STATUSES),
        "superseded_by_flow_id": q_str("superseded_by_flow_id"),
    }
    return paged([f for f in db.process_flows.values() if matches(f, filters)])


@bp.get("/fab/process-flows/<flow_id>")
@require(*ALL_ROLES)
def read_flow(flow_id):
    return ok(need(db.process_flows, flow_id, "ERR_PROCESS_FLOW_NOT_FOUND"))


@bp.post("/fab/process-flows/<flow_id>/steps")
@require("ProcessEngineer")
def create_step(flow_id):
    data = body()
    recipe_id = v_str(data, "recipe_id")
    step_seq = v_int(data, "step_seq", minimum=1)
    step_name = v_str(data, "step_name")
    standard_hours = v_num(data, "standard_hours", gt=0)
    metrology_required = v_bool(data, "metrology_required", default=False)
    rework_target_step_id = v_str(data, "rework_target_step_id", required=False, default=None)

    flow = need(db.process_flows, flow_id, "ERR_PROCESS_FLOW_NOT_FOUND")
    need(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    if rework_target_step_id is not None:
        need(db.process_steps, rework_target_step_id, "ERR_PROCESS_STEP_NOT_FOUND")

    if flow["status"] != "DRAFT":
        fail("ERR_FLOW_NOT_DRAFT", "Flow is %s, not DRAFT" % flow["status"])
    if any(s["flow_id"] == flow_id and s["step_seq"] == step_seq
           for s in db.process_steps.values()):
        fail("ERR_DUPLICATE_CODE", "step_seq %d already exists in this flow" % step_seq)

    row = new_row({
        "flow_id": flow_id,
        "recipe_id": recipe_id,
        "step_seq": step_seq,
        "step_name": step_name,
        "standard_hours": r2(standard_hours),
        "metrology_required": metrology_required,
        "rework_target_step_id": rework_target_step_id,
    })
    db.process_steps[row["id"]] = row

    recompute_flow(flow)
    if flow.get("_release_rejected"):
        flow["revision"] = flow["revision"] + 1
        flow["_release_rejected"] = False
    touch(flow)
    return ok(row, 201)


@bp.post("/fab/process-flows/<flow_id>/release")
@require("ProcessEngineer")
def release_flow(flow_id):
    data = body()
    supersedes_flow_id = v_str(data, "supersedes_flow_id", required=False, default=None)

    flow = need(db.process_flows, flow_id, "ERR_PROCESS_FLOW_NOT_FOUND")
    superseded = None
    if supersedes_flow_id is not None:
        superseded = need(db.process_flows, supersedes_flow_id, "ERR_PROCESS_FLOW_NOT_FOUND")

    if flow["status"] != "DRAFT":
        flow["_release_rejected"] = True
        fail("ERR_FLOW_NOT_DRAFT", "Flow is %s, not DRAFT" % flow["status"])
    if superseded is not None and superseded["status"] != "RELEASED":
        flow["_release_rejected"] = True
        fail("ERR_FLOW_NOT_RELEASED", "Superseded flow is %s, not RELEASED" % superseded["status"])
    if superseded is not None and superseded["product_family"] != flow["product_family"]:
        flow["_release_rejected"] = True
        fail("ERR_PRODUCT_FAMILY_MISMATCH",
             "Superseded flow belongs to product family %s" % superseded["product_family"])

    steps = flow_steps(flow_id)
    if not steps:
        flow["_release_rejected"] = True
        fail("ERR_FLOW_HAS_NO_STEPS", "Flow has no steps")
    for step in steps:
        recipe = db.recipes.get(step["recipe_id"])
        if recipe is None or recipe["status"] != "QUALIFIED":
            flow["_release_rejected"] = True
            fail("ERR_FLOW_HAS_NO_STEPS", "Step '%s' resolves a recipe that is not QUALIFIED"
                 % step["step_name"])

    recompute_flow(flow)
    flow["released_at"] = clock.now()
    flow["status"] = "RELEASED"
    flow["_release_rejected"] = False
    touch(flow)

    if superseded is not None:
        superseded["status"] = "OBSOLETE"
        superseded["superseded_by_flow_id"] = flow["id"]
        touch(superseded)
    return ok(flow)


# ------------------------------------------------------------- process steps

@bp.get("/fab/process-steps")
@require(*ALL_ROLES)
def list_steps():
    filters = {
        "flow_id": q_str("flow_id"),
        "recipe_id": q_str("recipe_id"),
        "rework_target_step_id": q_str("rework_target_step_id"),
    }
    return paged([s for s in db.process_steps.values() if matches(s, filters)])


@bp.get("/fab/process-steps/<step_id>")
@require(*ALL_ROLES)
def read_step(step_id):
    return ok(need(db.process_steps, step_id, "ERR_PROCESS_STEP_NOT_FOUND"))


# ------------------------------------------------------------------- recipes

@bp.post("/fab/recipes")
@require("ProcessEngineer")
def create_recipe():
    data = body()
    recipe_code = v_str(data, "recipe_code", min_len=1, max_len=32)
    tool_type = v_enum(data, "tool_type", TOOL_TYPES)
    target_value = v_num(data, "target_value", gt=0)
    qual_expiry_days = v_int(data, "qual_expiry_days", required=False, minimum=1, default=90)
    if any(r["recipe_code"] == recipe_code for r in db.recipes.values()):
        fail("ERR_DUPLICATE_CODE", "recipe_code '%s' already exists" % recipe_code)
    row = new_row({
        "recipe_code": recipe_code,
        "tool_type": tool_type,
        "target_value": r2(target_value),
        "qual_expiry_days": qual_expiry_days,
        "revision": 1,
        "status": "QUALIFIED",
        "restricted_reason": "NONE",
    })
    db.recipes[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/recipes")
@require(*ALL_ROLES)
def list_recipes():
    filters = {
        "tool_type": q_enum("tool_type", TOOL_TYPES),
        "status": q_enum("status", RECIPE_STATUSES),
    }
    return paged([r for r in db.recipes.values() if matches(r, filters)])


@bp.get("/fab/recipes/<recipe_id>")
@require(*ALL_ROLES)
def read_recipe(recipe_id):
    return ok(need(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND"))


# --------------------------------------------------- engineering change notices

@bp.post("/fab/recipes/<recipe_id>/change-requests")
@require("ProcessEngineer")
def create_change_request(recipe_id):
    data = body()
    change_class = v_enum(data, "change_class", CHANGE_CLASSES)
    proposed_target = v_num(data, "proposed_target", gt=0)
    justification = v_str(data, "justification")
    recipe = need(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")

    proposed_target = r2(proposed_target)
    impact, score, requal = calc.recipe_change_risk(recipe, change_class, proposed_target)
    row = new_row({
        "recipe_id": recipe_id,
        "change_class": change_class,
        "proposed_target": proposed_target,
        "justification": justification,
        "author_user_id": g.user_id,
        "approver_user_id": None,
        "status": "SUBMITTED",
        "revision_round": 0,
        "risk_score": score,
        "impact_lot_count": impact,
        "requires_full_requal": requal,
        "pinned_recipe_revision": None,
    })
    db.change_requests[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/change-requests")
@require("ProcessEngineer", "QualityManager", "YieldEngineer")
def list_change_requests():
    filters = {
        "recipe_id": q_str("recipe_id"),
        "status": q_enum("status", CR_STATUSES),
    }
    return paged([c for c in db.change_requests.values() if matches(c, filters)])


@bp.get("/fab/change-requests/<cr_id>")
@require("ProcessEngineer", "QualityManager", "YieldEngineer")
def read_change_request(cr_id):
    return ok(need(db.change_requests, cr_id, "ERR_CHANGE_REQUEST_NOT_FOUND"))


@bp.post("/fab/change-requests/<cr_id>/request-revision")
@require("QualityManager")
def request_revision(cr_id):
    data = body()
    v_str(data, "reviewer_comment")
    cr = need(db.change_requests, cr_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    if cr["status"] != "SUBMITTED":
        fail("ERR_CHANGE_REQUEST_INVALID_STATE",
             "Change notice is %s, not SUBMITTED" % cr["status"])
    if cr["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        cr["status"] = "REJECTED"
    else:
        cr["status"] = "REVISION_REQUESTED"
    touch(cr)
    return ok(cr)


@bp.post("/fab/change-requests/<cr_id>/resubmit")
@require("ProcessEngineer")
def resubmit(cr_id):
    data = body()
    change_class = v_enum(data, "change_class", CHANGE_CLASSES)
    proposed_target = v_num(data, "proposed_target", gt=0)
    justification = v_str(data, "justification")
    cr = need(db.change_requests, cr_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    if g.user_id != cr["author_user_id"]:
        fail("ERR_UNAUTHORIZED", "Only the original author may resubmit this change notice")
    if cr["status"] != "REVISION_REQUESTED":
        fail("ERR_CHANGE_REQUEST_INVALID_STATE",
             "Change notice is %s, not REVISION_REQUESTED" % cr["status"])

    recipe = db.recipes[cr["recipe_id"]]
    proposed_target = r2(proposed_target)
    impact, score, requal = calc.recipe_change_risk(recipe, change_class, proposed_target)
    cr["change_class"] = change_class
    cr["proposed_target"] = proposed_target
    cr["justification"] = justification
    cr["revision_round"] = cr["revision_round"] + 1
    cr["impact_lot_count"] = impact
    cr["risk_score"] = score
    cr["requires_full_requal"] = requal
    cr["status"] = "SUBMITTED"
    touch(cr)
    return ok(cr)


@bp.post("/fab/change-requests/<cr_id>/approve")
@require("QualityManager")
def approve(cr_id):
    data = body()
    expected_recipe_version = v_int(data, "expected_recipe_version", minimum=0)
    cr = need(db.change_requests, cr_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    recipe = db.recipes[cr["recipe_id"]]

    if g.user_id == cr["author_user_id"]:
        fail("ERR_SOD_SELF_APPROVAL", "The author of a change notice may not approve it")
    if expected_recipe_version != recipe["version"]:
        fail("ERR_STALE_RECIPE_VERSION",
             "expected_recipe_version %d does not match recipe version %d"
             % (expected_recipe_version, recipe["version"]))
    if cr["status"] != "SUBMITTED":
        fail("ERR_CHANGE_REQUEST_INVALID_STATE",
             "Change notice is %s, not SUBMITTED" % cr["status"])

    cr["approver_user_id"] = g.user_id
    cr["pinned_recipe_revision"] = recipe["revision"]
    cr["status"] = "APPROVED"
    touch(cr)

    if recipe["status"] == "QUALIFIED":
        recipe["status"] = "RESTRICTED"
        recipe["restricted_reason"] = "ECN_PENDING_IMPLEMENTATION"
    touch(recipe)
    return ok(cr)


@bp.post("/fab/change-requests/<cr_id>/implement")
@require("ProcessEngineer")
def implement(cr_id):
    body()
    cr = need(db.change_requests, cr_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    if cr["status"] != "APPROVED":
        fail("ERR_CHANGE_REQUEST_INVALID_STATE",
             "Change notice is %s, not APPROVED" % cr["status"])
    recipe = db.recipes[cr["recipe_id"]]
    if recipe["revision"] != cr["pinned_recipe_revision"]:
        fail("ERR_PINNED_REVISION_STALE",
             "Recipe revision %d no longer matches the pinned revision %s"
             % (recipe["revision"], cr["pinned_recipe_revision"]))

    cr["status"] = "IMPLEMENTED"
    touch(cr)

    recipe["target_value"] = cr["proposed_target"]
    recipe["revision"] = recipe["revision"] + 1
    recipe["status"] = "QUALIFIED"
    recipe["restricted_reason"] = "NONE"
    touch(recipe)

    if cr["requires_full_requal"]:
        cascades.requalification_cascade(recipe["id"])
    return ok(cr)


# ---------------------------------------------------------------- SPC charts

@bp.post("/fab/spc-charts")
@require("ProcessEngineer", "QualityManager")
def create_chart():
    data = body()
    step_id = v_str(data, "step_id")
    param_name = v_str(data, "param_name")
    target = v_num(data, "target")
    sigma = v_num(data, "sigma", gt=0)
    usl = v_num(data, "usl")
    lsl = v_num(data, "lsl")
    ucl = v_num(data, "ucl")
    lcl = v_num(data, "lcl")
    target, sigma = r2(target), r2(sigma)
    usl, lsl, ucl, lcl = r2(usl), r2(lsl), r2(ucl), r2(lcl)
    if not (lsl < lcl < target < ucl < usl):
        fail("ERR_VALIDATION", "Limits must satisfy lsl < lcl < target < ucl < usl")

    need(db.process_steps, step_id, "ERR_PROCESS_STEP_NOT_FOUND")
    row = new_row({
        "step_id": step_id,
        "param_name": param_name,
        "target": target,
        "sigma": sigma,
        "usl": usl,
        "lsl": lsl,
        "ucl": ucl,
        "lcl": lcl,
        "status": "MONITORING",
        "consecutive_same_side_count": 0,
        "last_side": "NONE",
        "violation_count": 0,
    })
    db.spc_charts[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/spc-charts")
@require("ProcessEngineer", "QualityManager", "YieldEngineer", "Operator")
def list_charts():
    filters = {
        "step_id": q_str("step_id"),
        "status": q_enum("status", CHART_STATUSES),
    }
    return paged([c for c in db.spc_charts.values() if matches(c, filters)])


@bp.get("/fab/spc-charts/<chart_id>")
@require("ProcessEngineer", "QualityManager", "YieldEngineer", "Operator")
def read_chart(chart_id):
    return ok(need(db.spc_charts, chart_id, "ERR_SPC_CHART_NOT_FOUND"))
