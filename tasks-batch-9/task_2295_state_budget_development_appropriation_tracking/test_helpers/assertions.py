"""Entity assertions and conservation-invariant checkers for the budget ledger."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgencyRequestStatus,
    AllotmentStatus,
    AuthorityStatus,
    BudgetTransferStatus,
    CashPosture,
    CashStatus,
    CyclePhase,
    DecisionPackageStatus,
    ExpenditureStatus,
    MatchCommitmentStatus,
    MatchStatus,
    MoeComplianceStatus,
    RecommendationStatus,
    RevenueForecastStatus,
)

_FULL_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")
_THIN_AUDIT_FIELDS = ("id", "created_at")


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_full_audit_fields(data: dict):
    """Rows carrying the full audit set expose id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_thin_audit_fields(data: dict):
    """Immutable and append-only rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "this record type exposes no updated_at"
    assert "version" not in data, "this record type exposes no version"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------


def assert_agency(data: dict):
    assert_full_audit_fields(data)
    assert isinstance(data["agency_code"], str) and 1 <= len(data["agency_code"]) <= 12
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert data["agency_type"] in ["EXECUTIVE", "JUDICIAL", "LEGISLATIVE", "HIGHER_ED"]
    assert data["federal_compliance_flag"] in ["CLEAR", "AT_RISK", "DEFICIENT"]


def assert_budget_cycle(data: dict):
    assert_full_audit_fields(data)
    assert isinstance(data["fiscal_year"], int) and 2000 <= data["fiscal_year"] <= 2100
    assert isinstance(data["fiscal_year_start_date"], str)
    assert data["phase"] in _values(CyclePhase)
    assert isinstance(data["balance_certified"], bool)
    assert data["cash_posture"] in _values(CashPosture)
    for field in (
        "reserve_balance_cents",
        "adopted_general_fund_revenue_cents",
        "total_recommended_cents",
        "required_reserve_cents",
        "emergency_granted_cents",
        "total_released_cents",
        "total_expended_cents",
        "total_reverted_cents",
        "total_carryforward_cents",
        "projected_cumulative_cash_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["cash_utilization_pct"], (int, float))
    assert 0 <= data["constitutional_reserve_pct"] <= 0.5


def assert_revenue_forecast(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(RevenueForecastStatus)
    assert data["fund_type"] in ["GENERAL", "FEDERAL", "DEDICATED"]
    assert data["forecast_round"] in ["CONSENSUS_SPRING", "CONSENSUS_FALL", "REVISED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["effective_to"] > data["effective_from"]


def assert_agency_request(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(AgencyRequestStatus)
    assert isinstance(data["base_budget_cents"], int) and data["base_budget_cents"] > 0
    assert isinstance(data["total_request_cents"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_decision_package(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(DecisionPackageStatus)
    assert data["package_type"] in ["EXPANSION", "REDUCTION", "TECHNICAL", "FEDERAL_MATCH"]
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_performance_measure(data: dict):
    assert_thin_audit_fields(data)
    assert data["unit"] in ["COUNT", "PERCENT", "DAYS", "DOLLARS"]
    assert data["target_value"] > data["baseline_value"]
    assert data["baseline_value"] >= 0


def assert_executive_recommendation(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(RecommendationStatus)
    assert data["policy_priority"] in [
        "WORKFORCE",
        "INFRASTRUCTURE",
        "PUBLIC_SAFETY",
        "EDUCATION",
        "HEALTH",
    ]
    assert isinstance(data["recommended_base_cents"], int)
    assert isinstance(data["recommended_amount_cents"], int)
    assert isinstance(data["recommended_package_ids"], list)


def assert_reduction_scenario(data: dict):
    assert_thin_audit_fields(data)
    assert data["feasibility"] in ["FEASIBLE", "INFEASIBLE"]
    assert isinstance(data["selected_package_ids"], list)
    assert isinstance(data["target_reduction_cents"], int)
    assert isinstance(data["achieved_reduction_cents"], int)
    assert data["overshoot_cents"] >= 0


def assert_appropriation(data: dict):
    assert_full_audit_fields(data)
    assert data["authority_status"] in _values(AuthorityStatus)
    assert data["cash_status"] in _values(CashStatus)
    assert data["fund_type"] in ["GENERAL", "FEDERAL", "DEDICATED"]
    assert isinstance(data["is_emergency"], bool)
    assert isinstance(data["release_hold"], bool)
    for field in (
        "introduced_amount_cents",
        "committee_balance_cents",
        "enacted_amount_cents",
        "transfers_in_cents",
        "transfers_out_cents",
        "released_cents",
        "expended_cents",
        "reverted_cents",
        "carryforward_cents",
        "available_cash_cents",
        "available_authority_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_committee_action(data: dict):
    assert_thin_audit_fields(data)
    assert data["chamber"] in ["HOUSE", "SENATE", "CONFERENCE"]
    assert data["action_type"] in ["SET", "INCREASE", "DECREASE", "RESTORE", "STRIKE"]
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["running_balance_cents"], int)


def assert_allotment(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(AllotmentStatus)
    assert data["quarter"] in (1, 2, 3, 4)
    assert isinstance(data["requested_cents"], int) and data["requested_cents"] > 0
    assert isinstance(data["computed_release_cents"], int)
    assert isinstance(data["released_cents"], int)
    if data.get("binding_constraint") is not None:
        assert data["binding_constraint"] in [
            "REQUEST",
            "QUARTER_CAP",
            "UNRELEASED_AUTHORITY",
            "CASH_FLOW",
        ]


def assert_budget_transfer(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(BudgetTransferStatus)
    assert data["transfer_type"] in ["INTRA_AGENCY", "INTER_AGENCY"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source_appropriation_id"] != data["target_appropriation_id"]


def assert_expenditure(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(ExpenditureStatus)
    assert data["quarter"] in (1, 2, 3, 4)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_federal_grant(data: dict):
    assert_full_audit_fields(data)
    assert data["match_status"] in _values(MatchStatus)
    assert data["moe_compliance_status"] in _values(MoeComplianceStatus)
    assert isinstance(data["award_cents"], int) and data["award_cents"] > 0
    assert isinstance(data["moe_baseline_cents"], int) and data["moe_baseline_cents"] > 0
    assert isinstance(data["required_state_match_cents"], int)
    assert isinstance(data["committed_match_cents"], int)
    assert isinstance(data["moe_current_spend_cents"], int)
    assert 0 <= data["required_match_ratio"] <= 3


def assert_match_commitment(data: dict):
    assert_full_audit_fields(data)
    assert data["status"] in _values(MatchCommitmentStatus)
    assert (
        isinstance(data["committed_match_cents"], int) and data["committed_match_cents"] > 0
    )


def assert_balance_summary(data: dict):
    for field in (
        "appropriation_id",
        "authority_cents",
        "released_cents",
        "expended_cents",
        "available_cash_cents",
        "available_authority_cents",
        "basis_delta_cents",
    ):
        assert field in data, f"balance summary must report {field}"
    assert data["basis_delta_cents"] == (
        data["available_authority_cents"] - data["available_cash_cents"]
    ), "basis_delta_cents is available_authority_cents minus available_cash_cents"


# --------------------------------------------------------------------------
# Derived-figure and conservation checks
# --------------------------------------------------------------------------


def current_authority_cents(appropriation: dict) -> int:
    """enacted_amount_cents plus transfers_in_cents minus transfers_out_cents."""
    return (
        appropriation["enacted_amount_cents"]
        + appropriation["transfers_in_cents"]
        - appropriation["transfers_out_cents"]
    )


def assert_two_bases(appropriation: dict):
    """The cash basis is released minus expended; the authority basis is authority minus expended."""
    assert appropriation["available_cash_cents"] == (
        appropriation["released_cents"] - appropriation["expended_cents"]
    ), "available_cash_cents is released_cents minus expended_cents"
    assert appropriation["available_authority_cents"] == (
        current_authority_cents(appropriation) - appropriation["expended_cents"]
    ), "available_authority_cents is current authority minus expended_cents"
    assert (
        appropriation["available_authority_cents"] >= appropriation["available_cash_cents"]
    ), "the authority basis is always at least the cash basis"


def assert_released_authority_conservation(cycle: dict, appropriations: list, allotments: list):
    """Cycle total, appropriation sum and released-allotment sum agree."""
    appropriation_sum = sum(row["released_cents"] for row in appropriations)
    allotment_sum = sum(
        row["released_cents"] for row in allotments if row["status"] == "RELEASED"
    )
    assert cycle["total_released_cents"] == appropriation_sum, (
        f"cycle total_released_cents {cycle['total_released_cents']} must equal the "
        f"appropriation sum {appropriation_sum}"
    )
    assert appropriation_sum == allotment_sum, (
        f"appropriation released sum {appropriation_sum} must equal the RELEASED "
        f"allotment sum {allotment_sum}"
    )


def assert_transfer_authority_conservation(appropriations: list):
    """Summed across a cycle, transfers move authority without creating or destroying it."""
    adjusted = sum(current_authority_cents(row) for row in appropriations)
    plain = sum(row["enacted_amount_cents"] for row in appropriations)
    assert adjusted == plain, (
        f"authority with transfers {adjusted} must equal plain enacted sum {plain}"
    )


def assert_expenditure_ledger_conservation(appropriation: dict, expenditures: list):
    """expended_cents equals the sum over POSTED expenditures."""
    posted = sum(row["amount_cents"] for row in expenditures if row["status"] == "POSTED")
    assert appropriation["expended_cents"] == posted, (
        f"expended_cents {appropriation['expended_cents']} must equal the POSTED sum {posted}"
    )


def assert_reversion_carryforward_conservation(appropriation: dict):
    """carryforward plus reverted equals the row's unexpended authority."""
    unexpended = max(
        0, current_authority_cents(appropriation) - appropriation["expended_cents"]
    )
    total = appropriation["carryforward_cents"] + appropriation["reverted_cents"]
    assert total == unexpended, (
        f"carryforward {appropriation['carryforward_cents']} plus reverted "
        f"{appropriation['reverted_cents']} must equal unexpended authority {unexpended}"
    )


def assert_meta_envelope(body: dict):
    """Every response carries a fresh api_request_id and an ISO 8601 api_request_timestamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )
