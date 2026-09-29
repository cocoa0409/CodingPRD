"""
Domain assertions for the Employer Tuition Benefit Administration API.

These wrap the invariants the PRD states in prose so a test can assert them in
one line: the conserved cap pool of §2.6, the obligation identity of §3.7, the
per-row and per-year tax ledger identities of §2.10, the persistence banding of
§3.8 and the envelope shapes of §2.2 and §2.3.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    PERSISTENCE_TIER_HIGH_FLOOR,
    PERSISTENCE_TIER_MEDIUM_FLOOR,
    RISK_SCORE_MAX,
    RISK_SCORE_MIN,
    TAX_EXCLUSION_LIMIT_CENTS,
    expected_persistence_tier,
)
from .types import FundingStatus, TaxEntryType

Record = Dict[str, Any]


# ─── Common resource properties (PRD §2.4) ─────────────────────────────────
def assert_versioned_record(record: Record, expected_version: Optional[int] = None):
    """A versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int) and record["version"] >= 1
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_append_only_record(record: Record):
    """An append-only row carries only id and created_at — no version at all."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only rows have no updated_at"
    assert "version" not in record, "append-only rows have no version field"


# ─── Envelope and pagination (PRD §2.2, §2.3) ─────────────────────────────
def assert_error_envelope(body: Record):
    """An error envelope's meta carries only the two request-identity keys."""
    assert body["response_type"] == "error", body["response_type"]
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, meta
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert set(body["data"].keys()) == {"error_id", "message"}, body["data"]


def assert_pagination_meta(
    meta: Record,
    expected_limit: int,
    expected_offset: int,
    expected_total: int,
    expected_has_more: bool,
):
    """Every list response reports limit, offset, total_count and has_more."""
    assert meta["limit"] == expected_limit, meta
    assert meta["offset"] == expected_offset, meta
    assert meta["total_count"] == expected_total, meta
    assert meta["has_more"] is expected_has_more, meta


# ─── The annual benefit cap as a conserved pool (PRD §2.6) ────────────────
def assert_cap_buckets(
    employee: Record,
    reserved: int,
    disbursed: int,
    clawback_hold: int,
    available: int,
):
    """Pin all four cap buckets of one employee at once."""
    assert employee["cap_reserved_cents"] == reserved, employee
    assert employee["cap_disbursed_cents"] == disbursed, employee
    assert employee["cap_clawback_hold_cents"] == clawback_hold, employee
    assert employee["cap_available_cents"] == available, employee


def assert_cap_pool_conserved(employee: Record, annual_cap_cents: int):
    """annual_cap_cents == available + reserved + disbursed + clawback_hold."""
    total = (
        employee["cap_available_cents"]
        + employee["cap_reserved_cents"]
        + employee["cap_disbursed_cents"]
        + employee["cap_clawback_hold_cents"]
    )
    assert total == annual_cap_cents, (
        f"cap pool not conserved: {annual_cap_cents} != "
        f"{employee['cap_available_cents']} + {employee['cap_reserved_cents']} + "
        f"{employee['cap_disbursed_cents']} + {employee['cap_clawback_hold_cents']}"
    )


# ─── Enrollment axes and money fields (PRD §3.4) ──────────────────────────
def assert_enrollment_axes(
    enrollment: Record, academic_status: str, funding_status: str
):
    """The two axes advance independently, so pin both explicitly."""
    assert enrollment["academic_status"] == academic_status, enrollment
    assert enrollment["funding_status"] == funding_status, enrollment


def assert_employee_share_tracks_money_axis(enrollment: Record):
    """employee_share_cents is not frozen at creation; it tracks the money axis."""
    gross = enrollment["gross_tuition_cents"]
    funding_status = enrollment["funding_status"]
    if funding_status in (FundingStatus.RESERVED, FundingStatus.BILLED):
        expected = gross - enrollment["employer_reserved_cents"]
    elif funding_status in (FundingStatus.SETTLED, FundingStatus.CLAWED_BACK):
        expected = gross - enrollment["employer_settled_cents"]
    else:
        expected = gross
    assert enrollment["employee_share_cents"] == expected, (
        f"employee_share_cents {enrollment['employee_share_cents']} does not track "
        f"funding_status {funding_status}; expected {expected}"
    )


# ─── Repayment obligations (PRD §3.7) ─────────────────────────────────────
def assert_obligation_identity(obligation: Record):
    """principal_cents == paid_cents + waived_cents + balance_cents."""
    total = (
        obligation["paid_cents"]
        + obligation["waived_cents"]
        + obligation["balance_cents"]
    )
    assert obligation["principal_cents"] == total, (
        f"obligation identity broken: {obligation['principal_cents']} != "
        f"{obligation['paid_cents']} + {obligation['waived_cents']} + "
        f"{obligation['balance_cents']}"
    )


# ─── The educational-assistance tax ledger (PRD §2.10) ────────────────────
def assert_ledger_row_identity(entry: Record):
    """On every row without exception, benefit == excluded + imputed."""
    assert entry["benefit_cents"] == (
        entry["excluded_cents"] + entry["imputed_income_cents"]
    ), entry


def assert_ledger_row(
    entry: Record,
    entry_type: str,
    benefit_cents: int,
    excluded_cents: int,
    imputed_income_cents: int,
    tax_year: Optional[int] = None,
):
    """Pin one ledger row's three-way split and re-check the per-row identity."""
    assert entry["entry_type"] == entry_type, entry
    assert entry["benefit_cents"] == benefit_cents, entry
    assert entry["excluded_cents"] == excluded_cents, entry
    assert entry["imputed_income_cents"] == imputed_income_cents, entry
    if tax_year is not None:
        assert entry["tax_year"] == tax_year, entry
    assert_ledger_row_identity(entry)


def assert_true_up_row_shape(entry: Record):
    """True-up rows are annual, so enrollment_id is null and benefit_cents is 0."""
    assert entry["entry_type"] == TaxEntryType.TRUE_UP, entry
    assert entry["enrollment_id"] is None, entry
    assert entry["benefit_cents"] == 0, entry
    assert_ledger_row_identity(entry)


def assert_ledger_year_identity(entries: Sequence[Record], employee: Record):
    """The employee's two year-to-date aggregates equal the ledger's own sums."""
    benefit = sum(e["benefit_cents"] for e in entries)
    excluded = sum(e["excluded_cents"] for e in entries)
    imputed = sum(e["imputed_income_cents"] for e in entries)
    assert benefit == excluded + imputed, (
        f"year sums broken: {benefit} != {excluded} + {imputed}"
    )
    assert employee["taxable_excluded_cents_ytd"] == excluded, (
        f"taxable_excluded_cents_ytd {employee['taxable_excluded_cents_ytd']} "
        f"!= ledger excluded sum {excluded}"
    )
    assert employee["imputed_income_cents_ytd"] == imputed, (
        f"imputed_income_cents_ytd {employee['imputed_income_cents_ytd']} "
        f"!= ledger imputed sum {imputed}"
    )
    assert excluded <= TAX_EXCLUSION_LIMIT_CENTS, (
        f"excluded sum {excluded} exceeds the statutory limit"
    )


def assert_ledger_posted_at_ascending(entries: List[Record]):
    """Attribution order is pinned to posted_at ascending, created_at tie-break."""
    keys = [(e["posted_at"], e["created_at"]) for e in entries]
    assert keys == sorted(keys), f"ledger not in posted_at ascending order: {keys}"


# ─── Persistence risk (PRD §3.8) ──────────────────────────────────────────
def assert_persistence(enrollment: Record, expected_score: int):
    """Pin the score and re-derive the tier banding from it."""
    score = enrollment["persistence_risk_score"]
    assert score == expected_score, (
        f"persistence_risk_score {score} != expected {expected_score}"
    )
    assert RISK_SCORE_MIN <= score <= RISK_SCORE_MAX, score
    assert enrollment["persistence_tier"] == expected_persistence_tier(score), (
        f"tier {enrollment['persistence_tier']} does not band score {score}"
    )


def assert_tier_bands_score(enrollment: Record):
    """LOW below 30, MEDIUM at least 30 and below 60, HIGH once it reaches 60."""
    score = enrollment["persistence_risk_score"]
    tier = enrollment["persistence_tier"]
    if score < PERSISTENCE_TIER_MEDIUM_FLOOR:
        assert tier == "LOW", (score, tier)
    elif score < PERSISTENCE_TIER_HIGH_FLOOR:
        assert tier == "MEDIUM", (score, tier)
    else:
        assert tier == "HIGH", (score, tier)


# ─── Term-close batch report (PRD §3.9) ───────────────────────────────────
def assert_term_close_counts(
    report: Record,
    superseded_policy_count: int,
    closed_enrollment_count: int,
    obligation_assessed_count: int,
    true_up_entry_count: int,
    coaching_hold_employee_count: int,
):
    """The batch reports exactly five counters."""
    assert report["superseded_policy_count"] == superseded_policy_count, report
    assert report["closed_enrollment_count"] == closed_enrollment_count, report
    assert report["obligation_assessed_count"] == obligation_assessed_count, report
    assert report["true_up_entry_count"] == true_up_entry_count, report
    assert (
        report["coaching_hold_employee_count"] == coaching_hold_employee_count
    ), report
