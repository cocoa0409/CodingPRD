"""Routes: incident reports, clinical referrals, evaluation surveys, summary."""
from flask import request

from db import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION, ERR_INCIDENT_ON_INVALID_SESSION,
    ERR_CLINICAL_REQUIRES_CRITICAL, ERR_SURVEY_INVALID, ERR_FORBIDDEN,
)
from util import (
    authenticate, authorize, require_owner, body, require_fields, require_enum,
    require_int, ok_object, paginate, serialize, fmt_ts,
)
import services as svc
from routes_ops import (
    resolve_group_session, get_participant_or_404, check_participant_self,
    check_facilitator_assigned,
)

SEVERITIES = ("STANDARD", "CRITICAL")
CATEGORIES = ("SAFETY", "CONFIDENTIALITY", "HARASSMENT", "MEDICAL", "OTHER")
REASON_CODES = ("OUT_OF_SCOPE", "CRISIS", "MEDICAL", "RISK_OF_HARM")
# session states in which a CRITICAL incident may be raised
CRITICAL_ALLOWED_SESSION_STATES = ("IN_PROGRESS", "COMPLETED", "COMPLETED_WITH_INCIDENT")


def incident_view(i):
    return serialize(i)


def referral_view(r):
    return serialize(r)


def survey_view(s):
    return serialize(s)


def get_incident_or_404(iid, session_id=None):
    i = db.incidents.get(iid)
    if i is None or (session_id is not None and i["session_id"] != session_id):
        raise_err(ERR_NOT_FOUND, "IncidentReport not found")
    return i


def get_referral_or_404(rid, participant_id=None):
    r = db.referrals.get(rid)
    if r is None or (participant_id is not None
                     and r.get("participant_id") != participant_id):
        raise_err(ERR_NOT_FOUND, "ClinicalReferral not found")
    return r


def check_referral_self(ctx, referral):
    if ctx.role == "Participant":
        require_owner(ctx.user_id == referral.get("participant_id"))


def register_incidents(app):

    # ---------- incidents ----------
    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents")
    def create_incident(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        program, group, s = resolve_group_session(pid, gid, sid)
        data = body()
        require_fields(data, ["raised_by_facilitator_id", "severity", "category",
                              "description"])
        raised_by = db.facilitators.get(data["raised_by_facilitator_id"])
        if raised_by is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Raising facilitator not found")
        severity = require_enum(data, "severity", SEVERITIES)
        category = require_enum(data, "category", CATEGORIES)
        # the raising facilitator must staff this session
        on_session = (data["raised_by_facilitator_id"] == s["primary_facilitator_id"]
                      or data["raised_by_facilitator_id"] == s.get("cofacilitator_id"))
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == data["raised_by_facilitator_id"] and on_session)
        elif not on_session:
            raise_err(ERR_FORBIDDEN,
                      "raised_by_facilitator_id must staff this session")
        # priority 8: CRITICAL requires the session to have started
        if severity == "CRITICAL" and s["status"] not in CRITICAL_ALLOWED_SESSION_STATES:
            raise_err(ERR_INCIDENT_ON_INVALID_SESSION,
                      "CRITICAL incidents require an IN_PROGRESS or later session")
        rec = svc.add_common(svc.make_record({
            "session_id": sid,
            "raised_by_facilitator_id": data["raised_by_facilitator_id"],
            "severity": severity,
            "category": category,
            "description": data["description"],
            "status": "OPEN",
        }))
        rec["_program_id"] = pid
        db.incidents[rec["id"]] = rec
        svc.recompute_program(program, bump=True)
        return ok_object(incident_view(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents")
    def list_incidents_nested(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "ClinicalCoordinator"])
        resolve_group_session(pid, gid, sid)
        items = [i for i in db.incidents.values() if i["session_id"] == sid]
        return _filter_incidents(items)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents/<iid>")
    def get_incident_nested(pid, gid, sid, iid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "ClinicalCoordinator"])
        resolve_group_session(pid, gid, sid)
        return ok_object(incident_view(get_incident_or_404(iid, sid)))

    @app.get("/incident-reports/<iid>")
    def get_incident_alias(iid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "ClinicalCoordinator"])
        return ok_object(incident_view(get_incident_or_404(iid)))

    @app.get("/incident-reports")
    def list_incidents_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "ClinicalCoordinator"])
        items = list(db.incidents.values())
        sid = request.args.get("session_id")
        fid = request.args.get("raised_by_facilitator_id")
        if sid is not None:
            items = [i for i in items if i["session_id"] == sid]
        if fid is not None:
            items = [i for i in items if i["raised_by_facilitator_id"] == fid]
        return _filter_incidents(items)

    def _filter_incidents(items):
        status = request.args.get("status")
        severity = request.args.get("severity")
        if status is not None:
            items = [i for i in items if i["status"] == status]
        if severity is not None:
            items = [i for i in items if i["severity"] == severity]
        return paginate(items)

    def _incident_action(pid, gid, sid, iid, fn):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        program, group, s = resolve_group_session(pid, gid, sid)
        inc = get_incident_or_404(iid, sid)
        fn(inc)
        svc.touch(inc)
        svc.recompute_program(program, bump=True)
        return ok_object(incident_view(inc))

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents/<iid>/acknowledge")
    def acknowledge_incident(pid, gid, sid, iid):
        def fn(inc):
            if inc["status"] != "OPEN":
                raise_err(ERR_INVALID_STATE, "Incident must be OPEN to acknowledge")
            inc["status"] = "ACKNOWLEDGED"
        return _incident_action(pid, gid, sid, iid, fn)

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents/<iid>/resolve")
    def resolve_incident(pid, gid, sid, iid):
        def fn(inc):
            if inc["status"] != "ACKNOWLEDGED":
                raise_err(ERR_INVALID_STATE,
                          "Incident must be ACKNOWLEDGED to resolve")
            inc["status"] = "RESOLVED"
        return _incident_action(pid, gid, sid, iid, fn)

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/incidents/<iid>/escalate")
    def escalate_incident(pid, gid, sid, iid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        program, group, s = resolve_group_session(pid, gid, sid)
        inc = get_incident_or_404(iid, sid)
        data = body()
        # priority 6: state
        if inc["status"] not in ("OPEN", "ACKNOWLEDGED"):
            raise_err(ERR_INVALID_STATE,
                      "Incident must be OPEN or ACKNOWLEDGED to escalate")
        # priority 10: clinical escalation requires CRITICAL severity
        if inc["severity"] != "CRITICAL":
            raise_err(ERR_CLINICAL_REQUIRES_CRITICAL,
                      "Escalation requires severity=CRITICAL")
        participant_id = data.get("participant_id")
        if participant_id is not None and participant_id not in db.participants:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Participant not found")
        reason = data.get("reason_code", "OUT_OF_SCOPE")
        if reason not in REASON_CODES:
            raise_err(ERR_VALIDATION, "Invalid reason_code")
        inc["status"] = "ESCALATED_TO_CLINICAL"
        svc.touch(inc)
        referral = svc.add_common(svc.make_record({
            "participant_id": participant_id,
            "source_incident_id": inc["id"],
            "reason_code": reason,
            "status": "PENDING",
            "clinical_notes": data.get("clinical_notes"),
        }))
        db.referrals[referral["id"]] = referral
        svc.recompute_program(program, bump=True)
        return ok_object(incident_view(inc))

    # ---------- clinical referrals ----------
    @app.get("/participants/<pid>/referrals")
    def list_referrals_nested(pid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "ClinicalCoordinator", "Participant"])
        get_participant_or_404(pid)
        check_participant_self(ctx, pid)
        items = [r for r in db.referrals.values()
                 if r.get("participant_id") == pid]
        status = request.args.get("status")
        if status is not None:
            items = [r for r in items if r["status"] == status]
        return paginate(items)

    @app.get("/participants/<pid>/referrals/<rid>")
    def get_referral_nested(pid, rid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "ClinicalCoordinator", "Participant"])
        get_participant_or_404(pid)
        check_participant_self(ctx, pid)
        return ok_object(referral_view(get_referral_or_404(rid, pid)))

    @app.get("/clinical-referrals/<rid>")
    def get_referral_alias(rid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "ClinicalCoordinator", "Participant"])
        r = get_referral_or_404(rid)
        check_referral_self(ctx, r)
        return ok_object(referral_view(r))

    @app.get("/clinical-referrals")
    def list_referrals_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "ClinicalCoordinator", "Participant"])
        items = list(db.referrals.values())
        pid = request.args.get("participant_id")
        iid = request.args.get("source_incident_id")
        status = request.args.get("status")
        if ctx.role == "Participant":
            if pid is not None:
                require_owner(pid == ctx.user_id)
            items = [r for r in items if r.get("participant_id") == ctx.user_id]
        if pid is not None:
            items = [r for r in items if r.get("participant_id") == pid]
        if iid is not None:
            items = [r for r in items if r.get("source_incident_id") == iid]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        return paginate(items)

    def _referral_action(pid, rid, from_status, to_status, label):
        ctx = authenticate()
        authorize(ctx, ["ClinicalCoordinator"])
        get_participant_or_404(pid)
        r = get_referral_or_404(rid, pid)
        if r["status"] != from_status:
            raise_err(ERR_INVALID_STATE, f"Referral must be {from_status} to {label}")
        data = body()
        if "clinical_notes" in data and data["clinical_notes"] is not None:
            r["clinical_notes"] = data["clinical_notes"]
        r["status"] = to_status
        svc.touch(r)
        return ok_object(referral_view(r))

    @app.post("/participants/<pid>/referrals/<rid>/accept")
    def accept_referral(pid, rid):
        return _referral_action(pid, rid, "PENDING", "ACCEPTED", "accept")

    @app.post("/participants/<pid>/referrals/<rid>/decline")
    def decline_referral(pid, rid):
        return _referral_action(pid, rid, "PENDING", "DECLINED", "decline")

    @app.post("/participants/<pid>/referrals/<rid>/complete")
    def complete_referral(pid, rid):
        return _referral_action(pid, rid, "ACCEPTED", "COMPLETED", "complete")

    # ---------- evaluation surveys ----------
    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/surveys")
    def create_survey(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["Participant"])
        resolve_group_session(pid, gid, sid)
        data = body()
        require_fields(data, ["participant_id", "overall_rating",
                              "facilitator_rating", "modality_rating"])
        participant = db.participants.get(data["participant_id"])
        if participant is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Participant not found")
        require_owner(ctx.user_id == participant["id"])
        # priority 24: ratings in 1..5 and the participant attended the session
        try:
            overall = require_int(data, "overall_rating")
            facilitator = require_int(data, "facilitator_rating")
            modality = require_int(data, "modality_rating")
        except Exception:
            raise_err(ERR_SURVEY_INVALID, "Ratings must be integers in 1..5")
        if not (1 <= overall <= 5 and 1 <= facilitator <= 5 and 1 <= modality <= 5):
            raise_err(ERR_SURVEY_INVALID, "Ratings must be in 1..5")
        attended = any(
            a["session_id"] == sid and a["participant_id"] == participant["id"]
            and a["status"] == "ATTENDED"
            for a in db.attendance.values()
        )
        if not attended:
            raise_err(ERR_SURVEY_INVALID,
                      "Participant did not attend this session")
        rec = svc.make_record({
            "session_id": sid,
            "participant_id": participant["id"],
            "overall_rating": overall,
            "facilitator_rating": facilitator,
            "modality_rating": modality,
            "free_text": data.get("free_text"),
            "submitted_at": fmt_ts(db.now()),
        })
        db.surveys[rec["id"]] = rec
        return ok_object(survey_view(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/surveys")
    def list_surveys_nested(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        resolve_group_session(pid, gid, sid)
        return paginate([s for s in db.surveys.values() if s["session_id"] == sid])

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/surveys/<svid>")
    def get_survey_nested(pid, gid, sid, svid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        resolve_group_session(pid, gid, sid)
        rec = db.surveys.get(svid)
        if rec is None or rec["session_id"] != sid:
            raise_err(ERR_NOT_FOUND, "EvaluationSurvey not found")
        return ok_object(survey_view(rec))

    @app.get("/evaluation-surveys/<svid>")
    def get_survey_alias(svid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        rec = db.surveys.get(svid)
        if rec is None:
            raise_err(ERR_NOT_FOUND, "EvaluationSurvey not found")
        return ok_object(survey_view(rec))

    @app.get("/evaluation-surveys")
    def list_surveys_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        items = list(db.surveys.values())
        sid = request.args.get("session_id")
        pid = request.args.get("participant_id")
        if sid is not None:
            items = [s for s in items if s["session_id"] == sid]
        if pid is not None:
            items = [s for s in items if s["participant_id"] == pid]
        return paginate(items)

    # ---------- computed session summary ----------
    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/summary")
    def session_summary(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        resolve_group_session(pid, gid, sid)
        records = [a for a in db.attendance.values() if a["session_id"] == sid]
        checked_in_or_attended = sum(
            1 for a in records if a["status"] in ("CHECKED_IN", "ATTENDED"))
        attended = sum(1 for a in records if a["status"] == "ATTENDED")
        confirmed = sum(
            1 for e in db.enrollments.values()
            if e["group_id"] == gid and e["seat_status"] == "CONFIRMED")
        denom = max(1, confirmed)
        surveys = [s for s in db.surveys.values() if s["session_id"] == sid]
        if surveys:
            avg = sum(s["overall_rating"] for s in surveys) / len(surveys)
        else:
            avg = None
        return ok_object({
            "attendance_rate_provisional": svc.round4(checked_in_or_attended, denom),
            "attendance_rate_final": svc.round4(attended, denom),
            "confirmed_count": confirmed,
            "average_overall_rating": avg,
        })
