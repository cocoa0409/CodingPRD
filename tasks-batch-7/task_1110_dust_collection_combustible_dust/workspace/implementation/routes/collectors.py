"""Collector endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_COLLECTOR_BUSY,
    ERR_COLLECTOR_HAS_OPEN_FINDING,
    ERR_FILTER_CHANGE_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POSTURE_STOP_WORK,
    ERR_VENT_UNDERSIZED,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    auto_create_finding,
    get_flat_or_404,
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    require_fields,
    serialize,
    touch,
    validate_int,
    validate_number,
    validate_str,
)

bp = Blueprint("collectors", __name__)

READ_ROLES = ("ComplianceEngineer", "ComplianceManager", "InspectorUser", "SafetyManager")


def _get_collector(site_id, collector_id):
    site = get_site_or_404(site_id)
    col = db.collectors.get(collector_id)
    if col is None or col["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"Collector {collector_id} not found", 404)
    return site, col


def _resolve_sample(site, sample_id):
    sample = db.dust_samples.get(sample_id)
    if sample is None or sample["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"DustSample {sample_id} not found", 404)
    return sample


@bp.route("/api/sites/<id>/collectors", methods=["POST"])
def create_collector(id):
    require_roles("ComplianceEngineer")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["tag", "dust_sample_id", "design_airflow_acfm", "filter_area_ft2", "internal_volume_m3"])
    validate_str(body, "tag")
    validate_int(body, "design_airflow_acfm", gt=0)
    validate_number(body, "filter_area_ft2", gt=0)
    validate_number(body, "internal_volume_m3", gt=0)
    validate_number(body, "installed_vent_area_m2", ge=0)

    # Body-level FK existence
    sample = _resolve_sample(site, body["dust_sample_id"])

    col = {
        "site_id": site["id"],
        "tag": body["tag"],
        "dust_sample_id": body["dust_sample_id"],
        "design_airflow_acfm": body["design_airflow_acfm"],
        "filter_area_ft2": body["filter_area_ft2"],
        "internal_volume_m3": body["internal_volume_m3"],
        "installed_vent_area_m2": body.get("installed_vent_area_m2", 0),
        "dp_current_inwc": 0,
        "dp_trend": "STABLE",
        "filter_change_due": False,
        "status": "DRAFT",
        "last_filter_change_at": None,
        "last_filter_change_at_dt": None,
    }
    init_common(col)
    calc.explosion_protection_design(col, sample)
    db.collectors[col["id"]] = col
    db.dp_readings[col["id"]] = []
    return success_object(serialize(col), 201)


@bp.route("/api/sites/<id>/collectors", methods=["GET"])
def list_collectors(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [c for c in db.collectors.values() if c["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("dust_sample_id") is not None:
        filters["dust_sample_id"] = "dust_sample_id"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/collectors/<collector_id>", methods=["GET"])
def get_collector(id, collector_id):
    require_roles(*READ_ROLES)
    _, col = _get_collector(id, collector_id)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>", methods=["PATCH"])
def update_collector(id, collector_id):
    require_roles("ComplianceEngineer")
    site, col = _get_collector(id, collector_id)
    body = parse_body()
    validate_str(body, "tag")
    validate_int(body, "design_airflow_acfm", gt=0)
    validate_number(body, "filter_area_ft2", gt=0)
    validate_number(body, "internal_volume_m3", gt=0)
    validate_number(body, "installed_vent_area_m2", ge=0)

    if "dust_sample_id" in body and body["dust_sample_id"] is not None:
        _resolve_sample(site, body["dust_sample_id"])

    changed = False
    for f in ("tag", "dust_sample_id", "design_airflow_acfm", "filter_area_ft2",
              "internal_volume_m3", "installed_vent_area_m2"):
        if f in body and body[f] is not None:
            col[f] = body[f]
            changed = True
    if changed:
        sample = db.dust_samples.get(col["dust_sample_id"])
        calc.explosion_protection_design(col, sample)
        touch(col)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>/commission", methods=["POST"])
def commission_collector(id, collector_id):
    require_roles("ComplianceEngineer")
    site, col = _get_collector(id, collector_id)
    if col["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Collector is not in DRAFT", 409)
    if site["posture"] == "STOP_WORK":
        raise ApiError(ERR_POSTURE_STOP_WORK, "Site is in STOP_WORK posture", 409)
    if not col.get("vent_adequate"):
        raise ApiError(ERR_VENT_UNDERSIZED, "Installed vent area is below required", 422)
    sample = db.dust_samples.get(col["dust_sample_id"])
    if sample is None or not sample.get("combustible"):
        raise ApiError(ERR_INVALID_STATE, "Dust sample is not combustible", 409)

    col["status"] = "IN_SERVICE"
    touch(col)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>/take_out_of_service", methods=["POST"])
def take_out_of_service(id, collector_id):
    require_roles("ComplianceEngineer")
    site, col = _get_collector(id, collector_id)
    if col["status"] != "IN_SERVICE":
        raise ApiError(ERR_INVALID_STATE, "Collector is not IN_SERVICE", 409)
    for permit in db.hot_work_permits.values():
        if permit.get("collector_id") == col["id"] and permit["status"] in ("ISSUED", "IN_PROGRESS"):
            raise ApiError(ERR_COLLECTOR_BUSY, "Collector has an active hot-work permit", 422)

    col["status"] = "OUT_OF_SERVICE"
    touch(col)
    if col.get("filter_change_due"):
        auto_create_finding(site, "MAJOR", col["id"], "Filter change due at take-out-of-service")
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>/return_to_service", methods=["POST"])
def return_to_service(id, collector_id):
    require_roles("ComplianceEngineer")
    site, col = _get_collector(id, collector_id)
    if col["status"] != "OUT_OF_SERVICE":
        raise ApiError(ERR_INVALID_STATE, "Collector is not OUT_OF_SERVICE", 409)
    if site["posture"] == "STOP_WORK":
        raise ApiError(ERR_POSTURE_STOP_WORK, "Site is in STOP_WORK posture", 409)
    if col.get("filter_change_due"):
        raise ApiError(ERR_FILTER_CHANGE_REQUIRED, "Filter change is due", 422)

    col["status"] = "IN_SERVICE"
    touch(col)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>/decommission", methods=["POST"])
def decommission_collector(id, collector_id):
    require_roles("ComplianceManager")
    site, col = _get_collector(id, collector_id)
    if col["status"] != "OUT_OF_SERVICE":
        raise ApiError(ERR_INVALID_STATE, "Collector is not OUT_OF_SERVICE", 409)
    for finding in db.inspection_findings.values():
        if finding.get("collector_id") == col["id"] and finding["status"] in ("OPEN", "IN_PROGRESS"):
            raise ApiError(ERR_COLLECTOR_HAS_OPEN_FINDING, "Collector has open findings", 422)

    col["status"] = "DECOMMISSIONED"
    touch(col)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(col), 200)


@bp.route("/api/sites/<id>/collectors/<collector_id>/dp-readings", methods=["POST"])
def add_dp_reading(id, collector_id):
    require_roles("ComplianceEngineer", "HousekeepingAuditor")
    site, col = _get_collector(id, collector_id)
    body = parse_body()
    require_fields(body, ["dp_inwc"])
    validate_number(body, "dp_inwc")

    reading = {
        "dp_inwc": float(calc.round_half_up(body["dp_inwc"], 2)),
        "created_at": db.now_iso(),
        "seq": db.next_reading_seq(),
    }
    db.dp_readings.setdefault(col["id"], []).append(reading)
    col["dp_current_inwc"] = reading["dp_inwc"]
    calc.dp_trend_derivation(col)
    touch(col)
    return success_object(serialize(col), 201)


@bp.route("/api/sites/<id>/collectors/<collector_id>/record_filter_change", methods=["POST"])
def record_filter_change(id, collector_id):
    require_roles("ComplianceEngineer")
    site, col = _get_collector(id, collector_id)
    col["last_filter_change_at"] = db.now_iso()
    col["last_filter_change_at_dt"] = db.now_dt()
    col["dp_current_inwc"] = 0
    col["filter_change_due"] = False
    calc.dp_trend_derivation(col)
    touch(col)
    return success_object(serialize(col), 200)


# ----- Flat GETs and sub-resource listings -----
@bp.route("/api/collectors/<id>", methods=["GET"])
def get_collector_flat(id):
    require_roles(*READ_ROLES)
    col = get_flat_or_404(db.collectors, id, "Collector")
    return success_object(serialize(col), 200)


@bp.route("/api/collectors/<id>/hot-work-permits", methods=["GET"])
def list_collector_permits(id):
    require_roles("SafetyManager", "ComplianceManager", "ComplianceEngineer",
                  "HotWorkPerformer", "InspectorUser")
    col = get_flat_or_404(db.collectors, id, "Collector")
    items = [p for p in db.hot_work_permits.values() if p.get("collector_id") == col["id"]]
    return paginate(items)


@bp.route("/api/collectors/<id>/incidents", methods=["GET"])
def list_collector_incidents(id):
    require_roles("ComplianceManager", "ComplianceEngineer", "IncidentInvestigator",
                  "SafetyManager", "InspectorUser")
    col = get_flat_or_404(db.collectors, id, "Collector")
    items = [i for i in db.incidents.values() if i.get("collector_id") == col["id"]]
    return paginate(items)


@bp.route("/api/collectors/<id>/inspection-findings", methods=["GET"])
def list_collector_findings(id):
    require_roles("InspectorUser", "ComplianceManager", "ComplianceEngineer")
    col = get_flat_or_404(db.collectors, id, "Collector")
    items = [f for f in db.inspection_findings.values() if f.get("collector_id") == col["id"]]
    return paginate(items)
