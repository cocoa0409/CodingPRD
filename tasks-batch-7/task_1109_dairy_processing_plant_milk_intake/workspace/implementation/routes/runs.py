"""Pasteurizer runs, CIP cycles, product batches (PRD 3.6-3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, base_record, now, touch
from errors import (
    ApiError,
    ERR_BATCHES_UNFINISHED,
    ERR_BATCH_IN_PRODUCTION,
    ERR_CIP_CAUSTIC_LOW,
    ERR_CIP_PH_OUT_OF_RANGE,
    ERR_CIP_STALE,
    ERR_INSUFFICIENT_CODE_LIFE,
    ERR_PASTEURIZER_OVERLAP,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_RUN_NOT_RUNNING,
    ERR_SHELF_LIFE_EXCEEDED,
    ERR_SOD_VIOLATION,
    bad_input,
    invalid_state,
    not_found,
)
from helpers import (
    body,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    sort_and_paginate,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    MAX_SHELF_LIFE,
    PRODUCT_CODES,
    latest_permit,
    ser_batch,
    ser_cip,
    ser_run,
)

bp = Blueprint("runs", __name__)

_PO = "PasteurizerOperator"
_PC = "PlantController"
_QA = "QualityAssuranceManager"


def _get_run(run_id):
    run = STORE["runs"].get(run_id)
    if run is None:
        raise not_found("PasteurizerRun not found")
    return run


def _get_cip(run_id, cip_id):
    cycle = STORE["cip_cycles"].get(cip_id)
    if cycle is None or cycle["pasteurizer_run_id"] != run_id:
        raise not_found("CipCycle not found")
    return cycle


def _get_batch(run_id, batch_id):
    batch = STORE["batches"].get(batch_id)
    if batch is None or batch["pasteurizer_run_id"] != run_id:
        raise not_found("ProductBatch not found")
    return batch


def _batches_of(run_id):
    return [b for b in STORE["batches"].values()
            if b["pasteurizer_run_id"] == run_id]


# ---------------------------------------------------------------------------
# Pasteurizer runs
# ---------------------------------------------------------------------------
@bp.route("/dairy/pasteurizer-runs", methods=["POST"])
def create_run():
    require_roles(_PO)
    data = body()
    pasteurizer_id = req_str(data, "pasteurizer_id")
    scheduled_start = req_dt(data, "scheduled_start_at")
    scheduled_end = req_dt(data, "scheduled_end_at")
    flow_rate = req_int(data, "flow_rate_gph")
    min_hold = req_num(data, "min_hold_temp_f")
    if not scheduled_end > scheduled_start:
        raise bad_input(
            "scheduled_end_at must be strictly greater than scheduled_start_at"
        )
    if min_hold < 161:
        raise bad_input("min_hold_temp_f must be at least 161 for HTST")
    rec = base_record()
    rec.update({
        "pasteurizer_id": pasteurizer_id,
        "scheduled_start_at": scheduled_start,
        "scheduled_end_at": scheduled_end,
        "actual_start_at": None,
        "actual_end_at": None,
        "flow_rate_gph": flow_rate,
        "min_hold_temp_f": min_hold,
        "status": "SCHEDULED",
    })
    STORE["runs"][rec["id"]] = rec
    return success_object(ser_run(rec), 201)


@bp.route("/dairy/pasteurizer-runs", methods=["GET"])
def list_runs():
    require_roles(_PO, _PC, _QA)
    pasteurizer_id = request.args.get("pasteurizer_id")
    status = request.args.get("status")
    records = list(STORE["runs"].values())
    if pasteurizer_id is not None:
        records = [r for r in records if r["pasteurizer_id"] == pasteurizer_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_run(r) for r in page], pagination)


@bp.route("/dairy/pasteurizer-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    require_roles(_PO, _PC, _QA)
    return success_object(ser_run(_get_run(run_id)))


@bp.route("/dairy/pasteurizer-runs/<run_id>/start", methods=["POST"])
def start_run(run_id):
    require_roles(_PO)
    run = _get_run(run_id)
    if run["status"] != "SCHEDULED":
        raise invalid_state("PasteurizerRun is not in SCHEDULED")

    permit = latest_permit()
    if permit is None or permit["status"] != "ACTIVE" \
            or permit["expires_at"] <= run["scheduled_end_at"]:
        raise ApiError(ERR_PERMIT_NOT_ACTIVE, 422,
                       "Grade A permit is not ACTIVE or expires before the run")

    completed = []
    for cycle in STORE["cip_cycles"].values():
        parent = STORE["runs"].get(cycle["pasteurizer_run_id"])
        if parent is not None \
                and parent["pasteurizer_id"] == run["pasteurizer_id"] \
                and cycle["status"] in ("VALIDATED", "FAILED") \
                and cycle["completed_at"] is not None:
            completed.append(cycle)
    latest = None
    if completed:
        latest = max(completed, key=lambda c: (c["completed_at"], c["_seq"]))
    if latest is None or latest["validation_outcome"] != "PASS" \
            or latest["completed_at"] < now() - timedelta(hours=24):
        raise ApiError(
            ERR_CIP_STALE, 422,
            "Most recent VALIDATED CipCycle is missing or older than 24 hours",
        )

    for other in STORE["runs"].values():
        if other["id"] == run["id"]:
            continue
        if other["pasteurizer_id"] != run["pasteurizer_id"]:
            continue
        if other["status"] != "RUNNING":
            continue
        if other["scheduled_start_at"] < run["scheduled_end_at"] \
                and run["scheduled_start_at"] < other["scheduled_end_at"]:
            raise ApiError(
                ERR_PASTEURIZER_OVERLAP, 409,
                "Another RUNNING run on the same pasteurizer overlaps",
            )

    run["status"] = "RUNNING"
    run["actual_start_at"] = now()
    touch(run)
    return success_object(ser_run(run), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/complete", methods=["POST"])
def complete_run(run_id):
    require_roles(_PO)
    run = _get_run(run_id)
    if run["status"] != "RUNNING":
        raise invalid_state("PasteurizerRun is not in RUNNING")
    batches = _batches_of(run_id)
    if any(b["status"] not in ("CODED", "SCRAPPED") for b in batches):
        raise ApiError(ERR_BATCHES_UNFINISHED, 422,
                       "Batches not in CODED or SCRAPPED remain")
    run["status"] = "COMPLETE"
    run["actual_end_at"] = now()
    touch(run)
    for batch in batches:
        if batch["status"] == "CODED":
            batch["code_date"] = run["actual_end_at"] + timedelta(
                days=batch["shelf_life_days"]
            )
            touch(batch)
    return success_object(ser_run(run), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/abort", methods=["POST"])
def abort_run(run_id):
    require_roles(_PO)
    run = _get_run(run_id)
    if run["status"] != "RUNNING":
        raise invalid_state("PasteurizerRun is not in RUNNING")
    run["status"] = "ABORTED"
    run["actual_end_at"] = now()
    touch(run)
    for batch in _batches_of(run_id):
        if batch["status"] not in ("CODED", "SCRAPPED"):
            batch["status"] = "SCRAPPED"
            touch(batch)
    return success_object(ser_run(run), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/cancel", methods=["POST"])
def cancel_run(run_id):
    require_roles(_PO)
    run = _get_run(run_id)
    if run["status"] != "SCHEDULED":
        raise invalid_state("PasteurizerRun is not in SCHEDULED")
    batches = _batches_of(run_id)
    if any(b["status"] == "IN_PRODUCTION" for b in batches):
        raise ApiError(ERR_BATCH_IN_PRODUCTION, 422,
                       "A batch is IN_PRODUCTION for this run")
    run["status"] = "CANCELLED"
    touch(run)
    for batch in batches:
        if batch["status"] == "SCHEDULED":
            batch["status"] = "SCRAPPED"
            touch(batch)
    return success_object(ser_run(run), 200)


# ---------------------------------------------------------------------------
# CIP cycles (nested under run)
# ---------------------------------------------------------------------------
@bp.route("/dairy/pasteurizer-runs/<run_id>/cip-cycles", methods=["POST"])
def create_cip(run_id):
    user_id = require_roles(_PO)
    _get_run(run_id)
    data = body()
    started_at = req_dt(data, "started_at")
    caustic = req_num(data, "caustic_conductivity_ms")
    rinse_ph = req_num(data, "rinse_ph")
    rec = base_record()
    rec.update({
        "pasteurizer_run_id": run_id,
        "started_at": started_at,
        "completed_at": None,
        "caustic_conductivity_ms": caustic,
        "rinse_ph": rinse_ph,
        "validation_outcome": None,
        "status": "IN_PROGRESS",
        "_created_by": user_id,
    })
    STORE["cip_cycles"][rec["id"]] = rec
    return success_object(ser_cip(rec), 201)


@bp.route("/dairy/pasteurizer-runs/<run_id>/cip-cycles", methods=["GET"])
def list_cips(run_id):
    require_roles(_PO, _QA, _PC)
    _get_run(run_id)
    run_filter = request.args.get("pasteurizer_run_id")
    records = [c for c in STORE["cip_cycles"].values()
               if c["pasteurizer_run_id"] == run_id]
    if run_filter is not None:
        records = [c for c in records
                   if c["pasteurizer_run_id"] == run_filter]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_cip(c) for c in page], pagination)


@bp.route("/dairy/pasteurizer-runs/<run_id>/cip-cycles/<cip_id>/validate",
          methods=["POST"])
def validate_cip(run_id, cip_id):
    user_id = require_roles(_QA)
    _get_run(run_id)
    cycle = _get_cip(run_id, cip_id)
    if cycle["status"] != "IN_PROGRESS":
        raise invalid_state("CipCycle is not IN_PROGRESS")
    if cycle["caustic_conductivity_ms"] < 80.0:
        raise ApiError(ERR_CIP_CAUSTIC_LOW, 422,
                       "caustic_conductivity_ms < 80.0")
    if not 6.5 <= cycle["rinse_ph"] <= 8.0:
        raise ApiError(ERR_CIP_PH_OUT_OF_RANGE, 422,
                       "rinse_ph outside [6.5, 8.0]")
    if user_id == cycle.get("_created_by"):
        raise ApiError(
            ERR_SOD_VIOLATION, 403,
            "Validating QA manager must differ from the cycle's creator",
        )
    cycle["status"] = "VALIDATED"
    cycle["validation_outcome"] = "PASS"
    cycle["completed_at"] = now()
    touch(cycle)
    return success_object(ser_cip(cycle), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/cip-cycles/<cip_id>/fail",
          methods=["POST"])
def fail_cip(run_id, cip_id):
    require_roles(_QA)
    _get_run(run_id)
    cycle = _get_cip(run_id, cip_id)
    if cycle["status"] != "IN_PROGRESS":
        raise invalid_state("CipCycle is not IN_PROGRESS")
    cycle["status"] = "FAILED"
    cycle["validation_outcome"] = "FAIL"
    cycle["completed_at"] = now()
    touch(cycle)
    return success_object(ser_cip(cycle), 200)


# ---------------------------------------------------------------------------
# Product batches (nested under run)
# ---------------------------------------------------------------------------
@bp.route("/dairy/pasteurizer-runs/<run_id>/batches", methods=["POST"])
def create_batch(run_id):
    require_roles(_PO)
    run = _get_run(run_id)
    data = body()
    product_code = req_enum(data, "product_code", PRODUCT_CODES)
    quantity = req_int(data, "quantity_gallons")
    shelf_life = req_int(data, "shelf_life_days")
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        raise invalid_state(
            "ProductBatch requires a SCHEDULED or RUNNING parent run"
        )
    rec = base_record()
    rec.update({
        "pasteurizer_run_id": run_id,
        "product_code": product_code,
        "quantity_gallons": quantity,
        "shelf_life_days": shelf_life,
        "code_date": None,
        "status": "SCHEDULED",
    })
    STORE["batches"][rec["id"]] = rec
    return success_object(ser_batch(rec), 201)


@bp.route("/dairy/pasteurizer-runs/<run_id>/batches", methods=["GET"])
def list_batches(run_id):
    require_roles(_PO, _PC, _QA)
    _get_run(run_id)
    run_filter = request.args.get("pasteurizer_run_id")
    records = _batches_of(run_id)
    if run_filter is not None:
        records = [b for b in records
                   if b["pasteurizer_run_id"] == run_filter]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_batch(b) for b in page], pagination)


@bp.route("/dairy/pasteurizer-runs/<run_id>/batches/<batch_id>/begin",
          methods=["POST"])
def begin_batch(run_id, batch_id):
    require_roles(_PO)
    run = _get_run(run_id)
    batch = _get_batch(run_id, batch_id)
    if batch["status"] != "SCHEDULED":
        raise invalid_state("ProductBatch is not in SCHEDULED")
    if run["status"] != "RUNNING":
        raise ApiError(ERR_RUN_NOT_RUNNING, 422,
                       "Parent PasteurizerRun is not RUNNING")
    batch["status"] = "IN_PRODUCTION"
    touch(batch)
    return success_object(ser_batch(batch), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/batches/<batch_id>/code",
          methods=["POST"])
def code_batch(run_id, batch_id):
    require_roles(_PO)
    run = _get_run(run_id)
    batch = _get_batch(run_id, batch_id)
    if batch["status"] != "IN_PRODUCTION":
        raise invalid_state("ProductBatch is not IN_PRODUCTION")
    if batch["shelf_life_days"] > MAX_SHELF_LIFE[batch["product_code"]]:
        raise ApiError(ERR_SHELF_LIFE_EXCEEDED, 422,
                       "shelf_life_days exceeds the product-specific cap")
    clock = now()
    base = run["actual_end_at"] or clock
    code_date = base + timedelta(days=batch["shelf_life_days"])
    for route in STORE["routes"].values():
        days_at_delivery = (code_date - clock).days - route["transit_days"]
        if days_at_delivery < route["min_days_of_code_required"]:
            raise ApiError(
                ERR_INSUFFICIENT_CODE_LIFE, 422,
                "code_date cannot satisfy min_days_of_code_required at "
                "delivery for route '%s'" % route["route_code"],
            )
    batch["code_date"] = code_date
    batch["status"] = "CODED"
    touch(batch)
    return success_object(ser_batch(batch), 200)


@bp.route("/dairy/pasteurizer-runs/<run_id>/batches/<batch_id>/scrap",
          methods=["POST"])
def scrap_batch(run_id, batch_id):
    require_roles(_PO)
    _get_run(run_id)
    batch = _get_batch(run_id, batch_id)
    if batch["status"] != "IN_PRODUCTION":
        raise invalid_state("ProductBatch is not IN_PRODUCTION")
    batch["status"] = "SCRAPPED"
    touch(batch)
    return success_object(ser_batch(batch), 200)
