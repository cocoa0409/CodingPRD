"""Queue A - rule ``boundary_precision_check``.

Two pinned boundaries: a sampling batch whose classification confidence lands
exactly on the 0.8000 floor while a 15.0 ppb sample sits exactly on the action
level, and a progress report whose replacement universe is empty.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    BatchState,
    Classification,
    ComplianceStatus,
    CctOptimizationStatus,
    EquityTier,
    FundingMode,
    Material,
    SampleType,
    Side,
    SourceType,
)


# ---------------------------------------------------------------------------
# sampling_confidence_exactly_at_floor_validates_and_action_level_is_strict
# ---------------------------------------------------------------------------


def _batch_at_the_confidence_floor(api: ApiClient):
    """Five samples of 2.0, 3.0, 4.0, 15.0 and 16.0 ppb in one OPEN stratum."""
    system = fixtures.create_water_system(
        api,
        "IL2031013",
        system_name="Quarrybrook Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    latest = None
    for ppb, stamp in (
        (2.0, "2026-07-11T09:00:00Z"),
        (3.0, "2026-07-12T09:00:00Z"),
        (4.0, "2026-07-13T09:00:00Z"),
        (15.0, "2026-07-14T09:00:00Z"),
        (16.0, "2026-07-15T09:00:00Z"),
    ):
        latest = fixtures.append_sample(
            api, batch["id"], line["id"], ppb, stamp, sample_type=SampleType.FIRST_DRAW
        )
    return {"system": system, "line": line, "batch": batch, "before": latest}


def test_sample_exactly_at_the_action_level_is_not_an_exceedance(api: ApiClient) -> None:
    """The 15.0 ppb reading is excluded from the tally, so confidence lands on 0.8000.

    PRD 3.4: "`exceedance` is true when `percentile_90_ppb` is strictly greater
    than the action level of 15.0 parts per billion — a ninetieth percentile of
    exactly 15.0 is **not** an exceedance."
    PRD 3.4: "`exceedance_count` is the number of valid samples whose own
    `lead_ppb` is strictly greater than 15.0."
    PRD 3.4: "And `classification_confidence` is one minus the exceedance count
    divided by the valid-sample count, rounded half-up to four decimal places."

    Design: Difficulty/boundary_precision_check/sampling_confidence_exactly_at_floor_validates_and_action_level_is_strict
    """
    scenario = _batch_at_the_confidence_floor(api)

    assert scenario["before"]["required_sample_count"] == 5
    assert scenario["before"]["valid_sample_count"] == 5
    assert scenario["before"]["state"] == BatchState.OPEN

    validated = fixtures.validate_batch(api, scenario["batch"]["id"])

    assert validated["percentile_90_ppb"] == pytest.approx(16.0)
    assert validated["exceedance"] is True
    assert validated["exceedance_count"] == 1
    assert validated["classification_confidence"] == pytest.approx(0.8000)
    assert validated["classification_confidence"] != pytest.approx(0.6000)


def test_confidence_exactly_at_the_floor_validates_rather_than_rejects(
    api: ApiClient,
) -> None:
    """0.8000 is admissible, so the batch validates and re-optimization is triggered.

    PRD 3.4: "When `classification_confidence` is at least 0.8000 — exactly 0.8000
    validates — the batch moves from `OPEN` to `VALIDATED`."
    PRD 3.4: "On that branch alone, and on that branch only when `exceedance` came
    out true, a second link fires: the parent water system's
    `cct_optimization_status` moves to `PENDING_REOPTIMIZATION`."
    PRD 3.4: "When `classification_confidence` is below 0.8000, the batch moves
    from `OPEN` to `REJECTED` instead, and `rejection_reason` is set to
    `CONFIDENCE_BELOW_FLOOR`."

    Design: Difficulty/boundary_precision_check/sampling_confidence_exactly_at_floor_validates_and_action_level_is_strict
    """
    scenario = _batch_at_the_confidence_floor(api)

    validated = fixtures.validate_batch(api, scenario["batch"]["id"])

    assert validated["state"] == BatchState.VALIDATED
    assert validated["state"] != BatchState.REJECTED
    assert validated["rejection_reason"] is None

    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["cct_optimization_status"] == CctOptimizationStatus.PENDING_REOPTIMIZATION


# ---------------------------------------------------------------------------
# progress_report_empty_universe_yields_exactly_100_pct_and_tier_d
# ---------------------------------------------------------------------------


def _empty_universe_system(api: ApiClient):
    """One NON_LEAD line, a zero baseline and no replacement orders at all."""
    system = fixtures.create_water_system(
        api,
        "IL2031014",
        system_name="Nettlewood Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=0,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.COPPER,
        observed_at="2026-06-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.CUSTOMER,
        observed_material=Material.PLASTIC,
        observed_at="2026-06-01T00:00:00Z",
    )
    return {"system": system, "line": line}


def test_zero_baseline_denominator_is_defined_as_exactly_one_hundred_per_cent(
    api: ApiClient,
) -> None:
    """No lead, no galvanized, no unknown and nothing replaced still reports 100.00.

    PRD 3.8: "`replacement_progress_pct` is defined as exactly 100.00 when
    `baseline_denominator` is zero — the empty-universe case is a definition,
    never a division by zero — and otherwise one hundred times `replaced_count`
    divided by `baseline_denominator`, rounded half-up to two decimals."
    PRD 3.8: "`baseline_denominator` is the sum of the water system's
    `lead_count`, `grr_count` and `unknown_count` plus that replaced count, so
    that non-lead lines which were never replaced contribute to neither the
    numerator nor the denominator."

    Design: Difficulty/boundary_precision_check/progress_report_empty_universe_yields_exactly_100_pct_and_tier_d
    """
    scenario = _empty_universe_system(api)

    before = fixtures.read_water_system(api, scenario["system"]["id"])
    assert before["lead_count"] == 0
    assert before["unknown_count"] == 0
    assert before["non_lead_count"] == 1
    assert (
        fixtures.read_service_line(api, scenario["line"]["id"])["classification"]
        == Classification.NON_LEAD
    )

    report = fixtures.create_progress_report(
        api, scenario["system"]["id"], "2026-08-01", "2026-08-31"
    )

    assert report["baseline_denominator"] == 0
    assert report["replacement_progress_pct"] == pytest.approx(100.00)
    assert report["replacement_progress_pct"] != pytest.approx(0.00)
    assert report["replaced_count"] == 0
    assert report["full_replacement_count"] == 0
    assert report["partial_replacement_count"] == 0


def test_empty_period_lands_tier_d_and_clamps_the_shortfall_at_zero(
    api: ApiClient,
) -> None:
    """A 0.00 share keys TIER_D and a mandate of 0 less an allowance of 1 clamps to 0.00.

    PRD 3.8: "The second step computes the report's own `disadvantaged_share_pct`
    as one hundred multiplied by `disadvantaged_full_count`, divided by the greater
    of 1 and `full_replacement_count` so that an empty period never divides by
    zero, rounded half-up to two decimals; the `equity_tier` and its
    `equity_multiplier` are keyed on that share **and on nothing else** — never on
    `base_credit` and never on `total_credit`."
    PRD 3.8: "A share of at least 60.00 is `TIER_A` with a multiplier of 1.20; at
    least 40.00 is `TIER_B` at 1.10; at least 20.00 is `TIER_C` at 1.00; anything
    below that is `TIER_D` at 0.90."
    PRD 3.8: "The sixth step computes `shortfall_credit` as the mandated annual
    credit less the deferral allowance less the total credit, clamped at zero so
    it never goes negative, rounded half-up to two decimals, and sets
    `compliance_status` to `ON_TRACK` when `shortfall_credit` is exactly zero and
    `BEHIND` otherwise."

    Design: Difficulty/boundary_precision_check/progress_report_empty_universe_yields_exactly_100_pct_and_tier_d
    """
    scenario = _empty_universe_system(api)

    report = fixtures.create_progress_report(
        api, scenario["system"]["id"], "2026-08-01", "2026-08-31"
    )

    assert report["base_credit"] == pytest.approx(0.00)
    assert report["disadvantaged_share_pct"] == pytest.approx(0.00)
    assert report["equity_tier"] == EquityTier.TIER_D
    assert report["equity_multiplier"] == pytest.approx(0.90)
    assert report["total_credit"] == pytest.approx(0.00)
    assert report["mandated_annual_credit"] == 0
    assert report["deferral_allowance"] == 1
    assert report["shortfall_credit"] == pytest.approx(0.00)
    assert report["compliance_status"] == ComplianceStatus.ON_TRACK
    assert "version" not in report
    assert "updated_at" not in report
    assert "id" in report
    assert "created_at" in report
