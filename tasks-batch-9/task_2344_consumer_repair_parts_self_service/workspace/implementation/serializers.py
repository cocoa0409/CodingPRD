"""Entity -> JSON projections. Common fields per PRD 2.4."""
import math

import db
from util import as_number, fmt_ts

_TS_FIELDS = (
    "created_at", "updated_at", "market_release_date", "end_of_production_date",
    "last_hardware_change_date", "support_end_date", "parts_available_until",
    "documentation_available_until", "last_attested_at", "effective_from",
    "effective_until", "published_at", "expires_at", "core_return_due_at",
    "disclosure_acknowledged_at", "confirmed_at", "delivered_at", "acknowledged_at",
    "valid_from", "valid_until", "received_at", "rental_window_start",
    "rental_window_end",
)

_NUM_FIELDS = ("buyer_multiplier", "volume_multiplier", "tier_surcharge_multiplier")


def _project(row, fields):
    out = {}
    for name in fields:
        value = row.get(name)
        if name in _TS_FIELDS:
            out[name] = fmt_ts(value)
        elif name in _NUM_FIELDS:
            out[name] = as_number(value)
        else:
            out[name] = value
    return out


COMMON = ("created_at", "updated_at", "version")

MODEL_FIELDS = (
    "id", "model_code", "product_family", "market_release_date",
    "end_of_production_date", "last_hardware_change_date", "repairability_tier",
    "support_state", "support_end_date", "documentation_posture",
    "published_disassembly_revision_number", "published_safety_sheet_revision_number",
    "compliance_posture", "open_obligation_count",
) + COMMON

PROFILE_FIELDS = (
    "id", "region_code", "min_parts_availability_years", "min_documentation_years",
    "requires_public_manual", "max_documentation_fee_cents",
    "allows_pairing_restriction", "self_service_mandate_tier",
) + COMMON

OBLIGATION_FIELDS = (
    "id", "model_id", "region_code", "parts_available_until",
    "documentation_available_until", "deadline_basis", "status",
    "documentation_verified", "last_attested_at", "last_attested_by_user_id",
    "breach_count",
) + COMMON

PART_FIELDS = (
    "id", "sku", "part_class", "safety_class", "list_price_cents",
    "core_return_required", "core_credit_cents", "rental_deposit_cents",
    "concurrent_rental_capacity", "requires_authentication", "requires_calibration",
    "supersedes_part_id", "status", "restriction_reason",
    "core_face_value_committed_cents", "core_liability_outstanding_cents",
    "core_credit_settled_cents", "core_credit_forfeited_cents",
) + COMMON

COMPAT_FIELDS = (
    "id", "part_id", "model_id", "required_tool_part_id", "self_service_eligible",
    "install_minutes", "effective_from", "effective_until",
    "superseded_by_safety_restriction",
) + COMMON

REVISION_FIELDS = (
    "id", "model_id", "doc_type", "revision_number", "covered_part_skus",
    "safety_warning_count", "status", "authored_by_user_id", "reviewed_by_user_id",
    "rejection_cycle_count", "effective_from", "published_at",
    "coverage_gap_sku_count",
) + COMMON

ASSESSMENT_FIELDS = (
    "id", "model_id", "part_id", "provider_id", "pinned_manual_revision_id",
    "region_code", "requester_class", "requester_user_id", "decision",
    "warranty_impact_class", "self_repair_risk_index", "liability_warning_version",
    "tool_rental_part_id", "status", "expires_at",
) + COMMON

ORDER_FIELDS = (
    "id", "assessment_id", "model_id", "provider_id", "pinned_manual_revision_id",
    "pinned_manual_revision_number", "region_code", "buyer_class",
    "customer_user_id", "rental_window_start", "rental_window_end",
    "fulfillment_status", "core_return_status", "warranty_impact_class",
    "parts_subtotal_cents", "tool_purchase_cents", "rental_deposit_cents",
    "documentation_fee_cents", "core_deposit_cents", "total_due_cents",
    "core_credit_provisional_cents", "core_credit_final_cents",
    "core_return_due_at", "core_days_late", "disclosure_acknowledged_at",
    "confirmed_at", "delivered_at", "blocked_reason", "cancellation_reason",
) + COMMON

LINE_FIELDS = (
    "id", "order_id", "part_id", "quantity", "buyer_multiplier",
    "volume_multiplier", "tier_surcharge_multiplier", "unit_price_cents",
    "line_total_cents", "authentication_status", "calibration_status",
    "calibration_attempt_count", "last_measured_offset_ppm", "pairing_token",
) + COMMON

ACK_FIELDS = (
    "id", "order_id", "warranty_impact_class_ack", "liability_warning_version",
    "acknowledged_scope", "acknowledged_by_user_id", "manual_revision_number",
    "acknowledged_at", "created_at",
)

PROVIDER_FIELDS = (
    "id", "legal_name", "region_code", "requested_access_tier", "technician_count",
    "authorization_status", "parts_access_tier", "training_credit_granted_total",
    "training_credit_balance", "training_credit_forfeited_total",
    "required_cert_count", "active_cert_count", "attested_compliance_score",
    "suspension_reason",
) + COMMON

CERT_FIELDS = (
    "id", "provider_id", "technician_user_id", "course_code", "valid_from",
    "valid_until", "exam_score", "status", "credits_consumed", "void_reason",
) + COMMON

CASE_FIELDS = (
    "id", "order_line_id", "part_id", "quantity", "reported_failure_code", "status",
    "root_cause_code", "defect_confirmed", "analyzed_by_user_id",
    "decided_by_user_id", "provisional_credit_cents", "final_credit_cents",
    "received_at",
) + COMMON


def model_json(row):
    return _project(row, MODEL_FIELDS)


def profile_json(row):
    return _project(row, PROFILE_FIELDS)


def obligation_json(row):
    return _project(row, OBLIGATION_FIELDS)


def part_json(row):
    return _project(row, PART_FIELDS)


def compat_json(row):
    return _project(row, COMPAT_FIELDS)


def revision_json(row):
    return _project(row, REVISION_FIELDS)


def assessment_json(row):
    return _project(row, ASSESSMENT_FIELDS)


def order_json(row):
    return _project(row, ORDER_FIELDS)


def line_json(row):
    return _project(row, LINE_FIELDS)


def ack_json(row):
    return _project(row, ACK_FIELDS)


def provider_json(row):
    out = _project(row, PROVIDER_FIELDS)
    out["required_cert_count"] = required_cert_count(row)
    out["active_cert_count"] = active_cert_count(row["id"])
    return out


def cert_json(row):
    return _project(row, CERT_FIELDS)


def case_json(row):
    return _project(row, CASE_FIELDS)


# --------------------------------------------------------------------------
# derived counters used both by projections and by business rules
# --------------------------------------------------------------------------

def required_cert_count(provider):
    return int(math.ceil(provider["technician_count"] / 4.0))


def active_cert_count(provider_id):
    return sum(
        1 for c in db.db.certs.all()
        if c["provider_id"] == provider_id and c["status"] == "ACTIVE"
    )
