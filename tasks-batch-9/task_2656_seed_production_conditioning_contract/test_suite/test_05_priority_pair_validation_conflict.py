"""Requests that violate two rules at once must report the higher-priority rule."""

from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    bagged_lot_state,
    create_conditioning_run_payload,
    create_harvest_event_payload,
    create_production_contract_payload,
    draw_sample,
    get_success_data,
    harvested_lot_state,
    lot_sample_results_payload,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_grower,
    make_grower_headers,
    make_harvest_equipment,
    make_production_field,
    make_program_admin_headers,
    make_treatment_product,
    make_variety,
    record_inspection,
    run_stage,
    set_clock,
    sign_contract_payload,
    validate_error,
    validate_paginated,
)

TREATMENT_LABEL_TEXT = (
    "Treated seed. EPA Reg. No. 400-461. DYED. Do not use for food, feed or oil purposes."
)


def _draft_and_inspected_contracts(api):
    """Contract A left in DRAFT, contract B carried to INSPECTION_PASSED, machine never cleaned."""
    variety = make_variety(api)
    grower = make_grower(api)

    field_a = make_production_field(
        api, grower["id"], field_code="F-A", acres=320.0, isolation_distance_m=250.0
    )
    make_field_history_record(api, field_a["id"])
    field_b = make_production_field(
        api, grower["id"], field_code="F-B", acres=200.0, isolation_distance_m=250.0
    )
    make_field_history_record(api, field_b["id"])

    contract_a = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(grower["id"], variety["id"], field_a["id"]),
            make_program_admin_headers(),
        )
    )
    contract_b = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(
                grower["id"],
                variety["id"],
                field_b["id"],
                contracted_acres=150.0,
                advance_total_cents=400000,
            ),
            make_program_admin_headers(),
        )
    )
    get_success_data(api.offer_production_contract(contract_b["id"], {}, make_program_admin_headers()))
    get_success_data(
        api.sign_production_contract(
            contract_b["id"], sign_contract_payload(), make_grower_headers(grower["id"])
        )
    )
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    record_inspection(api, contract_b["id"], inspector_user_id="fo-1")

    equipment = make_harvest_equipment(api)
    set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])
    return {
        "variety": variety,
        "grower": grower,
        "draft_contract": contract_a,
        "inspected_contract": contract_b,
        "equipment": equipment,
    }


class TestStateBeatsSafetyOnHarvestEvent:
    def test_contract_state_error_wins_over_the_uncertified_machine(self, api):
        """A DRAFT contract and a dirty machine both fail; the contract-state rule is higher.

        PRD: "7. Contract state permits the operation — `ERR_INVALID_CONTRACT_STATE`. This guards
        contract offer, contract signing, contract cancellation, inspection recording, harvest
        recording and settlement computation."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_harvest_event
        """
        state = _draft_and_inspected_contracts(api)

        response = api.create_harvest_event(
            create_harvest_event_payload(state["draft_contract"]["id"], state["equipment"]["id"]),
            make_conditioning_manager_headers(),
        )
        error = validate_error(response, "ERR_INVALID_CONTRACT_STATE", 409)
        assert error["error_id"] != "ERR_EQUIPMENT_CLEANOUT_REQUIRED"

    def test_the_cleanout_rule_is_armed_and_only_lost_the_first_race(self, api):
        """The same dirty machine refuses a properly advanced contract with the safety error.

        PRD: "22. Harvest machine documented clean for the contract's variety —
        `ERR_EQUIPMENT_CLEANOUT_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_harvest_event
        """
        state = _draft_and_inspected_contracts(api)

        api.create_harvest_event(
            create_harvest_event_payload(state["draft_contract"]["id"], state["equipment"]["id"]),
            make_conditioning_manager_headers(),
        )
        response = api.create_harvest_event(
            create_harvest_event_payload(
                state["inspected_contract"]["id"],
                state["equipment"]["id"],
                window_start="2026-09-11T08:00:00Z",
                window_end="2026-09-11T18:00:00Z",
                gross_weight_kg=28000.0,
            ),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_EQUIPMENT_CLEANOUT_REQUIRED", 409)

        events, meta = validate_paginated(api.list_harvest_events(make_program_admin_headers()))
        assert meta["total_count"] == 0
        assert events == []

        headers = make_program_admin_headers()
        draft = get_success_data(api.get_production_contract(state["draft_contract"]["id"], headers))
        inspected = get_success_data(
            api.get_production_contract(state["inspected_contract"]["id"], headers)
        )
        assert draft["status"] == "DRAFT"
        assert inspected["status"] == "INSPECTION_PASSED"


def _sized_lot_with_treatment_product(api):
    """A lot sized on LN-1 whose sizing run still occupies the line, plus a labelled product."""
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
    state["treatment_product"] = make_treatment_product(
        api,
        product_code="TP-VITAVAX",
        epa_registration_number="400-461",
        allowed_crop_kinds=["WHEAT", "TRITICALE"],
        max_rate_g_per_100kg=150.0,
        requires_dye=True,
        restricted_use=False,
        label_signal_word="CAUTION",
    )
    state["seed_lot"] = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
    return state


def _treating_run_payload(state, rate_g_per_100kg):
    return create_conditioning_run_payload(
        state["seed_lot"]["id"],
        state["line"]["id"],
        "TREATING",
        window_start="2026-09-12T15:00:00Z",
        window_end="2026-09-12T18:00:00Z",
        input_kg=36000.0,
        treatment_product_id=state["treatment_product"]["id"],
        treatment_rate_g_per_100kg=rate_g_per_100kg,
        label_text=TREATMENT_LABEL_TEXT,
    )


class TestSafetyBeatsTemporalOnTreatingRun:
    def test_label_rate_error_wins_over_the_line_window_conflict(self, api):
        """An over-label rate and an occupied line both fail; the pesticide rule is higher.

        PRD: "20. Treatment rate within the label maximum — `ERR_TREATMENT_RATE_EXCEEDS_LABEL`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_treating_run
        """
        state = _sized_lot_with_treatment_product(api)

        response = api.create_conditioning_run(
            _treating_run_payload(state, 250.0), make_conditioning_manager_headers()
        )
        error = validate_error(response, "ERR_TREATMENT_RATE_EXCEEDS_LABEL", 422)
        assert error["error_id"] != "ERR_LINE_WINDOW_CONFLICT"
        assert response.status_code != 409

    def test_the_line_calendar_rule_is_armed_at_the_exact_label_maximum(self, api):
        """At exactly the labelled maximum the safety rule passes and the calendar rule fires.

        PRD: "The requested `treatment_rate_g_per_100kg` may not exceed the product's
        `max_rate_g_per_100kg`; a rate exactly at the label maximum is permitted, and anything
        above it is refused with `ERR_TREATMENT_RATE_EXCEEDS_LABEL`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_treating_run
        """
        state = _sized_lot_with_treatment_product(api)

        api.create_conditioning_run(
            _treating_run_payload(state, 250.0), make_conditioning_manager_headers()
        )
        response = api.create_conditioning_run(
            _treating_run_payload(state, 150.0), make_conditioning_manager_headers()
        )
        validate_error(response, "ERR_LINE_WINDOW_CONFLICT", 409)

        runs, meta = validate_paginated(
            api.list_conditioning_runs(
                make_conditioning_manager_headers(), {"seed_lot_id": state["seed_lot"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {run["stage"] for run in runs} == {"CLEANING", "SIZING"}

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers()))
        assert lot["conditioning_status"] == "SIZED"
        assert lot["current_kg"] == pytest.approx(36000.0, abs=0.01)


class TestConstraintBeatsTemporalOnSampleResults:
    def test_component_sum_error_wins_over_the_future_report_date(self, api):
        """A purity and inert sum above a whole sample outranks a future `tested_at`.

        PRD: "33. Reported component percentages do not exceed a whole sample —
        `ERR_COMPONENT_PCT_SUM_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_sample_results
        """
        state = bagged_lot_state(api)
        sample = draw_sample(api, state["seed_lot"]["id"])

        response = api.post_lot_sample_results(
            sample["id"],
            lot_sample_results_payload(inert_pct=1.0, tested_at="2026-09-20T00:00:00Z"),
            make_certification_agency_headers(),
        )
        error = validate_error(response, "ERR_COMPONENT_PCT_SUM_INVALID", 422)
        assert error["error_id"] != "ERR_DATE_IN_FUTURE"

    def test_the_report_date_rule_is_armed_once_the_composition_is_valid(self, api):
        """With a valid composition the same future timestamp is refused, and nothing moved.

        PRD: "A `tested_at` after the current logical clock instant is refused with
        `ERR_DATE_IN_FUTURE`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_sample_results
        """
        state = bagged_lot_state(api)
        sample = draw_sample(api, state["seed_lot"]["id"])

        api.post_lot_sample_results(
            sample["id"],
            lot_sample_results_payload(inert_pct=1.0, tested_at="2026-09-20T00:00:00Z"),
            make_certification_agency_headers(),
        )
        response = api.post_lot_sample_results(
            sample["id"],
            lot_sample_results_payload(tested_at="2026-09-20T00:00:00Z"),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_DATE_IN_FUTURE", 422)

        stored = get_success_data(api.get_lot_sample(sample["id"], make_certification_agency_headers()))
        assert stored["result"] == "PENDING"
        assert stored["germination_pct"] is None

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], make_certification_agency_headers()))
        assert lot["certification_status"] == "SAMPLED"
