"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentStatus,
    AtmDisposition,
    BranchStatus,
    BranchType,
    CampaignStatus,
    CaseStatus,
    DispositionState,
    ForecastStatus,
    GovernanceFlag,
    ImpactTier,
    MonitoringPosture,
    NoticeStatus,
    NotificationState,
    PerformanceBand,
    PlanStatus,
    PropertyStatus,
    RampStatus,
    SaturationTier,
    SaturationTier as _Tier,
    ScoringVariant,
    TenureClass,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_identity(data: dict) -> None:
    """Every stored resource carries a bare-UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )


def assert_mutable_identity(data: dict) -> None:
    """A mutable resource additionally carries updated_at and an integer version."""
    assert_identity(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 on creation"


def assert_append_only_identity(data: dict) -> None:
    """An immutable append-only record exposes only id and created_at."""
    assert_identity(data)
    assert "updated_at" not in data, "an append-only record must not expose updated_at"
    assert "version" not in data, "an append-only record must not expose version"


def assert_market_area(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["saturation_tier"] in _values(SaturationTier)
    assert isinstance(data["competitor_density_index"], int)
    assert isinstance(data["own_branch_count"], int)
    assert isinstance(data["branch_density_per_100k"], int)
    assert isinstance(data["absorbed_deposits_cents"], int)
    assert isinstance(data["cumulative_runoff_deposits_cents"], int)
    assert isinstance(data["flagged_case_count"], int)
    assert isinstance(data["remediation_case_count"], int)
    assert isinstance(data["de_novo_hold"], bool)


def assert_branch(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(BranchStatus)
    assert data["branch_type"] in _values(BranchType)
    assert data["tenure_class"] in _values(TenureClass)
    assert data["performance_band"] in _values(PerformanceBand)
    assert data["scoring_variant"] in _values(ScoringVariant)
    assert isinstance(data["deposit_balance_cents"], int)
    assert isinstance(data["snapshot_count"], int)
    assert isinstance(data["transferred_in_deposits_cents"], int)


def assert_performance_snapshot(data: dict) -> None:
    assert_append_only_identity(data)
    assert isinstance(data["composite_score_bps"], int)
    assert 0 <= data["composite_score_bps"] <= 10000
    assert data["band"] in _values(PerformanceBand)


def assert_consolidation_case(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(CaseStatus)
    assert data["governance_flag"] in _values(GovernanceFlag)
    assert data["impact_tier"] in _values(ImpactTier)
    assert data["monitoring_posture"] in _values(MonitoringPosture)
    assert isinstance(data["returned_count"], int)
    assert isinstance(data["notice_required_days"], int)
    assert isinstance(data["net_annual_savings_cents"], int)
    assert isinstance(data["gross_annual_savings_cents"], int)


def assert_retention_forecast(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(ForecastStatus)
    assert isinstance(data["retention_bps"], int)
    assert data["retention_bps"] <= 9800, "retention is capped at the retention ceiling"
    assert (
        data["retained_deposits_cents"] + data["runoff_cents"]
        == data["baseline_deposits_cents"]
    ), "the retained/runoff split must be the exact complement of the baseline"


def assert_impact_assessment(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(AssessmentStatus)
    assert data["impact_tier"] in _values(ImpactTier)
    assert data["market_saturation_tier_at_assessment"] in _values(_Tier)
    assert 0 <= data["impact_score"] <= 100, "the impact score is clamped to 0 through 100"
    assert isinstance(data["requires_public_comment"], bool)
    assert data["notice_required_days"] <= 180, "notice days are capped at 180"


def assert_closure_notice(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(NoticeStatus)
    assert isinstance(data["lead_days"], int)
    assert isinstance(data["required_lead_days"], int)


def assert_staff_disposition(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["disposition_state"] in _values(DispositionState)
    assert data["notification_state"] in _values(NotificationState)
    assert isinstance(data["severance_weeks"], int)
    assert isinstance(data["weekly_pay_cents"], int)
    assert isinstance(data["severance_amount_cents"], int)


def assert_property_disposition(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(PropertyStatus)
    assert data["atm_disposition"] in _values(AtmDisposition)
    assert data["atm_decision_final"] in _values(AtmDisposition)
    assert isinstance(data["atm_breakeven_met"], bool)
    assert isinstance(data["annual_carry_cents"], int)


def assert_transition_campaign(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(CampaignStatus)
    assert isinstance(data["wave_days"], int) and data["wave_days"] >= 1
    assert isinstance(data["daily_onboarding_load"], int)


def assert_de_novo_plan(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _values(PlanStatus)
    assert data["ramp_status"] in _values(RampStatus)
    assert 0 <= data["site_score"] <= 100, "the site score is a whole point on a 0-to-100 scale"
    assert isinstance(data["ramp_month_index"], int)
    assert isinstance(data["ramp_attainment_bps"], int)


def assert_deposit_observation(data: dict) -> None:
    assert_append_only_identity(data)
    assert isinstance(data["observed_deposits_cents"], int)
    assert isinstance(data["forecast_deposits_cents"], int)
    assert isinstance(data["variance_bps"], int)
    assert isinstance(data["breach"], bool)
    assert 1 <= data["month_index"] <= 12


def assert_market_deposit_conservation(market: dict, branches: list, expected_total: int) -> None:
    """The trade area's deposits plus its runoff ledger are a conserved quantity."""
    counted = ("ACTIVE", "UNDER_REVIEW", "CLOSURE_SCHEDULED", "CLOSED", "DE_NOVO_RAMPING")
    total = sum(b["deposit_balance_cents"] for b in branches if b["status"] in counted)
    total += market["cumulative_runoff_deposits_cents"]
    assert total == expected_total, (
        f"market deposit total must be conserved exactly: expected {expected_total}, got {total}"
    )


def assert_headcount_conservation(case: dict, closing_branch: dict, receiving_branch: dict,
                                  expected_total: int) -> None:
    """Closing FTE plus receiving FTE plus severed FTE is a conserved quantity."""
    total = (
        closing_branch["fte_count"]
        + receiving_branch["fte_count"]
        + case["severed_fte_count"]
    )
    assert total == expected_total, (
        f"network headcount must be conserved exactly: expected {expected_total}, got {total}"
    )
