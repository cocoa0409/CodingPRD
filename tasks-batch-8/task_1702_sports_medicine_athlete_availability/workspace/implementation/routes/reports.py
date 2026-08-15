"""Disclosure grants, availability reports, injury-rate analytics."""
from flask import Blueprint, request

from db import STORE, new_id, now_stamp, touch, clock_date, clock_dt
from errors import (bad_request, not_found, conflict, ApiError,
                    ERR_GRANT_NOT_ACTIVE, ERR_AUDIENCE_INVALID)
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import (disclosure_grant_json, availability_report_json,
                                sorted_items)
from services.reports import materialize_lazy_expiry, injury_rate_groups
from util import (body, present, require_str, require_enum, require_date,
                  parse_date_value)

bp = Blueprint("reports", __name__)

GRANTEE_ROLES = ["COACHING", "FRONT_OFFICE"]
SCOPES = ["TIER_ONLY", "GENERAL", "FULL"]
AUDIENCES = ["COACHING", "FRONT_OFFICE", "MEDICAL"]
GRANT_READERS = ("MedicalStaff", "TeamAdmin")
REPORT_ROLES = ("CoachingStaff", "MedicalStaff", "TeamAdmin")
ANALYTICS_ROLES = ("MedicalStaff", "TeamAdmin", "PerformanceStaff")


def _get_grant(gid):
    g = STORE["disclosure_grants"].get(gid)
    if g is None:
        raise not_found("DisclosureGrant not found")
    return g


# ---------------- Disclosure grants ----------------

@bp.route("/disclosure-grants", methods=["POST"])
def create_grant():
    require_roles("MedicalStaff")
    j = body()
    athlete = None
    if present(j, "athlete_id"):
        athlete = STORE["athletes"].get(j["athlete_id"])
        if athlete is None:
            raise not_found("Athlete not found: athlete_id")
    if athlete is None:
        require_str(j, "athlete_id")
    grantee_role = require_enum(j, "grantee_role", GRANTEE_ROLES)
    scope = require_enum(j, "scope", SCOPES)
    ef_raw, ef = require_date(j, "effective_from")
    et_raw, et = require_date(j, "effective_to")
    if et <= ef:
        raise bad_request("effective_to must be later than effective_from")
    from datetime import datetime, timezone
    ts = now_stamp()
    grant = {
        "id": new_id(), "athlete_id": athlete["id"],
        "grantee_role": grantee_role, "scope": scope,
        "effective_from": ef_raw, "effective_to": et_raw,
        "_effective_from_dt": datetime(ef.year, ef.month, ef.day, tzinfo=timezone.utc),
        "_effective_to_dt": datetime(et.year, et.month, et.day, tzinfo=timezone.utc),
        "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    # preserve full-datetime windows when inputs carry time
    from db import parse_iso_dt
    pef = parse_iso_dt(ef_raw)
    pet = parse_iso_dt(et_raw)
    if pef is not None:
        grant["_effective_from_dt"] = pef
    if pet is not None:
        grant["_effective_to_dt"] = pet
    STORE["disclosure_grants"][grant["id"]] = grant
    return ok_obj(disclosure_grant_json(grant), 201)


@bp.route("/disclosure-grants", methods=["GET"])
def list_grants():
    require_roles(*GRANT_READERS)
    items = sorted_items(STORE["disclosure_grants"])
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    grantee_role = request.args.get("grantee_role")
    for g in items:
        materialize_lazy_expiry(g)
    if athlete_id is not None:
        items = [g for g in items if g["athlete_id"] == athlete_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    if grantee_role is not None:
        items = [g for g in items if g["grantee_role"] == grantee_role]
    return ok_list([disclosure_grant_json(g) for g in items])


@bp.route("/disclosure-grants/<grantId>", methods=["GET"])
def get_grant(grantId):
    require_roles(*GRANT_READERS)
    return ok_obj(disclosure_grant_json(_get_grant(grantId)))


@bp.route("/disclosure-grants/<grantId>/revoke", methods=["POST"])
def revoke_grant(grantId):
    require_roles("MedicalStaff")
    grant = _get_grant(grantId)
    materialize_lazy_expiry(grant)
    if grant["status"] != "ACTIVE":
        raise conflict(ERR_GRANT_NOT_ACTIVE, "revoke requires grant ACTIVE")
    grant["status"] = "REVOKED"
    touch(grant)
    return ok_obj(disclosure_grant_json(grant))


# ---------------- Availability reports ----------------

@bp.route("/availability-reports", methods=["POST"])
def create_report():
    uid, _ = require_roles(*REPORT_ROLES)
    j = body()
    team = None
    if present(j, "team_id"):
        team = STORE["teams"].get(j["team_id"])
        if team is None:
            raise not_found("Team not found: team_id")
    if team is None:
        require_str(j, "team_id")
    if not present(j, "audience"):
        raise bad_request("Missing required field: audience")
    audience = j["audience"]
    if not isinstance(audience, str) or audience not in AUDIENCES:
        raise ApiError(ERR_AUDIENCE_INVALID, 400,
                       "audience must be one of COACHING | FRONT_OFFICE | MEDICAL")
    ts = now_stamp()
    report = {
        "id": new_id(), "team_id": team["id"],
        "report_date": clock_date().isoformat(),
        "generated_by_user_id": uid, "generated_for_role": audience,
        "created_at": ts,
    }
    STORE["availability_reports"][report["id"]] = report
    return ok_obj(availability_report_json(report), 201)


@bp.route("/availability-reports", methods=["GET"])
def list_reports():
    require_roles(*REPORT_ROLES)
    items = sorted_items(STORE["availability_reports"])
    team_id = request.args.get("team_id")
    if team_id is not None:
        items = [r for r in items if r["team_id"] == team_id]
    return ok_list([availability_report_json(r) for r in items])


@bp.route("/availability-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require_roles(*REPORT_ROLES)
    r = STORE["availability_reports"].get(reportId)
    if r is None:
        raise not_found("AvailabilityReport not found")
    return ok_obj(availability_report_json(r))


# ---------------- Injury trend analytics ----------------

@bp.route("/teams/<teamId>/analytics/injury-rates", methods=["GET"])
def injury_rates(teamId):
    require_roles(*ANALYTICS_ROLES)
    team = STORE["teams"].get(teamId)
    if team is None:
        raise not_found("Team not found")
    from_raw = request.args.get("from_date")
    to_raw = request.args.get("to_date")
    from_d = parse_date_value(from_raw) if from_raw is not None else None
    to_d = parse_date_value(to_raw) if to_raw is not None else None
    if from_d is None or to_d is None:
        raise bad_request("from_date and to_date query parameters are required")
    groups = injury_rate_groups(teamId, from_d, to_d)
    return ok_obj({"groups": groups})
