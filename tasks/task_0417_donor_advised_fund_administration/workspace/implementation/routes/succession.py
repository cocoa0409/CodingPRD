"""SuccessionPlan endpoints: create, read, confirm (PRD 3.8)."""
from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import serialize
from services.lookup import get_or_404, require_string, require_enum, filtered_sorted

bp = Blueprint("succession", __name__)

READ_ROLES = {"SponsorAdmin", "DonorAdvisor"}
PLAN_TYPES = {"SUCCESSOR_ADVISOR", "LEGACY_GRANTS"}


@bp.post("/daf/succession-plans")
def create_plan():
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    body = get_json_body()
    donor_account_id = require_string(body, "donor_account_id")
    plan_type = require_enum(body, "plan_type", PLAN_TYPES)
    beneficiaries = body.get("beneficiaries")
    if beneficiaries is None or not isinstance(beneficiaries, list):
        raise err("ERR_INVALID_REQUEST")

    with LOCK:
        account = get_or_404(db.accounts, donor_account_id)  # body FK existence
        # Owner-scope (PRD 3.8): creating a plan is owner-scoped.
        if user_id != account["primary_advisor_user_id"]:
            raise err("ERR_NOT_ACCOUNT_OWNER")

        normalized = _validate_beneficiaries(plan_type, beneficiaries)

        plan = common_create_fields()
        plan.update({
            "donor_account_id": donor_account_id,
            "plan_type": plan_type,
            "beneficiaries": normalized,
            "status": "DRAFT",
        })
        db.succession_plans[plan["id"]] = plan
    return object_response(serialize.succession_plan(plan), status=201)


@bp.get("/daf/succession-plans/<plan_id>")
def get_plan(plan_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    plan = get_or_404(db.succession_plans, plan_id)
    return object_response(serialize.succession_plan(plan))


@bp.get("/daf/succession-plans")
def list_plans():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.succession_plans, {
        "donor_account_id": request.args.get("donor_account_id"),
        "plan_type": request.args.get("plan_type"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.succession_plan(p) for p in page], meta)


@bp.post("/daf/succession-plans/<plan_id>/confirm")
def confirm_plan(plan_id):
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    with LOCK:
        plan = get_or_404(db.succession_plans, plan_id)
        account = db.accounts[plan["donor_account_id"]]
        # Owner-scope precedes state (PRD 3.8 / 3.10): confirming is owner-scoped.
        if user_id != account["primary_advisor_user_id"]:
            raise err("ERR_NOT_ACCOUNT_OWNER")
        if plan["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE")
        plan["status"] = "CONFIRMED"
        touch(plan)
    return object_response(serialize.succession_plan(plan))


def _validate_beneficiaries(plan_type, beneficiaries):
    """Validate and normalize the beneficiaries array.

    PRD 3.8: SUCCESSOR_ADVISOR names a successor_user_id; LEGACY_GRANTS names a
    list of { charity_id, share_bps } whose share_bps sum to exactly 10000.
    """
    if plan_type == "LEGACY_GRANTS":
        if not beneficiaries:
            raise err("ERR_INVALID_REQUEST")
        normalized = []
        total = 0
        for b in beneficiaries:
            if not isinstance(b, dict):
                raise err("ERR_INVALID_REQUEST")
            charity_id = b.get("charity_id")
            share_bps = b.get("share_bps")
            if not isinstance(charity_id, str) or not charity_id:
                raise err("ERR_INVALID_REQUEST")
            if not isinstance(share_bps, int) or isinstance(share_bps, bool):
                raise err("ERR_INVALID_REQUEST")
            # Body FK existence: each beneficiary charity must exist.
            get_or_404(db.charities, charity_id)
            normalized.append({"charity_id": charity_id, "share_bps": share_bps})
            total += share_bps
        # share_bps must sum to exactly 10000 (PRD 3.8).
        if total != 10000:
            raise err("ERR_SHARE_BPS_NOT_100")
        return normalized

    # SUCCESSOR_ADVISOR
    normalized = []
    for b in beneficiaries:
        if not isinstance(b, dict):
            raise err("ERR_INVALID_REQUEST")
        successor_user_id = b.get("successor_user_id")
        if not isinstance(successor_user_id, str) or not successor_user_id:
            raise err("ERR_INVALID_REQUEST")
        normalized.append({"successor_user_id": successor_user_id})
    return normalized
