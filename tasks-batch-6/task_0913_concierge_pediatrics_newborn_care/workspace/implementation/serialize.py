"""Entity -> JSON payload.  Computed fields are derived here, on every read."""
import constants as C
import calc
from store import db
from timeutil import fmt_date, fmt_datetime


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_datetime(row["created_at"]),
        "updated_at": fmt_datetime(row["updated_at"]),
        "version": row["version"],
    }


def plan_json(row):
    out = _common(row)
    out.update(
        {
            "tier": row["tier"],
            "monthly_rate_cents": row["monthly_rate_cents"],
            "included_lactation_consults": row["included_lactation_consults"],
            "included_sleep_consults": row["included_sleep_consults"],
            "form_sla_hours": row["form_sla_hours"],
            "after_hours_surcharge_waived": row["after_hours_surcharge_waived"],
            "overage_consult_fee_cents": row["overage_consult_fee_cents"],
        }
    )
    return out


def physician_json(row):
    occupancy, available = calc.physician_occupancy(row)
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "panel_slot_cap": row["panel_slot_cap"],
            "licensed_state_codes": list(row["licensed_state_codes"]),
            "weighted_occupancy": occupancy,
            "available_panel_weight": available,
        }
    )
    return out


def family_json(row):
    count = 0
    for m in db.memberships.values():
        if m["family_id"] == row["id"] and m["status"] in C.MEMBERSHIP_OCCUPYING_STATUSES:
            count += 1
    out = _common(row)
    out.update(
        {
            "household_name": row["household_name"],
            "family_monthly_cap_cents": row["family_monthly_cap_cents"],
            "active_membership_count": count,
        }
    )
    return out


def policy_json(row):
    out = _common(row)
    out.update(
        {
            "family_id": row["family_id"],
            "carrier_name": row["carrier_name"],
            "deductible_cents": row["deductible_cents"],
            "deductible_met_cents": row["deductible_met_cents"],
            "coinsurance_rate": row["coinsurance_rate"],
            "status": row["status"],
        }
    )
    return out


def child_json(row):
    age_days = calc.child_age_days(row)
    out = _common(row)
    out.update(
        {
            "family_id": row["family_id"],
            "first_name": row["first_name"],
            "date_of_birth": fmt_date(row["date_of_birth"]),
            "age_days": age_days,
            "current_slot_weight": calc.slot_weight_for_age(age_days),
            "immunization_complete_for_age": calc.immunization_complete_for_age(row),
        }
    )
    return out


def membership_json(row):
    if row["status"] == "CANCELLED":
        slot_weight = 0.0
    else:
        child = db.children.get(row["child_id"])
        slot_weight = calc.child_slot_weight(child) if child else 0.0
    out = _common(row)
    out.update(
        {
            "child_id": row["child_id"],
            "family_id": row["family_id"],
            "plan_id": row["plan_id"],
            "physician_id": row["physician_id"],
            "start_date": fmt_date(row["start_date"]),
            "cancellation_effective_date": fmt_date(row["cancellation_effective_date"]),
            "status": row["status"],
            "enrollment_sequence": row["enrollment_sequence"],
            "discount_pct": row["discount_pct"],
            "monthly_rate_cents": row["monthly_rate_cents"],
            "slot_weight": slot_weight,
            "suspension_reason": row["suspension_reason"],
        }
    )
    return out


def waitlist_json(row):
    child = db.children.get(row["child_id"])
    out = _common(row)
    out.update(
        {
            "physician_id": row["physician_id"],
            "child_id": row["child_id"],
            "requested_plan_id": row["requested_plan_id"],
            "promoted_membership_id": row["promoted_membership_id"],
            "candidate_slot_weight": calc.child_slot_weight(child) if child else 0.0,
            "status": row["status"],
        }
    )
    return out


def grant_json(row):
    available = row["granted_count"] - row["booked_count"] - row["consumed_count"]
    if available < 0:
        available = 0
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "benefit_type": row["benefit_type"],
            "membership_year_index": row["membership_year_index"],
            "granted_count": row["granted_count"],
            "booked_count": row["booked_count"],
            "consumed_count": row["consumed_count"],
            "released_count": row["released_count"],
            "overage_count": row["overage_count"],
            "available_count": available,
            "status": row["status"],
        }
    )
    return out


def booking_json(row):
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "grant_id": row["grant_id"],
            "consultant_physician_id": row["consultant_physician_id"],
            "consult_type": row["consult_type"],
            "scheduled_start": fmt_datetime(row["scheduled_start"]),
            "scheduled_end": fmt_datetime(row["scheduled_end"]),
            "modality": row["modality"],
            "patient_state_code": row["patient_state_code"],
            "coverage_route": row["coverage_route"],
            "reschedule_count": row["reschedule_count"],
            "status": row["status"],
        }
    )
    return out


def well_visit_json(row):
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "child_id": row["child_id"],
            "milestone_code": row["milestone_code"],
            "target_date": fmt_date(row["target_date"]),
            "window_open_date": fmt_date(row["window_open_date"]),
            "window_close_date": fmt_date(row["window_close_date"]),
            "scheduled_date": fmt_date(row["scheduled_date"]),
            "completed_date": fmt_date(row["completed_date"]),
            "punctuality": row["punctuality"],
            "status": row["status"],
        }
    )
    return out


def dose_json(row):
    out = _common(row)
    out.update(
        {
            "child_id": row["child_id"],
            "prior_valid_dose_id": row["prior_valid_dose_id"],
            "vaccine_code": row["vaccine_code"],
            "administered_date": fmt_date(row["administered_date"]),
            "age_days_at_administration": row["age_days_at_administration"],
            "effective_series_index": row["effective_series_index"],
            "interval_days_since_prior": row["interval_days_since_prior"],
            "manually_invalidated": row["manually_invalidated"],
            "invalidation_reason_note": row["invalidation_reason_note"],
            "invalid_reason": row["invalid_reason"],
            "validity": row["validity"],
        }
    )
    return out


def encounter_json(row):
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "child_id": row["child_id"],
            "encounter_type": row["encounter_type"],
            "modality": row["modality"],
            "patient_state_code": row["patient_state_code"],
            "started_at": fmt_datetime(row["started_at"]),
            "ends_at": fmt_datetime(row["ends_at"]),
            "after_hours": row["after_hours"],
            "after_hours_reason": row["after_hours_reason"],
            "surcharge_cents": row["surcharge_cents"],
            "clinical_status": row["clinical_status"],
            "billing_status": row["billing_status"],
            "clinical_note": row["clinical_note"],
            "cancel_reason": row["cancel_reason"],
        }
    )
    return out


def service_line_json(row):
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "encounter_id": row["encounter_id"],
            "consult_booking_id": row["consult_booking_id"],
            "well_visit_id": row["well_visit_id"],
            "policy_id": row["policy_id"],
            "service_code": row["service_code"],
            "route": row["route"],
            "billed_amount_cents": row["billed_amount_cents"],
            "allowed_amount_cents": row["allowed_amount_cents"],
            "write_off_cents": row["write_off_cents"],
            "deductible_applied_cents": row["deductible_applied_cents"],
            "coinsurance_cents": row["coinsurance_cents"],
            "plan_paid_cents": row["plan_paid_cents"],
            "patient_responsibility_cents": row["patient_responsibility_cents"],
            "membership_covered_cents": row["membership_covered_cents"],
            "payment_received_cents": row["payment_received_cents"],
            "submitted_by_user_id": row["submitted_by_user_id"],
            "adjudicated_by_user_id": row["adjudicated_by_user_id"],
            "status": row["status"],
        }
    )
    return out


def invoice_json(row):
    out = _common(row)
    out.update(
        {
            "family_id": row["family_id"],
            "cycle_start_date": fmt_date(row["cycle_start_date"]),
            "cycle_end_date": fmt_date(row["cycle_end_date"]),
            "days_in_cycle": row["days_in_cycle"],
            "lines": [dict(line) for line in row["lines"]],
            "subtotal_cents": row["subtotal_cents"],
            "cap_adjustment_cents": row["cap_adjustment_cents"],
            "total_cents": row["total_cents"],
            "issued_date": fmt_date(row["issued_date"]),
            "due_date": fmt_date(row["due_date"]),
            "paid_date": fmt_date(row["paid_date"]),
            "amount_paid_cents": row["amount_paid_cents"],
            "status": row["status"],
        }
    )
    return out


def form_request_json(row):
    out = _common(row)
    out.update(
        {
            "membership_id": row["membership_id"],
            "child_id": row["child_id"],
            "form_type": row["form_type"],
            "needed_by_date": fmt_date(row["needed_by_date"]),
            "requested_at": fmt_datetime(row["requested_at"]),
            "due_at": fmt_datetime(row["due_at"]),
            "issued_at": fmt_datetime(row["issued_at"]),
            "sla_met": row["sla_met"],
            "blocked_reason": row["blocked_reason"],
            "status": row["status"],
        }
    )
    return out
