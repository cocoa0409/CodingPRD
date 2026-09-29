"""Field, cross-entity and temporal rules, each refused at its own declared error."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_instant_equals,
    bagged_lot_state,
    certify_cleanout,
    complete_conditioning_run_payload,
    create_carryover_payload,
    create_certification_tag_payload,
    create_conditioning_run_payload,
    create_harvest_event_payload,
    create_production_contract_payload,
    draft_contract_state,
    draw_sample,
    get_success_data,
    harvested_lot_state,
    inspection_passed_contract_state,
    issue_tag,
    lot_sample_results_payload,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_field_officer_headers,
    make_grower,
    make_grower_headers,
    make_harvest_equipment,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    passed_lot_state,
    plan_run,
    planted_contract_state,
    post_results,
    record_inspection,
    reverse_conditioning_run_payload,
    rogueing_declaration_payload,
    rogueing_verification_payload,
    set_clock,
    tagged_lot_state,
    validate_error,
    validate_paginated,
    validate_success,
)

OVERSIZED_CONTRACTED_ACRES = 400.0
MISMATCHED_INPUT_KG = 40000.0
OVERSIZED_OUTPUT_KG = 42000.0
CLEANING_SHRINK_KG = 3200.0
CLEANED_DOCKAGE_PCT = 7.80


class TestContractedAcresAgainstFieldAcres:
    def test_more_acres_than_the_field_holds_is_refused_and_the_exact_acreage_is_not(self, api):
        """The comparison is an inclusive ceiling, so the field's own acreage passes.

        PRD: "The commercial terms follow: `contracted_acres` must be greater than zero and may not
        exceed the field's `acres`, or the draft is rejected with `ERR_CONTRACTED_ACRES_EXCEED_FIELD`;
        `base_price_per_unit_cents` must be greater than zero; `conditioning_charge_per_unit_cents`,
        the charge deducted per clean seed unit, may be zero but not negative; and
        `advance_total_cents`, the pre-season cash advance extended to the grower, may likewise be
        zero but not negative."

        Design: Corner/validations/contracted_acres_exceeding_field_rejected
        """
        variety = make_variety(api)
        grower = make_grower(api)
        field = make_production_field(api, grower["id"])
        assert field["acres"] == pytest.approx(TEST_DEFAULTS["ACRES"], abs=0.01)

        response = api.create_production_contract(
            create_production_contract_payload(
                grower["id"],
                variety["id"],
                field["id"],
                contracted_acres=OVERSIZED_CONTRACTED_ACRES,
            ),
            make_program_admin_headers(),
        )
        validate_error(response, "ERR_CONTRACTED_ACRES_EXCEED_FIELD", 422)

        accepted = validate_success(
            api.create_production_contract(
                create_production_contract_payload(
                    grower["id"],
                    variety["id"],
                    field["id"],
                    contracted_acres=TEST_DEFAULTS["ACRES"],
                ),
                make_program_admin_headers(),
            ),
            201,
        )
        assert accepted["contracted_acres"] == pytest.approx(TEST_DEFAULTS["ACRES"], abs=0.01)

        _contracts, meta = validate_paginated(
            api.list_production_contracts(
                make_program_admin_headers(), {"production_field_id": field["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestRunInputMassAgainstLotMass:
    def test_a_run_declaring_less_mass_than_the_lot_holds_is_refused(self, api):
        """The mass ledger is auditable only because the declared input is pinned.

        PRD: "The declared input mass is not a free parameter: `input_kg` must equal the lot's
        `current_kg` as it stands at request time, exact to two decimal places, or the request is
        refused with `ERR_INPUT_MASS_MISMATCH`."

        Design: Corner/validations/run_input_mass_mismatch_rejected
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        response = api.create_conditioning_run(
            create_conditioning_run_payload(
                lot_id, state["line"]["id"], "CLEANING", input_kg=MISMATCHED_INPUT_KG
            ),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_INPUT_MASS_MISMATCH", 422)

        _runs, meta = validate_paginated(
            api.list_conditioning_runs(make_conditioning_manager_headers(), {"seed_lot_id": lot_id})
        )
        assert meta["total_count"] == 0

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert lot["conditioning_status"] == "RAW"


class TestRunStageLadder:
    def test_skipping_the_cleaning_rung_is_refused_even_with_a_perfect_payload(self, api):
        """Mass, window and line are all valid; only the requested rung is wrong.

        PRD: "The requested stage must be the immediate successor of the lot's current conditioning
        status: a `RAW` lot may only be sent to `CLEANING`, a `CLEANED` lot only to `SIZING`, a
        `SIZED` lot to `TREATING`, and a `TREATED` lot to `BAGGING`."

        PRD: "Any stage that is not the immediate successor under these rules is refused with
        `ERR_STAGE_OUT_OF_ORDER`."

        Design: Corner/validations/run_stage_out_of_order_rejected
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        response = api.create_conditioning_run(
            create_conditioning_run_payload(lot_id, state["line"]["id"], "SIZING"),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_STAGE_OUT_OF_ORDER", 409)

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["conditioning_status"] == "RAW"
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)

        _runs, meta = validate_paginated(
            api.list_conditioning_runs(
                make_conditioning_manager_headers(), {"seed_lot_id": lot_id, "stage": "SIZING"}
            )
        )
        assert meta["total_count"] == 0


class TestRunCompletionOutputCeiling:
    def test_output_heavier_than_the_input_is_refused_with_no_negative_shrink(self, api):
        """A run cannot create mass, so the completion is refused before any ledger moves.

        PRD: "The run must be in `PLANNED` status, or the request is refused with
        `ERR_INVALID_RUN_STATE`; the run's `window_end` must be at or before the current logical clock
        instant, or it is refused with `ERR_RUN_WINDOW_NOT_ELAPSED`; and the output mass must be at
        least zero and no greater than the run's `input_kg`, or it is refused with
        `ERR_OUTPUT_EXCEEDS_INPUT`."

        Design: Corner/validations/run_completion_output_exceeding_input_rejected
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        planned = plan_run(api, lot_id, state["line"]["id"], "CLEANING")

        response = api.complete_conditioning_run(
            planned["id"],
            complete_conditioning_run_payload(OVERSIZED_OUTPUT_KG),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_OUTPUT_EXCEEDS_INPUT", 422)

        run = get_success_data(
            api.get_conditioning_run(planned["id"], make_conditioning_manager_headers())
        )
        assert run["status"] == "PLANNED"
        assert run["shrink_kg"] is None

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert lot["cumulative_shrink_kg"] == pytest.approx(0.0, abs=0.001)
        assert lot["conditioning_status"] == "RAW"


def _harvest_ready_contract(api, cleanout_overrides=None, harvest_clock=None):
    """An INSPECTION_PASSED contract with a combine cleaned for its own variety."""
    state = inspection_passed_contract_state(api)
    state["equipment"] = make_harvest_equipment(api)
    if harvest_clock is not None:
        set_clock(api, harvest_clock)
    state["equipment"] = certify_cleanout(
        api, state["equipment"]["id"], state["variety"]["id"], **(cleanout_overrides or {})
    )
    return state


class TestHarvestWindowWellFormedness:
    def test_a_zero_length_window_is_refused_before_any_calendar_rule_runs(self, api):
        """Identical bounds fail the strict ordering rule, not the conflict scan.

        PRD: "The window must be well-formed, with `window_start` strictly before `window_end`, or the
        request is refused with `ERR_INVALID_WINDOW`, and it must already have elapsed — a
        `window_end` after the current logical clock instant is refused with
        `ERR_HARVEST_WINDOW_NOT_ELAPSED`."

        Design: Corner/validations/harvest_window_with_equal_bounds_rejected
        """
        state = _harvest_ready_contract(api, harvest_clock=TEST_DEFAULTS["HARVEST_CLOCK"])

        response = api.create_harvest_event(
            create_harvest_event_payload(
                state["contract"]["id"],
                state["equipment"]["id"],
                window_end=TEST_DEFAULTS["HARVEST_WINDOW_START"],
            ),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_INVALID_WINDOW", 422)

        _events, meta = validate_paginated(
            api.list_harvest_events(
                make_conditioning_manager_headers(),
                {"production_contract_id": state["contract"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "INSPECTION_PASSED"


class TestHarvestWindowMustHaveElapsed:
    def test_a_window_still_in_the_future_is_refused_until_the_clock_passes_it(self, api):
        """A harvest event records work already done, so the clock has to be past the window.

        PRD: "The window must be well-formed, with `window_start` strictly before `window_end`, or the
        request is refused with `ERR_INVALID_WINDOW`, and it must already have elapsed — a
        `window_end` after the current logical clock instant is refused with
        `ERR_HARVEST_WINDOW_NOT_ELAPSED`."

        Design: Corner/validations/harvest_window_not_yet_elapsed_rejected
        """
        state = _harvest_ready_contract(
            api, cleanout_overrides={"cleaned_at": "2026-08-19T18:00:00Z"}
        )
        payload = create_harvest_event_payload(
            state["contract"]["id"], state["equipment"]["id"]
        )

        response = api.create_harvest_event(payload, make_conditioning_manager_headers())
        validate_error(response, "ERR_HARVEST_WINDOW_NOT_ELAPSED", 422)

        clock = set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])
        assert clock["current_utc"] == TEST_DEFAULTS["HARVEST_CLOCK"]

        event = validate_success(
            api.create_harvest_event(payload, make_conditioning_manager_headers()), 201
        )
        lot = get_success_data(
            api.get_seed_lot(event["seed_lot_id"], make_conditioning_manager_headers())
        )
        assert lot["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert lot["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "HARVESTED"


FUTURE_RUN_WINDOW_START = "2026-09-15T06:00:00Z"
FUTURE_RUN_WINDOW_END = "2026-09-15T12:00:00Z"


class TestRunCompletionMustFollowItsWindow:
    def test_a_run_may_be_planned_into_the_future_but_not_completed_early(self, api):
        """Planning the future window is accepted; only the completion waits for the clock.

        PRD: "The run must be in `PLANNED` status, or the request is refused with
        `ERR_INVALID_RUN_STATE`; the run's `window_end` must be at or before the current logical clock
        instant, or it is refused with `ERR_RUN_WINDOW_NOT_ELAPSED`; and the output mass must be at
        least zero and no greater than the run's `input_kg`, or it is refused with
        `ERR_OUTPUT_EXCEEDS_INPUT`."

        Design: Corner/validations/run_completion_before_window_end_rejected
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        planned = plan_run(
            api,
            lot_id,
            state["line"]["id"],
            "CLEANING",
            window_start=FUTURE_RUN_WINDOW_START,
            window_end=FUTURE_RUN_WINDOW_END,
        )
        assert planned["status"] == "PLANNED"

        payload = complete_conditioning_run_payload(TEST_DEFAULTS["CLEANING_OUTPUT_KG"])
        response = api.complete_conditioning_run(
            planned["id"], payload, make_conditioning_manager_headers()
        )
        validate_error(response, "ERR_RUN_WINDOW_NOT_ELAPSED", 422)

        still_planned = get_success_data(
            api.get_conditioning_run(planned["id"], make_conditioning_manager_headers())
        )
        assert still_planned["status"] == "PLANNED"

        set_clock(api, FUTURE_RUN_WINDOW_END)
        completed = validate_success(
            api.complete_conditioning_run(
                planned["id"], payload, make_conditioning_manager_headers()
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["shrink_kg"] == pytest.approx(CLEANING_SHRINK_KG, abs=0.001)

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["CLEANING_OUTPUT_KG"], abs=0.001)
        assert lot["dockage_pct"] == pytest.approx(CLEANED_DOCKAGE_PCT, abs=0.001)
        assert lot["conditioning_status"] == "CLEANED"


class TestTagBagCountAgainstUntaggedRemainder:
    def test_one_bag_more_than_the_lot_holds_is_refused_and_the_full_block_is_not(self, api):
        """The ceiling is the lot's own bag count while nothing is tagged yet.

        PRD: "The requested bag count may not exceed the lot's untagged bags, computed as the lot's
        `bag_count` minus its `tagged_bag_count`, or the request is refused with
        `ERR_TAG_BAG_COUNT_EXCEEDS_LOT`."

        Design: Corner/validations/tag_bag_count_exceeding_lot_rejected
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        assert state["seed_lot"]["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]

        response = api.create_certification_tag(
            create_certification_tag_payload(
                lot_id, state["sample"]["id"], bag_count=GOLDEN_FIGURES["BAG_COUNT"] + 1
            ),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_TAG_BAG_COUNT_EXCEEDS_LOT", 422)

        headers = make_conditioning_manager_headers()
        untouched = get_success_data(api.get_seed_lot(lot_id, headers))
        assert untouched["tagged_bag_count"] == 0

        tag = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_id, state["sample"]["id"]),
                make_certification_agency_headers(),
            ),
            201,
        )
        assert tag["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert tag["status"] == "ISSUED"

        lot = get_success_data(api.get_seed_lot(lot_id, headers))
        assert lot["tagged_bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["certification_status"] == "TAGGED"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

    def test_the_remainder_shrinks_as_tags_are_issued(self, api):
        """After a thousand bags are tagged only the remaining three hundred and eighty fit.

        PRD: "The requested bag count may not exceed the lot's untagged bags, computed as the lot's
        `bag_count` minus its `tagged_bag_count`, or the request is refused with
        `ERR_TAG_BAG_COUNT_EXCEEDS_LOT`."

        Design: Corner/validations/tag_bag_count_exceeding_lot_rejected
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        sample_id = state["sample"]["id"]

        first = issue_tag(api, lot_id, sample_id, bag_count=1000)
        assert first["bag_count"] == 1000

        # PRD gate 28 wants the lot BAGGED and PASSED when a tag block is requested, and the
        # first tag block moved it PASSED -> TAGGED. A RETEST sample is admitted against a
        # TAGGED lot, and a passing retest walks it SAMPLED -> PASSED with its issued tags and
        # its tagged bag count left in place, which is the only state in which the untagged
        # remainder is non-trivial.
        retest = draw_sample(api, lot_id, sample_kind="RETEST")
        post_results(api, retest["id"])
        reopened = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert reopened["certification_status"] == "PASSED"
        assert reopened["tagged_bag_count"] == 1000

        response = api.create_certification_tag(
            create_certification_tag_payload(lot_id, sample_id, bag_count=500),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_TAG_BAG_COUNT_EXCEEDS_LOT", 422)

        second = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_id, sample_id, bag_count=380),
                make_certification_agency_headers(),
            ),
            201,
        )
        assert second["bag_count"] == 380

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["tagged_bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["certification_status"] == "TAGGED"


class TestTagClassAgainstVarietyCeiling:
    def test_a_class_outranking_the_variety_is_refused_and_the_ceiling_class_is_not(self, api):
        """`REGISTERED` outranks a variety topping out at `CERTIFIED`.

        PRD: "And the class printed on the tag may not outrank the variety's ceiling: ranking
        `CERTIFIED` lowest, `REGISTERED` above it and `FOUNDATION` highest, the requested `tag_class`
        rank must be at or below the rank of the variety's `max_seed_class`, or the request is refused
        with `ERR_TAG_CLASS_EXCEEDS_VARIETY`."

        Design: Corner/validations/tag_class_above_variety_maximum_rejected
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        assert state["variety"]["max_seed_class"] == TEST_DEFAULTS["MAX_SEED_CLASS"]

        response = api.create_certification_tag(
            create_certification_tag_payload(
                lot_id, state["sample"]["id"], tag_class="REGISTERED"
            ),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_TAG_CLASS_EXCEEDS_VARIETY", 422)

        headers = make_conditioning_manager_headers()
        refused = get_success_data(api.get_seed_lot(lot_id, headers))
        assert refused["certification_status"] == "PASSED"
        assert refused["tagged_bag_count"] == 0

        tag = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_id, state["sample"]["id"]),
                make_certification_agency_headers(),
            ),
            201,
        )
        assert tag["tag_class"] == "CERTIFIED"

        lot = get_success_data(api.get_seed_lot(lot_id, headers))
        assert lot["certification_status"] == "TAGGED"


CARRYOVER_CLOCK = "2027-06-12T00:00:00Z"


class TestCarryoverGenerationCeiling:
    def test_a_variety_forbidding_carryover_refuses_the_first_successor(self, api):
        """The generation ceiling is checked even though the retest window is genuinely open.

        PRD: "And the successor's generation depth must stay within the variety's ceiling: the
        parent's `carryover_generation` plus one may not exceed the variety's
        `max_carryover_generations`, or the request is refused with `ERR_CARRYOVER_LIMIT_EXCEEDED`."

        PRD: "The current logical clock instant must be strictly after the parent's
        `germination_valid_until`, or the request is refused with `ERR_RETEST_NOT_DUE`."

        Design: Corner/validations/carryover_beyond_generation_limit_rejected
        """
        state = tagged_lot_state(api, variety_overrides={"max_carryover_generations": 0})
        lot_id = state["seed_lot"]["id"]
        assert_instant_equals(
            state["seed_lot"]["germination_valid_until"], GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"]
        )

        set_clock(api, CARRYOVER_CLOCK)
        parent = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))

        response = api.create_carryover(
            lot_id,
            create_carryover_payload(parent["version"]),
            make_conditioning_manager_headers(),
        )
        error = validate_error(response, "ERR_CARRYOVER_LIMIT_EXCEEDED", 422)
        assert error["error_id"] != "ERR_RETEST_NOT_DUE"
        assert error["error_id"] != "ERR_STALE_LOT_VERSION"

        _successors, meta = validate_paginated(
            api.list_seed_lots(make_conditioning_manager_headers(), {"parent_seed_lot_id": lot_id})
        )
        assert meta["total_count"] == 0

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["certification_status"] == "TAGGED"
        assert lot["carryover_generation"] == 0


BAGGED_CUMULATIVE_SHRINK_KG = 6498.75


class TestReversalMustTakeTheLatestRun:
    def test_the_sizing_run_cannot_be_reversed_behind_a_completed_bagging_run(self, api):
        """The lot's history unwinds from the top only, so the middle run is frozen.

        PRD: "Two guards protect reversal: a completed run may only be reversed when it is the latest
        completed run on its lot, ordered by `window_end` descending with `created_at` descending as
        the tie-break, or the request is refused with `ERR_RUN_NOT_LATEST`; and no run on a lot whose
        certification status is `TAGGED` may be reversed at all, which is refused with
        `ERR_LOT_TAGGED_IMMUTABLE`."

        Design: Corner/validations/reversal_of_non_latest_completed_run_rejected
        """
        state = bagged_lot_state(api)

        response = api.reverse_conditioning_run(
            state["sizing_run"]["id"],
            reverse_conditioning_run_payload(reversal_reason="Sizing screens were mis-set"),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_RUN_NOT_LATEST", 409)

        headers = make_conditioning_manager_headers()
        sizing = get_success_data(api.get_conditioning_run(state["sizing_run"]["id"], headers))
        bagging = get_success_data(api.get_conditioning_run(state["bagging_run"]["id"], headers))
        assert sizing["status"] == "COMPLETED"
        assert bagging["status"] == "COMPLETED"

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], headers))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001)
        assert lot["cumulative_shrink_kg"] == pytest.approx(BAGGED_CUMULATIVE_SHRINK_KG, abs=0.001)
        assert lot["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["conditioning_status"] == "BAGGED"


class TestReversalOnATaggedLot:
    def test_the_tag_freezes_even_the_latest_completed_run(self, api):
        """The blocker is the certification axis, not the run ordering.

        PRD: "Two guards protect reversal: a completed run may only be reversed when it is the latest
        completed run on its lot, ordered by `window_end` descending with `created_at` descending as
        the tie-break, or the request is refused with `ERR_RUN_NOT_LATEST`; and no run on a lot whose
        certification status is `TAGGED` may be reversed at all, which is refused with
        `ERR_LOT_TAGGED_IMMUTABLE`."

        Design: Corner/validations/reversal_of_tagged_lot_run_rejected
        """
        state = tagged_lot_state(api)

        response = api.reverse_conditioning_run(
            state["bagging_run"]["id"],
            reverse_conditioning_run_payload(
                reversal_reason="Re-bagging requested after tagging"
            ),
            make_conditioning_manager_headers(),
        )
        error = validate_error(response, "ERR_LOT_TAGGED_IMMUTABLE", 409)
        assert error["error_id"] != "ERR_RUN_NOT_LATEST"

        headers = make_conditioning_manager_headers()
        run = get_success_data(api.get_conditioning_run(state["bagging_run"]["id"], headers))
        assert run["status"] == "COMPLETED"

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], headers))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001)
        assert lot["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["tagged_bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]

        tag = get_success_data(
            api.get_certification_tag(state["tag"]["id"], make_certification_agency_headers())
        )
        assert tag["status"] == "ISSUED"


SECOND_LOT_GROSS_KG = 28000.0
SECOND_HARVEST_WINDOW_START = "2026-09-11T08:00:00Z"
SECOND_HARVEST_WINDOW_END = "2026-09-11T18:00:00Z"


class TestTagSampleOwnership:
    def test_a_sample_drawn_from_another_lot_is_refused_before_the_eligibility_rule(self, api):
        """The mismatch is caught first, though the named lot is also far from tag-eligible.

        PRD: "The referenced sample must belong to that very lot and must carry a `PASS` result, or
        the request is refused with `ERR_SAMPLE_LOT_MISMATCH`."

        PRD: "The lot must be simultaneously `BAGGED` on its conditioning axis and `PASSED` on its
        certification axis, or the request is refused with `ERR_LOT_NOT_TAG_ELIGIBLE`."

        PRD: "27. The referenced sample belongs to the tagged lot and passed — `ERR_SAMPLE_LOT_MISMATCH`."

        PRD: "28. The lot is tag-eligible, meaning both `BAGGED` and `PASSED` — `ERR_LOT_NOT_TAG_ELIGIBLE`."

        Design: Corner/validations/tag_referencing_other_lots_sample_rejected
        """
        state = passed_lot_state(api)
        second_combine = make_harvest_equipment(
            api, equipment_code=TEST_DEFAULTS["SECOND_EQUIPMENT_CODE"]
        )
        certify_cleanout(api, second_combine["id"], state["variety"]["id"])
        second_event = get_success_data(
            api.create_harvest_event(
                create_harvest_event_payload(
                    state["contract"]["id"],
                    second_combine["id"],
                    window_start=SECOND_HARVEST_WINDOW_START,
                    window_end=SECOND_HARVEST_WINDOW_END,
                    gross_weight_kg=SECOND_LOT_GROSS_KG,
                ),
                make_conditioning_manager_headers(),
            )
        )
        second_lot_id = second_event["seed_lot_id"]

        response = api.create_certification_tag(
            create_certification_tag_payload(
                second_lot_id, state["sample"]["id"], bag_count=100
            ),
            make_certification_agency_headers(),
        )
        error = validate_error(response, "ERR_SAMPLE_LOT_MISMATCH", 422)
        assert error["error_id"] != "ERR_LOT_NOT_TAG_ELIGIBLE"

        headers = make_conditioning_manager_headers()
        second_lot = get_success_data(api.get_seed_lot(second_lot_id, headers))
        assert second_lot["certification_status"] == "UNSAMPLED"
        assert second_lot["tagged_bag_count"] == 0
        assert second_lot["bag_count"] == 0

        first_lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], headers))
        assert first_lot["certification_status"] == "PASSED"
        assert first_lot["tagged_bag_count"] == 0


SHORT_ISOLATION_DISTANCE_M = 150.0


class TestOfferIsolationGate:
    def test_a_field_short_of_the_varietys_minimum_isolation_cannot_be_offered(self, api):
        """No restricted record exists, so the isolation rule is the one that fires.

        PRD: "The field's `isolation_distance_m` must be at least the variety's `isolation_min_m`, or
        the offer is refused with `ERR_ISOLATION_DISTANCE_INSUFFICIENT`."

        PRD: "The strict variant's blocking error is `ERR_FIELD_HISTORY_RESTRICTED` whenever at least
        one restricted record exists, and `ERR_ISOLATION_DISTANCE_INSUFFICIENT` when there is no
        restricted record but the shortfall is positive — history is examined before isolation, so a
        field failing both reports the history error."

        Design: Corner/validations/offer_with_insufficient_isolation_rejected
        """
        state = draft_contract_state(
            api,
            field_overrides={
                "field_code": "F-South-4",
                "isolation_distance_m": SHORT_ISOLATION_DISTANCE_M,
            },
        )
        assert state["variety"]["isolation_min_m"] == pytest.approx(
            TEST_DEFAULTS["ISOLATION_MIN_M"], abs=0.01
        )

        response = api.offer_production_contract(
            state["contract"]["id"], {}, make_program_admin_headers()
        )
        error = validate_error(response, "ERR_ISOLATION_DISTANCE_INSUFFICIENT", 422)
        assert error["error_id"] != "ERR_FIELD_HISTORY_RESTRICTED"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "DRAFT"
        assert contract["version"] == 1


ROGUEABLE_OFF_TYPE_PLANTS = 21
ROGUEABLE_OFF_TYPE_RATE = 10.50
ROGUEING_PLANTS_REMOVED = 9
REMAINING_OFF_TYPE_PLANTS = 15


class TestRogueingVerificationNeedsADeclaration:
    def test_verifying_before_the_grower_declares_is_refused_then_accepted(self, api):
        """The declaration is the missing precondition, and filing it unblocks the walk.

        PRD: "A verification attempted against an inspection whose `outcome` is not
        `ROGUEING_ORDERED`, or whose `status` is already `ROGUEING_VERIFIED`, is refused with
        `ERR_INVALID_INSPECTION_STATE`; a verification attempted while the inspection is still in
        `RECORDED` status, meaning the grower has filed no declaration, is refused with
        `ERR_ROGUEING_NOT_DECLARED` instead."

        PRD: "A successful declaration stores both values, moves the inspection `RECORDED →
        ROGUEING_DECLARED`, and increments the inspection's `version` by 1."

        PRD: "When the remaining rate is at or below the variety's off-type tolerance *and* the
        contract's `rogueing_rounds_used` has not exceeded the variety's `max_rogueing_rounds`, the
        rogueing is accepted: the inspection moves `ROGUEING_DECLARED → ROGUEING_VERIFIED`,
        `rogueing_verified_by_user_id` is set from the verifying officer's `X-User-ID`, the contract
        returns `ROGUEING_REQUIRED → PLANTED` so that a further inspection round may be recorded, the
        inspection's `version` increments by 1, and the contract's `version` increments by 1."

        Design: Corner/validations/rogueing_verification_before_declaration_rejected
        """
        state = planted_contract_state(api)
        set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
        inspection = record_inspection(
            api,
            state["contract"]["id"],
            inspector_user_id="fo-1",
            off_type_plants=ROGUEABLE_OFF_TYPE_PLANTS,
        )
        assert inspection["outcome"] == "ROGUEING_ORDERED"

        verification = rogueing_verification_payload(
            verified_remaining_off_type_plants=REMAINING_OFF_TYPE_PLANTS
        )
        response = api.verify_rogueing(
            inspection["id"], verification, make_field_officer_headers("fo-2")
        )
        validate_error(response, "ERR_ROGUEING_NOT_DECLARED", 409)

        undeclared = get_success_data(
            api.get_field_inspection(inspection["id"], make_program_admin_headers())
        )
        assert undeclared["status"] == "RECORDED"
        assert undeclared["outcome"] == "ROGUEING_ORDERED"
        assert undeclared["off_type_rate_per_10000"] == pytest.approx(
            ROGUEABLE_OFF_TYPE_RATE, abs=0.01
        )

        declared = validate_success(
            api.declare_rogueing(
                inspection["id"],
                rogueing_declaration_payload(
                    rogueing_plants_removed=ROGUEING_PLANTS_REMOVED,
                    rogueing_declared_on=TEST_DEFAULTS["INSPECTED_ON"],
                ),
                make_grower_headers(state["grower"]["id"]),
            ),
            200,
        )
        assert declared["status"] == "ROGUEING_DECLARED"
        assert declared["rogueing_plants_removed"] == ROGUEING_PLANTS_REMOVED

        verified = validate_success(
            api.verify_rogueing(
                inspection["id"], verification, make_field_officer_headers("fo-2")
            ),
            200,
        )
        assert verified["status"] == "ROGUEING_VERIFIED"
        assert verified["rogueing_verified_by_user_id"] == "fo-2"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "PLANTED"
        assert contract["rogueing_rounds_used"] == 1


class TestRogueingDeclarationNeedsAnOrder:
    def test_a_passing_inspection_is_outside_the_rogueing_workflow(self, api):
        """The declaration reports the inspection state, not a missing declaration.

        PRD: "A declaration is accepted only when the inspection's `outcome` is `ROGUEING_ORDERED` and
        its `status` is still `RECORDED`; otherwise the request is refused with
        `ERR_INVALID_INSPECTION_STATE`."

        Design: Corner/validations/rogueing_declaration_on_passed_inspection_rejected
        """
        state = inspection_passed_contract_state(api)
        inspection = state["inspection"]
        assert inspection["outcome"] == "PASSED"

        response = api.declare_rogueing(
            inspection["id"],
            rogueing_declaration_payload(
                rogueing_plants_removed=3, rogueing_declared_on=TEST_DEFAULTS["INSPECTED_ON"]
            ),
            make_grower_headers(state["grower"]["id"]),
        )
        validate_error(response, "ERR_INVALID_INSPECTION_STATE", 409)

        stored = get_success_data(
            api.get_field_inspection(inspection["id"], make_program_admin_headers())
        )
        assert stored["outcome"] == "PASSED"
        assert stored["status"] == "RECORDED"
        assert stored["rogueing_plants_removed"] is None

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "INSPECTION_PASSED"
        assert contract["rogueing_rounds_used"] == 0


class TestSampleResultsPostedOnce:
    def test_a_second_laboratory_report_is_refused_and_changes_nothing(self, api):
        """The stored figures and the price the first report set both stand.

        PRD: "A sample that has already been resulted is refused with
        `ERR_SAMPLE_ALREADY_RESULTED`."

        Design: Corner/validations/sample_results_posted_twice_rejected
        """
        state = passed_lot_state(api)

        response = api.post_lot_sample_results(
            state["sample"]["id"],
            lot_sample_results_payload(
                germination_pct=88.0,
                purity_pct=97.5,
                inert_pct=1.0,
                weed_seed_count_per_kg=5,
            ),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_SAMPLE_ALREADY_RESULTED", 409)

        sample = get_success_data(
            api.get_lot_sample(state["sample"]["id"], make_certification_agency_headers())
        )
        assert sample["result"] == "PASS"
        assert sample["germination_pct"] == pytest.approx(
            TEST_DEFAULTS["RESULT_GERMINATION_PCT"], abs=0.01
        )
        assert sample["purity_pct"] == pytest.approx(TEST_DEFAULTS["RESULT_PURITY_PCT"], abs=0.01)

        lot = get_success_data(
            api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers())
        )
        assert lot["adjusted_price_per_unit_cents"] == GOLDEN_FIGURES[
            "ADJUSTED_PRICE_PER_UNIT_CENTS"
        ]
        assert lot["certification_status"] == "PASSED"
