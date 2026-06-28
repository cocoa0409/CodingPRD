"""Resource serialization (entity field projection per SCAFFOLD §1.1)."""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _append_only_common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def student_out(s):
    out = _common(s)
    out.update({
        "full_name": s["full_name"],
        "email": s["email"],
        "is_international": s["is_international"],
        "corporate_contract_id": s["corporate_contract_id"],
        "placement_level": s["placement_level"],
        "track": s["track"],
        "visa_status": s["visa_status"],
        "i20_required_weekly_hours": s["i20_required_weekly_hours"],
        "certification_status": s["certification_status"],
        "final_progress_score": s["final_progress_score"],
    })
    return out


def contract_out(c):
    out = _common(c)
    out.update({
        "company_name": c["company_name"],
        "contracted_seats": c["contracted_seats"],
        "seats_consumed": c["seats_consumed"],
        "discount_tier": c["discount_tier"],
        "status": c["status"],
    })
    return out


def placement_test_out(t):
    out = _common(t)
    out.update({
        "student_id": t["student_id"],
        "raw_score": t["raw_score"],
        "assigned_level": t["assigned_level"],
        "status": t["status"],
    })
    return out


def cohort_out(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "level": c["level"],
        "track": c["track"],
        "capacity": c["capacity"],
        "weekly_hours": c["weekly_hours"],
        "term_start": c["term_start"],
        "term_end": c["term_end"],
        "total_sessions": c["total_sessions"],
        "base_tuition_cents": c["base_tuition_cents"],
        "seats_taken": c["seats_taken"],
        "schedule_block": c["schedule_block"],
        "status": c["status"],
    })
    return out


def enrollment_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "cohort_id": e["cohort_id"],
        "status": e["status"],
        "enrolled_at": e["enrolled_at"],
        "sessions_attended": e["sessions_attended"],
        "sessions_elapsed": e["sessions_elapsed"],
        "attendance_rate": e["attendance_rate"],
        "tuition_invoice_cents": e["tuition_invoice_cents"],
        "refund_cents": e["refund_cents"],
        "completion_score": e["completion_score"],
        "termination_reason": e["termination_reason"],
    })
    return out


def attendance_out(a):
    out = _append_only_common(a)
    out.update({
        "enrollment_id": a["enrollment_id"],
        "session_index": a["session_index"],
        "status": a["status"],
        "recorded_at": a["recorded_at"],
    })
    return out


def progress_out(p):
    out = _common(p)
    out.update({
        "enrollment_id": p["enrollment_id"],
        "speaking": p["speaking"],
        "listening": p["listening"],
        "reading": p["reading"],
        "writing": p["writing"],
        "assessed_at": p["assessed_at"],
    })
    return out


def addon_out(a):
    out = _common(a)
    out.update({
        "student_id": a["student_id"],
        "add_on_type": a["add_on_type"],
        "enrollment_id": a["enrollment_id"],
        "units": a["units"],
        "fee_cents": a["fee_cents"],
        "status": a["status"],
    })
    return out


def compliance_event_out(ev):
    out = _append_only_common(ev)
    out.update({
        "student_id": ev["student_id"],
        "event_type": ev["event_type"],
        "prior_status": ev["prior_status"],
        "new_status": ev["new_status"],
        "reason": ev["reason"],
        "recorded_at": ev["recorded_at"],
    })
    return out
