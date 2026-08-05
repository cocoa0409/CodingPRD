"""Entity -> JSON projections, including the read-time derived fields (PRD 2.4)."""

import calc
import store
from timeutil import out


def _common(row, with_version=True):
    body = {"id": row["id"], "created_at": out(row["created_at"])}
    if with_version:
        body["updated_at"] = out(row.get("updated_at"))
        body["version"] = row.get("version")
    return body


def inmate(row):
    body = _common(row)
    body.update({
        "booking_number": row["booking_number"],
        "full_name": row["full_name"],
        "facility_code": row["facility_code"],
        "custody_level": row["custody_level"],
        "booked_at": out(row["booked_at"]),
        "admission_type": row["admission_type"],
        "prior_full_assessment_at": out(row.get("prior_full_assessment_at")),
        "scheduled_release_date": out(row.get("scheduled_release_date")),
        "custody_status": row["custody_status"],
        "records_state": row["records_state"],
        "account_balance_cents": row["account_balance_cents"],
        "indigent_flag": calc.indigency_determination(row),
        "open_sick_call_count": calc.open_sick_call_count(row["id"]),
        "no_show_count": calc.inmate_no_show_count(row["id"]),
    })
    return body


def intake_screening(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "screening_type": row["screening_type"],
        "due_at": out(row["due_at"]),
        "completed_at": out(row.get("completed_at")),
        "status": row["status"],
        "findings_code": row.get("findings_code"),
        "completed_late": row.get("completed_late"),
    })
    return body


def chronic_enrollment(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "condition_code": row["condition_code"],
        "severity": row["severity"],
        "tier": row["tier"],
        "periodicity_days": row["periodicity_days"],
        "enrolled_at": out(row["enrolled_at"]),
        "last_visit_at": out(row.get("last_visit_at")),
        "next_due_date": out(row.get("next_due_date")),
        "missed_visit_count": row["missed_visit_count"],
        "status": row["status"],
        "escalated": row["escalated"],
    })
    return body


def chronic_visit(row):
    # Immutable audit record: id + created_at only, no updated_at, no version.
    body = _common(row, with_version=False)
    body.update({
        "enrollment_id": row["enrollment_id"],
        "recorded_at": out(row["recorded_at"]),
        "outcome": row["outcome"],
        "due_at_snapshot": out(row.get("due_at_snapshot")),
        "recorded_by_user_id": row["recorded_by_user_id"],
    })
    return body


def sick_call(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "complaint_text": row["complaint_text"],
        "submitted_at": out(row["submitted_at"]),
        "acuity": row.get("acuity"),
        "triaged_at": out(row.get("triaged_at")),
        "deadline_anchor_at": out(row.get("deadline_anchor_at")),
        "response_deadline_at": out(row.get("response_deadline_at")),
        "seen_at": out(row.get("seen_at")),
        "sla_breached": calc.sick_call_sla_breached(row),
        "retriage_count": row["retriage_count"],
        "encounter_type": row["encounter_type"],
        "status": row["status"],
        "copay_charge_id": row.get("copay_charge_id"),
    })
    return body


def medication_order(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "drug_name": row["drug_name"],
        "drug_class": row["drug_class"],
        "route_mode": row["route_mode"],
        "doses_per_day": row["doses_per_day"],
        "start_date": out(row["start_date"]),
        "end_date": out(row["end_date"]),
        "units_dispensed": row["units_dispensed"],
        "units_returned": row["units_returned"],
        "consecutive_missed_count": row["consecutive_missed_count"],
        "consecutive_refused_count": row["consecutive_refused_count"],
        "adherence_pct": row["adherence_pct"],
        "escalated_to_prescriber": row["escalated_to_prescriber"],
        "forced_dot": row["forced_dot"],
        "status": row["status"],
        "prescriber_user_id": row["prescriber_user_id"],
    })
    return body


def medication_administration(row):
    body = _common(row)
    body.update({
        "order_id": row["order_id"],
        "scheduled_at": out(row["scheduled_at"]),
        "acted_at": out(row.get("acted_at")),
        "outcome": row["outcome"],
        "observed_swallow": row.get("observed_swallow"),
        "diversion_observed": row.get("diversion_observed"),
        "timing_class": row.get("timing_class"),
        "administered_by_user_id": row.get("administered_by_user_id"),
    })
    return body


def specialty_referral(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "specialty": row["specialty"],
        "urgency": row["urgency"],
        "requested_at": out(row["requested_at"]),
        "status": row["status"],
        "no_show_count": row["no_show_count"],
        "authorized_at": out(row.get("authorized_at")),
    })
    return body


def utilization_review(row):
    body = _common(row)
    body.update({
        "referral_id": row["referral_id"],
        "opened_at": out(row["opened_at"]),
        "turnaround_deadline_at": out(row.get("turnaround_deadline_at")),
        "decision": row.get("decision"),
        "decided_at": out(row.get("decided_at")),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "peer_reviewer_user_id": row.get("peer_reviewer_user_id"),
        "defer_count": row["defer_count"],
        "turnaround_breached": calc.ur_turnaround_breached(row),
        "retrospective": row["retrospective"],
        "status": row["status"],
    })
    return body


def transport_order(row):
    body = _common(row)
    body.update({
        "referral_id": row["referral_id"],
        "appointment_at": out(row["appointment_at"]),
        "required_escort_level": row["required_escort_level"],
        "assigned_escort_level": row.get("assigned_escort_level"),
        "lead_minutes": row["lead_minutes"],
        "status": row["status"],
        "cancel_reason": row.get("cancel_reason"),
    })
    return body


def copay_charge(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "encounter_type": row["encounter_type"],
        "source_sick_call_id": row.get("source_sick_call_id"),
        "scheduled_amount_cents": row["scheduled_amount_cents"],
        "amount_cents": row["amount_cents"],
        "charge_variant": row["charge_variant"],
        "indigency_snapshot": row["indigency_snapshot"],
        "status": row["status"],
        "reversal_grievance_id": row.get("reversal_grievance_id"),
    })
    return body


def ledger_entry(row):
    # Immutable audit record: id + created_at only, no updated_at, no version.
    body = _common(row, with_version=False)
    body.update({
        "inmate_id": row["inmate_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "source_copay_charge_id": row.get("source_copay_charge_id"),
        "memo": row.get("memo", ""),
    })
    return body


def grievance(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "subject_copay_charge_id": row.get("subject_copay_charge_id"),
        "grievance_text": row["grievance_text"],
        "grieved_event_at": out(row["grieved_event_at"]),
        "stage": row["stage"],
        "stage_entered_at": out(row["stage_entered_at"]),
        "response_due_at": out(row.get("response_due_at")),
        "response_breached": calc.grievance_response_breached(row),
        "remand_count": row["remand_count"],
        "outcome": row.get("outcome"),
        "status": row["status"],
    })
    return body


def release_plan(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "release_type": row["release_type"],
        "planned_release_at": out(row["planned_release_at"]),
        "bridge_supply_total_days": row["bridge_supply_total_days"],
        "bridge_supply_lines": row["bridge_supply_lines"],
        "reentry_referral_required": row["reentry_referral_required"],
        "records_packet_ready": row["records_packet_ready"],
        "status": row["status"],
    })
    return body


def mortality_review(row):
    body = _common(row)
    body.update({
        "inmate_id": row["inmate_id"],
        "death_at": out(row["death_at"]),
        "manner": row["manner"],
        "due_at": out(row["due_at"]),
        "corrective_action_count": row["corrective_action_count"],
        "corrective_actions": [
            {"action_text": a["action_text"], "recorded_at": out(a["recorded_at"])}
            for a in row["corrective_actions"]
        ],
        "closed_at": out(row.get("closed_at")),
        "closed_late": row["closed_late"],
        "status": row["status"],
    })
    return body


def many(fn, rows):
    return [fn(r) for r in rows]


def paginate(rows, key="created_at"):
    return store.sort_rows(rows, key)
