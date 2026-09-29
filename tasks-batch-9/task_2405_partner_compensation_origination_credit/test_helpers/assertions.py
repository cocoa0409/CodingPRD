"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ─── Generic helpers ──────────────────────────────────


def assert_identity(data: dict) -> None:
    """Every persisted resource carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def assert_versioned(data: dict) -> None:
    """Almost every resource additionally carries updated_at and an integer version."""
    assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def approx4(value: float):
    """Comparator for a 4-decimal-place figure."""
    return pytest.approx(value, abs=1e-4)


def approx2(value: float):
    """Comparator for a 2-decimal-place figure."""
    return pytest.approx(value, abs=1e-2)


def approx6(value: float):
    """Comparator for a 6-decimal-place figure."""
    return pytest.approx(value, abs=1e-6)


def assert_decimal_places(value, places: int) -> None:
    assert value == pytest.approx(
        round(float(value), places), abs=10 ** -(places + 2)
    ), f"{value} carries more than {places} decimal places"


def assert_integer_cents(value) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be an integer number of cents, got {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────


def assert_cycle(data: dict) -> None:
    assert_versioned(data)
    assert isinstance(data["fiscal_year"], int)
    assert data["state"] in (
        "OPEN_INTAKE",
        "SELF_ASSESSMENT",
        "PEER_REVIEW",
        "DELIBERATION",
        "AWARDS_PUBLISHED",
        "TRUE_UP_OPEN",
        "CLOSED",
    )
    for field in (
        "distributable_pool_cents",
        "lockstep_unit_cents",
        "lockstep_reserved_cents",
        "discretionary_pool_cents",
        "formula_pool_cents",
        "undistributed_cash_cents",
    ):
        assert_integer_cents(data[field])
    assert_decimal_places(data["discretionary_pool_pct"], 4)
    assert_decimal_places(data["draw_pct"], 4)
    assert_decimal_places(data["haircut_applied_pct"], 4)
    assert_decimal_places(data["total_formula_score"], 4)
    assert_decimal_places(data["total_committee_points"], 2)
    assert isinstance(data["unsettled_award_count"], int)
    assert isinstance(data["reopen_count"], int)
    assert isinstance(data["confidentiality_locked"], bool)


def assert_partner(data: dict) -> None:
    assert_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["practice_group"] in ("LITIGATION", "CORPORATE", "TAX", "IP", "REGULATORY")
    assert data["compensation_model"] in ("LOCKSTEP", "FORMULA", "DISCRETIONARY")
    assert isinstance(data["lockstep_step"], int) and 0 <= data["lockstep_step"] <= 12
    assert isinstance(data["admission_year"], int)
    assert isinstance(data["is_committee_member"], bool)
    assert isinstance(data["is_credit_arbiter"], bool)
    assert isinstance(data["evaluation_required"], bool)
    assert data["status"] in ("ACTIVE", "NOTICE_GIVEN", "DEPARTED")
    for field in (
        "opening_capital_cents",
        "target_capital_cents",
        "capital_account_balance_cents",
        "ytd_draw_paid_cents",
        "credited_collection_provisional_cents",
        "credited_collection_final_cents",
    ):
        assert_integer_cents(data[field])
    assert_decimal_places(data["verified_billable_hours"], 2)
    assert_decimal_places(data["non_billable_points"], 2)
    assert_decimal_places(data["normalized_credit_index_provisional"], 6)
    assert_decimal_places(data["normalized_credit_index_final"], 6)
    assert_decimal_places(data["blended_realization_pct"], 4)
    assert_decimal_places(data["weighted_profitability_points"], 4)
    assert_decimal_places(data["formula_score_provisional"], 4)
    assert_decimal_places(data["formula_score_final"], 4)
    assert_decimal_places(data["committee_points"], 2)
    assert isinstance(data["responsible_matter_count"], int)


def assert_matter(data: dict) -> None:
    assert_versioned(data)
    assert isinstance(data["client_key"], str) and data["client_key"]
    assert data["matter_type"] in ("NEW_CLIENT", "EXPANDED_MATTER", "CROSS_SELL", "EXISTING")
    assert data["state"] in ("OPEN", "CLOSED", "WRITTEN_OFF")
    assert is_valid_uuid(data["billing_attorney_id"])
    assert is_valid_uuid(data["responsible_attorney_id"])
    for field in ("billed_cents", "collected_cents", "direct_cost_cents"):
        assert_integer_cents(data[field])
        assert data[field] >= 0, f"{field} may never fall below zero"
    assert_decimal_places(data["realization_pct"], 4)
    assert_decimal_places(data["profitability_index_contribution"], 4)
    assert_decimal_places(data["profitability_index_fully_loaded"], 4)
    assert_decimal_places(data["verified_billable_hours"], 2)
    assert_decimal_places(data["origination_pct_assigned"], 2)
    assert isinstance(data["is_first_matter_for_client"], bool)


def assert_credit_allocation(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["partner_id"])
    assert data["credit_role"] in ("ORIGINATING", "BILLING", "RESPONSIBLE", "WORKING")
    assert data["source"] in (
        "CLAIM_ALLOCATED",
        "SHARING_CONVENTION",
        "DEFAULT_BILLING",
        "WORKING_DERIVED",
        "TRANSITION",
    )
    assert data["state"] in ("ACTIVE", "TRANSFERRED", "SUPERSEDED")
    assert_decimal_places(data["credit_pct"], 2)
    assert_integer_cents(data["credited_collection_provisional_cents"])
    assert_integer_cents(data["credited_collection_final_cents"])


def assert_contribution_record(data: dict) -> None:
    assert_versioned(data)
    assert data["kind"] in ("BILLABLE", "NON_BILLABLE")
    assert data["category"] in (
        "CLIENT_WORK",
        "FIRM_MANAGEMENT",
        "RECRUITING",
        "PRO_BONO",
        "TRAINING",
    )
    assert_decimal_places(data["hours"], 2)
    assert_integer_cents(data["standard_rate_cents"])
    assert_integer_cents(data["standard_value_cents"])
    assert isinstance(data["verified"], bool)


def assert_credit_claim(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["claimant_partner_id"])
    assert data["claim_basis"] in ("NEW_CLIENT", "EXPANDED_MATTER", "CROSS_SELL")
    assert data["state"] in ("DRAFT", "SUBMITTED", "DISPUTED", "ALLOCATED", "REJECTED")
    assert_decimal_places(data["requested_pct"], 2)
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["remand_count"], int)


def assert_self_assessment(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["partner_id"])
    assert data["state"] in ("DRAFT", "SUBMITTED", "ACCEPTED")
    assert_decimal_places(data["claimed_origination_pct_total"], 2)
    assert_decimal_places(data["claimed_non_billable_hours"], 2)
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["scored_review_count"], int)
    assert_decimal_places(data["mean_peer_score"], 4)


def assert_peer_review(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["self_assessment_id"])
    assert is_valid_uuid(data["reviewer_partner_id"])
    assert data["state"] in ("ASSIGNED", "SCORED", "RECUSED")
    if data.get("composite_score") is not None:
        assert_decimal_places(data["composite_score"], 4)


def assert_ballot(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["subject_partner_id"])
    assert is_valid_uuid(data["committee_member_id"])
    assert data["state"] in ("PENDING", "CAST", "ABSTAINED", "RECUSED")
    if data.get("points_proposed") is not None:
        assert_decimal_places(data["points_proposed"], 2)


def assert_award(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["partner_id"])
    assert data["award_state"] in ("PROPOSED", "PUBLISHED", "FINALIZED")
    assert data["payment_state"] in ("PENDING", "DRAWING", "TRUED_UP", "SETTLED")
    assert data["basis_model"] in ("LOCKSTEP", "FORMULA", "DISCRETIONARY")
    for field in (
        "target_award_cents",
        "final_award_cents",
        "draw_schedule_monthly_cents",
        "draw_paid_cents",
        "true_up_delta_cents",
        "capital_call_cents",
        "capital_shortfall_cents",
    ):
        assert_integer_cents(data[field])
    assert isinstance(data["reconsideration_count"], int)


def assert_draw_payment(data: dict) -> None:
    """A draw-payment row is append-only: id and created_at, no updated_at and
    no version at all."""
    assert_identity(data)
    assert "updated_at" not in data, "a cash ledger row has no updated_at field"
    assert "version" not in data, "a cash ledger row has no version field"
    assert is_valid_uuid(data["award_id"])
    assert data["kind"] in (
        "SCHEDULED_DRAW",
        "DRAW_REVERSAL",
        "TRUE_UP",
        "CLAWBACK",
        "CAPITAL_WITHHOLDING",
    )
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int)
    assert_integer_cents(data["amount_cents"])
    assert isinstance(data["reversed"], bool)


def assert_credit_transition(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data["departing_partner_id"])
    assert is_valid_uuid(data["matter_id"])
    assert data["state"] in ("PROPOSED", "EFFECTIVE", "VOIDED")
    assert_decimal_places(data["transferred_pct"], 2)
    assert_decimal_places(data["prior_credit_pct"], 2)


# ─── Domain invariant checkers ────────────────────────


def assert_origination_capacity(matter: dict) -> None:
    """The total originating percentage in force never exceeds the 100.00 ceiling."""
    assert 0.00 <= matter["origination_pct_assigned"] <= 100.00, (
        f"origination_pct_assigned out of range: {matter['origination_pct_assigned']}"
    )


def assert_ledger_signed_sum(rows: list, expected_sum: int) -> None:
    """The cash ledger is auditable by summing amount_cents over its rows."""
    actual = sum(row["amount_cents"] for row in rows)
    assert actual == expected_sum, (
        f"Expected ledger signed sum {expected_sum}, got {actual} over {len(rows)} rows"
    )


def assert_composite_score(review: dict, technical: int, collaboration: int, client_service: int) -> None:
    """composite_score is the technical score weighted 0.50 plus collaboration
    weighted 0.25 plus client service weighted 0.25, to 4 decimal places."""
    expected = round(technical * 0.50 + collaboration * 0.25 + client_service * 0.25, 4)
    assert review["composite_score"] == approx4(expected), (
        f"Expected composite_score {expected}, got {review['composite_score']}"
    )


def find_allocation(rows: list, credit_role: str, partner_id: str = None, state: str = None):
    """Locate one credit allocation in a listing by role, partner and state."""
    matches = [
        row
        for row in rows
        if row["credit_role"] == credit_role
        and (partner_id is None or row["partner_id"] == partner_id)
        and (state is None or row["state"] == state)
    ]
    assert len(matches) == 1, (
        f"Expected exactly one {credit_role} allocation "
        f"(partner={partner_id}, state={state}), found {len(matches)}"
    )
    return matches[0]
