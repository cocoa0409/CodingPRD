"""Production pathways, power contracts, lots, purity testing and release."""
from datetime import timedelta
from decimal import Decimal as D

from flask import Blueprint

import derive
import serializers as ser
from auth import actor
from constants import (
    ANALYTE_ORDER,
    CONTRACT_CHANGEOVER_BUFFER_HOURS,
    ELECTROLYSIS_PATHWAYS,
    LOT_STATUSES,
    OPTIONAL_ANALYTES,
    PATHWAYS,
    QA_STATUSES,
    REQUIRED_ANALYTES,
    VERDICTS,
)
from envelope import created, listing, ok
from errors import raise_error
from helpers import get_asset, get_lot
from store import base_row, db, sort_created, touch
from validate import (
    bad,
    f_bool,
    f_dt,
    f_enum,
    f_num,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
)

bp = Blueprint("production", __name__)


# =========================================================================
# ProductionAsset
# =========================================================================
@bp.get("/production-assets/<asset_id>")
def read_asset(asset_id):
    actor("PlatformAdmin", "ProductionEngineer", "ComplianceAdmin", "ProgramAuditor")
    return ok(ser.production_asset(get_asset(asset_id)))


@bp.post("/production-assets")
def create_asset():
    actor("PlatformAdmin", "ProductionEngineer")
    body = json_body()
    asset_code = f_str(body, "asset_code")
    pathway = f_enum(body, "pathway", PATHWAYS)
    nameplate_kg_per_day = f_num(body, "nameplate_kg_per_day", 3, gt=D(0))
    ccs_capture_rate = f_num(body, "ccs_capture_rate", 4, required=False,
                             default=D("0.0000"), ge=D(0), le=D(1))
    operator_org = f_str(body, "operator_org")

    if pathway != "SMR_CCS" and ccs_capture_rate != 0:
        bad("Field 'ccs_capture_rate' must be 0 unless 'pathway' is SMR_CCS.")

    if any(r["asset_code"] == asset_code for r in db.production_assets.values()):
        raise_error("ERR_CODE_TAKEN")

    row = base_row()
    row.update({
        "asset_code": asset_code,
        "pathway": pathway,
        "nameplate_kg_per_day": nameplate_kg_per_day,
        "ccs_capture_rate": ccs_capture_rate,
        "operator_org": operator_org,
    })
    db.production_assets[row["id"]] = row
    return created(ser.production_asset(row))


# =========================================================================
# PowerSupplyContract
# =========================================================================
@bp.get("/production-assets/<asset_id>/power-supply-contracts")
def list_contracts(asset_id):
    actor("PlatformAdmin", "ProductionEngineer", "ComplianceAdmin")
    asset = get_asset(asset_id)
    limit, offset = pagination()
    rows = derive.contracts_of_asset(asset["id"])
    page = paginate(rows, limit, offset)
    return listing([ser.power_contract(r) for r in page], limit, offset, len(rows))


@bp.post("/production-assets/<asset_id>/power-supply-contracts")
def create_contract(asset_id):
    actor("ProductionEngineer", "PlatformAdmin")
    asset = get_asset(asset_id)
    body = json_body()
    contract_code = f_str(body, "contract_code")
    grid_ci = f_num(body, "grid_ci_gco2e_per_mwh", 2, ge=D(0))
    annual_pct = f_num(body, "annual_renewable_pct", 3, ge=D(0), le=D(100))
    hourly_pct = f_num(body, "hourly_matched_renewable_pct", 3, ge=D(0), le=D(100))
    hourly_enabled = f_bool(body, "hourly_matching_enabled", required=False, default=False)
    effective_from, raw_from = f_dt(body, "effective_from")
    effective_to, raw_to = f_dt(body, "effective_to")
    if effective_to <= effective_from:
        bad("Field 'effective_to' must be strictly after 'effective_from'.")

    if any(r["contract_code"] == contract_code for r in db.power_contracts.values()):
        raise_error("ERR_CODE_TAKEN")

    buffer = timedelta(hours=CONTRACT_CHANGEOVER_BUFFER_HOURS)
    for existing in derive.contracts_of_asset(asset["id"]):
        if (effective_from < existing["effective_to"] + buffer
                and existing["effective_from"] < effective_to + buffer):
            raise_error("ERR_POWER_CONTRACT_OVERLAP")

    row = base_row()
    row.update({
        "production_asset_id": asset["id"],
        "contract_code": contract_code,
        "grid_ci_gco2e_per_mwh": grid_ci,
        "annual_renewable_pct": annual_pct,
        "hourly_matched_renewable_pct": hourly_pct,
        "hourly_matching_enabled": hourly_enabled,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "_raw": {"effective_from": raw_from, "effective_to": raw_to},
    })
    db.power_contracts[row["id"]] = row
    return created(ser.power_contract(row))


# =========================================================================
# ProductionLot
# =========================================================================
@bp.get("/production-lots/<lot_id>")
def read_lot(lot_id):
    actor("PlatformAdmin", "ProductionEngineer", "QualityAnalyst", "ComplianceAdmin",
          "ProgramAuditor", "LogisticsDispatcher")
    return ok(ser.production_lot(get_lot(lot_id)))


@bp.get("/production-lots")
def list_lots():
    actor("PlatformAdmin", "ProductionEngineer", "QualityAnalyst", "ComplianceAdmin",
          "ProgramAuditor")
    limit, offset = pagination()
    asset_id = q_str("production_asset_id")
    predecessor_id = q_str("predecessor_lot_id")
    qa_status = q_enum("qa_status", QA_STATUSES)
    status = q_enum("status", LOT_STATUSES)
    rows = sort_created(list(db.production_lots.values()))
    if asset_id is not None:
        rows = [r for r in rows if r["production_asset_id"] == asset_id]
    if predecessor_id is not None:
        rows = [r for r in rows if r["predecessor_lot_id"] == predecessor_id]
    if qa_status is not None:
        rows = [r for r in rows if r["qa_status"] == qa_status]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return listing([ser.production_lot(r) for r in page], limit, offset, len(rows))


@bp.post("/production-lots")
def create_lot():
    actor("ProductionEngineer")
    body = json_body()
    asset_id = f_str(body, "production_asset_id")
    lot_code = f_str(body, "lot_code")
    mass_kg = f_num(body, "mass_kg", 3, gt=D(0))
    energy_consumed_kwh = f_num(body, "energy_consumed_kwh", 3, ge=D(0))
    feedstock = f_num(body, "feedstock_consumed_mmbtu", 3, required=False,
                      default=D("0.000"), ge=D(0))
    predecessor_id = f_str(body, "predecessor_lot_id", required=False, default=None)
    carryover_kg = f_num(body, "carryover_kg", 3, required=False,
                         default=D("0.000"), ge=D(0))
    production_start_at, raw_start = f_dt(body, "production_start_at")
    production_end_at, raw_end = f_dt(body, "production_end_at")

    if production_end_at <= production_start_at:
        bad("Field 'production_end_at' must be strictly after 'production_start_at'.")
    if predecessor_id is None and carryover_kg != 0:
        bad("Field 'carryover_kg' must be 0 when 'predecessor_lot_id' is absent.")
    if carryover_kg > mass_kg:
        bad("Field 'carryover_kg' must not exceed 'mass_kg'.")

    asset = get_asset(asset_id)
    predecessor = get_lot(predecessor_id) if predecessor_id is not None else None

    if asset["pathway"] in ELECTROLYSIS_PATHWAYS and feedstock != 0:
        bad("Field 'feedstock_consumed_mmbtu' must be 0 for an electrolysis pathway.")
    if predecessor is not None and predecessor["production_asset_id"] != asset["id"]:
        bad("The predecessor lot must belong to the same 'production_asset_id'.")

    if any(r["lot_code"] == lot_code for r in db.production_lots.values()):
        raise_error("ERR_LOT_CODE_TAKEN")

    contract = derive.select_power_contract(asset["id"], production_end_at)
    if contract is None:
        raise_error("ERR_NO_POWER_CONTRACT")

    row = base_row()
    row.update({
        "production_asset_id": asset["id"],
        "predecessor_lot_id": predecessor_id,
        "lot_code": lot_code,
        "mass_kg": mass_kg,
        "energy_consumed_kwh": energy_consumed_kwh,
        "feedstock_consumed_mmbtu": feedstock,
        "carryover_kg": carryover_kg,
        "production_start_at": production_start_at,
        "production_end_at": production_end_at,
        "selected_power_contract_id": contract["id"],
        "ci_provisional_gco2e_per_mj": None,
        "ci_certified_gco2e_per_mj": None,
        "ci_variant_applied": None,
        "qa_status": "PENDING",
        "ci_status": "PENDING",
        "status": "PRODUCED",
        "released_by_user_id": None,
        "_raw": {"production_start_at": raw_start, "production_end_at": raw_end},
    })
    row["ci_provisional_gco2e_per_mj"] = derive.carbon_intensity(
        row, contract, asset, "ANNUAL_AVERAGE", certified=False)
    db.production_lots[row["id"]] = row
    return created(ser.production_lot(row))


# =========================================================================
# PurityTest
# =========================================================================
@bp.get("/production-lots/<lot_id>/purity-tests")
def list_tests(lot_id):
    actor("PlatformAdmin", "QualityAnalyst", "ComplianceAdmin", "ProgramAuditor")
    lot = get_lot(lot_id)
    limit, offset = pagination()
    verdict = q_enum("verdict", VERDICTS)
    rows = derive.tests_of_lot(lot["id"])
    rows.sort(key=lambda t: (t["sampled_at"], t["created_at"], t["_seq"]), reverse=True)
    if verdict is not None:
        rows = [r for r in rows if r["verdict"] == verdict]
    page = paginate(rows, limit, offset)
    return listing([ser.purity_test(r) for r in page], limit, offset, len(rows))


@bp.post("/production-lots/<lot_id>/purity-tests")
def create_test(lot_id):
    user_id, _role = actor("QualityAnalyst")
    lot = get_lot(lot_id)
    body = json_body()
    sampled_at, raw_sampled = f_dt(body, "sampled_at")
    values = {}
    for name in REQUIRED_ANALYTES:
        values[name] = f_num(body, name, 3, ge=D(0))
    for name in OPTIONAL_ANALYTES:
        values[name] = f_num(body, name, 3, required=False, default=None, ge=D(0))

    if lot["status"] != "PRODUCED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if sampled_at < lot["production_end_at"]:
        raise_error("ERR_SAMPLE_BEFORE_PRODUCTION_END")

    verdict, failing, margin = derive.purity_verdict(values)

    row = base_row(with_common=False)
    row.update({
        "production_lot_id": lot["id"],
        "performed_by_user_id": user_id,
        "sampled_at": sampled_at,
        "verdict": verdict,
        "failing_analytes": failing,
        "purity_margin_pct": margin,
        "_raw": {"sampled_at": raw_sampled},
    })
    for name in ANALYTE_ORDER:
        row[name] = values[name]
    db.purity_tests[row["id"]] = row

    # The lot's quality verdict always follows the latest test (sampled_at, then
    # created_at), which is not necessarily the row just inserted.
    latest = derive.latest_purity_test(lot["id"])
    if latest["verdict"] == "PASS":
        lot["qa_status"] = "PASSED"
    elif latest["verdict"] == "FAIL":
        lot["qa_status"] = "FAILED"
        lot["status"] = "REJECTED"
    else:
        lot["qa_status"] = "PENDING"
    touch(lot)
    return created(ser.purity_test(row))


# =========================================================================
# Carbon-intensity certification and release
# =========================================================================
@bp.post("/production-lots/<lot_id>/certify-ci")
def certify_ci(lot_id):
    actor("ComplianceAdmin")
    lot = get_lot(lot_id)
    if lot["status"] != "PRODUCED" or lot["ci_status"] != "PENDING":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if lot["selected_power_contract_id"] is None:
        raise_error("ERR_NO_POWER_CONTRACT")

    if lot["carryover_kg"] > 0 and lot["predecessor_lot_id"]:
        predecessor = db.production_lots[lot["predecessor_lot_id"]]
        if predecessor["ci_certified_gco2e_per_mj"] is None:
            raise_error("ERR_LOT_CI_NOT_CERTIFIED")

    contract = db.power_contracts[lot["selected_power_contract_id"]]
    asset = db.production_assets[lot["production_asset_id"]]
    variant = "HOURLY_MATCHED" if contract["hourly_matching_enabled"] else "ANNUAL_AVERAGE"
    lot["ci_variant_applied"] = variant
    lot["ci_certified_gco2e_per_mj"] = derive.carbon_intensity(
        lot, contract, asset, variant, certified=True)
    lot["ci_status"] = "CERTIFIED"
    touch(lot)
    return ok(ser.production_lot(lot))


@bp.post("/production-lots/<lot_id>/release")
def release_lot(lot_id):
    user_id, _role = actor("QualityAnalyst", "ComplianceAdmin")
    lot = get_lot(lot_id)
    if lot["status"] != "PRODUCED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if lot["qa_status"] != "PASSED" or lot["ci_status"] != "CERTIFIED":
        raise_error("ERR_QA_NOT_PASSED")
    for test in derive.tests_of_lot(lot["id"]):
        if test["performed_by_user_id"] == user_id:
            raise_error("ERR_SEGREGATION_OF_DUTIES")

    lot["status"] = "RELEASED"
    lot["released_by_user_id"] = user_id
    touch(lot)
    return ok(ser.production_lot(lot))
