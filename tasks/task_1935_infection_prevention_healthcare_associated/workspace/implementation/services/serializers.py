"""Entity -> JSON serializers (public views)."""
from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _dt(v):
    return fmt_dt(v) if v is not None else None


def facility_view(f):
    d = _common(f)
    d.update({
        "name": f["name"],
        "nhsn_org_id": f["nhsn_org_id"],
        "clabsi_baseline_per_1000": f["clabsi_baseline_per_1000"],
        "cauti_baseline_per_1000": f["cauti_baseline_per_1000"],
        "ssi_baseline_per_procedure": f["ssi_baseline_per_procedure"],
        "sir_high_threshold": f["sir_high_threshold"],
        "hh_min_opportunities": f["hh_min_opportunities"],
    })
    return d


def unit_view(u):
    d = _common(u)
    d.update({
        "facility_id": u["facility_id"],
        "name": u["name"],
        "unit_type": u["unit_type"],
        "nhsn_location_code": u["nhsn_location_code"],
        "surveillance_posture": u["surveillance_posture"],
    })
    return d


def patient_view(p):
    d = _common(p)
    d.update({
        "mrn": p["mrn"],
        "admitted_at": _dt(p["admitted_at"]),
        "unit_id": p["unit_id"],
        "current_unit_id": p["current_unit_id"],
        "unit_stays": [
            {
                "unit_id": s["unit_id"],
                "arrived_at": _dt(s["arrived_at"]),
                "departed_at": _dt(s["departed_at"]),
            }
            for s in p["unit_stays"]
        ],
        "discharged_at": _dt(p["discharged_at"]),
        "status": p["status"],
    })
    return d


def employee_view(e):
    d = _common(e)
    d.update({
        "employee_code": e["employee_code"],
        "role_title": e["role_title"],
        "home_unit_id": e["home_unit_id"],
    })
    return d


def device_episode_view(ep):
    d = _common(ep)
    d.update({
        "patient_id": ep["patient_id"],
        "unit_id": ep["unit_id"],
        "device_type": ep["device_type"],
        "placed_at": _dt(ep["placed_at"]),
        "removed_at": _dt(ep["removed_at"]),
        "status": ep["status"],
    })
    return d


def procedure_view(pr):
    d = _common(pr)
    d.update({
        "patient_id": pr["patient_id"],
        "unit_id": pr["unit_id"],
        "procedure_code": pr["procedure_code"],
        "performed_at": _dt(pr["performed_at"]),
        "duration_minutes": pr["duration_minutes"],
        "asa_score": pr["asa_score"],
        "wound_class": pr["wound_class"],
        "implant": pr["implant"],
    })
    return d


def case_view(c):
    d = _common(c)
    d.update({
        "patient_id": c["patient_id"],
        "unit_id": c["unit_id"],
        "case_type": c["case_type"],
        "suspected_organism": c["suspected_organism"],
        "first_positive_specimen_at": _dt(c["first_positive_specimen_at"]),
        "surgical_procedure_id": c["surgical_procedure_id"],
        "linked_device_episode_id": c["linked_device_episode_id"],
        "infection_window_start": _dt(c["infection_window_start"]),
        "infection_window_end": _dt(c["infection_window_end"]),
        "date_of_event": _dt(c["date_of_event"]),
        "is_hai": c["is_hai"],
        "rit_blocked_until": _dt(c["rit_blocked_until"]),
        "ssi_depth": c["ssi_depth"],
        "status": c["status"],
        "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        "adjudication_rationale": c["adjudication_rationale"],
    })
    return d


def ddc_view(r):
    d = _common(r)
    d.update({
        "unit_id": r["unit_id"],
        "count_date": _dt(r["count_date"]),
        "central_line_days": r["central_line_days"],
        "urinary_catheter_days": r["urinary_catheter_days"],
        "ventilator_days": r["ventilator_days"],
        "patient_days": r["patient_days"],
        "status": r["status"],
    })
    return d


def _num(v):
    """Rounded Decimal -> JSON number (float); None passthrough."""
    if v is None:
        return None
    return float(v)


def summary_view(s):
    d = _common(s)
    d.update({
        "unit_id": s["unit_id"],
        "month": s["month"],
        "central_line_days": s["central_line_days"],
        "urinary_catheter_days": s["urinary_catheter_days"],
        "ventilator_days": s["ventilator_days"],
        "patient_days_total": s["patient_days_total"],
        "procedure_count": s["procedure_count"],
        "clabsi_count": s["clabsi_count"],
        "cauti_count": s["cauti_count"],
        "ssi_count": s["ssi_count"],
        "provisional_clabsi_count": s["provisional_clabsi_count"],
        "provisional_cauti_count": s["provisional_cauti_count"],
        "provisional_ssi_count": s["provisional_ssi_count"],
        "predicted_clabsi": _num(s["predicted_clabsi"]),
        "predicted_cauti": _num(s["predicted_cauti"]),
        "predicted_ssi": _num(s["predicted_ssi"]),
        "sir_clabsi": _num(s["sir_clabsi"]),
        "sir_cauti": _num(s["sir_cauti"]),
        "sir_ssi": _num(s["sir_ssi"]),
        "provisional_sir_clabsi": _num(s["provisional_sir_clabsi"]),
        "provisional_sir_cauti": _num(s["provisional_sir_cauti"]),
        "provisional_sir_ssi": _num(s["provisional_sir_ssi"]),
        "sir_flag": s["sir_flag"],
        "status": s["status"],
        "amendment_count": s["amendment_count"],
        "submitted_by_user_id": s["submitted_by_user_id"],
        "accepted_by_user_id": s["accepted_by_user_id"],
    })
    return d


def outbreak_view(o):
    d = _common(o)
    d.update({
        "unit_id": o["unit_id"],
        "organism": o["organism"],
        "origin": o["origin"],
        "detection_window_start": _dt(o["detection_window_start"]),
        "detection_window_end": _dt(o["detection_window_end"]),
        "trigger_case_ids": list(o["trigger_case_ids"]),
        "contributing_case_count": o["contributing_case_count"],
        "status": o["status"],
    })
    return d


def isolation_order_view(o):
    d = _common(o)
    d.update({
        "patient_id": o["patient_id"],
        "unit_id": o["unit_id"],
        "precaution_type": o["precaution_type"],
        "ordered_by_user_id": o["ordered_by_user_id"],
        "ordered_at": _dt(o["ordered_at"]),
        "started_at": _dt(o["started_at"]),
        "discontinued_at": _dt(o["discontinued_at"]),
        "status": o["status"],
        "compliance_status": o["compliance_status"],
    })
    return d


def audit_view(a):
    d = _common(a)
    d.update({
        "isolation_order_id": a["isolation_order_id"],
        "auditor_user_id": a["auditor_user_id"],
        "observed_at": _dt(a["observed_at"]),
        "elements_checked": a["elements_checked"],
        "elements_passed": a["elements_passed"],
        "compliance_pct": _num(a["compliance_pct"]),
        "outcome": a["outcome"],
    })
    return d


def observation_view(o):
    d = _common(o)
    d.update({
        "unit_id": o["unit_id"],
        "observer_user_id": o["observer_user_id"],
        "observed_at": _dt(o["observed_at"]),
        "opportunity_type": o["opportunity_type"],
        "action": o["action"],
    })
    return d


def exposure_view(e, now=None):
    """current_stage_overdue is computed at read time from the logical clock."""
    from util import clock
    now = clock.get() if now is None else now
    overdue = (
        e["next_draw_due_at"] is not None
        and now > e["next_draw_due_at"]
        and e["status"] in ("REPORTED", "SOURCE_EVALUATED", "BASELINE_COMPLETE", "FOLLOWUP_IN_PROGRESS")
    )
    d = _common(e)
    d.update({
        "employee_id": e["employee_id"],
        "source_patient_id": e["source_patient_id"],
        "exposure_type": e["exposure_type"],
        "occurred_at": _dt(e["occurred_at"]),
        "source_hbv_status": e["source_hbv_status"],
        "source_hcv_status": e["source_hcv_status"],
        "source_hiv_status": e["source_hiv_status"],
        "recorded_stages": [
            {"stage": s["stage"], "drawn_at": _dt(s["drawn_at"]), "result": s["result"]}
            for s in e["recorded_stages"]
        ],
        "next_draw_due_at": _dt(e["next_draw_due_at"]),
        "current_stage_overdue": overdue,
        "status": e["status"],
    })
    return d


def cap_view(c):
    d = _common(c)
    d.update({
        "unit_id": c["unit_id"],
        "source_type": c["source_type"],
        "source_ref_id": c["source_ref_id"],
        "description": c["description"],
        "due_date": _dt(c["due_date"]),
        "evidence_notes": c["evidence_notes"],
        "failure_count": c["failure_count"],
        "created_by_user_id": c["created_by_user_id"],
        "verified_by_user_id": c["verified_by_user_id"],
        "status": c["status"],
    })
    return d
