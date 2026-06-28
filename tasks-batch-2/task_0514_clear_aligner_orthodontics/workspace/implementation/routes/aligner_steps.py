"""AlignerStep endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import serialize, touch
from response import object_response, array_response
from services.listing import paginate
from services.store import get_step, get_case
from validation import parse_pagination

bp = Blueprint("aligner_steps", __name__)


@bp.route("/aligner-steps/<sid>", methods=["GET"])
def fetch_step(sid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    rec = get_step(sid)
    return object_response(serialize(rec), status=200)


@bp.route("/aligner-steps", methods=["GET"])
def list_steps():
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    supersedes_step_id = request.args.get("supersedes_step_id")
    status = request.args.get("status")
    records = list(db.aligner_steps.values())
    if case_id is not None:
        records = [s for s in records if s["case_id"] == case_id]
    if supersedes_step_id is not None:
        records = [s for s in records
                   if s["supersedes_step_id"] == supersedes_step_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


def _prior_step(case_id, step_index):
    if step_index <= 1:
        return None
    for s in db.aligner_steps.values():
        if s["case_id"] == case_id and s["step_index"] == step_index - 1:
            return s
    return None


@bp.route("/aligner-steps/<sid>/start-production", methods=["POST"])
def start_production(sid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    step = get_step(sid)
    case = get_case(step["case_id"])
    if step["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Step must be PLANNED to start production.")
    if case["status"] not in ("ACTIVE", "REFINEMENT"):
        raise err("ERR_INVALID_STATE",
                  "Case must be ACTIVE or REFINEMENT to start production.")
    # strict in-order: the immediately-prior step_index step (if any) is SHIPPED
    prior = _prior_step(case["id"], step["step_index"])
    if prior is not None and prior["status"] != "SHIPPED":
        raise err("ERR_STEP_ORDER_VIOLATION",
                  "Prior step must be SHIPPED before starting this step.")
    step["status"] = "IN_PRODUCTION"
    touch(step)
    return object_response(serialize(step), status=200)


@bp.route("/aligner-steps/<sid>/complete-production", methods=["POST"])
def complete_production(sid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    step = get_step(sid)
    if step["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE",
                  "Step must be IN_PRODUCTION to complete production.")
    step["status"] = "MANUFACTURED"
    touch(step)
    return object_response(serialize(step), status=200)
