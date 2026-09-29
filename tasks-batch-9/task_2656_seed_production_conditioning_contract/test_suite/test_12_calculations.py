"""Derived figures pinned at their clamps, their tier bounds and their rounding steps."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    THRESHOLDS,
    assert_instant_equals,
    assert_lot_mass_conserved,
    bagged_lot_state,
    certify_cleanout,
    complete_run,
    compute_settlement,
    create_field_inspection_payload,
    create_harvest_event_payload,
    create_production_contract_payload,
    draw_sample,
    get_success_data,
    harvested_lot_state,
    issue_tag,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_field_officer_headers,
    make_grower,
    make_grower_headers,
    make_harvest_equipment,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    passed_lot_state,
    plan_run,
    post_results,
    record_inspection,
    run_stage,
    set_clock,
    sign_contract_payload,
    validate_error,
    validate_success,
)

ZERO_DOCKAGE_MOISTURE_PCT = 11.0
ZERO_DOCKAGE_PROVISIONAL_KG = 37720.000
ZERO_DOCKAGE_PROVISIONAL_UNITS = 1508.80
CLEANING_SHRINK_KG = 3200.0
CLEANED_DOCKAGE_PCT = 7.80
TIER_BOUND_PRICE_CENTS = 1836
CAPPED_PRICE_CENTS = 1998
BASE_MOISTURE_PCT = 12.0


class TestProvisionalUnitsAtOrBelowBaseMoisture:
    def test_seed_drier_than_base_takes_no_dockage_instead_of_a_negative_one(self, api):
        """The floor at zero is what stops dry seed from earning a moisture bonus.

        PRD: "First, a book moisture dockage percentage is derived as the intake moisture percentage
        minus a 12.0 percent base moisture, multiplied by a shrink factor of 1.5, and floored at zero
        so that seed at or below base moisture takes no dockage; that value is stored on the harvest
        event as `moisture_dockage_pct`."

        PRD: "Next, `provisional_clean_kg` is the gross field weight reduced by the moisture dockage
        percentage and then reduced again by the variety's book `estimated_conditioning_shrink_pct`,
        each reduction applied as a proportional factor of one minus the percentage divided by one
        hundred, with the result rounded half-up to three decimal places."

        PRD: "Finally, `provisional_clean_units` is that provisional clean mass divided by the clean
        seed unit of 25.0 kilograms, rounded half-up to two decimal places."

        Design: Corner/calculations/provisional_units_moisture_below_base_takes_zero_dockage
        """
        state = harvested_lot_state(
            api, harvest_overrides={"moisture_pct": ZERO_DOCKAGE_MOISTURE_PCT}
        )
        event = state["harvest_event"]

        assert event["moisture_dockage_pct"] == pytest.approx(0.00, abs=0.001)
        assert event["provisional_clean_kg"] == pytest.approx(ZERO_DOCKAGE_PROVISIONAL_KG, abs=0.001)
        assert event["provisional_clean_units"] == pytest.approx(
            ZERO_DOCKAGE_PROVISIONAL_UNITS, abs=0.01
        )

        lot = state["seed_lot"]
        assert lot["provisional_clean_units"] == pytest.approx(
            ZERO_DOCKAGE_PROVISIONAL_UNITS, abs=0.01
        )
        assert lot["intake_moisture_pct"] == pytest.approx(ZERO_DOCKAGE_MOISTURE_PCT, abs=0.01)
        assert lot["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)

        assert state["contract"]["provisional_clean_units_total"] == pytest.approx(
            ZERO_DOCKAGE_PROVISIONAL_UNITS, abs=0.01
        )


class TestDockagePercentagePrecision:
    def test_the_cleaning_pass_leaves_a_two_decimal_dockage_over_exact_masses(self, api):
        """The two mass fields stay exact; only the derived percentage is rounded.

        PRD: "On success the run advances `PLANNED → COMPLETED`, its `shrink_kg` is set to the input
        mass minus the output mass, the lot's `current_kg` is replaced by the output mass, the run's
        shrink is added to the lot's `cumulative_shrink_kg`, and the lot's `dockage_pct` is recomputed
        as the cumulative shrink divided by the lot's `gross_kg`, multiplied by one hundred, rounded
        half-up to two decimal places."

        PRD: "Neither the lot's mass presently held nor its cumulative shrink is ever rounded; only
        the derived dockage percentage is."

        Design: Corner/calculations/dockage_pct_precision_two_decimals
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        planned = plan_run(api, lot_id, state["line"]["id"], "CLEANING")
        completed = complete_run(api, planned["id"], TEST_DEFAULTS["CLEANING_OUTPUT_KG"])
        assert completed["status"] == "COMPLETED"
        assert completed["shrink_kg"] == pytest.approx(CLEANING_SHRINK_KG, abs=0.001)

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["CLEANING_OUTPUT_KG"], abs=0.001)
        assert lot["cumulative_shrink_kg"] == pytest.approx(CLEANING_SHRINK_KG, abs=0.001)
        assert lot["dockage_pct"] == pytest.approx(CLEANED_DOCKAGE_PCT, abs=0.001)
        assert lot["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert_lot_mass_conserved(lot)
        assert lot["conditioning_status"] == "CLEANED"
        assert lot["final_clean_units"] is None


class TestQualityTierBoundsAreInclusive:
    def test_measurements_sitting_exactly_on_three_tier_bounds_take_the_better_tier(self, api):
        """Germination 95.0, purity 98.0 and 10 weed seeds each land on their own bound.

        PRD: "The germination adjustment is a bonus of 6.0 percent when the germination percentage is
        at least 95.0, otherwise a bonus of 2.0 percent when it is at least 90.0, and otherwise 0.0
        percent."

        PRD: "The purity adjustment is a bonus of 2.0 percent when the purity percentage is at least
        99.5, otherwise 0.0 percent when it is at least 98.0, and otherwise a penalty of 4.0 percent."

        PRD: "The weed penalty is 0.0 percent for a perfectly clean report of zero weed seeds per
        kilogram, otherwise a penalty of 3.0 percent at up to and including 10 weed seeds per
        kilogram, and otherwise a penalty of 9.0 percent up to and including 30."

        PRD: "Every one of those tier boundaries is an inclusive lower bound."

        PRD: "Finally, `adjusted_price_per_unit_cents` is the contract's `base_price_per_unit_cents`
        scaled by one plus the clamped adjustment percentage divided by one hundred, rounded half-up
        to whole cents."

        Design: Corner/calculations/adjusted_price_tier_boundaries_are_inclusive
        """
        state = passed_lot_state(
            api,
            result_overrides={
                "germination_pct": 95.0,
                "purity_pct": 98.0,
                "inert_pct": 1.5,
                "weed_seed_count_per_kg": 10,
            },
        )
        assert state["sample"]["result"] == "PASS"

        lot = state["seed_lot"]
        assert lot["adjusted_price_per_unit_cents"] == TIER_BOUND_PRICE_CENTS
        assert lot["germination_pct"] == pytest.approx(95.0, abs=0.01)
        assert lot["purity_pct"] == pytest.approx(98.0, abs=0.01)
        assert lot["weed_seed_count_per_kg"] == 10
        assert lot["certification_status"] == "PASSED"
        assert_instant_equals(lot["germination_valid_until"], GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"])


class TestQualityAdjustmentAtTheCapBoundary:
    def test_an_adjustment_landing_exactly_on_the_ceiling_is_not_trimmed(self, api):
        """The best tiers plus a zero moisture dockage sum to the ceiling itself.

        PRD: "That raw adjustment is then clamped into a band whose ceiling is a bonus of 8.0 percent
        and whose floor is a penalty of 35.0 percent — first raised to the floor if it sits below it,
        then lowered to the ceiling if it sits above it."

        PRD: "A fourth term is a moisture dockage percentage, derived from the lot's
        `intake_moisture_pct` — the moisture measured at harvest intake, inherited by the lot and
        never re-derived from any later sample — as that intake moisture minus a 12.0 percent base
        moisture, multiplied by a factor of 1.5, floored at zero."

        Design: Corner/calculations/adjusted_price_clamped_at_cap_boundary
        """
        state = passed_lot_state(api, harvest_overrides={"moisture_pct": BASE_MOISTURE_PCT})

        assert state["harvest_event"]["moisture_dockage_pct"] == pytest.approx(0.00, abs=0.001)

        lot = state["seed_lot"]
        assert lot["intake_moisture_pct"] == pytest.approx(BASE_MOISTURE_PCT, abs=0.01)
        assert THRESHOLDS["ADJ_CAP_PCT"] == 8.0
        assert lot["adjusted_price_per_unit_cents"] == CAPPED_PRICE_CENTS
        assert lot["germination_pct"] == pytest.approx(TEST_DEFAULTS["RESULT_GERMINATION_PCT"], abs=0.01)
        assert lot["purity_pct"] == pytest.approx(TEST_DEFAULTS["RESULT_PURITY_PCT"], abs=0.01)
        assert lot["weed_seed_count_per_kg"] == TEST_DEFAULTS["RESULT_WEED_SEED_COUNT_PER_KG"]

        assert lot["provisional_clean_units"] == pytest.approx(
            ZERO_DOCKAGE_PROVISIONAL_UNITS, abs=0.01
        )
        assert lot["final_clean_units"] == pytest.approx(GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01)


SECOND_LOT_GROSS_KG = 28000.0
SECOND_LOT_BAGGED_KG = 23501.25
SECOND_LOT_FINAL_UNITS = 940.05
SECOND_HARVEST_WINDOW_START = "2026-09-11T08:00:00Z"
SECOND_HARVEST_WINDOW_END = "2026-09-11T18:00:00Z"
SECOND_LOT_CLEANING_WINDOW = ("2026-09-13T11:00:00Z", "2026-09-13T15:00:00Z")
SECOND_LOT_SIZING_WINDOW = ("2026-09-13T16:00:00Z", "2026-09-13T20:00:00Z")
SECOND_LOT_BAGGING_WINDOW = ("2026-09-13T20:00:00Z", "2026-09-13T23:00:00Z")
SECOND_LOT_CLEANING_OUTPUT_KG = 25800.0
SECOND_LOT_SIZING_OUTPUT_KG = 24500.0


def _contract_with_a_tagged_and_an_untagged_lot(api):
    """One contract, two bagged and PASSED lots, only the first one tagged."""
    state = bagged_lot_state(api)
    contract_id = state["contract"]["id"]
    line_id = state["line"]["id"]

    second_combine = make_harvest_equipment(
        api, equipment_code=TEST_DEFAULTS["SECOND_EQUIPMENT_CODE"]
    )
    certify_cleanout(api, second_combine["id"], state["variety"]["id"])
    second_event = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(
                contract_id,
                second_combine["id"],
                window_start=SECOND_HARVEST_WINDOW_START,
                window_end=SECOND_HARVEST_WINDOW_END,
                gross_weight_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )
    )
    second_lot_id = second_event["seed_lot_id"]

    run_stage(
        api, second_lot_id, line_id, "CLEANING", SECOND_LOT_CLEANING_OUTPUT_KG,
        window_start=SECOND_LOT_CLEANING_WINDOW[0],
        window_end=SECOND_LOT_CLEANING_WINDOW[1],
        input_kg=SECOND_LOT_GROSS_KG,
    )
    run_stage(
        api, second_lot_id, line_id, "SIZING", SECOND_LOT_SIZING_OUTPUT_KG,
        window_start=SECOND_LOT_SIZING_WINDOW[0],
        window_end=SECOND_LOT_SIZING_WINDOW[1],
        input_kg=SECOND_LOT_CLEANING_OUTPUT_KG,
    )
    run_stage(
        api, second_lot_id, line_id, "BAGGING", SECOND_LOT_BAGGED_KG,
        window_start=SECOND_LOT_BAGGING_WINDOW[0],
        window_end=SECOND_LOT_BAGGING_WINDOW[1],
        input_kg=SECOND_LOT_SIZING_OUTPUT_KG,
    )

    first_sample = post_results(api, draw_sample(api, state["seed_lot"]["id"])["id"])
    post_results(api, draw_sample(api, second_lot_id)["id"])
    tag = issue_tag(api, state["seed_lot"]["id"], first_sample["id"])

    return {
        "contract_id": contract_id,
        "first_lot_id": state["seed_lot"]["id"],
        "second_lot_id": second_lot_id,
        "tag": tag,
    }


class TestSettlementLineSelection:
    def test_a_passed_but_untagged_lot_contributes_nothing_to_the_rollup(self, api):
        """Both lots are priced, yet only the tagged one becomes a settlement line.

        PRD: "The rollup selects its lines by a narrow filter: every seed lot of that contract whose
        `certification_status` is `TAGGED` and whose `final_clean_units` is not null, ordered by
        `created_at` ascending with `lot_code` ascending as the tie-break."

        PRD: "Lots sitting in `UNSAMPLED`, `SAMPLED`, `PASSED`, `FAILED` or `RETEST_DUE` are
        excluded, and so are lots whose tags have all been voided, because voiding the last tag
        returned them to `PASSED`."

        PRD: "The settlement then records `line_count` as the number of lines folded in,
        `settled_units_total` as the sum of the lines' clean unit figures rounded half-up to two
        decimal places, `gross_payable_cents` as the sum of the already-rounded line gross amounts,
        and `conditioning_charges_cents` as the sum of the already-rounded line charges."

        Design: Corner/calculations/settlement_excludes_untagged_lots_from_lines
        """
        state = _contract_with_a_tagged_and_an_untagged_lot(api)

        settlement = compute_settlement(api, state["contract_id"])
        assert settlement["line_count"] == 1
        assert settlement["settled_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )
        assert settlement["gross_payable_cents"] == GOLDEN_FIGURES["GROSS_PAYABLE_CENTS"]
        assert settlement["conditioning_charges_cents"] == GOLDEN_FIGURES["CONDITIONING_CHARGES_CENTS"]
        assert settlement["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]

        headers = make_conditioning_manager_headers()
        second_lot = get_success_data(api.get_seed_lot(state["second_lot_id"], headers))
        assert second_lot["certification_status"] == "PASSED"
        assert second_lot["final_clean_units"] == pytest.approx(SECOND_LOT_FINAL_UNITS, abs=0.01)
        assert second_lot["adjusted_price_per_unit_cents"] == GOLDEN_FIGURES[
            "ADJUSTED_PRICE_PER_UNIT_CENTS"
        ]

        first_lot = get_success_data(api.get_seed_lot(state["first_lot_id"], headers))
        assert first_lot["certification_status"] == "TAGGED"
        assert first_lot["final_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        contract = get_success_data(
            api.get_production_contract(state["contract_id"], make_program_admin_headers())
        )
        assert contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )


FAILING_OFF_TYPE_PLANTS = 80
FAILING_OFF_TYPE_RATE_PER_10000 = 40.00
FIELD_CODES = ("F-A", "F-B", "F-C", "F-D", "F-E")
INSPECTING_OFFICERS = ("fo-1", "fo-1", "fo-2", "fo-2")
STANDING_AFTER_EACH_FLAG = ("GOOD_STANDING", "WATCH", "WATCH", "SUSPENDED")


def _one_grower_with_five_contracts(api):
    """Four signed contracts about to fail inspection plus a fifth left in DRAFT."""
    variety = make_variety(api)
    grower = make_grower(api)
    contracts = []
    for field_code in FIELD_CODES:
        field = make_production_field(api, grower["id"], field_code=field_code)
        make_field_history_record(api, field["id"])
        contracts.append(
            get_success_data(
                api.create_production_contract(
                    create_production_contract_payload(grower["id"], variety["id"], field["id"]),
                    make_program_admin_headers(),
                )
            )
        )
    for contract in contracts[:4]:
        get_success_data(
            api.offer_production_contract(contract["id"], {}, make_program_admin_headers())
        )
        get_success_data(
            api.sign_production_contract(
                contract["id"], sign_contract_payload(), make_grower_headers(grower["id"])
            )
        )
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    return grower, contracts


class TestGrowerStandingThresholds:
    def test_the_second_flag_reaches_watch_and_the_fourth_reaches_suspended(self, api):
        """Both standing thresholds are inclusive, so the counter alone drives the ladder.

        PRD: "On the second hop, because the contract entered one of those two conditions, the
        grower's `compliance_flag_count` increments by 1 and the grower's `version` increments by 1."

        PRD: "On the third hop, because the counter moved, the grower's `status` is re-derived from
        the counter alone: a count of at least 4 sets the standing to `SUSPENDED`, otherwise a count
        of at least 2 sets it to `WATCH`, and otherwise it remains `GOOD_STANDING`."

        PRD: "Both thresholds are inclusive, the counter is monotonically increasing, and it is never
        decremented — a rogueing round that is later verified successfully does not clear the flag it
        raised."

        PRD: "`off_type_rate_per_10000` is the off-type plant count divided by the sampled plant
        count, multiplied by ten thousand."

        Design: Corner/calculations/grower_standing_threshold_suspends_at_four_flags
        """
        grower, contracts = _one_grower_with_five_contracts(api)

        for index, contract in enumerate(contracts[:4]):
            inspection = validate_success(
                api.create_field_inspection(
                    create_field_inspection_payload(
                        contract["id"], off_type_plants=FAILING_OFF_TYPE_PLANTS
                    ),
                    make_field_officer_headers(INSPECTING_OFFICERS[index]),
                ),
                201,
            )
            assert inspection["off_type_rate_per_10000"] == pytest.approx(
                FAILING_OFF_TYPE_RATE_PER_10000, abs=0.01
            )
            assert inspection["outcome"] == "FAILED"

            inspected = get_success_data(
                api.get_production_contract(contract["id"], make_program_admin_headers())
            )
            assert inspected["status"] == "REJECTED"

            standing = get_success_data(api.get_grower(grower["id"], make_program_admin_headers()))
            assert standing["compliance_flag_count"] == index + 1
            assert standing["status"] == STANDING_AFTER_EACH_FLAG[index]

    def test_a_suspended_standing_blocks_the_fifth_contracts_offer(self, api):
        """The suspension is the gate the fifth contract now runs into.

        PRD: "The grower's standing must not be `SUSPENDED`, or the offer is refused with
        `ERR_GROWER_SUSPENDED`; standings of `GOOD_STANDING` and `WATCH` both permit an offer."

        Design: Corner/calculations/grower_standing_threshold_suspends_at_four_flags
        """
        grower, contracts = _one_grower_with_five_contracts(api)
        for index, contract in enumerate(contracts[:4]):
            record_inspection(
                api,
                contract["id"],
                inspector_user_id=INSPECTING_OFFICERS[index],
                off_type_plants=FAILING_OFF_TYPE_PLANTS,
            )

        suspended = get_success_data(api.get_grower(grower["id"], make_program_admin_headers()))
        assert suspended["compliance_flag_count"] == THRESHOLDS["SUSPEND_AT_FLAGS"]
        assert suspended["status"] == "SUSPENDED"

        response = api.offer_production_contract(
            contracts[4]["id"], {}, make_program_admin_headers()
        )
        validate_error(response, "ERR_GROWER_SUSPENDED", 409)

        fifth = get_success_data(
            api.get_production_contract(contracts[4]["id"], make_program_admin_headers())
        )
        assert fifth["status"] == "DRAFT"
