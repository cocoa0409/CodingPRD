"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_DRUG_STATUSES = {"ACTIVE", "DISCONTINUED"}
_DEA_SCHEDULES = {"NONE", "CII", "CIII", "CIV", "CV"}
_RX_STATUSES = {"ACTIVE", "EXHAUSTED", "EXPIRED", "DISCONTINUED"}
_FILL_STATUSES = {
    "ENTERED", "DUR_REVIEW", "ADJUDICATING", "PA_REFERRAL", "READY_FILL",
    "WILL_CALL", "DISPENSED", "RETURNED_TO_STOCK", "CANCELLED",
}
_CLAIM_STATUSES = {"UNCLAIMED", "SUBMITTED", "PAID", "REJECTED", "PA_PENDING", "REVERSED"}
_PA_STATUSES = {"PENDING", "APPROVED", "DENIED", "EXPIRED"}
_PDMP_FLAGS = {"CLEAR", "REVIEW", "BLOCKED"}
_CONTROLLED_STATUSES = {"ELIGIBLE", "LOCKED"}
_DUR_SEVERITIES = {"NONE", "MINOR", "MODERATE", "SEVERE"}
_ALERT_TYPES = {"INTERACTION", "ALLERGY", "DUPLICATE_THERAPY", "HIGH_DOSE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_drug_product(data: dict):
    _assert_common(data)
    assert isinstance(data["ndc"], str) and len(data["ndc"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["dea_schedule"] in _DEA_SCHEDULES, data.get("dea_schedule")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["pa_required"], bool)
    assert isinstance(data["is_active"], bool)
    assert data["status"] in _DRUG_STATUSES, data.get("status")


def assert_insurance_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["bin"], str) and isinstance(data["pcn"], str)
    assert 0.0 <= data["copay_pct"] <= 1.0
    assert isinstance(data["copay_max_cents"], int)
    assert data["copay_max_cents"] > data["copay_min_cents"]


def assert_formulary_entry(data: dict):
    _assert_common(data)
    assert 1 <= data["tier"] <= 4
    assert isinstance(data["allowed_amount_cents"], int) and data["allowed_amount_cents"] >= 0


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["allergy_classes"], list)
    assert isinstance(data["auto_refill_enrolled"], bool)
    assert data["pdmp_flag"] in _PDMP_FLAGS, data.get("pdmp_flag")
    assert data["controlled_status"] in _CONTROLLED_STATUSES, data.get("controlled_status")


def assert_prescriber(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert isinstance(data["dea_active"], bool)


def assert_prescription(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_per_fill"], int) and data["quantity_per_fill"] > 0
    assert isinstance(data["days_supply"], int) and data["days_supply"] > 0
    assert isinstance(data["refills_remaining"], int) and data["refills_remaining"] >= 0
    assert is_iso8601_timestamp(data["expires_utc"]), "expires_utc must be ISO 8601"
    assert data["status"] in _RX_STATUSES, data.get("status")


def assert_fill(data: dict):
    _assert_common(data)
    assert isinstance(data["fill_sequence"], int) and data["fill_sequence"] >= 1
    assert isinstance(data["quantity_dispensed"], int) and data["quantity_dispensed"] >= 0
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 0
    assert data["dur_severity"] in _DUR_SEVERITIES, data.get("dur_severity")
    assert data["claim_status"] in _CLAIM_STATUSES, data.get("claim_status")
    assert data["status"] in _FILL_STATUSES, data.get("status")


def assert_dur_alert(data: dict):
    _assert_common(data)
    assert data["alert_type"] in _ALERT_TYPES, data.get("alert_type")
    assert data["severity"] in _DUR_SEVERITIES, data.get("severity")
    assert isinstance(data["overridden"], bool)


def assert_interaction_rule(data: dict):
    _assert_common(data)
    assert data["severity"] in _DUR_SEVERITIES, data.get("severity")


def assert_prior_auth_request(data: dict):
    _assert_common(data)
    assert data["status"] in _PA_STATUSES, data.get("status")
    assert is_iso8601_timestamp(data["submitted_utc"]), "submitted_utc must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_utc"]), "expires_utc must be ISO 8601"


def assert_pdmp_report(data: dict):
    _assert_common(data)
    assert isinstance(data["controlled_fill_count"], int) and data["controlled_fill_count"] >= 0
    assert isinstance(data["distinct_prescriber_count"], int) and data["distinct_prescriber_count"] >= 0
    assert isinstance(data["risk_score"], int) and data["risk_score"] >= 0
    assert data["resulting_flag"] in _PDMP_FLAGS, data.get("resulting_flag")


def assert_payment_record(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["refunded"], bool)


def assert_money_conserved(fill: dict):
    """Compensating invariant (PRD §3.9): after reversal plan_paid reverts to 0
    while gross_amount_cents is untouched."""
    assert fill["plan_paid_cents"] == 0, \
        f"plan_paid_cents must revert to 0, got {fill['plan_paid_cents']}"
    assert fill["gross_amount_cents"] >= 0
