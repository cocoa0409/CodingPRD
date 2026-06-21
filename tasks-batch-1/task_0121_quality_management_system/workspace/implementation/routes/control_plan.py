"""ControlPlan and ControlPlanRevision routes (PRD 3.1, 3.10, 2.7)."""
from flask import Blueprint, request

from common import require_fields, require_non_negative_int, require_string, stamp_create, touch
from db import db
from errors import (ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_REVISION_SEQUENCE, ERR_STALE_VERSION, err)
from middleware import (ROLE_INSPECTOR, ROLE_QUALITY_ENGINEER,
                        ROLE_QUALITY_MANAGER, authenticate, require_role)
from response import list_success, success
from services.helpers import get_or_404, paginate, paginate_args
from services.serializers import (control_plan_out, control_plan_revision_out,
                                  inspection_plan_out)

bp = Blueprint("control_plan", __name__)


@bp.route("/control-plans", methods=["POST"])
def create_control_plan():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "part_number"])
    require_string(body["name"], "name")
    require_string(body["part_number"], "part_number")

    rec = {
        "name": body["name"],
        "part_number": body["part_number"],
        "current_revision_no": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.control_plans[rec["id"]] = rec
    return success(control_plan_out(rec), status=201)


@bp.route("/control-plans/<rid>", methods=["GET"])
def get_control_plan(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER, ROLE_INSPECTOR})
    rec = get_or_404(db.control_plans, rid)
    return success(control_plan_out(rec))


@bp.route("/control-plan-revisions", methods=["POST"])
def create_revision():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4): control_plan_id and optional source_capa_id.
    control_plan_id = body.get("control_plan_id")
    if control_plan_id is not None and control_plan_id not in db.control_plans:
        raise err(ERR_FK_NOT_FOUND, "control_plan_id does not resolve")
    source_capa_id = body.get("source_capa_id")
    if source_capa_id is not None and source_capa_id not in db.capas:
        raise err(ERR_FK_NOT_FOUND, "source_capa_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["control_plan_id", "revision_no", "change_summary",
                          "expected_control_plan_version"])
    require_non_negative_int(body["revision_no"], "revision_no", minimum=1)
    require_string(body["change_summary"], "change_summary")
    expected_version = body["expected_control_plan_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_control_plan_version must be an integer")

    plan = db.control_plans[control_plan_id]

    # OCC check (PRD 2.7): expected_control_plan_version must match current
    # ControlPlan.version, else ERR_STALE_VERSION (412).
    if expected_version != plan["version"]:
        raise err(ERR_STALE_VERSION, "Stale control plan version")

    # revision_no must equal current_revision_no + 1 (PRD 3.10).
    if body["revision_no"] != plan["current_revision_no"] + 1:
        raise err(ERR_REVISION_SEQUENCE, "revision_no must be current_revision_no + 1")

    rec = {
        "control_plan_id": control_plan_id,
        "revision_no": body["revision_no"],
        "change_summary": body["change_summary"],
        "source_capa_id": source_capa_id,
        "status": "DRAFT",
        "approved_by_personnel_id": None,
    }
    stamp_create(rec)
    db.control_plan_revisions[rec["id"]] = rec

    # A successful create advances the control plan's version (PRD 2.7/3.10).
    touch(plan)

    return success(control_plan_revision_out(rec), status=201)


@bp.route("/control-plans/<rid>/revisions", methods=["GET"])
def list_revisions(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    get_or_404(db.control_plans, rid)
    limit, offset = paginate_args()
    matches = [r for r in db.control_plan_revisions.values()
               if r["control_plan_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([control_plan_revision_out(r) for r in page],
                        limit, offset, total)


@bp.route("/control-plan-revisions/<rid>/approve", methods=["POST"])
def approve_revision(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    rec = get_or_404(db.control_plan_revisions, rid)

    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Revision is not DRAFT")

    plan = db.control_plans[rec["control_plan_id"]]
    # revision_no must equal current_revision_no + 1 (PRD 3.10).
    if rec["revision_no"] != plan["current_revision_no"] + 1:
        raise err(ERR_REVISION_SEQUENCE, "revision_no must be current_revision_no + 1")

    # Supersede any prior APPROVED revision of the same plan (PRD 3.10).
    for other in db.control_plan_revisions.values():
        if (other["control_plan_id"] == plan["id"] and other["status"] == "APPROVED"
                and other["id"] != rec["id"]):
            other["status"] = "SUPERSEDED"
            touch(other)

    rec["status"] = "APPROVED"
    rec["approved_by_personnel_id"] = auth.user_id
    touch(rec)

    # Set parent current_revision_no (PRD 3.10).
    plan["current_revision_no"] = rec["revision_no"]
    touch(plan)

    # Cascade needs_review=true to every inspection plan on this control plan.
    for ip in db.inspection_plans.values():
        if ip["control_plan_id"] == plan["id"]:
            ip["needs_review"] = True
            touch(ip)

    return success(control_plan_revision_out(rec))


@bp.route("/control-plans/<rid>/inspection-plans", methods=["GET"])
def list_control_plan_inspection_plans(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_INSPECTOR})
    get_or_404(db.control_plans, rid)
    limit, offset = paginate_args()
    matches = [ip for ip in db.inspection_plans.values()
               if ip["control_plan_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([inspection_plan_out(ip) for ip in page],
                        limit, offset, total)
