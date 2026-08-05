"""Resource serialisation.  Every datetime goes through the one shared renderer."""

from clock import render_datetime


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": render_datetime(rec["created_at"])}
    if versioned:
        out["updated_at"] = render_datetime(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def defendant_json(rec):
    out = {
        "case_number": rec["case_number"],
        "full_name": rec["full_name"],
        "date_of_birth": rec["date_of_birth"],
        "indigent": rec["indigent"],
        "supervision_status": rec["supervision_status"],
        "supervision_level": rec["supervision_level"],
        "risk_tier": rec["risk_tier"],
        "cumulative_violation_score": rec["cumulative_violation_score"],
        "balance_owed_cents": rec["balance_owed_cents"],
    }
    out.update(_common(rec))
    return out


def assessment_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "instrument_type": rec["instrument_type"],
        "prior_failures": rec["prior_failures"],
        "pending_charges_count": rec["pending_charges_count"],
        "pending_violent_charge": rec["pending_violent_charge"],
        "employment_status": rec["employment_status"],
        "residence_stability": rec["residence_stability"],
        "substance_flag": rec["substance_flag"],
        "status": rec["status"],
        "raw_score": rec["raw_score"],
        "recommended_level": rec["recommended_level"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
    }
    out.update(_common(rec))
    return out


def release_order_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "assessment_id": rec["assessment_id"],
        "decision": rec["decision"],
        "ordered_conditions": list(rec["ordered_conditions"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def check_in_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "due_at": render_datetime(rec["due_at"]),
        "completed_at": render_datetime(rec["completed_at"]),
        "origin": rec["origin"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def em_device_json(rec):
    out = {
        "model_name": rec["model_name"],
        "total_units": rec["total_units"],
        "available_units": rec["available_units"],
    }
    out.update(_common(rec))
    return out


def em_enrollment_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "device_id": rec["device_id"],
        "status": rec["status"],
        "activated_at": render_datetime(rec["activated_at"]),
    }
    out.update(_common(rec))
    return out


def curfew_window_json(rec):
    out = {
        "enrollment_id": rec["enrollment_id"],
        "day_of_week": rec["day_of_week"],
        "start_minute": rec["start_minute"],
        "end_minute": rec["end_minute"],
    }
    out.update(_common(rec, versioned=False))
    return out


def location_ping_json(rec):
    out = {
        "enrollment_id": rec["enrollment_id"],
        "pinged_at": render_datetime(rec["pinged_at"]),
        "at_home": rec["at_home"],
        "is_curfew_violation": rec["is_curfew_violation"],
    }
    out.update(_common(rec, versioned=False))
    return out


def violation_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "violation_type": rec["violation_type"],
        "severity": rec["severity"],
        "severity_points": rec["severity_points"],
        "status": rec["status"],
        "reported_by_user_id": rec["reported_by_user_id"],
        "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
        "adjudicated_at": render_datetime(rec["adjudicated_at"]),
        "source_ref": rec["source_ref"],
    }
    out.update(_common(rec))
    return out


def court_event_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "hearing_at": render_datetime(rec["hearing_at"]),
        "reminder_lead_days": rec["reminder_lead_days"],
        "reminder_due_at": render_datetime(rec["reminder_due_at"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def drug_test_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "site_id": rec["site_id"],
        "test_kind": rec["test_kind"],
        "slot_start": render_datetime(rec["slot_start"]),
        "slot_end": render_datetime(rec["slot_end"]),
        "status": rec["status"],
        "result_recorded_at": render_datetime(rec["result_recorded_at"]),
    }
    out.update(_common(rec))
    return out


def testing_site_json(rec):
    out = {
        "name": rec["name"],
        "slot_capacity": rec["slot_capacity"],
    }
    out.update(_common(rec))
    return out


def ledger_entry_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "entry_type": rec["entry_type"],
        "amount_cents": rec["amount_cents"],
        "reverses_entry_id": rec["reverses_entry_id"],
        "source": rec["source"],
    }
    out.update(_common(rec, versioned=False))
    return out


def level_adjustment_json(rec):
    out = {
        "defendant_id": rec["defendant_id"],
        "from_level": rec["from_level"],
        "to_level": rec["to_level"],
        "source": rec["source"],
        "reason": rec["reason"],
        "adjusted_by_user_id": rec["adjusted_by_user_id"],
    }
    out.update(_common(rec, versioned=False))
    return out
