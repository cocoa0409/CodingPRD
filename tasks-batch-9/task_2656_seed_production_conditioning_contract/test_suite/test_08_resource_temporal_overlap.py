"""Three shared resources with three different occupancy conventions."""

from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    certify_cleanout,
    complete_run,
    create_conditioning_run_payload,
    create_field_inspection_payload,
    create_harvest_event_payload,
    create_production_contract_payload,
    get_success_data,
    make_conditioning_line,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_field_officer_headers,
    make_grower,
    make_grower_headers,
    make_harvest_equipment,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    record_inspection,
    run_stage,
    set_clock,
    sign_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_HARVEST_END = TEST_DEFAULTS["HARVEST_WINDOW_END"]
SECOND_HARVEST_END = "2026-09-11T02:00:00Z"
ONE_SECOND_LATER = "2026-09-10T18:00:01Z"
SECOND_LOT_GROSS_KG = 28000.0
SECOND_LOT_PROVISIONAL_UNITS = 991.76


def _signed_contract(api, grower_id, variety_id, field_code, acres, contracted_acres, advance):
    field = make_production_field(
        api, grower_id, field_code=field_code, acres=acres, isolation_distance_m=250.0
    )
    make_field_history_record(api, field["id"])
    contract = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(
                grower_id,
                variety_id,
                field["id"],
                contracted_acres=contracted_acres,
                advance_total_cents=advance,
            ),
            make_program_admin_headers(),
        )
    )
    get_success_data(api.offer_production_contract(contract["id"], {}, make_program_admin_headers()))
    return get_success_data(
        api.sign_production_contract(
            contract["id"], sign_contract_payload(), make_grower_headers(grower_id)
        )
    )


def _one_machine_two_contracts(api):
    """Two inspection-passed contracts sharing one combine, the first already harvested."""
    variety = make_variety(api)
    grower = make_grower(api)
    contract_a = _signed_contract(api, grower["id"], variety["id"], "F-A", 320.0, 300.0, 1200000)
    contract_b = _signed_contract(api, grower["id"], variety["id"], "F-B", 200.0, 150.0, 400000)

    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    record_inspection(api, contract_a["id"], inspector_user_id="fo-1")
    record_inspection(api, contract_b["id"], inspector_user_id="fo-2")

    equipment = make_harvest_equipment(api)
    set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])
    certify_cleanout(api, equipment["id"], variety["id"])
    first_event = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(contract_a["id"], equipment["id"]),
            make_conditioning_manager_headers(),
        )
    )
    return {
        "variety": variety,
        "grower": grower,
        "contract_a": contract_a,
        "contract_b": contract_b,
        "equipment": equipment,
        "first_event": first_event,
    }


class TestEquipmentWindowTouchingEndpointCollides:
    def test_a_window_starting_at_the_previous_windows_end_collides(self, api):
        """The machine calendar is closed at both ends, so touching windows do collide.

        PRD: "Two windows that merely touch at a single instant therefore *do* collide, and no
        buffer notion applies to machines beyond the cleanout certification described in §3.4."

        Design: Difficulty/resource_temporal_overlap/equipment_window_touching_endpoint_collides
        """
        state = _one_machine_two_contracts(api)
        equipment_id = state["equipment"]["id"]

        certify_cleanout(api, equipment_id, state["variety"]["id"])
        response = api.create_harvest_event(
            create_harvest_event_payload(
                state["contract_b"]["id"],
                equipment_id,
                window_start=FIRST_HARVEST_END,
                window_end=SECOND_HARVEST_END,
                gross_weight_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_EQUIPMENT_WINDOW_CONFLICT", 409)

        _events, meta = validate_paginated(
            api.list_harvest_events(
                make_conditioning_manager_headers(), {"harvest_equipment_id": equipment_id}
            )
        )
        assert meta["total_count"] == 1

    def test_one_second_after_that_end_the_same_window_is_accepted(self, api):
        """The convention is pinned to the instant: a one-second gap clears the machine calendar.

        PRD: "A requested harvest window conflicts with an existing harvest window on the same
        machine whenever the requested start is at or before the existing end and the existing
        start is at or before the requested end."

        Design: Difficulty/resource_temporal_overlap/equipment_window_touching_endpoint_collides
        """
        state = _one_machine_two_contracts(api)
        equipment_id = state["equipment"]["id"]
        certify_cleanout(api, equipment_id, state["variety"]["id"])

        api.create_harvest_event(
            create_harvest_event_payload(
                state["contract_b"]["id"],
                equipment_id,
                window_start=FIRST_HARVEST_END,
                window_end=SECOND_HARVEST_END,
                gross_weight_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )
        event = validate_success(
            api.create_harvest_event(
                create_harvest_event_payload(
                    state["contract_b"]["id"],
                    equipment_id,
                    window_start=ONE_SECOND_LATER,
                    window_end=SECOND_HARVEST_END,
                    gross_weight_kg=SECOND_LOT_GROSS_KG,
                ),
                make_conditioning_manager_headers(),
            ),
            201,
        )

        lot = get_success_data(api.get_seed_lot(event["seed_lot_id"], make_conditioning_manager_headers()))
        assert lot["gross_kg"] == pytest.approx(SECOND_LOT_GROSS_KG, abs=0.01)
        assert lot["provisional_clean_units"] == pytest.approx(SECOND_LOT_PROVISIONAL_UNITS, abs=0.01)

        headers = make_program_admin_headers()
        first = get_success_data(api.get_production_contract(state["contract_a"]["id"], headers))
        second = get_success_data(api.get_production_contract(state["contract_b"]["id"], headers))
        assert first["status"] == "HARVESTED"
        assert second["status"] == "HARVESTED"


LINE_CLEANING_START = TEST_DEFAULTS["CLEANING_WINDOW_START"]
LINE_CLEANING_END = "2026-09-12T12:00:00Z"
LINE_SIZING_END = "2026-09-12T16:00:00Z"
FOREIGN_RUN_END = "2026-09-12T20:00:00Z"
BUFFERED_RUN_START = "2026-09-12T17:00:00Z"
BUFFERED_RUN_END = "2026-09-12T21:00:00Z"


def _two_varieties_sharing_one_line(api):
    """Line LN-1 has just completed a cleaning run for variety A; variety B's lot waits its turn."""
    variety_a = make_variety(api)
    variety_b = make_variety(api, variety_name=TEST_DEFAULTS["SECOND_VARIETY_NAME"])
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
            create_production_contract_payload(
                grower["id"], variety_a["id"], field_a["id"], contracted_acres=300.0
            ),
            make_program_admin_headers(),
        )
    )
    contract_b = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(
                grower["id"],
                variety_b["id"],
                field_b["id"],
                contracted_acres=150.0,
                advance_total_cents=400000,
            ),
            make_program_admin_headers(),
        )
    )
    for contract in (contract_a, contract_b):
        get_success_data(api.offer_production_contract(contract["id"], {}, make_program_admin_headers()))
        get_success_data(
            api.sign_production_contract(
                contract["id"], sign_contract_payload(), make_grower_headers(grower["id"])
            )
        )

    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    record_inspection(api, contract_a["id"], inspector_user_id="fo-1")
    record_inspection(api, contract_b["id"], inspector_user_id="fo-2")

    combine_a = make_harvest_equipment(api)
    combine_b = make_harvest_equipment(api, equipment_code="CMB-8")
    set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])
    certify_cleanout(api, combine_a["id"], variety_a["id"])
    certify_cleanout(api, combine_b["id"], variety_b["id"])

    line = make_conditioning_line(api)
    event_a = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(contract_a["id"], combine_a["id"]),
            make_conditioning_manager_headers(),
        )
    )
    event_b = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(
                contract_b["id"],
                combine_b["id"],
                window_start="2026-09-11T08:00:00Z",
                window_end="2026-09-11T18:00:00Z",
                gross_weight_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )
    )
    run_stage(
        api,
        event_a["seed_lot_id"],
        line["id"],
        "CLEANING",
        37800.0,
        window_start=LINE_CLEANING_START,
        window_end=LINE_CLEANING_END,
        input_kg=TEST_DEFAULTS["GROSS_WEIGHT_KG"],
    )
    return {
        "variety_a": variety_a,
        "variety_b": variety_b,
        "line": line,
        "lot_a": event_a["seed_lot_id"],
        "lot_b": event_b["seed_lot_id"],
    }


def _same_variety_sizing_payload(state):
    return create_conditioning_run_payload(
        state["lot_a"],
        state["line"]["id"],
        "SIZING",
        window_start=LINE_CLEANING_END,
        window_end=LINE_SIZING_END,
        input_kg=37800.0,
    )


class TestLineWindowTouchingEndpointAllowedButBufferEnforced:
    def test_a_zero_gap_successor_of_the_same_variety_needs_no_buffer(self, api):
        """The line calendar is half-open, so a run starting where the last one ended is accepted.

        PRD: "When the line's last variety is the same as the lot's variety, no cleanout is needed,
        the required buffer is zero, and a run starting at the exact instant the previous run ended
        is accepted."

        Design: Difficulty/resource_temporal_overlap/line_window_touching_endpoint_allowed_but_buffer_enforced
        """
        state = _two_varieties_sharing_one_line(api)

        sizing = validate_success(
            api.create_conditioning_run(
                _same_variety_sizing_payload(state), make_conditioning_manager_headers()
            ),
            201,
        )
        assert sizing["cleanout_buffer_applied_minutes"] == 0

    def test_the_same_zero_gap_window_is_refused_for_a_foreign_variety(self, api):
        """With a foreign variety the windows still do not overlap; only the buffer is short.

        PRD: "And the inter-variety cleanout buffer must have elapsed: when the line's
        `last_cleanout_variety_id` is non-null and differs from the requested lot's `variety_id`,
        the requested `window_start` must fall at or after the line's `last_run_end_utc` plus the
        line's `cleanout_minutes_required` minutes, or the request is refused with
        `ERR_LINE_CLEANOUT_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/line_window_touching_endpoint_allowed_but_buffer_enforced
        """
        state = _two_varieties_sharing_one_line(api)
        sizing = validate_success(
            api.create_conditioning_run(
                _same_variety_sizing_payload(state), make_conditioning_manager_headers()
            ),
            201,
        )
        complete_run(api, sizing["id"], 36000.0)

        response = api.create_conditioning_run(
            create_conditioning_run_payload(
                state["lot_b"],
                state["line"]["id"],
                "CLEANING",
                window_start=LINE_SIZING_END,
                window_end=FOREIGN_RUN_END,
                input_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )
        error = validate_error(response, "ERR_LINE_CLEANOUT_BUFFER_VIOLATION", 409)
        assert error["error_id"] != "ERR_LINE_WINDOW_CONFLICT"

    def test_an_hour_later_the_foreign_variety_run_carries_the_full_buffer(self, api):
        """Waiting out the line's cleanout minutes admits the run and records the buffer applied.

        PRD: "Whichever buffer the rule demanded is recorded on the run as
        `cleanout_buffer_applied_minutes`: zero when the line's last variety matched the lot's
        variety, and the line's full `cleanout_minutes_required` otherwise."

        Design: Difficulty/resource_temporal_overlap/line_window_touching_endpoint_allowed_but_buffer_enforced
        """
        state = _two_varieties_sharing_one_line(api)
        sizing = validate_success(
            api.create_conditioning_run(
                _same_variety_sizing_payload(state), make_conditioning_manager_headers()
            ),
            201,
        )
        complete_run(api, sizing["id"], 36000.0)
        api.create_conditioning_run(
            create_conditioning_run_payload(
                state["lot_b"],
                state["line"]["id"],
                "CLEANING",
                window_start=LINE_SIZING_END,
                window_end=FOREIGN_RUN_END,
                input_kg=SECOND_LOT_GROSS_KG,
            ),
            make_conditioning_manager_headers(),
        )

        buffered = validate_success(
            api.create_conditioning_run(
                create_conditioning_run_payload(
                    state["lot_b"],
                    state["line"]["id"],
                    "CLEANING",
                    window_start=BUFFERED_RUN_START,
                    window_end=BUFFERED_RUN_END,
                    input_kg=SECOND_LOT_GROSS_KG,
                ),
                make_conditioning_manager_headers(),
            ),
            201,
        )
        assert buffered["cleanout_buffer_applied_minutes"] == TEST_DEFAULTS[
            "LINE_CLEANOUT_MINUTES_REQUIRED"
        ]

        line = get_success_data(
            api.get_conditioning_line(state["line"]["id"], make_conditioning_manager_headers())
        )
        assert line["last_run_end_utc"] == LINE_SIZING_END
        assert line["last_cleanout_variety_id"] == state["variety_a"]["id"]

        headers = make_conditioning_manager_headers()
        lot_a = get_success_data(api.get_seed_lot(state["lot_a"], headers))
        lot_b = get_success_data(api.get_seed_lot(state["lot_b"], headers))
        assert lot_a["conditioning_status"] == "SIZED"
        assert lot_b["conditioning_status"] == "RAW"


def _three_signed_contracts(api):
    """One grower with three signed 2026 contracts and no inspection recorded yet."""
    variety = make_variety(api)
    grower = make_grower(api)
    contracts = [
        _signed_contract(api, grower["id"], variety["id"], "F-A", 320.0, 300.0, 1200000),
        _signed_contract(api, grower["id"], variety["id"], "F-B", 200.0, 150.0, 400000),
        _signed_contract(api, grower["id"], variety["id"], "F-C", 180.0, 150.0, 400000),
    ]
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    return grower, contracts


class TestInspectorDayCapacityAggregateExceeded:
    def test_two_walks_a_day_are_the_cap_and_the_third_is_refused(self, api):
        """The inspector's limit is a count per calendar date, not an interval intersection.

        PRD: "A field inspection occupies neither an instant nor a window but a calendar date, and
        its capacity rule is an aggregate rather than an overlap: at most two field inspections may
        share the same `inspector_user_id` and the same `inspected_on` calendar date."

        Design: Difficulty/resource_temporal_overlap/inspector_day_capacity_aggregate_exceeded
        """
        _grower, contracts = _three_signed_contracts(api)
        headers = make_field_officer_headers("fo-1")

        for contract in contracts[:2]:
            validate_success(
                api.create_field_inspection(
                    create_field_inspection_payload(contract["id"]), headers
                ),
                201,
            )

        response = api.create_field_inspection(
            create_field_inspection_payload(contracts[2]["id"]), headers
        )
        validate_error(response, "ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED", 409)

        _inspections, meta = validate_paginated(
            api.list_field_inspections(
                make_program_admin_headers(),
                {"inspector_user_id": "fo-1", "inspected_on": TEST_DEFAULTS["INSPECTED_ON"]},
            )
        )
        assert meta["total_count"] == 2

    def test_the_cap_is_scoped_to_one_officer(self, api):
        """The identical refused walk succeeds under a different officer on the same date.

        PRD: "A third inspection on the same officer and the same date is rejected with
        `ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspector_day_capacity_aggregate_exceeded
        """
        grower, contracts = _three_signed_contracts(api)
        first_officer = make_field_officer_headers("fo-1")

        for contract in contracts[:2]:
            api.create_field_inspection(create_field_inspection_payload(contract["id"]), first_officer)
        api.create_field_inspection(create_field_inspection_payload(contracts[2]["id"]), first_officer)

        accepted = validate_success(
            api.create_field_inspection(
                create_field_inspection_payload(contracts[2]["id"]),
                make_field_officer_headers("fo-2"),
            ),
            201,
        )
        assert accepted["inspector_user_id"] == "fo-2"
        assert accepted["outcome"] == "PASSED"

        headers = make_program_admin_headers()
        third = get_success_data(api.get_production_contract(contracts[2]["id"], headers))
        assert third["status"] == "INSPECTION_PASSED"

        standing = get_success_data(api.get_grower(grower["id"], headers))
        assert standing["compliance_flag_count"] == 0
