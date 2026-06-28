"""Entity -> public JSON serialization.

Datetimes are emitted as ISO 8601 UTC strings (3 fractional digits). Computed
fields are surfaced as stored (they are kept current by the service layer).
"""
from timeutil import to_iso

_DT_FIELDS = {
    "created_at", "updated_at", "current_period_start", "current_period_end",
    "past_due_since", "annual_physical_due_on", "checked_in_at", "starts_at",
    "ends_at", "authorized_at", "expires_at", "response_deadline",
}


def _base(entity, fields, include_common=True):
    out = {"id": entity["id"]}
    for f in fields:
        val = entity.get(f)
        if f in _DT_FIELDS:
            val = to_iso(val)
        out[f] = val
    if include_common:
        out["created_at"] = to_iso(entity["created_at"])
        out["updated_at"] = to_iso(entity["updated_at"])
        out["version"] = entity["version"]
    return out


def practice(e):
    return _base(e, [
        "name", "panel_target", "panel_hard_cap", "monthly_fee_cents",
        "annual_fee_discount_pct", "dpc_covered_service_codes",
        "insurance_coinsurance_pct", "late_fee_cents", "grace_period_days",
    ])


def provider(e):
    return _base(e, [
        "practice_id", "full_name", "npi", "panel_capacity",
        "accepting_new_members", "active_panel_count", "panel_load_bucket",
    ])


def employer(e):
    return _base(e, [
        "practice_id", "company_name", "sponsored_seat_limit",
        "sponsorship_pct", "occupied_seat_count",
    ])


def member(e):
    return _base(e, [
        "practice_id", "assigned_provider_id", "email", "full_name",
        "plan_type", "membership_status", "has_insurance",
        "wallet_credit_cents", "annual_physical_due_on",
    ])


def membership(e):
    return _base(e, [
        "member_id", "plan_type", "monthly_fee_cents", "employer_seat_id",
        "member_share_cents", "current_period_start", "current_period_end",
        "past_due_since",
    ])


def employer_seat(e):
    return _base(e, ["employer_id", "member_id", "seat_status"])


def visit_slot(e):
    return _base(e, [
        "provider_id", "slot_type", "starts_at", "ends_at",
        "virtual_capacity", "booked_count", "slot_state",
    ])


def visit(e):
    return _base(e, [
        "member_id", "provider_id", "slot_id", "visit_type",
        "clinical_status", "billing_status", "service_lines", "checked_in_at",
    ])


def care_plan(e):
    return _base(e, [
        "member_id", "origin_visit_id", "plan_status", "goal_count",
        "revision_number",
    ])


def referral(e):
    return _base(e, [
        "member_id", "origin_visit_id", "specialty", "referral_status",
        "authorized_at", "expires_at",
    ])


def message_thread(e):
    return _base(e, [
        "member_id", "provider_id", "priority", "thread_status",
        "response_deadline",
    ])


def invoice(e):
    return _base(e, [
        "member_id", "visit_id", "gross_charge_cents", "dpc_covered_cents",
        "insurance_billed_cents", "member_responsibility_cents",
        "invoice_status",
    ])


def payment(e):
    # Payment is the single exception: only id and created_at, no updated_at/version.
    out = {
        "id": e["id"],
        "member_id": e.get("member_id"),
        "membership_id": e.get("membership_id"),
        "invoice_id": e.get("invoice_id"),
        "charge_kind": e.get("charge_kind"),
        "amount_cents": e.get("amount_cents"),
        "outcome": e.get("outcome"),
        "wallet_applied_cents": e.get("wallet_applied_cents"),
        "created_at": to_iso(e["created_at"]),
    }
    return out
