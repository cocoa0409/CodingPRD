"""Domain assertions: resource shape, money/ratio precision and the two
conserved quantities of PRD §2.7.
"""

from typing import Iterable, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DRIFT_TOLERANCE_CENTS, DRIFT_TOLERANCE_SEATS, RATIO_ABS_TOLERANCE
from .types import BILLING_SUMMARY_FIELDS

# ── Primitive shape helpers ─────────────────────────────────────────────────

VERSIONED_SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_ratio(actual, expected) -> None:
    """A ratio is carried to four decimal places (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=RATIO_ABS_TOLERANCE), (
        f"expected ratio {expected}, got {actual}"
    )


def assert_money(actual, expected) -> None:
    """Money is whole integer cents (PRD §2.6) and therefore compares exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {expected} cents, got {actual} cents"


def assert_system_fields(resource: dict) -> None:
    """Every resource but LedgerEntry carries id, created_at, updated_at, version."""
    assert is_valid_uuid(resource["id"]), f"id must be a UUID, got {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int) and resource["version"] >= 1


def assert_has_fields(resource: dict, fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in resource]
    assert not missing, f"response is missing fields {missing}"


def assert_lacks_fields(resource: dict, fields: Iterable[str]) -> None:
    present = [field for field in fields if field in resource]
    assert not present, f"response must not carry fields {present}"


# ── Resource shape assertions ───────────────────────────────────────────────

def assert_term_shape(term: dict) -> None:
    assert_system_fields(term)
    assert_has_fields(term, [
        "code", "name", "term_start_date", "term_end_date", "total_term_days",
        "instructional_days", "census_date", "add_drop_deadline",
        "late_registration_cutoff_date", "adoption_deadline_date",
        "disclosure_deadline_date", "opt_out_window_days", "status",
        "ia_section_count", "closed_at",
    ])
    assert isinstance(term["total_term_days"], int)
    assert isinstance(term["ia_section_count"], int)


def assert_student_shape(student: dict) -> None:
    assert_system_fields(student)
    assert_has_fields(student, [
        "external_id", "full_name", "email", "program_code", "status",
        "bursar_balance_cents",
    ])
    assert isinstance(student["bursar_balance_cents"], int)


def assert_agreement_shape(agreement: dict) -> None:
    assert_system_fields(agreement)
    assert_has_fields(agreement, [
        "publisher_name", "agreement_code", "effective_from", "effective_to",
        "admin_fee_pct", "bookstore_margin_pct", "price_floor_cents",
        "max_list_price_pct", "rebate_threshold_cents", "rebate_pct", "status",
        "reconciliation_status", "settled_amount_cents", "suspend_reason_note",
    ])


def assert_title_shape(title: dict) -> None:
    assert_system_fields(title)
    assert_has_fields(title, [
        "agreement_id", "isbn", "title", "list_price_cents", "format", "status",
    ])


def assert_pricing_tier_shape(tier: dict) -> None:
    assert_system_fields(tier)
    assert_has_fields(tier, [
        "title_id", "min_enrollment", "max_enrollment", "per_student_price_cents",
    ])


def assert_section_shape(section: dict) -> None:
    assert_system_fields(section)
    assert_has_fields(section, [
        "term_id", "subject_code", "catalog_number", "section_number",
        "instructor_user_id", "max_concurrent_titles", "inclusive_access_flag",
        "ia_status", "enrolled_count", "provisioned_access_count",
        "revoked_access_count", "opted_out_count", "participation_rate",
        "billing_basis_enrollment_count", "first_posted_at",
    ])


def assert_adoption_shape(adoption: dict) -> None:
    assert_system_fields(adoption)
    assert_has_fields(adoption, [
        "section_id", "title_id", "supersedes_adoption_id", "status",
        "access_start_date", "access_end_date", "submitted_by_user_id",
        "approved_by_user_id", "submitted_at", "approved_at",
        "locked_list_price_cents", "change_note", "revision_count",
        "requires_rebill",
    ])


def assert_enrollment_shape(enrollment: dict) -> None:
    assert_system_fields(enrollment)
    assert_has_fields(enrollment, [
        "section_id", "student_id", "enrolled_on", "registration_type", "status",
        "dropped_on",
    ])


def assert_charge_shape(charge: dict) -> None:
    assert_system_fields(charge)
    assert_has_fields(charge, [
        "enrollment_id", "adoption_id", "student_id", "gross_price_cents",
        "proration_pct", "billed_amount_cents", "refunded_amount_cents",
        "net_billed_cents", "publisher_share_cents", "billing_status",
        "access_status", "posted_at", "opt_out_deadline_at", "access_start_at",
        "access_revoked_at", "access_restored_at", "rebill_count",
    ])
    for field in ("gross_price_cents", "billed_amount_cents",
                  "refunded_amount_cents", "net_billed_cents",
                  "publisher_share_cents"):
        assert isinstance(charge[field], int), f"{field} must be integer cents"


def assert_ledger_entry_shape(entry: dict) -> None:
    """A LedgerEntry is append-only: it carries id and created_at and nothing else
    from the system-field set — no updated_at and no version (PRD §2.5).
    """
    assert is_valid_uuid(entry["id"]), f"id must be a UUID, got {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"])
    assert_lacks_fields(entry, ["updated_at", "version"])
    assert_has_fields(entry, [
        "charge_id", "student_id", "entry_type", "reason_code", "amount_cents",
        "posted_at", "source_event",
    ])
    assert isinstance(entry["amount_cents"], int)


def assert_opt_out_request_shape(request: dict) -> None:
    assert_system_fields(request)
    assert_has_fields(request, [
        "charge_id", "status", "reason_code", "submitted_at", "decided_at",
        "decided_by_user_id", "denial_note", "refund_amount_cents",
        "rescinded_at", "recharge_amount_cents", "cycle_count",
    ])


def assert_reconciliation_run_shape(run: dict) -> None:
    assert_system_fields(run)
    assert_has_fields(run, [
        "agreement_id", "term_id", "supersedes_run_id", "method", "status",
        "billable_count", "opted_out_count", "gross_invoice_cents", "rebate_cents",
        "settlement_amount_cents", "publisher_reported_count",
        "publisher_reported_amount_cents", "count_variance", "variance_cents",
        "dispute_note", "computed_by_user_id", "settled_by_user_id", "settled_at",
    ])


def assert_disclosure_report_shape(report: dict) -> None:
    assert_system_fields(report)
    assert_has_fields(report, [
        "term_id", "reporting_state_code", "status", "ia_section_count",
        "charge_count", "enrolled_student_count", "opted_out_student_count",
        "total_list_price_cents", "total_net_billed_cents",
        "average_net_cost_cents", "savings_pct", "compliance_status",
        "certified_by_user_id", "certified_at", "published_at",
        "amendment_note", "amendment_count",
    ])


def assert_billing_summary_shape(summary: dict) -> None:
    """The billing summary is a purely computed read of fifteen named fields."""
    assert_has_fields(summary, BILLING_SUMMARY_FIELDS)


# ── Conserved quantities (PRD §2.7) ─────────────────────────────────────────

def assert_charge_ledger_conserved(charge: dict, entries: Sequence[dict]) -> None:
    """A charge's net_billed_cents equals the sum of its ledger movements."""
    ledger_sum = sum(entry["amount_cents"] for entry in entries)
    assert abs(ledger_sum - charge["net_billed_cents"]) <= DRIFT_TOLERANCE_CENTS, (
        f"ledger sums to {ledger_sum} but net_billed_cents is "
        f"{charge['net_billed_cents']}"
    )


def assert_student_balance_matches_ledger(student: dict,
                                          entries: Sequence[dict]) -> None:
    """A student's bursar balance equals the sum of that student's ledger rows."""
    ledger_sum = sum(entry["amount_cents"] for entry in entries)
    assert abs(ledger_sum - student["bursar_balance_cents"]) <= DRIFT_TOLERANCE_CENTS, (
        f"ledger sums to {ledger_sum} but bursar_balance_cents is "
        f"{student['bursar_balance_cents']}"
    )


def assert_entitlement_seats_conserved(section: dict,
                                       expected_basis: Optional[int] = None) -> None:
    """Provisioned plus revoked access seats equal the frozen billing basis."""
    basis = section["billing_basis_enrollment_count"] if expected_basis is None \
        else expected_basis
    assert basis is not None, "no frozen billing basis to conserve seats against"
    seats = section["provisioned_access_count"] + section["revoked_access_count"]
    assert abs(seats - basis) <= DRIFT_TOLERANCE_SEATS, (
        f"provisioned {section['provisioned_access_count']} + revoked "
        f"{section['revoked_access_count']} = {seats}, expected basis {basis}"
    )


def assert_ledger_append_only(before: Sequence[dict], after: Sequence[dict]) -> None:
    """Existing ledger rows are never rewritten; new rows only append."""
    assert len(after) >= len(before)
    for index, row in enumerate(before):
        assert after[index] == row, (
            f"ledger row {index} was rewritten: {row} became {after[index]}"
        )
