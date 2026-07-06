"""SkillOffer routes."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE
from response import envelope_object, envelope_array
from services import validators, pagination
from services.serializers import skill_offer_dto

bp = Blueprint("skill_offers", __name__)

TRUST_TIERS = ("UNVERIFIED", "BASIC", "TRUSTED", "ANCHOR")
OFFER_STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED")


@bp.route("/skill-offers", methods=["POST"])
def create_offer():
    user_id, _role = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["member_id", "skill_code", "title", "minutes_per_session"])
    member_id = validators.require_str(payload, "member_id")
    skill_code = validators.require_str(payload, "skill_code")
    title = validators.require_str(payload, "title")
    mps = validators.require_minute_multiple(payload, "minutes_per_session", 15, 480)
    tier = validators.optional_enum(payload, "required_trust_tier", set(TRUST_TIERS), default="UNVERIFIED")

    if db.members.get(member_id) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")
    if member_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal offer.member_id")

    o = {
        "member_id": member_id,
        "skill_code": skill_code,
        "title": title,
        "minutes_per_session": mps,
        "required_trust_tier": tier,
        "status": "ACTIVE",
    }
    db.stamp_new(o)
    db.skill_offers[o["id"]] = o
    return envelope_object(skill_offer_dto(o), status=201)


@bp.route("/skill-offers", methods=["GET"])
def list_offers():
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.skill_offers.values())
    for k in ("member_id", "skill_code", "status", "required_trust_tier"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([skill_offer_dto(x) for x in window], limit, offset, total)


@bp.route("/skill-offers/<oid>", methods=["GET"])
def get_offer(oid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    o = db.skill_offers.get(oid)
    if o is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Offer not found")
    return envelope_object(skill_offer_dto(o), status=200)


def _transition_offer(oid, allowed_from, new_status):
    user_id, _role = require_role({ROLE_MEMBER})
    o = db.skill_offers.get(oid)
    if o is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Offer not found")
    if o["status"] not in allowed_from:
        raise_err(ERR_INVALID_STATE, f"Offer.status must be in {allowed_from}")
    if o["member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal offer.member_id")
    o["status"] = new_status
    db.touch(o)
    return envelope_object(skill_offer_dto(o), status=200)


@bp.route("/skill-offers/<oid>/pause", methods=["POST"])
def pause(oid):
    return _transition_offer(oid, {"ACTIVE"}, "PAUSED")


@bp.route("/skill-offers/<oid>/resume", methods=["POST"])
def resume(oid):
    return _transition_offer(oid, {"PAUSED"}, "ACTIVE")


@bp.route("/skill-offers/<oid>/archive", methods=["POST"])
def archive(oid):
    return _transition_offer(oid, {"ACTIVE"}, "ARCHIVED")
