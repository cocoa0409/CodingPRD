"""Public serialization for each entity.

Each function returns the externally visible field set (per SCAFFOLD 1.1),
including the common fields id/created_at/updated_at/version. Internal-only keys
(those prefixed with '_') are never exposed.
"""

COMMON = ("id", "created_at", "updated_at", "version")


def _pick(entity, fields):
    out = {}
    for f in fields:
        out[f] = entity.get(f)
    return out


def subject(e):
    return _pick(e, COMMON + (
        "code", "display_name", "category", "requires_credential", "status",
    ))


def commission_policy(e):
    return _pick(e, COMMON + (
        "name", "tier_breakpoints_cents", "tier_rates_bps", "trial_commission_bps",
        "trial_max_billed_minutes", "refund_window_hours", "status", "activated_at",
    ))


def tutor(e):
    return _pick(e, COMMON + (
        "email", "full_name", "base_hourly_rate_cents", "verification_status",
        "lifetime_net_earnings_cents", "payout_balance_cents", "clawback_owed_cents",
        "reliability_score", "active_subject_count", "is_payable",
    ))


def credential(e):
    return _pick(e, COMMON + (
        "tutor_id", "subject_id", "kind", "document_ref", "status",
        "reviewed_by", "rejection_reason",
    ))


def subject_tag(e):
    return _pick(e, COMMON + (
        "tutor_id", "subject_id", "subject_rate_cents", "status",
        "effective_hourly_rate_cents",
    ))


def parent_account(e):
    return _pick(e, COMMON + (
        "email", "full_name", "wallet_balance_cents", "held_balance_cents",
        "available_balance_cents", "child_count", "status",
    ))


def student(e):
    return _pick(e, COMMON + (
        "parent_account_id", "display_name", "grade_level", "status",
    ))


def booking(e):
    return _pick(e, COMMON + (
        "parent_account_id", "student_id", "tutor_id", "subject_id",
        "scheduled_start", "planned_minutes", "is_trial", "quoted_rate_cents",
        "hold_amount_cents", "status", "reschedule_count",
    ))


def session(e):
    return _pick(e, COMMON + (
        "booking_id", "tutor_id", "actual_minutes", "billed_minutes",
        "settlement_status", "delivery_status",
    ))


def settlement(e):
    return _pick(e, COMMON + (
        "session_id", "tutor_id", "gross_amount_cents", "commission_bps",
        "commission_cents", "tutor_net_cents", "refunded_cents", "status",
    ))


def refund_case(e):
    return _pick(e, COMMON + (
        "session_id", "parent_account_id", "tutor_id", "supersedes_case_id",
        "claimed_amount_cents", "parent_offer_cents", "tutor_offer_cents",
        "round_count", "granted_amount_cents", "status",
    ))
