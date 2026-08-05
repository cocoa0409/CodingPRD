"""Resource representations. Only fields PRD declares are ever emitted."""

import derived


def _money(value):
    return float(value)


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def patient(row):
    out = _common(row)
    out.update({
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "home_distance_km": row["home_distance_km"],
        "primary_diagnosis_code": row["primary_diagnosis_code"],
        "diet_restriction": row["diet_restriction"],
        "broadband_verified": row["broadband_verified"],
        "caregiver_present": row["caregiver_present"],
        "status": row["status"],
    })
    return out


def referral(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "origin": row["origin"],
        "qualifying_condition_code": row["qualifying_condition_code"],
        "acuity": row["acuity"],
        "referring_physician_user_id": row["referring_physician_user_id"],
        "status": row["status"],
        "first_failed_gauntlet_rung": row["first_failed_gauntlet_rung"],
    })
    return out


def assessment(row):
    out = _common(row)
    out.update({
        "referral_id": row["referral_id"],
        "in_person_eval_at": row["in_person_eval_at"],
        "home_safety_outcome": row["home_safety_outcome"],
        "broadband_check": row["broadband_check"],
        "caregiver_present_confirmed": row["caregiver_present_confirmed"],
        "consent_signed": row["consent_signed"],
        "assessor_user_id": row["assessor_user_id"],
    })
    return out


def episode(row):
    service, billable, carved, pending = derived.episode_day_ledger(row["id"])
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "referral_id": row["referral_id"],
        "program_track": row["program_track"],
        "acuity": row["acuity"],
        "status": row["status"],
        "admitted_at": row["admitted_at"],
        "physician_eval_at": row["physician_eval_at"],
        "returned_at": row["returned_at"],
        "discharged_at": row["discharged_at"],
        "readmission_count": row["readmission_count"],
        "service_day_count": service,
        "billable_day_count": billable,
        "carved_out_day_count": carved,
        "pending_day_count": pending,
        "reimbursement_amount_usd": _money(derived.episode_reimbursement_amount(row)),
        "meal_credit_total_usd": _money(derived.episode_meal_credit_total(row["id"])),
        "travel_reimbursement_total_usd": _money(derived.episode_travel_total(row["id"])),
        "med_rec_signed": row["med_rec_signed"],
        "med_rec_signed_by_user_id": row["med_rec_signed_by_user_id"],
        "open_escalation_count": derived.episode_open_escalation_count(row["id"]),
    })
    return out


def episode_ledger(row):
    service, billable, carved, pending = derived.episode_day_ledger(row["id"])
    return {
        "service_day_count": service,
        "billable_day_count": billable,
        "carved_out_day_count": carved,
        "pending_day_count": pending,
        "reimbursement_amount_usd": _money(derived.episode_reimbursement_amount(row)),
        "meal_credit_total_usd": _money(derived.episode_meal_credit_total(row["id"])),
        "travel_reimbursement_total_usd": _money(derived.episode_travel_total(row["id"])),
    }


def visit(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "visit_type": row["visit_type"],
        "staff_user_id": row["staff_user_id"],
        "service_date": row["service_date"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "distance_km": row["distance_km"],
        "scheduling_status": row["scheduling_status"],
        "attestation_status": row["attestation_status"],
        "attested_by_user_id": row["attested_by_user_id"],
        "travel_payment_usd": _money(row["travel_payment_usd"]),
    })
    return out


def compliance_day(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "service_date": row["service_date"],
        "qualified_in_person_visit_count": derived.qualified_in_person_visit_count(
            row["episode_id"], row["service_date"]),
        "physician_eval_present": derived.physician_eval_present(
            row["episode_id"], row["service_date"]),
        "monitoring_lapse_minutes": derived.monitoring_lapse_minutes(
            row["episode_id"], row["service_date"]),
        "kit_deployed_all_day": row["kit_deployed_all_day"],
        "status": row["status"],
        "finalized_at": row["finalized_at"],
        "carve_out_reason": row["carve_out_reason"],
    })
    return out


def device_kit(row):
    out = _common(row)
    out.update({
        "asset_tag": row["asset_tag"],
        "assigned_episode_id": row["assigned_episode_id"],
        "status": row["status"],
        "refurb_cycle_count": row["refurb_cycle_count"],
        "deployed_at": row["deployed_at"],
        "component_count": derived.kit_component_count(row["id"]),
        "unreconciled_component_count": derived.kit_unreconciled_component_count(row["id"]),
    })
    return out


def device_component(row):
    out = _common(row)
    out.update({
        "kit_id": row["kit_id"],
        "component_type": row["component_type"],
        "serial_number": row["serial_number"],
        "replacement_cost_usd": row["replacement_cost_usd"],
        "reconciliation_status": row["reconciliation_status"],
        "reconciled_by_user_id": row["reconciled_by_user_id"],
    })
    return out


def monitoring_lapse(row):
    # PRD 2.4: append-only, so it carries only id and created_at -- no
    # updated_at and no version, and neither may appear in the payload.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "episode_id": row["episode_id"],
        "gap_start_at": row["gap_start_at"],
        "gap_end_at": row["gap_end_at"],
        "cause": row["cause"],
    }


def delivery_order(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "order_kind": row["order_kind"],
        "is_controlled": row["is_controlled"],
        "cold_chain_required": row["cold_chain_required"],
        "weight_kg": row["weight_kg"],
        "requested_by_user_id": row["requested_by_user_id"],
        "authorized_by_user_id": row["authorized_by_user_id"],
        "witness_staff_id": row["witness_staff_id"],
        "status": row["status"],
        "redelivery_count": row["redelivery_count"],
        "last_excursion_minutes": row["last_excursion_minutes"],
        "handling_fee_usd": _money(row["handling_fee_usd"]),
    })
    return out


def meal_plan(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "diet_code": row["diet_code"],
        "daily_delivery_count": row["daily_delivery_count"],
        "activated_on_date": row["activated_on_date"],
        "status": row["status"],
        "suspension_day_count": row["suspension_day_count"],
        "credited_day_count": derived.meal_plan_credited_day_count(row),
        "meal_credit_total_usd": _money(derived.meal_plan_credit_total(row)),
    })
    return out


def escalation_event(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "reason": row["reason"],
        "opened_by_user_id": row["opened_by_user_id"],
        "status": row["status"],
        "current_tier": row["current_tier"],
        "tier_entered_at": row["tier_entered_at"],
        "ack_deadline_at": row["ack_deadline_at"],
        "promotion_count": row["promotion_count"],
        "acknowledged_by_user_id": row["acknowledged_by_user_id"],
    })
    return out


def inpatient_unit(row):
    held, occupied, available = derived.unit_bed_census(row)
    out = _common(row)
    out.update({
        "unit_code": row["unit_code"],
        "total_beds": row["total_beds"],
        "held_bed_count": held,
        "occupied_bed_count": occupied,
        "available_bed_count": available,
    })
    return out


def bed_reservation(row):
    out = _common(row)
    out.update({
        "unit_id": row["unit_id"],
        "episode_id": row["episode_id"],
        "status": row["status"],
        "held_at": row["held_at"],
        "hold_expires_at": row["hold_expires_at"],
        "occupied_at": row["occupied_at"],
    })
    return out


def billing_claim(row):
    out = _common(row)
    out.update({
        "episode_id": row["episode_id"],
        "billed_day_count": row["billed_day_count"],
        "gross_amount_usd": _money(row["gross_amount_usd"]),
        "withhold_rate": float(row["withhold_rate"]),
        "withhold_amount_usd": _money(row["withhold_amount_usd"]),
        "net_payable_usd": _money(row["net_payable_usd"]),
        "paid_amount_usd": _money(row["paid_amount_usd"]),
        "status": row["status"],
        "appeal_count": row["appeal_count"],
        "denial_reason": row["denial_reason"],
    })
    return out
