"""Hop contracts: writing, carry-forward, default settlement and resale."""

from datetime import timedelta

from flask import Blueprint, request

from calc import (
    CARRY_FORWARD_SHIFT_DAYS,
    carry_forward_eligible,
    carry_forward_fee,
    contract_remaining,
    recompute_brewer,
    settle_default,
)
from cascades import post_receivable
from db import by_created, db, new_entity, now, set_dt, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, require, scope_brewer
from response import array_response, object_response
from serialize import contract_out
from util import D, rhu_int
from validation import (
    body,
    f_dec,
    f_dt,
    f_enum,
    f_str,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("contracts", __name__)

WORKING_STATUSES = ("ACTIVE", "SHORTFALL_ADJUSTED")
OVERLAP_EXEMPT_STATUSES = ("CARRIED_FORWARD", "RESOLD")


def _new_contract_record(brewer_id, variety_id, program_id, contract_type,
                         contracted_lbs, price_per_lb_cents, window_start,
                         window_end, window_start_raw=None, window_end_raw=None,
                         carried_forward_from=None):
    contract = new_entity()
    contract.update(
        {
            "brewer_id": brewer_id,
            "variety_id": variety_id,
            "crop_year_program_id": program_id,
            "contract_type": contract_type,
            "contracted_lbs": contracted_lbs,
            "price_per_lb_cents": price_per_lb_cents,
            "carried_forward_from_contract_id": carried_forward_from,
            "carry_forward_target_program_id": None,
            "allocated_lbs": contracted_lbs,
            "committed_lbs": D(0),
            "carried_forward_out_lbs": D(0),
            "defaulted_lbs": D(0),
            "resold_lbs": D(0),
            "remaining_lbs": contracted_lbs,
            "shortfall_lbs": D(0),
            "substitution_covered_lbs": D(0),
            "settlement_variant": None,
            "settlement_damages_cents": None,
            "settlement_admin_fee_cents": None,
            "settlement_total_cents": None,
            "resale_credit_cents": 0,
            "defaulted_by_user_id": None,
            "carry_forward_requested_lbs": None,
            "carry_forward_fee_cents": None,
            "status": "ACTIVE",
        }
    )
    set_dt(contract, "delivery_window_start", window_start, window_start_raw)
    set_dt(contract, "delivery_window_end", window_end, window_end_raw)
    db.contracts[contract["id"]] = contract
    return contract


@bp.post("/hop-contracts")
def create_contract():
    require(("AllocationManager",))
    payload = body()
    brewer_id = f_str(payload, "brewer_id", min_len=1)
    variety_id = f_str(payload, "variety_id", min_len=1)
    program_id = f_str(payload, "crop_year_program_id", min_len=1)
    contract_type = f_enum(
        payload, "contract_type", ("FIXED_CROP_YEAR", "SPOT_HOLD"), required=True
    )
    contracted_lbs = f_dec(payload, "contracted_lbs", required=True, scale=2, minimum=0)
    price = f_dec(payload, "price_per_lb_cents", required=True, scale=2, exclusive_min=0)
    window_start, start_raw = f_dt(payload, "delivery_window_start", required=True)
    window_end, end_raw = f_dt(payload, "delivery_window_end", required=True)
    if window_end <= window_start:
        raise bad_request("delivery_window_end must be later than delivery_window_start")

    must_exist("brewers", brewer_id)
    variety = must_exist("varieties", variety_id)
    program = must_exist("programs", program_id)

    if program["status"] != "OPEN":
        raise ApiError(
            "ERR_PROGRAM_NOT_OPEN",
            "Contracts may only be written against an OPEN crop-year program",
        )
    if contracted_lbs < D(variety["min_order_lbs"]):
        raise bad_request(
            "contracted_lbs must be at least the variety's min_order_lbs"
        )
    for existing in db.contracts.values():
        if existing["brewer_id"] != brewer_id or existing["variety_id"] != variety_id:
            continue
        if existing["status"] in OVERLAP_EXEMPT_STATUSES:
            continue
        if (
            window_start <= existing["delivery_window_end"]
            and existing["delivery_window_start"] <= window_end
        ):
            raise ApiError(
                "ERR_CONTRACT_WINDOW_OVERLAP",
                "Delivery window intersects an existing contract for this brewer and variety",
            )

    contract = _new_contract_record(
        brewer_id,
        variety_id,
        program_id,
        contract_type,
        contracted_lbs,
        price,
        window_start,
        window_end,
        start_raw,
        end_raw,
    )
    return object_response(contract_out(contract), 201)


@bp.get("/hop-contracts/<contract_id>")
def get_contract(contract_id):
    actor = require(ALL_ROLES)
    contract = must_exist("contracts", contract_id)
    scope_brewer(actor, contract["brewer_id"])
    return object_response(contract_out(contract))


@bp.get("/hop-contracts")
def list_contracts():
    require(ALL_ROLES)
    limit, offset = pagination()
    args = request.args
    brewer_id = args.get("brewer_id")
    variety_id = args.get("variety_id")
    program_id = args.get("crop_year_program_id")
    lineage_id = args.get("carried_forward_from_contract_id")
    target_program_id = args.get("carry_forward_target_program_id")
    contract_type = args.get("contract_type")
    status = args.get("status")
    filter_exists("brewers", brewer_id)
    filter_exists("varieties", variety_id)
    filter_exists("programs", program_id)
    filter_exists("programs", target_program_id)
    filter_exists("contracts", lineage_id)

    items = []
    for contract in db.contracts.values():
        if brewer_id and contract["brewer_id"] != brewer_id:
            continue
        if variety_id and contract["variety_id"] != variety_id:
            continue
        if program_id and contract["crop_year_program_id"] != program_id:
            continue
        if lineage_id and contract["carried_forward_from_contract_id"] != lineage_id:
            continue
        if (
            target_program_id
            and contract["carry_forward_target_program_id"] != target_program_id
        ):
            continue
        if contract_type and contract["contract_type"] != contract_type:
            continue
        if status and contract["status"] != status:
            continue
        items.append(contract)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([contract_out(c) for c in page], len(items), limit, offset)


@bp.post("/hop-contracts/<contract_id>/carry-forward-requests")
def request_carry_forward(contract_id):
    actor = require(("Brewer",))
    payload = body()
    target_program_id = f_str(payload, "carry_forward_target_program_id", min_len=1)
    requested_lbs = f_dec(payload, "requested_lbs", required=True, scale=2, minimum=0)
    f_str(payload, "justification", required=False, max_len=1000)

    contract = must_exist("contracts", contract_id)
    scope_brewer(actor, contract["brewer_id"])
    if contract["status"] not in WORKING_STATUSES:
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "Carry-forward may only be requested from ACTIVE or SHORTFALL_ADJUSTED",
        )
    source_program = db.programs[contract["crop_year_program_id"]]
    if source_program["status"] != "HARVEST_REPORTED":
        raise ApiError(
            "ERR_INVALID_PROGRAM_STATE",
            "The contract's crop-year program must be in HARVEST_REPORTED",
        )
    target = db.programs.get(target_program_id)
    if (
        target is None
        or target["id"] == source_program["id"]
        or target["crop_year"] != source_program["crop_year"] + 1
        or target["status"] != "OPEN"
    ):
        raise ApiError(
            "ERR_INVALID_CARRY_FORWARD_TARGET",
            "The carry-forward target program is not the next OPEN crop year",
        )
    if requested_lbs > carry_forward_eligible(contract):
        raise ApiError(
            "ERR_CARRY_FORWARD_EXCEEDS_CAP",
            "requested_lbs exceeds the eligible carry-forward poundage",
        )
    if contract_remaining(contract) <= 0:
        raise ApiError(
            "ERR_NO_UNCOMMITTED_VOLUME",
            "The contract has no undrawn poundage left to carry forward",
        )

    contract["carry_forward_target_program_id"] = target_program_id
    contract["carry_forward_requested_lbs"] = requested_lbs
    contract["carry_forward_fee_cents"] = carry_forward_fee(contract, requested_lbs)
    contract["status"] = "CARRY_FORWARD_PENDING"
    touch(contract)
    return object_response(contract_out(contract))


@bp.post("/hop-contracts/<contract_id>/carry-forward-decision")
def decide_carry_forward(contract_id):
    require(("AllocationManager",))
    payload = body()
    decision = f_enum(payload, "decision", ("APPROVE", "DECLINE"), required=True)
    f_str(payload, "decision_note", required=False, max_len=1000)

    contract = must_exist("contracts", contract_id)
    if contract["status"] != "CARRY_FORWARD_PENDING":
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "Only a CARRY_FORWARD_PENDING contract carries a decision",
        )

    if decision == "DECLINE":
        contract["status"] = "ACTIVE"
        contract["carry_forward_target_program_id"] = None
        contract["carry_forward_requested_lbs"] = None
        contract["carry_forward_fee_cents"] = None
        touch(contract)
        return object_response(contract_out(contract))

    target = db.programs.get(contract["carry_forward_target_program_id"])
    if target is None or target["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_CARRY_FORWARD_TARGET",
            "The carry-forward target program is no longer OPEN",
        )
    carried = D(contract["carry_forward_requested_lbs"])
    contract["carried_forward_out_lbs"] = carried
    contract["status"] = "CARRIED_FORWARD"
    successor = _new_contract_record(
        contract["brewer_id"],
        contract["variety_id"],
        target["id"],
        contract["contract_type"],
        carried,
        contract["price_per_lb_cents"],
        contract["delivery_window_start"] + timedelta(days=CARRY_FORWARD_SHIFT_DAYS),
        contract["delivery_window_end"] + timedelta(days=CARRY_FORWARD_SHIFT_DAYS),
        carried_forward_from=contract["id"],
    )
    touch(contract)
    brewer = db.brewers[contract["brewer_id"]]
    post_receivable(brewer, int(contract["carry_forward_fee_cents"]))
    return object_response(contract_out(contract))


@bp.post("/hop-contracts/<contract_id>/declare-default")
def declare_default(contract_id):
    actor = require(("AllocationManager",))
    payload = body()
    f_str(payload, "default_reason", required=True, min_len=1, max_len=1000)
    f_dt(payload, "declared_at", required=False)

    contract = must_exist("contracts", contract_id)
    if contract["status"] not in WORKING_STATUSES:
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "Default may only be declared from ACTIVE or SHORTFALL_ADJUSTED",
        )
    remaining = contract_remaining(contract)
    if remaining <= 0:
        raise ApiError(
            "ERR_NO_UNCOMMITTED_VOLUME", "The contract has no undrawn poundage"
        )

    contract["defaulted_lbs"] = remaining
    contract["defaulted_by_user_id"] = actor.user_id
    contract.update(settle_default(contract, remaining))
    contract["status"] = "DEFAULTED"
    touch(contract)
    brewer = db.brewers[contract["brewer_id"]]
    post_receivable(
        brewer, int(contract["settlement_total_cents"]), propagate=True
    )
    return object_response(contract_out(contract))


@bp.post("/hop-contracts/<contract_id>/resale")
def resell_default(contract_id):
    actor = require(("AllocationManager",))
    payload = body()
    buyer_id = f_str(payload, "buyer_brewer_id", min_len=1)
    resale_lbs = f_dec(payload, "resale_lbs", required=True, scale=2, minimum=0)
    resale_price = f_dec(
        payload, "resale_price_cents_per_lb", required=True, scale=2, minimum=0
    )

    contract = must_exist("contracts", contract_id)
    must_exist("brewers", buyer_id)
    if contract["status"] != "DEFAULTED":
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE", "Only a DEFAULTED contract may be resold"
        )
    if actor.user_id == contract["defaulted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who declared the default may not action the resale",
        )
    if resale_lbs > D(contract["defaulted_lbs"]):
        raise ApiError(
            "ERR_RESALE_EXCEEDS_DEFAULTED_VOLUME",
            "resale_lbs exceeds the contract's defaulted poundage",
        )
    if buyer_id == contract["brewer_id"]:
        raise ApiError(
            "ERR_RESALE_BUYER_INVALID",
            "A brewery may not buy back its own defaulted poundage",
        )

    proceeds = rhu_int(resale_lbs * resale_price)
    settlement_total = int(contract["settlement_total_cents"] or 0)
    credit = proceeds if proceeds < settlement_total else settlement_total
    contract["defaulted_lbs"] = D(contract["defaulted_lbs"]) - resale_lbs
    contract["resold_lbs"] = D(contract["resold_lbs"]) + resale_lbs
    contract["resale_credit_cents"] = credit
    contract["status"] = "RESOLD"
    touch(contract)
    brewer = db.brewers[contract["brewer_id"]]
    post_receivable(brewer, -credit)
    return object_response(contract_out(contract))
