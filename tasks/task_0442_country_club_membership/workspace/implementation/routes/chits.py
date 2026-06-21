"""Chit / charge-account endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
import services
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import chit_out

bp = Blueprint("chits", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]
_KINDS = {"DINING", "PRO_SHOP", "GUEST_FEE", "EVENT"}


@bp.post("/chits")
def create_chit():
    role, _ = get_auth()
    require_roles(role, ["BillingClerk"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "membership_id", "amount_cents", "kind"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    membership = common.get_membership(common.require_string(body, "membership_id"))
    amount = common.require_positive_int(body, "amount_cents")
    kind = common.require_enum(body, "kind", _KINDS)
    rec = services.post_chit(club_id, membership["id"], amount, kind, bump_membership=True)
    return success_object(chit_out(rec), status=201)


@bp.get("/chits/<cid>")
def get_chit(cid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_chit(cid)
    return success_object(chit_out(rec), status=200)


@bp.get("/chits")
def list_chits():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.chits.values())
    membership_id = request.args.get("membership_id")
    club_id = request.args.get("club_id")
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [chit_out(r) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/chits/<cid>/void")
def void_chit(cid):
    role, _ = get_auth()
    require_roles(role, ["BillingClerk"])
    rec = common.get_chit(cid)
    if rec["status"] != "POSTED":
        raise errors.invalid_state("Chit is not POSTED")
    rec["status"] = "VOIDED"
    db.touch(rec)
    # Compensating reversal: credit charge_balance and recompute fb_spend
    # (both derived from the ledger, so a recompute does both).
    membership = db.memberships.get(rec["membership_id"])
    if membership:
        computed.refresh_membership_computeds(membership["id"])
        db.touch(membership)
    return success_object(chit_out(rec), status=200)
