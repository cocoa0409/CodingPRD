"""Encounter + ProductivityReport endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_ENCOUNTER_ALREADY_VOIDED, ERR_REPORT_INVALID_STATE,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    make_entity, touch, round2, ESTIMATED_WRVU, ADJUST_FACTOR,
    compute_report_totals, link_report_encounters,
)
from services import serializers
import clock

bp = Blueprint("productivity", __name__)

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]
ENCOUNTER_TYPES = {"ADMISSION_HCP", "SUBSEQUENT_VISIT", "DISCHARGE_DAY", "CONSULT_NOTE"}


def _paginate(items, serializer):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------

@bp.route("/encounters", methods=["POST"])
def create_encounter():
    role, uid = require_roles(["Hospitalist"])
    body = _body()
    patient_id = body.get("patient_id")
    encounter_type = body.get("encounter_type")
    occurred_on = body.get("occurred_on")
    wrvu_value = body.get("wrvu_value")

    if not patient_id or not isinstance(patient_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "patient_id is required", 400)
    if encounter_type not in ENCOUNTER_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid encounter_type", 400)
    if not isinstance(occurred_on, str) or clock.parse_date(occurred_on) is None:
        raise ApiError(ERR_INVALID_REQUEST, "occurred_on must be YYYY-MM-DD", 400)
    if not isinstance(wrvu_value, (int, float)) or isinstance(wrvu_value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "wrvu_value must be a number", 400)

    patient = store["patients"].get(patient_id)
    if patient is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)

    est = round2(ESTIMATED_WRVU[encounter_type] * ADJUST_FACTOR)
    e = make_entity({
        "hospitalist_id": uid,
        "patient_id": patient_id,
        "encounter_type": encounter_type,
        "occurred_on": occurred_on,
        "wrvu_value": wrvu_value,
        "estimated_wrvu": est,
        "status": "RECORDED",
        "productivity_report_id": None,
    })
    store["encounters"][e["id"]] = e
    return success_object(serializers.encounter(e), 201)


@bp.route("/encounters", methods=["GET"])
def list_encounters():
    require_roles(ALL_ROLES)
    items = list(store["encounters"].values())
    hid = request.args.get("hospitalist_id")
    if hid is not None:
        items = [e for e in items if e["hospitalist_id"] == hid]
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [e for e in items if e["patient_id"] == pid]
    rid = request.args.get("productivity_report_id")
    if rid is not None:
        items = [e for e in items if e.get("productivity_report_id") == rid]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    return _paginate(items, serializers.encounter)


@bp.route("/encounters/<eid>", methods=["GET"])
def get_encounter(eid):
    require_roles(ALL_ROLES)
    e = store["encounters"].get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, "Encounter not found", 404)
    return success_object(serializers.encounter(e))


@bp.route("/encounters/<eid>/void", methods=["POST"])
def void_encounter(eid):
    role, uid = require_roles(["Hospitalist", "GroupAdmin"])
    e = store["encounters"].get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, "Encounter not found", 404)
    if role == "Hospitalist" and e["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "Hospitalist may only void own encounters", 403)
    if e["status"] != "RECORDED":
        raise ApiError(ERR_ENCOUNTER_ALREADY_VOIDED, "encounter is already VOIDED", 409)
    e["status"] = "VOIDED"
    touch(e)

    rid = e.get("productivity_report_id")
    if rid is not None:
        report = store["productivity_reports"].get(rid)
        if report is not None:
            if report["status"] == "FINALIZED":
                report["status"] = "REOPENED"
                compute_report_totals(report)
                touch(report)
            elif report["status"] in ("PROVISIONAL", "REOPENED"):
                compute_report_totals(report)
                touch(report)
    return success_object(serializers.encounter(e))


# ---------------------------------------------------------------------------
# Productivity reports
# ---------------------------------------------------------------------------

@bp.route("/productivity-reports/generate", methods=["POST"])
def generate_report():
    require_roles(["GroupAdmin"])
    body = _body()
    hospitalist_id = body.get("hospitalist_id")
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    if not hospitalist_id or not isinstance(hospitalist_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "hospitalist_id is required", 400)
    if clock.parse_date(period_start) is None or clock.parse_date(period_end) is None:
        raise ApiError(ERR_INVALID_REQUEST, "period_start and period_end must be YYYY-MM-DD", 400)

    h = store["hospitalists"].get(hospitalist_id)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Hospitalist not found", 404)

    now = clock.now()
    r = make_entity({
        "hospitalist_id": hospitalist_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "PROVISIONAL",
        "encounter_count": 0,
        "total_wrvu_provisional": Decimal("0"),
        "total_wrvu_final": None,
        "wrvu_variance": None,
        "generated_at": now,
        "finalized_at": None,
    })
    store["productivity_reports"][r["id"]] = r
    link_report_encounters(r)
    compute_report_totals(r)
    return success_object(serializers.productivity_report(r), 201)


@bp.route("/productivity-reports", methods=["GET"])
def list_reports():
    require_roles(["GroupAdmin", "Hospitalist"])
    items = list(store["productivity_reports"].values())
    hid = request.args.get("hospitalist_id")
    if hid is not None:
        items = [r for r in items if r["hospitalist_id"] == hid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    return _paginate(items, serializers.productivity_report)


@bp.route("/productivity-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_roles(["GroupAdmin", "Hospitalist"])
    r = store["productivity_reports"].get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "ProductivityReport not found", 404)
    return success_object(serializers.productivity_report(r))


@bp.route("/productivity-reports/<rid>/finalize", methods=["POST"])
def finalize_report(rid):
    require_roles(["GroupAdmin"])
    r = store["productivity_reports"].get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "ProductivityReport not found", 404)
    if r["status"] not in ("PROVISIONAL", "REOPENED"):
        raise ApiError(ERR_REPORT_INVALID_STATE, "finalize requires PROVISIONAL or REOPENED", 409)

    # re-link all currently RECORDED in-period encounters
    link_report_encounters(r)
    # recompute provisional + final
    linked = [
        e for e in store["encounters"].values()
        if e["hospitalist_id"] == r["hospitalist_id"]
        and e["status"] == "RECORDED"
        and r["period_start"] <= e["occurred_on"] <= r["period_end"]
    ]
    r["encounter_count"] = len(linked)
    prov = Decimal("0")
    raw = Decimal("0")
    for e in linked:
        prov += Decimal(str(e["estimated_wrvu"]))
        raw += Decimal(str(e["wrvu_value"]))
    r["total_wrvu_provisional"] = round2(prov)
    final = round2(raw)
    r["total_wrvu_final"] = final
    r["wrvu_variance"] = round2(final - r["total_wrvu_provisional"])

    r["status"] = "FINALIZED"
    r["finalized_at"] = clock.now()
    touch(r)
    return success_object(serializers.productivity_report(r))


@bp.route("/productivity-reports/<rid>/reopen", methods=["POST"])
def reopen_report(rid):
    require_roles(["GroupAdmin"])
    r = store["productivity_reports"].get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "ProductivityReport not found", 404)
    if r["status"] != "FINALIZED":
        raise ApiError(ERR_REPORT_INVALID_STATE, "reopen requires FINALIZED", 409)
    r["status"] = "REOPENED"
    compute_report_totals(r)
    touch(r)
    return success_object(serializers.productivity_report(r))
