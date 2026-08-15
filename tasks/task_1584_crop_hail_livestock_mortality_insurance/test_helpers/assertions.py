"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Each assert_{entity}() checks only fields the PRD guarantees: the common
resource properties of §2.4 plus the fields PRD prose explicitly assigns.
Nullable or conditional fields are checked for type only when present.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

GROWER_STATUSES = ["ACTIVE", "SUSPENDED", "DEBARRED"]
FEDERAL_STATUSES = ["ACTIVE", "EXPIRED", "CANCELLED"]
RATE_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
RATING_KINDS = ["CROP_HAIL", "LIVESTOCK_MORTALITY"]
SPECIES = ["CATTLE", "SWINE", "POULTRY", "EQUINE", "SHEEP"]
POLICY_KINDS = ["CROP_HAIL", "LIVESTOCK_MORTALITY"]
LIFECYCLE_STATES = ["APPLICATION", "BOUND", "ACTIVE", "EXPIRED", "CANCELLED", "NON_RENEWED"]
BILLING_STATES = ["UNBILLED", "BILLED", "PARTIALLY_PAID", "PAID_IN_FULL", "DELINQUENT"]
CLAIMS_POSTURES = ["OPEN", "RESTRICTED"]
UNIT_STATUSES = ["PENDING_REPORT", "REPORTED", "LAPSED_REPORT", "UNDER_CLAIM", "SETTLED"]
CLAIM_STATES = [
    "REPORTED", "INSPECTION_SCHEDULED", "INSPECTED", "UNDER_REVIEW",
    "APPROVED", "DENIED", "PAID", "WITHDRAWN", "CLOSED_UNTIMELY",
]
CLAIM_KINDS = ["HAIL_DAMAGE", "LIVESTOCK_MORTALITY"]
DOC_POSTURES = ["DOCS_PENDING", "DOCS_COMPLETE", "DOCS_WAIVED"]
PAYMENT_STATUSES = ["ISSUED", "CLEARED", "VOID"]
PAYMENT_METHODS = ["ACH", "CHECK", "WIRE"]
DETERMINATION_DECISIONS = ["APPROVE", "DENY", "PARTIAL"]
RENEWAL_DECISIONS = ["RENEW", "NON_RENEW"]


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(ts, str), f"expected timestamp string, got {type(ts)}"
    normalized = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_timestamp_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two timestamps denote the same instant (fractional-digit formatting is
    an implementation choice; the instant is the contract)."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC: {actual!r}"
    assert _parse_utc(actual) == _parse_utc(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int: {data.get('version')!r}"
    )


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert is_iso8601_timestamp(data.get("current_utc", "")), "current_utc must be ISO 8601"
    assert isinstance(data["reinsurance_treaty_attachment_cents"], int)


def assert_grower(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["tax_id_last4"], str) and len(data["tax_id_last4"]) == 4
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["county_code"], str)
    assert isinstance(data["state_code"], str)
    assert data["status"] in GROWER_STATUSES
    assert isinstance(data["prior_claims_count"], int) and data["prior_claims_count"] >= 0
    assert "continuous_coverage_since" in data, "continuous_coverage_since must be present"
    if data["continuous_coverage_since"] is not None:
        assert is_iso8601_timestamp(data["continuous_coverage_since"])


def assert_adjuster(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["county_codes"], list)
    assert isinstance(data["species_qualified"], list)
    assert isinstance(data["capacity_max_open_claims"], int)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_rate_table(data: dict):
    _assert_common(data)
    assert data["rating_kind"] in RATING_KINDS
    assert isinstance(data["rate_per_100_cents_of_liability"], int)
    assert is_iso8601_timestamp(data.get("effective_from", "")), "effective_from ISO 8601"
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in RATE_STATUSES


def assert_federal_crop_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["fci_policy_number"], str) and data["fci_policy_number"]
    assert isinstance(data["crop_code"], str)
    assert isinstance(data["county_code"], str)
    assert isinstance(data["liability_cents"], int)
    assert data["status"] in FEDERAL_STATUSES


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"].startswith("POL-")
    assert data["policy_kind"] in POLICY_KINDS
    assert data["lifecycle_state"] in LIFECYCLE_STATES
    assert data["billing_state"] in BILLING_STATES
    assert data["claims_posture"] in CLAIMS_POSTURES
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0
    assert isinstance(data["premium_paid_cents"], int) and data["premium_paid_cents"] >= 0
    assert isinstance(data["premium_reserve_cents"], int) and data["premium_reserve_cents"] >= 0
    assert isinstance(data["high_risk_surcharge_pct"], int)
    assert isinstance(data["continuous_coverage_carryover_credit_cents"], int)


def assert_policy_invariants(data: dict):
    """Domain invariants that must hold on any policy read (PRD §3.4, §3.8)."""
    import math

    assert data["premium_cents"] >= 0, "premium never negative (floored at zero)"
    assert 0 <= data["premium_reserve_cents"] <= math.floor(data["premium_cents"] * 0.60) or (
        data["premium_cents"] == 0 and data["premium_reserve_cents"] == 0
    ), "reserve is 60% of premium less approved/paid indemnities, floored at zero"
    if data["billing_state"] == "DELINQUENT" or data["lifecycle_state"] in (
        "EXPIRED", "CANCELLED", "NON_RENEWED",
    ):
        assert data["claims_posture"] == "RESTRICTED", (
            "posture reads RESTRICTED when delinquent or in a terminal lifecycle state"
        )


def assert_coverage_unit(data: dict):
    _assert_common(data)
    assert data["unit_kind"] in POLICY_KINDS
    assert data["status"] in UNIT_STATUSES
    assert isinstance(data["liability_cents"], int) and data["liability_cents"] >= 0
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0


def assert_acreage_report(data: dict):
    _assert_common(data)
    assert data["report_kind"] in ["PLANTING", "HARVEST"]
    assert isinstance(data["reported_acres"], int)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert isinstance(data["is_timely"], bool)
    assert isinstance(data["lateness_days"], int) and data["lateness_days"] >= 0
    assert isinstance(data["coverage_reduction_pct"], int)
    assert 0 <= data["coverage_reduction_pct"] <= 100


def assert_head_report(data: dict):
    _assert_common(data)
    assert data["report_kind"] in ["INITIAL", "INTERIM", "FINAL"]
    assert isinstance(data["reported_head_count"], int)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert isinstance(data["is_timely"], bool)
    assert isinstance(data["lateness_days"], int) and data["lateness_days"] >= 0
    assert isinstance(data["coverage_reduction_pct"], int)
    assert 0 <= data["coverage_reduction_pct"] <= 100


def assert_claim(data: dict):
    _assert_common(data)
    assert data["claim_kind"] in CLAIM_KINDS
    assert data["claim_state"] in CLAIM_STATES
    assert data["doc_posture"] in DOC_POSTURES
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert isinstance(data["reported_within_window"], bool)
    assert isinstance(data["late_notification_penalty_pct"], int)
    assert isinstance(data["provisional_indemnity_cents"], int)
    assert isinstance(data["final_indemnity_cents"], int)
    assert data.get("adjuster_id") is None or isinstance(data["adjuster_id"], str)


def assert_field_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["adjuster_id"], str)
    assert is_iso8601_timestamp(data.get("inspected_at", ""))
    assert isinstance(data["within_inspection_window"], bool)
    assert isinstance(data["provisional_indemnity_cents"], int)


def assert_veterinary_report(data: dict):
    _assert_common(data)
    assert isinstance(data["veterinarian_license"], str)
    assert data["report_kind"] in [
        "VETERINARY_CERTIFICATE", "NECROPSY_REPORT", "THIRD_PARTY_AFFIDAVIT",
    ]
    assert isinstance(data["necropsy_performed"], bool)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))


def assert_loss_determination(data: dict):
    _assert_common(data)
    assert data["decision"] in DETERMINATION_DECISIONS
    assert isinstance(data["reviewer_id"], str)
    assert isinstance(data["approved_indemnity_cents"], int)
    assert isinstance(data["applied_coverage_reduction_pct"], int)
    assert isinstance(data["applied_late_notification_penalty_pct"], int)
    assert isinstance(data["applied_dual_coverage_offset_cents"], int)
    assert isinstance(data["final_indemnity_cents"], int) and data["final_indemnity_cents"] >= 0
    assert is_iso8601_timestamp(data.get("decided_at", ""))


def assert_indemnity_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert data["payment_method"] in PAYMENT_METHODS
    assert data["status"] in PAYMENT_STATUSES


def assert_dual_coverage_link(data: dict):
    _assert_common(data)
    assert isinstance(data["federal_crop_policy_id"], str)
    assert data["offset_pct_of_federal_liability"] == 20, (
        "a successful link fixes offset_pct_of_federal_liability at 20 (PRD §3.3)"
    )
    assert is_iso8601_timestamp(data.get("established_at", ""))


def assert_renewal(data: dict):
    _assert_common(data)
    assert data["decision"] in RENEWAL_DECISIONS
    assert isinstance(data["continuity_gap_days"], int) and data["continuity_gap_days"] >= 0
    assert isinstance(data["carryover_credit_cents"], int) and data["carryover_credit_cents"] >= 0
    assert is_iso8601_timestamp(data.get("decided_at", ""))


def assert_premium_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("posted_at", ""))
