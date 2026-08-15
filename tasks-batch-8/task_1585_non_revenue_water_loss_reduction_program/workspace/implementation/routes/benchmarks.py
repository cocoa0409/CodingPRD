"""BenchmarkReport endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from services import calc, core
from util import canon, paginate, sort_created, v_dt, v_int

bp = make_bp("benchmarks")

RL = {"RegulatorLiaison"}
READ_ROLES = {"ProgramDirector", "UtilityAnalyst", "RegulatorLiaison"}


def _get_or_404(report_id):
    rec = db.store["benchmark_reports"].get(report_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "benchmark report not found")
    return rec


@bp.route("/nrw/benchmark-reports", methods=["POST"])
def create_report():
    uid, role = require_roles(RL)
    body = get_body()
    # priority 3: existence of every element of dma_ids
    dma_ids = body.get("dma_ids")
    if isinstance(dma_ids, list):
        for element in dma_ids:
            if not isinstance(element, str) or element not in db.store["dmas"]:
                raise ApiError(errors.ERR_NOT_FOUND, 404,
                               "an element of dma_ids does not resolve to an existing DMA")
    # priority 9: scalar constraints
    year = v_int(body, "reporting_year", ge=2000)
    start = v_dt(body, "reporting_period_start")
    end = v_dt(body, "reporting_period_end")
    if not isinstance(dma_ids, list) or any(not isinstance(e, str) for e in dma_ids):
        raise ApiError(errors.ERR_VALIDATION, 422, "dma_ids must be an array of strings")
    if not end > start:
        raise ApiError(errors.ERR_VALIDATION, 422,
                       "reporting_period_end must be after reporting_period_start")

    rec = db.new_record()
    rec.update({
        "reporting_year": year,
        "reporting_period_start": canon(start),
        "reporting_period_end": canon(end),
        "dma_ids": list(dma_ids),
        "status": "DRAFT",
        "utility_nrw_pct": None,
        "utility_ili": None,
        "per_dma_breakdown": None,
    })
    db.store["benchmark_reports"][rec["id"]] = rec
    db.append_audit("BenchmarkReport", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/benchmark-reports", methods=["GET"])
def list_reports():
    require_roles(READ_ROLES)
    from flask import request
    items = list(db.store["benchmark_reports"].values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    year = request.args.get("reporting_year")
    if year is not None:
        items = [r for r in items if str(r["reporting_year"]) == year]
    dma = request.args.get("dma_ids")
    if dma is not None:
        items = [r for r in items if dma in r["dma_ids"]]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(r) for r in page], meta)


@bp.route("/nrw/benchmark-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    require_roles(READ_ROLES)
    return success_object(db.serialize(_get_or_404(report_id)))


@bp.route("/nrw/benchmark-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    uid, role = require_roles(RL)
    rec = _get_or_404(report_id)
    # priority 5: state-machine validity
    if rec["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a DRAFT or RETURNED report can be submitted")
    body = get_body()
    # priority 9: scalar — expected_report_version is mandatory
    expected = v_int(body, "expected_report_version")
    # priority 10: cross-entity prerequisites
    if not rec["dma_ids"]:
        raise ApiError(errors.ERR_MISSING_PREREQUISITE, 422,
                       "dma_ids must be non-empty at submission")
    for dma_id in rec["dma_ids"]:
        bal = calc.qualifying_balance(dma_id, rec["reporting_period_start"],
                                      rec["reporting_period_end"])
        if bal is None:
            raise ApiError(errors.ERR_MISSING_PREREQUISITE, 422,
                           "every listed DMA needs a qualifying FINALIZED balance "
                           "fully inside the reporting window")
    # priority 13: OCC
    if expected != rec["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_report_version does not match the report's current version")

    calc.compute_benchmark_snapshot(rec)
    before = rec["status"]
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    # freeze the districts
    for dma_id in rec["dma_ids"]:
        core.recompute_posture(db.store["dmas"][dma_id])
    db.append_audit("BenchmarkReport", rec["id"], "SUBMIT", uid, role,
                    {"before": {"status": before}, "after": {"status": "SUBMITTED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/benchmark-reports/<report_id>/accept", methods=["POST"])
def accept_report(report_id):
    uid, role = require_roles(RL)
    rec = _get_or_404(report_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SUBMITTED report can be accepted")
    rec["status"] = "ACCEPTED"
    db.touch(rec)
    # acceptance does not release the DMA freeze
    for dma_id in rec["dma_ids"]:
        core.recompute_posture(db.store["dmas"][dma_id])
    db.append_audit("BenchmarkReport", rec["id"], "ACCEPT", uid, role,
                    {"before": {"status": "SUBMITTED"},
                     "after": {"status": "ACCEPTED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/benchmark-reports/<report_id>/return", methods=["POST"])
def return_report(report_id):
    uid, role = require_roles(RL)
    rec = _get_or_404(report_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SUBMITTED report can be returned")
    rec["status"] = "RETURNED"
    db.touch(rec)
    # compensation: release the DMA freeze where nothing else gates
    for dma_id in rec["dma_ids"]:
        core.recompute_posture(db.store["dmas"][dma_id])
    db.append_audit("BenchmarkReport", rec["id"], "RETURN", uid, role,
                    {"before": {"status": "SUBMITTED"},
                     "after": {"status": "RETURNED"}})
    return success_object(db.serialize(rec))
