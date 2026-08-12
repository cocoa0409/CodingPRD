"""Entity projections.

Rows are stored with their instants already rendered as strings -- server
instants through the single renderer, caller-supplied instants verbatim (G2)
-- so a projection is a straight field pick with no re-formatting anywhere.
"""

_COMMON = ("id", "created_at", "updated_at", "version")
_CONFIG_COMMON = ("id", "created_at")


def _pick(row, names, common=_COMMON):
    out = {}
    for name in common:
        if name in row:
            out[name] = row[name]
    for name in names:
        out[name] = row.get(name)
    return out


def household(row):
    return _pick(row, (
        "name", "region_code", "billing_email", "account_status", "suspended_at",
        "entitled_device_count", "active_device_count",
    ))


def household_member(row):
    return _pick(row, ("household_id", "full_name", "email", "member_role", "is_active"))


def subscription_plan(row):
    return _pick(row, (
        "tier", "monthly_fee_cents", "included_device_count",
        "overage_fee_cents_per_device", "coverage_mode",
        "first_response_minutes_p1", "first_response_minutes_p2", "first_response_minutes_p3",
        "onsite_resolution_hours_p1", "onsite_resolution_hours_p2", "onsite_resolution_hours_p3",
        "warranty_extension_months", "included_install_credits", "advance_replacement_eligible",
    ), common=_CONFIG_COMMON)


def subscription(row):
    return _pick(row, (
        "household_id", "plan_id", "pending_tier_plan_id", "status", "allow_overage",
        "cycle_index", "cycle_start_at", "cycle_end_at", "monthly_fee_cents",
        "install_credits_granted", "install_credits_consumed", "install_credits_remaining",
        "overage_device_count", "overage_charges_cents_this_cycle",
        "credits_issued_cents_this_cycle", "next_invoice_credit_cents",
        "next_invoice_adjustment_cents",
    ))


def device_catalog_entry(row):
    return _pick(row, (
        "model_code", "display_name", "device_class", "serial_prefix",
        "base_warranty_months", "requires_install", "manufacturer_service_only",
        "msrp_cents", "current_firmware_version",
    ), common=_CONFIG_COMMON)


def device(row):
    return _pick(row, (
        "household_id", "catalog_entry_id", "transfer_target_household_id",
        "serial_number", "purchase_date", "lifecycle_status", "firmware_status",
        "firmware_version", "activation_token", "activation_expires_at",
        "activation_attempts", "activated_at", "warranty_expires_at",
        "warranty_basis", "is_overage",
    ))


def ticket(row):
    return _pick(row, (
        "household_id", "device_id", "opened_by_member_id", "severity", "summary",
        "workflow_status", "sla_status", "dispatch_status", "first_response_at",
        "resolved_at", "closed_at", "pause_started_at", "sla_paused_minutes",
        "sla_uncovered_minutes", "sla_counted_minutes", "first_response_target_minutes",
        "onsite_resolution_target_minutes", "remote_session_failure_count",
        "escalation_reason", "survey_solicited_at",
    ))


def remote_session(row):
    return _pick(row, (
        "ticket_id", "agent_user_id", "session_index", "started_at", "ended_at",
        "status", "outcome", "diagnostic_notes",
    ))


def technician(row):
    return _pick(row, (
        "full_name", "region_code", "skills", "total_slot_count",
        "open_slot_count", "booked_slot_count", "blocked_slot_count",
    ))


def visit_slot(row):
    return _pick(row, ("technician_id", "region_code", "start_at", "end_at", "status"))


def visit(row):
    return _pick(row, (
        "ticket_id", "slot_id", "status", "scheduled_start_at", "scheduled_end_at",
        "cancelled_at", "fee_kind", "fee_cents", "fee_waived", "completion_notes",
    ))


def firmware_campaign(row):
    return _pick(row, (
        "catalog_entry_id", "kind", "target_firmware_version", "halt_failure_rate_pct",
        "status", "current_ring_index", "ring_window_start_at", "ring_window_end_at",
        "ring_device_count", "ring_failed_count", "ring_failure_rate",
    ))


def firmware_rollout(row):
    return _pick(row, (
        "campaign_id", "device_id", "ring_index", "window_start_at", "window_end_at",
        "status", "last_result", "retry_count", "deferred_until", "result_reported_at",
    ))


def addon_order(row):
    return _pick(row, (
        "household_id", "subscription_id", "lines", "status", "subtotal_cents",
        "bundle_discount_pct", "bundle_discount_cents", "discounted_subtotal_cents",
        "install_credits_applied", "install_charge_cents", "monthly_delta_cents",
        "proration_mode", "proration_cents", "order_total_cents", "fulfilled_device_ids",
    ))


def rma_case(row):
    return _pick(row, (
        "device_id", "ticket_id", "supersedes_rma_id", "warranty_state",
        "routing_target", "status", "hold_amount_cents", "hold_state",
        "shipped_at", "return_deadline_at", "returned_at",
    ))


def satisfaction_survey(row):
    return _pick(row, (
        "ticket_id", "score", "comment", "submitted_at", "window_closes_at",
        "credit_variant", "credit_cents",
    ))


def service_credit(row):
    return _pick(row, (
        "household_id", "subscription_id", "ticket_id", "reason", "breach_tier",
        "uncapped_amount_cents", "amount_cents", "cycle_index", "applied_to_cycle_index",
    ))
