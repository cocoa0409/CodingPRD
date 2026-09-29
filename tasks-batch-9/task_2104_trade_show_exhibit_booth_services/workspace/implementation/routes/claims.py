"""Damage and loss claims: adjudication variants, appeals and settlement."""
from flask import Blueprint, g

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles, segregation
from services import calc, state
from validation import json_body, require_row

bp = Blueprint("claims", __name__)
store = db.store

TERMINAL = ("SETTLED",)


@bp.post("/damage-claims")
def file_claim():
    uid, _role = require_roles("Exhibitor", "ClaimsAdjuster")
    body = json_body()
    own_exhibitor(body.peek_str("exhibitor_id"))

    exhibitor_id = body.string("exhibitor_id")
    asset_id = body.string("asset_id")
    claim_type = body.enum("claim_type", ("DAMAGE", "LOSS"))
    declared_value = body.integer("declared_value_cents")
    incident_at = body.datetime_str("incident_at")
    crate_id = body.string("crate_id", required=False, default=None)
    shipment_id = body.string("shipment_id", required=False, default=None)

    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    asset = require_row(store.assets, asset_id, "ERR_ASSET_NOT_FOUND", "Exhibit asset")
    crate = None
    if crate_id is not None:
        crate = require_row(store.crates, crate_id, "ERR_CRATE_NOT_FOUND", "Crate")
    if shipment_id is not None:
        require_row(store.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND", "Shipment")

    if asset["exhibitor_id"] != exhibitor_id or \
            (crate is not None and crate.get("asset_id") != asset_id):
        raise ApiError("ERR_CLAIM_REFERENCE_MISMATCH",
                       "The cited crate or asset does not belong with this claim")

    if declared_value > int(asset["list_value_cents"]):
        raise ApiError("ERR_DECLARED_VALUE_EXCEEDS_ASSET",
                       "declared_value_cents exceeds the asset list value")

    claim = {
        "id": db.new_id(),
        "exhibitor_id": exhibitor_id,
        "asset_id": asset_id,
        "crate_id": crate_id,
        "shipment_id": shipment_id,
        "claim_type": claim_type,
        "declared_value_cents": declared_value,
        "incident_at": incident_at,
        "coverage_basis": "TARIFF_LIABILITY",
        "settlement_cents": None,
        "filed_by_user_id": uid,
        "adjudicated_by_user_id": None,
        "appeal_count": 0,
        "status": "FILED",
    }
    db.stamp_common(claim)
    store.claims[claim["id"]] = claim
    return response.created(claim)


@bp.get("/damage-claims/<claim_id>")
def get_claim(claim_id):
    require_roles(ANY_ROLE)
    claim = store.claims.get(claim_id)
    own_exhibitor(claim["exhibitor_id"] if claim else None)
    claim = require_row(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "Damage claim")
    return response.ok(claim)


@bp.get("/damage-claims")
def list_claims():
    require_roles(ANY_ROLE)
    rows = list(store.claims.values())
    rows = response.filter_rows(rows, "exhibitor_id", "asset_id", "crate_id",
                                "shipment_id", "status")
    return response.listing(rows)


@bp.post("/damage-claims/<claim_id>/investigation")
def investigation(claim_id):
    require_roles("ClaimsAdjuster")
    json_body()
    claim = require_row(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "Damage claim")
    asset = store.assets.get(claim["asset_id"])

    guards.transition(claim["status"], TERMINAL, ("FILED",))
    if asset is not None and asset["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The claimed asset has already been retired")

    claim["status"] = "UNDER_INVESTIGATION"
    db.touch(claim)
    return response.ok(claim)


@bp.post("/damage-claims/<claim_id>/adjudication")
def adjudication(claim_id):
    require_roles("ClaimsAdjuster")
    body = json_body()
    claim = store.claims.get(claim_id)
    if claim is not None:
        segregation(claim.get("filed_by_user_id"))

    decision = body.enum("decision", ("APPROVE", "DENY"))
    coverage_basis = body.enum("coverage_basis", ("TARIFF_LIABILITY", "DECLARED_VALUE"),
                               required=False, default=None)
    body.string("note", required=False, default=None)
    claim = require_row(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "Damage claim")
    asset = store.assets.get(claim["asset_id"])

    guards.transition(claim["status"], TERMINAL, ("UNDER_INVESTIGATION",))

    if decision == "DENY":
        claim["adjudicated_by_user_id"] = g.user_id
        claim["status"] = "DENIED"
        db.touch(claim)
        return response.ok(claim)

    if asset is not None and asset["status"] in ("RETIRED", "WRITTEN_OFF"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The claimed asset is no longer adjudicable")

    basis = coverage_basis or "TARIFF_LIABILITY"
    shipment = store.shipments.get(claim.get("shipment_id"))
    if basis == "DECLARED_VALUE" and (shipment is None or
                                      not shipment.get("declared_value_coverage")):
        raise ApiError("ERR_COVERAGE_BASIS_UNAVAILABLE",
                       "The cited shipment does not carry declared-value coverage")

    if basis == "DECLARED_VALUE":
        settlement = calc.declared_value_settlement(
            claim["declared_value_cents"], asset["list_value_cents"],
            asset["condition_grade"])
    else:
        crate = store.crates.get(claim.get("crate_id"))
        weight_basis = crate["weight_lbs"] if crate is not None \
            else asset["shipping_weight_lbs"]
        settlement = calc.tariff_settlement(claim["declared_value_cents"], weight_basis)

    claim["coverage_basis"] = basis
    claim["settlement_cents"] = settlement
    claim["adjudicated_by_user_id"] = g.user_id
    claim["status"] = "APPROVED"
    db.touch(claim)

    if asset is not None:
        if claim["claim_type"] == "DAMAGE":
            _downgrade(asset)
        else:
            _write_off(asset)
    return response.ok(claim)


def _downgrade(asset):
    grades = calc.CONDITION_GRADES
    index = grades.index(asset["condition_grade"]) if asset["condition_grade"] in grades \
        else 0
    asset["condition_grade"] = grades[min(index + 1, len(grades) - 1)]
    db.touch(asset)


def _write_off(asset):
    """Loss cascade: asset written off, its crates lost, warehouse weight freed."""
    asset["status"] = "WRITTEN_OFF"
    asset["current_warehouse_id"] = None
    asset["stored_since"] = None
    db.touch(asset)

    touched_warehouses = []
    for crate in store.crates.values():
        if crate.get("asset_id") != asset["id"]:
            continue
        if crate["status"] in ("LOST", "RELEASED_TO_CARRIER"):
            continue
        warehouse = state.warehouse_of_crate(crate)
        crate["status"] = "LOST"
        crate["warehouse_id"] = None
        crate["stored_since"] = None
        db.touch(crate)
        if warehouse is not None and warehouse not in touched_warehouses:
            touched_warehouses.append(warehouse)
    for warehouse in touched_warehouses:
        state.recompute_warehouse_cwt(warehouse)

    for work_order in store.refurbs.values():
        if work_order["asset_id"] == asset["id"] and \
                work_order["status"] in ("OPEN", "IN_PROGRESS"):
            work_order["status"] = "CANCELLED"
            db.touch(work_order)


@bp.post("/damage-claims/<claim_id>/appeal")
def appeal(claim_id):
    require_roles("Exhibitor", "ClaimsAdjuster")
    body = json_body()
    claim = store.claims.get(claim_id)
    own_exhibitor(claim["exhibitor_id"] if claim else None)
    body.string("note")
    claim = require_row(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "Damage claim")

    guards.transition(claim["status"], TERMINAL, ("DENIED",))
    if int(claim["appeal_count"]) >= calc.MAX_CLAIM_APPEALS:
        raise ApiError("ERR_CLAIM_APPEAL_LIMIT", "The appeal budget is exhausted")

    claim["appeal_count"] = int(claim["appeal_count"]) + 1
    claim["adjudicated_by_user_id"] = None
    claim["status"] = "UNDER_INVESTIGATION"
    db.touch(claim)
    return response.ok(claim)


@bp.post("/damage-claims/<claim_id>/settlement")
def settlement(claim_id):
    require_roles("ClaimsAdjuster", "FinanceController")
    json_body()
    claim = require_row(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "Damage claim")

    guards.transition(claim["status"], TERMINAL, ("APPROVED",))
    if claim["settlement_cents"] is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The claim carries no settlement figure")

    claim["status"] = "SETTLED"
    db.touch(claim)

    exhibitor = store.exhibitors.get(claim["exhibitor_id"])
    if exhibitor is not None:
        state.recompute_balance(exhibitor)
        state.refresh_exhibitor_booths(exhibitor["id"])
    return response.ok(claim)
