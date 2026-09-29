"""Entity -> JSON projections. Field sets follow the PRD entity definitions."""

from datetime import datetime

from util import fmt_instant, fmt_stamp

STAMP_FIELDS = ("created_at", "updated_at")

PORT_FIELDS = ("id", "port_code", "name", "country_code", "docking_mode",
               "risk_buffer_minutes", "tender_egress_minutes",
               "created_at", "updated_at", "version")

MEETING_POINT_FIELDS = ("id", "port_id", "name", "zone", "max_concurrent_groups",
                        "slot_buffer_minutes", "created_at", "updated_at", "version")

PORT_CALL_FIELDS = ("id", "port_id", "voyage_code", "ship_code", "arrival_utc",
                    "all_aboard_utc", "departure_utc", "delay_minutes",
                    "effective_arrival_utc", "status",
                    "created_at", "updated_at", "version")

TENDER_WAVE_FIELDS = ("id", "port_call_id", "wave_index", "window_start_utc",
                      "window_end_utc", "guest_capacity", "priority_class",
                      "assigned_guest_count", "assigned_departure_count",
                      "created_at", "updated_at", "version")

OPERATOR_FIELDS = ("id", "port_id", "legal_name", "contact_email",
                   "insurance_expiry_date", "insurance_liability_limit_cents",
                   "commission_rate_bps", "vetting_status", "vetting_cycle_count",
                   "safety_score", "reliability_strikes", "liability_reserve_cents",
                   "latest_audit_auditor_user_id",
                   "created_at", "updated_at", "version")

AUDIT_FIELDS = ("id", "operator_id", "audit_type", "conducted_on", "raw_score",
                "critical_finding_count", "auditor_user_id", "created_at")

EXCURSION_FIELDS = ("id", "port_id", "operator_id", "alternative_excursion_id",
                    "title", "duration_minutes", "min_age", "max_age",
                    "mobility_level", "medical_warning_codes", "languages",
                    "base_price_cents", "price_tier", "is_line_operated",
                    "return_guarantee", "catalog_status", "published_at",
                    "created_at", "updated_at", "version")

DEPARTURE_FIELDS = ("id", "excursion_id", "port_call_id", "meeting_point_id",
                    "tender_wave_id", "meeting_time_utc", "dispatch_dwell_minutes",
                    "total_capacity", "precruise_allocation", "onboard_allocation",
                    "precruise_sold_seats", "onboard_sold_seats",
                    "seats_available_total", "effective_precruise_available",
                    "effective_onboard_available", "status", "cancellation_cause",
                    "projected_return_scheduled_utc", "projected_return_actual_utc",
                    "slack_minutes_scheduled", "slack_minutes_actual",
                    "timing_risk_band_scheduled", "timing_risk_band_actual",
                    "return_guarantee_eligible", "actual_return_utc",
                    "created_at", "updated_at", "version")

GUEST_FIELDS = ("id", "full_name", "birth_date", "voyage_code", "mobility_level",
                "language_pref", "medical_flags", "loyalty_tier",
                "created_at", "updated_at", "version")

BOOKING_FIELDS = ("id", "departure_id", "guest_id", "alternative_departure_id",
                  "party_size", "channel", "language_choice",
                  "medical_warning_acknowledged", "age_at_meeting",
                  "per_guest_price_cents", "quoted_total_cents", "service_fee_cents",
                  "charge_total_cents", "refunded_cents", "retained_cents",
                  "goodwill_credit_cents", "commission_accrued_cents",
                  "fulfillment_status", "financial_status", "alternative_offer_status",
                  "return_guarantee_honored", "created_at", "updated_at", "version")

LEDGER_FIELDS = ("id", "booking_id", "entry_kind", "amount_cents", "refund_pct_bps",
                 "basis", "reason_code", "created_at")

INCIDENT_FIELDS = ("id", "booking_id", "category", "severity", "occurred_utc",
                   "narrative", "filed_by_user_id", "status",
                   "created_at", "updated_at", "version")

CLAIM_FIELDS = ("id", "incident_id", "operator_id", "port_call_id",
                "claimed_amount_cents", "basis_code", "status", "dispute_round_count",
                "liability_share_bps", "settlement_amount_cents",
                "operator_charge_cents", "submitted_by_user_id",
                "adjudicated_by_user_id", "created_at", "updated_at", "version")

STATEMENT_FIELDS = ("id", "operator_id", "port_call_id", "basis", "status",
                    "gross_ticket_cents", "refunds_cents", "port_fee_cents",
                    "line_commission_cents", "claim_offset_cents",
                    "operational_penalty_cents", "payable_pre_rebate_cents",
                    "rebate_bps", "rebate_cents", "adjustment_cents",
                    "operator_payable_cents", "booking_line_count", "issued_at",
                    "settled_at", "created_at", "updated_at", "version")


def _project(row, fields):
    out = {}
    for name in fields:
        value = row.get(name)
        if isinstance(value, datetime):
            value = fmt_stamp(value) if name in STAMP_FIELDS else fmt_instant(value)
        elif isinstance(value, list):
            value = list(value)
        out[name] = value
    return out


def port_json(row):
    return _project(row, PORT_FIELDS)


def meeting_point_json(row):
    return _project(row, MEETING_POINT_FIELDS)


def port_call_json(row):
    return _project(row, PORT_CALL_FIELDS)


def tender_wave_json(row):
    return _project(row, TENDER_WAVE_FIELDS)


def operator_json(row):
    return _project(row, OPERATOR_FIELDS)


def audit_json(row):
    return _project(row, AUDIT_FIELDS)


def excursion_json(row):
    return _project(row, EXCURSION_FIELDS)


def departure_json(row):
    from services.timing import recompute_projections
    from services.allocation import recompute_seats
    recompute_projections(row)
    recompute_seats(row)
    return _project(row, DEPARTURE_FIELDS)


def guest_json(row):
    return _project(row, GUEST_FIELDS)


def booking_json(row):
    return _project(row, BOOKING_FIELDS)


def ledger_json(row):
    return _project(row, LEDGER_FIELDS)


def incident_json(row):
    return _project(row, INCIDENT_FIELDS)


def claim_json(row):
    return _project(row, CLAIM_FIELDS)


def statement_json(row):
    return _project(row, STATEMENT_FIELDS)
