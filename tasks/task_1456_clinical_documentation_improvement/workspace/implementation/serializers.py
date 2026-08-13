"""Entity serializers (stored dict -> API representation)."""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def program_out(p):
    out = _common(p)
    out.update({
        "facility_name": p["facility_name"],
        "program_code": p["program_code"],
        "baseline_cmi": p["baseline_cmi"],
        "current_period_index": p["current_period_index"],
        "status": p["status"],
    })
    return out


def policy_out(p):
    out = _common(p)
    out.update({
        "cdi_program_id": p["cdi_program_id"],
        "name": p["name"],
        "response_due_periods": p["response_due_periods"],
        "escalation_stage_periods": p["escalation_stage_periods"],
        "max_escalation_stage": p["max_escalation_stage"],
        "is_default": p["is_default"],
    })
    return out


def provider_out(p):
    out = _common(p)
    out.update({
        "cdi_program_id": p["cdi_program_id"],
        "npi": p["npi"],
        "full_name": p["full_name"],
        "specialty": p["specialty"],
        "education_score": p["education_score"],
        "pattern_tally_json": dict(p["pattern_tally_json"]),
        "education_flag": p["education_flag"],
    })
    return out


def case_out(c):
    out = _common(c)
    out.update({
        "cdi_program_id": c["cdi_program_id"],
        "mrn": c["mrn"],
        "admission_period": c["admission_period"],
        "discharge_period": c["discharge_period"],
        "attending_provider_id": c["attending_provider_id"],
        "initial_drg_code": c["initial_drg_code"],
        "initial_drg_weight": c["initial_drg_weight"],
        "working_drg_code": c["working_drg_code"],
        "working_drg_weight": c["working_drg_weight"],
        "working_soi": c["working_soi"],
        "working_rom": c["working_rom"],
        "priority_score": c["priority_score"],
        "reconciliation_status": c["reconciliation_status"],
        "status": c["status"],
    })
    return out


def review_out(r):
    out = _common(r)
    out.update({
        "patient_case_id": r["patient_case_id"],
        "cdi_program_id": r["cdi_program_id"],
        "cdi_specialist_id": r["cdi_specialist_id"],
        "opened_period": r["opened_period"],
        "opportunity_weight_delta": r["opportunity_weight_delta"],
        "opportunity_soi_delta": r["opportunity_soi_delta"],
        "opportunity_rom_delta": r["opportunity_rom_delta"],
        "closed_reason": r["closed_reason"],
        "status": r["status"],
    })
    return out


def query_out(q):
    out = _common(q)
    out.update({
        "cdi_review_id": q["cdi_review_id"],
        "patient_case_id": q["patient_case_id"],
        "cdi_program_id": q["cdi_program_id"],
        "provider_id": q["provider_id"],
        "escalation_policy_id": q["escalation_policy_id"],
        "query_text": q["query_text"],
        "clinical_indicators": list(q["clinical_indicators"]),
        "proposed_drg_code": q["proposed_drg_code"],
        "proposed_drg_weight": q["proposed_drg_weight"],
        "proposed_soi": q["proposed_soi"],
        "proposed_rom": q["proposed_rom"],
        "compliant_language": q["compliant_language"],
        "lint_findings": list(q["lint_findings"]),
        "sent_period": q["sent_period"],
        "due_period": q["due_period"],
        "escalation_stage": q["escalation_stage"],
        "last_escalated_period": q["last_escalated_period"],
        "response_id": q["response_id"],
        "status": q["status"],
    })
    return out


def response_out(r):
    out = _common(r)
    out.update({
        "cdi_query_id": r["cdi_query_id"],
        "patient_case_id": r["patient_case_id"],
        "responder_provider_id": r["responder_provider_id"],
        "response_type": r["response_type"],
        "response_text": r["response_text"],
        "responded_period": r["responded_period"],
        "was_overdue": r["was_overdue"],
    })
    return out


def reconciliation_out(e):
    out = _common(e)
    out.update({
        "patient_case_id": e["patient_case_id"],
        "cdi_program_id": e["cdi_program_id"],
        "coder_user_id": e["coder_user_id"],
        "coder_drg_code": e["coder_drg_code"],
        "coder_drg_weight": e["coder_drg_weight"],
        "cdi_drg_code": e["cdi_drg_code"],
        "cdi_drg_weight": e["cdi_drg_weight"],
        "resolution_note": e["resolution_note"],
        "status": e["status"],
    })
    return out


def target_out(t):
    out = _common(t)
    out.update({
        "cdi_program_id": t["cdi_program_id"],
        "drg_code": t["drg_code"],
        "required_evidence_tags": list(t["required_evidence_tags"]),
        "severity_floor": t["severity_floor"],
        "active_from_period": t["active_from_period"],
        "active_to_period": t["active_to_period"],
    })
    return out


def education_event_out(e):
    out = _common(e)
    out.update({
        "provider_id": e["provider_id"],
        "cdi_program_id": e["cdi_program_id"],
        "pattern_tag": e["pattern_tag"],
        "points_deducted": e["points_deducted"],
        "source_query_id": e["source_query_id"],
        "note": e["note"],
        "recorded_period": e["recorded_period"],
    })
    return out


def snapshot_out(s):
    out = _common(s)
    out.update({
        "cdi_program_id": s["cdi_program_id"],
        "as_of_period": s["as_of_period"],
        "case_count": s["case_count"],
        "unadjusted_cmi": s["unadjusted_cmi"],
        "adjusted_cmi": s["adjusted_cmi"],
        "cdi_lift": s["cdi_lift"],
        "denial_target_misses": s["denial_target_misses"],
    })
    return out
