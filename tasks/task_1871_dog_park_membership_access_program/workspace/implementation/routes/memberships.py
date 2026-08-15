"""Membership endpoints: initial purchase, list, OCC-guarded renewal."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_MEMBER_NOT_FOUND, ERR_MEMBERSHIP_NOT_FOUND, ERR_NOT_OWNER,
    ERR_NO_VERIFIED_DOG, ERR_MEMBER_NOT_ACTIVE, ERR_STALE_VERSION,
)
from helpers import (
    get_body, req_int, now_dt, now_iso, today, term_end_string,
    parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("memberships", __name__)


def _get_member_or_404(member_id):
    member = store.members.get(member_id)
    if member is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, 404, "Member not found")
    return member


@bp.route("/dog-park/members/<memberId>/memberships", methods=["POST"])
def purchase_membership(memberId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only purchase their own membership")
    member = _get_member_or_404(memberId)
    if domain.verified_dog_count(memberId) < 1:
        raise ApiError(ERR_NO_VERIFIED_DOG, 409,
                       "Membership purchase requires at least one VERIFIED dog")
    purchase_date = today()
    fee = domain.initial_membership_fee(memberId, purchase_date)
    membership = domain.new_entity(store.memberships, {
        "member_id": memberId,
        "term_start": now_iso(),
        "term_end": term_end_string(purchase_date.year),
        "charged_fee_cents": fee,
        "renewal_count": 0,
        "status": "ACTIVE",
    })
    if member["status"] == "PENDING_VERIFICATION":
        member["status"] = "ACTIVE"
        domain.touch(member)
    return ok(domain.public(membership), 201)


@bp.route("/dog-park/members/<memberId>/memberships", methods=["GET"])
def list_memberships(memberId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only list their own memberships")
    limit, offset = parse_pagination()
    _get_member_or_404(memberId)
    items = [m for m in store.memberships.values() if m["member_id"] == memberId]
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(m) for m in page], 200, meta)


@bp.route("/dog-park/memberships/<membershipId>/renew", methods=["POST"])
def renew_membership(membershipId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    body = get_body()
    expected = req_int(body, "expected_membership_version")
    membership = store.memberships.get(membershipId)
    if membership is None:
        raise ApiError(ERR_MEMBERSHIP_NOT_FOUND, 404, "Membership not found")
    if role == "Member" and membership["member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only renew their own membership")
    # Stage 7 OCC — checked FIRST, before any member/membership state rule.
    if expected != membership["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_membership_version does not match the current version")
    member = _get_member_or_404(membership["member_id"])
    # Stage 8: member state evaluated before membership state, per renewal flavor.
    if membership["status"] == "ACTIVE":
        # Early renewal: member must be ACTIVE.
        if member["status"] != "ACTIVE":
            raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409,
                           "Early renewal requires an ACTIVE member")
        membership["charged_fee_cents"] = domain.early_renewal_fee(member["id"])
        current_term_year = int(membership["term_end"][0:4])
        membership["term_end"] = term_end_string(current_term_year + 1)
    elif membership["status"] == "EXPIRED":
        # Lapsed renewal: member must be LAPSED.
        if member["status"] != "LAPSED":
            raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409,
                           "Lapsed renewal requires a LAPSED member")
        membership["charged_fee_cents"] = domain.lapsed_renewal_fee(member["id"])
        membership["term_start"] = now_iso()
        membership["term_end"] = term_end_string(now_dt().year)
        membership["status"] = "ACTIVE"
        member["status"] = "ACTIVE"
        domain.touch(member)
    else:
        # No renewal path from SUSPENDED.
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409,
                       "Membership in status {} has no renewal path".format(
                           membership["status"]))
    membership["renewal_count"] += 1
    domain.touch(membership)
    return ok(domain.public(membership))
