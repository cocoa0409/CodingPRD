"""Members, waivers, memberships, fine payments."""

from flask import Blueprint, g, request

import errors as E
from domain import (member_out, membership_out, membership_fee, lazy_expire_membership,
                    get_or_404)
from store import DB
from util import (body_json, req_str, req_enum, req_int, req_present, is_int,
                  envelope_object, list_response, require_role, stamp_new, touch, today)

bp = Blueprint("members", __name__)

AFFILIATIONS = {"STUDENT", "FACULTY", "COMMUNITY"}
TERMS = {"FALL_2026", "SPRING_2027", "SUMMER_2027"}


def _self_or_forbidden(member_id):
    if g.role == "Member" and g.user_id != member_id:
        raise E.err_forbidden("Members may only act on their own record")


@bp.route("/v1/members", methods=["POST"])
def create_member():
    require_role("RecAdmin")
    body = body_json()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    affiliation = req_enum(body, "affiliation", AFFILIATIONS)
    for m in DB.members.values():
        if m["email"].lower() == email.lower():
            raise E.err_validation("Email address already in use")
    member = stamp_new({
        "email": email,
        "full_name": full_name,
        "affiliation": affiliation,
        "status": "ACTIVE",
        "waiver_signed_date": None,
        "outstanding_fines_cents": 0,
        "no_show_count": 0,
    })
    DB.members[member["id"]] = member
    return envelope_object(member_out(member), 201)


@bp.route("/v1/members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    member = get_or_404(DB.members, member_id)
    return envelope_object(member_out(member))


@bp.route("/v1/members/<member_id>/waiver-sign", methods=["POST"])
def waiver_sign(member_id):
    require_role("Member")
    _self_or_forbidden(member_id)
    member = get_or_404(DB.members, member_id)
    member["waiver_signed_date"] = today()
    touch(member)
    return envelope_object(member_out(member))


@bp.route("/v1/members/<member_id>/memberships", methods=["POST"])
def purchase_membership(member_id):
    require_role("Member")
    _self_or_forbidden(member_id)
    member = get_or_404(DB.members, member_id)
    body = body_json()
    term = req_enum(body, "term", TERMS)
    expected = req_present(body, "expected_member_version")
    if not is_int(expected):
        raise E.err_validation("expected_member_version must be an integer")
    # Fee validation (incl. purchase-after-term-end) runs before the OCC check.
    variant, fee = membership_fee(term, member["affiliation"], today())
    if expected != member["version"]:
        raise E.err_stale_version()
    # Lazy expiry first so a lapsed ACTIVE membership is not "superseded".
    for ms in DB.memberships.values():
        if ms["member_id"] == member_id:
            lazy_expire_membership(ms)
    prior = None
    for ms in DB.memberships.values():
        if ms["member_id"] == member_id and ms["status"] == "ACTIVE":
            prior = ms
            break
    membership = stamp_new({
        "member_id": member_id,
        "term": term,
        "pricing_variant": variant,
        "fee_cents": fee,
        "status": "ACTIVE",
        "supersedes_membership_id": prior["id"] if prior else None,
    })
    DB.memberships[membership["id"]] = membership
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    touch(member)
    return envelope_object(membership_out(membership), 201)


@bp.route("/v1/memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    ms = get_or_404(DB.memberships, membership_id)
    lazy_expire_membership(ms)
    return envelope_object(membership_out(ms))


@bp.route("/v1/memberships", methods=["GET"])
def list_memberships():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    for ms in DB.memberships.values():
        lazy_expire_membership(ms)
    member_id = request.args.get("member_id")
    term = request.args.get("term")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_membership_id")
    records = [ms for ms in DB.memberships.values()
               if (member_id is None or ms["member_id"] == member_id)
               and (term is None or ms["term"] == term)
               and (status is None or ms["status"] == status)
               and (supersedes is None or ms["supersedes_membership_id"] == supersedes)]
    return list_response(records, membership_out)


@bp.route("/v1/memberships/<membership_id>/cancel", methods=["POST"])
def cancel_membership(membership_id):
    require_role("Member", "RecAdmin")
    ms = get_or_404(DB.memberships, membership_id)
    if g.role == "Member" and ms["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only cancel their own membership")
    lazy_expire_membership(ms)
    if ms["status"] != "ACTIVE":
        raise E.err_invalid_state("Only an ACTIVE membership can be cancelled")
    ms["status"] = "CANCELLED"
    touch(ms)
    return envelope_object(membership_out(ms))


@bp.route("/v1/members/<member_id>/fine-payments", methods=["POST"])
def pay_fine(member_id):
    require_role("Member")
    _self_or_forbidden(member_id)
    member = get_or_404(DB.members, member_id)
    body = body_json()
    amount = req_int(body, "amount_cents")
    if amount <= 0 or amount > member["outstanding_fines_cents"]:
        raise E.err_validation("amount_cents must be > 0 and <= outstanding_fines_cents")
    member["outstanding_fines_cents"] -= amount
    touch(member)
    return envelope_object(member_out(member))
