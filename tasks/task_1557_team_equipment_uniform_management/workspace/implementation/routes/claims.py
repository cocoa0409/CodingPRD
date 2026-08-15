"""Damage claims (PRD §3.7): report -> assess -> settle/waive/reopen with
subject cascades."""
from datetime import datetime

from flask import Blueprint, request

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_CLAIM_SUBJECT,
    ERR_PLAYER_NOT_FOUND,
    ERR_KIT_ASSIGNMENT_NOT_FOUND,
    ERR_GEAR_ITEM_NOT_FOUND,
    ERR_DAMAGE_CLAIM_NOT_FOUND,
    ERR_KIT_NOT_ISSUED,
    ERR_GEAR_NOT_ISSUED,
    ERR_CLAIM_PLAYER_MISMATCH,
    ERR_CLAIM_NOT_REPORTED,
    ERR_CLAIM_NOT_ASSESSED,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from routes.gear import GRADES
from services.fees import replacement_fee, depreciated_fee
from services.pools import reconcile_pool, kit_pool_pairs
from util import is_int

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"LOST", "DAMAGED"}
CLAIM_STATUSES = {"REPORTED", "ASSESSED", "SETTLED", "WAIVED"}


def _subject(claim):
    """Return ("kit", kit) or ("gear", item)."""
    if claim.get("kit_assignment_id"):
        return "kit", db.kits.get(claim["kit_assignment_id"])
    return "gear", db.gear_items.get(claim["gear_item_id"])


def _apply_subject_mutation(claim):
    """Settle/waive cascade per claim_type (PRD §3.7)."""
    kind, subject = _subject(claim)
    if subject is None:
        return
    if kind == "kit":
        if claim["claim_type"] == "LOST":
            # Garments already written out of stock at issue: no restock.
            subject["status"] = "LOST"
            subject["closed_at"] = clock()
            touch(subject)
        else:
            # DAMAGED kit: same pool-restock cascade as a manager return
            # (increase direction may clear reorder_blocked).
            for pool, units in kit_pool_pairs(subject):
                prev = pool["available_quantity"]
                pool["stock_on_hand"] += units
                reconcile_pool(pool, "increase", prev)
            subject["status"] = "RETURNED"
            subject["closed_at"] = clock()
            touch(subject)
    else:
        if claim["claim_type"] == "LOST":
            subject["status"] = "RETIRED"
            subject["current_holder_id"] = None
            touch(subject)
        else:
            subject["status"] = "IN_STOCK"
            subject["current_holder_id"] = None
            subject["condition_grade"] = claim["condition_grade"]
            touch(subject)


@bp.post("/damage-claims")
@endpoint("EquipmentManager")
def create_claim(ctx):
    b = ctx.body
    player_id = b.get("player_id")
    claim_type = b.get("claim_type")
    base_value = b.get("base_value_cents")
    kit_id = b.get("kit_assignment_id")
    gear_id = b.get("gear_item_id")
    description = b.get("description")
    if not isinstance(player_id, str) or not player_id:
        raise_err(ERR_INVALID_REQUEST, "player_id is required")
    if claim_type not in CLAIM_TYPES:
        raise_err(ERR_INVALID_REQUEST, "claim_type is not a declared value")
    if not is_int(base_value) or base_value <= 0:
        raise_err(ERR_INVALID_REQUEST, "base_value_cents must be an integer > 0")
    if description is not None and not isinstance(description, str):
        raise_err(ERR_INVALID_REQUEST, "description must be a string")
    kit_set = kit_id is not None
    gear_set = gear_id is not None
    if kit_set == gear_set:
        raise_err(
            ERR_INVALID_CLAIM_SUBJECT,
            "exactly one of kit_assignment_id / gear_item_id must be set",
        )
    if kit_set and (not isinstance(kit_id, str) or not kit_id):
        raise_err(ERR_INVALID_CLAIM_SUBJECT, "kit_assignment_id must be a string")
    if gear_set and (not isinstance(gear_id, str) or not gear_id):
        raise_err(ERR_INVALID_CLAIM_SUBJECT, "gear_item_id must be a string")
    player = db.players.get(player_id)
    if player is None:
        raise_err(ERR_PLAYER_NOT_FOUND, "player not found")
    if kit_set:
        subject = db.kits.get(kit_id)
        if subject is None:
            raise_err(ERR_KIT_ASSIGNMENT_NOT_FOUND, "kit assignment not found")
        if subject["status"] != "ISSUED":
            raise_err(ERR_KIT_NOT_ISSUED, "claim subject kit must be ISSUED")
        if subject["player_id"] != player_id:
            raise_err(ERR_CLAIM_PLAYER_MISMATCH, "kit not issued to claim player")
    else:
        subject = db.gear_items.get(gear_id)
        if subject is None:
            raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
        if subject["status"] != "ISSUED":
            raise_err(ERR_GEAR_NOT_ISSUED, "claim subject gear must be ISSUED")
        if subject["current_holder_id"] != player_id:
            raise_err(ERR_CLAIM_PLAYER_MISMATCH, "gear not held by claim player")
    claim = stamp(
        {
            "player_id": player_id,
            "claim_type": claim_type,
            "kit_assignment_id": kit_id,
            "gear_item_id": gear_id,
            "base_value_cents": base_value,
            "description": description,
            "status": "REPORTED",
            "condition_grade": None,
            "provisional_fee_cents": replacement_fee(base_value),
            "assessed_fee_cents": None,
            "final_fee_cents": None,
        }
    )
    db.claims[claim["id"]] = claim
    return success(serialize(claim), 201)


@bp.get("/damage-claims")
@endpoint(*ALL_ROLES)
def list_claims(ctx):
    status = request.args.get("status")
    if status is not None and status not in CLAIM_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.claims,
        {
            "player_id": request.args.get("player_id"),
            "kit_assignment_id": request.args.get("kit_assignment_id"),
            "gear_item_id": request.args.get("gear_item_id"),
            "status": status,
        },
    )


@bp.get("/damage-claims/<claim_id>")
@endpoint(*ALL_ROLES)
def get_claim(ctx, claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_DAMAGE_CLAIM_NOT_FOUND, "damage claim not found")
    return success(serialize(claim))


@bp.post("/damage-claims/<claim_id>/assess")
@endpoint("EquipmentManager")
def assess_claim(ctx, claim_id):
    b = ctx.body
    grade = b.get("condition_grade")
    if grade not in GRADES:
        raise_err(ERR_INVALID_REQUEST, "condition_grade is not a declared value")
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_DAMAGE_CLAIM_NOT_FOUND, "damage claim not found")
    if claim["status"] != "REPORTED":
        raise_err(ERR_CLAIM_NOT_REPORTED, "assess requires claim in REPORTED")
    if claim["claim_type"] == "LOST":
        fee = replacement_fee(claim["base_value_cents"])
    else:
        kind, subject = _subject(claim)
        if kind == "kit":
            acquired = subject["created_at"].date() if subject else clock().date()
        else:
            acquired = (
                datetime.strptime(subject["acquired_on"], "%Y-%m-%d").date()
                if subject
                else clock().date()
            )
        age_days = (clock().date() - acquired).days
        fee = depreciated_fee(claim["base_value_cents"], grade, age_days)
    claim["condition_grade"] = grade
    claim["assessed_fee_cents"] = fee
    claim["status"] = "ASSESSED"
    touch(claim)
    return success(serialize(claim))


@bp.post("/damage-claims/<claim_id>/settle")
@endpoint("EquipmentManager")
def settle_claim(ctx, claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_DAMAGE_CLAIM_NOT_FOUND, "damage claim not found")
    if claim["status"] != "ASSESSED":
        raise_err(ERR_CLAIM_NOT_ASSESSED, "settle requires claim in ASSESSED")
    claim["final_fee_cents"] = claim["assessed_fee_cents"]
    claim["status"] = "SETTLED"
    _apply_subject_mutation(claim)
    touch(claim)
    return success(serialize(claim))


@bp.post("/damage-claims/<claim_id>/waive")
@endpoint("TeamAdmin")
def waive_claim(ctx, claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_DAMAGE_CLAIM_NOT_FOUND, "damage claim not found")
    if claim["status"] != "ASSESSED":
        raise_err(ERR_CLAIM_NOT_ASSESSED, "waive requires claim in ASSESSED")
    claim["final_fee_cents"] = 0
    claim["status"] = "WAIVED"
    _apply_subject_mutation(claim)
    touch(claim)
    return success(serialize(claim))


@bp.post("/damage-claims/<claim_id>/reopen")
@endpoint("TeamAdmin")
def reopen_claim(ctx, claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_DAMAGE_CLAIM_NOT_FOUND, "damage claim not found")
    if claim["status"] != "ASSESSED":
        raise_err(ERR_CLAIM_NOT_ASSESSED, "reopen requires claim in ASSESSED")
    claim["assessed_fee_cents"] = None
    claim["condition_grade"] = None
    claim["status"] = "REPORTED"
    touch(claim)
    return success(serialize(claim))
