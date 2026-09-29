"""Resource-shape assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ALLOCATION_EFFECTIVE_STATUSES,
    ALLOCATION_SOURCE_TYPES,
    ASSESSMENT_VARIANTS,
    BUYING_DECISIONS,
    CAP_STATUSES,
    CHARGEBACK_DISPUTE_STATUSES,
    DEDUCTION_STATUSES,
    DISPUTE_REASON_CODES,
    DISPUTE_STATUSES,
    EVIDENCE_KINDS,
    EVIDENCE_SUBJECT_TYPES,
    GUIDE_SCOPE_CODES,
    GUIDE_STATUSES,
    MEASUREMENT_VARIANTS,
    PO_STATUSES,
    REQUIREMENT_DOMAINS,
    SCORECARD_STATUSES,
    SETTLEMENT_STATUSES,
    SEVERITY_TIERS,
    SHIPMENT_STATUSES,
    VENDOR_STATUSES,
    VIOLATION_STATUSES,
)


def assert_common_resource_fields(data: dict):
    """Every resource but the evidence item carries an opaque UUID `id`, ISO-8601
    `created_at`/`updated_at` and an integer `version` starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_millisecond_timestamp(value: str):
    """Timestamps are ISO-8601 UTC carried to three fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO-8601 timestamp: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits, got {value!r}"
    )


def _non_negative_ints(data: dict, *fields):
    for field in fields:
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_vendor(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["payment_terms_days"], int)
    assert data["status"] in VENDOR_STATUSES
    if data["otif_score"] is not None:
        assert isinstance(data["otif_score"], (int, float))
    _non_negative_ints(
        data,
        "open_chargeback_cents",
        "recovered_lifetime_cents",
        "refund_due_cents",
        "open_violation_count",
        "open_cap_count",
    )
    assert isinstance(data["repeat_offender_flag"], bool)
    assert isinstance(data["exposure_alert_flag"], bool)


def assert_routing_guide(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["guide_code"], str) and data["guide_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["scope_code"] in GUIDE_SCOPE_CODES
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in GUIDE_STATUSES
    _non_negative_ints(data, "requirement_count")


def assert_routing_requirement(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["guide_id"], str) and data["guide_id"]
    assert isinstance(data["requirement_code"], str) and data["requirement_code"]
    assert data["domain"] in REQUIREMENT_DOMAINS
    assert data["severity_tier"] in SEVERITY_TIERS
    assert 0 <= data["min_evidence_count"] <= 5
    _non_negative_ints(
        data, "fixed_fee_cents", "per_unit_recovery_cents", "min_fee_cents", "cap_cents"
    )
    assert 0.00 <= data["handling_pct"] <= 25.00
    assert data["cap_cents"] >= 1
    assert data["cap_cents"] >= data["min_fee_cents"]


def assert_purchase_order(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert data["ordered_units"] >= 1
    assert data["unit_cost_cents"] >= 0
    assert data["status"] in PO_STATUSES
    _non_negative_ints(data, "received_units")


def assert_shipment(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["po_id"], str) and data["po_id"]
    assert isinstance(data["asn_number"], str) and data["asn_number"]
    assert data["shipped_units"] >= 1
    assert data["carton_count"] >= 1
    assert data["status"] in SHIPMENT_STATUSES
    _non_negative_ints(
        data, "invoice_value_cents", "open_violation_count", "evidence_capture_count"
    )


def assert_compliance_violation(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["shipment_id"], str) and data["shipment_id"]
    assert isinstance(data["requirement_id"], str) and data["requirement_id"]
    assert data["affected_units"] >= 1
    assert data["affected_cartons"] >= 0
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert isinstance(data["detected_by_user_id"], str) and data["detected_by_user_id"]
    assert is_iso8601_timestamp(data["detected_at"])
    assert data["status"] in VIOLATION_STATUSES
    _non_negative_ints(data, "evidence_count")


def assert_evidence_item(data: dict):
    """Evidence is append-only audit history: `id` and `created_at` only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "an evidence item must not carry updated_at"
    assert "version" not in data, "an evidence item must not carry version"
    assert data["subject_type"] in EVIDENCE_SUBJECT_TYPES
    assert data["kind"] in EVIDENCE_KINDS
    assert isinstance(data["reference_uri"], str) and data["reference_uri"]
    assert isinstance(data["captured_by_user_id"], str) and data["captured_by_user_id"]
    assert is_iso8601_timestamp(data["captured_at"])


def assert_chargeback(data: dict):
    assert_common_resource_fields(data)
    for field in ("violation_id", "vendor_id", "requirement_id"):
        assert isinstance(data[field], str) and data[field]
    assert data["assessment_variant"] in ASSESSMENT_VARIANTS
    _non_negative_ints(
        data,
        "fixed_fee_cents",
        "cost_recovery_cents",
        "gross_assessed_cents",
        "reversal_cents",
        "recovered_cents",
        "outstanding_cents",
        "evidence_at_assessment_count",
    )
    assert data["dispute_status"] in CHARGEBACK_DISPUTE_STATUSES
    assert isinstance(data["deduction_posted"], bool)
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert is_iso8601_timestamp(data["assessed_at"])


def assert_vendor_dispute(data: dict):
    assert_common_resource_fields(data)
    for field in ("chargeback_id", "vendor_id"):
        assert isinstance(data[field], str) and data[field]
    assert data["reason_code"] in DISPUTE_REASON_CODES
    assert data["claimed_reversal_cents"] >= 1
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert data["status"] in DISPUTE_STATUSES
    assert data["round_count"] >= 1
    _non_negative_ints(data, "approved_reversal_cents", "goodwill_cents")
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_scorecard(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert 0 <= data["tolerance_early_days"] <= 14
    assert 0 <= data["tolerance_late_days"] <= 14
    assert 0.00 <= data["fill_tolerance_pct"] <= 10.00
    if data["measurement_variant"] is not None:
        assert data["measurement_variant"] in MEASUREMENT_VARIANTS
    assert data["status"] in SCORECARD_STATUSES
    _non_negative_ints(
        data, "measured_po_count", "on_time_count", "in_full_count", "otif_count"
    )
    assert isinstance(data["cap_required"], bool)


def assert_corrective_action_plan(data: dict):
    assert_common_resource_fields(data)
    for field in ("vendor_id", "trigger_scorecard_id"):
        assert isinstance(data[field], str) and data[field]
    assert data["status"] in CAP_STATUSES
    assert 1 <= data["escalation_level"] <= 3
    assert data["repeat_count"] >= 0
    assert data["buying_decision"] in BUYING_DECISIONS
    assert data["submission_round"] >= 0
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["due_at"])


def assert_deduction(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["invoice_reference"], str) and data["invoice_reference"]
    assert data["status"] in DEDUCTION_STATUSES
    _non_negative_ints(
        data, "amount_cents", "allocation_count", "over_allocated_cents"
    )


def assert_recovery_allocation(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["chargeback_id"], str) and data["chargeback_id"]
    assert data["source_type"] in ALLOCATION_SOURCE_TYPES
    assert data["allocated_cents"] >= 1
    assert data["effective_status"] in ALLOCATION_EFFECTIVE_STATUSES
    assert isinstance(data["applied_by_user_id"], str) and data["applied_by_user_id"]
    assert is_iso8601_timestamp(data["applied_at"])


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_settlement_identity(chargeback: dict):
    """`outstanding_cents` is the assessed figure less reversals and recoveries,
    floored at zero, and never negative."""
    net = (
        chargeback["gross_assessed_cents"]
        - chargeback["reversal_cents"]
        - chargeback["recovered_cents"]
    )
    expected = max(net, 0)
    assert chargeback["outstanding_cents"] == expected, (
        f"outstanding_cents should be max(gross - reversal - recovered, 0) = "
        f"{expected}, got {chargeback['outstanding_cents']}"
    )


def assert_settlement_branch(chargeback: dict):
    """The four settlement branches are evaluated in a pinned order: a net of zero
    or less writes the chargeback off, recovery at or above the net makes it
    recovered, any recovery makes it partially recovered, otherwise it is
    assessed."""
    net = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
    recovered = chargeback["recovered_cents"]
    if net <= 0:
        expected = "WRITTEN_OFF"
    elif recovered >= net:
        expected = "RECOVERED"
    elif recovered > 0:
        expected = "PARTIALLY_RECOVERED"
    else:
        expected = "ASSESSED"
    assert chargeback["settlement_status"] == expected, (
        f"settlement_status should be {expected}, got {chargeback['settlement_status']}"
    )


def assert_composite_score(scorecard: dict):
    """The composite is 0.60 multiplied by `otif_pct` plus 0.40 multiplied by
    `fill_rate_pct`, rounded half up to two decimals."""
    from decimal import ROUND_HALF_UP, Decimal

    expected = (
        Decimal("0.60") * Decimal(str(scorecard["otif_pct"]))
        + Decimal("0.40") * Decimal(str(scorecard["fill_rate_pct"]))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(scorecard["composite_score"])) == expected, (
        f"composite_score should be {expected}, got {scorecard['composite_score']}"
    )


def assert_no_evidence_version_fields(items: list):
    for item in items:
        assert "version" not in item
        assert "updated_at" not in item
