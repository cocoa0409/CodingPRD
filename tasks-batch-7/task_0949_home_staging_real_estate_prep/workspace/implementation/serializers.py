"""Resource serializers.

Every datetime-valued attribute in this service is listed in DATETIME_FIELDS and
is rendered by store.iso() -- ISO 8601 UTC with exactly three fractional digits
and a trailing 'Z'.  Caller-supplied instants, server-minted instants and
derived instants all take that same canonical rendering.
"""
from datetime import datetime
from decimal import Decimal

import calc
import store

DATETIME_FIELDS = {
    "created_at", "updated_at", "acquired_at", "scheduled_at", "held_at",
    "under_contract_at", "closed_at", "authorized_at", "service_window_end_date",
    "committed_at", "placed_at", "earliest_delivery_date", "cancel_cutoff_date",
    "completed_at", "start_date", "end_date", "pickup_window_start",
    "pickup_window_end", "holdover_cap_period_start", "delivered_at",
    "issued_at", "due_date", "paid_at",
}

COMMON = ["created_at", "updated_at", "version"]


def _value(name, value):
    if name in DATETIME_FIELDS:
        if isinstance(value, datetime):
            return store.iso(value)
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):        # safety net: never leak an HTTP-date
        return store.iso(value)
    if isinstance(value, dict):
        return {k: _value(k, v) for k, v in value.items()}
    return value


def _pack(row, fields, extra=None):
    out = {}
    for name in fields:
        out[name] = _value(name, row.get(name))
    if extra:
        for name, value in extra.items():
            out[name] = _value(name, value)
    return out


# --------------------------------------------------------------------------
def brokerage(row):
    open_count = len([p for p in store.where("projects", brokerage_id=row["id"])
                      if p["workflow_state"] != "CLOSED"])
    row["open_project_count"] = open_count
    return _pack(row, ["id", "name", "license_code", "authorization_cap", "tax_exempt",
                       "billing_email", "open_project_count"] + COMMON)


def client(row):
    return _pack(row, ["id", "brokerage_id", "client_type", "full_name", "email",
                       "personal_authorization_cap", "effective_authorization_cap",
                       "consent_on_file"] + COMMON)


def property_(row):
    return _pack(row, ["id", "owner_client_id", "address_line", "city", "state_code",
                       "distance_miles", "occupancy", "room_count", "prep_state"] + COMMON)


def listing(row):
    return _pack(row, ["id", "property_id", "listing_agent_client_id", "mls_number",
                       "list_price", "listing_state", "under_contract_at", "closed_at",
                       "fallout_count"] + COMMON)


def tier(row):
    return _pack(row, ["id", "tier_code", "tier_rank", "room_cap", "included_accessory_sets",
                       "included_photo_sessions", "base_price", "monthly_rent_rate",
                       "created_at"])


def vendor(row):
    return _pack(row, ["id", "name", "lead_time_days", "min_lease_cycles",
                       "cancel_cutoff_days", "rate_multiplier", "status"] + COMMON)


def item(row):
    return _pack(row, ["id", "sku", "category", "acquired_at", "replacement_value",
                       "monthly_rate", "condition_grade", "status", "times_deployed"] + COMMON)


def consultation(row):
    return _pack(row, ["id", "property_id", "requested_by_client_id", "scheduled_at",
                       "held_at", "pipeline", "state", "revision_count",
                       "recommended_tier_code", "estimated_hours", "scoped_room_count",
                       "rental_line_count"] + COMMON)


def scope_item(row):
    return _pack(row, ["id", "consultation_id", "room_label", "action", "estimated_hours",
                       "requires_rental", "accessory_set_count", "sequence_index"] + COMMON)


def project(row):
    row["photo_sessions_consumed"] = calc.photo_sessions_consumed(row)
    row["reshoot_credits_remaining"] = calc.reshoot_credits_remaining(row)
    row["fiscal_hold"] = (row.get("payment_state") == "ESCALATED")
    return _pack(row, ["id", "property_id", "consultation_id", "listing_id",
                       "package_tier_id", "payer_client_id", "brokerage_id",
                       "authorized_by_client_id", "pipeline", "payer_type",
                       "payer_split_agent_pct", "workflow_state", "payment_state",
                       "room_count", "accessory_set_count", "contract_value",
                       "authorized_amount", "authorized_at", "destage_eligible",
                       "service_window_end_date", "window_extension_count",
                       "photo_sessions_consumed", "reshoot_credits_remaining",
                       "restage_count", "fiscal_hold"] + COMMON)


def pull(row):
    return _pack(row, ["id", "project_id", "state", "requested_unit_count",
                       "filled_unit_count", "fill_rate", "resubmit_count",
                       "committed_at"] + COMMON)


def pull_line(row):
    return _pack(row, ["id", "pull_id", "inventory_item_id", "rental_order_id", "source",
                       "category", "room_label", "quantity", "monthly_rate", "state"] + COMMON)


def order(row):
    return _pack(row, ["id", "project_id", "vendor_id", "state", "unit_count", "placed_at",
                       "earliest_delivery_date", "cancel_cutoff_date",
                       "effective_term_cycles", "monthly_rate_total",
                       "cancellation_fee"] + COMMON)


def install(row):
    return _pack(row, ["id", "project_id", "scheduled_at", "crew_size", "state",
                       "completed_at", "attempt_count"] + COMMON)


def visit(row):
    return _pack(row, ["id", "project_id", "scheduled_at", "visit_index", "hours_logged",
                       "billable_hours", "state", "attempt_count"] + COMMON)


def lease(row):
    return _pack(row, ["id", "project_id", "initial_cycles", "extension_cycles",
                       "billed_cycles", "state", "start_date", "end_date",
                       "pickup_window_start", "pickup_window_end", "monthly_rent",
                       "holdover_days", "holdover_charge",
                       "holdover_cap_period_start"] + COMMON)


def extension(row):
    return _pack(row, ["id", "lease_id", "requested_cycles", "state", "granted_cycles",
                       "extended_line_count", "returned_line_count", "extension_charge",
                       "swap_credit"] + COMMON)


def pickup(row):
    return _pack(row, ["id", "project_id", "lease_id", "scheduled_at", "state",
                       "attempt_count", "completed_at", "assessed_line_count",
                       "damage_total"] + COMMON)


def assessment(row):
    return _pack(row, ["id", "pickup_id", "pull_line_id", "condition_at_pickup",
                       "repair_cost_estimate", "state", "depreciated_replacement_value",
                       "charge_amount", "disposition", "appeal_count"] + COMMON)


def shoot(row):
    proj = store.get("projects", row["project_id"])
    if proj is not None:
        row["mls_delivery_gated"] = calc.mls_delivery_gate(proj)
    return _pack(row, ["id", "project_id", "scheduled_at", "is_reshoot", "session_index",
                       "state", "overage_fee", "mls_delivery_gated", "delivered_at"] + COMMON)


def invoice(row):
    calc.refresh_invoice(row)
    return _pack(row, ["id", "project_id", "state", "subtotal", "tax_amount",
                       "deposit_applied", "interest_accrued", "total_due", "issued_at",
                       "due_date", "paid_at", "line_summary"] + COMMON)


def deposit(row):
    return _pack(row, ["id", "project_id", "invoice_id", "amount", "state",
                       "applied_to_damage", "applied_to_holdover", "applied_to_balance",
                       "refunded_amount", "forfeited_amount", "held_remaining"] + COMMON)
