"""Entity shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import types as t


def _assert_common_fields(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def _assert_enum(data: dict, field: str, enum_cls, label: str) -> None:
    allowed = [e.value for e in enum_cls]
    assert data.get(field) in allowed, (
        f"{label}.{field} must be one of {allowed}, got {data.get(field)!r}"
    )


def assert_institution(data: dict) -> None:
    _assert_common_fields(data, "Institution")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and len(data["ein"]) == 9
    _assert_enum(data, "entity_type", t.InstitutionEntityType, "Institution")
    assert len(data["primary_mission_statement"]) >= 40
    assert isinstance(data["asset_size_cents"], int) and data["asset_size_cents"] >= 0
    assert data["loss_reserve_balance_cents"] >= 0
    _assert_enum(data, "reserve_method", t.ReserveMethod, "Institution")
    _assert_enum(data, "certification_state", t.CertificationState, "Institution")
    _assert_enum(data, "compliance_posture", t.CompliancePosture, "Institution")
    assert isinstance(data["accountability_satisfied"], bool)
    assert data["governing_seats_active"] >= 0
    assert data["advisory_seats_active"] >= 0
    assert data["portfolio_principal_outstanding_cents"] >= 0
    assert data["portfolio_principal_disbursed_cents"] >= 0


def assert_target_market(data: dict) -> None:
    _assert_common_fields(data, "TargetMarket")
    assert is_valid_uuid(data["institution_id"])
    _assert_enum(data, "market_type", t.MarketType, "TargetMarket")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["census_tract_codes"], list)
    _assert_enum(data, "state", t.TargetMarketState, "TargetMarket")


def assert_board_seat(data: dict) -> None:
    _assert_common_fields(data, "BoardSeat")
    assert is_valid_uuid(data["institution_id"])
    _assert_enum(data, "structure", t.BoardStructure, "BoardSeat")
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["represents_target_market"], bool)
    _assert_enum(data, "status", t.BoardSeatStatus, "BoardSeat")


def assert_certification_application(data: dict) -> None:
    _assert_common_fields(data, "CertificationApplication")
    assert is_valid_uuid(data["institution_id"])
    _assert_enum(data, "state", t.ApplicationState, "CertificationApplication")
    assert isinstance(data["revision_round"], int)
    assert 0 <= data["revision_round"] <= 3, (
        "revision_round reaches 3 only on the pass that denies the docket"
    )
    for field in (
        "test_primary_mission_state",
        "test_financing_entity_state",
        "test_target_market_state",
        "test_development_services_state",
        "test_accountability_state",
        "test_non_government_state",
    ):
        _assert_enum(data, field, t.TestVerdictState, "CertificationApplication")


def assert_borrower(data: dict) -> None:
    _assert_common_fields(data, "Borrower")
    assert is_valid_uuid(data["institution_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["household_income_cents"] >= 0
    assert data["area_median_income_cents"] > 0
    if data.get("credit_score") is not None:
        assert 300 <= data["credit_score"] <= 850
    _assert_enum(data, "geocode_state", t.GeocodeState, "Borrower")
    assert data["geocode_attempts"] >= 0
    assert isinstance(data["in_target_market"], bool)
    if data.get("matched_target_market_type") is not None:
        _assert_enum(data, "matched_target_market_type", t.MarketType, "Borrower")


def assert_loan_product(data: dict) -> None:
    _assert_common_fields(data, "LoanProduct")
    assert is_valid_uuid(data["institution_id"])
    assert 0 <= data["base_rate_bps"] <= 3600
    assert 1 <= data["term_months"] <= 360
    assert 0.00 < float(data["max_dti_pct"]) <= 60.00
    assert 300 <= data["min_credit_score"] <= 850
    assert isinstance(data["allow_no_credit_score"], bool)
    assert isinstance(data["credit_building_features"], list)
    for feature in data["credit_building_features"]:
        assert feature in [f.value for f in t.CreditBuildingFeature]
    assert isinstance(data["requires_ta_completion"], bool)
    assert data["product_cap_cents"] > 0
    assert data["committed_principal_cents"] >= 0


def assert_loan(data: dict) -> None:
    _assert_common_fields(data, "Loan")
    assert is_valid_uuid(data["institution_id"])
    assert is_valid_uuid(data["borrower_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["requested_principal_cents"] > 0
    _assert_enum(data, "underwriting_state", t.UnderwritingState, "Loan")
    _assert_enum(data, "servicing_state", t.ServicingState, "Loan")
    if data.get("risk_grade") is not None:
        _assert_enum(data, "risk_grade", t.RiskGrade, "Loan")
    assert data["principal_disbursed_cents"] >= 0
    assert data["principal_repaid_cents"] >= 0
    assert data["charged_off_principal_cents"] >= 0
    assert data["days_past_due"] >= 0
    assert isinstance(data["borrower_in_target_market_at_origination"], bool)


def assert_ta_engagement(data: dict) -> None:
    _assert_common_fields(data, "TAEngagement")
    assert is_valid_uuid(data["institution_id"])
    assert is_valid_uuid(data["borrower_id"])
    _assert_enum(data, "topic", t.TATopic, "TAEngagement")
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert 0.00 < float(data["planned_hours"]) <= 8.00
    assert isinstance(data["competency_verified"], bool)
    _assert_enum(data, "state", t.TAEngagementState, "TAEngagement")


def assert_impact_report(data: dict) -> None:
    _assert_common_fields(data, "ImpactReport")
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["borrower_id"])
    for field in ("jobs_created", "jobs_retained", "housing_units",
                  "businesses_financed"):
        assert data[field] >= 0, f"ImpactReport.{field} may not be negative"
    _assert_enum(data, "state", t.ImpactReportState, "ImpactReport")
    assert data["revision_count"] >= 0


def assert_compliance_measurement(data: dict) -> None:
    _assert_common_fields(data, "ComplianceMeasurement")
    assert is_valid_uuid(data["institution_id"])
    assert data["period_end"] > data["period_start"]
    _assert_enum(data, "weighting_basis", t.WeightingBasis, "ComplianceMeasurement")
    _assert_enum(data, "state", t.MeasurementState, "ComplianceMeasurement")
    _assert_enum(data, "verdict", t.MeasurementVerdict, "ComplianceMeasurement")
    assert data["measured_loan_count"] >= 0
    assert data["target_market_loan_count"] >= 0
    assert data["target_market_loan_count"] <= data["measured_loan_count"]


def assert_award_application(data: dict) -> None:
    _assert_common_fields(data, "AwardApplication")
    assert is_valid_uuid(data["institution_id"])
    _assert_enum(data, "program", t.AwardProgram, "AwardApplication")
    assert data["requested_amount_cents"] > 0
    assert 0.00 <= float(data["match_ratio_pct"]) <= 200.00
    assert data["required_match_cents"] >= 0
    assert data["match_eligible_cents"] >= 0
    assert data["match_shortfall_cents"] >= 0
    assert data["period_end"] > data["period_start"]
    _assert_enum(data, "state", t.AwardState, "AwardApplication")


def assert_matching_fund_commitment(data: dict) -> None:
    _assert_common_fields(data, "MatchingFundCommitment")
    assert is_valid_uuid(data["award_application_id"])
    _assert_enum(data, "source_type", t.MatchSourceType, "MatchingFundCommitment")
    assert data["amount_cents"] > 0
    assert data["eligible_cents"] >= 0
    _assert_enum(data, "status", t.CommitmentStatus, "MatchingFundCommitment")


# ----------------------------------------------------------------------
# Domain invariant checkers
# ----------------------------------------------------------------------
def assert_loan_ledger_invariant(loan: dict) -> None:
    """Outstanding principal is disbursed less repaid less charged off."""
    expected = (
        loan["principal_disbursed_cents"]
        - loan["principal_repaid_cents"]
        - loan["charged_off_principal_cents"]
    )
    assert loan["principal_outstanding_cents"] == expected, (
        "principal_outstanding_cents must equal principal_disbursed_cents minus "
        "principal_repaid_cents minus charged_off_principal_cents, expected "
        f"{expected}, got {loan['principal_outstanding_cents']}"
    )


def assert_match_shortfall_invariant(award: dict) -> None:
    """Shortfall is the requirement less the eligible total, floored at zero."""
    expected = max(0, award["required_match_cents"] - award["match_eligible_cents"])
    assert award["match_shortfall_cents"] == expected, (
        f"match_shortfall_cents must be {expected}, got "
        f"{award['match_shortfall_cents']}"
    )


def assert_posture_matches_ratio(institution: dict) -> None:
    """Posture bands follow reserve_coverage_ratio."""
    ratio = float(institution["reserve_coverage_ratio"])
    if ratio >= 1.0000:
        expected = "COMPLIANT"
    elif ratio >= 0.8000:
        expected = "WATCH"
    else:
        expected = "PROBATION"
    assert institution["compliance_posture"] == expected, (
        f"a reserve_coverage_ratio of {ratio} must read {expected}, got "
        f"{institution['compliance_posture']}"
    )


def assert_decimal_places(value, places: int, label: str) -> None:
    """A numeric response field is carried to a fixed number of decimals."""
    scaled = round(float(value) * (10 ** places))
    assert abs(float(value) * (10 ** places) - scaled) < 1e-6, (
        f"{label} must carry {places} decimal places, got {value}"
    )
