"""Operations gated by the state of a second entity the request only references."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_harvest_equipment,
    certify_cleanout,
    create_harvest_event_payload,
    create_lot_sample_payload,
    get_success_data,
    harvested_lot_state,
    inspection_passed_contract_state,
    make_certification_agency_headers,
    make_conditioning_line,
    make_conditioning_manager_headers,
    make_harvest_equipment,
    make_program_admin_headers,
    make_variety,
    run_stage,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _contract_with_wrongly_cleaned_machine(api):
    """An inspection-passed contract on one variety, machine cleaned out for another."""
    state = inspection_passed_contract_state(api)
    state["other_variety"] = make_variety(
        api, variety_name=TEST_DEFAULTS["SECOND_VARIETY_NAME"], crop_kind="WHEAT"
    )
    state["equipment"] = make_harvest_equipment(api)
    set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])
    state["equipment"] = certify_cleanout(
        api, state["equipment"]["id"], state["other_variety"]["id"]
    )
    state["line"] = make_conditioning_line(api)
    return state


class TestHarvestBlockedByEquipmentCleanoutVariety:
    def test_machine_cleaned_for_another_variety_is_as_useless_as_a_dirty_machine(self, api):
        """`cleanout_certified` is true, yet the wrong variety blocks the harvest.

        PRD: "The machine must be simultaneously in `AVAILABLE` status, carry
        `cleanout_certified` true, and have a `last_cleanout_variety_id` equal to the contract's
        `variety_id`; if any of those three fails the request is refused with
        `ERR_EQUIPMENT_CLEANOUT_REQUIRED`, which is what makes a machine cleaned for the wrong
        variety as useless as a machine never cleaned at all."

        Design: Difficulty/cross_entity_state_dependency/harvest_blocked_by_equipment_cleanout_variety
        """
        state = _contract_with_wrongly_cleaned_machine(api)
        equipment = state["equipment"]
        assert_harvest_equipment(equipment)
        assert equipment["cleanout_certified"] is True
        assert equipment["status"] == "AVAILABLE"
        assert equipment["last_cleanout_variety_id"] == state["other_variety"]["id"]

        response = api.create_harvest_event(
            create_harvest_event_payload(state["contract"]["id"], equipment["id"]),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_EQUIPMENT_CLEANOUT_REQUIRED", 409)

        _events, event_meta = validate_paginated(api.list_harvest_events(make_program_admin_headers()))
        assert event_meta["total_count"] == 0
        _lots, lot_meta = validate_paginated(api.list_seed_lots(make_program_admin_headers()))
        assert lot_meta["total_count"] == 0

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "INSPECTION_PASSED"

    def test_recertifying_for_the_contracts_variety_admits_the_identical_call(self, api):
        """Only the posture for the contract's own variety unblocks the very same request.

        PRD: "A successful certification sets the machine's `status` to `AVAILABLE`, sets
        `cleanout_certified` to true, sets `last_cleanout_variety_id` to the supplied variety and
        `last_cleanout_at` to the supplied instant, and increments the machine's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/harvest_blocked_by_equipment_cleanout_variety
        """
        state = _contract_with_wrongly_cleaned_machine(api)
        payload = create_harvest_event_payload(state["contract"]["id"], state["equipment"]["id"])
        api.create_harvest_event(payload, make_conditioning_manager_headers())

        recertified = certify_cleanout(api, state["equipment"]["id"], state["variety"]["id"])
        assert recertified["last_cleanout_variety_id"] == state["variety"]["id"]

        event = validate_success(
            api.create_harvest_event(payload, make_conditioning_manager_headers()), 201
        )
        lot = get_success_data(api.get_seed_lot(event["seed_lot_id"], make_conditioning_manager_headers()))
        assert lot["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.01)
        assert lot["conditioning_status"] == "RAW"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "HARVESTED"


def _sized_lot_state(api):
    """A lot cleaned and sized on its line but not yet bagged."""
    state = harvested_lot_state(api)
    lot_id = state["seed_lot"]["id"]
    line_id = state["line"]["id"]
    run_stage(
        api, lot_id, line_id, "CLEANING", 37800.0,
        window_start=TEST_DEFAULTS["CLEANING_WINDOW_START"],
        window_end=TEST_DEFAULTS["CLEANING_WINDOW_END"],
        input_kg=TEST_DEFAULTS["GROSS_WEIGHT_KG"],
    )
    run_stage(
        api, lot_id, line_id, "SIZING", 36000.0,
        window_start=TEST_DEFAULTS["SIZING_WINDOW_START"],
        window_end=TEST_DEFAULTS["SIZING_WINDOW_END"],
        input_kg=37800.0,
    )
    state["seed_lot"] = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
    return state


class TestSamplingBlockedByLotNotBagged:
    def test_a_sized_lot_may_not_be_sampled(self, api):
        """Sampling reads the other axis of the lot: only a fully bagged lot admits it.

        PRD: "Only a fully bagged lot may be sampled: the lot's `conditioning_status` must be
        `BAGGED`."

        Design: Difficulty/cross_entity_state_dependency/sampling_blocked_by_lot_not_bagged
        """
        state = _sized_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        assert state["seed_lot"]["conditioning_status"] == "SIZED"

        response = api.create_lot_sample(
            create_lot_sample_payload(lot_id), make_certification_agency_headers()
        )
        validate_error(response, "ERR_INVALID_LOT_STATE", 409)

        _samples, meta = validate_paginated(
            api.list_lot_samples(make_certification_agency_headers(), {"seed_lot_id": lot_id})
        )
        assert meta["total_count"] == 0

        lot = get_success_data(api.get_seed_lot(lot_id, make_certification_agency_headers()))
        assert lot["certification_status"] == "UNSAMPLED"

    def test_completing_the_bagging_run_admits_the_identical_sample_call(self, api):
        """The bagging completion is what makes the previously refused request succeed.

        PRD: "The certification axis must also permit it, and the two sample kinds have different
        entry points: an `INITIAL` sample requires the lot's `certification_status` to be
        `UNSAMPLED`, while a `RETEST` sample requires it to be either `RETEST_DUE` or `TAGGED`."

        Design: Difficulty/cross_entity_state_dependency/sampling_blocked_by_lot_not_bagged
        """
        state = _sized_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        payload = create_lot_sample_payload(lot_id)
        api.create_lot_sample(payload, make_certification_agency_headers())

        run_stage(
            api, lot_id, state["line"]["id"], "BAGGING", TEST_DEFAULTS["BAGGING_OUTPUT_KG"],
            window_start=TEST_DEFAULTS["BAGGING_WINDOW_START"],
            window_end=TEST_DEFAULTS["BAGGING_WINDOW_END"],
            input_kg=36000.0,
        )
        bagged = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert bagged["conditioning_status"] == "BAGGED"
        assert bagged["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.01)
        assert bagged["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert bagged["final_clean_units"] == pytest.approx(GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01)

        sample = validate_success(
            api.create_lot_sample(payload, make_certification_agency_headers()), 201
        )
        assert sample["result"] == "PENDING"

        lot = get_success_data(api.get_seed_lot(lot_id, make_certification_agency_headers()))
        assert lot["certification_status"] == "SAMPLED"
        assert lot["conditioning_status"] == "BAGGED"
