"""Anesthesia permits, facility inspections and emergency drills."""
from decimal import Decimal

from flask import Blueprint

from db import clock_dt, clock_str, db, new_record, ordered, touch
from errors import ApiError
from middleware import authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (DRILL_COMPLIANCE_FLOOR, DRILL_TYPES,
                             INSPECTION_STATUSES, PERMIT_LEVELS,
                             PERMIT_STATUSES, get_practice, open_permit,
                             path_row, referenced_row)
from services.permit import (required_drill_types, to_active, to_applied,
                             to_probation, to_revoked, to_suspended)
from services.practice import (permit_ratio, recompute_privilege,
                               refresh_permit_ratio, touch_practice)
from timeutil import parse_date
from validation import (q_bool, q_enum, q_string, read_body, v_enum, v_id,
                        v_instant, v_int, v_not_after)

bp = Blueprint("permits", __name__)


# ------------------------------------------------------------- permits ------

@bp.post("/anesthesia-permits")
def create_permit():
    authorize("PracticeAdministrator")
    body = read_body(required=("practice_id", "permit_level", "applied_on"))
    practice_id = v_id(body, "practice_id")
    permit_level = v_enum(body, "permit_level", PERMIT_LEVELS)
    applied_on = v_instant(body, "applied_on")
    v_not_after(applied_on, "applied_on", clock_dt())

    practice = referenced_row(db.practices, practice_id)
    if open_permit(practice_id) is not None:
        raise ApiError("ERR_PERMIT_ALREADY_OPEN")

    permit = new_record({
        "practice_id": practice_id,
        "permit_level": permit_level,
        "applied_on": applied_on,
        "status": "APPLIED",
        "issued_at": None,
        "expires_at": None,
        "required_drill_types": required_drill_types(permit_level),
        "drill_compliance_ratio": 0.0,
        "probation_count": 0,
        "remediation_deadline_at": None,
        "last_enforcement_reason": None,
    })
    db.permits[permit["id"]] = permit
    refresh_permit_ratio(permit)
    recompute_privilege(practice)
    return send(permit, 201)


@bp.get("/anesthesia-permits/<permit_id>")
def read_permit(permit_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.permits, permit_id))


@bp.get("/anesthesia-permits")
def list_permits():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    status = q_enum("status", PERMIT_STATUSES)
    rows = ordered([p for p in db.permits.values()
                    if (practice_id is None or p["practice_id"] == practice_id)
                    and (status is None or p["status"] == status)])
    return send_list(rows)


@bp.post("/anesthesia-permits/<permit_id>/remediation")
def remediate_permit(permit_id):
    authorize("PracticeAdministrator")
    permit = path_row(db.permits, permit_id)
    read_body(required=("attestation_note",))

    if permit["status"] != "PROBATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    deadline = permit.get("remediation_deadline_at")
    if deadline and clock_dt() > parse_date(deadline):
        raise ApiError("ERR_REMEDIATION_WINDOW_EXPIRED")
    ratio = refresh_permit_ratio(permit)
    if ratio < DRILL_COMPLIANCE_FLOOR:
        raise ApiError("ERR_DRILL_COMPLIANCE_LAPSED")

    practice = get_practice(permit["practice_id"])
    to_active(permit, practice, stamp=False)
    touch_practice(practice)
    return send(permit)


# --------------------------------------------------------- inspections ------

@bp.post("/facility-inspections")
def create_inspection():
    authorize("PracticeAdministrator")
    body = read_body(required=("permit_id", "scheduled_for"))
    permit_id = v_id(body, "permit_id")
    scheduled_for = v_instant(body, "scheduled_for")
    moment = parse_date(scheduled_for)
    if moment <= clock_dt():
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'scheduled_for' must be strictly later than the logical clock.")

    permit = referenced_row(db.permits, permit_id)
    if permit["status"] not in ("APPLIED", "ACTIVE", "PROBATION", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for row in db.inspections.values():
        if row["permit_id"] == permit_id and row["status"] == "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    inspection = new_record({
        "permit_id": permit_id,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "minor_deficiency_count": 0,
        "major_deficiency_count": 0,
        "critical_deficiency_count": 0,
        "inspection_score": None,
        "outcome_recorded_at": None,
    })
    db.inspections[inspection["id"]] = inspection

    if permit["status"] == "APPLIED":
        permit["status"] = "INSPECTION_PENDING"
        touch(permit)
        practice = get_practice(permit["practice_id"])
        if practice is not None:
            recompute_privilege(practice)
    return send(inspection, 201)


@bp.get("/facility-inspections/<inspection_id>")
def read_inspection(inspection_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.inspections, inspection_id))


@bp.get("/facility-inspections")
def list_inspections():
    authorize(*ALL_ROLES)
    permit_id = q_string("permit_id")
    status = q_enum("status", INSPECTION_STATUSES)
    rows = ordered([i for i in db.inspections.values()
                    if (permit_id is None or i["permit_id"] == permit_id)
                    and (status is None or i["status"] == status)])
    return send_list(rows)


@bp.post("/facility-inspections/<inspection_id>/result")
def post_inspection_result(inspection_id):
    authorize("PracticeAdministrator")
    inspection = path_row(db.inspections, inspection_id)
    body = read_body(required=("minor_deficiency_count", "major_deficiency_count",
                               "critical_deficiency_count"))
    minor = v_int(body, "minor_deficiency_count", minimum=0)
    major = v_int(body, "major_deficiency_count", minimum=0)
    critical = v_int(body, "critical_deficiency_count", minimum=0)

    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if clock_dt() < parse_date(inspection["scheduled_for"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    score = max(0, 100 - (2 * minor) - (7 * major) - (25 * critical))
    if critical > 0:
        outcome = "FAILED_CRITICAL"
    elif score >= 70:
        outcome = "PASSED"
    else:
        outcome = "FAILED_CORRECTABLE"

    inspection["minor_deficiency_count"] = minor
    inspection["major_deficiency_count"] = major
    inspection["critical_deficiency_count"] = critical
    inspection["inspection_score"] = score
    inspection["status"] = outcome
    inspection["outcome_recorded_at"] = clock_str()
    touch(inspection)

    permit = db.permits.get(inspection["permit_id"])
    if permit is not None:
        practice = get_practice(permit["practice_id"])
        ratio = refresh_permit_ratio(permit)
        _apply_permit_branch(permit, practice, outcome, ratio)
        if practice is not None:
            recompute_privilege(practice)
            touch_practice(practice)
    return send(inspection)


def _apply_permit_branch(permit, practice, outcome, ratio):
    status = permit["status"]
    if status == "INSPECTION_PENDING":
        if outcome == "PASSED":
            if ratio >= DRILL_COMPLIANCE_FLOOR:
                to_active(permit, practice)
            else:
                to_probation(permit, practice, "DRILL_LAPSE", stamp=True)
        elif outcome == "FAILED_CORRECTABLE":
            to_applied(permit, practice, "DEFICIENCY_SCORE")
        else:
            if not permit.get("issued_at"):
                to_revoked(permit, practice, "CRITICAL_DEFICIENCY")
            else:
                to_suspended(permit, practice, "CRITICAL_DEFICIENCY")
    elif status == "ACTIVE":
        if outcome == "FAILED_CRITICAL":
            to_suspended(permit, practice, "CRITICAL_DEFICIENCY")
        elif outcome == "FAILED_CORRECTABLE":
            to_probation(permit, practice, "DEFICIENCY_SCORE")
    elif status == "PROBATION":
        if outcome == "FAILED_CRITICAL":
            to_suspended(permit, practice, "CRITICAL_DEFICIENCY")
    elif status == "SUSPENDED":
        if outcome == "PASSED" and ratio >= DRILL_COMPLIANCE_FLOOR:
            to_active(permit, practice, stamp=False)


# -------------------------------------------------------------- drills ------

@bp.post("/emergency-drills")
def create_drill():
    authorize("PracticeAdministrator", "AnesthesiaCoordinator")
    body = read_body(
        required=("practice_id", "drill_type", "conducted_at", "participant_staff_ids"),
        optional=("deficiency_noted",),
    )
    practice_id = v_id(body, "practice_id")
    drill_type = v_enum(body, "drill_type", DRILL_TYPES)
    conducted_at = v_instant(body, "conducted_at")
    v_not_after(conducted_at, "conducted_at", clock_dt())
    participants = body["participant_staff_ids"]
    if not isinstance(participants, list) or len(participants) < 2:
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'participant_staff_ids' must list at least two staff members.")
    for entry in participants:
        if not isinstance(entry, str) or entry.strip() == "":
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "Field 'participant_staff_ids' must contain identifier strings.")
    deficiency_noted = body.get("deficiency_noted", False)
    if not isinstance(deficiency_noted, bool):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "Field 'deficiency_noted' must be a boolean.")

    practice = referenced_row(db.practices, practice_id)
    for entry in participants:
        staff = referenced_row(db.staff, entry)
        scope_check(staff["practice_id"], practice_id)

    drill = new_record({
        "practice_id": practice_id,
        "drill_type": drill_type,
        "conducted_at": conducted_at,
        "participant_staff_ids": list(participants),
        "deficiency_noted": deficiency_noted,
    }, immutable=True)
    db.drills[drill["id"]] = drill

    permit = open_permit(practice_id)
    if permit is not None:
        refresh_permit_ratio(permit)
        touch(permit)
    return send(drill, 201)


@bp.get("/emergency-drills/<drill_id>")
def read_drill(drill_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.drills, drill_id))


@bp.get("/emergency-drills")
def list_drills():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    drill_type = q_enum("drill_type", DRILL_TYPES)
    deficiency_noted = q_bool("deficiency_noted")
    rows = [d for d in db.drills.values()
            if (practice_id is None or d["practice_id"] == practice_id)
            and (drill_type is None or d["drill_type"] == drill_type)
            and (deficiency_noted is None or bool(d["deficiency_noted"]) == deficiency_noted)]
    rows.sort(key=lambda d: (parse_date(d["conducted_at"]), d["created_at"], d["_seq"]))
    return send_list(rows)
