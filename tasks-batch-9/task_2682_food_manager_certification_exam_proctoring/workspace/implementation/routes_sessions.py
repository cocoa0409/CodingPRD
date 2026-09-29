"""Exam sessions: scheduling, re-timing, proctor attachment and delivery day."""
from datetime import timedelta

from flask import Blueprint

import authz
import calc
import cascade
import validation as V
from authz import require, find, maybe, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

sessions_bp = Blueprint("sessions", __name__)


def _session_scope(session, user_id, role, acting=False):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_session(session) != user_id:
        deny_scope()
    if role == authz.CANDIDATE and session["candidate_id"] != user_id:
        deny_scope()
    if role == authz.PROCTOR:
        if session["proctor_id"] is None:
            if not acting:
                deny_scope()
        elif session["proctor_id"] != user_id:
            deny_scope()


def _jurisdiction_of(candidate):
    return store.jurisdictions.get(candidate["jurisdiction_id"])


def _check_acceptance(jurisdiction, form, delivery_mode):
    if jurisdiction is None:
        return
    if form["accreditation_body"] not in \
            jurisdiction["accepted_accreditation_bodies"]:
        raise ApiError("ERR_ACCREDITATION_NOT_ACCEPTED",
                       "the jurisdiction does not accept that accreditation body")
    if form["language"] not in jurisdiction["accepted_languages"]:
        raise ApiError("ERR_LANGUAGE_NOT_ACCEPTED",
                       "the jurisdiction does not accept that exam language")
    if delivery_mode == "REMOTE" and not jurisdiction["accepts_remote_proctoring"]:
        raise ApiError("ERR_REMOTE_PROCTORING_NOT_ACCEPTED",
                       "the jurisdiction does not accept remote proctoring")


def _check_capability(proctor, site, form, delivery_mode):
    if proctor is not None:
        if form["language"] not in proctor["languages_certified"]:
            raise ApiError("ERR_PROCTOR_LANGUAGE_NOT_CERTIFIED",
                           "the proctor is not certified in the form's language")
        if delivery_mode == "REMOTE" and not proctor["remote_certified"]:
            raise ApiError("ERR_PROCTOR_NOT_REMOTE_CERTIFIED",
                           "the proctor is not remote-certified")
    if delivery_mode == "IN_PERSON" and site is not None:
        if form["language"] not in site["languages_supported"]:
            raise ApiError("ERR_SITE_LANGUAGE_UNSUPPORTED",
                           "the site cannot deliver the form's language")
    if delivery_mode == "IN_PERSON" and site is None:
        raise ApiError("ERR_SITE_REQUIRED_FOR_IN_PERSON",
                       "an in-person sitting requires a testing_site_id")
    if delivery_mode == "REMOTE" and site is not None:
        raise ApiError("ERR_SITE_REQUIRED_FOR_IN_PERSON",
                       "a remote sitting must not carry a testing_site_id")


def _check_lead_time(start_at):
    if start_at - store.clock < timedelta(minutes=calc.LEAD_TIME_MINUTES):
        raise ApiError("ERR_SCHEDULE_LEAD_TIME_TOO_SHORT",
                       "the sitting must start at least 1440 minutes from now")


@sessions_bp.post("/exam-sessions")
def create_session():
    user_id, role = require(authz.PROVIDER_ADMIN)
    body = V.get_body()
    candidate_id = V.req_id(body, "candidate_id")
    form_id = V.req_id(body, "exam_form_id")
    code_id = V.req_id(body, "access_code_id")
    delivery_mode = V.req_enum(body, "delivery_mode", V.DELIVERY_MODES)
    start_at = V.req_datetime(body, "scheduled_start_at")
    site_id = V.opt_id(body, "testing_site_id", None)
    proctor_id = V.opt_id(body, "proctor_id", None)
    accommodation_id = V.opt_id(body, "accommodation_request_id", None)

    candidate = find("candidate", candidate_id)
    if candidate["training_provider_id"] != user_id:
        deny_scope()
    form = find("exam_form", form_id)
    code = find("code", code_id)
    site = find("testing_site", site_id) if site_id is not None else None
    proctor = find("proctor", proctor_id) if proctor_id is not None else None
    accommodation = find("accommodation", accommodation_id) \
        if accommodation_id is not None else None

    if code["status"] != "ASSIGNED":
        raise ApiError("ERR_ACCESS_CODE_STATE_INVALID",
                       "the access code is not ASSIGNED")
    if form["status"] != "ACTIVE":
        raise ApiError("ERR_EXAM_FORM_RETIRED",
                       "no new sitting may be scheduled on a retired form")
    if candidate["security_hold"]:
        raise ApiError("ERR_CANDIDATE_SECURITY_HOLD",
                       "the candidate is under a security hold")
    if proctor is not None and proctor["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PROCTOR_NOT_REGISTERED",
                       "the proctor is not REGISTERED")
    _check_acceptance(_jurisdiction_of(candidate), form, delivery_mode)
    if code["candidate_id"] != candidate_id:
        raise ApiError("ERR_ACCESS_CODE_CANDIDATE_MISMATCH",
                       "the access code belongs to another candidate")
    batch = store.batches.get(code["batch_id"])
    if batch is None or batch["exam_form_id"] != form_id:
        raise ApiError("ERR_ACCESS_CODE_FORM_MISMATCH",
                       "the access code was bought for another exam form")
    if accommodation is not None:
        if accommodation["candidate_id"] != candidate_id \
                or accommodation["status"] not in ("UNDER_REVIEW", "APPROVED"):
            raise ApiError("ERR_ACCOMMODATION_CANDIDATE_MISMATCH",
                           "the accommodation is not usable for this candidate")
    _check_capability(proctor, site, form, delivery_mode)
    _check_lead_time(start_at)

    minutes = calc.compute_allowed_minutes(form, accommodation, delivery_mode)
    end_at = start_at + timedelta(minutes=minutes)
    calc.check_occupancy(proctor_id, site_id if delivery_mode == "IN_PERSON"
                         else None, start_at, end_at, None)

    row = store.base()
    row.update({
        "candidate_id": candidate_id,
        "exam_form_id": form_id,
        "access_code_id": code_id,
        "testing_site_id": site_id,
        "proctor_id": proctor_id,
        "accommodation_request_id": accommodation_id,
        "delivery_mode": delivery_mode,
        "scheduled_start_at": start_at,
        "allowed_minutes": minutes,
        "scheduled_end_at": end_at,
        "session_status": "SCHEDULED",
        "proctoring_status": "ASSIGNED" if proctor_id else "PENDING_ASSIGNMENT",
        "id_document_type": None,
        "id_document_expires_on": None,
        "biometric_match_score": None,
        "proctor_attestation": False,
        "identity_verified_at": None,
        "checked_in_at": None,
        "started_at": None,
        "submitted_at": None,
        "reschedule_count": 0,
    })
    store.sessions[row["id"]] = row
    cascade.reserve_interval(row, minutes)
    return ok(row, 201)


@sessions_bp.get("/exam-sessions/<session_id>")
def read_session(session_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.PROCTOR, authz.CANDIDATE)
    session = find("session", session_id)
    _session_scope(session, user_id, role)
    return ok(session)


@sessions_bp.get("/exam-sessions")
def list_sessions():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.PROCTOR)
    candidate_filter = V.query_id("candidate_id")
    form_filter = V.query_id("exam_form_id")
    code_filter = V.query_id("access_code_id")
    site_filter = V.query_id("testing_site_id")
    proctor_filter = V.query_id("proctor_id")
    accommodation_filter = V.query_id("accommodation_request_id")
    session_status = V.query_enum("session_status", V.SESSION_STATUS)
    proctoring_status = V.query_enum("proctoring_status", V.PROCTORING_STATUS)
    if role == authz.PROCTOR:
        proctor_filter = scoped_filter(proctor_filter, user_id)
    rows = [r for r in store.sessions.values()
            if match(r, "candidate_id", candidate_filter)
            and match(r, "exam_form_id", form_filter)
            and match(r, "access_code_id", code_filter)
            and match(r, "testing_site_id", site_filter)
            and match(r, "proctor_id", proctor_filter)
            and match(r, "accommodation_request_id", accommodation_filter)
            and match(r, "session_status", session_status)
            and match(r, "proctoring_status", proctoring_status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows if authz.provider_of_session(r) == user_id]
    return paged(rows)


@sessions_bp.post("/exam-sessions/<session_id>/reschedule")
def reschedule_session(session_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    session = find("session", session_id)
    _session_scope(session, user_id, role)
    body = V.get_body()
    start_at = V.req_datetime(body, "scheduled_start_at")
    expected_version = V.req_int(body, "expected_session_version")
    new_mode = V.opt_enum(body, "delivery_mode", V.DELIVERY_MODES,
                          session["delivery_mode"])
    site_supplied = "testing_site_id" in body
    site_id = V.opt_id(body, "testing_site_id", None)
    proctor_supplied = "proctor_id" in body
    proctor_id = V.opt_id(body, "proctor_id", None)

    if not site_supplied:
        site_id = session["testing_site_id"] if new_mode == "IN_PERSON" else None
    if not proctor_supplied:
        proctor_id = session["proctor_id"]

    site = find("testing_site", site_id) if site_id is not None else None
    proctor = find("proctor", proctor_id) if proctor_id is not None else None

    if expected_version != session["version"]:
        raise ApiError("ERR_STALE_SESSION_VERSION",
                       "expected_session_version does not match the sitting")
    if session["session_status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED sitting may be re-timed")
    candidate = store.candidates.get(session["candidate_id"])
    if candidate is not None and candidate["security_hold"]:
        raise ApiError("ERR_CANDIDATE_SECURITY_HOLD",
                       "the candidate is under a security hold")
    if proctor is not None and proctor["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PROCTOR_NOT_REGISTERED",
                       "the proctor is not REGISTERED")
    form = store.exam_forms.get(session["exam_form_id"])
    jurisdiction = _jurisdiction_of(candidate) if candidate else None
    if new_mode == "REMOTE" and jurisdiction is not None \
            and not jurisdiction["accepts_remote_proctoring"]:
        raise ApiError("ERR_REMOTE_PROCTORING_NOT_ACCEPTED",
                       "the jurisdiction does not accept remote proctoring")
    _check_capability(proctor, site, form, new_mode)
    _check_lead_time(start_at)

    accommodation = maybe("accommodation", session["accommodation_request_id"])
    minutes = calc.compute_allowed_minutes(form, accommodation, new_mode)
    end_at = start_at + timedelta(minutes=minutes)
    calc.check_occupancy(proctor_id, site_id, start_at, end_at, session["id"])

    outgoing = store.proctors.get(session["proctor_id"]) \
        if session["proctor_id"] else None
    cascade.release_interval(session, session["allowed_minutes"])
    session["delivery_mode"] = new_mode
    session["testing_site_id"] = site_id
    session["proctor_id"] = proctor_id
    session["scheduled_start_at"] = start_at
    session["allowed_minutes"] = minutes
    session["scheduled_end_at"] = end_at
    session["reschedule_count"] += 1
    if proctor_id is not None \
            and session["proctoring_status"] in ("PENDING_REPROCTOR",
                                                 "PENDING_ASSIGNMENT"):
        session["proctoring_status"] = "ASSIGNED"
    cascade.reserve_interval(session, minutes)
    if outgoing is not None:
        store.touch(outgoing)
    store.touch(session)
    return ok(session)


@sessions_bp.post("/exam-sessions/<session_id>/proctor-assignment")
def assign_proctor(session_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    session = find("session", session_id)
    _session_scope(session, user_id, role)
    body = V.get_body()
    proctor_id = V.req_id(body, "proctor_id")
    proctor = find("proctor", proctor_id)
    if session["session_status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED sitting may take a proctor")
    if proctor["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PROCTOR_NOT_REGISTERED",
                       "the proctor is not REGISTERED")
    form = store.exam_forms.get(session["exam_form_id"])
    if form["language"] not in proctor["languages_certified"]:
        raise ApiError("ERR_PROCTOR_LANGUAGE_NOT_CERTIFIED",
                       "the proctor is not certified in the form's language")
    if session["delivery_mode"] == "REMOTE" and not proctor["remote_certified"]:
        raise ApiError("ERR_PROCTOR_NOT_REMOTE_CERTIFIED",
                       "the proctor is not remote-certified")
    calc.check_occupancy(proctor_id, None, session["scheduled_start_at"],
                         session["scheduled_end_at"], session["id"])
    outgoing = store.proctors.get(session["proctor_id"]) \
        if session["proctor_id"] else None
    if outgoing is not None and outgoing["id"] != proctor_id:
        outgoing["reserved_minutes"] -= session["allowed_minutes"]
        store.touch(outgoing)
    if outgoing is None or outgoing["id"] != proctor_id:
        proctor["reserved_minutes"] += session["allowed_minutes"]
        store.touch(proctor)
    session["proctor_id"] = proctor_id
    session["proctoring_status"] = "ASSIGNED"
    store.touch(session)
    return ok(session)


@sessions_bp.post("/exam-sessions/<session_id>/check-in")
def check_in(session_id):
    user_id, role = require(authz.PROCTOR)
    session = find("session", session_id)
    _session_scope(session, user_id, role, acting=True)
    body = V.get_body()
    document_type = V.req_enum(body, "id_document_type", V.ID_DOCUMENT_TYPES)
    expires_on = V.req_date_string(body, "id_document_expires_on")
    biometric = V.opt_int(body, "biometric_match_score", 0, 100, None)
    attestation = V.opt_bool(body, "proctor_attestation", None)

    if session["session_status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED sitting may check in")
    candidate = store.candidates.get(session["candidate_id"])
    if candidate is not None and candidate["security_hold"]:
        raise ApiError("ERR_CANDIDATE_SECURITY_HOLD",
                       "the candidate is under a security hold")
    if expires_on < store.clock.date().isoformat():
        raise ApiError("ERR_ID_DOCUMENT_EXPIRED",
                       "the presented identity document has expired")
    if session["delivery_mode"] == "REMOTE":
        if biometric is None:
            raise ApiError("ERR_BIOMETRIC_REQUIRED_FOR_REMOTE",
                           "a remote check-in requires biometric_match_score")
        if biometric < calc.BIOMETRIC_MIN_SCORE:
            raise ApiError("ERR_IDENTITY_VERIFICATION_FAILED",
                           "the biometric score is below the minimum")
    else:
        cleared = bool(attestation) or (biometric is not None
                                        and biometric >= calc.BIOMETRIC_MIN_SCORE)
        if not cleared:
            raise ApiError("ERR_IDENTITY_VERIFICATION_FAILED",
                           "identity could not be verified")
    code = store.codes.get(session["access_code_id"])
    if code is not None and code["bundle_type"] != "EXAM_ONLY" \
            and code["course_completed_at"] is None:
        raise ApiError("ERR_COURSE_NOT_COMPLETED",
                       "the bundled course has not been signed off")
    if session["proctoring_status"] != "ASSIGNED":
        raise ApiError("ERR_SESSION_PROCTOR_UNASSIGNED",
                       "no proctor is currently attached to the sitting")
    opens_at = session["scheduled_start_at"] \
        - timedelta(minutes=calc.CHECKIN_OPENS_MINUTES)
    closes_at = session["scheduled_start_at"] \
        + timedelta(minutes=calc.CHECKIN_CLOSES_MINUTES)
    if store.clock < opens_at or store.clock > closes_at:
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED",
                       "the check-in window is not open")

    session["session_status"] = "CHECKED_IN"
    session["id_document_type"] = document_type
    session["id_document_expires_on"] = expires_on
    session["biometric_match_score"] = biometric
    if attestation is not None:
        session["proctor_attestation"] = attestation
    session["identity_verified_at"] = store.clock
    session["checked_in_at"] = store.clock
    store.touch(session)
    return ok(session)


@sessions_bp.post("/exam-sessions/<session_id>/start")
def start_session(session_id):
    user_id, role = require(authz.PROCTOR)
    session = find("session", session_id)
    _session_scope(session, user_id, role, acting=True)
    V.get_body()
    if session["session_status"] != "CHECKED_IN" \
            or session["identity_verified_at"] is None:
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a CHECKED_IN sitting may be released")
    if session["proctoring_status"] != "ASSIGNED":
        raise ApiError("ERR_SESSION_PROCTOR_UNASSIGNED",
                       "no proctor is currently attached to the sitting")
    session["session_status"] = "IN_PROGRESS"
    session["started_at"] = store.clock
    store.touch(session)
    return ok(session)


def effective_cut_score(form, jurisdiction):
    national = form["national_cut_score"]
    if jurisdiction is None:
        return national
    override = jurisdiction["min_passing_score_override"]
    if override is None:
        return national
    return max(national, override)


@sessions_bp.post("/exam-sessions/<session_id>/submission")
def submit_session(session_id):
    user_id, role = require(authz.PROCTOR)
    session = find("session", session_id)
    _session_scope(session, user_id, role, acting=True)
    form = store.exam_forms.get(session["exam_form_id"])
    body = V.get_body()
    scored_correct = V.req_int(body, "scored_correct_count", 0,
                               form["scored_item_count"] if form else None)
    attestation = V.req_bool(body, "proctor_attestation")
    pretest_correct = V.opt_int(body, "pretest_correct_count", 0,
                                form["pretest_item_count"] if form else None, 0)
    if session["session_status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only an IN_PROGRESS sitting may be submitted")
    if session["proctoring_status"] != "ASSIGNED":
        raise ApiError("ERR_SESSION_PROCTOR_UNASSIGNED",
                       "no proctor is currently attached to the sitting")

    session["session_status"] = "SUBMITTED"
    session["submitted_at"] = store.clock
    session["proctor_attestation"] = attestation
    if attestation:
        session["proctoring_status"] = "ATTESTED"
    store.touch(session)

    code = store.codes.get(session["access_code_id"])
    if code is not None and code["status"] == "ASSIGNED":
        code["status"] = "CONSUMED"
        code["consumed_at"] = store.clock
        store.touch(code)
        batch = store.batches.get(code["batch_id"])
        if batch is not None:
            cascade.recount_batch(batch)
            store.touch(batch)

    proctor = store.proctors.get(session["proctor_id"]) \
        if session["proctor_id"] else None
    if proctor is not None:
        proctor["proctored_session_count"] += 1
        store.touch(proctor)

    candidate = store.candidates.get(session["candidate_id"])
    jurisdiction = _jurisdiction_of(candidate) if candidate else None
    report = store.base()
    report.update({
        "exam_session_id": session["id"],
        "exam_form_id": session["exam_form_id"],
        "raw_correct_count": scored_correct,
        "pretest_correct_count": pretest_correct,
        "voided_item_count": 0,
        "voided_correct_count": 0,
        "provisional_scaled_score": calc.scaled_score(
            scored_correct, form["scored_item_count"]),
        "final_scaled_score": None,
        "effective_cut_score": effective_cut_score(form, jurisdiction),
        "pass_flag": None,
        "status": "PROVISIONAL",
        "finalized_by_user_id": None,
        "released_at": None,
    })
    store.score_reports[report["id"]] = report
    return ok(report, 201)


@sessions_bp.post("/exam-sessions/<session_id>/cancellation")
def cancel_session(session_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    session = find("session", session_id)
    _session_scope(session, user_id, role)
    body = V.get_body()
    V.req_str(body, "reason", 1)
    if session["session_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED or CHECKED_IN sitting may be cancelled")
    cascade.release_interval(session, session["allowed_minutes"])
    session["session_status"] = "CANCELLED"
    session["proctoring_status"] = "CLEARED"
    store.touch(session)
    code = store.codes.get(session["access_code_id"])
    if code is not None and code["status"] == "ASSIGNED":
        code["status"] = "AVAILABLE"
        code["candidate_id"] = None
        code["assigned_at"] = None
        code["assignment_release_count"] += 1
        store.touch(code)
        batch = store.batches.get(code["batch_id"])
        if batch is not None:
            cascade.recount_batch(batch)
            if batch["available_count"] > 0 and batch["status"] == "DEPLETED":
                batch["status"] = "ACTIVE"
            store.touch(batch)
    return ok(session)
