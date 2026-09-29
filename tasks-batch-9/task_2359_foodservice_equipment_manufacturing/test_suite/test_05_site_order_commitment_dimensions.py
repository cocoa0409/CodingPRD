"""Site orders: the two independent dimensions, the slack bands, waivers and delivery events."""

from test_helpers import (
    ApiErrorId,
    advance_slot,
    create_build_line,
    create_chain_account,
    create_chain_configuration,
    create_construction_program,
    create_equipment_model,
    create_site_order,
    make_chain_admin_headers,
    read_build_line,
    read_construction_program,
    read_production_slot,
    read_site_order,
    reserve_production_slot,
    set_clock,
    setup_completed_slot,
    setup_program_with_site_order,
    setup_scheduled_site_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# The ELECTRIC-only build line, the unbranded configuration and the
# single-controls model the programme geometry in this file is proved against.
ELECTRIC_LINE = {"supported_energy_types": ["ELECTRIC"]}
PLAIN_MODEL = {"supported_controls_packages": ["STANDARD_DIAL"]}
PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}
PLAIN_RELEASE = {"model_overrides": PLAIN_MODEL, "config_overrides": PLAIN_CONFIG}


class TestDimensionsMoveIndependently:
    def test_a_remedial_slot_breaches_the_commitment_while_fulfilment_stays_built(self):
        """A later slot drags commitment_status to BREACHED with fulfillment_status still BUILT.

        PRD §3.7: "A successful reservation sets the slot's `status` to `RESERVED`,
        adds its `units` to the line's `committed_units`, moves the site order's
        fulfilment dimension `PENDING → SCHEDULED` (a no-op when the site order has
        already advanced past `PENDING`, which is how the two site-order dimensions move
        independently), recomputes the site order's `projected_delivery_date`,
        `slack_days` and `commitment_status`, and re-derives the programme's
        `commit_posture`."

        Design: Difficulty/non_linear_state_machine/site_order_fulfillment_and_commitment_dimensions_move_independently
        """
        state = setup_completed_slot(**PLAIN_RELEASE)
        assert state["slot"]["status"] == "COMPLETED", (
            f"the first slot was walked to COMPLETED, got {state['slot']['status']}"
        )
        before = read_site_order(state["site_order"]["id"])
        assert before["fulfillment_status"] == "BUILT", (
            "completing the build carries the order to BUILT, got "
            f"{before['fulfillment_status']}"
        )
        assert before["commitment_status"] == "COMMITTED", (
            "the completed window ends 2026-09-11, so the projection is 2026-09-18 "
            f"against a 2026-09-25 promise, got {before['commitment_status']}"
        )
        assert before["slack_days"] == 7, (
            f"2026-09-25 minus 2026-09-18 is seven whole days, got {before['slack_days']}"
        )

        remedial = reserve_production_slot(
            state["build_line"]["id"],
            state["site_order"]["id"],
            window_start="2026-09-24T00:00:00Z",
            window_end="2026-09-26T00:00:00Z",
            units=20,
        )

        assert remedial["status"] == "RESERVED", (
            f"the remedial slot is reserved, got {remedial['status']}"
        )
        after = read_site_order(state["site_order"]["id"])
        assert after["fulfillment_status"] == "BUILT", (
            "reserving another slot is a no-op on a site order that has already left "
            f"PENDING, so the fulfilment dimension stays BUILT, got "
            f"{after['fulfillment_status']}"
        )
        assert after["projected_delivery_date"].startswith("2026-10-03T00:00:00"), (
            "the latest surviving window end is 2026-09-26, plus seven days of transit "
            f"is 2026-10-03, got {after['projected_delivery_date']}"
        )
        assert after["slack_days"] == -8, (
            "2026-09-25 minus 2026-10-03 is a shortfall of eight days, got "
            f"{after['slack_days']}"
        )
        assert after["commitment_status"] == "BREACHED", (
            "a shortfall of four days or more is BREACHED, so the commitment dimension "
            f"moves while the fulfilment one does not, got {after['commitment_status']}"
        )
        program = read_construction_program(
            state["program"]["id"], state["chain_account"]["id"]
        )
        assert program["commit_posture"] == "BREACHED", (
            "the programme's only considered child is BREACHED, so the posture follows, "
            f"got {program['commit_posture']}"
        )

    def test_shipping_a_breached_site_order_advances_only_the_fulfilment_dimension(
        self, api, production_planner
    ):
        """SHIP walks BUILT to SHIPPED and leaves the BREACHED commitment untouched.

        PRD §2.8: "A site order carries two independent status dimensions on one row:
        `fulfillment_status` tracks physical progress and is driven by production-slot
        transitions plus shipping events, while `commitment_status` tracks the
        delivery-date promise and is recomputed whenever the slot set, the clock or the
        fulfilment dimension changes."

        Design: Difficulty/non_linear_state_machine/site_order_fulfillment_and_commitment_dimensions_move_independently
        """
        state = setup_completed_slot(**PLAIN_RELEASE)
        reserve_production_slot(
            state["build_line"]["id"],
            state["site_order"]["id"],
            window_start="2026-09-24T00:00:00Z",
            window_end="2026-09-26T00:00:00Z",
            units=20,
        )
        breached = read_site_order(state["site_order"]["id"])
        assert breached["commitment_status"] == "BREACHED", (
            f"the remedial slot breaches the promise, got {breached['commitment_status']}"
        )
        assert breached["fulfillment_status"] == "BUILT", (
            f"the order is still BUILT before shipping, got {breached['fulfillment_status']}"
        )

        shipped = validate_success(
            api.record_fulfillment_event(
                state["site_order"]["id"], {"event": "SHIP"}, production_planner
            )
        )

        assert shipped["fulfillment_status"] == "SHIPPED", (
            f"SHIP takes a BUILT order to SHIPPED, got {shipped['fulfillment_status']}"
        )
        assert shipped["commitment_status"] == "BREACHED", (
            "the shipping milestone drives only the fulfilment axis, so the commitment "
            f"axis stays BREACHED, got {shipped['commitment_status']}"
        )
        assert shipped["slack_days"] == -8, (
            f"the eight-day shortfall survives the shipment, got {shipped['slack_days']}"
        )
        assert shipped["projected_delivery_date"].startswith("2026-10-03T00:00:00"), (
            "the projection is still driven by the latest surviving window end, got "
            f"{shipped['projected_delivery_date']}"
        )


class TestSlackBandBoundary:
    def test_three_days_short_is_at_risk_while_four_days_short_is_breached(self):
        """Two sites one day apart against the same 2026-09-18 projection split at the band edge.

        PRD §3.6: "Both boundaries are inclusive on the tighter side — slack of exactly
        zero is `COMMITTED`, and slack of exactly negative three is `AT_RISK` while
        negative four is `BREACHED`."

        Design: Difficulty/boundary_precision_check/slack_days_exactly_negative_at_risk_grace_days_is_at_risk_not_breached
        """
        state = setup_program_with_site_order(
            program_overrides={"program_type": "REMODEL"},
            site_order_overrides={
                "site_code": "SITE-3",
                "committed_delivery_date": "2026-09-15T00:00:00Z",
                "unit_count": 20,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        site_three = state["site_order"]
        site_four = create_site_order(
            state["program"]["id"],
            state["config"]["id"],
            account_id,
            site_code="SITE-4",
            committed_delivery_date="2026-09-14T00:00:00Z",
            unit_count=20,
        )
        line_one = create_build_line(**ELECTRIC_LINE)
        line_two = create_build_line(line_code="LN-2", **ELECTRIC_LINE)

        reserve_production_slot(line_one["id"], site_three["id"], units=20)
        reserve_production_slot(line_two["id"], site_four["id"], units=20)

        three = read_site_order(site_three["id"])
        four = read_site_order(site_four["id"])
        assert three["projected_delivery_date"].startswith("2026-09-18T00:00:00"), (
            "the window ends 2026-09-11 and transit adds seven days, got "
            f"{three['projected_delivery_date']}"
        )
        assert three["slack_days"] == -3, (
            "2026-09-15 minus 2026-09-18 is a three-day shortfall, got "
            f"{three['slack_days']}"
        )
        assert three["commitment_status"] == "AT_RISK", (
            "a shortfall of exactly three days sits inside the grace, so the site is "
            f"AT_RISK and not BREACHED, got {three['commitment_status']}"
        )
        assert four["projected_delivery_date"].startswith("2026-09-18T00:00:00"), (
            "the second line's identical window projects to the same date, got "
            f"{four['projected_delivery_date']}"
        )
        assert four["slack_days"] == -4, (
            "2026-09-14 minus 2026-09-18 is a four-day shortfall, got "
            f"{four['slack_days']}"
        )
        assert four["commitment_status"] == "BREACHED", (
            "one day past the grace is BREACHED, got "
            f"{four['commitment_status']}"
        )
        program = read_construction_program(state["program"]["id"], account_id)
        assert program["commit_posture"] == "BREACHED", (
            "the posture takes the worse of the two considered children, got "
            f"{program['commit_posture']}"
        )

    def test_a_later_slot_slides_a_committed_site_into_at_risk_at_exactly_three_days_short(
        self,
    ):
        """Re-planning from a 2026-09-09 projection to 2026-09-18 lands on AT_RISK, not BREACHED.

        PRD §3.6: "`slack_days` then selects the status against a three-day grace: zero
        or more days of slack means `COMMITTED`; a shortfall of one, two or three days
        means `AT_RISK`; a shortfall of four days or more means `BREACHED`."

        Design: Difficulty/boundary_precision_check/slack_days_exactly_negative_at_risk_grace_days_is_at_risk_not_breached
        """
        state = setup_scheduled_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-15T00:00:00Z",
                "unit_count": 10,
            },
            line_overrides=ELECTRIC_LINE,
            slot_overrides={
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-02T00:00:00Z",
                "units": 10,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        early = read_site_order(state["site_order"]["id"])
        assert early["projected_delivery_date"].startswith("2026-09-09T00:00:00"), (
            "the first window ends 2026-09-02, so the projection is 2026-09-09, got "
            f"{early['projected_delivery_date']}"
        )
        assert early["slack_days"] == 6, (
            f"2026-09-15 minus 2026-09-09 is six days of slack, got {early['slack_days']}"
        )
        assert early["commitment_status"] == "COMMITTED", (
            f"positive slack is COMMITTED, got {early['commitment_status']}"
        )

        reserve_production_slot(
            state["build_line"]["id"],
            state["site_order"]["id"],
            window_start="2026-09-07T00:00:00Z",
            window_end="2026-09-11T00:00:00Z",
            units=10,
        )

        late = read_site_order(state["site_order"]["id"])
        assert late["projected_delivery_date"].startswith("2026-09-18T00:00:00"), (
            "the later window now drives the projection to 2026-09-18, got "
            f"{late['projected_delivery_date']}"
        )
        assert late["slack_days"] == -3, (
            f"the shortfall is exactly three days, got {late['slack_days']}"
        )
        assert late["commitment_status"] == "AT_RISK", (
            "a three-day shortfall walks COMMITTED to AT_RISK rather than to BREACHED, "
            f"got {late['commitment_status']}"
        )
        program = read_construction_program(state["program"]["id"], account_id)
        assert program["commit_posture"] == "AT_RISK", (
            "the programme's only considered child is AT_RISK, so the posture is "
            f"AT_RISK and not BREACHED, got {program['commit_posture']}"
        )


class TestCommitmentWaiver:
    def test_waiving_the_only_at_risk_site_returns_the_programme_to_on_track(self, api):
        """The waived child leaves the considered set while keeping its own projection.

        PRD §3.6: "`WAIVED` is terminal and sticky: the commitment calculation
        continues to refresh `projected_delivery_date` and `slack_days` on that site
        order but never overwrites `commitment_status` again."

        Design: Corner/state_machines/program_posture_returns_to_on_track_when_its_only_at_risk_site_order_is_waived
        """
        state = setup_scheduled_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-15T00:00:00Z",
                "unit_count": 10,
            },
            line_overrides=ELECTRIC_LINE,
            slot_overrides={"units": 10},
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        assert state["program"]["commit_posture"] == "ON_TRACK", (
            "an empty programme always reports ON_TRACK, got "
            f"{state['program']['commit_posture']}"
        )
        before = read_construction_program(state["program"]["id"], account_id)
        assert before["commit_posture"] == "AT_RISK", (
            "the single child is three days short, so the posture is AT_RISK, got "
            f"{before['commit_posture']}"
        )

        waived = validate_success(
            api.waive_commitment(
                state["site_order"]["id"],
                {"waiver_reason": "Chain accepted a two-week late handover"},
                make_chain_admin_headers(account_id),
            )
        )

        assert waived["commitment_status"] == "WAIVED", (
            "waiving an AT_RISK site takes the commitment dimension to WAIVED, got "
            f"{waived['commitment_status']}"
        )
        assert waived["waiver_reason"] == "Chain accepted a two-week late handover", (
            f"the supplied reason is stored verbatim, got {waived['waiver_reason']}"
        )
        assert waived["slack_days"] == -3, (
            "the waiver freezes the status but not the arithmetic, so the three-day "
            f"shortfall is still reported, got {waived['slack_days']}"
        )
        assert waived["projected_delivery_date"].startswith("2026-09-18T00:00:00"), (
            "the projection keeps refreshing on a waived site order, got "
            f"{waived['projected_delivery_date']}"
        )
        assert waived["fulfillment_status"] == "SCHEDULED", (
            "the waiver touches only the commitment axis, so the fulfilment axis stays "
            f"SCHEDULED, got {waived['fulfillment_status']}"
        )
        after = read_construction_program(state["program"]["id"], account_id)
        assert after["commit_posture"] == "ON_TRACK", (
            "a WAIVED child is excluded from consideration, leaving an empty considered "
            f"set and an ON_TRACK posture, got {after['commit_posture']}"
        )
        assert after["version"] > before["version"], (
            "landing on a new posture increments the programme's version, got "
            f"{after['version']} against {before['version']}"
        )


class TestSlotCancellationBubblesUp:
    def test_the_survivor_keeps_the_order_scheduled_and_the_last_cancellation_resets_it(
        self, api, production_planner
    ):
        """Cancelling one of two slots re-projects; cancelling the last one nulls everything.

        PRD §3.7: "It subtracts the slot's `units` from the line's `committed_units`,
        restoring the capacity invariant, and if the site order is left with no slot in
        `RESERVED`, `CONFIRMED`, `IN_BUILD` or `COMPLETED`, resets that site order's
        fulfilment dimension `SCHEDULED → PENDING` and its commitment dimension to
        `UNSCHEDULED`, clearing `projected_delivery_date` and `slack_days` to null, and
        then re-derives the programme's `commit_posture`."

        Design: Corner/state_machines/cancelling_the_last_active_slot_bubbles_the_site_order_back_to_pending
        """
        state = setup_scheduled_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={"unit_count": 10},
            line_overrides=ELECTRIC_LINE,
            slot_overrides={
                "window_start": "2026-09-07T00:00:00Z",
                "window_end": "2026-09-08T00:00:00Z",
                "units": 10,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        slot_a = state["slot"]
        slot_b = reserve_production_slot(
            state["build_line"]["id"],
            state["site_order"]["id"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
            units=10,
        )
        assert read_build_line(state["build_line"]["id"])["committed_units"] == 20, (
            "both reservations are counted against the line before any cancellation"
        )

        validate_success(
            api.cancel_production_slot(
                slot_b["id"],
                {"cancellation_reason": "Chain moved the second tranche"},
                production_planner,
            )
        )

        mid = read_site_order(state["site_order"]["id"])
        assert mid["fulfillment_status"] == "SCHEDULED", (
            "one active slot survives, so the order does not bubble back, got "
            f"{mid['fulfillment_status']}"
        )
        assert mid["projected_delivery_date"].startswith("2026-09-15T00:00:00"), (
            "the survivor's window ends 2026-09-08, so the projection re-selects to "
            f"2026-09-15, got {mid['projected_delivery_date']}"
        )
        assert mid["slack_days"] == 10, (
            f"2026-09-25 minus 2026-09-15 is ten days of slack, got {mid['slack_days']}"
        )
        assert mid["commitment_status"] == "COMMITTED", (
            f"positive slack is COMMITTED, got {mid['commitment_status']}"
        )
        assert read_build_line(state["build_line"]["id"])["committed_units"] == 10, (
            "the cancelled slot's ten units are returned to the line"
        )

        validate_success(
            api.cancel_production_slot(
                slot_a["id"],
                {"cancellation_reason": "Chain paused the site"},
                production_planner,
            )
        )

        final = read_site_order(state["site_order"]["id"])
        assert final["fulfillment_status"] == "PENDING", (
            "with no active slot left the fulfilment dimension resets to PENDING, got "
            f"{final['fulfillment_status']}"
        )
        assert final["commitment_status"] == "UNSCHEDULED", (
            "the commitment dimension resets to UNSCHEDULED, got "
            f"{final['commitment_status']}"
        )
        assert final["projected_delivery_date"] is None, (
            f"the projection is cleared to null, got {final['projected_delivery_date']}"
        )
        assert final["slack_days"] is None, (
            f"the slack is cleared to null, got {final['slack_days']}"
        )
        assert read_construction_program(state["program"]["id"], account_id)[
            "commit_posture"
        ] == "ON_TRACK", (
            "an UNSCHEDULED child is excluded from consideration, so the posture is "
            "ON_TRACK"
        )
        assert read_build_line(state["build_line"]["id"])["committed_units"] == 0, (
            "both cancellations have restored the whole of the line's capacity"
        )


class TestProjectionSelection:
    def test_the_latest_window_end_wins_and_a_cancellation_re_selects_the_earlier_slot(
        self, api, production_planner
    ):
        """Creating the later window first still projects from it, and cancelling it falls back.

        PRD §3.6: "The computation first picks the one slot that drives the projection:
        among the site order's production slots whose `status` is `RESERVED`,
        `CONFIRMED`, `IN_BUILD` or `COMPLETED` — cancelled slots are excluded entirely —
        take the slot with the latest `window_end`, breaking a tie by the earliest
        `created_at`; the resource identifier is never a decision input."

        Design: Corner/calculations/projection_selects_latest_window_end_regardless_of_creation_order_and_skips_cancelled_slots
        """
        state = setup_program_with_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-20T00:00:00Z",
                "unit_count": 10,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        line = create_build_line(**ELECTRIC_LINE)
        late = reserve_production_slot(
            line["id"],
            state["site_order"]["id"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
            units=10,
        )
        early = reserve_production_slot(
            line["id"],
            state["site_order"]["id"],
            window_start="2026-09-07T00:00:00Z",
            window_end="2026-09-08T00:00:00Z",
            units=10,
        )

        with_both = read_site_order(state["site_order"]["id"])
        assert with_both["projected_delivery_date"].startswith("2026-09-28T00:00:00"), (
            "the later window end of 2026-09-21 drives the projection even though it "
            f"was created first, got {with_both['projected_delivery_date']}"
        )
        assert with_both["slack_days"] == -8, (
            f"2026-09-20 minus 2026-09-28 is an eight-day shortfall, got "
            f"{with_both['slack_days']}"
        )
        assert with_both["commitment_status"] == "BREACHED", (
            f"an eight-day shortfall is BREACHED, got {with_both['commitment_status']}"
        )

        validate_success(
            api.cancel_production_slot(
                late["id"],
                {"cancellation_reason": "Late tranche pulled forward"},
                production_planner,
            )
        )

        after = read_site_order(state["site_order"]["id"])
        assert after["projected_delivery_date"].startswith("2026-09-15T00:00:00"), (
            "the cancelled slot leaves the candidate set, so the 2026-09-08 window is "
            f"selected, got {after['projected_delivery_date']}"
        )
        assert after["slack_days"] == 5, (
            f"2026-09-20 minus 2026-09-15 is five days of slack, got {after['slack_days']}"
        )
        assert after["commitment_status"] == "COMMITTED", (
            "the re-selection walks BREACHED back to COMMITTED, got "
            f"{after['commitment_status']}"
        )
        assert read_production_slot(early["id"])["status"] == "RESERVED", (
            "the surviving slot is untouched by the other slot's cancellation"
        )
        assert read_construction_program(state["program"]["id"], account_id)[
            "commit_posture"
        ] == "ON_TRACK", "the only considered child is COMMITTED, so the posture is ON_TRACK"


class TestSiteOrderCreationWellFormedness:
    def test_a_missing_committed_delivery_date_is_refused_before_the_release_gate(
        self, api
    ):
        """Omitting the promise date fails well-formedness, not the not-released check.

        PRD §2.9: "Payload well-formedness — required fields present, enum members
        valid, integers inside their declared bounds, datetimes ISO 8601 UTC,
        `window_end` strictly later than `window_start`, `limit` between 1 and 100
        inclusive, `offset` at least 0, and array-valued fields free of duplicate
        elements. Applies to every endpoint. `ERR_INVALID_REQUEST`."

        Design: Corner/entities/site_order_creation_missing_committed_delivery_date_returns_invalid_request
        """
        set_clock()
        model = create_equipment_model(**PLAIN_MODEL)
        account = create_chain_account()
        config = create_chain_configuration(
            account["id"], model["id"], account["version"], **PLAIN_CONFIG
        )
        assert config["status"] == "DRAFT", (
            "the configuration is deliberately left unreleased so the later gate would "
            f"also fail, got {config['status']}"
        )
        program = create_construction_program(account["id"], site_count_planned=3)
        headers = make_chain_admin_headers(account["id"])

        response = api.create_site_order(
            {
                "construction_program_id": program["id"],
                "chain_configuration_id": config["id"],
                "site_code": "SITE-1",
                "unit_count": 10,
            },
            headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        body = response.json()
        assert (
            body["data"]["error_id"] != ApiErrorId.ERR_CONFIGURATION_NOT_RELEASED.value
        ), (
            "well-formedness is checked before the release gate, so the DRAFT "
            "configuration must not be the reported problem"
        )
        data, meta = validate_paginated(
            api.list_site_orders(headers, {"construction_program_id": program["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the refused create must not have persisted a site order, got {meta['total_count']}"
        )
        assert data == [], f"the programme holds no sites, got {data}"


class TestProgramSiteCapacity:
    def test_only_the_third_site_order_exceeds_a_two_site_programme(self, api):
        """Two individually valid sites are accepted and the third trips the aggregate limit.

        PRD §3.6: "Two gates apply: the referenced configuration's `status` must be
        `RELEASED`, otherwise `ERR_CONFIGURATION_NOT_RELEASED` — a chain cannot commit a
        delivery date against a build the factory is not cleared to make — and the
        programme must not already hold `site_count_planned` site orders, otherwise
        `ERR_PROGRAM_SITE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/program_site_capacity_is_an_aggregate_limit_reached_only_by_the_third_order
        """
        state = setup_program_with_site_order(
            program_overrides={"program_type": "REMODEL", "site_count_planned": 2},
            site_order_overrides={
                "site_code": "SITE-1",
                "committed_delivery_date": "2026-09-20T00:00:00Z",
                "unit_count": 4,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        headers = make_chain_admin_headers(account_id)
        first = state["site_order"]
        second = create_site_order(
            state["program"]["id"],
            state["config"]["id"],
            account_id,
            site_code="SITE-2",
            committed_delivery_date="2026-09-21T00:00:00Z",
            unit_count=4,
        )

        third = api.create_site_order(
            {
                "construction_program_id": state["program"]["id"],
                "chain_configuration_id": state["config"]["id"],
                "site_code": "SITE-3",
                "committed_delivery_date": "2026-09-22T00:00:00Z",
                "unit_count": 4,
            },
            headers,
        )

        validate_error(
            third, ApiErrorId.ERR_PROGRAM_SITE_CAPACITY_EXCEEDED.value, 422
        )
        data, meta = validate_paginated(
            api.list_site_orders(headers, {"construction_program_id": state["program"]["id"]})
        )
        assert meta["total_count"] == 2, (
            f"the programme keeps exactly its two admitted sites, got {meta['total_count']}"
        )
        assert {row["id"] for row in data} == {first["id"], second["id"]}, (
            "the two surviving rows are the first two site orders, got "
            f"{[row['id'] for row in data]}"
        )
        assert all(row["site_code"] != "SITE-3" for row in data), (
            "the refused third site must not have been persisted"
        )
        assert first["commitment_status"] == "UNSCHEDULED", (
            "a new site order holds no slot, so it starts UNSCHEDULED, got "
            f"{first['commitment_status']}"
        )
        assert second["commitment_status"] == "UNSCHEDULED", (
            f"the second site order likewise starts UNSCHEDULED, got "
            f"{second['commitment_status']}"
        )


class TestFulfilmentEvents:
    def test_events_walk_built_to_shipped_to_delivered_and_refuse_an_early_ship(
        self, api, production_planner
    ):
        """SHIP before the build is refused, and DELIVER is terminal on the fulfilment axis.

        PRD §3.7: "`DELIVER` takes it `SHIPPED → DELIVERED`, which is terminal on the
        fulfilment dimension, and recomputes the site order's `commitment_status` and its
        programme's `commit_posture` — delivery is the last moment the promise can be
        re-scored."

        Design: Corner/endpoints/fulfillment_events_walk_built_to_shipped_to_delivered_and_refuse_an_early_ship
        """
        state = setup_scheduled_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-10-15T00:00:00Z",
                "unit_count": 10,
            },
            line_overrides=ELECTRIC_LINE,
            slot_overrides={
                "window_start": "2026-09-07T00:00:00Z",
                "window_end": "2026-09-08T00:00:00Z",
                "units": 10,
            },
            **PLAIN_RELEASE,
        )
        site_order_id = state["site_order"]["id"]
        slot_id = state["slot"]["id"]
        assert state["slot"]["status"] == "RESERVED", (
            f"the slot starts RESERVED, got {state['slot']['status']}"
        )
        opening = read_site_order(site_order_id)
        assert opening["fulfillment_status"] == "SCHEDULED", (
            f"the reservation moved the order to SCHEDULED, got {opening['fulfillment_status']}"
        )
        assert opening["commitment_status"] == "COMMITTED", (
            f"the 2026-09-15 projection beats the promise, got {opening['commitment_status']}"
        )
        assert opening["slack_days"] == 30, (
            f"2026-10-15 minus 2026-09-15 is thirty days of slack, got {opening['slack_days']}"
        )

        early_ship = api.record_fulfillment_event(
            site_order_id, {"event": "SHIP"}, production_planner
        )
        validate_error(early_ship, ApiErrorId.ERR_PRODUCTION_STATE_INVALID.value)
        assert read_site_order(site_order_id)["fulfillment_status"] == "SCHEDULED", (
            "the refused event leaves the fulfilment dimension where it was"
        )

        confirmed = advance_slot(slot_id, "CONFIRM")
        assert confirmed["status"] == "CONFIRMED", (
            f"CONFIRM takes the slot to CONFIRMED, got {confirmed['status']}"
        )
        assert read_site_order(site_order_id)["fulfillment_status"] == "SCHEDULED", (
            "the CONFIRM hop does not touch the site order"
        )

        set_clock("2026-09-07T00:00:00Z")
        started = advance_slot(slot_id, "START")
        assert started["status"] == "IN_BUILD", (
            f"START takes the slot to IN_BUILD, got {started['status']}"
        )
        assert read_site_order(site_order_id)["fulfillment_status"] == "IN_BUILD", (
            "the START hop carries the site order to IN_BUILD"
        )

        completed = advance_slot(slot_id, "COMPLETE")
        assert completed["status"] == "COMPLETED", (
            f"COMPLETE takes the slot to COMPLETED, got {completed['status']}"
        )
        assert read_production_slot(slot_id)["status"] == "COMPLETED", (
            "COMPLETED is terminal and survives a re-read"
        )
        assert read_site_order(site_order_id)["fulfillment_status"] == "BUILT", (
            "the COMPLETE hop carries the site order to BUILT"
        )
        assert read_build_line(state["build_line"]["id"])["committed_units"] == 0, (
            "COMPLETE subtracts the slot's units from the line, because the units are "
            "now built rather than committed"
        )

        shipped = validate_success(
            api.record_fulfillment_event(
                site_order_id, {"event": "SHIP"}, production_planner
            )
        )
        assert shipped["fulfillment_status"] == "SHIPPED", (
            f"SHIP is admitted once the order is BUILT, got {shipped['fulfillment_status']}"
        )
        assert shipped["commitment_status"] == "COMMITTED", (
            f"the promise is still comfortably met, got {shipped['commitment_status']}"
        )

        delivered = validate_success(
            api.record_fulfillment_event(
                site_order_id, {"event": "DELIVER"}, production_planner
            )
        )
        assert delivered["fulfillment_status"] == "DELIVERED", (
            f"DELIVER takes SHIPPED to DELIVERED, got {delivered['fulfillment_status']}"
        )
        assert delivered["slack_days"] == 30, (
            "delivery re-scores the promise against the same projection, got "
            f"{delivered['slack_days']}"
        )

        replay = api.record_fulfillment_event(
            site_order_id, {"event": "DELIVER"}, production_planner
        )
        validate_error(replay, ApiErrorId.ERR_PRODUCTION_STATE_INVALID.value)
        assert read_site_order(site_order_id)["fulfillment_status"] == "DELIVERED", (
            "the refused replay leaves the terminal state intact"
        )


class TestDerivedFieldVisibility:
    def test_a_reservation_makes_the_recomputed_commitment_readable_immediately(self):
        """One reservation and the very next read already carry the projection and the posture.

        PRD §2.8: "Cascades in this system are ordered and complete. When a hop mutates
        a second entity, that mutation happens in full — its own derived fields are
        refreshed, its `updated_at` is bumped and its `version` increments — before the
        next hop reads it."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response_that_causes_them
        """
        state = setup_program_with_site_order(
            program_overrides={"site_count_planned": 3},
            site_order_overrides={
                "committed_delivery_date": "2026-09-20T00:00:00Z",
                "unit_count": 10,
            },
            **PLAIN_RELEASE,
        )
        account_id = state["chain_account"]["id"]
        assert state["program"]["commit_posture"] == "ON_TRACK", (
            "a fresh programme reports ON_TRACK, got "
            f"{state['program']['commit_posture']}"
        )
        assert state["site_order"]["commitment_status"] == "UNSCHEDULED", (
            "a fresh site order holds no slot, got "
            f"{state['site_order']['commitment_status']}"
        )
        assert state["site_order"]["projected_delivery_date"] is None, (
            "the projection starts null, got "
            f"{state['site_order']['projected_delivery_date']}"
        )
        line = create_build_line(**ELECTRIC_LINE)

        slot = reserve_production_slot(
            line["id"],
            state["site_order"]["id"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
            units=10,
        )

        assert slot["status"] == "RESERVED", (
            f"the reservation succeeded, got {slot['status']}"
        )
        first = read_site_order(state["site_order"]["id"])
        assert first["projected_delivery_date"].startswith("2026-09-28T00:00:00"), (
            "the derived projection is already visible on the next read, got "
            f"{first['projected_delivery_date']}"
        )
        assert first["slack_days"] == -8, (
            f"the derived slack is already -8, got {first['slack_days']}"
        )
        assert first["commitment_status"] == "BREACHED", (
            f"the derived commitment status is already BREACHED, got "
            f"{first['commitment_status']}"
        )
        assert first["fulfillment_status"] == "SCHEDULED", (
            "the same reservation moved the fulfilment dimension, got "
            f"{first['fulfillment_status']}"
        )
        assert read_construction_program(state["program"]["id"], account_id)[
            "commit_posture"
        ] == "BREACHED", (
            "the parent posture was re-derived in the same request cycle"
        )
        second = read_site_order(state["site_order"]["id"])
        assert (
            second["projected_delivery_date"] == first["projected_delivery_date"]
            and second["slack_days"] == first["slack_days"]
            and second["commitment_status"] == first["commitment_status"]
        ), (
            "a repeated read returns identical derived values, got "
            f"{second['projected_delivery_date']}, {second['slack_days']}, "
            f"{second['commitment_status']}"
        )
        assert read_build_line(line["id"])["committed_units"] == 10, (
            "the reservation added its ten units to the line's committed total"
        )

