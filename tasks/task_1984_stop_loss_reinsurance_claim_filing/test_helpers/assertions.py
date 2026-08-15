"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(str(data.get("id", ""))), \
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_name}.version must be a positive int, got {data.get('version')!r}"


def assert_plan(data: dict):
    _assert_common_fields(data, "Plan")
    assert isinstance(data.get("plan_name"), str) and len(data["plan_name"]) > 0
    assert isinstance(data.get("sponsor_tax_id"), str)
    assert data.get("status") in ("ACTIVE", "TERMINATED")


def assert_contract(data: dict):
    _assert_common_fields(data, "StopLossContract")
    assert isinstance(data.get("plan_id"), str)
    assert is_iso8601_timestamp(str(data.get("policy_year_start", "")))
    assert is_iso8601_timestamp(str(data.get("policy_year_end", "")))
    assert data.get("contract_basis") in ("POLICY_YEAR", "PAID")
    assert isinstance(data.get("specific_deductible_cents"), int)
    assert isinstance(data.get("aggregate_deductible_cents"), int)
    assert data.get("aggregating_specific_deductible_cents") is None or \
        isinstance(data["aggregating_specific_deductible_cents"], int)
    assert isinstance(data.get("filing_deadline_days"), int)
    assert isinstance(data.get("run_in_days"), int)
    assert isinstance(data.get("run_out_days"), int)
    assert data.get("status") in ("DRAFT", "IN_FORCE", "EXPIRED", "RENEWED")


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("member_external_id"), str)
    assert isinstance(data.get("date_of_birth"), str)
    assert is_iso8601_timestamp(str(data.get("coverage_start", "")))
    assert data.get("coverage_end") is None or \
        isinstance(data["coverage_end"], str)
    assert data.get("notice_status") in ("NONE", "NOTICE_PENDING", "NOTICE_FILED")
    assert data.get("status") in ("ACTIVE", "TERMINATED")


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert is_iso8601_timestamp(str(data.get("service_date", "")))
    assert data.get("paid_date") is None or isinstance(data["paid_date"], str)
    assert isinstance(data.get("billed_amount_cents"), int)
    assert data.get("claim_type") in ("MEDICAL", "RX")
    assert data.get("status") in ("SUBMITTED", "ADJUDICATED", "PAID", "REVERSED")


def assert_accumulation(data: dict):
    _assert_common_fields(data, "ClaimAccumulation")
    assert isinstance(data.get("contract_id"), str)
    assert data.get("member_id") is None or isinstance(data["member_id"], str)
    assert data.get("scope") in ("SPECIFIC", "AGGREGATE")
    assert isinstance(data.get("accumulated_cents"), int)
    assert isinstance(data.get("excess_cents"), int)
    assert isinstance(data.get("applicable_deductible_cents"), int)
    assert isinstance(data.get("notice_triggered"), bool)


def assert_filing(data: dict):
    _assert_common_fields(data, "StopLossFiling")
    assert isinstance(data.get("contract_id"), str)
    assert data.get("filing_scope") in ("SPECIFIC", "AGGREGATE")
    assert data.get("member_id") is None or isinstance(data["member_id"], str)
    assert isinstance(data.get("requested_amount_cents"), int)
    assert data.get("approved_amount_cents") is None or \
        isinstance(data["approved_amount_cents"], int)
    assert data.get("submitted_at") is None or \
        isinstance(data["submitted_at"], str)
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "DISPUTED", "APPROVED",
        "DENIED", "PAID")


def assert_filing_line_item(data: dict):
    """Line items carry only id + created_at: no updated_at, no version."""
    assert is_valid_uuid(str(data.get("id", ""))), \
        f"FilingLineItem.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        "FilingLineItem.created_at must be ISO 8601"
    assert "updated_at" not in data, "FilingLineItem must not expose updated_at"
    assert "version" not in data, "FilingLineItem must not expose version"
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("eligible_excess_cents"), int)
    assert isinstance(data.get("disputed"), bool)


def assert_reimbursement(data: dict):
    _assert_common_fields(data, "Reimbursement")
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("received_amount_cents"), int)
    assert is_iso8601_timestamp(str(data.get("received_at", "")))
    assert data.get("status") in ("RECEIVED", "POSTED")


def assert_forecast(data: dict):
    _assert_common_fields(data, "HighCostClaimantForecast")
    assert isinstance(data.get("plan_id"), str)
    assert data.get("forecast_basis") in ("PURE_EXPERIENCE", "CREDIBILITY_WEIGHTED")
    assert isinstance(data.get("projected_excess_cents"), int)
    assert isinstance(data.get("projected_member_count"), int)
    assert is_iso8601_timestamp(str(data.get("computed_at", "")))


def assert_audit(data: dict):
    _assert_common_fields(data, "AuditReview")
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("reason"), str)
    assert data.get("adjustment_cents") is None or \
        isinstance(data["adjustment_cents"], int)
    assert data.get("status") in ("OPENED", "FINDINGS_ISSUED", "RESOLVED")


def assert_lasered_term(data: dict):
    _assert_common_fields(data, "LaseredMemberTerm")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("lasered_specific_deductible_cents"), int)
    assert is_iso8601_timestamp(str(data.get("effective_from", "")))
    assert is_iso8601_timestamp(str(data.get("effective_to", "")))
    assert data.get("status") in ("ACTIVE", "RESCINDED")


def assert_accumulation_invariants(row: dict):
    """excess_cents == max(0, accumulated_cents - applicable_deductible_cents)."""
    expected = max(
        0, row["accumulated_cents"] - row["applicable_deductible_cents"])
    assert row["excess_cents"] == expected, (
        f"excess_cents {row['excess_cents']} != max(0, "
        f"{row['accumulated_cents']} - {row['applicable_deductible_cents']})")
