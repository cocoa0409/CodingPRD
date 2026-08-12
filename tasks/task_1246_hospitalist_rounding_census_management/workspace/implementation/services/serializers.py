"""Entity -> JSON serializers with the exact field names and formats."""

import clock


def _dt(v):
    return clock.iso(v) if v is not None else None


def _num(v):
    """Decimal -> float for JSON."""
    if v is None:
        return None
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def base(e):
    return {
        "id": e["id"],
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
    }


def hospitalist(h):
    d = base(h)
    d.update({
        "full_name": h["full_name"],
        "specialty": h["specialty"],
        "employment_status": h["employment_status"],
        "max_census_cap": h["max_census_cap"],
        "night_eligible": h["night_eligible"],
        "current_census": h["current_census"],
        "pending_offers": h["pending_offers"],
        "distribution_eligible": h["distribution_eligible"],
    })
    return d


def patient(p):
    d = base(p)
    d.update({
        "mrn": p["mrn"],
        "acuity": p["acuity"],
        "admit_source": p["admit_source"],
        "stay_type": p["stay_type"],
        "admitted_at": _dt(p["admitted_at"]),
        "admission_status": p["admission_status"],
        "observation_status": p["observation_status"],
        "observation_started_at": _dt(p.get("observation_started_at")),
        "los_midnights": p["los_midnights"],
        "los_blocks": p["los_blocks"],
        "los_alert_flag": p["los_alert_flag"],
    })
    return d


def shift(s):
    d = base(s)
    d.update({
        "hospitalist_id": s["hospitalist_id"],
        "shift_type": s["shift_type"],
        "start_at": _dt(s["start_at"]),
        "end_at": _dt(s["end_at"]),
        "state": s["state"],
    })
    return d


def admission(a):
    d = base(a)
    d.update({
        "patient_id": a["patient_id"],
        "status": a["status"],
        "offered_to_hospitalist_id": a["offered_to_hospitalist_id"],
        "declined_hospitalist_ids": list(a["declined_hospitalist_ids"]),
        "distribution_score": _num(a["distribution_score"]),
        "assignment_id": a["assignment_id"],
        "offered_at": _dt(a.get("offered_at")),
        "decided_at": _dt(a.get("decided_at")),
    })
    return d


def assignment(a):
    d = base(a)
    d.update({
        "patient_id": a["patient_id"],
        "hospitalist_id": a["hospitalist_id"],
        "status": a["status"],
        "continuity_flag": a["continuity_flag"],
        "assigned_at": _dt(a["assigned_at"]),
        "closed_at": _dt(a.get("closed_at")),
        "close_reason": a.get("close_reason"),
        "transfer_target_hospitalist_id": a.get("transfer_target_hospitalist_id"),
    })
    return d


def discharge_order(o):
    d = base(o)
    d.update({
        "patient_id": o["patient_id"],
        "ordering_hospitalist_id": o["ordering_hospitalist_id"],
        "status": o["status"],
        "target_discharge_at": _dt(o["target_discharge_at"]),
        "ordered_at": _dt(o.get("ordered_at")),
        "executed_at": _dt(o.get("executed_at")),
        "meets_throughput_target": o.get("meets_throughput_target"),
    })
    return d


def handoff(h):
    d = base(h)
    d.update({
        "shift_id": h["shift_id"],
        "receiving_hospitalist_id": h["receiving_hospitalist_id"],
        "patient_ids": list(h["patient_ids"]),
        "status": h["status"],
        "required_patient_count": h["required_patient_count"],
        "covered_patient_count": h["covered_patient_count"],
        "open_item_count": h["open_item_count"],
        "completeness_score": _num(h["completeness_score"]),
        "submitted_at": _dt(h.get("submitted_at")),
        "reviewed_at": _dt(h.get("reviewed_at")),
        "return_reason": h.get("return_reason"),
    })
    return d


def consult_request(c):
    d = base(c)
    d.update({
        "patient_id": c["patient_id"],
        "requesting_hospitalist_id": c["requesting_hospitalist_id"],
        "specialty": c["specialty"],
        "priority": c["priority"],
        "reason": c["reason"],
        "status": c["status"],
        "requested_at": _dt(c["requested_at"]),
        "sla_deadline": _dt(c["sla_deadline"]),
        "sla_breached": c["sla_breached"],
        "acknowledged_at": _dt(c.get("acknowledged_at")),
        "completed_at": _dt(c.get("completed_at")),
        "escalation_count": c["escalation_count"],
        "response_minutes": _num(c.get("response_minutes")),
    })
    return d


def encounter(e):
    d = base(e)
    d.update({
        "hospitalist_id": e["hospitalist_id"],
        "patient_id": e["patient_id"],
        "encounter_type": e["encounter_type"],
        "occurred_on": e["occurred_on"],
        "wrvu_value": _num(e["wrvu_value"]),
        "estimated_wrvu": _num(e["estimated_wrvu"]),
        "status": e["status"],
        "productivity_report_id": e.get("productivity_report_id"),
    })
    return d


def productivity_report(r):
    d = base(r)
    d.update({
        "hospitalist_id": r["hospitalist_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "status": r["status"],
        "encounter_count": r["encounter_count"],
        "total_wrvu_provisional": _num(r["total_wrvu_provisional"]),
        "total_wrvu_final": _num(r.get("total_wrvu_final")),
        "wrvu_variance": _num(r.get("wrvu_variance")),
        "generated_at": _dt(r["generated_at"]),
        "finalized_at": _dt(r.get("finalized_at")),
    })
    return d


def coverage_window(w):
    d = base(w)
    d.update({
        "window_date": w["window_date"],
        "window_type": w["window_type"],
        "start_at": _dt(w["start_at"]),
        "end_at": _dt(w["end_at"]),
        "capacity": w["capacity"],
        "enrolled_hospitalist_ids": list(w["enrolled_hospitalist_ids"]),
        "enrolled_count": w["enrolled_count"],
        "status": w["status"],
        "current_load": _num(w["current_load"]),
    })
    return d
