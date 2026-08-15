"""BackfillPlan endpoints: approval with provisional coverage, compaction
recording, erosion verification with final coverage, and completion."""

from decimal import Decimal

from flask import Blueprint, g

from db import store, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_COMPACTION_BELOW_SPEC, ERR_EROSION_COVERAGE_INSUFFICIENT,
                    ERR_FORBIDDEN)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_backfill_plan
from services import get_project, get_backfill_plan, children, MIN_FINAL_COVERAGE
from util import req_int, req_number, round4

bp = Blueprint("backfill", __name__)

BACKFILL_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "StructuralEngineer", "MunicipalInspector")
BACKFILL_ACTIONS = ("APPROVE", "RECORD_COMPACTION", "VERIFY_EROSION", "COMPLETE")
BACKFILL_ACTION_ROLES = {
    "APPROVE": ("StructuralEngineer",),
    "RECORD_COMPACTION": ("SiteSupervisor",),
    "VERIFY_EROSION": ("MunicipalInspector",),
    "COMPLETE": ("SiteSupervisor",),
}


@bp.post("/demolition/projects/<pid>/backfill-plans")
@require_roles("SiteSupervisor")
def create_backfill_plan(pid):
    b = body()
    design_area = req_int(b, "design_disturbed_area_sqft", minimum=1)
    planned_protected = req_int(b, "planned_protected_area_sqft", minimum=0)
    fill_volume = req_int(b, "fill_volume_cu_yd", minimum=1)
    required_compaction = req_number(b, "required_compaction_pct")
    if required_compaction <= 0:
        raise err(ERR_VALIDATION, "required_compaction_pct must be > 0")
    project = get_project(pid)

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "design_disturbed_area_sqft": design_area,
        "planned_protected_area_sqft": planned_protected,
        "fill_volume_cu_yd": fill_volume,
        "required_compaction_pct": required_compaction,
        "status": "DRAFT",
        "provisional_coverage_ratio": Decimal("0"),
        "compaction_pct_achieved": None,
        "measured_disturbed_area_sqft": None,
        "measured_protected_area_sqft": None,
        "final_coverage_ratio": Decimal("0"),
    })
    store.backfill_plans[rec["id"]] = rec
    return success(ser_backfill_plan(rec), status=201)


@bp.get("/demolition/projects/<pid>/backfill-plans")
@require_roles(*BACKFILL_READ_ROLES)
def list_backfill_plans(pid):
    project = get_project(pid)
    return list_response(children(store.backfill_plans, "project_id", project["id"]),
                         ser_backfill_plan)


@bp.post("/demolition/backfill-plans/<bid>/transition")
@require_roles("SiteSupervisor", "StructuralEngineer", "MunicipalInspector")
def backfill_transition(bid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in BACKFILL_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    compaction = None
    if "compaction_pct" in b and b["compaction_pct"] is not None:
        compaction = req_number(b, "compaction_pct")
    measured_disturbed = None
    if "measured_disturbed_area_sqft" in b and b["measured_disturbed_area_sqft"] is not None:
        measured_disturbed = req_int(b, "measured_disturbed_area_sqft", minimum=1)
    measured_protected = None
    if "measured_protected_area_sqft" in b and b["measured_protected_area_sqft"] is not None:
        measured_protected = req_int(b, "measured_protected_area_sqft", minimum=0)

    plan = get_backfill_plan(bid)
    if g.role not in BACKFILL_ACTION_ROLES[action]:
        raise err(ERR_FORBIDDEN, "role not permitted for this action")
    status = plan["status"]

    if action == "APPROVE":
        if status != "DRAFT":
            raise err(ERR_INVALID_STATE, "APPROVE requires DRAFT")
        plan["provisional_coverage_ratio"] = round4(
            Decimal(plan["planned_protected_area_sqft"]) / Decimal(plan["design_disturbed_area_sqft"]))
        plan["status"] = "APPROVED"
    elif action == "RECORD_COMPACTION":
        if status != "APPROVED":
            raise err(ERR_INVALID_STATE, "RECORD_COMPACTION requires APPROVED")
        if compaction is None:
            raise err(ERR_VALIDATION, "compaction_pct is required")
        if compaction < plan["required_compaction_pct"]:
            raise err(ERR_COMPACTION_BELOW_SPEC, "compaction below specification")
        plan["compaction_pct_achieved"] = compaction
        plan["status"] = "COMPACTION_VERIFIED"
    elif action == "VERIFY_EROSION":
        if status != "COMPACTION_VERIFIED":
            raise err(ERR_INVALID_STATE, "VERIFY_EROSION requires COMPACTION_VERIFIED")
        if measured_disturbed is None or measured_protected is None:
            raise err(ERR_VALIDATION,
                      "measured_disturbed_area_sqft and measured_protected_area_sqft are required")
        final_ratio = round4(Decimal(measured_protected) / Decimal(measured_disturbed))
        if final_ratio < MIN_FINAL_COVERAGE:
            raise err(ERR_EROSION_COVERAGE_INSUFFICIENT, "final coverage below 0.9000")
        plan["measured_disturbed_area_sqft"] = measured_disturbed
        plan["measured_protected_area_sqft"] = measured_protected
        plan["final_coverage_ratio"] = final_ratio
        plan["status"] = "EROSION_VERIFIED"
    else:  # COMPLETE
        if status != "EROSION_VERIFIED":
            raise err(ERR_INVALID_STATE, "COMPLETE requires EROSION_VERIFIED")
        plan["status"] = "COMPLETE"

    touch(plan)
    return success(ser_backfill_plan(plan))
