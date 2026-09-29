"""Formulas whose input dimensions multiply, and whose rounding order is itself part
of the specification.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    ChallengeType,
    EvidenceType,
    InterventionStatus,
    ResolutionDisposition,
    ReviewAction,
    SelectionBand,
    STATE_OFFICER_WA_ID,
    UnitType,
    ViolationStatus,
    assert_credit_pct,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    contribution_for,
    fixtures as fx,
    get_success_data,
    make_state_officer_headers,
    validate_paginated,
)


def _four_category_matrix(api) -> Dict[str, Any]:
    """A SMALL carrier at utilization tier 1.8 (exposure 18.0) with two scored
    reports, so all three denominator branches are exercised at one snapshot."""
    officer = make_state_officer_headers(STATE_OFFICER_WA_ID)
    fx.set_clock(api)
    carrier = fx.create_carrier(
        api,
        legal_name="Cascade Hauling Inc",
        average_power_units=10,
        annual_vmt=1200000,
    )
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="WA-D-40001", full_name="Kai Osborne"
    )
    codes = {
        BasicCategory.UNSAFE_DRIVING: fx.create_violation_code(
            api,
            code="392.2S",
            basic_category=BasicCategory.UNSAFE_DRIVING,
            severity_weight=5,
        ),
        BasicCategory.HOURS_OF_SERVICE: fx.create_violation_code(
            api,
            code="395.3A1",
            description="Driving beyond 11 hour limit",
            basic_category=BasicCategory.HOURS_OF_SERVICE,
            severity_weight=5,
        ),
        BasicCategory.VEHICLE_MAINTENANCE: fx.create_violation_code(
            api,
            code="393.9TS",
            description="Inoperative tail lamp",
            basic_category=BasicCategory.VEHICLE_MAINTENANCE,
            severity_weight=2,
        ),
        BasicCategory.DRIVER_FITNESS: fx.create_violation_code(
            api,
            code="391.11B5",
            description="Driver lacking valid medical certificate",
            basic_category=BasicCategory.DRIVER_FITNESS,
            severity_weight=4,
        ),
    }
    fx.create_thresholds_for_all_categories(
        api, carrier_segment="SMALL", measures=(1.0, 2.0, 4.0)
    )
    fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": codes[BasicCategory.UNSAFE_DRIVING]["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
            {
                "violation_code_id": codes[BasicCategory.HOURS_OF_SERVICE]["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
        ],
        officer,
        report_number="WA20260701A",
        inspection_state="WA",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": codes[BasicCategory.VEHICLE_MAINTENANCE]["id"],
                "unit_type": UnitType.VEHICLE,
            },
            {
                "violation_code_id": codes[BasicCategory.DRIVER_FITNESS]["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
        ],
        officer,
        report_number="WA20260701B",
        inspection_state="WA",
        inspection_level=1,
        selection_source="WEIGH_STATION",
        driver_id=driver["id"],
        inspection_start="2026-07-01T18:00:00Z",
        inspection_end="2026-07-01T19:00:00Z",
    )
    return {"carrier": carrier, "driver": driver, "codes": codes}


class TestDenominatorTierTimesCategoryBranch:
    def test_one_snapshot_carries_three_different_denominators(self, api):
        """PRD 3.4: "The `denominator_value` actually used depends on the category:
        for `VEHICLE_MAINTENANCE` it is `relevant_inspection_count` with a floor of
        1.0; for `HOURS_OF_SERVICE` it is the smaller of power-unit exposure and twice
        `relevant_inspection_count`, again with a floor of 1.0; for `UNSAFE_DRIVING`
        and `DRIVER_FITNESS` it is power-unit exposure."

        Design: Difficulty/combinatorial_formula/basic_measure_utilization_tier_times_category_denominator_matrix
        """
        scenario = _four_category_matrix(api)
        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert carrier["carrier_segment"] == "SMALL"
        assert_one_decimal(carrier["utilization_factor"], 1.8)

        expected = {
            BasicCategory.UNSAFE_DRIVING: (18.0, 0.833, 41.7, AlertStatus.CLEAR),
            BasicCategory.HOURS_OF_SERVICE: (4.0, 3.750, 78.1, AlertStatus.ALERT),
            BasicCategory.VEHICLE_MAINTENANCE: (2.0, 3.000, 72.5, AlertStatus.ALERT),
            BasicCategory.DRIVER_FITNESS: (18.0, 0.667, 33.4, AlertStatus.CLEAR),
        }
        for category, (denominator, measure, percentile, alert) in expected.items():
            row = fx.read_basic_score(api, carrier["id"], category)
            assert_one_decimal(row["denominator_value"], denominator)
            assert_measure(row["certified_measure"], measure)
            assert_one_decimal(row["percentile"], percentile)
            assert row["alert_status"] == alert, category

    def test_matrix_rolls_up_to_investigation_and_the_optional_band(self, api):
        """PRD 3.4: "Then `intervention_status` is `INVESTIGATION` when
        `open_alert_count` is 2 or more; `INVESTIGATION` also when `max_percentile` is
        present and at or above the investigation bar; `WARNING_LETTER` when neither of
        those holds but `open_alert_count` is at least 1; and `NONE` otherwise."

        Design: Difficulty/combinatorial_formula/basic_measure_utilization_tier_times_category_denominator_matrix
        """
        scenario = _four_category_matrix(api)
        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert carrier["open_alert_count"] == 2
        assert_one_decimal(carrier["max_percentile"], 78.1)
        assert carrier["intervention_status"] == InterventionStatus.INVESTIGATION

        risk = fx.read_screening_risk(api, carrier["id"])
        assert_two_decimals(contribution_for(risk, BasicCategory.UNSAFE_DRIVING), 14.60)
        assert_two_decimals(contribution_for(risk, BasicCategory.HOURS_OF_SERVICE), 23.43)
        assert_two_decimals(
            contribution_for(risk, BasicCategory.VEHICLE_MAINTENANCE), 18.13
        )
        assert_two_decimals(contribution_for(risk, BasicCategory.DRIVER_FITNESS), 3.34)
        assert_one_decimal(risk["iss_pre_credit_value"], 59.5)
        assert_one_decimal(risk["iss_value"], 59.5)
        assert risk["selection_band"] == SelectionBand.OPTIONAL
        assert_one_decimal(carrier["iss_pre_credit_value"], 59.5)
        assert_one_decimal(carrier["iss_value"], 59.5)
        assert carrier["selection_band"] == SelectionBand.OPTIONAL


def _half_cent_contributions(api) -> Dict[str, Any]:
    """Thresholds picked so both weighted contributions land on a half-cent, which is
    where per-category rounding and end-of-chain rounding disagree."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code_ud = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    code_vm = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=BasicCategory.VEHICLE_MAINTENANCE,
        severity_weight=2,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=1.0225,
        measure_at_p65=2.045,
        measure_at_p80=4.09,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.VEHICLE_MAINTENANCE,
        carrier_segment="MEDIUM",
        measure_at_p50=7.4075,
        measure_at_p65=14.815,
        measure_at_p80=29.63,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": code_ud["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code_ud["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code_vm["id"], "unit_type": UnitType.VEHICLE},
        ],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {"carrier": carrier, "report": report, "violations": rows}


class TestContributionsRoundedBeforeSummation:
    def test_each_contribution_is_rounded_to_two_decimals_first(self, api):
        """PRD 3.5: "A category's contribution is 0.00 whenever that row's
        `alert_status` is `NOT_ENOUGH_DATA` or its `percentile` is empty; otherwise it
        is the row's `percentile` multiplied by the category's weight, **rounded half
        up to 2 decimal places at this point**."

        Design: Difficulty/combinatorial_formula/iss_contribution_rounded_per_category_before_summation
        """
        scenario = _half_cent_contributions(api)
        carrier_id = scenario["carrier"]["id"]

        unsafe = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(unsafe["denominator_value"], 30.0)
        assert_measure(unsafe["certified_measure"], 1.000)
        assert_one_decimal(unsafe["percentile"], 48.9)
        assert unsafe["alert_status"] == AlertStatus.CLEAR

        vehicle = fx.read_basic_score(api, carrier_id, BasicCategory.VEHICLE_MAINTENANCE)
        assert_one_decimal(vehicle["denominator_value"], 1.0)
        assert_measure(vehicle["certified_measure"], 6.000)
        assert_one_decimal(vehicle["percentile"], 40.5)
        assert vehicle["alert_status"] == AlertStatus.CLEAR

        risk = fx.read_screening_risk(api, carrier_id)
        assert_two_decimals(contribution_for(risk, BasicCategory.UNSAFE_DRIVING), 17.12)
        assert_two_decimals(
            contribution_for(risk, BasicCategory.VEHICLE_MAINTENANCE), 10.13
        )
        assert_two_decimals(contribution_for(risk, BasicCategory.HOURS_OF_SERVICE), 0.00)
        assert_two_decimals(contribution_for(risk, BasicCategory.DRIVER_FITNESS), 0.00)

    def test_summing_unrounded_products_would_give_a_different_value(self, api):
        """PRD 3.5: "The raw figure is the sum of the four already-rounded
        contributions. Summing the unrounded products and rounding once at the end
        yields a different value and is wrong."

        Design: Difficulty/combinatorial_formula/iss_contribution_rounded_per_category_before_summation
        """
        scenario = _half_cent_contributions(api)
        carrier = fx.read_carrier(api, scenario["carrier"]["id"])

        assert_one_decimal(carrier["iss_pre_credit_value"], 27.3)
        assert carrier["iss_pre_credit_value"] != 27.2
        assert_credit_pct(carrier["data_quality_credit_pct"], 0.0)
        assert_one_decimal(carrier["iss_value"], 27.3)
        assert carrier["selection_band"] == SelectionBand.PASS
        assert carrier["open_alert_count"] == 0
        assert carrier["intervention_status"] == InterventionStatus.NONE


def _accepted_code_correction(api) -> Dict[str, Any]:
    """A carrier whose pre-credit screening value lands at 50.6 with one accepted
    challenge on file, so the credit tier is decided at the boundary."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code_ud = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    code_ud_b = fx.create_violation_code(
        api,
        code="392.2P",
        description="Improper passing",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    code_hos = fx.create_violation_code(
        api,
        code="395.3A1",
        description="Driving beyond 11 hour limit",
        basic_category=BasicCategory.HOURS_OF_SERVICE,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.1,
        measure_at_p65=0.2,
        measure_at_p80=0.4,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.HOURS_OF_SERVICE,
        carrier_segment="MEDIUM",
        measure_at_p50=7.0,
        measure_at_p65=10.75,
        measure_at_p80=21.5,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": code_ud["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code_ud["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code_ud["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code_hos["id"], "unit_type": UnitType.VEHICLE},
        ],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.build_challenge_under_review(
        api,
        carrier["id"],
        report["id"],
        evidence_type=EvidenceType.PHOTO,
        challenge_type=ChallengeType.INCORRECT_VIOLATION_CODE,
        narrative="Third entry was an improper-passing event, not a speeding event.",
        target_violation_id=rows[2]["id"],
        asserted_correct_violation_code_id=code_ud_b["id"],
    )
    fx.review_challenge(
        api,
        challenge["id"],
        ReviewAction.RESOLVE_ACCEPT,
    )
    return {
        "carrier": carrier,
        "corrected_code": code_ud_b,
        "report": report,
        "violations": rows,
        "challenge": challenge,
    }


class TestCreditTierKeyedOnPreCreditValue:
    def test_credit_tier_comes_from_the_pre_credit_value(self, api):
        """PRD 3.5: "The credit tier is keyed on `iss_pre_credit_value` and on nothing
        else: 0.06 when `iss_pre_credit_value` is 75.0 or above, 0.04 when it is 50.0
        or above but below 75.0, and 0.02 in all other cases."

        Design: Difficulty/combinatorial_formula/data_quality_credit_tier_keyed_on_pre_credit_iss_only
        """
        scenario = _accepted_code_correction(api)
        carrier = fx.read_carrier(api, scenario["carrier"]["id"])

        assert carrier["accepted_challenge_count_24mo"] == 1
        assert carrier["resolved_challenge_count_24mo"] == 1
        assert carrier["challenge_quota_used"] == 1
        assert_one_decimal(carrier["iss_pre_credit_value"], 50.6)
        assert_credit_pct(carrier["data_quality_credit_pct"], 0.0400)
        assert_one_decimal(carrier["iss_value"], 48.6)
        assert carrier["iss_value"] != 49.6
        assert carrier["selection_band"] == SelectionBand.PASS

        risk = fx.read_screening_risk(api, scenario["carrier"]["id"])
        assert_one_decimal(risk["iss_pre_credit_value"], 50.6)
        assert_credit_pct(risk["data_quality_credit_pct"], 0.0400)
        assert_one_decimal(risk["iss_value"], 48.6)
        assert risk["selection_band"] == SelectionBand.PASS

    def test_acceptance_recodes_the_target_and_writes_the_amendment(self, api):
        """PRD 3.6: "It sets the target violation's `effective_violation_code_id` to
        the `asserted_correct_violation_code_id`, moves the violation's `status` to
        `RECODED`, re-pins `code_weight_snapshot`, `oos_add_on_snapshot` and
        `pinned_violation_code_version` from the new code, and recomputes
        `time_weighted_severity`."

        Design: Difficulty/combinatorial_formula/data_quality_credit_tier_keyed_on_pre_credit_iss_only
        """
        scenario = _accepted_code_correction(api)
        carrier_id = scenario["carrier"]["id"]
        target_id = scenario["violations"][2]["id"]

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == "RESOLVED_ACCEPTED"
        assert challenge["resolution_disposition"] == ResolutionDisposition.CODE_CORRECTED

        target = fx.read_violation(api, target_id)
        assert target["status"] == ViolationStatus.RECODED
        assert target["effective_violation_code_id"] == scenario["corrected_code"]["id"]
        assert target["code_weight_snapshot"] == 5
        assert_one_decimal(target["time_weighted_severity"], 15.0)
        assert target["under_challenge"] is False

        amendments, meta = validate_paginated(
            api.list_report_amendments(
                fx.AUDITOR, {"source_challenge_id": scenario["challenge"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert amendments[0]["amendment_type"] == "VIOLATION_CODE_CORRECTION"
        assert amendments[0]["target_violation_id"] == target_id
        assert (
            amendments[0]["corrected_violation_code_id"]
            == scenario["corrected_code"]["id"]
        )

        unsafe = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(unsafe["total_time_weighted_severity"], 45.0)
        assert_measure(unsafe["certified_measure"], 1.500)
        assert_one_decimal(unsafe["percentile"], 100.0)
        assert unsafe["alert_status"] == AlertStatus.ALERT

        hos = fx.read_basic_score(api, carrier_id, BasicCategory.HOURS_OF_SERVICE)
        assert_measure(hos["certified_measure"], 7.500)
        assert_one_decimal(hos["percentile"], 52.0)

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 1
        assert_one_decimal(carrier["max_percentile"], 100.0)
        assert carrier["intervention_status"] == InterventionStatus.INVESTIGATION
