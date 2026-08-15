"""Helmet distribution ledger (PRD §3.11) — compliance gate for graduation,
sale completion, and YOUTH giveaway fulfillment."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_event, touch, paginate, sorted_by_created, recompute_part_low_stock

bp = Blueprint("helmets", __name__)

RECIPIENT_KINDS = ["EARN_A_BIKE_GRADUATE", "SALE_BUYER", "GIVEAWAY_RECIPIENT", "COMMUNITY"]
KIND_FK = {
    "EARN_A_BIKE_GRADUATE": "participant_id",
    "SALE_BUYER": "sale_id",
    "GIVEAWAY_RECIPIENT": "giveaway_id",
}


def distribution_view(d):
    return {
        "id": d["id"],
        "helmet_part_id": d["helmet_part_id"],
        "recipient_kind": d["recipient_kind"],
        "participant_id": d["participant_id"],
        "sale_id": d["sale_id"],
        "giveaway_id": d["giveaway_id"],
        "recipient_name": d["recipient_name"],
        "distributed_by_user_id": d["distributed_by_user_id"],
        "created_at": d["created_at"],
    }


@bp.post("/helmet-distributions")
def create_distribution():
    user_id, _ = require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "helmet_part_id": {"type": "string", "required": True},
        "recipient_kind": {"type": "string", "required": True, "enum": RECIPIENT_KINDS},
        "participant_id": {"type": "string"},
        "sale_id": {"type": "string"},
        "giveaway_id": {"type": "string"},
        "recipient_name": {"type": "string"},
    })
    part = db.parts.get(body["helmet_part_id"])
    if part is None:
        raise ApiError("ERR_NOT_FOUND", f"Part {body['helmet_part_id']} does not exist")

    kind = body["recipient_kind"]
    fk_field = KIND_FK.get(kind)
    fk_id = body.get(fk_field) if fk_field else None

    # Body FK existence (priority 4) — resolve the referenced recipient.
    recipient = None
    if fk_field == "participant_id" and fk_id is not None:
        recipient = db.participants.get(fk_id)
        if recipient is None:
            raise ApiError("ERR_NOT_FOUND", f"EarnABikeParticipant {fk_id} does not exist")
    elif fk_field == "sale_id" and fk_id is not None:
        recipient = db.sales.get(fk_id)
        if recipient is None:
            raise ApiError("ERR_NOT_FOUND", f"Sale {fk_id} does not exist")
    elif fk_field == "giveaway_id" and fk_id is not None:
        recipient = db.giveaways.get(fk_id)
        if recipient is None:
            raise ApiError("ERR_NOT_FOUND", f"GiveawayAward {fk_id} does not exist")

    # State gates on the referenced recipient (priority 6).
    if kind == "EARN_A_BIKE_GRADUATE" and recipient is not None:
        if recipient["status"] != "HOURS_MET":
            raise ApiError("ERR_INVALID_STATE", "Participant must be HOURS_MET for a helmet distribution")
    elif kind == "SALE_BUYER" and recipient is not None:
        if recipient["status"] != "PENDING":
            raise ApiError("ERR_SALE_NOT_PENDING", "Sale must be PENDING for a helmet distribution")
    elif kind == "GIVEAWAY_RECIPIENT" and recipient is not None:
        if recipient["status"] != "APPROVED":
            raise ApiError("ERR_AWARD_NOT_APPROVED", "Award must be APPROVED for a helmet distribution")

    # Stock gate (fiscal) precedes referential checks.
    if part["quantity_on_hand"] < 1:
        raise ApiError("ERR_HELMET_OUT_OF_STOCK", "Helmet SKU is out of stock")

    # Referential discipline: exactly the matching reference present, others absent.
    mismatch = False
    if kind == "COMMUNITY":
        if not body.get("recipient_name"):
            mismatch = True
        if body.get("participant_id") or body.get("sale_id") or body.get("giveaway_id"):
            mismatch = True
    else:
        if fk_id is None:
            mismatch = True
        for other in ("participant_id", "sale_id", "giveaway_id"):
            if other != fk_field and body.get(other) is not None:
                mismatch = True
        if body.get("recipient_name") is not None:
            mismatch = True
    if mismatch:
        raise ApiError("ERR_RECIPIENT_REFERENCE_MISMATCH",
                       "Exactly the reference matching recipient_kind must be present")

    if part["category"] != "HELMET":
        raise ApiError("ERR_NOT_A_HELMET_SKU", "helmet_part_id must reference a HELMET part")

    d = make_event()
    d.update({
        "helmet_part_id": part["id"],
        "recipient_kind": kind,
        "participant_id": body.get("participant_id"),
        "sale_id": body.get("sale_id"),
        "giveaway_id": body.get("giveaway_id"),
        "recipient_name": body.get("recipient_name"),
        "distributed_by_user_id": user_id,
    })
    db.helmet_distributions[d["id"]] = d
    part["quantity_on_hand"] -= 1
    touch(part)
    recompute_part_low_stock(part)
    return success(distribution_view(d), status=201)


@bp.get("/helmet-distributions/<distribution_id>")
def get_distribution(distribution_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    d = db.helmet_distributions.get(distribution_id)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", f"HelmetDistribution {distribution_id} does not exist")
    return success(distribution_view(d))


@bp.get("/helmet-distributions")
def list_distributions():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.helmet_distributions.values())
    for param in ("helmet_part_id", "participant_id", "sale_id", "giveaway_id", "recipient_kind"):
        value = request.args.get(param)
        if value is not None:
            rows = [d for d in rows if d[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([distribution_view(d) for d in page], pagination=pg)
