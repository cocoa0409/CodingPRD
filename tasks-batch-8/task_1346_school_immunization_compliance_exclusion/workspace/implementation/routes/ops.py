"""Ops endpoints: the compliance sweep (PRD §3.5)."""

from datetime import timedelta

import db
from db import clock, parse_iso, format_iso, stamp_new, touch
from middleware import require_roles
from response import success_object
from services.evaluation import deficiency_codes


def _recompute_booked_count(session):
    session["booked_count"] = sum(
        1 for a in db.clinic_appointments.values()
        if a["clinic_session_id"] == session["id"] and a["status"] == "BOOKED"
    )


def register(app):

    @app.post("/api/ops/compliance-sweep")
    def compliance_sweep():
        require_roles("DistrictHealthOfficer")
        now = clock.now()
        now_iso = format_iso(now)

        provisional_expired = 0
        notices_escalated = 0
        students_excluded = 0
        students_marked_compliant = 0
        appointments_no_show = 0

        # Pass A: ENROLLED_PROVISIONAL past deadline AND deficient -> NON_COMPLIANT
        # Also pass D: ENROLLED_PROVISIONAL with zero deficiencies -> ENROLLED_COMPLIANT
        for student in list(db.students.values()):
            if student["status"] != "ENROLLED_PROVISIONAL":
                continue
            deadline = parse_iso(student["provisional_deadline"])
            codes = deficiency_codes(student)
            if not codes:
                # zero deficiencies -> ENROLLED_COMPLIANT
                student["status"] = "ENROLLED_COMPLIANT"
                student["deficiency_vaccine_codes"] = []
                touch(student)
                students_marked_compliant += 1
            elif now > deadline:
                # strictly past deadline
                student["status"] = "NON_COMPLIANT"
                student["deficiency_vaccine_codes"] = codes
                # Auto-issue INITIAL_NONCOMPLIANCE notice
                notice = {
                    "student_id": student["id"],
                    "notice_type": "INITIAL_NONCOMPLIANCE",
                    "status": "ISSUED",
                    "issue_date": now_iso,
                    "exclusion_date": format_iso(now + timedelta(days=14)),
                    "resolved_at": None,
                }
                stamp_new(notice)
                db.compliance_notices[notice["id"]] = notice
                touch(student)
                provisional_expired += 1

        # Pass B: ISSUED notices at/past exclusion_date, student still deficient
        for notice in list(db.compliance_notices.values()):
            if notice["status"] != "ISSUED":
                continue
            if notice["notice_type"] != "INITIAL_NONCOMPLIANCE":
                continue
            exclusion = parse_iso(notice["exclusion_date"])
            if now < exclusion:
                continue
            student = db.students.get(notice["student_id"])
            if student is None:
                continue
            codes = deficiency_codes(student)
            if not codes:
                continue
            notice["status"] = "EXCLUSION_EFFECTIVE"
            touch(notice)
            notices_escalated += 1
            if student["status"] == "NON_COMPLIANT":
                student["status"] = "EXCLUDED"
                student["deficiency_vaccine_codes"] = codes
                touch(student)
                students_excluded += 1

        # Pass C: BOOKED appointments past end_time -> NO_SHOW
        affected_sessions = set()
        for appt in list(db.clinic_appointments.values()):
            if appt["status"] != "BOOKED":
                continue
            end_time = parse_iso(appt["end_time"])
            if end_time < now:
                appt["status"] = "NO_SHOW"
                touch(appt)
                affected_sessions.add(appt["clinic_session_id"])
                appointments_no_show += 1
        for sid in affected_sessions:
            session = db.clinic_sessions.get(sid)
            if session is not None:
                _recompute_booked_count(session)
                touch(session)

        return success_object({
            "provisional_expired_count": provisional_expired,
            "notices_escalated_count": notices_escalated,
            "students_excluded_count": students_excluded,
            "students_marked_compliant_count": students_marked_compliant,
            "appointments_no_show_count": appointments_no_show,
        })
