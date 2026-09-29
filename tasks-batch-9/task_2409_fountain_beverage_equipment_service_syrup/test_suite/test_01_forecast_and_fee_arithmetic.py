"""Dual-variant calculations and multi-term formulae.

Covers the two forecast variants over identical telemetry, the two equipment
exposure variants over the identical fleet, the pinned per-quarter rounding
order of the shortfall fee, and the multi-term service-call severity score.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    activate_agreement,
    add_telemetry,
    assess_shortfall_payload,
    create_agreement,
    create_outlet,
    create_position,
    create_service_call_payload,
    create_supply_item,
    create_unit,
    evaluate_task,
    create_task,
    pin_clock,
    read_agreement,
    read_position,
    read_unit,
    recall_decision_payload,
    run_forecast,
    TEST_USERS,
)

ADMIN_ALT = TEST_USERS["admin_alt_headers"]

THREE_QUARTER_READINGS = [
    (128126.72, "2026-02-15T00:00:00Z"),
    (192126.72, "2026-05-15T00:00:00Z"),
    (230526.72, "2026-08-15T00:00:00Z"),
]


def _forecast_scenario():
    """Large outlet, one 7000 oz week of telemetry, six cartridges on hand."""
    pin_clock("2026-08-15T00:00:00Z")
    outlet = create_outlet(
        name="Stadium Concourse 4",
        account_code="ACCT-DVC-A",
        region_code="R1",
        throughput_tier="LARGE",
        water_hardness_gpg=8,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=8000,
        equipment_value_cents=480000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=50,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-DVC-A-01",
        installed_at="2026-01-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_CART",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    add_telemetry(
        unit["id"], item["id"], 7000, "2026-08-10T00:00:00Z", window_days=7,
        source="TELEMETRY",
    )
    position = create_position(outlet["id"], item["id"], 6)
    return outlet, agreement, unit, item, position


def _assessment_scenario(account_code, serial_number, sku_code,
                         readings=THREE_QUARTER_READINGS):
    """An ACTIVE agreement with three quarters of under-commitment telemetry.

    The clock is pinned at the assessment instant from the outset because PRD
    §2.6 rung 20 refuses any ``reading_at`` later than the logical clock, and the
    third quarter's reading sits at 2026-08-15.
    """
    pin_clock("2026-10-01T00:00:00Z")
    outlet = create_outlet(
        name="Airport Food Court B",
        account_code=account_code,
        region_code="R2",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2027-01-01T00:00:00Z",
        annual_commitment_gallons=8000,
        equipment_value_cents=480000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=50,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number=serial_number,
        installed_at="2026-01-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code=sku_code,
        brand_name="Diet Coke",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    for ounces, reading_at in readings:
        add_telemetry(unit["id"], item["id"], ounces, reading_at, window_days=30)
    pin_clock("2026-10-01T00:00:00Z")
    return outlet, agreement, unit, item


def _severity_scenario():
    """Outlet whose two overdue tasks leave it RESTRICTED with a counter of 2."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Highway Diner 7",
        account_code="ACCT-CF-B",
        region_code="R4",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-CF-B-01",
        installed_at="2026-01-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    preventive = create_task(unit["id"], "PREVENTIVE", "2026-08-02T00:00:00Z")
    sanitation = create_task(unit["id"], "SANITATION", "2026-08-02T00:00:00Z")
    pin_clock("2026-08-10T00:00:00Z")
    evaluate_task(preventive["id"])
    evaluate_task(sanitation["id"])
    return outlet, unit


class TestForecastVariantDivergence:
    def test_projected_variant_adds_the_large_tier_factor_to_the_same_telemetry(self, api):
        """PRD §3.6: "Under `TRAILING_ACTUAL` the projection is simply the daily
        rate multiplied by 14, and the outlet's `throughput_tier` is ignored
        entirely. Under `THROUGHPUT_PROJECTED` the same fourteen-day projection
        is additionally multiplied by the tier factor of the outlet's
        `throughput_tier`: a `SMALL` outlet uses 1.00, a `MEDIUM` outlet 1.15 and
        a `LARGE` outlet 1.30 — so from identical telemetry a large outlet
        forecasts thirty percent more units than a small one."

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_trailing_actual_vs_throughput_projected
        """
        _outlet, _agreement, _unit, _item, position = _forecast_scenario()

        trailing = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        assert trailing["forecast_variant"] == "TRAILING_ACTUAL"
        assert trailing["forecast_units"] == pytest.approx(34.00, abs=0.01)
        assert trailing["requested_units"] == 34

        projected = run_forecast(position["id"], "THROUGHPUT_PROJECTED", 7)
        assert projected["forecast_variant"] == "THROUGHPUT_PROJECTED"
        assert projected["forecast_units"] == pytest.approx(46.00, abs=0.01)
        assert projected["requested_units"] == 46

        assert projected["forecast_units"] - trailing["forecast_units"] == pytest.approx(
            12.00, abs=0.01
        )
        assert projected["requested_units"] - trailing["requested_units"] == 12

    def test_both_variants_leave_the_same_alert_band_and_odometer(self, api):
        """PRD §3.6: "The resulting `alert_level` is `CRITICAL` when the position
        has zero `on_hand_units` **or** its cover is under 3 days, `LOW` when the
        cover is under 7 days without meeting the critical test, and `NONE`
        otherwise."

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_trailing_actual_vs_throughput_projected
        """
        _outlet, _agreement, unit, _item, position = _forecast_scenario()

        run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        projected = run_forecast(position["id"], "THROUGHPUT_PROJECTED", 7)

        assert projected["alert_level"] == "CRITICAL"
        assert projected["promo_suppressed"] is False
        assert projected["on_hand_units"] == 6
        assert projected["allocated_units"] == 0
        assert read_position(position["id"])["version"] == 3
        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            54.69, abs=0.01
        )


class TestExposureVariantDivergence:
    def test_book_value_exposure_depreciates_below_the_recall_floor(self, api):
        """PRD §3.9: "Under the `BOOK_VALUE` variant the unit's exposure is the
        agreement's `equipment_value_cents` multiplied by one minus one percent
        per whole month in service, with that multiplier clamped up to zero so a
        very old machine is worth nothing rather than a negative amount."

        Design: Difficulty/dual_variant_calc/recall_exposure_variant_divergence_book_value_vs_replacement_risk
        """
        _outlet, agreement, unit, _item = _assessment_scenario(
            "ACCT-DVC-B", "SN-DVC-B-01", "DIET_CART"
        )

        payload = assess_shortfall_payload("2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z")
        payload["exposure_variant"] = "BOOK_VALUE"
        assessed = validate_success(
            api.assess_shortfall(agreement["id"], payload, TEST_USERS["admin_headers"])
        )
        assert assessed["recall_exposure_cents"] == 436800
        assert assessed["assessed_fee_cents"] == 84853
        assert assessed["status"] == "SHORTFALL_REVIEW"

        refused = api.recall_decision(
            agreement["id"], recall_decision_payload("RECALL"),
            TEST_USERS["officer_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_RECALL_EXPOSURE_BELOW_FLOOR.value, 422)

        assert read_agreement(agreement["id"])["status"] == "SHORTFALL_REVIEW"
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"

    def test_replacement_risk_exposure_escalates_over_the_recall_floor(self, api):
        """PRD §3.9: "Under the `REPLACEMENT_RISK` variant the unit's exposure is
        instead `equipment_value_cents` multiplied by one plus one half of one
        percent per whole month in service, so age escalates rather than erodes
        the figure."

        Design: Difficulty/dual_variant_calc/recall_exposure_variant_divergence_book_value_vs_replacement_risk
        """
        _outlet, agreement, unit, _item = _assessment_scenario(
            "ACCT-DVC-B", "SN-DVC-B-01", "DIET_CART"
        )

        book_payload = assess_shortfall_payload(
            "2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"
        )
        book_payload["exposure_variant"] = "BOOK_VALUE"
        book = validate_success(
            api.assess_shortfall(
                agreement["id"], book_payload, TEST_USERS["admin_headers"]
            )
        )
        validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("FEE_ONLY"),
                TEST_USERS["officer_headers"],
            )
        )
        assert read_agreement(agreement["id"])["status"] == "ACTIVE"

        risk_payload = assess_shortfall_payload(
            "2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"
        )
        risk_payload["exposure_variant"] = "REPLACEMENT_RISK"
        risk = validate_success(
            api.assess_shortfall(
                agreement["id"], risk_payload, TEST_USERS["admin_headers"]
            )
        )
        assert risk["recall_exposure_cents"] == 501600
        assert risk["recall_exposure_cents"] - book["recall_exposure_cents"] == 64800
        assert risk["assessed_fee_cents"] == 84853

        recalled = validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("RECALL"),
                TEST_USERS["officer_headers"],
            )
        )
        assert recalled["status"] == "RECALL_PENDING"
        assert read_unit(unit["id"])["status"] == "RECALL_STAGED"


class TestQuarterlyFeeRoundingOrder:
    def test_fee_rounds_each_quarter_before_summing_the_cents(self, api):
        """PRD §3.9: "The quarter's fee is that shortfall multiplied by the
        agreement's `shortfall_fee_cents_per_gallon` and **rounded half up to
        whole cents at this point**." The agreement's "`assessed_fee_cents` is
        the sum of the **already-rounded** per-quarter cent amounts."

        Design: Difficulty/combinatorial_formula/quarterly_shortfall_fee_round_then_sum_order_dependence
        """
        _outlet, agreement, _unit, _item = _assessment_scenario(
            "ACCT-CF-A", "SN-CF-A-01", "SPRITE_BIB"
        )

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN_ALT,
            )
        )

        # 49951 + 24951 + 9951 rounded per quarter, not 84852 rounded once.
        assert assessed["assessed_fee_cents"] == 84853
        assert assessed["assessed_fee_cents"] != 84852
        assert assessed["assessed_shortfall_gallons"] == pytest.approx(1697.03, abs=0.01)

    def test_assessment_defaults_the_exposure_variant_and_echoes_its_period(self, api):
        """PRD §3.9: "A successful assessment writes `assessed_shortfall_gallons`,
        `assessed_fee_cents`, `recall_exposure_cents`, the `exposure_variant`
        actually used, `assessment_period_start` and `assessment_period_end` from
        the submitted period bounds, and `shortfall_assessed_by_user_id` from the
        acting `X-User-ID`, and advances the agreement's `version` by one."

        Design: Difficulty/combinatorial_formula/quarterly_shortfall_fee_round_then_sum_order_dependence
        """
        _outlet, agreement, _unit, _item = _assessment_scenario(
            "ACCT-CF-A", "SN-CF-A-01", "SPRITE_BIB"
        )

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN_ALT,
            )
        )

        assert assessed["exposure_variant"] == "BOOK_VALUE"
        assert assessed["recall_exposure_cents"] == 436800
        assert assessed["assessment_period_start"].startswith("2026-01-01T00:00:00")
        assert assessed["assessment_period_end"].startswith("2026-10-01T00:00:00")
        assert assessed["shortfall_assessed_by_user_id"] == ADMIN_ALT["X-User-ID"]
        assert assessed["status"] == "SHORTFALL_REVIEW"
        assert assessed["version"] == 3


class TestSeverityScoreComposition:
    def test_no_pour_with_two_overdue_tasks_scores_eighty_five_and_grades_critical(
        self, api
    ):
        """PRD §3.8: "The outlet's overdue maintenance adds 5 points for each task
        counted in `overdue_task_count`, but that component is capped at 20
        points, so a fifth overdue task adds nothing further." A "score of 85 or
        more is `CRITICAL`".

        Design: Difficulty/combinatorial_formula/service_call_severity_multi_factor_score_with_capped_overdue_term
        """
        _outlet, unit = _severity_scenario()

        call = validate_success(
            api.create_service_call(
                create_service_call_payload(
                    unit["id"], "NO_POUR", "2026-08-10T00:00:00Z"
                ),
                TEST_USERS["admin_headers"],
            ),
            201,
        )

        # 60 base + 15 RESTRICTED + min(20, 5 * 2) overdue + 0 calibration.
        assert call["severity_score"] == 85
        assert call["severity"] == "CRITICAL"
        assert call["status"] == "OPEN"
        assert call["version"] == 1
        assert read_unit(unit["id"])["calibration_status"] == "UNVERIFIED"

    def test_symptom_weight_alone_separates_two_calls_by_thirty_points(self, api):
        """PRD §3.8: "The grade starts from the symptom's own weight: `NO_POUR` is
        worth 60 points, `LEAK` 55, `OFF_RATIO` 40, `CO2_LOW` 30 and `ICE_FAULT`
        25." Anything "below 60 is `ROUTINE`".

        Design: Difficulty/combinatorial_formula/service_call_severity_multi_factor_score_with_capped_overdue_term
        """
        _outlet, unit = _severity_scenario()

        high = validate_success(
            api.create_service_call(
                create_service_call_payload(
                    unit["id"], "NO_POUR", "2026-08-10T00:00:00Z"
                ),
                TEST_USERS["admin_headers"],
            ),
            201,
        )
        low = validate_success(
            api.create_service_call(
                create_service_call_payload(
                    unit["id"], "CO2_LOW", "2026-08-10T00:00:00Z"
                ),
                TEST_USERS["admin_headers"],
            ),
            201,
        )

        assert low["severity_score"] == 55
        assert low["severity"] == "ROUTINE"
        assert high["severity_score"] - low["severity_score"] == 30
