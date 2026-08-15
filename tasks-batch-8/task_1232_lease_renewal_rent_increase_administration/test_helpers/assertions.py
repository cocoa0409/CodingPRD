"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LEASE_STATUSES = ["ACTIVE", "RENEWAL_PENDING", "MTM", "NON_RENEWAL_NOTICED", "ENDED"]
OFFER_STATUSES = [
    "DRAFT", "ISSUED", "COUNTERED", "ACCEPTED", "EXECUTED",
    "DECLINED", "EXPIRED", "WITHDRAWN", "SUPERSEDED", "VOIDED",
]
CONCESSION_STATUSES = ["SUBMITTED", "APPROVED", "DENIED", "APPLIED", "VOIDED"]
NOTICE_STATUSES = ["DRAFT", "SERVED", "CONFIRMED", "ENFORCED", "RESCINDED"]
DOCUMENT_STATUSES = ["GENERATED", "RESIDENT_SIGNED", "COUNTERSIGNED", "VOIDED", "RESCINDED"]
RATE_STRATEGIES = ["AGGRESSIVE", "BALANCED", "CONSERVATIVE"]
CAUSE_TYPES = [
    "LEASE_VIOLATION", "REPEATED_LATE_PAYMENT", "PROPERTY_REPOSITIONING", "OWNER_OCCUPANCY",
]


def _assert_common(data: dict, label: str):
    """PRD §2.5 shared system-managed fields."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_rent_cap_policy(data: dict):
    _assert_common(data, "RentCapPolicy")
    for f in (
        "jurisdiction_code", "base_cap_bps", "cpi_adjustment_bps", "hard_ceiling_bps",
        "high_increase_threshold_bps", "notice_days_low", "notice_days_high",
        "non_renewal_notice_days", "effective_cap_bps",
    ):
        assert f in data, f"RentCapPolicy missing {f}"
    # PRD §2.8: effective cap is the lesser of base+CPI and the hard ceiling.
    assert data["effective_cap_bps"] == min(
        data["base_cap_bps"] + data["cpi_adjustment_bps"], data["hard_ceiling_bps"]
    ), "effective_cap_bps must equal min(base_cap_bps + cpi_adjustment_bps, hard_ceiling_bps)"


def assert_property(data: dict):
    _assert_common(data, "Property")
    for f in ("name", "rent_cap_policy_id", "min_term_months", "max_term_months"):
        assert f in data, f"Property missing {f}"
    assert data["min_term_months"] >= 1
    assert data["max_term_months"] >= data["min_term_months"]


def assert_unit(data: dict):
    _assert_common(data, "Unit")
    for f in ("property_id", "unit_number", "bedrooms", "current_market_rent_cents"):
        assert f in data, f"Unit missing {f}"


def assert_resident(data: dict):
    _assert_common(data, "Resident")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]


def assert_lease(data: dict):
    _assert_common(data, "Lease")
    for f in (
        "unit_id", "resident_id", "property_id", "term_start_date", "term_months",
        "term_end_date", "monthly_rent_cents", "status",
    ):
        assert f in data, f"Lease missing {f}"
    assert data["status"] in LEASE_STATUSES
    assert "status_before_offer" in data, "Lease missing status_before_offer"
    assert "mtm_converted_on" in data, "Lease missing mtm_converted_on"


def assert_renewal_offer(data: dict):
    _assert_common(data, "RenewalOffer")
    for f in (
        "lease_id", "rate_strategy", "offer_round", "base_rent_cents",
        "proposed_rent_cents", "proposed_increase_bps", "cap_bps_snapshot",
        "offered_term_months", "notice_days_required", "status",
    ):
        assert f in data, f"RenewalOffer missing {f}"
    assert data["status"] in OFFER_STATUSES
    assert data["rate_strategy"] in RATE_STRATEGIES
    for f in (
        "latest_issue_date", "issued_on_date", "issued_by_user_id",
        "response_deadline_date", "counter_rent_cents", "counter_term_months",
        "accepted_on_date", "execution_deadline_date", "executed_rent_cents",
        "supersedes_offer_id",
    ):
        assert f in data, f"RenewalOffer missing {f}"


def assert_concession_approval(data: dict):
    _assert_common(data, "ConcessionApproval")
    for f in (
        "offer_id", "requested_rent_cents", "concession_bps",
        "requested_by_user_id", "decided_by_user_id", "status",
    ):
        assert f in data, f"ConcessionApproval missing {f}"
    assert data["status"] in CONCESSION_STATUSES


def assert_non_renewal_notice(data: dict):
    _assert_common(data, "NonRenewalNotice")
    for f in (
        "lease_id", "cause_type", "effective_date", "served_on_date",
        "cure_deadline_date", "prior_lease_status", "created_by_user_id",
        "served_by_user_id", "status",
    ):
        assert f in data, f"NonRenewalNotice missing {f}"
    assert data["status"] in NOTICE_STATUSES
    assert data["cause_type"] in CAUSE_TYPES


def assert_renewal_document(data: dict):
    _assert_common(data, "RenewalDocument")
    for f in (
        "offer_id", "lease_id", "status", "executed_rent_cents",
        "countersigned_on_date", "rescind_deadline_date",
        "prior_lease_status", "prior_monthly_rent_cents", "prior_term_start_date",
        "prior_term_end_date", "prior_term_months",
    ):
        assert f in data, f"RenewalDocument missing {f}"
    assert data["status"] in DOCUMENT_STATUSES
