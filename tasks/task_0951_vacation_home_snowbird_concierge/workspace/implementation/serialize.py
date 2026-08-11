"""Resource serialisers.

Every datetime-valued field in this module is rendered through `fmt_iso`, which
emits ISO-8601 UTC with exactly three fractional digits and a trailing `Z`.
That single rule covers server-minted stamps, caller-supplied instants echoed
back, and instants derived from caller input alike.
"""
import calc
import core
from core import fmt_iso


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_iso(row["created_at"])
    out["updated_at"] = fmt_iso(row["updated_at"])
    out["version"] = row["version"]
    return out


def owner(row):
    return _common(row, {
        "full_name": row["full_name"],
        "email": row["email"],
        "phone": row["phone"],
        "primary_residence_state": row["primary_residence_state"],
        "snowbird_flag": row["snowbird_flag"],
        "notification_preference": row["notification_preference"],
        "approval_ceiling_override_cents": row["approval_ceiling_override_cents"],
        "lifetime_credit_balance_cents": calc.owner_lifetime_credit(row["id"]),
        "status": row["status"],
    })


def prop(row):
    return _common(row, {
        "owner_id": row["owner_id"],
        "label": row["label"],
        "address_line": row["address_line"],
        "state_code": row["state_code"],
        "travel_distance_miles": row["travel_distance_miles"],
        "travel_zone": row["travel_zone"],
        "seasonal_state": row["seasonal_state"],
        "occupancy_state": row["occupancy_state"],
        "freeze_setpoint_f": row["freeze_setpoint_f"],
        "last_interior_temp_f": row["last_interior_temp_f"],
        "last_temp_reading_at": fmt_iso(row["last_temp_reading_at"]),
        "freeze_risk_score": row["freeze_risk_score"],
        "risk_posture": row["risk_posture"],
        "winterization_completeness_pct": row["winterization_completeness_pct"],
        "false_alarm_count_window": calc.false_alarm_count_window(row["id"]),
        "open_critical_finding_count": calc.open_critical_finding_count(row["id"]),
        "storm_hold_flag": row["storm_hold_flag"],
        "rental_program_enrolled": row["rental_program_enrolled"],
    })


def service_plan(row):
    return _common(row, {
        "tier": row["tier"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "included_visit_units": row["included_visit_units"],
        "entitlement_rollover_policy": row["entitlement_rollover_policy"],
        "storm_guarantee_included": row["storm_guarantee_included"],
        "covered_visit_types": row["covered_visit_types"],
        "status": row["status"],
    })


def subscription(row):
    return _common(row, {
        "property_id": row["property_id"],
        "service_plan_id": row["service_plan_id"],
        "status": row["status"],
        "started_on": fmt_iso(row["started_on"]),
        "current_cycle_id": row["current_cycle_id"],
        "paused_at": fmt_iso(row["paused_at"]),
        "resumed_at": fmt_iso(row["resumed_at"]),
        "cumulative_paused_days": row["cumulative_paused_days"],
        "pending_tier_change_plan_id": row["pending_tier_change_plan_id"],
        "delinquent_since": fmt_iso(row["delinquent_since"]),
        "cancelled_at": fmt_iso(row["cancelled_at"]),
    })


def billing_cycle(row):
    return _common(row, {
        "subscription_id": row["subscription_id"],
        "cycle_index": row["cycle_index"],
        "period_start": fmt_iso(row["period_start"]),
        "period_end": fmt_iso(row["period_end"]),
        "status": row["status"],
        "entitlement_granted_units": row["entitlement_granted_units"],
        "entitlement_carried_in_units": row["entitlement_carried_in_units"],
        "entitlement_consumed_units": row["entitlement_consumed_units"],
        "entitlement_remaining_units": row["entitlement_remaining_units"],
        "entitlement_expired_units": row["entitlement_expired_units"],
        "entitlement_carried_out_units": row["entitlement_carried_out_units"],
        "prorated_fee_cents": row["prorated_fee_cents"],
        "closed_at": fmt_iso(row["closed_at"]),
    })


def away_period(row):
    return _common(row, {
        "property_id": row["property_id"],
        "owner_id": row["owner_id"],
        "start_at": fmt_iso(row["start_at"]),
        "end_at": fmt_iso(row["end_at"]),
        "cadence_days": row["cadence_days"],
        "projected_visit_count": row["projected_visit_count"],
        "scheduled_visit_count": calc.away_scheduled_visit_count(row),
        "derived_status": calc.away_period_derived_status(row),
        "cadence_revision_count": row["cadence_revision_count"],
    })


def checklist_template(row):
    return _common(row, {
        "visit_type": row["visit_type"],
        "version_label": row["version_label"],
        "item_codes": row["item_codes"],
        "critical_item_codes": row["critical_item_codes"],
        "default_finding_category": row["default_finding_category"],
        "required_item_count": row["required_item_count"],
        "status": row["status"],
    })


def visit(row):
    return _common(row, {
        "property_id": row["property_id"],
        "checklist_template_id": row["checklist_template_id"],
        "away_period_id": row["away_period_id"],
        "storm_response_id": row["storm_response_id"],
        "rental_turnover_id": row["rental_turnover_id"],
        "billing_cycle_id": row["billing_cycle_id"],
        "visit_type": row["visit_type"],
        "trigger_source": row["trigger_source"],
        "scheduled_start_at": fmt_iso(row["scheduled_start_at"]),
        "scheduled_end_at": fmt_iso(row["scheduled_end_at"]),
        "status": row["status"],
        "departed_at": fmt_iso(row["departed_at"]),
        "arrived_at": fmt_iso(row["arrived_at"]),
        "completed_at": fmt_iso(row["completed_at"]),
        "tech_user_id": row["tech_user_id"],
        "completed_item_codes": row["completed_item_codes"],
        "failed_item_codes": row["failed_item_codes"],
        "checklist_completion_pct": row["checklist_completion_pct"],
        "interior_temp_f": row["interior_temp_f"],
        "entitlement_applied": row["entitlement_applied"],
        "billable_amount_cents": row["billable_amount_cents"],
        "after_hours_flag": row["after_hours_flag"],
        "deferral_count": row["deferral_count"],
        "defer_reason": row["defer_reason"],
        "duration_minutes": calc.visit_duration_minutes(row),
    })


def finding(row):
    return _common(row, {
        "visit_id": row["visit_id"],
        "property_id": row["property_id"],
        "item_code": row["item_code"],
        "severity": row["severity"],
        "category": row["category"],
        "status": row["status"],
        "escalation_score": row["escalation_score"],
        "triaged_at": fmt_iso(row["triaged_at"]),
        "dismissed_at": fmt_iso(row["dismissed_at"]),
        "monitor_recheck_count": row["monitor_recheck_count"],
        "description": row["description"],
    })


def vendor(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "trade": row["trade"],
        "coi_expires_at": fmt_iso(row["coi_expires_at"]),
        "license_expires_at": fmt_iso(row["license_expires_at"]),
        "hourly_rate_cents": row["hourly_rate_cents"],
        "rating": row["rating"],
        "billing_mode": row["billing_mode"],
        "status": row["status"],
        "emergency_capable": row["emergency_capable"],
        "outstanding_key_count": calc.vendor_outstanding_key_count(row["id"]),
        "last_eligibility_evaluated_at": fmt_iso(row["last_eligibility_evaluated_at"]),
    })


def work_order(row):
    return _common(row, {
        "finding_id": row["finding_id"],
        "property_id": row["property_id"],
        "storm_event_id": row["storm_event_id"],
        "key_asset_id": row["key_asset_id"],
        "work_type": row["work_type"],
        "pipeline": calc.pipeline_of(row),
        "estimated_labour_hours": row["estimated_labour_hours"],
        "estimated_parts_cents": row["estimated_parts_cents"],
        "labour_cost_cents": row["labour_cost_cents"],
        "parts_cost_cents": row["parts_cost_cents"],
        "markup_cents": row["markup_cents"],
        "surcharge_pct_applied": row["surcharge_pct_applied"],
        "storm_surcharge_cents": row["storm_surcharge_cents"],
        "total_cents": row["total_cents"],
        "approval_ceiling_cents": row["approval_ceiling_cents"],
        "approval_required": row["approval_required"],
        "status": row["status"],
        "dispatch_attempt_count": row["dispatch_attempt_count"],
        "approved_by_user_id": row["approved_by_user_id"],
        "created_by_user_id": row["created_by_user_id"],
        "rejection_reason": row["rejection_reason"],
        "actual_labour_hours": row["actual_labour_hours"],
        "actual_parts_cents": row["actual_parts_cents"],
    })


def vendor_assignment(row):
    return _common(row, {
        "work_order_id": row["work_order_id"],
        "vendor_id": row["vendor_id"],
        "window_start_at": fmt_iso(row["window_start_at"]),
        "window_end_at": fmt_iso(row["window_end_at"]),
        "status": row["status"],
        "offered_at": fmt_iso(row["offered_at"]),
        "accepted_at": fmt_iso(row["accepted_at"]),
        "finished_at": fmt_iso(row["finished_at"]),
        "decline_reason": row["decline_reason"],
        "coi_valid_at_offer": row["coi_valid_at_offer"],
        "access_blocked_flag": row["access_blocked_flag"],
    })


def key_asset(row):
    return _common(row, {
        "property_id": row["property_id"],
        "key_type": row["key_type"],
        "label": row["label"],
        "copies_total": row["copies_total"],
        "copies_on_hand": calc.key_copies_on_hand(row),
        "copies_issued_outstanding": calc.key_copies_issued_outstanding(row),
        "copies_lost": calc.key_copies_lost(row),
        "current_code": row["current_code"],
        "code_rotation_count": row["code_rotation_count"],
        "active_grant_count": calc.key_active_grant_count(row),
        "rekey_pending_flag": row["rekey_pending_flag"],
    })


def key_issuance(row):
    return _common(row, {
        "key_asset_id": row["key_asset_id"],
        "vendor_id": row["vendor_id"],
        "vendor_assignment_id": row["vendor_assignment_id"],
        "issued_at": fmt_iso(row["issued_at"]),
        "return_deadline_at": fmt_iso(row["return_deadline_at"]),
        "returned_at": fmt_iso(row["returned_at"]),
        "status": row["status"],
        "overdue_days": (calc.key_overdue_days(row) if row["status"] == "OVERDUE"
                         else row["overdue_days"]),
        "copies_issued": row["copies_issued"],
    })


def access_grant(row):
    return _common(row, {
        "key_asset_id": row["key_asset_id"],
        "vendor_id": row["vendor_id"],
        "key_issuance_id": row["key_issuance_id"],
        "window_start_at": fmt_iso(row["window_start_at"]),
        "window_end_at": fmt_iso(row["window_end_at"]),
        "code_snapshot": row["code_snapshot"],
        "status": row["status"],
        "invalidated_reason": row["invalidated_reason"],
        "rotation_index_at_grant": row["rotation_index_at_grant"],
    })


def winterization_record(row):
    return _common(row, {
        "property_id": row["property_id"],
        "visit_id": row["visit_id"],
        "water_shutoff_done": row["water_shutoff_done"],
        "lines_drained_done": row["lines_drained_done"],
        "thermostat_set_f": row["thermostat_set_f"],
        "valve_tagged_done": row["valve_tagged_done"],
        "antifreeze_added_done": row["antifreeze_added_done"],
        "completed_step_count": row["completed_step_count"],
        "completeness_pct": row["completeness_pct"],
        "status": row["status"],
        "completed_at": fmt_iso(row["completed_at"]),
        "reopen_reason": row["reopen_reason"],
    })


def rental_turnover(row):
    return _common(row, {
        "property_id": row["property_id"],
        "checkout_at": fmt_iso(row["checkout_at"]),
        "checkin_at": fmt_iso(row["checkin_at"]),
        "clean_started_at": fmt_iso(row["clean_started_at"]),
        "inspect_started_at": fmt_iso(row["inspect_started_at"]),
        "ready_at": fmt_iso(row["ready_at"]),
        "status": row["status"],
        "reclean_attempt_count": row["reclean_attempt_count"],
        "absorbed_visit_id": row["absorbed_visit_id"],
        "guest_reference": row["guest_reference"],
    })


def mail_hold(row):
    return _common(row, {
        "property_id": row["property_id"],
        "start_on": fmt_iso(row["start_on"]),
        "end_on": fmt_iso(row["end_on"]),
        "hold_days": row["hold_days"],
        "extension_count": row["extension_count"],
        "package_count": row["package_count"],
        "overflow_events": row["overflow_events"],
        "status": row["status"],
        "forwarding_address": row["forwarding_address"],
        "disposition_fee_cents": row["disposition_fee_cents"],
    })


def security_incident(row):
    return _common(row, {
        "property_id": row["property_id"],
        "visit_id": row["visit_id"],
        "incident_type": row["incident_type"],
        "reported_at": fmt_iso(row["reported_at"]),
        "severity": row["severity"],
        "status": row["status"],
        "escalation_count": row["escalation_count"],
        "false_alarm_sequence": row["false_alarm_sequence"],
        "false_alarm_fee_cents": row["false_alarm_fee_cents"],
        "triggered_visit_id": row["triggered_visit_id"],
        "resolution_note": row["resolution_note"],
    })


def storm_event(row):
    return _common(row, {
        "name": row["name"],
        "region_state_code": row["region_state_code"],
        "landfall_eta_at": fmt_iso(row["landfall_eta_at"]),
        "status": row["status"],
        "derived_tier": calc.storm_advisory_tier(row),
        "landfall_recorded_at": fmt_iso(row["landfall_recorded_at"]),
        "all_clear_at": fmt_iso(row["all_clear_at"]),
        "downgrade_count": row["downgrade_count"],
        "response_count": calc.storm_response_count(row["id"]),
    })


def storm_response(row):
    return _common(row, {
        "storm_event_id": row["storm_event_id"],
        "property_id": row["property_id"],
        "subscription_id": row["subscription_id"],
        "secure_sweep_deadline_at": fmt_iso(row["secure_sweep_deadline_at"]),
        "secure_sweep_visit_id": row["secure_sweep_visit_id"],
        "secured_at": fmt_iso(row["secured_at"]),
        "sweep_on_time": row["sweep_on_time"],
        "guarantee_credit_cents": row["guarantee_credit_cents"],
        "assessment_deadline_at": fmt_iso(row["assessment_deadline_at"]),
        "assessed_at": fmt_iso(row["assessed_at"]),
        "swept_by_user_id": row["swept_by_user_id"],
        "assessed_by_user_id": row["assessed_by_user_id"],
        "damage_level": row["damage_level"],
        "surcharge_pct_at_dispatch": row["surcharge_pct_at_dispatch"],
        "status": row["status"],
    })


def invoice(row):
    return _common(row, {
        "billing_cycle_id": row["billing_cycle_id"],
        "property_id": row["property_id"],
        "owner_id": row["owner_id"],
        "status": row["status"],
        "storm_surcharge_pct": row["storm_surcharge_pct"],
        "gross_service_cents": row["gross_service_cents"],
        "entitlement_offset_cents": row["entitlement_offset_cents"],
        "storm_surcharge_cents": row["storm_surcharge_cents"],
        "guarantee_credit_cents": row["guarantee_credit_cents"],
        "subtotal_cents": row["subtotal_cents"],
        "tax_cents": row["tax_cents"],
        "late_fee_cents": row["late_fee_cents"],
        "total_cents": row["total_cents"],
        "amount_paid_cents": row["amount_paid_cents"],
        "balance_due_cents": row["balance_due_cents"],
        "issued_at": fmt_iso(row["issued_at"]),
        "paid_at": fmt_iso(row["paid_at"]),
        "dispute_count": row["dispute_count"],
    })


def invoice_line(row):
    return _common(row, {
        "invoice_id": row["invoice_id"],
        "visit_id": row["visit_id"],
        "work_order_id": row["work_order_id"],
        "security_incident_id": row["security_incident_id"],
        "mail_hold_id": row["mail_hold_id"],
        "line_type": row["line_type"],
        "description": row["description"],
        "amount_cents": row["amount_cents"],
        "taxable": row["taxable"],
        "tax_cents": row["tax_cents"],
        "status": row["status"],
        "sequence_index": row["sequence_index"],
    })
