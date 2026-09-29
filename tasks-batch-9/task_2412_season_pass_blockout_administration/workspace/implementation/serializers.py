"""Record serialisation.  Computed fields are derived on read (PRD 2.6)."""

import json

from services import domain


def _common(record, payload):
    payload["id"] = record["id"]
    payload["created_at"] = record["created_at"]
    payload["updated_at"] = record["updated_at"]
    payload["version"] = record["version"]
    return payload


def program_out(record):
    revenue = domain.program_revenue(record["id"])
    return _common(record, {
        "season_year": record["season_year"],
        "park_name": record["park_name"],
        "status": record["status"],
        "early_bird_deadline": record["early_bird_deadline"],
        "capacity_peak_threshold_pct": record["capacity_peak_threshold_pct"],
        "capacity_lock_threshold_pct": record["capacity_lock_threshold_pct"],
        "capacity_lock_blockout_max_rank": record["capacity_lock_blockout_max_rank"],
        "delinquency_suspension_threshold": record["delinquency_suspension_threshold"],
        "default_threshold": record["default_threshold"],
        "sharing_case_auto_open_score": record["sharing_case_auto_open_score"],
        "base_revenue_cents": revenue["base_revenue_cents"],
        "recognized_revenue_cents": revenue["recognized_revenue_cents"],
        "deferred_revenue_cents": revenue["deferred_revenue_cents"],
        "forfeited_revenue_cents": revenue["forfeited_revenue_cents"],
        "active_pass_count": revenue["active_pass_count"],
    })


def tier_out(record):
    return _common(record, {
        "program_id": record["program_id"],
        "name": record["name"],
        "tier_rank": record["tier_rank"],
        "base_price_cents": record["base_price_cents"],
        "parking_benefit": record["parking_benefit"],
        "in_park_discount_pct": record["in_park_discount_pct"],
        "reservation_required_on_peak": record["reservation_required_on_peak"],
        "peak_reservation_quota": record["peak_reservation_quota"],
        "status": record["status"],
    })


def park_day_out(record):
    counters = domain.day_counters(record)
    payload = {
        "program_id": record["program_id"],
        "calendar_date": record["calendar_date"],
        "capacity_total": record["capacity_total"],
        "forecast_attendance": record["forecast_attendance"],
        "forecast_utilization_pct": record["forecast_utilization_pct"],
        "day_class": record["day_class"],
        "reservation_slot_capacity": record["reservation_slot_capacity"],
        "window_slot_capacity": record["window_slot_capacity"],
        "grant_count": record["grant_count"],
    }
    payload.update(counters)
    return _common(record, payload)


def assignment_out(record):
    return _common(record, {
        "tier_id": record["tier_id"],
        "park_day_id": record["park_day_id"],
        "source": record["source"],
        "status": record["status"],
        "lift_reason": record["lift_reason"],
    })


def passholder_out(record):
    return _common(record, {
        "full_name": record["full_name"],
        "email": record["email"],
        "date_of_birth": record["date_of_birth"],
        "sharing_risk_score": record["sharing_risk_score"],
        "photo_mismatch_count": domain.holder_photo_mismatch_count(record["id"]),
        "status": record["status"],
    })


def pass_out(record):
    return _common(record, {
        "program_id": record["program_id"],
        "tier_id": record["tier_id"],
        "passholder_id": record["passholder_id"],
        "renewed_from_pass_id": record["renewed_from_pass_id"],
        "media_number": record["media_number"],
        "payment_mode": record["payment_mode"],
        "pass_status": record["pass_status"],
        "billing_status": record["billing_status"],
        "photo_captured": record["photo_captured"],
        "photo_hash": record["photo_hash"],
        "identity_bound": record["identity_bound"],
        "government_id_last4": record["government_id_last4"],
        "contract_value_cents": record["contract_value_cents"],
        "billed_total_cents": record["billed_total_cents"],
        "paid_to_date_cents": record["paid_to_date_cents"],
        "credited_amount_cents": domain.pass_credited_cents(record),
        "outstanding_balance_cents": domain.pass_outstanding_cents(record),
        "visit_count": domain.pass_visit_count(record),
        "in_park_spend_cents": domain.pass_in_park_spend_cents(record),
        "suspension_count": record["suspension_count"],
    })


def plan_out(record):
    counts = domain.plan_counts(record)
    return _common(record, {
        "season_pass_id": record["season_pass_id"],
        "plan_status": record["plan_status"],
        "down_payment_cents": record["down_payment_cents"],
        "setup_fee_cents": record["setup_fee_cents"],
        "financed_amount_cents": record["financed_amount_cents"],
        "installment_count": record["installment_count"],
        "first_due_date": record["first_due_date"],
        "monthly_amount_cents": record["monthly_amount_cents"],
        "final_installment_cents": record["final_installment_cents"],
        "missed_count": counts["missed_count"],
        "settled_count": counts["settled_count"],
    })


def installment_out(record):
    return _common(record, {
        "payment_plan_id": record["payment_plan_id"],
        "sequence_no": record["sequence_no"],
        "due_date": record["due_date"],
        "amount_cents": record["amount_cents"],
        "status": record["status"],
        "settled_at": record["settled_at"],
    })


def reservation_out(record):
    return _common(record, {
        "season_pass_id": record["season_pass_id"],
        "park_day_id": record["park_day_id"],
        "arrival_window_start": record["arrival_window_start"],
        "arrival_window_end": record["arrival_window_end"],
        "status": record["status"],
        "redeemed_visit_id": record["redeemed_visit_id"],
    })


def visit_out(record):
    return _common(record, {
        "season_pass_id": record["season_pass_id"],
        "park_day_id": record["park_day_id"],
        "reservation_id": record["reservation_id"],
        "entry_at": record["entry_at"],
        "gate_code": record["gate_code"],
        "photo_match": record["photo_match"],
        "status": record["status"],
        "spend_cents": record["spend_cents"],
        "discount_applied_pct": record["discount_applied_pct"],
    })


def case_out(record):
    return _common(record, {
        "season_pass_id": record["season_pass_id"],
        "opened_by_user_id": record["opened_by_user_id"],
        "opened_by_role": record["opened_by_role"],
        "evidence_visit_ids": list(record["evidence_visit_ids"]),
        "note": record["note"],
        "case_status": record["case_status"],
        "review_round": record["review_round"],
        "risk_score_at_open": record["risk_score_at_open"],
        "decided_by_user_id": record["decided_by_user_id"],
        "decision_rationale": record["decision_rationale"],
        "revocation_forfeit_cents": record["revocation_forfeit_cents"],
    })


def upgrade_out(record):
    return _common(record, {
        "season_pass_id": record["season_pass_id"],
        "source_tier_id": record["source_tier_id"],
        "target_tier_id": record["target_tier_id"],
        "credit_mode": record["credit_mode"],
        "gross_delta_cents": record["gross_delta_cents"],
        "raw_credit_cents": record["raw_credit_cents"],
        "credit_cents": record["credit_cents"],
        "net_delta_cents": record["net_delta_cents"],
        "admin_fee_cents": record["admin_fee_cents"],
        "total_due_cents": record["total_due_cents"],
        "payment_amount_cents": record["payment_amount_cents"],
        "quoted_at": record["quoted_at"],
        "quote_expires_at": record["quote_expires_at"],
        "status": record["status"],
        "reverse_reason": record["reverse_reason"],
    })


TABLE_SERIALIZERS = (
    ("pass_programs", program_out),
    ("pass_tiers", tier_out),
    ("park_days", park_day_out),
    ("blockout_assignments", assignment_out),
    ("passholders", passholder_out),
    ("season_passes", pass_out),
    ("payment_plans", plan_out),
    ("installments", installment_out),
    ("reservations", reservation_out),
    ("visits", visit_out),
    ("sharing_cases", case_out),
    ("upgrade_orders", upgrade_out),
)


def capture_all(store):
    """Canonical state of every record, used to detect mutations (PRD 2.4)."""
    snapshot = {}
    for table, serializer in TABLE_SERIALIZERS:
        for record_id, record in getattr(store, table).items():
            payload = serializer(record)
            payload.pop("version", None)
            payload.pop("updated_at", None)
            snapshot[(table, record_id)] = json.dumps(payload, sort_keys=True, default=str)
    return snapshot
