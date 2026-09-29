"""Organization recognitions, representatives and accreditations (PRD 3.5)."""

import datetime

from flask import Blueprint, request

import auth
import calc
import cascades
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("authority", __name__)

CONDITIONAL_REASONS = ("ANNUAL_REPORT_LATE", "STAFFING_DEFICIENCY", "COMPLAINT_UNDER_REVIEW")
DENY_REASONS = ("TRAINING_INCOMPLETE", "BACKGROUND_ADVERSE")
REVOKE_REASONS = ("CONDUCT_VIOLATION", "VOLUNTARY_SURRENDER")


# --------------------------------------------------------------------------
# organization recognitions
# --------------------------------------------------------------------------

@bp.post("/organization-recognitions")
@auth.requires("ProgramDirector")
def create_recognition():
    payload = v.body()
    number = v.as_str(payload, "recognition_number", min_len=1, max_len=40)
    effective = v.as_date(payload, "effective_date")
    expiry = v.as_date(payload, "expiry_date")
    forums = v.as_str_list(payload, "authorized_forums", allowed=calc.FORUMS)
    if expiry <= effective:
        v.bad("expiry_date must be strictly after effective_date.")
    for existing in store.db["recognitions"].values():
        if existing.get("recognition_number") == number:
            raise ApiError("ERR_RECOGNITION_ALREADY_EXISTS",
                           "recognition_number is already registered.")
    row = store.new_row({
        "recognition_number": number,
        "effective_date": effective.isoformat(),
        "expiry_date": expiry.isoformat(),
        "authorized_forums": list(forums),
        "status": "ACTIVE",
        "conditional_reason_code": None,
        "suspended_accreditation_count": 0,
        "lapsed_at_utc": None,
    })
    store.insert("recognitions", row)
    return response.created(serialize.recognition(row))


@bp.get("/organization-recognitions")
@auth.requires("ProgramDirector", "SupervisingAttorney", "GrantAnalyst")
def list_recognitions():
    rows = store.rows("recognitions")
    args = request.args
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.recognition(r) for r in page], meta)


@bp.get("/organization-recognitions/<recognition_id>")
@auth.requires("ProgramDirector", "SupervisingAttorney", "GrantAnalyst")
def read_recognition(recognition_id):
    row = store.get("recognitions", recognition_id)
    if row is None:
        raise ApiError("ERR_RECOGNITION_NOT_FOUND")
    return response.ok(serialize.recognition(row))


@bp.post("/organization-recognitions/<recognition_id>/transition")
@auth.requires("ProgramDirector")
def transition_recognition(recognition_id):
    row = store.get("recognitions", recognition_id)
    if row is None:
        raise ApiError("ERR_RECOGNITION_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", ("CONDITION", "REINSTATE", "LAPSE", "WITHDRAW"))
    status = row["status"]

    if action == "CONDITION":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CONDITION is only legal from ACTIVE.")
        reason = v.as_enum(payload, "conditional_reason_code", CONDITIONAL_REASONS)
        row["status"] = "CONDITIONAL"
        row["conditional_reason_code"] = reason
        store.touch(row)
    elif action == "REINSTATE":
        if status not in ("CONDITIONAL", "LAPSED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REINSTATE is only legal from CONDITIONAL or LAPSED.")
        expiry = store.parse_date(row["expiry_date"])
        if expiry is not None and store.clock_date() > expiry:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The recognition term has already expired.")
        was_lapsed = status == "LAPSED"
        row["status"] = "ACTIVE"
        row["conditional_reason_code"] = None
        if was_lapsed:
            # PRD 3.5: "from LAPSED it additionally clears lapsed_at_utc".
            row["lapsed_at_utc"] = None
        store.touch(row)
        if was_lapsed:
            cascades.recognition_reinstate(row)
    elif action == "LAPSE":
        if status not in ("ACTIVE", "CONDITIONAL"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "LAPSE is only legal from ACTIVE or CONDITIONAL.")
        cascades.recognition_lapse(row)
    else:
        if status not in ("ACTIVE", "CONDITIONAL", "LAPSED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "WITHDRAW is only legal from ACTIVE, CONDITIONAL or LAPSED.")
        row["status"] = "WITHDRAWN"
        store.touch(row)
    return response.ok(serialize.recognition(row))


# --------------------------------------------------------------------------
# representatives
# --------------------------------------------------------------------------

@bp.post("/representatives")
@auth.requires("ProgramDirector")
def create_representative():
    payload = v.body()
    full_name = v.as_str(payload, "full_name", min_len=1, max_len=120)
    rep_type = v.as_enum(payload, "rep_type", calc.REP_TYPES)
    languages = v.as_str_list(payload, "languages")
    max_case_load = v.as_int(payload, "max_case_load", minimum=0)
    max_supervisees = v.as_int(payload, "max_supervisees", minimum=0)
    capacity = v.as_decimal(payload, "weekly_capacity_hours", exclusive_min=0, places=2)
    bar_number = v.as_str(payload, "bar_number", required=False, min_len=1, default=None)
    credential = v.as_date(payload, "facility_access_credential_expires_on",
                           required=False, default=None)
    if rep_type == "STAFF_ATTORNEY" and bar_number is None:
        v.bad("bar_number is required for a STAFF_ATTORNEY.")
    if rep_type != "STAFF_ATTORNEY" and bar_number is not None:
        v.bad("bar_number is only permitted for a STAFF_ATTORNEY.")
    row = store.new_row({
        "full_name": full_name,
        "rep_type": rep_type,
        "bar_number": bar_number,
        "languages": list(languages),
        "max_case_load": max_case_load,
        "max_supervisees": max_supervisees,
        "weekly_capacity_hours": capacity,
        "active_case_load": 0,
        "supervisee_count": 0,
        "facility_access_credential_expires_on":
            credential.isoformat() if credential else None,
        "status": "ACTIVE",
    })
    store.insert("representatives", row)
    return response.created(serialize.representative(row))


@bp.get("/representatives")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative")
def list_representatives():
    rows = store.rows("representatives")
    args = request.args
    if args.get("rep_type"):
        rows = [r for r in rows if r["rep_type"] == args["rep_type"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    if args.get("authorization_status"):
        rows = [r for r in rows
                if calc.authorization_status(r) == args["authorization_status"]]
    if args.get("language_code"):
        rows = [r for r in rows if args["language_code"] in (r.get("languages") or [])]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.representative(r) for r in page], meta)


@bp.get("/representatives/<representative_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative")
def read_representative(representative_id):
    row = store.get("representatives", representative_id)
    if row is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    return response.ok(serialize.representative(row))


@bp.patch("/representatives/<representative_id>")
@auth.requires("ProgramDirector")
def update_representative(representative_id):
    row = store.get("representatives", representative_id)
    if row is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    payload = v.body()
    if v.present(payload, "languages"):
        row["languages"] = list(v.as_str_list(payload, "languages"))
    if v.present(payload, "max_case_load"):
        row["max_case_load"] = v.as_int(payload, "max_case_load", minimum=0)
    if v.present(payload, "max_supervisees"):
        row["max_supervisees"] = v.as_int(payload, "max_supervisees", minimum=0)
    if v.present(payload, "weekly_capacity_hours"):
        row["weekly_capacity_hours"] = v.as_decimal(
            payload, "weekly_capacity_hours", exclusive_min=0, places=2)
    if v.present(payload, "facility_access_credential_expires_on"):
        parsed = v.as_date(payload, "facility_access_credential_expires_on")
        row["facility_access_credential_expires_on"] = parsed.isoformat()
    if v.present(payload, "status"):
        row["status"] = v.as_enum(payload, "status", ("ACTIVE", "INACTIVE", "SUSPENDED"))
    store.touch(row)
    return response.ok(serialize.representative(row))


# --------------------------------------------------------------------------
# accreditations
# --------------------------------------------------------------------------

@bp.post("/accreditations")
@auth.requires("ProgramDirector", "SupervisingAttorney")
def create_accreditation():
    payload = v.body()
    rep_id = v.as_id(payload, "representative_id")
    recognition_id = v.as_id(payload, "recognition_id")
    rep = store.get("representatives", rep_id)
    if rep is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    recognition = store.get("recognitions", recognition_id)
    if recognition is None:
        raise ApiError("ERR_RECOGNITION_NOT_FOUND")
    accreditation_type = v.as_enum(payload, "accreditation_type", ("PARTIAL", "FULL"))
    requested = v.as_str_list(payload, "requested_forums", allowed=calc.FORUMS)
    if recognition["status"] not in calc.ACTIVE_RECOGNITION_STATUSES:
        raise ApiError("ERR_RECOGNITION_NOT_ACTIVE",
                       "The recognition must be ACTIVE or CONDITIONAL.")
    if rep["rep_type"] == "STAFF_ATTORNEY":
        raise ApiError("ERR_ACCREDITATION_NOT_APPLICABLE",
                       "A STAFF_ATTORNEY does not take accreditation.")
    row = store.new_row({
        "representative_id": rep_id,
        "recognition_id": recognition_id,
        "approved_by_representative_id": None,
        "accreditation_type": accreditation_type,
        "requested_forums": list(requested),
        "authorized_forums": [],
        "status": "PENDING",
        "effective_date": None,
        "expiry_date": None,
        "renewal_round": 0,
        "decision_reason_code": None,
    })
    store.insert("accreditations", row)
    return response.created(serialize.accreditation(row))


@bp.get("/accreditations")
@auth.requires("ProgramDirector", "SupervisingAttorney", "GrantAnalyst")
def list_accreditations():
    rows = store.rows("accreditations")
    args = request.args
    for key in ("representative_id", "recognition_id", "approved_by_representative_id",
                "status", "accreditation_type"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.accreditation(r) for r in page], meta)


@bp.get("/accreditations/<accreditation_id>")
@auth.requires("ProgramDirector", "SupervisingAttorney", "GrantAnalyst")
def read_accreditation(accreditation_id):
    row = store.get("accreditations", accreditation_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The accreditation does not exist.")
    return response.ok(serialize.accreditation(row))


def _grant_forums(row, recognition, requested):
    granted = calc.forum_grant(requested, recognition, row["accreditation_type"])
    if not granted:
        raise ApiError("ERR_FORUM_GRANT_EMPTY",
                       "The requested forums intersect to the empty set.")
    return granted


@bp.post("/accreditations/<accreditation_id>/transition")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def transition_accreditation(accreditation_id):
    row = store.get("accreditations", accreditation_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The accreditation does not exist.")
    payload = v.body()
    action = v.as_enum(payload, "action", ("APPROVE", "DENY", "REVOKE"))
    status = row["status"]

    if action in ("APPROVE", "REVOKE") and auth.user_id() == row["representative_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A representative may not decide its own accreditation.")

    subject = store.get("representatives", row["representative_id"])
    subject_version = None if subject is None else int(subject["version"])

    if action == "APPROVE":
        if status not in ("PENDING", "RENEWAL_PENDING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "APPROVE is only legal from PENDING or RENEWAL_PENDING.")
        recognition = store.get("recognitions", row["recognition_id"])
        if recognition is None:
            raise ApiError("ERR_RECOGNITION_NOT_FOUND")
        if recognition["status"] not in calc.ACTIVE_RECOGNITION_STATUSES:
            raise ApiError("ERR_RECOGNITION_NOT_ACTIVE",
                           "The recognition must be ACTIVE or CONDITIONAL.")
        granted = _grant_forums(row, recognition, row.get("requested_forums"))
        effective = store.clock_date()
        row["authorized_forums"] = granted
        row["effective_date"] = effective.isoformat()
        row["expiry_date"] = (
            effective + datetime.timedelta(days=calc.ACCREDITATION_TERM_DAYS)
        ).isoformat()
        row["approved_by_representative_id"] = auth.user_id()
        row["decision_reason_code"] = "CREDENTIALS_VERIFIED"
        if status == "RENEWAL_PENDING":
            row["renewal_round"] = int(row.get("renewal_round") or 0) + 1
        row["status"] = "APPROVED"
        store.touch(row)
    elif action == "DENY":
        if status != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DENY is only legal from PENDING.")
        reason = v.as_enum(payload, "decision_reason_code", DENY_REASONS)
        row["status"] = "DENIED"
        row["decision_reason_code"] = reason
        store.touch(row)
    else:
        if status in ("EXPIRED", "REVOKED", "DENIED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REVOKE is not legal from a terminal state.")
        reason = v.as_enum(payload, "decision_reason_code", REVOKE_REASONS)
        row["status"] = "REVOKED"
        row["decision_reason_code"] = reason
        store.touch(row)
        cascades.release_representative_authority(row["representative_id"])
    # PRD 3.5: "Every action re-derives the representative's authorization_status
    # and advances both the accreditation's and the representative's version by 1"
    # -- exactly one advance, whichever counters a revocation cascade also moved.
    if subject is not None:
        subject["version"] = subject_version + 1
        subject["updated_at"] = store.clock_iso()
    return response.ok(serialize.accreditation(row))


@bp.post("/accreditations/<accreditation_id>/renew")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def renew_accreditation(accreditation_id):
    row = store.get("accreditations", accreditation_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The accreditation does not exist.")
    payload = v.body()
    expected = v.as_int(payload, "expected_recognition_version")
    requested = v.as_str_list(payload, "requested_forums", allowed=calc.FORUMS)
    recognition = store.get("recognitions", row["recognition_id"])
    if recognition is None:
        raise ApiError("ERR_RECOGNITION_NOT_FOUND")
    if row["status"] != "EXPIRING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Renewal is only legal from EXPIRING.")
    expiry = store.parse_date(row.get("expiry_date"))
    if expiry is not None and store.clock_date() > expiry:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The accreditation term has already expired.")
    if recognition["status"] not in calc.ACTIVE_RECOGNITION_STATUSES:
        raise ApiError("ERR_RECOGNITION_NOT_ACTIVE",
                       "The recognition must be ACTIVE or CONDITIONAL.")
    if int(recognition["version"]) != expected:
        raise ApiError("ERR_STALE_RECOGNITION_VERSION",
                       "expected_recognition_version does not match the recognition.")
    row["requested_forums"] = list(requested)
    row["status"] = "RENEWAL_PENDING"
    store.touch(row)
    store.touch(recognition)
    return response.ok(serialize.accreditation(row))
