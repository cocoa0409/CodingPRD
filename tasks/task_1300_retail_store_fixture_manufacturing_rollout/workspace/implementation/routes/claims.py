"""DamageClaim endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DELIVERY_NOT_FOUND,
    ERR_DELIVERY_INVALID_STATE,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_OPEN,
    ERR_PART_RECALL_HOLD,
    ERR_CONTINGENCY_EXCEEDED,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import recompute_wave_utilization
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"DAMAGED", "MISSING"}


def _get_claim_or_404(claim_id: str) -> dict:
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_CLAIM_NOT_FOUND, "DamageClaim id does not exist")
    return claim


@bp.route("/damage-claims", methods=["POST"])
@require_roles("HotlineAgent")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()
    delivery_id = require_string(body, "delivery_id")
    part_number = require_string(body, "part_number")
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    replacement_component_count = require_int(body, "replacement_component_count", minimum=1)
    replacement_cost_cents = require_int(body, "replacement_cost_cents", minimum=0)

    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise_err(ERR_DELIVERY_NOT_FOUND, "InstallDelivery id does not exist")
    if delivery["status"] not in ("DELIVERED", "COMPLETE"):
        raise_err(ERR_DELIVERY_INVALID_STATE, "claim creation requires delivery DELIVERED or COMPLETE")

    claim = {
        "delivery_id": delivery_id,
        "part_number": part_number,
        "claim_type": claim_type,
        "replacement_component_count": replacement_component_count,
        "replacement_cost_cents": replacement_cost_cents,
        "status": "OPEN",
    }
    db.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(serialize(claim), 201)


@bp.route("/damage-claims", methods=["GET"])
@require_roles("Any")
def list_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.claims.values()))
    items = apply_filters(items, ["delivery_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/damage-claims/<claim_id>", methods=["GET"])
@require_roles("Any")
def get_claim(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    return success_object(serialize(claim))


@bp.route("/damage-claims/<claim_id>/approve", methods=["POST"])
@require_roles("ProgramManager")
def approve_claim(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    if claim["status"] != "OPEN":
        raise_err(ERR_CLAIM_NOT_OPEN, "approve requires claim OPEN")

    # Resolve program through delivery -> kit -> program
    delivery = db.deliveries.get(claim["delivery_id"])
    kit = db.kits.get(delivery["kit_id"]) if delivery else None
    program = db.programs.get(kit["program_id"]) if kit else None
    if program is None:
        raise_err(ERR_INVALID_REQUEST, "claim's program could not be resolved")

    # Segregation/recall gate (priority 6)
    if claim["part_number"] in program.get("recalled_part_numbers", []):
        raise_err(ERR_PART_RECALL_HOLD, "Claim part_number is on the program's recall hold list")

    # Money (priority 9)
    remaining_contingency = program["contingency_budget_cents"] - program["contingency_spent_cents"]
    if claim["replacement_cost_cents"] > remaining_contingency:
        raise_err(ERR_CONTINGENCY_EXCEEDED, "replacement_cost_cents exceeds remaining contingency budget")

    # Cascade hop 1: contingency spend
    program["contingency_spent_cents"] += claim["replacement_cost_cents"]
    db.touch(program)

    # Cascade hop 2/3: wave committed units + utilization
    wave_id = kit.get("wave_id")
    if wave_id is not None:
        wave = db.waves.get(wave_id)
        if wave is not None:
            wave["committed_units"] += claim["replacement_component_count"]
            recompute_wave_utilization(wave)
            db.touch(wave)

    claim["status"] = "APPROVED"
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/damage-claims/<claim_id>/reject", methods=["POST"])
@require_roles("ProgramManager")
def reject_claim(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    if claim["status"] != "OPEN":
        raise_err(ERR_CLAIM_NOT_OPEN, "reject requires claim OPEN")
    claim["status"] = "REJECTED"
    db.touch(claim)
    return success_object(serialize(claim))
