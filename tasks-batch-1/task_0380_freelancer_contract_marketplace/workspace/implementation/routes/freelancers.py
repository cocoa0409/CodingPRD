"""Freelancer endpoints (PRD 3.1, 3.6)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("freelancers", __name__)


@bp.post("/freelancers")
def create_freelancer():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = common.get_body()
    display_name = common.require_str(body, "display_name")
    email = common.require_str(body, "email")
    skills = body.get("skills")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise err("ERR_INVALID_REQUEST", "skills must be an array of strings")
    tax_id = body.get("tax_id_on_file", False)
    if not isinstance(tax_id, bool):
        raise err("ERR_INVALID_REQUEST", "tax_id_on_file must be a boolean")
    for f in db.freelancers.values():
        if f["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already used by another freelancer")
    rec = db.new_common()
    rec.update({
        "display_name": display_name,
        "email": email,
        "tax_id_on_file": tax_id,
        "skills": list(skills),
        "lifetime_earnings_cents": 0,
        "reputation_score": 0.0,
        "fee_tier": "TIER_A",
        "status": "ACTIVE",
    })
    db.freelancers[rec["id"]] = rec
    return success(derive.freelancer_view(rec), status=201)


@bp.get("/freelancers")
def list_freelancers():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    email = request.args.get("email")
    items = list(db.freelancers.values())
    if email is not None:
        items = [f for f in items if f["email"] == email]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.freelancer_view(f) for f in page], pagination=meta)


@bp.get("/freelancers/<fid>")
def get_freelancer(fid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    f = common.get_freelancer(fid)
    return success(derive.freelancer_view(f))


@bp.patch("/freelancers/<fid>")
def update_freelancer(fid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer"])
    f = common.get_freelancer(fid)
    common.check_freelancer_owns(role, user_id, f["id"])
    body = common.get_body()
    if "skills" in body and body["skills"] is not None:
        skills = body["skills"]
        if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
            raise err("ERR_INVALID_REQUEST", "skills must be an array of strings")
        f["skills"] = list(skills)
    if "tax_id_on_file" in body and body["tax_id_on_file"] is not None:
        tax = body["tax_id_on_file"]
        if not isinstance(tax, bool):
            raise err("ERR_INVALID_REQUEST", "tax_id_on_file must be a boolean")
        f["tax_id_on_file"] = tax
    db.touch(f)
    # Setting tax_id_on_file true does not auto-settle held payouts; it merely
    # unblocks a subsequent settle attempt (PRD 3.6). No state mutation here.
    return success(derive.freelancer_view(f))


@bp.get("/freelancers/<fid>/proposals")
def freelancer_proposals(fid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer"])
    common.get_freelancer(fid)
    common.check_freelancer_owns(role, user_id, fid)
    items = [p for p in db.proposals.values() if p["freelancer_id"] == fid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.proposal_view(p) for p in page], pagination=meta)


@bp.get("/freelancers/<fid>/contracts")
def freelancer_contracts(fid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer", "Client"])
    common.get_freelancer(fid)
    common.check_freelancer_owns(role, user_id, fid)
    items = [c for c in db.contracts.values() if c["freelancer_id"] == fid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.contract_view(c) for c in page], pagination=meta)


@bp.get("/freelancers/<fid>/payouts")
def freelancer_payouts(fid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer"])
    common.get_freelancer(fid)
    common.check_freelancer_owns(role, user_id, fid)
    tax_year = request.args.get("tax_year")
    items = [p for p in db.payouts.values() if p["freelancer_id"] == fid]
    if tax_year is not None:
        try:
            ty = int(tax_year)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "tax_year must be an integer")
        items = [p for p in items if p["tax_year"] == ty]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.payout_view(p) for p in page], pagination=meta)


@bp.get("/freelancers/<fid>/tax-records")
def freelancer_tax_records(fid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer"])
    common.get_freelancer(fid)
    common.check_freelancer_owns(role, user_id, fid)
    items = [t for t in db.tax_records.values() if t["freelancer_id"] == fid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.tax_record_view(t) for t in page], pagination=meta)
