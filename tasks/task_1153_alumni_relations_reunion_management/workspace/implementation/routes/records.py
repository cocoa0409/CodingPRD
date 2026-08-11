"""AlumniRecord endpoints."""

from flask import Blueprint

import db
from errors import (
    err_invalid_request, err_invalid_state, err_not_found, err_stale_version,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import recompute_all_preferences_for
from services.cascades import mark_alumnus_deceased
from services.common import (
    apply_pagination, json_body, logical_ts, new_entity, pagination_args,
    req_int, req_str, touch,
)
from services.serializers import RECORD_FIELDS, serialize

bp = Blueprint("records", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
ALL_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair",
            "CommitteeVolunteer", "AffinityGroupLeader", "Alumni")


def _get_record(record_id):
    rec = db.records.get(record_id)
    if rec is None:
        raise err_not_found("AlumniRecord not found")
    return rec


def _check_email_unique(email, exclude_id=None):
    for r in db.records.values():
        if r["id"] == exclude_id:
            continue
        if r["status"] == "DECEASED":
            continue
        if r["primary_email"] == email:
            raise err_invalid_request("primary_email must be unique across non-DECEASED records")


@bp.route("/alumni/records", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_record(_role, _user_id):
    body = json_body(required=["full_name", "primary_email", "class_year", "degree_code"])
    full_name = req_str(body["full_name"], "full_name")
    primary_email = req_str(body["primary_email"], "primary_email")
    class_year = req_int(body["class_year"], "class_year")
    degree_code = req_str(body["degree_code"], "degree_code")
    _check_email_unique(primary_email)

    rec = new_entity({
        "full_name": full_name,
        "primary_email": primary_email,
        "class_year": class_year,
        "degree_code": degree_code,
        "status": "ACTIVE",
        "engagement_score": 0.00,
        "engagement_tier": "LOW",
        "giving_propensity": 0.00,
        "lifetime_giving_cents": 0,
        "lost_since": None,
        "hard_bounce_flag": False,
    })
    db.records[rec["id"]] = rec
    return success_object(serialize(rec, RECORD_FIELDS), status=201)


@bp.route("/alumni/records/<rid>", methods=["GET"])
@require_roles(*ALL_READ)
def get_record(rid, _role, _user_id):
    rec = _get_record(rid)
    return success_object(serialize(rec, RECORD_FIELDS))


@bp.route("/alumni/records", methods=["GET"])
@require_roles(*STAFF_OR_DIRECTOR)
def list_records(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.records.values())
    status = _q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    class_year = _q("class_year")
    if class_year is not None:
        try:
            cy = int(class_year)
        except ValueError:
            raise err_invalid_request("class_year must be an integer")
        rows = [r for r in rows if r["class_year"] == cy]
    tier = _q("engagement_tier")
    if tier is not None:
        rows = [r for r in rows if r["engagement_tier"] == tier]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(r, RECORD_FIELDS) for r in page], limit, offset, total)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/alumni/records/<rid>", methods=["PUT"])
@require_roles(*STAFF_OR_DIRECTOR)
def update_record(rid, _role, _user_id):
    rec = _get_record(rid)
    body = json_body(required=["expected_record_version"])
    expected = body["expected_record_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_record_version must be an integer")
    if expected != rec["version"]:
        raise err_stale_version("AlumniRecord version has advanced")

    if "full_name" in body and body["full_name"] is not None:
        rec["full_name"] = req_str(body["full_name"], "full_name")
    if "primary_email" in body and body["primary_email"] is not None:
        email = req_str(body["primary_email"], "primary_email")
        if email != rec["primary_email"]:
            _check_email_unique(email, exclude_id=rec["id"])
        rec["primary_email"] = email
    if "degree_code" in body and body["degree_code"] is not None:
        rec["degree_code"] = req_str(body["degree_code"], "degree_code")

    touch(rec)
    return success_object(serialize(rec, RECORD_FIELDS))


@bp.route("/alumni/records/<rid>/mark-lost", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def mark_lost(rid, _role, _user_id):
    rec = _get_record(rid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("AlumniRecord must be ACTIVE to mark lost")
    # Precondition: no CONFIRMED registration on an OPEN_FOR_REGISTRATION event
    for reg in db.registrations.values():
        if reg["alumni_id"] != rid or reg["payment_status"] != "CONFIRMED":
            continue
        event = db.events.get(reg["event_id"])
        if event is not None and event["status"] == "OPEN_FOR_REGISTRATION":
            raise err_invalid_state(
                "Alumnus holds a CONFIRMED registration on an open event")
    rec["status"] = "LOST"
    rec["lost_since"] = logical_ts()
    touch(rec)
    recompute_all_preferences_for(rid)
    return success_object(serialize(rec, RECORD_FIELDS))


@bp.route("/alumni/records/<rid>/set-do-not-contact", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def set_dnc(rid, _role, _user_id):
    rec = _get_record(rid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("AlumniRecord must be ACTIVE to set do-not-contact")
    rec["status"] = "DO_NOT_CONTACT"
    touch(rec)
    recompute_all_preferences_for(rid)
    return success_object(serialize(rec, RECORD_FIELDS))


@bp.route("/alumni/records/<rid>/clear-do-not-contact", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def clear_dnc(rid, _role, _user_id):
    rec = _get_record(rid)
    if rec["status"] != "DO_NOT_CONTACT":
        raise err_invalid_state("AlumniRecord must be DO_NOT_CONTACT to clear")
    rec["status"] = "ACTIVE"
    touch(rec)
    recompute_all_preferences_for(rid)
    return success_object(serialize(rec, RECORD_FIELDS))


@bp.route("/alumni/records/<rid>/mark-deceased", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def mark_deceased(rid, _role, _user_id):
    rec = _get_record(rid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("AlumniRecord must be ACTIVE to mark deceased")
    mark_alumnus_deceased(rec)
    return success_object(serialize(rec, RECORD_FIELDS))
