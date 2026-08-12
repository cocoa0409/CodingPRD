"""Entity serializers: stored record -> API representation (PRD §2.4).

Internal datetime bookkeeping fields (prefixed with _) are never exposed.
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(r, fields, common=True):
    out = {"id": r["id"], "created_at": r["created_at"]}
    if common:
        out["updated_at"] = r["updated_at"]
        out["version"] = r["version"]
    for f in fields:
        out[f] = r.get(f)
    return out


def employer(r):
    return _base(r, [
        "name", "annual_self_only_premium_cents", "tobacco_surcharge_cents",
        "pmpm_fee_cents", "coaching_session_fee_cents", "k_anonymity_threshold",
        "kiosk_capacity", "invoice_approval_limit_cents",
    ])


def employee(r):
    return _base(r, [
        "employer_id", "email", "full_name", "department", "hire_date",
        "tobacco_attested",
    ])


def program(r):
    return _base(r, [
        "employer_id", "name", "plan_year_start", "plan_year_end",
        "bronze_threshold", "silver_threshold", "gold_threshold",
        "bronze_award_cents", "silver_award_cents", "gold_award_cents",
        "premium_cap_pct", "coaching_required_sessions", "status",
    ])


def enrollment(r):
    return _base(r, [
        "program_id", "employee_id", "ra_eligible", "participation_status",
        "verification_status", "points_balance_provisional",
        "points_balance_settled", "auto_referral_count", "terminated_at",
    ])


def hra(r):
    # HealthAssessment is a light resource: id + created_at only (PRD §2.4)
    return _base(r, ["enrollment_id", "answers", "risk_score", "risk_band"], common=False)


def screening(r):
    return _base(r, [
        "enrollment_id", "clinic_location", "slot_start", "slot_end", "bmi",
        "systolic_bp", "total_cholesterol", "glucose", "targets_met", "status",
    ])


def challenge(r):
    return _base(r, [
        "program_id", "name", "activity_type", "goal_quantity", "points_reward",
        "starts_at", "ends_at", "completed_count", "status",
    ])


def participation(r):
    return _base(r, [
        "challenge_id", "enrollment_id", "progress_quantity", "status",
    ])


def activity_event(r):
    # ActivityEvent is a light resource: id + created_at only (PRD §2.4)
    return _base(r, [
        "enrollment_id", "device_source", "external_event_id", "activity_type",
        "quantity", "occurred_at", "points_granted",
    ], common=False)


def ledger_entry(r):
    return _base(r, [
        "enrollment_id", "kind", "points_delta", "source_activity_event_id",
        "reason", "status",
    ])


def award(r):
    return _base(r, [
        "enrollment_id", "program_id", "tier", "standard_award_cents",
        "award_cents", "applied_variant", "surcharge_cents",
        "net_annual_differential_cents", "status", "confirmed_at",
        "dispute_reason",
    ])


def referral(r):
    return _base(r, [
        "enrollment_id", "reason", "source", "assigned_coach_id",
        "sessions_completed", "session_dates", "referral_round", "outcome",
        "status",
    ])


def invoice(r):
    return _base(r, [
        "program_id", "vendor_name", "period_start", "period_end",
        "line_items", "total_cents", "submitted_by", "status",
    ])


def report(r):
    return _base(r, [
        "program_id", "department", "cohort_size", "avg_settled_points",
        "participation_rate", "tobacco_rate", "status",
    ])
