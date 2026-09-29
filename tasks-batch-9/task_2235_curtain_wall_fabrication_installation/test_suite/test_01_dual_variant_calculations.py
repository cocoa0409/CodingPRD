"""Two calculations in this service publish two independent variants of the
same quantity: field labor cost (forward estimate versus chronological actual)
and procurement risk (nominal versus expedite-adjusted)."""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_crew_hour_ledger,
    assert_day_cost_sum_equals_final,
    assert_day_indices_packed,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]


class TestZoneLaborVariants:
    """The forward estimate and the chronological actual coexist on one zone."""

    def test_certification_writes_the_chronological_actual_and_leaves_the_forward_estimate_alone(
        self,
    ):
        """Certifying a zone stamps final_labor_cost_cents from the crew days
        actually posted while provisional_labor_cost_cents keeps the value
        written at hang time, so the two variants diverge on the same row.

        PRD: "This variant deliberately charges every hour at straight time and ignores elevation entirely: at hang time no crew-day logs exist yet, so neither overtime nor a high-elevation factor can be known."

        Design: Difficulty/dual_variant_calc/zone_labor_provisional_forward_versus_final_chronological
        """
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]

        before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert before["provisional_labor_cost_cents"] == 940800
        assert before["final_labor_cost_cents"] is None

        response = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        zone = validate_success(response, expected_status=200)

        assert zone["provisional_labor_cost_cents"] == 940800
        assert zone["final_labor_cost_cents"] == 1149540
        assert (
            zone["final_labor_cost_cents"] - zone["provisional_labor_cost_cents"] == 208740
        )
        assert zone["weather_status"] == "WEATHER_TIGHT"
        assert zone["install_status"] == "PANELS_HUNG"
        assert zone["certified_line_cents"] == 58266376

    def test_chronological_actual_equals_the_sum_of_the_per_day_rounded_amounts(self):
        """Each crew day carries its own rounded day_cost_cents, indexed 1, 2, 3
        in work_date order, and the zone total is exactly their sum — never a
        single rounding of the unrounded products.

        PRD: "Because each day is rounded to whole cents *before* it enters the sum, the zone total must equal the sum of the surviving logs' persisted `day_cost_cents` values exactly."

        Design: Difficulty/dual_variant_calc/zone_labor_provisional_forward_versus_final_chronological
        """
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]
        zone = get_success_data(
            api_client.certify_weather_tight(zone_id, f.certify_weather_tight_payload(), PM)
        )

        logs = get_success_data(api_client.list_zone_crew_day_logs(zone_id, PM))
        posted = [log for log in logs if log["status"] == "POSTED"]
        assert len(posted) == 3

        by_index = {log["day_index"]: log for log in posted}
        assert by_index[1]["day_cost_cents"] == 428260
        assert by_index[2]["day_cost_cents"] == 360640
        assert by_index[3]["day_cost_cents"] == 360640

        assert_day_indices_packed(posted)
        assert_day_cost_sum_equals_final(zone, posted)
        assert zone["consumed_crew_hours"] == pytest.approx(100.0, abs=0.01)
        assert zone["remaining_crew_hours"] == pytest.approx(220.0, abs=0.01)
        assert_crew_hour_ledger(zone)


class TestGlassRiskVariants:
    """The nominal and expedite-adjusted variants score the same order
    differently in two terms at once."""

    def test_nominal_variant_scores_the_quoted_lead_time_against_the_ninety_day_horizon(self):
        """A fresh order with no expedite and no coating revision is scored
        under NOMINAL: effective_lead_days is the quoted figure and the score
        stays below the release threshold.

        PRD: "The `NOMINAL` variant applies when `expedite_tier` is 0 and `coating_revision_count` is 0: `effective_lead_days` is the `quoted_lead_time_days` plus a re-fire penalty of 21 days for each coating revision recorded, and the judgement horizon is 90 days."

        Design: Difficulty/dual_variant_calc/glass_risk_nominal_versus_expedite_adjusted_variant
        """
        ctx = fx.new_project()
        order = get_success_data(
            api_client.create_glass_order(
                f.create_glass_order_payload(
                    ctx["package_id"], quoted_lead_time_days=90, ordered_lites=240
                ),
                PROCUREMENT,
            )
        )

        assert order["risk_variant"] == "NOMINAL"
        assert order["effective_lead_days"] == 90
        assert order["risk_score"] == pytest.approx(48.11, abs=0.01)
        assert order["risk_flag"] is False
        assert order["state"] == "ORDERED"

    def test_expedite_switches_the_variant_and_rescores_without_moving_the_order_state(self):
        """Buying tier 1 credits ten days and judges the surviving float against
        the nearer 45-day horizon, so the score falls by 21.24 points while the
        order stays in ORDERED.

        PRD: "The expedited variant therefore diverges from the nominal one in two terms at once — it credits the days bought *and* judges the surviving float against a nearer horizon."

        Design: Difficulty/dual_variant_calc/glass_risk_nominal_versus_expedite_adjusted_variant
        """
        ctx = fx.new_project()
        fx.create_glass_order(ctx, quoted_lead_time_days=90, ordered_lites=240)
        nominal = ctx["glass_order"]
        assert nominal["risk_variant"] == "NOMINAL"
        assert nominal["risk_score"] == pytest.approx(48.11, abs=0.01)

        response = api_client.request_expedite(
            ctx["glass_order_id"], f.request_expedite_payload(1), PROCUREMENT
        )
        expedited = validate_success(response, expected_status=200)

        assert expedited["risk_variant"] == "EXPEDITE_ADJUSTED"
        assert expedited["expedite_tier"] == 1
        assert expedited["effective_lead_days"] == 80
        assert expedited["risk_score"] == pytest.approx(26.87, abs=0.01)
        assert expedited["risk_flag"] is False
        assert expedited["state"] == "ORDERED"
        assert nominal["risk_score"] - expedited["risk_score"] == pytest.approx(21.24, abs=0.01)
