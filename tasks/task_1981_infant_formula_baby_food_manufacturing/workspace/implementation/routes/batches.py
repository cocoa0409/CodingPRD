"""ProductionBatch endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INVALID_RANGE, ERR_STALE_VERSION,
                    ERR_SEGREGATION_OF_DUTIES, ERR_VALIDATION_REQUIRED,
                    ERR_FORMULA_NOT_ACTIVE, ERR_LOT_NOT_QC_PASSED,
                    ERR_SUPPLIER_NOT_QUALIFIED, ERR_LOT_EXPIRED,
                    ERR_INSUFFICIENT_INGREDIENT_QUANTITY,
                    ERR_INCOMPLETE_TEST_RESULTS, ERR_BATCH_TESTS_FAILED)
from middleware import authorized
from response import ok, paginate
from services import (ser_batch, get_or_404, stamp_new, touch,
                      evaluate_nutrient_results, batch_shelf_life_months)
from routes.formulas import _start_production_validation_satisfied
from util import get_body, require_fields, parse_datetime, to_decimal, add_months

bp = Blueprint("batches", __name__)

BATCH_READ = ("QA_MANAGER", "QUALITY_ANALYST", "PRODUCTION_SUPERVISOR", "SUPPLY_CHAIN_PLANNER")


@bp.post("/production-batches")
@authorized("PRODUCTION_SUPERVISOR")
def create_batch(_user_id=None, _role=None):
    body = get_body()
    formula = None
    if body.get("formula_id") is not None:
        formula = get_or_404(store.formulas, body["formula_id"], "Formula")
    # business: formula must be ACTIVE
    if formula is not None and formula["status"] != "ACTIVE":
        raise err(ERR_FORMULA_NOT_ACTIVE,
                  "Formula status is not ACTIVE; production batches cannot be created")
    # field shape
    require_fields(body, ["formula_id", "batch_size_kg", "production_date",
                          "expected_formula_version"])
    size = to_decimal(body["batch_size_kg"], "batch_size_kg")
    if size <= 0:
        raise err(ERR_INVALID_RANGE, "batch_size_kg must be greater than 0")
    size = size.quantize(Decimal("0.001"))
    production_date = parse_datetime(body["production_date"], "production_date")
    # OCC: applied immediately before write commit
    expected = body["expected_formula_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_formula_version must be an integer")
    if expected != formula["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_formula_version %s does not match current formula version %s"
                  % (expected, formula["version"]))
    rec = stamp_new({
        "id": new_id(),
        "formula_id": formula["id"],
        "batch_number": store.next_ref("B"),
        "batch_size_kg": size,
        "actual_yield_kg": None,
        "status": "PLANNED",
        "production_date": production_date,
        "expiry_date": None,
        "ingredient_consumptions": [],
        "nutrient_results": None,
        "pathogen_results": None,
        "release_decision": None,
        "_test_submitted_by": None,
        "_recall_review_flagged": False,
    })
    store.batches[rec["id"]] = rec
    # side effect: parent formula version bump
    touch(formula)
    return ok(ser_batch(rec), 201)


@bp.get("/production-batches")
@authorized(*BATCH_READ)
def list_batches(_user_id=None, _role=None):
    records = list(store.batches.values())
    for param, field in (("formula_id", "formula_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [b for b in records if b[field] == v]
    return paginate(records, ser_batch)


@bp.get("/production-batches/<bid>")
@authorized(*BATCH_READ)
def get_batch(bid, _user_id=None, _role=None):
    return ok(ser_batch(get_or_404(store.batches, bid, "ProductionBatch")))


@bp.get("/formulas/<fid>/batches")
@authorized(*BATCH_READ)
def list_formula_batches(fid, _user_id=None, _role=None):
    get_or_404(store.formulas, fid, "Formula")
    records = [b for b in store.batches.values() if b["formula_id"] == fid]
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    return paginate(records, ser_batch)


def _fifo_check_and_consume(batch, formula, commit=False):
    """Validate ingredient availability per priority order, then (when commit)
    consume lots FIFO. Returns the consumption list."""
    ts = now()
    consumptions = []
    order = 0
    diagnoses = []  # (priority_rank, error) gathered across short ingredients

    for entry in formula["ingredients"]:
        required = batch["batch_size_kg"] * Decimal(str(entry["percentage_by_weight"])) / Decimal(100)
        lots = [l for l in store.lots.values()
                if l["ingredient_id"] == entry["ingredient_id"] and l["remaining_kg"] > 0]
        eligible = [l for l in lots
                    if l["qc_status"] == "QC_PASSED" and l["expiry_date"] > ts]
        eligible_sum = sum(l["remaining_kg"] for l in eligible)
        if eligible_sum < required:
            # Diagnose the binding constraint: a blocker error fires when the
            # lots it blocks, if usable, would let the recipe meet demand.
            # PRD §3.4 priority: qc_status == QC_PASSED is checked first (any
            # non-QC_PASSED lot — PENDING_QC, QC_FAILED, or QUARANTINED — is a
            # lot-QC violation); the supplier-qualification check applies to
            # lots that passed the QC gate.
            not_qc = [l for l in lots if l["qc_status"] != "QC_PASSED"]
            not_qualified = [
                l for l in lots
                if l["qc_status"] == "QC_PASSED"
                and (store.suppliers.get(l["supplier_id"]) is None
                     or store.suppliers[l["supplier_id"]]["qualification_status"] != "QUALIFIED")]
            expired = [l for l in lots
                       if l["qc_status"] == "QC_PASSED" and l["expiry_date"] <= ts
                       and l not in not_qualified]
            if not_qc and eligible_sum + sum(l["remaining_kg"] for l in not_qc) >= required:
                diagnoses.append((8, err(ERR_LOT_NOT_QC_PASSED,
                                         "Required ingredient lot has not passed QC")))
            elif not_qualified and \
                    eligible_sum + sum(l["remaining_kg"] for l in not_qualified) >= required:
                diagnoses.append((9, err(ERR_SUPPLIER_NOT_QUALIFIED,
                                         "Supplier of a required lot is not QUALIFIED")))
            elif expired and \
                    eligible_sum + sum(l["remaining_kg"] for l in expired) >= required:
                diagnoses.append((11, err(ERR_LOT_EXPIRED,
                                          "Required ingredient lot is expired")))
            else:
                diagnoses.append((16, err(ERR_INSUFFICIENT_INGREDIENT_QUANTITY,
                                          "Eligible lots are insufficient for batch requirements")))
            continue
        # consume FIFO: expiry ASC, created_at ASC
        eligible.sort(key=lambda l: (l["expiry_date"], l["created_at"], l.get("_seq", 0)))
        consumed = Decimal("0")
        for lot in eligible:
            take = min(lot["remaining_kg"], required - consumed)
            if take <= 0:
                break
            consumptions.append((lot, take, order))
            consumed += take
            order += 1

    if diagnoses:
        # validation-currency check (priority 10) sits between supplier (9) and expiry (11)
        diagnoses.sort(key=lambda d: d[0])
        first = diagnoses[0]
        if first[0] < 10:
            raise first[1]
        if not _start_production_validation_satisfied(formula):
            raise err(ERR_VALIDATION_REQUIRED,
                      "Required process validation is missing, not PASSED, or expired")
        raise first[1]

    if not _start_production_validation_satisfied(formula):
        raise err(ERR_VALIDATION_REQUIRED,
                  "Required process validation is missing, not PASSED, or expired")

    if commit:
        for lot, take, _o in consumptions:
            lot["remaining_kg"] -= take
            touch(lot)
        return [{"ingredient_lot_id": lot["id"],
                 "consumed_kg": take,
                 "consumption_order": o} for lot, take, o in consumptions]
    return consumptions


@bp.post("/production-batches/<bid>/start-production")
@authorized("PRODUCTION_SUPERVISOR")
def start_production(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot start production" % batch["status"])
    formula = store.formulas.get(batch["formula_id"])
    if formula is None or formula["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Formula is not ACTIVE")
    batch["ingredient_consumptions"] = _fifo_check_and_consume(batch, formula, commit=True)
    batch["status"] = "IN_PRODUCTION"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/complete-blending")
@authorized("PRODUCTION_SUPERVISOR")
def complete_blending(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "IN_PRODUCTION":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot complete blending" % batch["status"])
    formula = store.formulas.get(batch["formula_id"])
    if formula is None or formula["process_type"] not in ("DRY_BLEND", "COMBINATION"):
        raise err(ERR_INVALID_STATE,
                  "complete-blending applies only to DRY_BLEND or COMBINATION formulas")
    batch["status"] = "BLENDING_COMPLETE"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/complete-processing")
@authorized("PRODUCTION_SUPERVISOR")
def complete_processing(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    formula = store.formulas.get(batch["formula_id"])
    allowed = batch["status"] == "BLENDING_COMPLETE" or (
        batch["status"] == "IN_PRODUCTION" and formula is not None
        and formula["process_type"] == "WET_PROCESS")
    if not allowed:
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot complete processing" % batch["status"])
    body = get_body()
    require_fields(body, ["actual_yield_kg"])
    y = to_decimal(body["actual_yield_kg"], "actual_yield_kg")
    if y <= 0:
        raise err(ERR_INVALID_RANGE, "actual_yield_kg must be greater than 0")
    batch["actual_yield_kg"] = y.quantize(Decimal("0.001"))
    batch["status"] = "PROCESSING_COMPLETE"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/submit-for-testing")
@authorized("QUALITY_ANALYST")
def submit_for_testing(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "PROCESSING_COMPLETE":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot be submitted for testing" % batch["status"])
    if batch.get("actual_yield_kg") is None or batch["actual_yield_kg"] <= 0:
        raise err(ERR_INVALID_STATE, "actual_yield_kg must be set and positive")
    batch["status"] = "TESTING"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/submit-test-results")
@authorized("QUALITY_ANALYST")
def submit_test_results(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "TESTING":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot accept test results" % batch["status"])
    body = get_body()
    require_fields(body, ["nutrient_results", "pathogen_results"])
    nutrient_results = body["nutrient_results"]
    pathogen_results = body["pathogen_results"]
    if not isinstance(nutrient_results, list) or not isinstance(pathogen_results, list):
        raise err(ERR_INVALID_REQUEST, "nutrient_results and pathogen_results must be arrays")
    formula = store.formulas.get(batch["formula_id"])
    profile = store.profiles.get(formula["nutrient_profile_id"]) if formula else None
    submitted_codes = set()
    for r in nutrient_results:
        if not isinstance(r, dict) or not r.get("nutrient_code") \
                or "measured_per_100kcal" not in r:
            raise err(ERR_INVALID_REQUEST,
                      "Each nutrient result requires nutrient_code and measured_per_100kcal")
        to_decimal(r["measured_per_100kcal"], "measured_per_100kcal")
        submitted_codes.add(r["nutrient_code"])
    if profile is not None:
        missing = [s.get("nutrient_code") for s in profile["nutrient_specs"]
                   if s.get("nutrient_code") not in submitted_codes]
        if missing:
            raise err(ERR_INCOMPLETE_TEST_RESULTS,
                      "Test results do not cover all nutrients in the NutrientProfile")
    if not pathogen_results:
        raise err(ERR_INCOMPLETE_TEST_RESULTS,
                  "pathogen_results must cover the required pathogen panel")
    for r in pathogen_results:
        if not isinstance(r, dict) or not r.get("pathogen_code") \
                or not isinstance(r.get("detected"), bool):
            raise err(ERR_INVALID_REQUEST,
                      "Each pathogen result requires pathogen_code and detected")
    batch["nutrient_results"] = evaluate_nutrient_results(profile, nutrient_results)
    batch["pathogen_results"] = pathogen_results
    batch["_test_submitted_by"] = _user_id
    batch["status"] = "POSITIVE_RELEASE_HOLD"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/release")
@authorized("QA_MANAGER")
def release_batch(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "POSITIVE_RELEASE_HOLD":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot be released" % batch["status"])
    if batch.get("_test_submitted_by") is not None and batch["_test_submitted_by"] == _user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Releasing manager must differ from the user who submitted test results")
    nutrient_ok = all(r.get("pass") is True for r in (batch.get("nutrient_results") or []))
    pathogen_ok = all(r.get("detected") is False for r in (batch.get("pathogen_results") or []))
    if not (nutrient_ok and pathogen_ok):
        raise err(ERR_BATCH_TESTS_FAILED,
                  "Batch release blocked: failing nutrient test or detected pathogen")
    formula = store.formulas.get(batch["formula_id"])
    profile = store.profiles.get(formula["nutrient_profile_id"]) if formula else None
    months = batch_shelf_life_months(profile["profile_code"] if profile else None,
                                     formula["process_type"] if formula else None)
    batch["expiry_date"] = add_months(batch["production_date"], months)
    batch["release_decision"] = "RELEASED"
    batch["status"] = "RELEASED"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/production-batches/<bid>/reject")
@authorized("QA_MANAGER")
def reject_batch(bid, _user_id=None, _role=None):
    batch = get_or_404(store.batches, bid, "ProductionBatch")
    if batch["status"] != "POSITIVE_RELEASE_HOLD":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot be rejected" % batch["status"])
    nutrient_fail = any(r.get("pass") is False for r in (batch.get("nutrient_results") or []))
    pathogen_fail = any(r.get("detected") is True for r in (batch.get("pathogen_results") or []))
    if not (nutrient_fail or pathogen_fail):
        raise err(ERR_INVALID_STATE,
                  "Batch cannot be rejected: all tests passed")
    body = get_body()
    require_fields(body, ["rejection_reason"])
    # compensation: restore remaining_kg on every consumed lot
    for c in batch.get("ingredient_consumptions", []):
        lot = store.lots.get(c["ingredient_lot_id"])
        if lot is not None:
            lot["remaining_kg"] += c["consumed_kg"]
            touch(lot)
    batch["release_decision"] = "REJECTED"
    batch["status"] = "REJECTED"
    touch(batch)
    return ok(ser_batch(batch))
