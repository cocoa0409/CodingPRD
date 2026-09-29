"""Domain assertions: per-entity shape checks plus builders risk invariants."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import OCCURRENCE_DEDUCTIBLE_CENTS
from .types import ALLOCATION_ORDER

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(entity: dict) -> None:
    """Every entity except PremiumTransaction carries the full common block."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field {field}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1, entity["version"]


def assert_fields_present(entity: dict, fields) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


PROJECT_FIELDS = (
    "name", "site_address", "construction_type", "project_kind",
    "hard_cost_value_cents", "existing_structure_value_cents", "cat_zone",
    "planned_start_date", "projected_completion_date",
    "actual_substantial_completion_date", "status", "engineering_grade",
    "loss_control_report_ref", "screened_by_user_id", "submission_risk_score",
    "audit_risk_score", "in_force_policy_count",
)

POLICY_FIELDS = (
    "project_id", "term_start_date", "term_end_date", "original_term_days",
    "cumulative_extension_days", "adjusted_completion_date",
    "includes_existing_structure", "deductible_tier",
    "occurrence_deductible_cents", "limit_cents", "daily_delay_rate_cents",
    "insured_tiv_cents", "quoted_premium_cents", "referral_load_pct",
    "written_premium_cents", "eroded_total_cents", "return_premium_cents",
    "status", "quoted_by_user_id", "bound_at", "cancel_reason",
    "cancel_effective_date",
)

COVERAGE_PART_FIELDS = (
    "policy_id", "part_type", "sublimit_cents", "condition_code",
    "eroded_cents", "available_cents", "status",
)

INTEREST_FIELDS = (
    "policy_id", "party_name", "party_role", "insurable_interest_pct",
    "loss_payee_priority", "acknowledgment_status", "acknowledged_at",
)

ENDORSEMENT_FIELDS = (
    "policy_id", "requested_extension_days", "slip_reason",
    "revised_completion_date", "status", "requested_by_user_id",
    "decided_by_user_id", "info_request_note", "resubmission_count",
    "slip_factor", "additional_premium_cents",
)

CLAIM_FIELDS = (
    "policy_id", "peril", "loss_date", "description", "reported_at",
    "adjustment_status", "payment_status", "adjustment_basis",
    "continuing_pm_weeks", "allocation_lines", "indemnity_cents",
    "uncovered_cents", "delay_days_indemnified", "paid_cents",
    "outstanding_reserve_cents", "total_incurred_cents",
    "adjusted_by_user_id", "reopen_count",
)

LOSS_PAYMENT_FIELDS = (
    "claim_id", "payee_interest_id", "part_type", "amount_cents", "status",
    "created_by_user_id", "voided_by_user_id",
)

PREMIUM_TRANSACTION_FIELDS = (
    "id", "created_at", "policy_id", "sequence_no", "txn_type", "amount_cents",
    "effective_date", "reverses_sequence_no", "memo",
)

NOTICE_FIELDS = (
    "project_id", "system_type", "window_start", "window_end", "hot_work",
    "water_charged", "mitigation_plan_ref", "status", "decided_by_user_id",
    "rejection_reason",
)

FACILITY_FIELDS = (
    "name", "site_code", "distance_from_site_miles",
    "aggregate_capacity_cents", "protection_class", "committed_value_cents",
    "status",
)

ASSIGNMENT_FIELDS = (
    "policy_id", "facility_id", "stored_value_cents", "window_start",
    "window_end", "status", "released_at", "release_reason",
)


def assert_project(project: dict, status: str = None) -> None:
    assert_common_fields(project)
    assert_fields_present(project, PROJECT_FIELDS)
    if status is not None:
        assert project["status"] == status, project["status"]


def assert_policy(policy: dict, status: str = None) -> None:
    assert_common_fields(policy)
    assert_fields_present(policy, POLICY_FIELDS)
    if status is not None:
        assert policy["status"] == status, policy["status"]


def assert_coverage_part(part: dict, status: str = None) -> None:
    assert_common_fields(part)
    assert_fields_present(part, COVERAGE_PART_FIELDS)
    if status is not None:
        assert part["status"] == status, part["status"]
    assert part["available_cents"] == part["sublimit_cents"] - part["eroded_cents"], part


def assert_named_insured_interest(interest: dict, acknowledgment_status: str = None) -> None:
    assert_common_fields(interest)
    assert_fields_present(interest, INTEREST_FIELDS)
    if acknowledgment_status is not None:
        assert interest["acknowledgment_status"] == acknowledgment_status, interest


def assert_extension_endorsement(endorsement: dict, status: str = None) -> None:
    assert_common_fields(endorsement)
    assert_fields_present(endorsement, ENDORSEMENT_FIELDS)
    if status is not None:
        assert endorsement["status"] == status, endorsement["status"]


def assert_claim(claim: dict, adjustment_status: str = None,
                 payment_status: str = None) -> None:
    assert_common_fields(claim)
    assert_fields_present(claim, CLAIM_FIELDS)
    if adjustment_status is not None:
        assert claim["adjustment_status"] == adjustment_status, claim["adjustment_status"]
    if payment_status is not None:
        assert claim["payment_status"] == payment_status, claim["payment_status"]
    assert isinstance(claim["allocation_lines"], list), claim["allocation_lines"]


def assert_loss_payment(payment: dict, status: str = None) -> None:
    assert_common_fields(payment)
    assert_fields_present(payment, LOSS_PAYMENT_FIELDS)
    if status is not None:
        assert payment["status"] == status, payment["status"]


def assert_premium_transaction(txn: dict, txn_type: str = None) -> None:
    """PremiumTransaction is the one resource without updated_at / version."""
    assert_fields_present(txn, PREMIUM_TRANSACTION_FIELDS)
    assert is_valid_uuid(txn["id"]), txn["id"]
    assert is_iso8601_timestamp(txn["created_at"]), txn["created_at"]
    assert "updated_at" not in txn, "PremiumTransaction must not expose updated_at"
    assert "version" not in txn, "PremiumTransaction must not expose version"
    if txn_type is not None:
        assert txn["txn_type"] == txn_type, txn["txn_type"]


def assert_testing_notice(notice: dict, status: str = None) -> None:
    assert_common_fields(notice)
    assert_fields_present(notice, NOTICE_FIELDS)
    if status is not None:
        assert notice["status"] == status, notice["status"]


def assert_facility(facility: dict, status: str = None) -> None:
    assert_common_fields(facility)
    assert_fields_present(facility, FACILITY_FIELDS)
    if status is not None:
        assert facility["status"] == status, facility["status"]


def assert_storage_assignment(assignment: dict, status: str = None) -> None:
    assert_common_fields(assignment)
    assert_fields_present(assignment, ASSIGNMENT_FIELDS)
    if status is not None:
        assert assignment["status"] == status, assignment["status"]


def assert_deductible_for_tier(policy: dict) -> None:
    expected = OCCURRENCE_DEDUCTIBLE_CENTS[policy["deductible_tier"]]
    assert policy["occurrence_deductible_cents"] == expected, policy


def assert_claim_incurred_identity(claim: dict) -> None:
    """paid + outstanding reserve must reconcile against indemnity."""
    assert claim["total_incurred_cents"] == claim["indemnity_cents"], claim
    assert (claim["paid_cents"] + claim["outstanding_reserve_cents"]
            == claim["indemnity_cents"]), claim


def assert_allocation_line_order(claim: dict) -> None:
    """Allocation lines are emitted in the pinned waterfall order."""
    seen = [line["part_type"] for line in claim["allocation_lines"]]
    ranked = [ALLOCATION_ORDER.index(part_type) for part_type in seen]
    assert ranked == sorted(ranked), seen


def allocation_line(claim: dict, part_type: str) -> dict:
    for line in claim["allocation_lines"]:
        if line["part_type"] == part_type:
            return line
    raise AssertionError(
        f"no allocation line for {part_type}: {claim['allocation_lines']}")


def assert_no_allocation_line(claim: dict, part_type: str) -> None:
    present = [line["part_type"] for line in claim["allocation_lines"]]
    assert part_type not in present, present


def assert_ledger_balances(transactions, written_premium_cents: int) -> None:
    """The append-only ledger always sums to written_premium_cents."""
    total = sum(txn["amount_cents"] for txn in transactions)
    assert total == written_premium_cents, (
        f"ledger sum {total} != written_premium_cents {written_premium_cents}")


def assert_ledger_sequence(transactions) -> None:
    """sequence_no is dense and 1-based in created_at order."""
    numbers = [txn["sequence_no"] for txn in transactions]
    assert numbers == list(range(1, len(numbers) + 1)), numbers


def assert_erosion_reconciles(policy: dict, parts) -> None:
    total = sum(part["eroded_cents"] for part in parts)
    assert policy["eroded_total_cents"] == total, (
        f"policy eroded_total {policy['eroded_total_cents']} != parts sum {total}")


def assert_pagination_meta(meta: dict, total_count: int = None, limit: int = None,
                           offset: int = None, has_more: bool = None) -> None:
    """List envelopes carry limit, offset, total_count and has_more in meta."""
    for key in ("total_count", "limit", "offset", "has_more"):
        assert key in meta, f"missing pagination key {key}: {meta}"
    if total_count is not None:
        assert meta["total_count"] == total_count, meta
    if limit is not None:
        assert meta["limit"] == limit, meta
    if offset is not None:
        assert meta["offset"] == offset, meta
    if has_more is not None:
        assert meta["has_more"] is has_more, meta


def assert_created_at_ascending(items) -> None:
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), stamps
