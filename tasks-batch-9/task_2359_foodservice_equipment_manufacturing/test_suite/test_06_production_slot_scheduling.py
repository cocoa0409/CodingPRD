"""Production slots: the padded closed interval, the capacity ceiling and the units ledger."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_slot,
    create_build_line,
    create_chain_account,
    create_chain_configuration,
    create_construction_program,
    create_equipment_model,
    read_build_line,
    read_production_slot,
    read_site_order,
    reserve_production_slot,
    set_clock,
    setup_program_with_site_order,
    setup_scheduled_site_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ELECTRIC_LINE = {"supported_energy_types": ["ELECTRIC"]}
PLAIN_MODEL = {"supported_controls_packages": ["STANDARD_DIAL"]}
PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}
PLAIN_RELEASE = {"model_overrides": PLAIN_MODEL, "config_overrides": PLAIN_CONFIG}

# The counted states of the build-line capacity ledger.
COUNTED_SLOT_STATES = {"RESERVED", "CONFIRMED", "IN_BUILD"}


def _line_with_one_reserved_slot(**slot_overrides):
    """A RELEASED site order for 60 units holding one 2026-09-07 to 2026-09-11 slot."""
    return setup_scheduled_site_order(
        slot_overrides=slot_overrides or None, **PLAIN_RELEASE
    )


def _reconstructed_committed_units(api, headers, line_id):
    """The ledger recomputed from the line's own slot rows."""
    data, _ = validate_paginated(
        api.list_production_slots(headers, {"build_line_id": line_id, "limit": 100})
    )
    return sum(
        slot["units"] for slot in data if slot["status"] in COUNTED_SLOT_STATES
    )


class TestChangeoverBuffer:
    def test_a_window_starting_exactly_twelve_hours_after_the_last_one_is_rejected(
        self, api, production_planner
    ):
        """2026-09-11T12:00:00Z collides with the pad while 12:00:01Z clears it.

        PRD §3.7: "Every existing slot on the same `build_line_id` whose `status` is
        `RESERVED`, `CONFIRMED` or `IN_BUILD` is padded by twelve hours on each side, and
        the requested interval is rejected with `ERR_BUILD_SLOT_OVERLAP` if its start is
        at or before that padded end **and** its end is at or after that padded start."

        Design: Difficulty/resource_temporal_overlap/production_slot_closed_interval_with_changeover_buffer_rejects_touching_windows
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]

        touching = api.create_production_slot(
            {
                "build_line_id": line_id,
                "site_order_id": site_order_id,
                "window_start": "2026-09-11T12:00:00Z",
                "window_end": "2026-09-11T20:00:00Z",
                "units": 10,
            },
            production_planner,
        )

        validate_error(touching, ApiErrorId.ERR_BUILD_SLOT_OVERLAP.value, 409)
        assert read_build_line(line_id)["committed_units"] == 60, (
            "the refused reservation must not touch the line's ledger, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

        one_second_later = validate_success(
            api.create_production_slot(
                {
                    "build_line_id": line_id,
                    "site_order_id": site_order_id,
                    "window_start": "2026-09-11T12:00:01Z",
                    "window_end": "2026-09-11T20:00:00Z",
                    "units": 10,
                },
                production_planner,
            ),
            201,
        )

        assert one_second_later["status"] == "RESERVED", (
            "a window that starts one second past the padded end is admitted, got "
            f"{one_second_later['status']}"
        )
        assert read_build_line(line_id)["committed_units"] == 70, (
            "the accepted reservation adds its ten units to the sixty already held, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

    def test_a_window_ending_exactly_at_the_padded_start_is_rejected(
        self, api, production_planner
    ):
        """The pad is symmetric: an end of 2026-09-06T12:00:00Z collides, 11:59:59Z does not.

        PRD §3.7: "Because the comparison is inclusive on both sides and the pad is
        applied on both sides, two back-to-back windows that merely touch at an instant
        are rejected, and so is a window that begins less than twelve hours after another
        ends."

        Design: Difficulty/resource_temporal_overlap/production_slot_closed_interval_with_changeover_buffer_rejects_touching_windows
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]

        touching = api.create_production_slot(
            {
                "build_line_id": line_id,
                "site_order_id": site_order_id,
                "window_start": "2026-09-05T00:00:00Z",
                "window_end": "2026-09-06T12:00:00Z",
                "units": 10,
            },
            production_planner,
        )

        validate_error(touching, ApiErrorId.ERR_BUILD_SLOT_OVERLAP.value, 409)
        assert read_build_line(line_id)["committed_units"] == 60, (
            "the refused reservation leaves the ledger alone, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

        one_second_earlier = validate_success(
            api.create_production_slot(
                {
                    "build_line_id": line_id,
                    "site_order_id": site_order_id,
                    "window_start": "2026-09-05T00:00:00Z",
                    "window_end": "2026-09-06T11:59:59Z",
                    "units": 10,
                },
                production_planner,
            ),
            201,
        )

        assert one_second_earlier["status"] == "RESERVED", (
            "a window that ends one second before the padded start is admitted, got "
            f"{one_second_earlier['status']}"
        )
        assert read_build_line(line_id)["committed_units"] == 70, (
            "the second reservation is counted as well, got "
            f"{read_build_line(line_id)['committed_units']}"
        )
        assert read_site_order(site_order_id)["projected_delivery_date"].startswith(
            "2026-09-18T00:00:00"
        ), (
            "the later of the two windows still ends 2026-09-11, so the projection is "
            "unchanged at 2026-09-18"
        )


class TestOverlapOutranksCapacity:
    def test_a_window_breaking_both_rules_reports_the_overlap(
        self, api, production_planner
    ):
        """50 units inside the pad on a 20-per-day line answers with the overlap error.

        PRD §2.9: "Beyond path resolution, the checks a request undergoes are strictly
        ordered, and the first failing check determines the response. Two checks that
        would both fail must produce the earlier one's error, which is why the ordering
        below is normative rather than descriptive:"

        Design: Difficulty/priority_pair_validation_conflict/slot_overlap_check_34_outranks_build_capacity_check_49_on_slot_reservation
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]

        both = api.create_production_slot(
            {
                "build_line_id": line_id,
                "site_order_id": site_order_id,
                "window_start": "2026-09-11T06:00:00Z",
                "window_end": "2026-09-11T18:00:00Z",
                "units": 50,
            },
            production_planner,
        )

        validate_error(both, ApiErrorId.ERR_BUILD_SLOT_OVERLAP.value, 409)
        body = both.json()
        assert (
            body["data"]["error_id"] != ApiErrorId.ERR_BUILD_CAPACITY_EXCEEDED.value
        ), (
            "a half-day window of fifty units also exceeds the twenty-unit daily "
            "capacity, but the overlap check is consulted first"
        )
        assert read_build_line(line_id)["committed_units"] == 60, (
            "the rejected reservation must not perturb the ledger, got "
            f"{read_build_line(line_id)['committed_units']}"
        )
        site_order = read_site_order(site_order_id)
        assert site_order["slack_days"] == 7, (
            f"the surviving slot still projects seven days of slack, got "
            f"{site_order['slack_days']}"
        )
        assert site_order["commitment_status"] == "COMMITTED", (
            f"the site order is untouched by the refusal, got {site_order['commitment_status']}"
        )

    def test_clearing_the_buffer_without_shrinking_the_units_surfaces_the_capacity_error(
        self, api, production_planner
    ):
        """The same 50 units in a clear window fail on capacity, and 20 units fit exactly.

        PRD §3.7: "Finally the interval must be physically buildable: the requested
        `units` may not exceed the line's `daily_capacity_units` multiplied by the
        interval's span in days, where the span is the floor of the whole-day difference
        between `window_end` and `window_start`, plus one, because the interval is closed
        at both ends and a window that starts and ends on the same day still gives the
        line one day of capacity."

        Design: Difficulty/priority_pair_validation_conflict/slot_overlap_check_34_outranks_build_capacity_check_49_on_slot_reservation
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]

        too_many = api.create_production_slot(
            {
                "build_line_id": line_id,
                "site_order_id": site_order_id,
                "window_start": "2026-09-12T00:00:00Z",
                "window_end": "2026-09-12T18:00:00Z",
                "units": 50,
            },
            production_planner,
        )

        validate_error(too_many, ApiErrorId.ERR_BUILD_CAPACITY_EXCEEDED.value, 422)
        assert read_build_line(line_id)["committed_units"] == 60, (
            "the capacity refusal leaves the ledger alone, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

        exactly_one_day = validate_success(
            api.create_production_slot(
                {
                    "build_line_id": line_id,
                    "site_order_id": site_order_id,
                    "window_start": "2026-09-12T00:00:00Z",
                    "window_end": "2026-09-12T18:00:00Z",
                    "units": 20,
                },
                production_planner,
            ),
            201,
        )

        assert exactly_one_day["status"] == "RESERVED", (
            "a same-day window still gives the line one day of capacity, so twenty "
            f"units fit exactly, got {exactly_one_day['status']}"
        )
        assert read_build_line(line_id)["committed_units"] == 80, (
            "the accepted twenty units join the sixty already committed, got "
            f"{read_build_line(line_id)['committed_units']}"
        )


class TestCommittedUnitsLedger:
    def test_cancelling_each_reservation_walks_the_ledger_back_to_zero(
        self, api, production_planner
    ):
        """80 becomes 20 and then 0, matching the sum over the line's surviving slots.

        PRD §2.11: "The first is a build line's `committed_units`, which must at all
        times equal the sum of `units` over that line's production slots whose `status`
        is `RESERVED`, `CONFIRMED` or `IN_BUILD`."

        Design: Difficulty/compensating_invariant/build_line_committed_units_reconciles_with_active_slots_after_cancellation
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]
        slot_a = state["slot"]
        slot_b = reserve_production_slot(
            line_id,
            site_order_id,
            window_start="2026-09-15T00:00:00Z",
            window_end="2026-09-16T00:00:00Z",
            units=20,
        )
        assert read_build_line(line_id)["committed_units"] == 80, (
            "sixty plus twenty units are committed before any cancellation, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

        validate_success(
            api.cancel_production_slot(
                slot_a["id"],
                {"cancellation_reason": "chain deferred the flagship site"},
                production_planner,
            )
        )

        mid = read_build_line(line_id)["committed_units"]
        assert mid == 20, (
            "cancelling the sixty-unit slot decrements by exactly that slot's units, "
            f"got {mid}"
        )
        assert mid == _reconstructed_committed_units(
            api, production_planner, line_id
        ), "the ledger must equal the sum over the line's surviving counted slots"
        assert read_production_slot(slot_b["id"])["status"] == "RESERVED", (
            "the other reservation is untouched by the cancellation"
        )

        validate_success(
            api.cancel_production_slot(
                slot_b["id"],
                {"cancellation_reason": "remaining units moved to a partner plant"},
                production_planner,
            )
        )

        final = read_build_line(line_id)["committed_units"]
        assert final == 0, (
            f"the second cancellation lands the ledger back on zero, got {final}"
        )
        assert final == _reconstructed_committed_units(
            api, production_planner, line_id
        ), "no counted slot survives, so the reconstructed sum is zero as well"
        assert read_production_slot(slot_a["id"])["status"] == "CANCELLED", (
            "the first slot is terminal at CANCELLED"
        )
        site_order = read_site_order(site_order_id)
        assert site_order["fulfillment_status"] == "PENDING", (
            f"with no active slot the order resets to PENDING, got {site_order['fulfillment_status']}"
        )
        assert site_order["commitment_status"] == "UNSCHEDULED", (
            f"the commitment dimension resets too, got {site_order['commitment_status']}"
        )
        assert site_order["slack_days"] is None, (
            f"the slack is cleared to null, got {site_order['slack_days']}"
        )

    def test_completing_one_slot_and_cancelling_the_other_reconciles_the_ledger(
        self, api, production_planner
    ):
        """CONFIRM leaves 80, COMPLETE drops it to 20 and the cancellation to 0.

        PRD §2.11: "Reserving a slot adds its `units`; completing a build subtracts them,
        because the units have left the forward commitment and become physical inventory;
        cancelling a reserved or confirmed slot subtracts them, restoring the invariant
        exactly. Confirming a slot moves it between two counted states and therefore
        leaves `committed_units` unchanged."

        Design: Difficulty/compensating_invariant/build_line_committed_units_reconciles_with_active_slots_after_cancellation
        """
        state = _line_with_one_reserved_slot()
        line_id = state["build_line"]["id"]
        site_order_id = state["site_order"]["id"]
        slot_a = state["slot"]
        slot_b = reserve_production_slot(
            line_id,
            site_order_id,
            window_start="2026-09-15T00:00:00Z",
            window_end="2026-09-16T00:00:00Z",
            units=20,
        )

        advance_slot(slot_a["id"], "CONFIRM")
        assert read_build_line(line_id)["committed_units"] == 80, (
            "confirming moves the slot between two counted states, so the ledger is "
            f"unchanged, got {read_build_line(line_id)['committed_units']}"
        )
        assert _reconstructed_committed_units(api, production_planner, line_id) == 80, (
            "the reconstructed sum counts CONFIRMED slots as well"
        )

        set_clock("2026-09-08T00:00:00Z")
        advance_slot(slot_a["id"], "START")
        assert read_build_line(line_id)["committed_units"] == 80, (
            "IN_BUILD is still a counted state, got "
            f"{read_build_line(line_id)['committed_units']}"
        )

        advance_slot(slot_a["id"], "COMPLETE")

        after_complete = read_build_line(line_id)["committed_units"]
        assert after_complete == 20, (
            "completing the sixty-unit build subtracts those units, leaving only the "
            f"twenty still reserved, got {after_complete}"
        )
        assert after_complete == _reconstructed_committed_units(
            api, production_planner, line_id
        ), "a COMPLETED slot has left the counted set, so the sums agree at twenty"

        validate_success(
            api.cancel_production_slot(
                slot_b["id"],
                {"cancellation_reason": "remaining units moved to a partner plant"},
                production_planner,
            )
        )

        final = read_build_line(line_id)["committed_units"]
        assert final == 0, (
            f"cancelling the last reservation empties the ledger, got {final}"
        )
        assert final == _reconstructed_committed_units(
            api, production_planner, line_id
        ), "no RESERVED, CONFIRMED or IN_BUILD slot survives on the line"
        site_order = read_site_order(site_order_id)
        assert site_order["fulfillment_status"] == "BUILT", (
            "the COMPLETED slot keeps the order out of the reset, so it stays BUILT, got "
            f"{site_order['fulfillment_status']}"
        )
        assert site_order["commitment_status"] == "COMMITTED", (
            "the completed slot still drives a 2026-09-18 projection against a "
            f"2026-09-25 promise, got {site_order['commitment_status']}"
        )


class TestEnergyCompatibility:
    def test_an_electric_model_cannot_be_slotted_on_a_gas_only_line(
        self, api, production_planner
    ):
        """The same payload is refused on LN-GAS and accepted on an ELECTRIC line.

        PRD §3.7: "The referenced model's `energy_type` must be a member of the line's
        `supported_energy_types`, otherwise `ERR_LINE_ENERGY_INCOMPATIBLE` — a gas fryer
        cannot be built on an electric-only line."

        Design: Corner/validations/build_line_energy_compatibility_is_checked_against_the_models_energy_type
        """
        state = setup_program_with_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-20T00:00:00Z",
                "unit_count": 10,
            },
            **PLAIN_RELEASE,
        )
        site_order_id = state["site_order"]["id"]
        gas_line = create_build_line(
            line_code="LN-GAS", supported_energy_types=["GAS"]
        )
        electric_line = create_build_line(**ELECTRIC_LINE)
        window = {
            "window_start": "2026-09-07T00:00:00Z",
            "window_end": "2026-09-08T00:00:00Z",
            "units": 10,
        }

        refused = api.create_production_slot(
            {"build_line_id": gas_line["id"], "site_order_id": site_order_id, **window},
            production_planner,
        )

        validate_error(refused, ApiErrorId.ERR_LINE_ENERGY_INCOMPATIBLE.value, 422)
        assert read_build_line(gas_line["id"])["committed_units"] == 0, (
            "no slot row was created on the gas line, got "
            f"{read_build_line(gas_line['id'])['committed_units']}"
        )

        accepted = validate_success(
            api.create_production_slot(
                {
                    "build_line_id": electric_line["id"],
                    "site_order_id": site_order_id,
                    **window,
                },
                production_planner,
            ),
            201,
        )

        assert accepted["status"] == "RESERVED", (
            "the identical payload succeeds on a line tooled for ELECTRIC, got "
            f"{accepted['status']}"
        )
        assert read_build_line(electric_line["id"])["committed_units"] == 10, (
            "the electric line now carries the ten units, got "
            f"{read_build_line(electric_line['id'])['committed_units']}"
        )
        site_order = read_site_order(site_order_id)
        assert site_order["fulfillment_status"] == "SCHEDULED", (
            f"the accepted reservation schedules the order, got {site_order['fulfillment_status']}"
        )
        assert site_order["commitment_status"] == "COMMITTED", (
            "the 2026-09-15 projection beats the 2026-09-20 promise, got "
            f"{site_order['commitment_status']}"
        )


class TestCancelledSlotIsTerminal:
    def test_a_cancelled_slot_refuses_a_second_cancellation_and_any_progress(
        self, api, production_planner
    ):
        """Both replays answer ERR_PRODUCTION_STATE_INVALID and the ledger stays at zero.

        PRD §3.7: "A `progress` value the slot's current `status` does not admit, or an
        attempt to start or complete a build before the clock has reached `window_start`,
        is rejected with `ERR_PRODUCTION_STATE_INVALID`."

        Design: Corner/validations/cancelled_slot_rejects_a_second_cancellation_and_any_further_progress
        """
        state = setup_program_with_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-20T00:00:00Z",
                "unit_count": 10,
            },
            **PLAIN_RELEASE,
        )
        line = create_build_line(**ELECTRIC_LINE)
        slot = reserve_production_slot(line["id"], state["site_order"]["id"], units=100)
        assert slot["status"] == "RESERVED", (
            "one hundred units over five span days is exactly the capacity boundary, so "
            f"the reservation stands, got {slot['status']}"
        )

        cancelled = validate_success(
            api.cancel_production_slot(
                slot["id"],
                {"cancellation_reason": "Chain deferred the remodel"},
                production_planner,
            )
        )
        assert cancelled["status"] == "CANCELLED", (
            f"the cancellation is accepted once, got {cancelled['status']}"
        )

        replay = api.cancel_production_slot(
            slot["id"],
            {"cancellation_reason": "Cancelled again by mistake"},
            production_planner,
        )
        validate_error(replay, ApiErrorId.ERR_PRODUCTION_STATE_INVALID.value, 409)

        progress = api.advance_build_progress(
            slot["id"], {"progress": "CONFIRM"}, production_planner
        )
        validate_error(progress, ApiErrorId.ERR_PRODUCTION_STATE_INVALID.value, 409)

        assert read_build_line(line["id"])["committed_units"] == 0, (
            "the units were returned exactly once, so the ledger must not be "
            f"double-decremented, got {read_build_line(line['id'])['committed_units']}"
        )
        assert read_production_slot(slot["id"])["status"] == "CANCELLED", (
            "CANCELLED is terminal and survives both refused calls"
        )
        site_order = read_site_order(state["site_order"]["id"])
        assert site_order["fulfillment_status"] == "PENDING", (
            f"the cancellation had already reset the order, got {site_order['fulfillment_status']}"
        )
        assert site_order["commitment_status"] == "UNSCHEDULED", (
            f"and its commitment dimension too, got {site_order['commitment_status']}"
        )


class TestSlotWellFormedness:
    def test_a_zero_length_window_is_refused_before_the_referential_checks(
        self, api, production_planner
    ):
        """window_end equal to window_start is ERR_INVALID_REQUEST, not a not-found.

        PRD §3.7: "The planner names the `build_line_id` and the `site_order_id`, gives
        the inclusive `window_start` and `window_end` of the build interval — the end must
        be strictly later than the start — and states the `units` to be built in that
        interval, at least one."

        Design: Corner/entities/production_slot_window_end_not_after_window_start_returns_invalid_request
        """
        set_clock()
        model = create_equipment_model(**PLAIN_MODEL)
        account = create_chain_account()
        config = create_chain_configuration(
            account["id"], model["id"], account["version"], **PLAIN_CONFIG
        )
        assert config["status"] == "DRAFT", (
            f"the configuration is left unreleased on purpose, got {config['status']}"
        )
        create_construction_program(account["id"], site_count_planned=3)
        line = create_build_line(**ELECTRIC_LINE)

        response = api.create_production_slot(
            {
                "build_line_id": line["id"],
                "site_order_id": NON_EXISTENT_UUID,
                "window_start": "2026-09-07T00:00:00Z",
                "window_end": "2026-09-07T00:00:00Z",
                "units": 5,
            },
            production_planner,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        error_id = response.json()["data"]["error_id"]
        assert error_id != ApiErrorId.ERR_PRODUCTION_RESOURCE_NOT_FOUND.value, (
            "well-formedness precedes resolution of the referenced site order, so the "
            "unknown identifier must not be the reported problem"
        )
        assert error_id != ApiErrorId.ERR_CHAIN_RESOURCE_NOT_FOUND.value, (
            "the same holds for the chain-side resolution error"
        )
        assert read_build_line(line["id"])["committed_units"] == 0, (
            "no slot was created, so the line holds nothing, got "
            f"{read_build_line(line['id'])['committed_units']}"
        )
        _, meta = validate_paginated(
            api.list_production_slots(production_planner, {"build_line_id": line["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the line has no slot rows at all, got {meta['total_count']}"
        )
