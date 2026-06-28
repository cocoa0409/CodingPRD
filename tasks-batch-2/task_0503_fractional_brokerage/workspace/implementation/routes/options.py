"""Options approval endpoints (PRD §3.8, §4)."""
from flask import Blueprint, request

import constants
import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import _base_full, options_approval_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_account, get_options_approval,
                           paginate, page_slice)
from services.account import recompute_account

bp = Blueprint("options", __name__)


def _suitability_cap(experience_years, net_worth_cents):
    """Options suitability cap (PRD §3.8). Net-worth gate matters only at level 3.
      3 if experience>=3 AND net_worth>=$100,000 (10,000,000 cents)
      else 2 if experience>=2
      else 1 if experience>=1
      else 0"""
    if experience_years >= 3 and net_worth_cents >= 10_000_000:
        return 3
    if experience_years >= 2:
        return 2
    if experience_years >= 1:
        return 1
    return 0


@bp.post("/options-approvals")
def apply_options():
    user_id, role = get_identity()
    require_role(role, {"AccountHolder"})
    body = get_json_body()

    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "account_id is required")
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    requested_level = body.get("requested_level")
    if not isinstance(requested_level, int) or isinstance(requested_level, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "requested_level is required")
    if requested_level not in (1, 2, 3):
        raise errors.err(errors.ERR_OPTIONS_LEVEL_TOO_HIGH, "requested_level must be 1..3")

    experience = body.get("stated_experience_years")
    if not isinstance(experience, int) or isinstance(experience, bool) or experience < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "stated_experience_years must be a non-negative integer")

    net_worth = body.get("liquid_net_worth_cents")
    if not isinstance(net_worth, int) or isinstance(net_worth, bool) or net_worth < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "liquid_net_worth_cents must be a non-negative integer")

    rec = _base_full()
    rec.update({
        "account_id": account_id,
        "requested_level": requested_level,
        "stated_experience_years": experience,
        "liquid_net_worth_cents": net_worth,
        "granted_level": 0,
        "status": "SUBMITTED",
    })
    db.options_approvals[rec["id"]] = rec
    return object_response(options_approval_dict(rec), 201)


@bp.get("/accounts/<account_id>/options-approvals")
def list_options(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ComplianceOfficer"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    status = request.args.get("status")
    items = [o for o in db.options_approvals.values() if o["account_id"] == account_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([options_approval_dict(o) for o in page], limit, offset, total)


@bp.post("/options-approvals/<oa_id>/decide")
def decide_options(oa_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    oa = get_options_approval(oa_id)
    body = get_json_body()

    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")

    expected_version = body.get("expected_account_version")
    if expected_version is None or not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_account_version is required")

    acct = db.accounts.get(oa["account_id"])

    # OCC (PRD §2.7 gate 5) precedes state (gate 6)
    if expected_version != acct["version"]:
        raise errors.err(errors.ERR_STALE_ACCOUNT_VERSION, "Account version mismatch")

    # state gate (PRD §2.7 gate 6) — must be SUBMITTED
    if oa["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application is not SUBMITTED")

    if decision == "DENY":
        oa["granted_level"] = 0
        oa["status"] = "DENIED"
        touch(oa)
        return object_response(options_approval_dict(oa), 200)

    # APPROVE: compute suitability cap
    cap = _suitability_cap(oa["stated_experience_years"], oa["liquid_net_worth_cents"])
    granted = min(oa["requested_level"], cap)
    oa["granted_level"] = granted

    if granted > 0:
        oa["status"] = "APPROVED"
        touch(oa)
        acct["options_level"] = max(acct["options_level"], granted)
        recompute_account(acct)
        touch(acct)
    else:
        oa["status"] = "DENIED"
        touch(oa)
    return object_response(options_approval_dict(oa), 200)


@bp.post("/options-approvals/<oa_id>/revoke")
def revoke_options(oa_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    oa = get_options_approval(oa_id)

    if oa["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application is not APPROVED")

    oa["status"] = "REVOKED"
    touch(oa)

    acct = db.accounts.get(oa["account_id"])
    # reset options_level to highest still-APPROVED level (0 if none)
    highest = 0
    for o in db.options_approvals.values():
        if o["account_id"] == acct["id"] and o["status"] == "APPROVED":
            highest = max(highest, o["granted_level"])
    acct["options_level"] = highest
    recompute_account(acct)
    touch(acct)
    return object_response(options_approval_dict(oa), 200)
