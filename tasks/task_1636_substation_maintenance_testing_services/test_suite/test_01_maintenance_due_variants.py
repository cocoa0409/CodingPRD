"""Maintenance due-date dual variants (PRD §3.5): interval-baseline vs
condition-adjusted produce different dates for identical asset data."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    create_accepted_test_event,
    create_certified_technician,
    setup_asset,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


def _setup_conditioned_asset() -> dict:
    """Asset with last maintenance 2026-01-15; one ACCEPTED FAIL insulation
    test (400 Mohm @ 40C) and one ACCEPTED MARGINAL oil test (25 ppm)."""
    base = setup_asset(
        "POWER_TRANSFORMER",
        criticality="HIGH",
        nameplate_mva=20,
        install_date="2020-05-01T00:00:00Z",
        last_maintenance_completed_at="2026-01-15T00:00:00Z",
    )
    _, tech_headers = create_certified_technician("NETA_LEVEL_2")
    asset_id = base["asset"]["id"]
    create_accepted_test_event(
        asset_id, tech_headers, "INSULATION_RESISTANCE",
        value_primary=400, ambient_temp_c=40, measured_at="2026-07-01T10:00:00Z",
    )
    create_accepted_test_event(
        asset_id, tech_headers, "OIL_MOISTURE",
        value_primary=25, measured_at="2026-07-02T10:00:00Z",
    )
    return base


class TestMaintenanceDueDualVariant:
    def test_forecast_exposes_divergent_variants(self):
        """PRD §3.5: "The **interval-baseline** variant adds the policy's
        `interval_months` to the baseline regardless of condition. The
        **condition-adjusted** variant — which is authoritative for the asset's
        stored `next_due_date` — divides the interval by 4 when
        `condition_score` is strictly below `condition_critical_threshold`,
        divides it by 2 when the score is strictly below
        `condition_escalation_threshold` but not below the critical threshold,
        and otherwise uses the full `interval_months`; the result is added to
        the baseline."
        PRD §3.5: "A computed read on the asset exposes both variants together
        with the current `condition_score` and an `escalation_active` flag,
        under the response keys `condition_score`, `next_due_interval_baseline`,
        `next_due_condition_adjusted`, and `escalation_active`."

        Design: Difficulty/dual_variant_calc/maintenance_due_dual_variant
        """
        base = _setup_conditioned_asset()
        forecast = validate_success(
            api_client.get_asset_forecast(base["asset"]["id"], OPS)
        )
        # FAIL insulation (30) + MARGINAL oil (70) renormalize over the two
        # present weights: (0.4*30 + 0.35*70) / 0.75 = 48.67; the accepted
        # tests auto-created one C2 (-2) and one C3 (-1) defect -> 45.67.
        assert forecast["condition_score"] == pytest.approx(45.67, abs=0.01)
        assert forecast["next_due_interval_baseline"] == "2027-01-15"
        assert forecast["next_due_condition_adjusted"] == "2026-07-15"
        assert forecast["next_due_interval_baseline"] != forecast["next_due_condition_adjusted"]

    def test_condition_adjusted_variant_is_stored_on_asset(self):
        """PRD §3.5: "The **condition-adjusted** variant — which is authoritative
        for the asset's stored `next_due_date` — divides the interval by 4 when
        `condition_score` is strictly below `condition_critical_threshold`,
        divides it by 2 when the score is strictly below
        `condition_escalation_threshold` but not below the critical threshold,
        and otherwise uses the full `interval_months`; the result is added to
        the baseline."
        PRD §3.4: "Second, when the accepted `result` is `MARGINAL` or `FAIL`,
        the platform auto-creates a `Defect` on the same asset with
        `test_event_id` pointing at the accepted event, a system-generated
        `title`, severity mapped from the result (`FAIL` becomes `C2`;
        `MARGINAL` becomes `C3` — any severity supplied by the caller on this
        path is ignored), and status `OPEN`."

        Design: Difficulty/dual_variant_calc/maintenance_due_dual_variant
        """
        base = _setup_conditioned_asset()
        asset = validate_success(api_client.get_asset(base["asset"]["id"], OPS))
        # Score 45.67 is below the escalation threshold 60 but not below the
        # critical threshold 40, so the 12-month interval is halved: the
        # authoritative stored next_due_date is 2026-01-15 + 6 months.
        assert asset["condition_score"] == pytest.approx(45.67, abs=0.01)
        assert asset["next_due_date"] == "2026-07-15"
