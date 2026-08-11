"""The serialized representations of PRD section 2.13.

Each entity has exactly one shape and it does not vary with context.
Instant fields are rendered with three fractional digits (PRD 2.4); every
caller-supplied calendar date is stored and echoed byte-for-byte, so it is
simply copied through.
"""

from .clock import render_instant
from .store import db


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": render_instant(row["created_at"])}
    if versioned:
        out["updated_at"] = render_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def _pick(row, names):
    return {name: row.get(name) for name in names}


def _instants(row, names):
    return {name: render_instant(row.get(name)) for name in names}


def client(row):
    out = _common(row)
    out.update(_pick(row, [
        "full_name", "date_of_birth", "intake_reference", "status",
        "capacity_determination", "capacity_determined_on", "activated_on",
        "closed_on",
    ]))
    return out


def authorization(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "scope_tier", "instrument_reference", "effective_date",
        "expiry_date", "status", "revocation_reason",
        "cascaded_payments_cancelled", "cascaded_recipients_terminated",
        "cascaded_applications_withdrawn",
    ]))
    out.update(_instants(row, ["executed_at", "revoked_at"]))
    return out


def account(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "institution_name", "account_label", "account_type",
        "opening_balance_cents", "cleared_balance_cents", "pending_holds_cents",
        "committed_disbursements_cents", "available_balance_cents",
        "fraud_posture", "fraud_posture_reason",
    ]))
    return out


def payee(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "payee_name", "payee_type", "remittance_reference",
        "status", "blocked_reason", "settled_payment_count",
    ]))
    return out


def budget_category(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "category_name", "budget_month", "allocation_cents",
        "override_granted_cents", "override_count", "last_override_reason",
        "committed_cents", "settled_cents", "remaining_cents",
        "variance_full_cents", "variance_ptd_cents", "variance_direction",
    ]))
    return out


def surety_bond(row):
    out = _common(row)
    out.update(_pick(row, [
        "carrier_name", "bond_number", "coverage_cents", "effective_date",
        "expiry_date", "status", "exposure_committed_cents",
        "exposure_settled_inclusive_cents", "headroom_committed_cents",
    ]))
    return out


def payment(row):
    out = _common(row)
    out.update(_pick(row, [
        "account_id", "payee_id", "authorization_id", "budget_category_id",
        "amount_cents", "channel", "memo", "requested_send_date",
        "duplicate_override", "service_fee_cents", "total_charge_cents",
        "prepared_by_user_id", "approved_by_user_id", "approval_status",
        "settlement_status", "projected_settlement_date",
        "effective_settlement_date", "settled_on", "revision_count",
        "return_reason", "stop_reason",
    ]))
    out.update(_instants(row, ["released_at"]))
    return out


def dispute(row):
    out = _common(row)
    out.update(_pick(row, [
        "payment_id", "reason_code", "disputed_amount_cents", "filed_on",
        "days_since_settlement", "provisional_credit_cents", "status",
        "resolution_note",
    ]))
    return out


def reconciliation_period(row):
    out = _common(row)
    out.update(_pick(row, [
        "account_id", "period_month", "status", "imported_line_count",
        "open_exception_count", "unreconciled_entry_count", "reopen_count",
        "has_retro_adjustment",
    ]))
    out.update(_instants(row, ["closed_at"]))
    return out


def statement_line(row):
    out = _common(row)
    out.update(_pick(row, [
        "period_id", "external_ref", "amount_cents", "line_date",
        "line_description", "match_status", "matched_ledger_entry_id",
        "exception_note",
    ]))
    return out


def ledger_entry(row):
    out = _common(row, versioned=False)
    out.update(_pick(row, [
        "account_id", "period_id", "source_payment_id", "entry_type",
        "amount_cents", "entry_date", "retro_period_month", "memo",
    ]))
    # PRD 3.7: frozen is never stored; it is derived at read time from the
    # entry's period's current status.
    period_id = row.get("period_id")
    frozen = False
    if period_id is not None:
        period = db.reconciliation_periods.get(period_id)
        frozen = bool(period and period["status"] in ("CLOSED", "LOCKED"))
    out["frozen"] = frozen
    return out


def fraud_alert(row):
    out = _common(row)
    out.update(_pick(row, [
        "account_id", "payment_id", "reason_code", "detail",
        "intake_risk_score", "intake_risk_band", "review_risk_score",
        "review_risk_band", "status", "disposition_note",
    ]))
    out.update(_instants(row, ["ack_due_at", "acknowledged_at"]))
    return out


def benefit_application(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "authorization_id", "program",
        "asserted_monthly_income_cents", "resource_items",
        "countable_resources_gross_cents", "countable_resources_net_cents",
        "status", "appeal_count", "submitted_on", "decision_date",
        "award_effective_date", "award_monthly_amount_cents", "retro_months",
        "retro_award_cents", "denial_reason",
    ]))
    return out


def family_recipient(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "authorization_id", "full_name", "contact_email",
        "relationship", "permitted_categories", "subscription_status",
        "consent_recorded_by_role", "report_count",
    ]))
    out.update(_instants(row, ["consent_recorded_at"]))
    return out


def family_report(row):
    out = _common(row, versioned=False)
    out.update(_pick(row, [
        "recipient_id", "report_month", "requested_categories",
        "included_categories", "withheld_categories", "is_provisional",
        "total_disbursed_cents", "closing_available_balance_cents",
    ]))
    out.update(_instants(row, ["generated_at"]))
    return out


def coordination_request(row):
    out = _common(row)
    out.update(_pick(row, [
        "client_id", "subject", "tier", "assigned_member_user_id",
        "reroute_count", "status", "disposition_note",
    ]))
    out.update(_instants(row, ["ack_due_at", "acknowledged_at"]))
    return out


def audit_entry(row):
    out = _common(row, versioned=False)
    out.update(_pick(row, [
        "client_id", "actor_role", "actor_user_id", "operation",
        "subject_entity", "subject_id", "outcome", "error_id",
        "disclosure_category",
    ]))
    out.update(_instants(row, ["recorded_at"]))
    return out
