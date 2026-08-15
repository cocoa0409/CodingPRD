"""Routes: review comments, outreach events, public hearings, decisions."""

from datetime import timedelta

from flask import request

import store
from store import CLOCK, touch
from auth import authenticate, authorize, require_owner
from envelope import success, paginate
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_FORBIDDEN,
    ERR_DISCIPLINE_MISMATCH, ERR_REVISION_MISMATCH, ERR_NOT_FOUND,
    ERR_BLOCKING_COMMENTS_OPEN, ERR_INSUFFICIENT_NOTICE, ERR_HEARING_NOT_YET,
    ERR_STALE_APPLICATION_VERSION, ERR_DECISION_DEADLINE_PASSED,
    ERR_SEGREGATION_OF_DUTIES, ERR_HEARING_REQUIRED,
)
from validate import (
    body_or_empty, require_fields, reject_version_fields, req_str, req_enum,
    req_int, req_datetime,
)
import domain
from domain import get_or_404

ALL_ROLES = ("PlatformAdmin", "Applicant", "StaffReviewer", "DecisionAuthority")
DISCIPLINES = ("TRANSPORTATION", "PARKS", "FIRE", "WATER", "SEWER", "PLANNING")
TERMINAL_APP = ("APPROVED", "DENIED", "WITHDRAWN")


def _json():
    return request.get_json(silent=True)


def _app_or_404(appId):
    return get_or_404("applications", appId, "EntitlementApplication")


def _require_not_terminal_app(app_rec):
    if app_rec["status"] in TERMINAL_APP:
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "Application is in a terminal state", 409)


def register_review_routes(app):

    # --- review comments ------------------------------------------------------
    @app.post("/entitlement/applications/<appId>/review-comments")
    def create_review_comment(appId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["reviewer_id", "discipline", "comment_text",
                              "severity"])
        reviewer_id = req_str(body, "reviewer_id")
        discipline = req_enum(body, "discipline", DISCIPLINES)
        text = req_str(body, "comment_text")
        severity = req_enum(body, "severity", ("INFO", "REQUIRED", "BLOCKING"))
        revises_id = body.get("revises_comment_id")
        if revises_id is not None and not isinstance(revises_id, str):
            raise ApiError("ERR_INVALID_REQUEST",
                           "revises_comment_id must be a string", 400)

        _require_not_terminal_app(app_rec)
        if app_rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE,
                           "Comments may only be posted while the application "
                           "is UNDER_REVIEW", 409)

        reviewer = get_or_404("staff_reviewers", reviewer_id, "StaffReviewer")
        if reviewer_id != p.user_id:
            raise ApiError(ERR_FORBIDDEN,
                           "reviewer_id must equal the acting reviewer's "
                           "X-User-ID", 403)
        if discipline not in (reviewer.get("disciplines") or []):
            raise ApiError(ERR_DISCIPLINE_MISMATCH,
                           "Reviewer.disciplines does not include "
                           f"{discipline}", 422)
        if revises_id is not None:
            target = get_or_404("review_comments", revises_id, "ReviewComment")
            if (target.get("application_id") != appId
                    or target.get("discipline") != discipline):
                raise ApiError(ERR_REVISION_MISMATCH,
                               "revises_comment_id must target the same "
                               "application and discipline", 422)

        existing_rounds = [c["round_number"]
                           for c in store.all_records("review_comments")
                           if c.get("application_id") == appId]
        round_number = (max(existing_rounds) + 1) if existing_rounds else 1

        rec = store.new_record("review_comments")
        rec.update({
            "application_id": appId,
            "reviewer_id": reviewer_id,
            "discipline": discipline,
            "comment_text": text,
            "severity": severity,
            "round_number": round_number,
            "revises_comment_id": revises_id,
            "status": "OPEN",
        })
        # Posting a comment is a modification of the application (PRD 2.4).
        touch(app_rec)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/review-comments")
    def list_review_comments(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [c for c in store.all_records("review_comments")
                if c.get("application_id") == appId]
        for param in ("status", "severity"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/review-comments/<commentId>")
    def get_review_comment(commentId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("review_comments", commentId,
                                  "ReviewComment"), 200)

    @app.get("/entitlement/review-comments")
    def filter_review_comments():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("review_comments")
        for param in ("application_id", "reviewer_id", "revises_comment_id",
                      "status", "severity"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    def _comment_and_app(commentId):
        comment = get_or_404("review_comments", commentId, "ReviewComment")
        app_rec = store.get("applications", comment.get("application_id"))
        return comment, app_rec

    @app.post("/entitlement/review-comments/<commentId>/address")
    def address_comment(commentId):
        p = authenticate()
        authorize(p, ("Applicant",))
        reject_version_fields(body_or_empty(_json()))
        comment, app_rec = _comment_and_app(commentId)
        if comment["status"] in ("VERIFIED", "WAIVED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Comment is in a terminal state", 409)
        if comment["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE,
                           "Only an OPEN comment can be marked ADDRESSED", 409)
        if app_rec is None or app_rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE,
                           "Applicant responds while the application is "
                           "UNDER_REVIEW", 409)
        project = domain.project_for(app_rec)
        if project is not None:
            require_owner(p, project)
        comment["status"] = "ADDRESSED"
        touch(comment)
        return success(comment, 200)

    @app.post("/entitlement/review-comments/<commentId>/verify")
    def verify_comment(commentId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        comment, _app_rec = _comment_and_app(commentId)
        if comment["status"] in ("VERIFIED", "WAIVED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Comment is in a terminal state", 409)
        if comment["status"] != "ADDRESSED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only an ADDRESSED comment can be verified", 409)
        if comment.get("reviewer_id") != p.user_id:
            raise ApiError(ERR_FORBIDDEN,
                           "Only the authoring reviewer can verify this "
                           "comment", 403)
        comment["status"] = "VERIFIED"
        touch(comment)
        return success(comment, 200)

    @app.post("/entitlement/review-comments/<commentId>/waive")
    def waive_comment(commentId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        comment, _app_rec = _comment_and_app(commentId)
        if comment["status"] in ("VERIFIED", "WAIVED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Comment is in a terminal state", 409)
        if comment["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE,
                           "Only an OPEN comment can be waived", 409)
        if comment.get("reviewer_id") != p.user_id:
            raise ApiError(ERR_FORBIDDEN,
                           "Only the authoring reviewer can waive this "
                           "comment", 403)
        comment["status"] = "WAIVED"
        touch(comment)
        return success(comment, 200)

    # --- outreach events ------------------------------------------------------
    @app.post("/entitlement/applications/<appId>/outreach-events")
    def create_outreach_event(appId):
        p = authenticate()
        authorize(p, ("StaffReviewer", "Applicant"))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["event_date", "disposition", "attendee_count"])
        event_date = req_datetime(body, "event_date")
        disposition = req_enum(body, "disposition",
                               ("SUPPORT", "NEUTRAL", "OPPOSE",
                                "ORGANIZED_OPPOSITION"))
        attendees = req_int(body, "attendee_count")
        if attendees < 1:
            raise ApiError("ERR_INVALID_REQUEST",
                           "attendee_count must be >= 1", 400)
        if p.is_applicant:
            project = domain.project_for(app_rec)
            if project is not None:
                require_owner(p, project)
        rec = store.new_record("outreach_events")
        rec.update({
            "application_id": appId,
            "event_date": store.fmt_dt(event_date),
            "disposition": disposition,
            "attendee_count": attendees,
            "weight": domain.WEIGHTS[disposition],
        })
        domain.recompute_opposition(app_rec)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/outreach-events")
    def list_outreach_events(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [e for e in store.all_records("outreach_events")
                if e.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/outreach-events/<eventId>")
    def get_outreach_event(eventId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("outreach_events", eventId,
                                  "OutreachEvent"), 200)

    @app.get("/entitlement/outreach-events")
    def filter_outreach_events():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("outreach_events")
        v = request.args.get("application_id")
        if v is not None:
            recs = [r for r in recs if r.get("application_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    # --- public hearings --------------------------------------------------------
    def _check_notice_lead(hearing_date, notice_posted_date):
        if hearing_date - notice_posted_date < timedelta(
                days=domain.NOTICE_LEAD_DAYS):
            raise ApiError(ERR_INSUFFICIENT_NOTICE,
                           "hearing_date - notice_posted_date must be at "
                           f"least {domain.NOTICE_LEAD_DAYS} days", 422)

    @app.post("/entitlement/applications/<appId>/hearings")
    def create_hearing(appId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["hearing_date", "notice_posted_date",
                              "hearing_body"])
        hearing_date = req_datetime(body, "hearing_date")
        notice_posted = req_datetime(body, "notice_posted_date")
        hearing_body = req_enum(body, "hearing_body",
                                ("PLANNING_COMMISSION", "CITY_COUNCIL"))
        _require_not_terminal_app(app_rec)
        if app_rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE,
                           "Hearings are scheduled while the application is "
                           "UNDER_REVIEW", 409)
        # Temporal gate (5) precedes the constraint gate (7) per PRD 2.9.
        _check_notice_lead(hearing_date, notice_posted)
        open_blocking = [c for c in store.all_records("review_comments")
                         if c.get("application_id") == appId
                         and c["severity"] == "BLOCKING"
                         and c["status"] == "OPEN"]
        if open_blocking:
            raise ApiError(ERR_BLOCKING_COMMENTS_OPEN,
                           "A BLOCKING review comment remains OPEN", 409)
        rec = store.new_record("hearings")
        rec.update({
            "application_id": appId,
            "hearing_date": store.fmt_dt(hearing_date),
            "notice_posted_date": store.fmt_dt(notice_posted),
            "hearing_body": hearing_body,
            "status": "SCHEDULED",
        })
        app_rec["status"] = "HEARING_SCHEDULED"
        touch(app_rec)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/hearings")
    def list_hearings(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [h for h in store.all_records("hearings")
                if h.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/hearings/<hearingId>")
    def get_hearing(hearingId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("hearings", hearingId, "PublicHearing"), 200)

    @app.get("/entitlement/hearings")
    def filter_hearings():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("hearings")
        v = request.args.get("application_id")
        if v is not None:
            recs = [r for r in recs if r.get("application_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    def _hearing_or_404(hid):
        return get_or_404("hearings", hid, "PublicHearing")

    def _hearing_state_gate(h, required):
        if h["status"] in ("HELD", "CANCELLED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Hearing is in a terminal state", 409)
        if h["status"] != required:
            raise ApiError(ERR_INVALID_STATE,
                           f"Hearing must be {required} for this transition",
                           409)

    @app.post("/entitlement/hearings/<hearingId>/mark-held")
    def mark_hearing_held(hearingId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        h = _hearing_or_404(hearingId)
        _hearing_state_gate(h, "SCHEDULED")
        if CLOCK.now() < store.parse_dt(h["hearing_date"]):
            raise ApiError(ERR_HEARING_NOT_YET,
                           "Cannot mark a hearing HELD before its "
                           "hearing_date", 422)
        h["status"] = "HELD"
        touch(h)
        return success(h, 200)

    @app.post("/entitlement/hearings/<hearingId>/continue")
    def continue_hearing(hearingId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        h = _hearing_or_404(hearingId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["new_hearing_date"])
        new_date = req_datetime(body, "new_hearing_date")
        _hearing_state_gate(h, "SCHEDULED")
        # Notice is re-validated against the new date (PRD 3.5).
        _check_notice_lead(new_date, store.parse_dt(h["notice_posted_date"]))
        h["hearing_date"] = store.fmt_dt(new_date)
        h["status"] = "CONTINUED"
        touch(h)
        return success(h, 200)

    @app.post("/entitlement/hearings/<hearingId>/renotice")
    def renotice_hearing(hearingId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        h = _hearing_or_404(hearingId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["hearing_date", "notice_posted_date"])
        hearing_date = req_datetime(body, "hearing_date")
        notice_posted = req_datetime(body, "notice_posted_date")
        if h["status"] in ("HELD", "CANCELLED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Hearing is in a terminal state", 409)
        if h["status"] != "CONTINUED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a CONTINUED hearing can be re-noticed", 409)
        _check_notice_lead(hearing_date, notice_posted)
        h["hearing_date"] = store.fmt_dt(hearing_date)
        h["notice_posted_date"] = store.fmt_dt(notice_posted)
        h["status"] = "SCHEDULED"
        touch(h)
        return success(h, 200)

    @app.post("/entitlement/hearings/<hearingId>/cancel")
    def cancel_hearing(hearingId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        h = _hearing_or_404(hearingId)
        _hearing_state_gate(h, "SCHEDULED")
        h["status"] = "CANCELLED"
        touch(h)
        return success(h, 200)

    # --- decisions ---------------------------------------------------------------
    @app.post("/entitlement/applications/<appId>/decisions")
    def render_decision(appId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body,
                              allowed=("expected_application_version",))
        require_fields(body, ["decision", "decided_by",
                              "expected_application_version"])
        decision = req_enum(body, "decision", ("APPROVE", "DENY"))
        decided_by = req_str(body, "decided_by")
        expected = req_int(body, "expected_application_version")

        _require_not_terminal_app(app_rec)
        if app_rec["status"] != "DECISION_PENDING":
            raise ApiError(ERR_INVALID_STATE,
                           "Decisions can only be rendered from "
                           "DECISION_PENDING", 409)
        if expected != app_rec["version"]:
            raise ApiError(ERR_STALE_APPLICATION_VERSION,
                           "expected_application_version does not match the "
                           "current application version", 412)
        now = CLOCK.now()
        if app_rec.get("decision_due_date") and \
                now > store.parse_dt(app_rec["decision_due_date"]):
            raise ApiError(ERR_DECISION_DEADLINE_PASSED,
                           "Decision rendered after decision_due_date "
                           f"(PERMIT_STREAMLINING_DAYS="
                           f"{domain.PERMIT_STREAMLINING_DAYS})", 422)
        comment_authors = {c.get("reviewer_id")
                           for c in store.all_records("review_comments")
                           if c.get("application_id") == appId}
        if decided_by in comment_authors:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "decided_by equals a StaffReviewer who authored a "
                           "review comment on this application", 422)
        held = [h for h in store.all_records("hearings")
                if h.get("application_id") == appId and h["status"] == "HELD"]
        via_hearing = bool(held)
        if decision == "APPROVE" and \
                app_rec.get("opposition_posture") == "HIGH" and not via_hearing:
            raise ApiError(ERR_HEARING_REQUIRED,
                           "opposition_posture HIGH requires the decision to "
                           "come through a HELD hearing", 409)

        rec = store.new_record("decisions")
        rec.update({
            "application_id": appId,
            "decision": decision,
            "decided_by": decided_by,
            "decision_effective_date": store.fmt_dt(now),
            "appeal_deadline": store.fmt_dt(
                now + timedelta(days=domain.APPEAL_WINDOW_DAYS)),
            "via_hearing": via_hearing,
            "status": "RENDERED",
        })

        project = domain.project_for(app_rec)
        if decision == "APPROVE":
            app_rec["status"] = "APPROVED"
            schedule = domain.final_schedule_for(app_rec)
            if schedule is not None and project is not None:
                existing_final = domain.final_assessment_for(appId)
                if existing_final is None:
                    assessment = domain.create_assessment(
                        app_rec, project, schedule, "FINAL", now)
                else:
                    domain.recompute_final_assessment(
                        existing_final, app_rec, project, schedule, now)
                    assessment = existing_final
                app_rec["final_fee_total"] = assessment["net_total"]
        else:
            app_rec["status"] = "DENIED"
            domain.refund_open_assessments(app_rec)
        touch(app_rec)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/decisions")
    def list_decisions(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [d for d in store.all_records("decisions")
                if d.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/decisions/<decisionId>")
    def get_decision(decisionId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("decisions", decisionId,
                                  "EntitlementDecision"), 200)

    @app.get("/entitlement/decisions")
    def filter_decisions():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("decisions")
        for param in ("application_id", "decided_by"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)
