"""OptionSelection endpoints: create / list / get / confirm / unconfirm /
cancel (PRD section 3.5)."""

from decimal import Decimal

import db
from constants import READ_ROLES, ROLE_BUYER, STAGE_ORDINAL, CHANGE_FEE_PCT
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_OPTION_ITEM_NOT_FOUND,
    ERR_SELECTION_NOT_FOUND,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_SELECTION_INVALID_STATE,
    ERR_OPTION_CUTOFF_PASSED,
    ERR_OPTION_NOT_IN_COMMUNITY,
)
from middleware import authenticate, require_agreement_owner
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_selection
from util import (
    body_json,
    check_shape,
    require_fk,
    rhu,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("selections")

CREATE_SPEC = {
    "agreement_id": {"type": "string", "required": True},
    "option_item_id": {"type": "string", "required": True},
    "quantity": {"type": "integer", "min": 1},
}


def _load_selection(sid):
    selection = require_fk("selections", sid, ERR_SELECTION_NOT_FOUND, "selection")
    agreement = db.get("agreements", selection["agreement_id"])
    item = db.get("option_items", selection["option_item_id"])
    return selection, agreement, item


@bp.post("/option-selections")
def create_selection():
    user_id, role = authenticate(["Buyer"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    # Existence (tier 4): body FKs left to right.
    agreement = require_fk("agreements", body["agreement_id"], ERR_AGREEMENT_NOT_FOUND, "agreement")
    item = require_fk("option_items", body["option_item_id"], ERR_OPTION_ITEM_NOT_FOUND, "option item")
    # Ownership (tier 5).
    require_agreement_owner(agreement, user_id, role)
    # Temporal window (tier 8): free while current_stage ordinal <= cutoff
    # ordinal; strictly past the cutoff is rejected. Evaluated BEFORE the
    # referential community check (priority 8 beats priority 10).
    if STAGE_ORDINAL[agreement["current_stage"]] > STAGE_ORDINAL[item["cutoff_stage"]]:
        raise ApiError(ERR_OPTION_CUTOFF_PASSED, 409, "the option's cutoff stage has passed")
    # Referential (tier 10).
    if item["community_id"] != agreement["community_id"]:
        raise ApiError(ERR_OPTION_NOT_IN_COMMUNITY, 422, "option item belongs to a different community than the agreement")

    quantity = body.get("quantity", 1)
    selection = db.new_entity("selections", {
        "agreement_id": agreement["id"],
        "option_item_id": item["id"],
        "quantity": quantity,
        "unit_price_cents": item["price_cents"],  # snapshot at selection
        "line_total_cents": item["price_cents"] * quantity,
        "change_fee_cents": 0,
        "selected_at_stage": agreement["current_stage"],
        "confirmed_at_stage": None,
        "status": "SELECTED",
        "cancel_reason": None,
    })
    db.touch(agreement)
    return success_obj(ser_selection(selection), 201)


@bp.get("/option-selections")
def list_selections():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("selections")
    if role == ROLE_BUYER:
        items = [
            s for s in items
            if (db.get("agreements", s["agreement_id"]) or {}).get("buyer_id") == user_id
        ]
    items = apply_filters(items, ["agreement_id", "option_item_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_selection(s) for s in page], limit, offset, total, has_more)


@bp.get("/option-selections/<sid>")
def get_selection(sid):
    authenticate(READ_ROLES)
    selection = require_fk("selections", sid, ERR_SELECTION_NOT_FOUND, "selection")
    return success_obj(ser_selection(selection), 200)


@bp.post("/option-selections/<sid>/confirm")
def confirm_selection(sid):
    user_id, role = authenticate(["Buyer"])
    selection, agreement, _item = _load_selection(sid)
    require_agreement_owner(agreement, user_id, role)
    # State tier (scaffold order): selection state, then agreement state.
    if selection["status"] != "SELECTED":
        raise ApiError(ERR_SELECTION_INVALID_STATE, 409, "only a SELECTED selection can be confirmed")
    if agreement["status"] not in ("PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "agreement is not in a confirmable state")
    # Never a fee on confirm: a stale SELECTED line cannot survive past cutoff
    # because the milestone sweep cancels it first.
    selection["status"] = "CONFIRMED"
    selection["confirmed_at_stage"] = agreement["current_stage"]
    db.touch(selection)
    db.touch(agreement)
    return success_obj(ser_selection(selection), 200)


@bp.post("/option-selections/<sid>/unconfirm")
def unconfirm_selection(sid):
    user_id, role = authenticate(["Buyer"])
    selection, agreement, item = _load_selection(sid)
    require_agreement_owner(agreement, user_id, role)
    if selection["status"] != "CONFIRMED":
        raise ApiError(ERR_SELECTION_INVALID_STATE, 409, "only a CONFIRMED selection can be unconfirmed")
    # Re-open is only available inside the free window; at exact stage equality
    # the window is still open.
    if STAGE_ORDINAL[agreement["current_stage"]] > STAGE_ORDINAL[item["cutoff_stage"]]:
        raise ApiError(ERR_OPTION_CUTOFF_PASSED, 409, "the option's cutoff stage has passed")
    selection["status"] = "SELECTED"
    selection["confirmed_at_stage"] = None
    db.touch(selection)
    db.touch(agreement)
    return success_obj(ser_selection(selection), 200)


@bp.post("/option-selections/<sid>/cancel")
def cancel_selection(sid):
    user_id, role = authenticate(["Buyer"])
    selection, agreement, item = _load_selection(sid)
    require_agreement_owner(agreement, user_id, role)
    if selection["status"] not in ("SELECTED", "CONFIRMED"):
        raise ApiError(ERR_SELECTION_INVALID_STATE, 409, "only a SELECTED or CONFIRMED selection can be cancelled")
    # Cancelling SELECTED is always free; cancelling CONFIRMED past the cutoff
    # accrues the change fee (round_half_up(line_total * 0.10)).
    if (
        selection["status"] == "CONFIRMED"
        and STAGE_ORDINAL[agreement["current_stage"]] > STAGE_ORDINAL[item["cutoff_stage"]]
    ):
        selection["change_fee_cents"] = rhu(Decimal(selection["line_total_cents"]) * CHANGE_FEE_PCT)
    selection["status"] = "CANCELLED"
    selection["cancel_reason"] = "BUYER_REQUEST"
    db.touch(selection)
    db.touch(agreement)
    return success_obj(ser_selection(selection), 200)
