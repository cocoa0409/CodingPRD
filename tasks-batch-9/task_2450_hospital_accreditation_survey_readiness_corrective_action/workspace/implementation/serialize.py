"""Resource serializers.

Common fields per PRD 2.5: every resource carries id + created_at; most also
carry updated_at + version. TracerObservation and EscSubmission carry only
id and created_at.
"""

from envelope import iso


def _common(entity, out):
    out["created_at"] = iso(entity["created_at"])
    if "updated_at" in entity:
        out["updated_at"] = iso(entity["updated_at"])
    if "version" in entity:
        out["version"] = entity["version"]
    return out


def chapter(c):
    return _common(
        c,
        {
            "id": c["id"],
            "code": c["code"],
            "name": c["name"],
            "weight_pct": c["weight_pct"],
            "evidence_min_count": c["evidence_min_count"],
            "standard_count": c["standard_count"],
            "mapped_standard_count": c["mapped_standard_count"],
            "evidence_complete_standard_count": c["evidence_complete_standard_count"],
            "deficient_standard_count": c["deficient_standard_count"],
            "ppr_escalation_count": c["ppr_escalation_count"],
            "readiness_flag": c["readiness_flag"],
        },
    )


def standard(s):
    return _common(
        s,
        {
            "id": s["id"],
            "chapter_id": s["chapter_id"],
            "standard_code": s["standard_code"],
            "title": s["title"],
            "risk_tier": s["risk_tier"],
            "compliance_state": s["compliance_state"],
            "active_owner_count": s["active_owner_count"],
            "validated_evidence_count": s["validated_evidence_count"],
            "last_noncompliant_observed_at": iso(s["last_noncompliant_observed_at"]),
        },
    )


def owner_assignment(a):
    return _common(
        a,
        {
            "id": a["id"],
            "standard_id": a["standard_id"],
            "owner_user_id": a["owner_user_id"],
            "designation": a["designation"],
            "status": a["status"],
            "revoked_at": iso(a["revoked_at"]),
        },
    )


def evidence_item(e):
    return _common(
        e,
        {
            "id": e["id"],
            "standard_id": e["standard_id"],
            "title": e["title"],
            "doc_type": e["doc_type"],
            "effective_date": iso(e["effective_date"]),
            "expires_at": iso(e["expires_at"]),
            "validation_state": e["validation_state"],
            "submitted_by_user_id": e["submitted_by_user_id"],
            "reviewed_by_user_id": e["reviewed_by_user_id"],
            "review_note": e["review_note"],
            "rejection_count": e["rejection_count"],
        },
    )


def unit(u):
    return _common(
        u,
        {
            "id": u["id"],
            "name": u["name"],
            "unit_type": u["unit_type"],
            "bed_count": u["bed_count"],
            "posture": u["posture"],
            "open_deficiency_penalty_points": u["open_deficiency_penalty_points"],
            "readiness_score": u["readiness_score"],
            "readiness_band": u["readiness_band"],
            "scheduled_tracer_count": u["scheduled_tracer_count"],
        },
    )


def tracer(t):
    return _common(
        t,
        {
            "id": t["id"],
            "unit_id": t["unit_id"],
            "chapter_id": t["chapter_id"],
            "tracer_type": t["tracer_type"],
            "window_start": iso(t["window_start"]),
            "window_end": iso(t["window_end"]),
            "state": t["state"],
            "scored_weight": t["scored_weight"],
            "earned_weight": t["earned_weight"],
            "tracer_score": t["tracer_score"],
            "contributes_to_readiness": t["contributes_to_readiness"],
            "started_at": iso(t["started_at"]),
            "completed_at": iso(t["completed_at"]),
            "abort_reason": t["abort_reason"],
        },
    )


def observation(o):
    return _common(
        o,
        {
            "id": o["id"],
            "mock_tracer_id": o["mock_tracer_id"],
            "standard_id": o["standard_id"],
            "result": o["result"],
            "weight": o["weight"],
            "note": o["note"],
            "recorded_by_user_id": o["recorded_by_user_id"],
        },
    )


def rounding_session(s):
    return _common(
        s,
        {
            "id": s["id"],
            "unit_id": s["unit_id"],
            "round_type": s["round_type"],
            "window_start": iso(s["window_start"]),
            "window_end": iso(s["window_end"]),
            "state": s["state"],
            "deficiency_count": s["deficiency_count"],
            "closed_at": iso(s["closed_at"]),
        },
    )


def ticket(t):
    return _common(
        t,
        {
            "id": t["id"],
            "rounding_session_id": t["rounding_session_id"],
            "standard_id": t["standard_id"],
            "description": t["description"],
            "severity": t["severity"],
            "state": t["state"],
            "penalty_points": t["penalty_points"],
            "due_at": iso(t["due_at"]),
            "accelerated": t["accelerated"],
            "verified_by_user_id": t["verified_by_user_id"],
            "failed_verification_count": t["failed_verification_count"],
        },
    )


def survey_window(w):
    return _common(
        w,
        {
            "id": w["id"],
            "cycle_label": w["cycle_label"],
            "prior_survey_end_date": iso(w["prior_survey_end_date"]),
            "predicted_open_date": iso(w["predicted_open_date"]),
            "predicted_close_date": iso(w["predicted_close_date"]),
            "command_center_activation_allowed_from": iso(
                w["command_center_activation_allowed_from"]
            ),
            "window_state": w["window_state"],
            "command_center_state": w["command_center_state"],
            "survey_opened_at": iso(w["survey_opened_at"]),
            "survey_closed_at": iso(w["survey_closed_at"]),
            "condition_level_finding_count": w["condition_level_finding_count"],
            "follow_up_required": w["follow_up_required"],
            "follow_up_due_at": iso(w["follow_up_due_at"]),
        },
    )


def finding(f):
    return _common(
        f,
        {
            "id": f["id"],
            "survey_window_id": f["survey_window_id"],
            "standard_id": f["standard_id"],
            "unit_id": f["unit_id"],
            "observed_noncompliance_count": f["observed_noncompliance_count"],
            "sampled_count": f["sampled_count"],
            "patient_harm_observed": f["patient_harm_observed"],
            "noncompliance_rate": f["noncompliance_rate"],
            "classification": f["classification"],
            "risk_level": f["risk_level"],
            "condition_level": f["condition_level"],
            "response_deadline_days": f["response_deadline_days"],
            "initial_response_due_at": iso(f["initial_response_due_at"]),
            "response_due_at": iso(f["response_due_at"]),
            "state": f["state"],
            "clarification_round_count": f["clarification_round_count"],
            "submission_count": f["submission_count"],
            "accepted_at": iso(f["accepted_at"]),
        },
    )


def esc_submission(s):
    return _common(
        s,
        {
            "id": s["id"],
            "survey_finding_id": s["survey_finding_id"],
            "corrective_action_summary": s["corrective_action_summary"],
            "measure_of_success": s["measure_of_success"],
            "leadership_signoff": s["leadership_signoff"],
            "submission_round": s["submission_round"],
            "submitted_by_user_id": s["submitted_by_user_id"],
            "decision": s["decision"],
            "decision_note": s["decision_note"],
        },
    )


def ppr(p):
    return _common(
        p,
        {
            "id": p["id"],
            "chapter_id": p["chapter_id"],
            "period_label": p["period_label"],
            "self_ratings": [
                {"standard_id": r["standard_id"], "rating": r["rating"]} for r in p["self_ratings"]
            ],
            "self_score": p["self_score"],
            "verified_score": p["verified_score"],
            "gap": p["gap"],
            "flagged_overstatement": p["flagged_overstatement"],
            "requires_reassessment": p["requires_reassessment"],
            "state": p["state"],
            "attested_by_user_id": p["attested_by_user_id"],
        },
    )


def readiness(result):
    return {
        "unit_id": result["unit_id"],
        "mode": result["mode"],
        "base_score": result["base_score"],
        "penalty_points_applied": result["penalty_points_applied"],
        "participating_weight_pct": result["participating_weight_pct"],
        "readiness_score": result["readiness_score"],
        "readiness_band": result["readiness_band"],
        "chapter_breakdown": result["chapter_breakdown"],
    }
