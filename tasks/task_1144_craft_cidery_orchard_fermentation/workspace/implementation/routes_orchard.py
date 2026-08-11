"""Varieties, orchard contracts, harvest lots."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CONTRACT_HAS_OPEN_LOTS,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    invalid_state,
    not_found,
    validation,
)
from middleware import require_roles
from response import paginate, parse_ts, success_object
from services import (
    compute_shortfall_penalty,
    emit_event,
    recompute_contract_received,
    ser_contract,
    ser_lot,
    ser_variety,
)

bp = Blueprint("orchard", __name__, url_prefix="/cidery")


def body():
    return request.get_json(silent=True) or {}


# --- AppleVariety --------------------------------------------------------------
@bp.post("/varieties")
@require_roles("OrchardManager")
def create_variety():
    b = body()
    rec = {
        "code": b.get("code"),
        "tannin_g_per_l": b.get("tannin_g_per_l"),
        "brix_at_harvest": b.get("brix_at_harvest"),
        "acidity_g_per_l": b.get("acidity_g_per_l"),
        "is_bittersweet": bool(b.get("is_bittersweet", False)),
    }
    db.stamp_new(rec, common=False)
    db.store["varieties"][rec["id"]] = rec
    return success_object(ser_variety(rec), 201)


@bp.get("/varieties/<varietyId>")
@require_roles(
    "OrchardManager", "CellarLead", "ComplianceOfficer", "SalesRep",
    "PackagingOperator", "PlatformAdmin",
)
def get_variety(varietyId):
    rec = db.store["varieties"].get(varietyId)
    if rec is None:
        raise not_found("variety")
    return success_object(ser_variety(rec))


@bp.get("/varieties")
@require_roles(
    "OrchardManager", "CellarLead", "ComplianceOfficer", "SalesRep",
    "PackagingOperator", "PlatformAdmin",
)
def list_varieties():
    return paginate(list(db.store["varieties"].values()), ser_variety)


# --- OrchardContract -------------------------------------------------------------
@bp.post("/contracts")
@require_roles("OrchardManager")
def create_contract():
    b = body()
    rec = {
        "grower_name": b.get("grower_name"),
        "region_code": b.get("region_code"),
        "season_year": b.get("season_year"),
        "committed_weight_lbs": b.get("committed_weight_lbs"),
        "received_weight_lbs": 0,
        "price_per_lb_cents": b.get("price_per_lb_cents"),
        "shortfall_penalty_cents_per_lb": b.get("shortfall_penalty_cents_per_lb", 0),
        "settlement_penalty_cents": None,
        "status": "DRAFT",
    }
    db.stamp_new(rec)
    db.store["contracts"][rec["id"]] = rec
    return success_object(ser_contract(rec), 201)


def _get_contract(contractId):
    rec = db.store["contracts"].get(contractId)
    if rec is None:
        raise not_found("contract")
    return rec


@bp.get("/contracts/<contractId>")
@require_roles("OrchardManager", "ComplianceOfficer", "PlatformAdmin")
def get_contract(contractId):
    return success_object(ser_contract(_get_contract(contractId)))


@bp.get("/contracts")
@require_roles("OrchardManager", "ComplianceOfficer", "PlatformAdmin")
def list_contracts():
    items = list(db.store["contracts"].values())
    season_year = request.args.get("season_year")
    if season_year is not None:
        try:
            season_year_i = int(season_year)
            items = [c for c in items if c["season_year"] == season_year_i]
        except ValueError:
            items = []
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, ser_contract)


@bp.post("/contracts/<contractId>/activate")
@require_roles("OrchardManager")
def activate_contract(contractId):
    contract = _get_contract(contractId)
    if contract["status"] != "DRAFT":
        raise invalid_state("contract is not DRAFT")
    if not (contract["committed_weight_lbs"] or 0) > 0:
        raise invalid_state("committed_weight_lbs must be greater than zero")
    if (contract["season_year"] or 0) < db.now().year:
        raise invalid_state("season_year is before the current year")
    b = body()
    expected = b.get("expected_contract_version")
    if expected is not None and expected != contract["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_contract_version does not match current version",
            412,
        )
    before = {"status": contract["status"]}
    contract["status"] = "ACTIVE"
    db.bump(contract)
    emit_event(
        "OrchardContract", contract["id"], "CONTRACT_ACTIVATED",
        before, {"status": "ACTIVE"},
    )
    return success_object(ser_contract(contract))


@bp.post("/contracts/<contractId>/settle")
@require_roles("OrchardManager")
def settle_contract(contractId):
    contract = _get_contract(contractId)
    if contract["status"] != "ACTIVE":
        raise invalid_state("contract is not ACTIVE")
    lots = [
        lot for lot in db.store["harvest_lots"].values()
        if lot["contract_id"] == contract["id"]
    ]
    if any(lot["status"] not in ("PRESSED", "SPOILED") for lot in lots):
        raise ApiError(
            ERR_CONTRACT_HAS_OPEN_LOTS,
            "contract has lots not in PRESSED or SPOILED",
            409,
        )
    received = sum(
        lot["weight_lbs"] for lot in lots
        if lot["status"] in ("PRESSED", "PARTIALLY_PRESSED")
    )
    penalty = compute_shortfall_penalty(contract, received)
    before = {
        "status": contract["status"],
        "received_weight_lbs": contract["received_weight_lbs"],
    }
    contract["status"] = "SETTLED"
    contract["settlement_penalty_cents"] = penalty
    db.bump(contract)
    emit_event(
        "OrchardContract", contract["id"], "CONTRACT_SETTLED",
        before,
        {
            "status": "SETTLED",
            "received_weight_lbs": contract["received_weight_lbs"],
            "settlement_penalty_cents": penalty,
        },
    )
    return success_object(ser_contract(contract))


@bp.post("/contracts/<contractId>/void")
@require_roles("OrchardManager")
def void_contract(contractId):
    contract = _get_contract(contractId)
    if contract["status"] != "DRAFT":
        raise invalid_state("only a DRAFT contract can be voided")
    if any(
        lot["contract_id"] == contract["id"]
        for lot in db.store["harvest_lots"].values()
    ):
        raise invalid_state("contract has linked harvest lots")
    contract["status"] = "VOIDED"
    db.bump(contract)
    return success_object(ser_contract(contract))


# --- HarvestLot ---------------------------------------------------------------------
@bp.post("/contracts/<contractId>/harvest-lots")
@require_roles("OrchardManager")
def create_harvest_lot(contractId):
    contract = _get_contract(contractId)
    b = body()
    variety = db.store["varieties"].get(b.get("variety_id"))
    if variety is None:
        raise not_found("variety")
    if contract["status"] != "ACTIVE":
        raise invalid_state("contract is not ACTIVE")
    try:
        received_at = parse_ts(b.get("received_at"))
    except (TypeError, ValueError):
        raise validation("received_at must be an ISO8601 timestamp")
    rec = {
        "contract_id": contract["id"],
        "variety_id": variety["id"],
        "received_at": received_at,
        "weight_lbs": b.get("weight_lbs"),
        "measured_brix": b.get("measured_brix"),
        "measured_tannin_g_per_l": b.get("measured_tannin_g_per_l"),
        "pressed_weight_lbs": 0,
        "status": "RECEIVED",
    }
    db.stamp_new(rec)
    db.store["harvest_lots"][rec["id"]] = rec
    recompute_contract_received(contract)
    return success_object(ser_lot(rec), 201)


@bp.get("/harvest-lots/<lotId>")
@require_roles("OrchardManager", "CellarLead", "ComplianceOfficer", "PlatformAdmin")
def get_harvest_lot(lotId):
    rec = db.store["harvest_lots"].get(lotId)
    if rec is None:
        raise not_found("harvest lot")
    return success_object(ser_lot(rec))


@bp.get("/contracts/<contractId>/harvest-lots")
@require_roles("OrchardManager", "CellarLead", "ComplianceOfficer", "PlatformAdmin")
def list_contract_lots(contractId):
    contract = _get_contract(contractId)
    items = [
        lot for lot in db.store["harvest_lots"].values()
        if lot["contract_id"] == contract["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [lot for lot in items if lot["status"] == status]
    return paginate(items, ser_lot)


@bp.get("/harvest-lots")
@require_roles("OrchardManager", "CellarLead", "ComplianceOfficer", "PlatformAdmin")
def list_harvest_lots():
    items = list(db.store["harvest_lots"].values())
    contract_id = request.args.get("contract_id")
    if contract_id is not None:
        items = [lot for lot in items if lot["contract_id"] == contract_id]
    variety_id = request.args.get("variety_id")
    if variety_id is not None:
        items = [lot for lot in items if lot["variety_id"] == variety_id]
    status = request.args.get("status")
    if status is not None:
        items = [lot for lot in items if lot["status"] == status]
    return paginate(items, ser_lot)


@bp.post("/harvest-lots/<lotId>/spoil")
@require_roles("CellarLead")
def spoil_harvest_lot(lotId):
    lot = db.store["harvest_lots"].get(lotId)
    if lot is None:
        raise not_found("harvest lot")
    if lot["status"] != "RECEIVED":
        raise invalid_state("lot is not RECEIVED")
    # lot must not be referenced by any press batch in PLANNED/PRESSING
    for line in db.store["blend_lines"].values():
        if line["harvest_lot_id"] == lot["id"]:
            batch = db.store["press_batches"].get(line["press_batch_id"])
            if batch is not None and batch["status"] in ("PLANNED", "PRESSING"):
                raise invalid_state(
                    "lot is referenced by a PLANNED or PRESSING press batch"
                )
    before = {"status": lot["status"]}
    lot["status"] = "SPOILED"
    db.bump(lot)
    contract = db.store["contracts"].get(lot["contract_id"])
    if contract is not None:
        recompute_contract_received(contract)
    emit_event("HarvestLot", lot["id"], "LOT_SPOILED", before, {"status": "SPOILED"})
    return success_object(ser_lot(lot))
