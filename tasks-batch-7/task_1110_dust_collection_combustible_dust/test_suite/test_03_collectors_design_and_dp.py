"""Collector engineering: air-to-cloth ratio, explosion-protection design
variants, differential-pressure trend derivation, and filter-change
reconciliation."""
import pytest

from test_helpers import (
    assert_collector,
    create_collector,
    create_dust_sample,
    create_site,
    setup_site_with_in_service_collector,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["compliance_engineer_headers"]


def test_air_to_cloth_ratio_computed(api):
    """PRD §3.3: "The derived `air_to_cloth_ratio` is the `design_airflow_acfm`
    divided by `filter_area_ft2`, rounded to 4 decimal places, round-half-up."

    Design: Corner/entities/collector_computed_air_to_cloth_ratio
    """
    site = create_site(insurer_id="FM-1")
    sample = create_dust_sample(site["id"])
    collector = create_collector(site["id"], sample["id"], tag="C",
                                 design_airflow_acfm=5000, filter_area_ft2=1000,
                                 internal_volume_m3=8, installed_vent_area_m2=500)
    assert_collector(collector)
    assert collector["air_to_cloth_ratio"] == pytest.approx(5.0, abs=1e-9)


def test_small_vessel_prescriptive_vent_area(api):
    """PRD §3.3: "Compute the maximum reduced pressure as
    `Pred_max = min(Pmax * 0.5, 0.5 + 0.04 * Kst**0.5)` — that is, take the
    smaller of (half of Pmax) and (0.5 plus 0.04 multiplied by the square root
    of Kst)."
    PRD §3.3: "Compute the unrestricted vent coefficient
    `Av0 = 0.1 * Kst * V**(2.0/3.0)`, where `V` is `internal_volume_m3` raised
    to the two-thirds power."
    PRD §3.3: "The required vent area is
    `required_vent_area_m2 = Av0 * (Pmax / max(Pred_max, 0.05))**0.5`".
    PRD §3.3: "Round `required_vent_area_m2` to exactly 3 decimal places,
    round-half-up."

    Kst=200, Pmax=9, V=10 (not over 25, so the default prescriptive variant
    applies): Pred_max = min(4.5, 1.0657) = 1.0657, required area = 269.776.

    Design: Difficulty/combinatorial_formula/explosion_protection_design_min_max_conditional_branch
    """
    site = create_site()
    sample = create_dust_sample(site["id"], material_name="k",
                                kst_bar_m_per_s=200, pmax_bar_g=9.0, mie_mj=10)
    collector = create_collector(site["id"], sample["id"], tag="DC-small",
                                 internal_volume_m3=10, installed_vent_area_m2=0)
    assert collector["required_vent_area_m2"] == pytest.approx(269.776, abs=1e-9)
    assert collector["pred_max_bar_g"] == pytest.approx(1.066, abs=1e-9)
    assert collector["vent_adequate"] is False


def test_large_vessel_performance_multiplier_vent_area(api):
    """PRD §3.3: "There is a **performance-based variant** for large vessels.
    When `internal_volume_m3` exceeds 25, a 1.20 safety multiplier is applied
    to `required_vent_area_m2` before the 3-decimal-place rounding — so the
    same collector geometry yields a larger required vent area under the
    variant."

    Kst=200, Pmax=9, V=30: prescriptive value 561.157, then the 1.20
    multiplier yields 673.388 after the 3-decimal round.

    Design: Difficulty/combinatorial_formula/explosion_protection_design_min_max_conditional_branch
    """
    site = create_site()
    sample = create_dust_sample(site["id"], material_name="k",
                                kst_bar_m_per_s=200, pmax_bar_g=9.0, mie_mj=10)
    collector = create_collector(site["id"], sample["id"], tag="DC-large",
                                 internal_volume_m3=30, installed_vent_area_m2=0)
    assert collector["required_vent_area_m2"] == pytest.approx(673.388, abs=1e-9)
    assert collector["pred_max_bar_g"] == pytest.approx(1.066, abs=1e-9)
    assert collector["vent_adequate"] is False


def test_dp_slope_below_delta_stays_stable(api):
    """PRD §3.3: "Else if there are at least 3 readings in the lookback window
    and the most recent reading minus the reading three positions back is at
    least 1.5 inches of water column, `dp_trend` is `RISING`."
    PRD §3.3: "Otherwise `dp_trend` is `STABLE`."

    Readings 2.0, 2.5, 3.0: delta = 3.0 - 2.0 = 1.0, below the 1.5 slope
    threshold, and below the 6.0 high-alarm threshold.

    Design: Corner/calculations/dp_reading_slope_detection_rising
    """
    site, _sample, collector = setup_site_with_in_service_collector(
        insurer_id="FM-1")
    for dp in (2.0, 2.5):
        validate_success(api.submit_dp_reading(site["id"], collector["id"], dp,
                                               ENGINEER), 201)
    validate_success(api.submit_dp_reading(site["id"], collector["id"], 3.0,
                                           ENGINEER), 201)

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["dp_trend"] == "STABLE"


def test_dp_alarm_sets_filter_change_due(api):
    """PRD §3.3: "If `dp_current_inwc` is at least 6.0 inches of water column
    (the high-alarm threshold), `dp_trend` is `ALARM_HIGH`."
    PRD §3.3: "A filter change becomes due when either condition holds:
    `dp_current_inwc` is at least 6.0 in w.c., OR at least 180 days have
    elapsed since `last_filter_change_at`. In either case `filter_change_due`
    is set true."

    Design: Difficulty/transitive_cascade/dp_reading_to_alarm_to_collector_filter_due_to_site_posture
    """
    site, _sample, collector = setup_site_with_in_service_collector()
    for dp in (2.0, 3.5, 6.5):
        validate_success(api.submit_dp_reading(site["id"], collector["id"], dp,
                                               ENGINEER), 201)

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["dp_current_inwc"] == pytest.approx(6.5, abs=1e-9)
    assert after["dp_trend"] == "ALARM_HIGH"
    assert after["filter_change_due"] is True


def test_record_filter_change_reconciles_derived_fields(api):
    """PRD §3.3: "Recording a filter change resets `last_filter_change_at` to
    the current clock, resets `dp_current_inwc` to 0, clears
    `filter_change_due` to false, and bumps `Collector.version` by 1."
    PRD §3.3: "Otherwise `dp_trend` is `STABLE`."

    Design: Corner/cross_cutting/derived_field_filter_change_due_reconciles_on_record_filter_change
    """
    site, _sample, collector = setup_site_with_in_service_collector(
        insurer_id="FM-1")
    validate_success(api.submit_dp_reading(site["id"], collector["id"], 6.5,
                                           ENGINEER), 201)
    alarmed = validate_success(api.get_collector(site["id"], collector["id"],
                                                 ENGINEER), 200)
    assert alarmed["filter_change_due"] is True

    validate_success(api.record_filter_change(site["id"], collector["id"],
                                              ENGINEER), 200)
    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["dp_current_inwc"] == 0
    assert after["filter_change_due"] is False
    assert after["dp_trend"] == "STABLE"
