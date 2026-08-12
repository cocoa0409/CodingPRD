"""Plan endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, paginate
from response import success_object, success_list
from services import audit
from services.state import get_plan
from services.util import new_id, now_iso, today, touch

bp = Blueprint("plans", __name__)

PLAN_LEVERS = (
    "max_loans_outstanding", "min_loan_amount_cents", "max_loan_amount_cents",
    "max_term_months", "interest_rate_bps", "day_count_convention",
    "allows_refinance", "refinance_min_months_since_disbursement",
    "hardship_suspension_months", "substantiation_standard",
    "withholding_rate_bps", "allowed_hardship_reasons",
    "loan_approval_chain", "hardship_approval_chain",
)

PLAN_DEFAULTS = {
    "max_loans_outstanding": 1,
    "min_loan_amount_cents": 100000,
    "max_loan_amount_cents": 5000000,
    "max_term_months": 60,
    "interest_rate_bps": 500,
    "day_count_convention": "THIRTY_360",
    "allows_refinance": False,
    "refinance_min_months_since_disbursement": 12,
    "hardship_suspension_months": 6,
    "substantiation_standard": "FULL_DOCUMENTATION",
    "withholding_rate_bps": 2000,
    "allowed_hardship_reasons": ["MEDICAL", "FUNERAL", "EVICTION", "TUITION",
                                  "HOME_PURCHASE", "DISASTER"],
    "loan_approval_chain": ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"],
    "hardship_approval_chain": ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"],
}

DAY_COUNT_CONVENTIONS = ("THIRTY_360", "ACT_360")
SUBSTANTIATION_STANDARDS = ("FULL_DOCUMENTATION", "SELF_CERTIFY")
APPROVER_ROLES = ("PLAN_SPONSOR", "RECORDKEEPER_ADMIN")
HARDSHIP_REASONS = ("MEDICAL", "FUNERAL", "EVICTION", "TUITION", "HOME_PURCHASE", "DISASTER")


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


def _validate_levers(body, partial=False):
    """Validate plan policy lever types/enums. Returns dict of cleaned lever values."""
    out = {}
    for lever in PLAN_LEVERS:
        if lever not in body:
            continue
        v = body[lever]
        if lever in ("max_loans_outstanding", "min_loan_amount_cents",
                     "max_loan_amount_cents", "max_term_months",
                     "interest_rate_bps", "refinance_min_months_since_disbursement",
                     "hardship_suspension_months", "withholding_rate_bps"):
            if not isinstance(v, int) or isinstance(v, bool):
                raise _bad(f"{lever} must be an integer")
            out[lever] = v
        elif lever == "allows_refinance":
            if not isinstance(v, bool):
                raise _bad("allows_refinance must be a boolean")
            out[lever] = v
        elif lever == "day_count_convention":
            if v not in DAY_COUNT_CONVENTIONS:
                raise _bad("day_count_convention must be THIRTY_360 or ACT_360")
            out[lever] = v
        elif lever == "substantiation_standard":
            if v not in SUBSTANTIATION_STANDARDS:
                raise _bad("substantiation_standard must be FULL_DOCUMENTATION or SELF_CERTIFY")
            out[lever] = v
        elif lever == "allowed_hardship_reasons":
            if not isinstance(v, list) or any(r not in HARDSHIP_REASONS for r in v):
                raise _bad("allowed_hardship_reasons must be a list of safe-harbor reasons")
            out[lever] = list(v)
        elif lever in ("loan_approval_chain", "hardship_approval_chain"):
            if not isinstance(v, list) or not v or any(r not in APPROVER_ROLES for r in v):
                raise _bad(f"{lever} must be a non-empty list of approver roles")
            out[lever] = list(v)
    return out


@bp.route("/plans", methods=["POST"])
def create_plan():
    user_id, role = require_roles("RecordkeeperAdmin")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise _bad("name is required")
    levers = _validate_levers(body)
    plan = {"id": new_id(), "name": name, "status": "ACTIVE"}
    for lever in PLAN_LEVERS:
        default = PLAN_DEFAULTS[lever]
        plan[lever] = levers.get(lever, list(default) if isinstance(default, list) else default)
    plan["created_at"] = now_iso()
    plan["updated_at"] = plan["created_at"]
    plan["version"] = 1
    db.plans[plan["id"]] = plan
    audit.append(plan["id"], role, user_id, "PLAN_CREATED", "Plan", plan["id"],
                 {"name": name})
    return success_object(plan, status=201)


@bp.route("/plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    plan = get_plan(plan_id)
    return success_object(plan)


@bp.route("/plans/<plan_id>/policy", methods=["PUT"])
def update_policy(plan_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    plan = get_plan(plan_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    if "expected_plan_version" not in body:
        raise _bad("expected_plan_version is required")
    if not isinstance(body["expected_plan_version"], int) or \
            isinstance(body["expected_plan_version"], bool):
        raise _bad("expected_plan_version must be an integer")
    levers = _validate_levers(body)
    # OCC check
    if body["expected_plan_version"] != plan["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_plan_version does not match current plan version", 412)
    for k, v in levers.items():
        plan[k] = v
    touch(plan)
    audit.append(plan["id"], role, user_id, "PLAN_POLICY_UPDATED", "Plan", plan["id"],
                 {"updated": sorted(levers.keys())})
    return success_object(plan)


@bp.route("/plans/<plan_id>/freeze", methods=["POST"])
def freeze_plan(plan_id):
    user_id, role = require_roles("PlanSponsor", "RecordkeeperAdmin")
    plan = get_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot freeze a plan in {plan['status']}", 409)
    plan["status"] = "FROZEN"
    touch(plan)
    audit.append(plan["id"], role, user_id, "PLAN_FROZEN", "Plan", plan["id"], {})
    return success_object(plan)


@bp.route("/plans/<plan_id>/unfreeze", methods=["POST"])
def unfreeze_plan(plan_id):
    user_id, role = require_roles("PlanSponsor", "RecordkeeperAdmin")
    plan = get_plan(plan_id)
    if plan["status"] != "FROZEN":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot unfreeze a plan in {plan['status']}", 409)
    plan["status"] = "ACTIVE"
    touch(plan)
    audit.append(plan["id"], role, user_id, "PLAN_UNFROZEN", "Plan", plan["id"], {})
    return success_object(plan)


def _sorted_created(items):
    return sorted(items, key=lambda r: r["created_at"])


@bp.route("/plans/<plan_id>/participants", methods=["GET"])
def list_plan_participants(plan_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    get_plan(plan_id)
    items = _sorted_created([p for p in db.participants.values() if p["plan_id"] == plan_id])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/plans/<plan_id>/loans", methods=["GET"])
def list_plan_loans(plan_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    get_plan(plan_id)
    items = _sorted_created([l for l in db.loans.values() if l["plan_id"] == plan_id])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/plans/<plan_id>/hardship-requests", methods=["GET"])
def list_plan_hardships(plan_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    get_plan(plan_id)
    items = _sorted_created([h for h in db.hardship_requests.values()
                             if h["plan_id"] == plan_id])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/plans/<plan_id>/approval-tasks", methods=["GET"])
def list_plan_approval_tasks(plan_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    get_plan(plan_id)
    items = _sorted_created([t for t in db.approval_tasks.values() if t["plan_id"] == plan_id])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/plans/<plan_id>/audit-events", methods=["GET"])
def list_plan_audit_events(plan_id):
    require_roles("RecordkeeperAdmin", "Auditor")
    get_plan(plan_id)
    items = _sorted_created([e for e in db.audit_events.values() if e["plan_id"] == plan_id])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)
