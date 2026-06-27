"""Serialization helpers — define the exact public field set for each entity."""

_COMMON = ["id", "created_at", "updated_at", "version"]
_LIGHT = ["id", "created_at"]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def client_out(c):
    return _pick(c, _COMMON + [
        "email", "full_name", "state_code", "status",
        "financial_aid_tier", "wallet_credit_cents", "risk_flag",
    ])


def therapist_out(t):
    return _pick(t, _COMMON + [
        "full_name", "status", "max_active_caseload",
        "active_caseload", "specialties",
    ])


def license_out(l):
    return _pick(l, _COMMON + [
        "therapist_id", "state_code", "expires_on", "status",
    ])


def intake_out(i):
    return _pick(i, _COMMON + [
        "client_id", "presenting_concerns", "severity_score",
        "crisis_indicator", "submitted_at",
    ])


def match_out(m):
    return _pick(m, _COMMON + [
        "client_id", "therapist_id", "status", "match_score",
        "switch_reason", "superseded_by_match_id",
    ])


def subscription_out(s):
    return _pick(s, _COMMON + [
        "client_id", "status", "base_weekly_fee_cents", "weekly_credit_grant",
        "current_period_start", "pause_resumes_on", "cancel_effective_on",
    ])


def billing_cycle_out(b):
    return _pick(b, _COMMON + [
        "subscription_id", "period_start", "period_end", "list_amount_cents",
        "wallet_applied_cents", "charged_amount_cents", "status", "credits_granted",
    ])


def session_credit_out(sc):
    return _pick(sc, _LIGHT + [
        "client_id", "billing_cycle_id", "status", "expires_on", "live_session_id",
    ])


def live_session_out(ls):
    return _pick(ls, _COMMON + [
        "match_id", "session_credit_id", "starts_at", "ends_at",
        "status", "cancelled_within_window",
    ])


def thread_out(t):
    return _pick(t, _COMMON + [
        "match_id", "status", "unread_for_therapist",
    ])


def message_out(m):
    return _pick(m, _LIGHT + [
        "thread_id", "sender_role", "body",
    ])


def crisis_out(c):
    return _pick(c, _COMMON + [
        "client_id", "raised_by_role", "severity", "status", "safety_resources_sent",
    ])


def aid_out(a):
    return _pick(a, _COMMON + [
        "client_id", "annual_income_cents", "household_size", "status", "awarded_tier",
    ])


def superbill_out(s):
    return _pick(s, _COMMON + [
        "client_id", "period_start", "period_end", "status",
        "session_count", "reimbursable_amount_cents",
    ])
