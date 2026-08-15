"""PaddyLot endpoints: intake, grade, regrade, reject, store (PRD §3.3, §3.4)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_GROWER_NOT_FOUND, ERR_CONTRACT_NOT_FOUND,
    ERR_BIN_NOT_FOUND, ERR_SEASON_INTAKE_NOT_OPEN, ERR_CONTRACT_NOT_OPEN,
    ERR_STALE_CONTRACT_VERSION, ERR_OUTSIDE_INTAKE_WINDOW, ERR_SPOT_CAP_REACHED,
    ERR_INVALID_LOT_STATE, ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
    ERR_OVERDELIVERY_BEYOND_TOLERANCE, ERR_LOT_ALREADY_IN_DRYING_RUN,
    ERR_BIN_NOT_RECEIVE_READY, ERR_BIN_VARIETY_MISMATCH, ERR_BIN_CAPACITY_EXCEEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import D, q2, new_id, next_seq, parse_date
from validate import get_body, req_str, req_enum, req_int, req_num, req_date, opt_int

bp = Blueprint("lots", __name__)


@bp.route("/mill/lots", methods=["POST"])
def create_lot():
    authorized(["ScaleOperator"])
    body = get_body()
    # --- priority 4: request shape ---
    season_id = req_str(body, "season_id")
    grower_id = req_str(body, "grower_id")
    variety = req_enum(body, "variety", core.VARIETIES)
    source = req_enum(body, "source", ("CONTRACT", "SPOT"))
    gross = req_int(body, "gross_weight_lbs", positive=True)
    tare = req_int(body, "tare_weight_lbs", non_negative=True)
    scheduled_date = req_date(body, "scheduled_date")
    moisture_handheld = req_num(body, "moisture_pct_handheld")
    if tare >= gross:
        raise_error(ERR_INVALID_REQUEST, "tare_weight_lbs must be less than gross_weight_lbs")
    contract_id = None
    expected_version = None
    spot_price = None
    if source == "CONTRACT":
        contract_id = body.get("contract_id")
        if contract_id is None or not isinstance(contract_id, str) or not contract_id.strip():
            raise_error(ERR_INVALID_REQUEST, "contract_id is required for CONTRACT lots")
        expected_version = body.get("expected_contract_version")
        if expected_version is None or isinstance(expected_version, bool) \
                or not isinstance(expected_version, int):
            raise_error(ERR_INVALID_REQUEST,
                        "expected_contract_version is required for CONTRACT lots")
    else:
        spot_price = body.get("spot_price_cents_per_cwt")
        if spot_price is None or isinstance(spot_price, bool) or not isinstance(spot_price, int):
            raise_error(ERR_INVALID_REQUEST,
                        "spot_price_cents_per_cwt is required for SPOT lots")

    # --- priority 5: existence, left to right; FKs must belong to the season ---
    season = require_resource("seasons", season_id)
    grower = db["growers"].get(grower_id)
    if grower is None or grower["season_id"] != season_id:
        raise_error(ERR_GROWER_NOT_FOUND, "grower not found in this season")
    contract = None
    if source == "CONTRACT":
        contract = db["contracts"].get(contract_id)
        if contract is None or contract["season_id"] != season_id:
            raise_error(ERR_CONTRACT_NOT_FOUND, "contract not found in this season")
        if contract["grower_id"] != grower_id or contract["variety"] != variety:
            raise_error(ERR_INVALID_REQUEST,
                        "lot grower/variety must match the contract")

    # --- priority 6: state ---
    if season["status"] != "INTAKE_OPEN":
        raise_error(ERR_SEASON_INTAKE_NOT_OPEN,
                    "lot intake requires the season to be INTAKE_OPEN")
    if contract is not None and contract["status"] not in ("OPEN", "PARTIALLY_FULFILLED"):
        raise_error(ERR_CONTRACT_NOT_OPEN,
                    f"contract status {contract['status']} does not accept deliveries")

    # --- priority 7: optimistic concurrency on the contract ---
    if contract is not None and int(contract["version"]) != expected_version:
        raise_error(ERR_STALE_CONTRACT_VERSION,
                    "expected_contract_version does not match the contract's current version")

    # --- priority 9: temporal (intake window, inclusive) ---
    sd = parse_date(scheduled_date)
    if sd < parse_date(season["intake_start_date"]) or sd > parse_date(season["intake_end_date"]):
        raise_error(ERR_OUTSIDE_INTAKE_WINDOW,
                    "scheduled_date lies outside the season intake window")

    # --- priority 11: spot daily cap ---
    if source == "SPOT":
        count = 0
        for lot in db["lots"].values():
            if (lot["season_id"] == season_id and lot["source"] == "SPOT"
                    and lot["scheduled_date"] == scheduled_date and lot["status"] != "REJECTED"):
                count += 1
        if count >= int(season["spot_daily_cap"]):
            raise_error(ERR_SPOT_CAP_REACHED,
                        "the spot daily cap for this scheduled_date is reached")

    # --- commit ---
    net_wet = core.compute_net_wet_cwt(gross, tare)
    prov_dry, _, _ = core.compute_shrink(net_wet, moisture_handheld)
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "grower_id": grower_id,
        "contract_id": contract_id if source == "CONTRACT" else None,
        "bin_id": None,
        "drying_run_id": None,
        "settlement_id": None,
        "variety": variety,
        "source": source,
        "spot_price_cents_per_cwt": spot_price if source == "SPOT" else None,
        "scheduled_date": scheduled_date,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_wet_cwt": net_wet,
        "moisture_pct_handheld": _num_out(moisture_handheld),
        "moisture_pct_official": None,
        "provisional_dry_weight_cwt": prov_dry,
        "dry_weight_cwt": None,
        "moisture_shrink_cwt": None,
        "handling_loss_cwt": None,
        "foreign_matter_pct": None,
        "damage_pct": None,
        "broken_pct": None,
        "grade_score": None,
        "grade": None,
        "drying_charge_cents": None,
        "price_cents_per_cwt": None,
        "line_value_cents": None,
        "graded_date": None,
        "reject_reason": None,
        "status": "WEIGHED",
    }
    core.touch_new(rec)
    db["lots"][rec["id"]] = rec
    if contract is not None:
        contract["delivery_count"] = int(contract["delivery_count"]) + 1
        core.bump(contract)
    return success_object(public(rec), 201)


def _num_out(dec):
    """Serialize a validated numeric input back as a JSON number."""
    return float(dec)


@bp.route("/mill/lots", methods=["GET"])
def list_lots():
    return list_endpoint("lots", [
        "season_id", "grower_id", "contract_id", "bin_id", "drying_run_id",
        "settlement_id", "variety", "source", "status", "scheduled_date",
    ])


@bp.route("/mill/lots/<rid>", methods=["GET"])
def get_lot(rid):
    return get_endpoint("lots", rid)


def _grade_inputs(body):
    moisture = req_num(body, "moisture_pct_official")
    fm = req_num(body, "foreign_matter_pct")
    dmg = req_num(body, "damage_pct")
    brk = req_num(body, "broken_pct")
    return moisture, fm, dmg, brk


def _apply_grading(lot, season, moisture, fm, dmg, brk):
    """Compute and store all grading-derived fields on the lot."""
    net_wet = D(lot["net_wet_cwt"])
    dry, ms_cwt, hl_cwt = core.compute_shrink(net_wet, moisture)
    score, grade = core.grade_score_and_grade(fm, dmg, brk)
    charge = core.drying_charge_cents(net_wet, moisture)
    if lot["source"] == "CONTRACT":
        contract = db["contracts"].get(lot["contract_id"])
        price = int(contract["base_price_cents_per_cwt"]) + \
            int(contract["grade_adjustments"].get(grade, 0))
    else:
        price = int(lot["spot_price_cents_per_cwt"])
    lot["moisture_pct_official"] = _num_out(moisture)
    lot["foreign_matter_pct"] = _num_out(fm)
    lot["damage_pct"] = _num_out(dmg)
    lot["broken_pct"] = _num_out(brk)
    lot["dry_weight_cwt"] = dry
    lot["moisture_shrink_cwt"] = ms_cwt
    lot["handling_loss_cwt"] = hl_cwt
    lot["grade_score"] = score
    lot["grade"] = grade
    lot["drying_charge_cents"] = charge
    lot["price_cents_per_cwt"] = price
    lot["line_value_cents"] = core.line_value_cents(dry, price)
    lot["graded_date"] = core.season_clock_date_str(season)
    return dry


@bp.route("/mill/lots/<rid>/grade", methods=["POST"])
def grade_lot(rid):
    authorized(["QualityLabTech"])
    body = get_body()
    moisture, fm, dmg, brk = _grade_inputs(body)
    lot = require_resource("lots", rid)
    if lot["status"] != "WEIGHED":
        raise_error(ERR_INVALID_LOT_STATE,
                    f"grade requires WEIGHED; lot is {lot['status']}")
    if core.active_hold_on(lot["season_id"], "LOT", lot["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the lot blocks grading")
    season = db["seasons"][lot["season_id"]]
    dry, _, _ = core.compute_shrink(D(lot["net_wet_cwt"]), moisture)
    # Over-delivery guard (contract lots only), evaluated before any mutation.
    if lot["source"] == "CONTRACT":
        contract = db["contracts"][lot["contract_id"]]
        fulfilled_before = D(contract["fulfilled_cwt"])
        tolerance = q2(D(contract["contracted_cwt"]) * core.OVERDELIVERY_TOLERANCE)
        if fulfilled_before + dry > tolerance:
            raise_error(ERR_OVERDELIVERY_BEYOND_TOLERANCE,
                        "grading would push the contract beyond 105% of contracted volume")
    _apply_grading(lot, season, moisture, fm, dmg, brk)
    lot["status"] = "GRADED"
    core.bump(lot)
    if lot["source"] == "CONTRACT":
        contract = db["contracts"][lot["contract_id"]]
        core.recompute_contract_fulfillment(contract, force_bump=True)
    return success_object(public(lot))


@bp.route("/mill/lots/<rid>/regrade", methods=["POST"])
def regrade_lot(rid):
    authorized(["QualityLabTech"])
    body = get_body()
    moisture, fm, dmg, brk = _grade_inputs(body)
    lot = require_resource("lots", rid)
    if lot["status"] not in ("GRADED", "BINNED"):
        raise_error(ERR_INVALID_LOT_STATE,
                    f"regrade requires GRADED or BINNED; lot is {lot['status']}")
    if core.active_hold_on(lot["season_id"], "LOT", lot["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the lot blocks regrading")
    season = db["seasons"][lot["season_id"]]
    old_dry = D(lot["dry_weight_cwt"])
    new_dry, _, _ = core.compute_shrink(D(lot["net_wet_cwt"]), moisture)
    binned_bin = None
    if lot["status"] == "BINNED":
        binned_bin = db["bins"].get(lot["bin_id"])
        delta = new_dry - old_dry
        if delta > 0 and binned_bin is not None and D(binned_bin["available_cwt"]) < delta:
            raise_error(ERR_BIN_CAPACITY_EXCEEDED,
                        "bin cannot absorb the regraded weight increase")
    _apply_grading(lot, season, moisture, fm, dmg, brk)
    core.bump(lot)
    if binned_bin is not None:
        binned_bin["stock_cwt"] = q2(D(binned_bin["stock_cwt"]) + (D(lot["dry_weight_cwt"]) - old_dry))
        core.refresh_bin(binned_bin)
        core.bump(binned_bin)
    if lot["source"] == "CONTRACT" and lot.get("contract_id"):
        contract = db["contracts"].get(lot["contract_id"])
        if contract is not None:
            core.recompute_contract_fulfillment(contract)
    # Settlement cascade (PRD §3.4).
    settlement = db["settlements"].get(lot.get("settlement_id") or "")
    if settlement is not None:
        if settlement["status"] == "DRAFT":
            core.compute_provisional(settlement)
            core.bump(settlement)
        elif settlement["status"] == "PROVISIONAL_ISSUED":
            settlement["status"] = "DISPUTED"
            settlement["dispute_reason"] = "LOT_REGRADED"
            core.bump(settlement)
            core.season_revert_on_dispute(settlement["season_id"])
    return success_object(public(lot))


@bp.route("/mill/lots/<rid>/reject", methods=["POST"])
def reject_lot(rid):
    authorized(["QualityLabTech"])
    body = get_body()
    reason = req_str(body, "reject_reason")
    lot = require_resource("lots", rid)
    if lot["status"] not in ("WEIGHED", "GRADED"):
        raise_error(ERR_INVALID_LOT_STATE,
                    f"reject requires WEIGHED or GRADED; lot is {lot['status']}")
    was_graded = lot["status"] == "GRADED"
    lot["status"] = "REJECTED"
    lot["reject_reason"] = reason
    core.bump(lot)
    if was_graded and lot["source"] == "CONTRACT" and lot.get("contract_id"):
        contract = db["contracts"].get(lot["contract_id"])
        if contract is not None:
            core.recompute_contract_fulfillment(contract, force_bump=True)
    return success_object(public(lot))


@bp.route("/mill/lots/<rid>/store", methods=["POST"])
def store_lot(rid):
    authorized(["ScaleOperator"])
    body = get_body()
    bin_id = req_str(body, "bin_id")
    lot = require_resource("lots", rid)
    b = db["bins"].get(bin_id)
    if b is None or b["season_id"] != lot["season_id"]:
        raise_error(ERR_BIN_NOT_FOUND, "bin not found in the lot's season")
    if lot["status"] != "GRADED":
        raise_error(ERR_INVALID_LOT_STATE,
                    f"store requires GRADED; lot is {lot['status']}")
    if lot.get("drying_run_id") is not None:
        raise_error(ERR_LOT_ALREADY_IN_DRYING_RUN,
                    "lot is held by a non-terminal drying run")
    if b["status"] != "AVAILABLE":
        raise_error(ERR_BIN_NOT_RECEIVE_READY,
                    f"bin status {b['status']} cannot receive grain")
    if core.active_hold_on(lot["season_id"], "LOT", lot["id"]) or \
            core.active_hold_on(lot["season_id"], "BIN", b["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the lot or the bin blocks storage")
    if b["variety_lock"] is not None and b["variety_lock"] != lot["variety"]:
        raise_error(ERR_BIN_VARIETY_MISMATCH,
                    "bin variety_lock differs from the lot variety")
    if D(b["available_cwt"]) < D(lot["dry_weight_cwt"]):
        raise_error(ERR_BIN_CAPACITY_EXCEEDED,
                    "lot dry weight exceeds bin available capacity")
    b["stock_cwt"] = q2(D(b["stock_cwt"]) + D(lot["dry_weight_cwt"]))
    if b["variety_lock"] is None:
        b["variety_lock"] = lot["variety"]
    core.refresh_bin(b)
    core.bump(b)
    lot["bin_id"] = b["id"]
    lot["status"] = "BINNED"
    core.bump(lot)
    return success_object(public(lot))
