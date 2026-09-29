"""Row -> JSON projection. Field lists mirror the entity tables exactly."""
from datetime import datetime
from decimal import Decimal

import clock

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY = ("id", "created_at")

TERMINAL = (
    "code",
    "name",
    "calibration_interval_captures",
    "captures_since_calibration",
    "dimensioner_status",
    "last_capture_at",
)

CUSTOMER = (
    "account_code",
    "name",
    "billing_posture",
    "education_status",
    "education_strike_interval",
    "education_threshold_strikes",
    "education_required_at",
    "offender_strike_count",
    "liability_index_rolling",
    "liability_index_lifetime",
    "offender_tier",
    "dispute_window_days",
    "active_program_type",
)

TARIFF_VERSION = (
    "code",
    "effective_at",
    "status",
    "density_breaks",
    "superseded_by_tariff_version_id",
    "published_at",
)

COMMODITY_PROFILE = (
    "tariff_version_id",
    "nmfc_item",
    "description",
    "classification_basis",
    "fixed_class_code",
    "handling_code",
    "stowability_code",
    "liability_code",
    "min_class_floor",
)

RATE_PROGRAM = (
    "customer_id",
    "program_type",
    "status",
    "base_rate_per_cwt_cents",
    "discount_pct",
    "min_charge_cents",
    "fak_class_code",
    "pinned_tariff_version_id",
    "effective_from",
    "effective_to",
    "baseline_revenue_cents",
    "modeled_annual_revenue_cents",
    "modeled_delta_pct",
    "modeled_shipment_count",
    "migration_recommendation",
)

EXCEPTION_AGREEMENT = (
    "customer_id",
    "commodity_profile_id",
    "agreement_type",
    "agreed_class_code",
    "effective_from",
    "effective_to",
    "status",
    "approved_by_user_id",
    "approved_at",
)

SHIPMENT = (
    "customer_id",
    "origin_terminal_id",
    "rate_program_id",
    "tariff_version_id",
    "pro_number",
    "pickup_at",
    "bol_declared_total_weight_lb",
    "class_status",
    "billing_status",
    "line_count",
    "declared_total_weight_lb",
    "measured_total_weight_lb",
    "weight_variance_pct",
    "reweigh_required",
    "declared_vs_found_class_delta_count",
    "original_charge_cents",
    "assessed_total_cents",
    "open_notice_count",
    "billed_at",
)

SHIPMENT_LINE = (
    "shipment_id",
    "line_no",
    "commodity_profile_id",
    "declared_class_code",
    "declared_weight_lb",
    "pieces",
    "declared_length_in",
    "declared_width_in",
    "declared_height_in",
    "declared_cubic_ft",
    "declared_density_pcf",
    "measured_weight_lb",
    "measured_length_in",
    "measured_width_in",
    "measured_height_in",
    "measured_cubic_ft",
    "measured_density_pcf",
    "found_class_code",
    "effective_class_code",
    "classification_source",
    "class_floor_applied",
    "line_charge_cents",
)

CAPTURE_EVENT = (
    "shipment_id",
    "terminal_id",
    "captured_by_user_id",
    "device_type",
    "capture_sequence",
    "measured_total_weight_lb",
    "line_measurements",
    "captured_at",
    "variance_pct",
    "triggered_reweigh",
    "triggered_reclass",
    "reclassed_line_count",
)

INSPECTION_FINDING = (
    "shipment_line_id",
    "inspector_user_id",
    "finding_basis",
    "found_commodity_profile_id",
    "found_class_code",
    "evidence_photo_count",
    "notes",
    "status",
    "accepted_by_user_id",
    "accepted_at",
)

CORRECTION_NOTICE = (
    "shipment_id",
    "basis_capture_event_id",
    "supersedes_notice_id",
    "notice_type",
    "origin",
    "issued_by_user_id",
    "provisional_delta_cents",
    "final_delta_cents",
    "applied_delta_cents",
    "inspection_fee_cents",
    "evidence_bundle_count",
    "uses_inspection_findings",
    "status",
    "issued_at",
    "dispute_deadline_at",
    "dispute_round_count",
    "supplement_request_count",
    "resolved_at",
    "credited_total_cents",
)

DISPUTE = (
    "correction_notice_id",
    "filed_by_customer_id",
    "round_no",
    "claim_basis",
    "claimed_class_code",
    "evidence_doc_count",
    "filed_at",
    "reviewer_user_id",
    "outcome",
    "outcome_class_code",
    "status",
    "resolved_at",
)

CREDIT_MEMO = (
    "correction_notice_id",
    "customer_id",
    "reason",
    "freight_credit_cents",
    "fee_credit_cents",
    "interest_credit_cents",
    "amount_cents",
    "issued_at",
)

REPRICING_RUN = (
    "new_tariff_version_id",
    "scope",
    "sample_window_start_at",
    "sample_window_end_at",
    "status",
    "impacted_customer_count",
    "aggregate_delta_cents",
    "modeled_at",
    "committed_at",
)


def value(raw):
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw
    if isinstance(raw, Decimal):
        if raw == raw.to_integral_value():
            return int(raw)
        return float(raw)
    if isinstance(raw, float):
        return raw
    if isinstance(raw, datetime):
        return clock.iso(raw)
    if isinstance(raw, (list, tuple)):
        return [value(item) for item in raw]
    if isinstance(raw, dict):
        return {key: value(item) for key, item in raw.items()}
    return raw


def project(row, fields, common=COMMON):
    if row is None:
        return None
    out = {}
    for name in common:
        out[name] = value(row.get(name))
    for name in fields:
        out[name] = value(row.get(name))
    return out


def terminal(row):
    return project(row, TERMINAL)


def customer(row):
    return project(row, CUSTOMER)


def tariff_version(row):
    return project(row, TARIFF_VERSION)


def commodity_profile(row):
    return project(row, COMMODITY_PROFILE)


def rate_program(row):
    return project(row, RATE_PROGRAM)


def exception_agreement(row):
    return project(row, EXCEPTION_AGREEMENT)


def shipment(row):
    return project(row, SHIPMENT)


def shipment_line(row):
    return project(row, SHIPMENT_LINE)


def capture_event(row):
    return project(row, CAPTURE_EVENT, common=APPEND_ONLY)


def inspection_finding(row):
    return project(row, INSPECTION_FINDING)


def correction_notice(row):
    return project(row, CORRECTION_NOTICE)


def dispute(row):
    return project(row, DISPUTE)


def credit_memo(row):
    return project(row, CREDIT_MEMO, common=APPEND_ONLY)


def repricing_run(row):
    return project(row, REPRICING_RUN)
