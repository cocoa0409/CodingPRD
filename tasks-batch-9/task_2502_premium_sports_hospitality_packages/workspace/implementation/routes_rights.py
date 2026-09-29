"""Rights deals, promised releases and the channel allocation waterfall."""
from flask import Blueprint, g

import calc
import services
from auth import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    FINANCE_CONTROLLER,
    RIGHTS_MANAGER,
    guard,
)
from common import get_block, get_deal, get_event, get_tranche, listing
from errors import (
    ERR_BLOCK_NOT_OPEN,
    ERR_CONFIRMED_UNITS_OUT_OF_RANGE,
    ERR_DUPLICATE_CHANNEL_BLOCK,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_MINIMUM_EXCEEDS_CONTRACT,
    ERR_STALE_DEAL_VERSION,
    ERR_TRANCHE_EXCEEDS_CONTRACT,
    ERR_TRANCHE_NOT_PENDING,
    fail,
)
from response import object_response
from store import (
    allocation_block_json,
    create_record,
    db,
    logical_now,
    release_tranche_json,
    rights_deal_json,
    touch,
    update_record,
)
from validation import body, req_datetime, req_enum, req_id, req_int, req_string

bp = Blueprint("rights", __name__)

INVENTORY_TYPES = ("TICKET", "HOSPITALITY_SPACE", "ACCESS_EXPERIENCE")
CHANNELS = ("INDIVIDUAL", "CORPORATE", "TRAVEL_PARTNER")
PROMISABLE_DEAL_STATES = ("COMMITTED", "PARTIALLY_RELEASED", "SHORTFALL_DECLARED")


def _deal_held_units(deal):
    held = 0
    for block in calc.blocks_of_deal(deal["id"]):
        held += block["allocated_units"]
    return held


# --- RightsDeal -------------------------------------------------------------


@bp.route("/rights-deals", methods=["POST"])
@guard(RIGHTS_MANAGER)
def create_rights_deal():
    data = body()
    event_id = req_id(data, "event_id")
    rights_holder_name = req_string(data, "rights_holder_name")
    inventory_type = req_enum(data, "inventory_type", INVENTORY_TYPES)
    contracted_units = req_int(data, "contracted_units", minimum=1)
    guaranteed_minimum_units = req_int(data, "guaranteed_minimum_units", minimum=0)
    unit_cost_cents = req_int(data, "unit_cost_cents", minimum=1)

    event = get_event(event_id)
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "Rights cannot be acquired against this fixture.")
    if guaranteed_minimum_units > contracted_units:
        fail(
            ERR_MINIMUM_EXCEEDS_CONTRACT,
            "guaranteed_minimum_units may not exceed contracted_units.",
        )

    deal = create_record(
        db.rights_deals,
        {
            "event_id": event_id,
            "rights_holder_name": rights_holder_name,
            "inventory_type": inventory_type,
            "contracted_units": contracted_units,
            "guaranteed_minimum_units": guaranteed_minimum_units,
            "unit_cost_cents": unit_cost_cents,
            "deal_status": "DRAFT",
            "released_units": 0,
            "shortfall_units": 0,
            "unallocated_units": 0,
            "minimum_liability_cents": 0,
            "committed_by_user_id": None,
            "settled_at": None,
        },
    )
    return object_response(rights_deal_json(deal), 201)


@bp.route("/rights-deals/<deal_id>", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR, FINANCE_CONTROLLER)
def read_rights_deal(deal_id):
    return object_response(rights_deal_json(get_deal(deal_id)))


@bp.route("/rights-deals", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR, FINANCE_CONTROLLER)
def list_rights_deals():
    return listing(
        calc.all_of(db.rights_deals),
        rights_deal_json,
        ("event_id", "deal_status", "inventory_type"),
    )


@bp.route("/rights-deals/<deal_id>/commit", methods=["POST"])
@guard(RIGHTS_MANAGER)
def commit_rights_deal(deal_id):
    deal = get_deal(deal_id)
    body()
    event = get_event(deal["event_id"])
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "This fixture can no longer take on rights liability.")
    if deal["deal_status"] != "DRAFT":
        fail(ERR_INVALID_DEAL_STATE, "Only a drafted deal can be committed.")

    values = calc.deal_liability_values(deal)
    deal.update(values)
    deal["deal_status"] = "COMMITTED"
    deal["committed_by_user_id"] = g.user_id
    deal["unallocated_units"] = values["released_units"] - _deal_held_units(deal)
    touch(deal)
    services.recompute_event_risk(event)
    return object_response(rights_deal_json(deal))


@bp.route("/rights-deals/<deal_id>/settle", methods=["POST"])
@guard(FINANCE_CONTROLLER)
def settle_rights_deal(deal_id):
    deal = get_deal(deal_id)
    body()
    event = get_event(deal["event_id"])
    if deal["deal_status"] not in ("PARTIALLY_RELEASED", "FULLY_RELEASED", "SHORTFALL_DECLARED"):
        fail(ERR_INVALID_DEAL_STATE, "This deal cannot be settled from its current status.")
    if event["status"] not in ("COMPLETED", "CANCELLED"):
        fail(ERR_INVALID_DEAL_STATE, "The fixture must have played or been cancelled first.")
    for tranche in calc.tranches_of_deal(deal["id"]):
        if tranche["tranche_state"] == "PENDING":
            fail(ERR_INVALID_DEAL_STATE, "A tranche of this deal is still pending.")

    now = logical_now()
    for block in calc.blocks_of_deal(deal["id"]):
        if block["block_state"] in calc.LIVE_BLOCK_STATES:
            update_record(block, {"block_state": "RECALLED", "recalled_at": now})

    values = calc.deal_liability_values(deal)
    deal.update(values)
    deal["deal_status"] = "SETTLED"
    deal["settled_at"] = now
    deal["unallocated_units"] = values["released_units"] - _deal_held_units(deal)
    touch(deal)
    services.recompute_event_risk(event)
    return object_response(rights_deal_json(deal))


# --- ReleaseTranche ---------------------------------------------------------


@bp.route("/release-tranches", methods=["POST"])
@guard(RIGHTS_MANAGER)
def create_release_tranche():
    data = body()
    deal_id = req_id(data, "rights_deal_id")
    promised_units = req_int(data, "promised_units", minimum=1)
    promised_release_at = req_datetime(data, "promised_release_at")

    deal = get_deal(deal_id)
    if deal["deal_status"] not in PROMISABLE_DEAL_STATES:
        fail(ERR_INVALID_DEAL_STATE, "Nothing may be promised against this deal.")
    outstanding = calc.deal_promised_units_in_states(
        deal, ("PENDING", "CONFIRMED", "SHORT_CONFIRMED")
    )
    if outstanding + promised_units > deal["contracted_units"]:
        fail(
            ERR_TRANCHE_EXCEEDS_CONTRACT,
            "Promised units would exceed the contracted quantity.",
        )

    tranche = create_record(
        db.release_tranches,
        {
            "rights_deal_id": deal_id,
            "promised_units": promised_units,
            "promised_release_at": promised_release_at,
            "tranche_state": "PENDING",
            "confirmed_units": 0,
            "confirmed_at": None,
            "lapsed_at": None,
        },
    )

    values = calc.deal_liability_values(deal)
    values["unallocated_units"] = values["released_units"] - _deal_held_units(deal)
    reopened = services.reopen_shortfall_deal(deal)
    if reopened is not None:
        values["deal_status"] = reopened
    update_record(deal, values)
    services.recompute_event_risk(get_event(deal["event_id"]))
    return object_response(release_tranche_json(tranche), 201)


@bp.route("/release-tranches/<tranche_id>", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER)
def read_release_tranche(tranche_id):
    return object_response(release_tranche_json(get_tranche(tranche_id)))


@bp.route("/release-tranches", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER)
def list_release_tranches():
    return listing(
        calc.all_of(db.release_tranches),
        release_tranche_json,
        ("rights_deal_id", "tranche_state"),
    )


@bp.route("/release-tranches/<tranche_id>/confirm", methods=["POST"])
@guard(RIGHTS_MANAGER)
def confirm_release_tranche(tranche_id):
    tranche = get_tranche(tranche_id)
    data = body()
    confirmed_units = req_int(data, "confirmed_units")
    expected_version = req_int(data, "expected_rights_deal_version")

    deal = get_deal(tranche["rights_deal_id"])
    if expected_version != deal["version"]:
        fail(ERR_STALE_DEAL_VERSION, "The rights deal has moved on since you read it.")
    if deal["deal_status"] not in PROMISABLE_DEAL_STATES:
        fail(ERR_INVALID_DEAL_STATE, "This deal can no longer take confirmations.")
    if tranche["tranche_state"] != "PENDING":
        fail(ERR_TRANCHE_NOT_PENDING, "Only a pending tranche can be confirmed.")
    if confirmed_units < 1 or confirmed_units > tranche["promised_units"]:
        fail(
            ERR_CONFIRMED_UNITS_OUT_OF_RANGE,
            "confirmed_units must lie between 1 and promised_units inclusive.",
        )

    tranche["tranche_state"] = (
        "CONFIRMED" if confirmed_units == tranche["promised_units"] else "SHORT_CONFIRMED"
    )
    tranche["confirmed_units"] = confirmed_units
    tranche["confirmed_at"] = logical_now()
    touch(tranche)

    services.apply_deal_state(deal, with_status=True, force=True, waterfall=True)
    services.recompute_event_risk(get_event(deal["event_id"]))
    return object_response(release_tranche_json(tranche))


# --- AllocationBlock --------------------------------------------------------


@bp.route("/allocation-blocks", methods=["POST"])
@guard(COMMERCIAL_MANAGER)
def create_allocation_block():
    data = body()
    deal_id = req_id(data, "rights_deal_id")
    channel = req_enum(data, "channel", CHANNELS)
    target_units = req_int(data, "target_units", minimum=1)
    priority_rank = req_int(data, "priority_rank", minimum=1)

    deal = get_deal(deal_id)
    if deal["deal_status"] not in PROMISABLE_DEAL_STATES:
        fail(ERR_INVALID_DEAL_STATE, "This deal cannot carry channel allocation.")
    for block in calc.blocks_of_deal(deal_id):
        if block["channel"] == channel and block["block_state"] in calc.LIVE_BLOCK_STATES:
            fail(
                ERR_DUPLICATE_CHANNEL_BLOCK,
                "This deal already holds a live block for that channel.",
            )

    block = create_record(
        db.allocation_blocks,
        {
            "rights_deal_id": deal_id,
            "channel": channel,
            "target_units": target_units,
            "priority_rank": priority_rank,
            "allocated_units": 0,
            "committed_units": 0,
            "released_back_units": 0,
            "block_state": "OPEN",
            "recalled_at": None,
        },
    )

    services.apply_deal_state(
        deal, with_status=False, force=False, waterfall=True, suppress_block=block["id"]
    )
    services.recompute_event_risk(get_event(deal["event_id"]))
    return object_response(allocation_block_json(block), 201)


@bp.route("/allocation-blocks/<block_id>", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, CLIENT_SERVICE_AGENT)
def read_allocation_block(block_id):
    return object_response(allocation_block_json(get_block(block_id)))


@bp.route("/allocation-blocks", methods=["GET"])
@guard(RIGHTS_MANAGER, COMMERCIAL_MANAGER, CLIENT_SERVICE_AGENT)
def list_allocation_blocks():
    return listing(
        calc.all_of(db.allocation_blocks),
        allocation_block_json,
        ("rights_deal_id", "channel", "block_state"),
    )


@bp.route("/allocation-blocks/<block_id>/recall", methods=["POST"])
@guard(RIGHTS_MANAGER)
def recall_allocation_block(block_id):
    block = get_block(block_id)
    body()
    if block["block_state"] not in calc.LIVE_BLOCK_STATES or block["committed_units"] != 0:
        fail(ERR_BLOCK_NOT_OPEN, "Only an unsold open or exhausted block can be recalled.")

    deal = get_deal(block["rights_deal_id"])
    block["block_state"] = "RECALLED"
    block["recalled_at"] = logical_now()
    touch(block)

    services.apply_deal_state(deal, with_status=False, force=True, waterfall=True)
    services.recompute_event_risk(get_event(deal["event_id"]))
    return object_response(allocation_block_json(block))
