"""Carcass lot + cut record + pathogen sample endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_string, req_enum, req_number, req_int
from errors import (raise_error, ERR_NOT_FOUND, ERR_DAY_NOT_OPEN, ERR_LOT_INVALID_STATE,
                    ERR_INVALID_REQUEST, ERR_MASS_BALANCE_VIOLATION,
                    ERR_POSITIVE_PATHOGEN_UNRESOLVED, ERR_SAMPLE_ALREADY_REPORTED)
from serializers import lot_out, cut_record_out, sample_out
from services import touch, recompute_day_posture, recompute_day_totals, round2, cascade_positive_sample

bp = Blueprint("lots", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")
SPECIES = {"BOVINE", "SWINE", "OVINE", "POULTRY"}
PRIMAL_TYPES = {"CHUCK", "RIB", "LOIN", "ROUND", "BRISKET", "BELLY", "HAM", "OTHER"}
ORGANISMS = {"ECOLI_O157H7", "SALMONELLA", "LISTERIA_MONOCYTOGENES", "GENERIC_ECOLI"}
SAMPLE_TYPES = {"CARCASS_SWAB", "GROUND_PRODUCT", "ENVIRONMENTAL"}
SAMPLE_ALLOWED_STATES = {"HARVESTED", "CHILLED", "FABRICATING", "FABRICATED", "HELD"}

GRADE_A_MIN = 72.0
GRADE_B_MIN = 68.0
MASS_BALANCE_TOLERANCE = 0.5


def _get_lot(lot_id):
    lot = store.carcass_lots.get(lot_id)
    if not lot:
        raise_error(ERR_NOT_FOUND, "Carcass lot not found")
    return lot


def _require_day_open(lot):
    day = store.production_days[lot["production_day_id"]]
    if day["status"] != "OPEN":
        raise_error(ERR_DAY_NOT_OPEN, "Owning production day is not OPEN")
    return day


# ---------------------------------------------------------------------------
# Carcass lots
# ---------------------------------------------------------------------------

@bp.route("/production-days/<did>/lots", methods=["POST"])
def receive_lot(did):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    species = req_enum(body, "species", SPECIES)
    supplier_name = req_string(body, "supplier_name")
    head_count = req_int(body, "head_count", gt=0)
    live_weight_lbs = req_number(body, "live_weight_lbs", gt=0)

    day = store.production_days.get(did)
    if not day:
        raise_error(ERR_NOT_FOUND, "Production day not found")
    if day["status"] != "OPEN":
        raise_error(ERR_DAY_NOT_OPEN, "Production day is not OPEN")

    now = store.now_iso()
    lot = {
        "id": new_id(),
        "production_day_id": did,
        "species": species,
        "supplier_name": supplier_name,
        "head_count": head_count,
        "live_weight_lbs": live_weight_lbs,
        "hot_carcass_weight_lbs": None,
        "cold_carcass_weight_lbs": None,
        "drip_loss_pct": None,
        "total_cut_weight_lbs": 0,
        "trim_waste_lbs": None,
        "fabrication_yield_pct": None,
        "packer_yield_pct": None,
        "yield_grade": None,
        "status": "RECEIVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.carcass_lots[lot["id"]] = lot
    return success_object(lot_out(lot), 201)


@bp.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    require_roles(*READ_ROLES)
    return success_object(lot_out(_get_lot(lid)))


@bp.route("/lots", methods=["GET"])
def list_lots():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    day_id = request.args.get("production_day_id")
    status = request.args.get("status")
    species = request.args.get("species")
    items = sorted(store.carcass_lots.values(), key=lambda l: (l["created_at"], l["id"]))
    if day_id is not None:
        items = [l for l in items if l["production_day_id"] == day_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if species is not None:
        items = [l for l in items if l["species"] == species]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([lot_out(l) for l in page], limit, offset, total)


@bp.route("/lots/<lid>/pass-ante-mortem", methods=["POST"])
def pass_ante_mortem(lid):
    user_id, _ = require_roles("Inspector")
    get_body()
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] != "RECEIVED":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be RECEIVED for ante-mortem")
    lot["status"] = "CLEARED"
    touch(lot)
    return success_object(lot_out(lot))


@bp.route("/lots/<lid>/harvest", methods=["POST"])
def harvest(lid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    hot = req_number(body, "hot_carcass_weight_lbs", gt=0)
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] != "CLEARED":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be CLEARED for harvest")
    lot["hot_carcass_weight_lbs"] = hot
    lot["status"] = "HARVESTED"
    touch(lot)
    return success_object(lot_out(lot))


@bp.route("/lots/<lid>/chill-complete", methods=["POST"])
def chill_complete(lid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    cold = req_number(body, "cold_carcass_weight_lbs", gt=0)
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] != "HARVESTED":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be HARVESTED for chill-complete")
    if cold > lot["hot_carcass_weight_lbs"]:
        raise_error(ERR_INVALID_REQUEST, "cold_carcass_weight_lbs must be <= hot_carcass_weight_lbs")
    lot["cold_carcass_weight_lbs"] = cold
    hot = lot["hot_carcass_weight_lbs"]
    lot["drip_loss_pct"] = round2(100.0 * (hot - cold) / hot)
    lot["status"] = "CHILLED"
    touch(lot)
    return success_object(lot_out(lot))


@bp.route("/lots/<lid>/fabricate", methods=["POST"])
def fabricate(lid):
    user_id, _ = require_roles("ProductionManager")
    get_body()
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] not in ("CHILLED", "RELEASED"):
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be CHILLED or RELEASED to fabricate")
    lot["status"] = "FABRICATING"
    touch(lot)
    return success_object(lot_out(lot))


@bp.route("/lots/<lid>/complete-fabrication", methods=["POST"])
def complete_fabrication(lid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    trim_waste_lbs = req_number(body, "trim_waste_lbs", ge=0)
    lot = _get_lot(lid)
    day = _require_day_open(lot)
    if lot["status"] != "FABRICATING":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be FABRICATING to complete fabrication")
    # Mass balance
    cuts = [c for c in store.cut_records.values() if c["lot_id"] == lid]
    if not cuts:
        raise_error(ERR_MASS_BALANCE_VIOLATION, "At least one cut record is required")
    diff = abs(lot["total_cut_weight_lbs"] + trim_waste_lbs - lot["cold_carcass_weight_lbs"])
    if diff > MASS_BALANCE_TOLERANCE:
        raise_error(ERR_MASS_BALANCE_VIOLATION, "Cut + trim weights deviate from cold weight by more than 0.5 lbs")

    lot["trim_waste_lbs"] = trim_waste_lbs
    # PRD §3.5: yields are computed from the *unrounded* sum of stored cut
    # weights, each rounded half-up to two decimals exactly once at the end.
    total_cut_dec = sum((Decimal(str(c["weight_lbs"])) for c in cuts), Decimal("0"))
    total_cut = float(total_cut_dec)
    lot["total_cut_weight_lbs"] = total_cut
    cold = lot["cold_carcass_weight_lbs"]
    hot = lot["hot_carcass_weight_lbs"]
    fab_yield = round2(Decimal("100") * total_cut_dec / Decimal(str(cold)))
    pack_yield = round2(Decimal("100") * total_cut_dec / Decimal(str(hot)))
    lot["fabrication_yield_pct"] = fab_yield
    lot["packer_yield_pct"] = pack_yield
    if fab_yield >= GRADE_A_MIN:
        lot["yield_grade"] = "A"
    elif fab_yield >= GRADE_B_MIN:
        lot["yield_grade"] = "B"
    else:
        lot["yield_grade"] = "C"
    lot["status"] = "FABRICATED"
    touch(lot)
    # Ledger sync
    recompute_day_totals(day["id"])
    return success_object(lot_out(lot))


@bp.route("/lots/<lid>/release-hold", methods=["POST"])
def release_hold(lid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    disposition_note = req_string(body, "disposition_note")
    lot = _get_lot(lid)
    if lot["status"] != "HELD":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be HELD to release")
    # Require a NEGATIVE sample created later than the latest POSITIVE sample.
    # Ordering is (created_at, insertion sequence) so samples recorded within the same
    # logical-clock tick still have a well-defined later/earlier relationship.
    samples = [s for s in store.pathogen_samples.values() if s["lot_id"] == lid]
    samples.sort(key=lambda s: (s["created_at"], s.get("_seq", 0)))
    latest_positive_key = None
    for s in samples:
        if s["result"] == "POSITIVE":
            key = (s["created_at"], s.get("_seq", 0))
            if latest_positive_key is None or key > latest_positive_key:
                latest_positive_key = key
    confirmed = False
    if latest_positive_key is not None:
        for s in samples:
            if s["result"] == "NEGATIVE" and (s["created_at"], s.get("_seq", 0)) > latest_positive_key:
                confirmed = True
                break
    if not confirmed:
        raise_error(ERR_POSITIVE_PATHOGEN_UNRESOLVED,
                    "No NEGATIVE confirmation sample newer than the latest POSITIVE exists")
    lot["status"] = "RELEASED"
    touch(lot)
    recompute_day_posture(lot["production_day_id"])
    return success_object(lot_out(lot))


# ---------------------------------------------------------------------------
# Cut records
# ---------------------------------------------------------------------------

@bp.route("/lots/<lid>/cut-records", methods=["POST"])
def create_cut_record(lid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    primal_type = req_enum(body, "primal_type", PRIMAL_TYPES)
    weight_lbs = req_number(body, "weight_lbs", gt=0)
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] != "FABRICATING":
        raise_error(ERR_LOT_INVALID_STATE, "Lot must be FABRICATING to record cuts")

    pct = round2(100.0 * weight_lbs / lot["cold_carcass_weight_lbs"])
    now = store.now_iso()
    cr = {
        "id": new_id(),
        "lot_id": lid,
        "primal_type": primal_type,
        "weight_lbs": weight_lbs,
        "pct_of_cold_weight": pct,
        "created_at": now,
    }
    store.cut_records[cr["id"]] = cr
    # PRD §3.5: the line's weight accumulates unrounded; only pct_of_cold_weight
    # is rounded at line creation. Decimal(str(...)) avoids float dust.
    lot["total_cut_weight_lbs"] = float(
        Decimal(str(lot["total_cut_weight_lbs"])) + Decimal(str(weight_lbs))
    )
    touch(lot)
    return success_object(cut_record_out(cr), 201)


@bp.route("/cut-records/<cid>", methods=["GET"])
def get_cut_record(cid):
    require_roles(*READ_ROLES)
    cr = store.cut_records.get(cid)
    if not cr:
        raise_error(ERR_NOT_FOUND, "Cut record not found")
    return success_object(cut_record_out(cr))


@bp.route("/cut-records", methods=["GET"])
def list_cut_records():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    lot_id = request.args.get("lot_id")
    primal_type = request.args.get("primal_type")
    items = sorted(store.cut_records.values(), key=lambda c: (c["created_at"], c["id"]))
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if primal_type is not None:
        items = [c for c in items if c["primal_type"] == primal_type]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([cut_record_out(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Pathogen samples
# ---------------------------------------------------------------------------

@bp.route("/lots/<lid>/pathogen-samples", methods=["POST"])
def collect_sample(lid):
    user_id, _ = require_roles("QATech")
    body = get_body()
    organism = req_enum(body, "organism", ORGANISMS)
    sample_type = req_enum(body, "sample_type", SAMPLE_TYPES)
    lot = _get_lot(lid)
    _require_day_open(lot)
    if lot["status"] not in SAMPLE_ALLOWED_STATES:
        raise_error(ERR_LOT_INVALID_STATE, "Lot state does not permit sampling")

    # is_confirmation: true when an earlier-created POSITIVE sample exists for this lot
    has_prior_positive = any(
        s["lot_id"] == lid and s["result"] == "POSITIVE"
        for s in store.pathogen_samples.values()
    )
    now = store.now_iso()
    sample = {
        "id": new_id(),
        "lot_id": lid,
        "organism": organism,
        "sample_type": sample_type,
        "collected_by": user_id,
        "result": "PENDING",
        "is_confirmation": has_prior_positive,
        "reported_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.pathogen_samples[sample["id"]] = sample
    return success_object(sample_out(sample), 201)


@bp.route("/pathogen-samples/<sid>", methods=["GET"])
def get_sample(sid):
    require_roles(*READ_ROLES)
    s = store.pathogen_samples.get(sid)
    if not s:
        raise_error(ERR_NOT_FOUND, "Pathogen sample not found")
    return success_object(sample_out(s))


@bp.route("/pathogen-samples", methods=["GET"])
def list_samples():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    lot_id = request.args.get("lot_id")
    result = request.args.get("result")
    organism = request.args.get("organism")
    items = sorted(store.pathogen_samples.values(), key=lambda s: (s["created_at"], s["id"]))
    if lot_id is not None:
        items = [s for s in items if s["lot_id"] == lot_id]
    if result is not None:
        items = [s for s in items if s["result"] == result]
    if organism is not None:
        items = [s for s in items if s["organism"] == organism]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([sample_out(s) for s in page], limit, offset, total)


@bp.route("/pathogen-samples/<sid>/report-result", methods=["POST"])
def report_result(sid):
    user_id, _ = require_roles("LabAnalyst")
    body = get_body()
    result = req_enum(body, "result", {"NEGATIVE", "POSITIVE"})
    sample = store.pathogen_samples.get(sid)
    if not sample:
        raise_error(ERR_NOT_FOUND, "Pathogen sample not found")
    if sample["result"] != "PENDING":
        raise_error(ERR_SAMPLE_ALREADY_REPORTED, "Sample result already reported")
    sample["result"] = result
    sample["reported_at"] = store.now_iso()
    touch(sample)

    if result == "POSITIVE":
        lot = store.carcass_lots[sample["lot_id"]]
        # Cascade link 1: lot -> HELD (or CONDEMNED when already HELD / confirmation)
        if lot["status"] == "HELD":
            lot["status"] = "CONDEMNED"
            touch(lot)
            cascade_positive_sample(lot)
        elif lot["status"] in ("HARVESTED", "CHILLED", "FABRICATING", "FABRICATED"):
            lot["status"] = "HELD"
            touch(lot)
            cascade_positive_sample(lot)
    return success_object(sample_out(sample))
