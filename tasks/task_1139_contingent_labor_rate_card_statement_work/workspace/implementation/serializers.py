"""Entity -> public JSON dict. Field names follow SCAFFOLD.yaml exactly.

Common-fields entities expose id/created_at/updated_at/version.
InvoiceLine and SpendLedgerEntry expose only id and created_at.
Worker exposes the computed cumulative_tenure_days on read.
"""

import services

_COMMON = ("id", "created_at", "updated_at", "version")


def _pub(rec, fields, common=True):
    out = {}
    for f in fields:
        out[f] = rec.get(f)
    if common:
        for f in _COMMON:
            out[f] = rec.get(f)
    else:
        out["id"] = rec.get("id")
        out["created_at"] = rec.get("created_at")
    return out


def supplier(s):
    return _pub(s, [
        "name", "supplier_code", "tier", "status", "tier_score",
        "offers_made_count", "offers_filled_count", "open_offers_count",
        "completed_assignments_count", "open_violation_count",
        "milestones_delivered_count", "milestones_accepted_count",
        "spend_ytd_cents",
    ])


def rate_card(c):
    return _pub(c, [
        "role_code", "skill_code", "geo_code", "currency",
        "pay_rate_floor_cents", "bill_rate_ceiling_cents", "max_markup_pct",
        "effective_from", "effective_to", "status", "supersedes_id",
    ])


def engagement(e):
    return _pub(e, [
        "title", "engagement_type", "role_code", "skill_code", "geo_code",
        "payment_basis", "supervision_level", "duration_months", "budget_cents",
        "prorata_conversion", "status", "misclassification_risk",
        "classification_note", "awarded_supplier_id", "committed_spend_cents",
        "budget_audit_raised",
    ])


def offer(o):
    return _pub(o, [
        "engagement_id", "supplier_id", "status", "offered_at",
        "response_due_at", "responded_at",
    ])


def worker(w):
    out = _pub(w, [
        "supplier_id", "full_name", "email", "tenure_carryover_days",
        "status", "conversion_status",
    ])
    out["cumulative_tenure_days"] = services.cumulative_tenure(w)
    return out


def assignment(a):
    return _pub(a, [
        "worker_id", "engagement_id", "offer_id", "supplier_id",
        "rate_card_id", "bill_rate_cents", "pay_rate_cents",
        "start_date", "end_date", "actual_end_date", "status",
        "termination_reason",
    ])


def timesheet(t):
    return _pub(t, [
        "assignment_id", "period_start", "period_end", "submitted_hours",
        "approved_hours", "status", "provisional_amount_cents",
        "final_amount_cents", "rejection_reason", "void_reason",
        "submitted_by_user_id", "approved_by_user_id",
    ])


def milestone(m):
    return _pub(m, [
        "engagement_id", "name", "amount_cents", "due_date",
        "acceptance_status", "payment_status", "rejection_reason",
        "delivered_by_supplier_id", "accepted_by_user_id",
    ])


def invoice(inv):
    return _pub(inv, [
        "supplier_id", "period_start", "period_end", "status", "line_count",
        "subtotal_cents", "processing_fee_cents", "total_cents",
        "consolidation_savings_cents", "finalized_by_user_id",
        "paid_by_user_id", "void_reason",
    ])


def invoice_line(l):
    return _pub(l, [
        "invoice_id", "timesheet_id", "milestone_id", "amount_cents",
    ], common=False)


def conversion_request(c):
    return _pub(c, [
        "worker_id", "assignment_id", "tenure_days_at_request",
        "fee_variant", "fee_cents", "status", "decline_reason",
    ])


def audit(a):
    return _pub(a, [
        "supplier_id", "engagement_id", "timesheet_id", "assignment_id",
        "finding", "severity", "status", "details", "resolution_note",
    ])


def ledger_entry(e):
    return _pub(e, [
        "supplier_id", "engagement_id", "timesheet_id", "milestone_id",
        "invoice_id", "entry_type", "delta_cents", "running_balance_cents",
    ], common=False)
