"""Score reports, equating and certificate issuance / recertification."""
from datetime import timedelta

from flask import Blueprint

import authz
import calc
import cascade
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

scoring_bp = Blueprint("scoring", __name__)


def _report_scope(report, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_report(report) != user_id:
        deny_scope()
    if role == authz.CANDIDATE and authz.candidate_of_report(report) != user_id:
        deny_scope()


@scoring_bp.get("/score-reports/<report_id>")
def read_score_report(report_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE)
    report = find("score_report", report_id)
    _report_scope(report, user_id, role)
    return ok(report)


@scoring_bp.get("/score-reports")
def list_score_reports():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    session_filter = V.query_id("exam_session_id")
    form_filter = V.query_id("exam_form_id")
    status = V.query_enum("status", V.SCORE_REPORT_STATUS)
    rows = [r for r in store.score_reports.values()
            if match(r, "exam_session_id", session_filter)
            and match(r, "exam_form_id", form_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows if authz.provider_of_report(r) == user_id]
    return paged(rows)


@scoring_bp.post("/score-reports/<report_id>/finalization")
def finalize_score_report(report_id):
    user_id, role = require(authz.PLATFORM_ADMIN)
    report = find("score_report", report_id)
    body = V.get_body()
    voided_items = V.opt_int(body, "voided_item_count", 0, None, 0)
    voided_correct = V.opt_int(body, "voided_correct_count", 0, None, 0)
    if report["status"] != "PROVISIONAL":
        raise ApiError("ERR_SCORE_REPORT_STATE_INVALID",
                       "the score report is not PROVISIONAL")
    session = store.sessions.get(report["exam_session_id"])
    if session is None or session["session_status"] != "SUBMITTED" \
            or session["proctoring_status"] not in ("ATTESTED", "CLEARED"):
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "the sitting is not ready for score release")
    form = store.exam_forms.get(report["exam_form_id"])
    scored_items = form["scored_item_count"] if form else 0
    if voided_items >= scored_items \
            or voided_correct > voided_items \
            or voided_correct > report["raw_correct_count"]:
        raise ApiError("ERR_VOIDED_ITEM_COUNT_INVALID",
                       "the keyed-out item counts are not coherent")

    report["voided_item_count"] = voided_items
    report["voided_correct_count"] = voided_correct
    final_score = calc.scaled_score(report["raw_correct_count"] - voided_correct,
                                    scored_items - voided_items)
    report["final_scaled_score"] = final_score
    report["pass_flag"] = final_score >= report["effective_cut_score"]
    report["status"] = "FINAL"
    report["released_at"] = store.clock
    report["finalized_by_user_id"] = user_id
    store.touch(report)

    session["session_status"] = "CLOSED"
    unresolved = any(i["exam_session_id"] == session["id"]
                     and i["status"] in ("OPEN", "UNDER_REVIEW")
                     for i in store.incidents.values())
    if session["proctoring_status"] == "ATTESTED" and not unresolved:
        session["proctoring_status"] = "CLEARED"
    cascade.release_interval(session, session["allowed_minutes"])
    store.touch(session)
    return ok(report)


# --- certificates ----------------------------------------------------------

def _certificate_scope(certificate, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_certificate(certificate) != user_id:
        deny_scope()
    if role == authz.CANDIDATE and certificate["candidate_id"] != user_id:
        deny_scope()
    if role == authz.HEALTH_OFFICER \
            and certificate["jurisdiction_id"] != user_id:
        deny_scope()


@scoring_bp.post("/certificates")
def issue_certificate():
    user_id, role = require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    report_id = V.req_id(body, "score_report_id")
    report = find("score_report", report_id)
    if report["status"] != "FINAL":
        raise ApiError("ERR_SCORE_REPORT_STATE_INVALID",
                       "the score report is not FINAL")
    session = store.sessions.get(report["exam_session_id"])
    candidate = store.candidates.get(session["candidate_id"]) if session else None
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", "candidate could not be found")
    jurisdiction = store.jurisdictions.get(candidate["jurisdiction_id"])
    form = store.exam_forms.get(report["exam_form_id"])
    if jurisdiction is not None and form is not None:
        if form["accreditation_body"] not in \
                jurisdiction["accepted_accreditation_bodies"]:
            raise ApiError("ERR_ACCREDITATION_NOT_ACCEPTED",
                           "the jurisdiction no longer accepts that body")
        if form["language"] not in jurisdiction["accepted_languages"]:
            raise ApiError("ERR_LANGUAGE_NOT_ACCEPTED",
                           "the jurisdiction no longer accepts that language")
    prior = None
    for existing in store.ordered(list(store.certificates.values())):
        if existing["candidate_id"] != candidate["id"]:
            continue
        if existing["jurisdiction_id"] != candidate["jurisdiction_id"]:
            continue
        if existing["status"] == "ISSUED":
            if existing["recert_authorized_at"] is None:
                raise ApiError("ERR_DUPLICATE_ACTIVE_CERTIFICATE",
                               "the candidate already holds an active "
                               "certificate in this jurisdiction")
            prior = existing
        elif existing["status"] == "EXPIRED" \
                and existing["recert_authorized_at"] is not None:
            prior = existing
    if not report["pass_flag"]:
        raise ApiError("ERR_CANDIDATE_DID_NOT_PASS",
                       "the score report is not passing")
    provider = store.providers.get(candidate["training_provider_id"])
    if provider is None:
        raise ApiError("ERR_TRAINING_PROVIDER_NOT_FOUND",
                       "training provider could not be found")
    cascade.check_credit(provider, calc.CERT_ISSUANCE_FEE_CENTS)

    issued_at = store.clock
    cycle_months = jurisdiction["recert_cycle_months"] if jurisdiction else 60
    expires_at = calc.add_months(issued_at, cycle_months)
    row = store.base()
    row.update({
        "candidate_id": candidate["id"],
        "score_report_id": report_id,
        "jurisdiction_id": candidate["jurisdiction_id"],
        "superseded_by_certificate_id": None,
        "certificate_number": store.next_certificate_number(),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "recert_window_opens_at": expires_at
        - timedelta(days=calc.RECERT_WINDOW_DAYS),
        "status": "ISSUED",
        "issuance_fee_cents": calc.CERT_ISSUANCE_FEE_CENTS,
        "reminder_tiers_sent": [],
        "recert_authorized_at": None,
        "revocation_reason": None,
    })
    store.certificates[row["id"]] = row
    cascade.debit_provider(provider, calc.CERT_ISSUANCE_FEE_CENTS)
    if prior is not None:
        prior["superseded_by_certificate_id"] = row["id"]
        prior["status"] = "SUPERSEDED"
        store.touch(prior)
    candidate["compliance_status"] = "CERTIFIED"
    store.touch(candidate)
    return ok(row, 201)


@scoring_bp.get("/certificates/<certificate_id>")
def read_certificate(certificate_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE, authz.HEALTH_OFFICER)
    certificate = find("certificate", certificate_id)
    _certificate_scope(certificate, user_id, role)
    return ok(certificate)


@scoring_bp.get("/certificates")
def list_certificates():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.HEALTH_OFFICER)
    candidate_filter = V.query_id("candidate_id")
    report_filter = V.query_id("score_report_id")
    jurisdiction_filter = V.query_id("jurisdiction_id")
    superseded_filter = V.query_id("superseded_by_certificate_id")
    status = V.query_enum("status", V.CERTIFICATE_STATUS)
    if role == authz.HEALTH_OFFICER:
        jurisdiction_filter = scoped_filter(jurisdiction_filter, user_id)
    rows = [r for r in store.certificates.values()
            if match(r, "candidate_id", candidate_filter)
            and match(r, "score_report_id", report_filter)
            and match(r, "jurisdiction_id", jurisdiction_filter)
            and match(r, "superseded_by_certificate_id", superseded_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows
                if authz.provider_of_certificate(r) == user_id]
    return paged(rows)


@scoring_bp.post("/certificates/<certificate_id>/recert-authorization")
def recert_authorization(certificate_id):
    require(authz.PLATFORM_ADMIN)
    certificate = find("certificate", certificate_id)
    V.get_body()
    if certificate["status"] not in ("ISSUED", "EXPIRED"):
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID",
                       "the certificate may not be authorized from this state")
    if store.clock < certificate["recert_window_opens_at"]:
        raise ApiError("ERR_RECERT_WINDOW_NOT_OPEN",
                       "the recertification window has not opened")
    certificate["recert_authorized_at"] = store.clock
    store.touch(certificate)
    return ok(certificate)
