"""Retailer contracts and settlements (OCC, supersession, pinned pricing)."""
from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_FARM_SUSPENDED, ERR_CONTRACT_WINDOW_OVERLAP, ERR_CONTRACT_INACTIVE,
    ERR_LOT_QUALITY_HELD, ERR_SETTLEMENT_EMPTY,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_num, req_enum, req_date, opt_int, D, rhu, rhu_int
from services.domain import (
    get_entity, serialize_contract, contract_held_allocated_dozen,
    suspend_contract, void_draft_settlements,
    SIZE_PREMIUM_PCT, GRADE_UPLIFT_PCT,
)
from services.pricing import farm_cost_per_dozen_actual

bp = Blueprint("contracts", __name__)

CM = ["ContractManager"]
PRICING_MODELS = {"MARKET_INDEX", "COST_PLUS"}
CLAIMS = {"NONE", "CAGE_FREE", "PASTURE"}

REBATE_TIER_2 = 500000   # >= -> 0.04
REBATE_TIER_1 = 100000   # >= -> 0.02


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _get_contract(contractId):
    return get_entity("contracts", contractId, "RetailerContract")


def _windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) overlap; touching at a boundary is allowed."""
    return s1 < e2 and s2 < e1


def _check_window_overlap(farm_id, start, end, exclude_id=None):
    for c in STORE["contracts"].values():
        if c["farm_id"] != farm_id or c["status"] == "EXPIRED" or c["id"] == exclude_id:
            continue
        if _windows_overlap(start, end, c["effective_start"], c["effective_end"]):
            raise ApiError(ERR_CONTRACT_WINDOW_OVERLAP, 409, "Contract window overlaps another non-terminal contract of the farm")


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@bp.route("/api/contracts", methods=["POST"])
@endpoint(CM)
def create_contract(actor):
    body = _body()
    farm_id = body.get("farm_id")
    if isinstance(farm_id, str) and farm_id:
        get_entity("farms", farm_id, "Farm")
    farm_id = req_str(body, "farm_id")
    get_entity("farms", farm_id, "Farm")
    retailer_name = req_str(body, "retailer_name")
    pricing_model = req_enum(body, "pricing_model", PRICING_MODELS)
    spread_cents = req_int(body, "spread_cents", min_v=0)
    margin_pct = req_num(body, "margin_pct", min_v=0)
    claim_premium_pct = req_num(body, "claim_premium_pct", min_v=0)
    claim_required = req_enum(body, "claim_required", CLAIMS)
    effective_start = req_date(body, "effective_start")
    effective_end = req_date(body, "effective_end")
    if effective_start >= effective_end:
        raise ApiError(ERR_VALIDATION, 400, "effective_start must precede effective_end")
    weekly_min_dozen = req_int(body, "weekly_min_dozen", min_v=0)
    max_open_dozen = req_int(body, "max_open_dozen", min_v=1)
    # Model consistency: MARKET_INDEX -> margin_pct == 0; COST_PLUS -> spread_cents == 0.
    if pricing_model == "MARKET_INDEX" and D(margin_pct) != 0:
        raise ApiError(ERR_VALIDATION, 400, "margin_pct must be 0 for MARKET_INDEX contracts")
    if pricing_model == "COST_PLUS" and spread_cents != 0:
        raise ApiError(ERR_VALIDATION, 400, "spread_cents must be 0 for COST_PLUS contracts")
    # Tier 10: half-open window non-overlap per farm among non-terminal contracts.
    _check_window_overlap(farm_id, effective_start, effective_end)
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "retailer_name": retailer_name,
        "pricing_model": pricing_model,
        "spread_cents": spread_cents,
        "margin_pct": margin_pct,
        "claim_premium_pct": claim_premium_pct,
        "claim_required": claim_required,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "weekly_min_dozen": weekly_min_dozen,
        "max_open_dozen": max_open_dozen,
        "status": "DRAFT",
    })
    STORE["contracts"][rec["id"]] = rec
    return ok(pub(serialize_contract(rec)), status=201)


@bp.route("/api/contracts/<contractId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_contract(contractId, actor):
    return ok(pub(serialize_contract(_get_contract(contractId))), status=200)


@bp.route("/api/contracts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_contracts(actor):
    items = list(STORE["contracts"].values())
    farm_id = request.args.get("farm_id")
    status = request.args.get("status")
    if farm_id is not None:
        items = [c for c in items if c["farm_id"] == farm_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return paginate(items, lambda c: pub(serialize_contract(c)))


@bp.route("/api/contracts/<contractId>/activate", methods=["POST"])
@endpoint(CM)
def activate_contract(contractId, actor):
    contract = _get_contract(contractId)
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Contract must be DRAFT to activate")
    farm = get_entity("farms", contract["farm_id"], "Farm")
    # Tier 8: farm posture gate.
    if farm["compliance_posture"] == "SUSPENDED":
        raise ApiError(ERR_FARM_SUSPENDED, 409, "Farm compliance posture is SUSPENDED")
    # Tier 10: window overlap re-checked at activation.
    _check_window_overlap(contract["farm_id"], contract["effective_start"],
                          contract["effective_end"], exclude_id=contract["id"])
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(pub(serialize_contract(contract)), status=200)


@bp.route("/api/contracts/<contractId>/suspend", methods=["POST"])
@endpoint(CM)
def suspend_contract_endpoint(contractId, actor):
    contract = _get_contract(contractId)
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Contract must be ACTIVE to suspend")
    suspend_contract(contract)  # cascades DRAFT settlements -> VOIDED
    return ok(pub(serialize_contract(contract)), status=200)


@bp.route("/api/contracts/<contractId>/reinstate", methods=["POST"])
@endpoint(CM)
def reinstate_contract(contractId, actor):
    contract = _get_contract(contractId)
    if contract["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Contract must be SUSPENDED to reinstate")
    farm = get_entity("farms", contract["farm_id"], "Farm")
    # Tier 8: farm posture gate.
    if farm["compliance_posture"] == "SUSPENDED":
        raise ApiError(ERR_FARM_SUSPENDED, 409, "Farm compliance posture is SUSPENDED")
    # Tier 9: no held allocated lots.
    if contract_held_allocated_dozen(contract) != 0:
        raise ApiError(ERR_LOT_QUALITY_HELD, 409, "Contract has held allocated lots")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(pub(serialize_contract(contract)), status=200)


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------
@bp.route("/api/settlements", methods=["POST"])
@endpoint(CM)
def create_settlement(actor):
    body = _body()
    # Tier 4: body FK existence.
    contract_id = body.get("contract_id")
    if isinstance(contract_id, str) and contract_id:
        get_entity("contracts", contract_id, "RetailerContract")
    contract_id = req_str(body, "contract_id")
    contract = get_entity("contracts", contract_id, "RetailerContract")
    # Tier 5: schema.
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if period_start > period_end:
        raise ApiError(ERR_VALIDATION, 400, "period_start must not be after period_end")
    market_index_cents = opt_int(body, "market_index_cents", min_v=0)
    if contract["pricing_model"] == "MARKET_INDEX" and market_index_cents is None:
        raise ApiError(ERR_VALIDATION, 400, "market_index_cents is required for MARKET_INDEX contracts")
    if "expected_contract_version" not in body or body["expected_contract_version"] is None:
        raise ApiError(ERR_VALIDATION, 400, "Missing required field: expected_contract_version")
    ecv = body["expected_contract_version"]
    if not isinstance(ecv, int) or isinstance(ecv, bool):
        raise ApiError(ERR_VALIDATION, 400, "expected_contract_version must be an integer")
    # Tier 7: optimistic concurrency on the parent contract.
    if ecv != contract["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_contract_version does not match the contract version")
    # Tier 8: contract must be ACTIVE.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_INACTIVE, 409, "Contract is not ACTIVE")
    # Supersession: overlapping DRAFT settlements of this contract auto-VOID.
    for s in STORE["settlements"].values():
        if s["contract_id"] == contract["id"] and s["status"] == "DRAFT":
            if period_start <= s["period_end"] and s["period_start"] <= period_end:
                s["status"] = "VOIDED"
                touch(s)
    rec = new_record()
    rec.update({
        "contract_id": contract_id,
        "period_start": period_start,
        "period_end": period_end,
        "market_index_cents": market_index_cents,
        "expected_contract_version": ecv,
        "status": "DRAFT",
        "pricing_model_used": None,
        "lines": [],
        "cost_per_dozen_cents": None,
        "subtotal_cents": None,
        "rebate_pct": None,
        "rebate_cents": None,
        "total_cents": None,
    })
    STORE["settlements"][rec["id"]] = rec
    touch(contract)  # creation bumps the parent contract version (PRD §3.6)
    return ok(pub(rec), status=201)


@bp.route("/api/settlements/<settlementId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_settlement(settlementId, actor):
    return ok(pub(get_entity("settlements", settlementId, "Settlement")), status=200)


@bp.route("/api/settlements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_settlements(actor):
    items = list(STORE["settlements"].values())
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if contract_id is not None:
        items = [s for s in items if s["contract_id"] == contract_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return paginate(items, pub)


@bp.route("/api/settlements/<settlementId>/finalize", methods=["POST"])
@endpoint(CM)
def finalize_settlement(settlementId, actor):
    settlement = get_entity("settlements", settlementId, "Settlement")
    # Tier 6: DRAFT -> FINALIZED.
    if settlement["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Settlement must be DRAFT to finalize")
    contract = get_entity("contracts", settlement["contract_id"], "RetailerContract")
    # Tier 8: contract must be ACTIVE.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_INACTIVE, 409, "Contract is not ACTIVE")
    ps, pe = settlement["period_start"], settlement["period_end"]
    # Step 1: covered SHIPPED lots, pack_date ASC, created_at ASC.
    covered = [
        l for l in STORE["lots"].values()
        if l.get("contract_id") == contract["id"]
        and l["lifecycle_status"] == "SHIPPED"
        and l.get("ship_date") is not None
        and ps <= l["ship_date"] <= pe
    ]
    covered.sort(key=lambda l: (l["pack_date"], l["created_at"], l["_seq"]))
    if not covered:
        raise ApiError(ERR_SETTLEMENT_EMPTY, 422, "No SHIPPED lots of the contract fall in the period")
    # Step 2: per-line pricing, rounded per line first.
    pricing_model_used = contract["pricing_model"]
    cost_per_dozen_cents = None
    if pricing_model_used == "MARKET_INDEX":
        base = D(settlement["market_index_cents"] + contract["spread_cents"])
    else:  # COST_PLUS
        cpd = farm_cost_per_dozen_actual(
            get_entity("farms", contract["farm_id"], "Farm"), ps, pe
        )  # raises ERR_SETTLEMENT_EMPTY on zero eggs
        cost_per_dozen_cents = float(cpd)
        base = cpd * (D(1) + D(contract["margin_pct"]))
    lines = []
    for lot in covered:
        multiplier = (
            D(1)
            + SIZE_PREMIUM_PCT[lot["size_class"]]
            + GRADE_UPLIFT_PCT[lot["grade"]]
            + (D(contract["claim_premium_pct"]) if contract["claim_required"] != "NONE" else D(0))
        )
        price = rhu_int(base * multiplier)  # per-line rounding first
        lines.append({
            "lot_id": lot["id"],
            "size_class": lot["size_class"],
            "grade": lot["grade"],
            "dozen_count": lot["dozen_count"],
            "price_cents_per_dozen": price,
            "line_amount_cents": price * lot["dozen_count"],
        })
    # Steps 4-7: subtotal, pre-rebate tier selection, rebate, total.
    subtotal = sum(l["line_amount_cents"] for l in lines)
    if subtotal >= REBATE_TIER_2:
        rebate_pct = D("0.04")
    elif subtotal >= REBATE_TIER_1:
        rebate_pct = D("0.02")
    else:
        rebate_pct = D("0")
    rebate_cents = rhu_int(D(subtotal) * rebate_pct)
    total_cents = subtotal - rebate_cents
    # Covered lots cascade SHIPPED -> CLOSED.
    for lot in covered:
        lot["lifecycle_status"] = "CLOSED"
        touch(lot)
    settlement.update({
        "status": "FINALIZED",
        "pricing_model_used": pricing_model_used,
        "lines": lines,
        "cost_per_dozen_cents": cost_per_dozen_cents,
        "subtotal_cents": subtotal,
        "rebate_pct": float(rebate_pct),
        "rebate_cents": rebate_cents,
        "total_cents": total_cents,
    })
    touch(settlement)
    return ok(pub(settlement), status=200)
