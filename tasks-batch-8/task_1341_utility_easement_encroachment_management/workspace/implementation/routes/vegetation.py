"""VegetationZone and VegetationViolation endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from constants import (
    EXEMPTABLE_HEIGHT_MARGIN_FT,
    LOCATIONS_WITHIN_ZONE,
    REMEDIATION_WINDOW_DAYS,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from services.serializers import serialize_violation, serialize_zone, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    parse_ts_stored,
    require_enum,
    require_list,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("vegetation", __name__)

READERS = (VI, RoWA, DD)


@bp.route("/easement-cases/<case_id>/vegetation-zones", methods=["POST"])
@require_roles(VI)
def create_zone(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    zone_label = require_string(body, "zone_label")
    max_allowed_height_ft = require_number(body, "max_allowed_height_ft")
    prohibited_species = require_list(body, "prohibited_species")
    wire_zone_width_ft = require_number(body, "wire_zone_width_ft")
    border_zone_width_ft = require_number(body, "border_zone_width_ft")

    zone = {
        "case_id": case_id,
        "zone_label": zone_label,
        "max_allowed_height_ft": float(max_allowed_height_ft) if max_allowed_height_ft % 1 else int(max_allowed_height_ft),
        "prohibited_species": prohibited_species,
        "wire_zone_width_ft": float(wire_zone_width_ft) if wire_zone_width_ft % 1 else int(wire_zone_width_ft),
        "border_zone_width_ft": float(border_zone_width_ft) if border_zone_width_ft % 1 else int(border_zone_width_ft),
        "last_inspection_date": None,
        "violation_count": 0,
        "status": "ACTIVE_MONITORING",
    }
    db.stamp_new(zone)
    db.zones[zone["id"]] = zone
    return success_object(serialize_zone(zone), 201)


@bp.route("/easement-cases/<case_id>/vegetation-zones", methods=["GET"])
@require_roles(*READERS)
def list_zones(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [z for z in db.zones.values() if z["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_zone), limit, offset, total)


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>", methods=["GET"])
@require_roles(*READERS)
def get_zone(case_id: str, zone_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    zone = domain.get_zone_or_404(case, zone_id)
    return success_object(serialize_zone(zone))


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>/violations", methods=["POST"])
@require_roles(VI)
def create_violation(case_id: str, zone_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    zone = domain.get_zone_or_404(case, zone_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    species = require_string(body, "species")
    observed_height_ft = require_number(body, "observed_height_ft")
    location = require_enum(body, "location_within_zone", LOCATIONS_WITHIN_ZONE)

    excess = calculations.excess_height_ft(zone, observed_height_ft, location)
    viol = {
        "zone_id": zone_id,
        "case_id": case_id,
        "species": species,
        "observed_height_ft": float(observed_height_ft) if observed_height_ft % 1 else int(observed_height_ft),
        "location_within_zone": location,
        "excess_height_ft": excess,
        "remediation_deadline": None,
        "status": "DETECTED",
    }
    db.stamp_new(viol)
    db.violations[viol["id"]] = viol

    # Recording a violation is an inspection event for the zone.
    zone["last_inspection_date"] = db.now_iso()
    domain.reconcile_zone(zone)
    db.touch(zone)
    return success_object(serialize_violation(viol), 201)


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>/violations", methods=["GET"])
@require_roles(*READERS)
def list_violations(case_id: str, zone_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.get_zone_or_404(case, zone_id)
    limit, offset = parse_pagination()
    items = [v for v in db.violations.values() if v["zone_id"] == zone_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_violation), limit, offset, total)


def _check_remediation_deadline(viol: dict) -> None:
    deadline = parse_ts_stored(viol.get("remediation_deadline"))
    if deadline is not None and db.get_clock_dt() > deadline:
        raise_err("ERR_DEADLINE_PASSED", "remediation_deadline has passed")


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>/violations/<viol_id>/notify", methods=["POST"])
@require_roles(VI)
def notify_violation(case_id: str, zone_id: str, viol_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    zone = domain.get_zone_or_404(case, zone_id)
    viol = domain.get_violation_or_404(zone, viol_id)
    domain.ensure_case_not_closed(case)
    if viol["status"] != "DETECTED":
        raise_err("ERR_INVALID_STATE", "notify requires violation DETECTED")
    _check_remediation_deadline(viol)
    viol["status"] = "NOTIFIED"
    viol["remediation_deadline"] = db.fmt_dt(
        db.get_clock_dt() + timedelta(days=REMEDIATION_WINDOW_DAYS)
    )
    db.touch(viol)
    return success_object(serialize_violation(viol))


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>/violations/<viol_id>/confirm-remediation", methods=["POST"])
@require_roles(VI)
def confirm_remediation(case_id: str, zone_id: str, viol_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    zone = domain.get_zone_or_404(case, zone_id)
    viol = domain.get_violation_or_404(zone, viol_id)
    domain.ensure_case_not_closed(case)
    if viol["status"] != "NOTIFIED":
        raise_err("ERR_INVALID_STATE", "confirm-remediation requires violation NOTIFIED")
    _check_remediation_deadline(viol)
    viol["status"] = "REMEDIATED"
    db.touch(viol)
    domain.reconcile_zone(zone)
    db.touch(zone)
    return success_object(serialize_violation(viol))


@bp.route("/easement-cases/<case_id>/vegetation-zones/<zone_id>/violations/<viol_id>/exempt", methods=["POST"])
@require_roles(DD)
def exempt_violation(case_id: str, zone_id: str, viol_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    zone = domain.get_zone_or_404(case, zone_id)
    viol = domain.get_violation_or_404(zone, viol_id)
    domain.ensure_case_not_closed(case)
    if viol["status"] != "DETECTED":
        raise_err("ERR_INVALID_STATE", "exempt requires violation DETECTED")
    if viol["species"] in (zone.get("prohibited_species") or []):
        raise_err(
            "ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE",
            "Violation species is in zone.prohibited_species; cannot exempt",
        )
    if float(viol["excess_height_ft"]) > EXEMPTABLE_HEIGHT_MARGIN_FT:
        raise_err("ERR_EXCESS_HEIGHT_TOO_LARGE", "excess_height_ft exceeds EXEMPTABLE_HEIGHT_MARGIN_FT")
    viol["status"] = "EXEMPTED"
    db.touch(viol)
    domain.reconcile_zone(zone)
    db.touch(zone)
    return success_object(serialize_violation(viol))
