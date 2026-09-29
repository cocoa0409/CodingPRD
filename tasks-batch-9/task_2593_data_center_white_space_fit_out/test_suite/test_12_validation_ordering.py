"""The global rejection ladder seen from the corners: which of two simultaneous
problems a request reports, and which threshold sits exactly on its own edge."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import USER_IDS
from test_helpers.fixtures import (
    CM,
    EC,
    FP,
    MC,
    OM,
    approve_mop,
    commission_cooling_unit,
    create_busway,
    create_cage,
    create_cooling_unit,
    create_hall,
    create_mop,
    create_pdu,
    create_rack,
    create_tenant,
    create_zone,
    install_rack,
    leakage_test,
    place_unit_in_service,
    power_on_rack,
    prove_zone_and_cooling,
    read_busway,
    read_capacity_summary,
    read_cooling_unit,
    read_feed,
    read_hall,
    read_mop,
    read_rack,
    reserve_feed,
    schedule_mop,
    set_clock,
    setup_executing_mop,
    setup_fit_out_hall,
    setup_planning_hall,
    submit_mop,
)


class TestRequestShapeOutranksMissingForeignKey:
    """A feed reservation that names a run that does not exist *and* asks for an illegal
    breaker size reports the payload problem, because request shape sits at level 4 of
    the ladder and body foreign keys at level 6."""

    def _fit_out_hall_with_one_position(self):
        ctx = setup_fit_out_hall("CX50", design_kw_capacity=400.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=10.00,
            required_feed_count=1,
        )
        return ctx

    def test_an_illegal_breaker_size_is_reported_before_the_unknown_run(self):
        """The request names a busway identifier that resolves to nothing and a breaker
        ampacity of 0 where at least 1 is declared; ERR_VALIDATION is what comes back.

        PRD: "When several rules could reject the same request, the API always returns
        the rejection that comes first in the ladder below."

        PRD: "**Request shape (`ERR_VALIDATION`, 422)** — every required field of the
        operation's payload is present; enum-typed fields carry in-domain values;
        numeric fields obey their declared constraints, including strict positivity
        where declared and 2 decimal places on kilowatt fields; datetimes are
        well-formed ISO 8601 UTC instants; every window-bearing payload has its
        `window_end` strictly after its `window_start`; and `step_pct_sequence` is a
        strictly ascending list of integers each between 1 and 100."

        Design: Corner/validations/validation_priority_ordering_body_shape_beats_missing_fk
        """
        ctx = self._fit_out_hall_with_one_position()
        response = api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_1"]["id"],
                "busway_id": NON_EXISTENT_UUID,
                "feed_side": "A",
                "requested_kw": 10.00,
                "breaker_amps": 0,
            },
            EC,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

        rows, meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack_1"]["id"]})
        )
        assert meta["total_count"] == 0, "the refused request reserved nothing"
        assert rows == []
        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(375.00, abs=0.005)

    def test_a_missing_required_field_also_outranks_the_unknown_run(self):
        """Omitting `requested_kw` altogether, again alongside an unknown busway, is the
        same level-4 failure; fixing the shape is what finally reveals the missing run as
        a 404.

        PRD: "**Body foreign-key existence (404)** — each foreign key in the body
        resolves, per §2.5."

        Design: Corner/validations/validation_priority_ordering_body_shape_beats_missing_fk
        """
        ctx = self._fit_out_hall_with_one_position()
        shapeless = api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_1"]["id"],
                "busway_id": NON_EXISTENT_UUID,
                "feed_side": "A",
                "breaker_amps": 32,
            },
            EC,
        )
        validate_error(shapeless, ApiErrorId.ERR_VALIDATION.value, 422)

        well_formed = api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_1"]["id"],
                "busway_id": NON_EXISTENT_UUID,
                "feed_side": "A",
                "requested_kw": 10.00,
                "breaker_amps": 32,
            },
            EC,
        )
        # A caller who fixes the reported problem sees the next problem down the ladder.
        validate_error(well_formed, ApiErrorId.ERR_BUSWAY_NOT_FOUND.value, 404)

        assert read_hall(ctx["hall_id"])["committed_kw"] == pytest.approx(
            0.00, abs=0.005
        )


class TestHallMismatchOutranksGridCollision:
    """A placement that borrows another white space's containment zone *and* lands on an
    occupied floor position reports the cross-parent disagreement, because level 8
    precedes level 11."""

    def _two_halls_with_one_occupied_position(self):
        hall_a = create_hall("CX51")
        zone_a = create_zone(hall_a["id"], "CA-51")
        hall_b = create_hall("CX52")
        zone_b = create_zone(hall_b["id"], "CA-52")
        occupant = create_rack(hall_b["id"], zone_b["id"], "A", 1, design_kw=10.00)
        return {
            "hall_a": hall_a,
            "zone_a": zone_a,
            "hall_b": hall_b,
            "zone_b": zone_b,
            "occupant": occupant,
        }

    def test_the_foreign_zone_is_reported_before_the_occupied_position(self):
        """The request names hall CX52, CX51's containment zone and the already-occupied
        A/1 position; ERR_HALL_MISMATCH is what comes back, not ERR_DUPLICATE_GRID_POSITION.

        PRD: "Any of those disagreements is rejected with `ERR_HALL_MISMATCH` (HTTP 422)
        on rack creation, busway creation, feed reservation, release-packet creation and
        cage creation."

        Design: Corner/validations/rack_create_hall_mismatch_outranks_duplicate_grid_position
        """
        ctx = self._two_halls_with_one_occupied_position()
        response = api_client.create_rack(
            {
                "hall_id": ctx["hall_b"]["id"],
                "containment_zone_id": ctx["zone_a"]["id"],
                "grid_row": "A",
                "grid_col": 1,
                "design_kw": 10.00,
                "u_height": 45,
                "required_feed_count": 2,
            },
            FP,
        )
        validate_error(response, ApiErrorId.ERR_HALL_MISMATCH.value, 422)

        assert read_hall(ctx["hall_b"]["id"])["rack_total_count"] == 1, (
            "only the original occupant stands in CX52"
        )
        assert read_hall(ctx["hall_a"]["id"])["rack_total_count"] == 0, (
            "nothing was placed in CX51 either"
        )
        rows, meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall_b"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["occupant"]["id"]

    def test_repairing_the_zone_reveals_the_grid_collision_beneath_it(self):
        """The very same placement, with CX52's own zone named, is refused on floor
        geometry instead — which is the proof that the collision was there all along.

        PRD: "A rack position is identified by its hall together with its `grid_row` (1
        to 4 characters) and `grid_col` (an integer of at least 1), and that triple is
        unique: two racks may not occupy the same floor position, and an attempt to
        place one is rejected with `ERR_DUPLICATE_GRID_POSITION` (HTTP 409)."

        Design: Corner/validations/rack_create_hall_mismatch_outranks_duplicate_grid_position
        """
        ctx = self._two_halls_with_one_occupied_position()
        validate_error(
            api_client.create_rack(
                {
                    "hall_id": ctx["hall_b"]["id"],
                    "containment_zone_id": ctx["zone_a"]["id"],
                    "grid_row": "A",
                    "grid_col": 1,
                    "design_kw": 10.00,
                    "u_height": 45,
                    "required_feed_count": 2,
                },
                FP,
            ),
            ApiErrorId.ERR_HALL_MISMATCH.value,
            422,
        )
        validate_error(
            api_client.create_rack(
                {
                    "hall_id": ctx["hall_b"]["id"],
                    "containment_zone_id": ctx["zone_b"]["id"],
                    "grid_row": "A",
                    "grid_col": 1,
                    "design_kw": 10.00,
                    "u_height": 45,
                    "required_feed_count": 2,
                },
                FP,
            ),
            ApiErrorId.ERR_DUPLICATE_GRID_POSITION.value,
            409,
        )

        free = create_rack(
            ctx["hall_b"]["id"], ctx["zone_b"]["id"], "A", 2, design_kw=10.00
        )
        assert free["grid_col"] == 2, "the next position along is unoccupied"
        assert read_hall(ctx["hall_b"]["id"])["rack_total_count"] == 2


class TestContainmentGateOutranksTheCoolingMargin:
    """A cabinet standing behind an untested aisle in a room with no cooling in duty
    fails both the containment gate and the margin gate; containment is level 32 and the
    margin is level 43, so containment reports."""

    def _installed_position_behind_an_untested_aisle(self):
        ctx = setup_fit_out_hall("CX53", design_kw_capacity=400.00)
        rack = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=10.00,
            required_feed_count=2,
        )
        ctx["rack_1"] = rack
        ctx["feed_a"] = reserve_feed(rack["id"], ctx["bw_a"]["id"], "A", 5.00, 32)
        ctx["feed_b"] = reserve_feed(rack["id"], ctx["bw_b"]["id"], "B", 5.00, 32)
        ctx["rack_1"] = install_rack(rack["id"], "AT-0053")
        return ctx

    def test_the_untested_aisle_is_reported_before_the_negative_margin(self):
        """The room publishes no cooling capacity at all, so the recomputed margin would
        be minus 8.50 kW — yet the refusal names the containment zone.

        PRD: "A rack power-on request that is simultaneously short a feed, sitting behind
        a failed containment zone and over the cooling margin reports the containment
        failure (level 32) before the feed topology problem (level 35) and before the
        cooling margin problem (level 43)."

        Design: Corner/validations/rack_power_on_requires_containment_zone_at_pass
        """
        ctx = self._installed_position_behind_an_untested_aisle()
        assert read_hall(ctx["hall_id"])["cooling_capacity_kw"] == pytest.approx(
            0.00, abs=0.005
        ), "CU-1 has never been commissioned, so nothing is in duty"

        validate_error(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC),
            ApiErrorId.ERR_CONTAINMENT_NOT_PASSED.value,
            409,
        )

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "INSTALLED", "the position did not take load"
        assert rack["energized_feed_count"] == 0
        assert read_feed(ctx["feed_a"]["id"])["status"] == "RESERVED"
        assert read_feed(ctx["feed_b"]["id"])["status"] == "RESERVED"

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["custody_ops_count"] == 0
        assert summary["custody_fitout_count"] == 1
        assert summary["thermal_load_kw"] == pytest.approx(0.00, abs=0.005), (
            "an installed position that never energised draws no heat"
        )

    def test_proving_the_aisle_reveals_the_cooling_margin_beneath_it(self):
        """A passing leakage test satisfies level 32 and the same request is then refused
        on the margin at level 43; bringing CU-1 into duty is what finally lets the
        cabinet take load.

        PRD: "The hall's `cooling_margin_kw`, recomputed with this position's heat load
        included, is at least 0.00; otherwise `ERR_COOLING_MARGIN_EXCEEDED`."

        Design: Corner/validations/rack_power_on_requires_containment_zone_at_pass
        """
        ctx = self._installed_position_behind_an_untested_aisle()
        proved = leakage_test(ctx["zone_id"], 5.00, 20.0)
        assert proved["leakage_status"] == "PASS"

        validate_error(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC),
            ApiErrorId.ERR_COOLING_MARGIN_EXCEEDED.value,
            422,
        )
        assert read_rack(ctx["rack_1"]["id"])["status"] == "INSTALLED"

        commission_cooling_unit(ctx["cu_1"]["id"], 22000)
        place_unit_in_service(ctx["cu_1"]["id"])
        assert read_cooling_unit(ctx["cu_1"]["id"])["status"] == "IN_SERVICE"

        powered = power_on_rack(ctx["rack_1"]["id"])
        assert powered["status"] == "POWERED"
        assert powered["energized_feed_count"] == 2

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["thermal_load_kw"] == pytest.approx(8.50, abs=0.005), (
            "10.00 kW at the 0.85 diversity factor"
        )
        assert summary["cooling_margin_kw"] == pytest.approx(110.58, abs=0.005), (
            "119.08 kW of gating capacity less 8.50 kW of demand"
        )
        assert summary["thermal_posture"] == "NOMINAL"


class TestSubmissionRejectsAWindowAlreadyBegun:
    """The submission gate on `window_start` is inclusive of the current instant: a
    window that has already opened is refused, one opening exactly now is accepted."""

    def _hall_with_a_stale_window_and_a_boundary_window(self):
        ctx = setup_planning_hall("CX54", clock="2026-08-15T00:00:00Z")
        ctx["mop_stale"] = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Isolate BW-A1 last week",
            risk_class="MEDIUM",
            window_start="2026-08-10T02:00:00Z",
            window_end="2026-08-10T06:00:00Z",
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        ctx["mop_boundary"] = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_b"]["id"],
            title="Isolate BW-B1 starting now",
            risk_class="MEDIUM",
            window_start="2026-08-15T00:00:00Z",
            window_end="2026-08-15T04:00:00Z",
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        return ctx

    def test_a_window_that_opened_five_days_ago_cannot_be_submitted(self):
        """With the clock at 2026-08-15 a window that opened on 2026-08-10 is refused, and
        the change stays at DRAFT with no approval requirement derived.

        PRD: "The `window_start` must be at or after the logical clock's current instant
        — a window that has already begun cannot be submitted, and the attempt is refused
        with `ERR_OUTSIDE_EXECUTION_WINDOW`."

        Design: Corner/validations/mop_submit_rejects_window_start_in_the_past
        """
        ctx = self._hall_with_a_stale_window_and_a_boundary_window()
        assert ctx["mop_stale"]["status"] == "DRAFT"

        validate_error(
            api_client.submit_mop(
                ctx["mop_stale"]["id"],
                {**EC, "X-User-ID": USER_IDS["ELECTRICAL_CONTRACTOR"]},
            ),
            ApiErrorId.ERR_OUTSIDE_EXECUTION_WINDOW.value,
            409,
        )

        mop = read_mop(ctx["mop_stale"]["id"])
        assert mop["status"] == "DRAFT", "the change never left the author's hands"
        assert mop["required_approval_count"] == 0, (
            "the requirement is derived on a successful submission and nowhere else"
        )
        assert mop["approval_count"] == 0

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 0
        assert hall["release_posture"] == "OPEN"

    def test_a_window_opening_exactly_now_is_accepted(self):
        """A window whose `window_start` equals the clock's current instant satisfies the
        gate, which is what makes the comparison inclusive rather than strict.

        PRD: "On success `required_approval_count` is derived: 2 for a `HIGH` risk MOP, 1
        for `LOW` or `MEDIUM`."

        Design: Corner/validations/mop_submit_rejects_window_start_in_the_past
        """
        ctx = self._hall_with_a_stale_window_and_a_boundary_window()
        submitted = submit_mop(
            ctx["mop_boundary"]["id"], USER_IDS["ELECTRICAL_CONTRACTOR"]
        )
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["window_start"].startswith("2026-08-15T00:00:00")
        assert submitted["required_approval_count"] == 1
        assert submitted["approval_count"] == 0

        assert read_mop(ctx["mop_stale"]["id"])["status"] == "DRAFT", (
            "the stale change is untouched by its sibling's progress"
        )
        assert read_hall(ctx["hall_id"])["open_mop_count"] == 0, (
            "an UNDER_REVIEW change occupies no window"
        )


class TestRoomCeilingIsEvaluatedOverTheAggregate:
    """The room's gate is evaluated on the re-derived ledger, not on the single request,
    so a reservation the run would happily have carried can still be refused."""

    def _small_room_with_one_reservation_already_made(self):
        ctx = setup_fit_out_hall("CX55", design_kw_capacity=100.00)
        for index in (1, 2):
            ctx[f"rack_{index}"] = create_rack(
                ctx["hall_id"],
                ctx["zone_id"],
                "A",
                index,
                design_kw=40.00,
                required_feed_count=1,
            )
        ctx["feed_1"] = reserve_feed(
            ctx["rack_1"]["id"], ctx["bw_a"]["id"], "A", 40.00, 100
        )
        return ctx

    def test_the_second_forty_kilowatt_feed_exhausts_the_room_and_is_refused(self):
        """The run has 196.66 kW of ceiling and the breaker admits 54.63 kW, yet a second
        40.00 kW reservation would leave spare at minus 5.00 kW in a 100.00 kW room.

        PRD: "After the hall power ledger is re-derived with this reservation included,
        `spare_kw` must be at least 0.00. A breach is
        `ERR_HALL_SPARE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/hall_spare_capacity_aggregate_violation_on_second_feed
        """
        ctx = self._small_room_with_one_reservation_already_made()
        before = read_hall(ctx["hall_id"])
        assert before["committed_kw"] == pytest.approx(40.00, abs=0.005)
        assert before["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert before["spare_kw"] == pytest.approx(35.00, abs=0.005)

        validate_error(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack_2"]["id"],
                    "busway_id": ctx["bw_a"]["id"],
                    "feed_side": "A",
                    "requested_kw": 40.00,
                    "breaker_amps": 100,
                },
                EC,
            ),
            ApiErrorId.ERR_HALL_SPARE_CAPACITY_EXCEEDED.value,
            422,
        )

        after = read_hall(ctx["hall_id"])
        assert after["committed_kw"] == pytest.approx(40.00, abs=0.005)
        assert after["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert after["spare_kw"] == pytest.approx(35.00, abs=0.005)

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["committed_kw"] == pytest.approx(40.000, abs=0.0005)
        assert busway["feed_count"] == 1
        assert busway["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the run itself would have carried 80.000 kW without complaint"
        )
        rows, meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack_2"]["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_reservation_landing_spare_on_exactly_zero_is_accepted(self):
        """Asking for 35.00 kW instead lands spare on exactly 0.00 kW, which the gate
        admits because its floor is inclusive.

        PRD: "Note what this means in practice: the room can refuse a reservation that
        the run would happily have carried, because the room's reserve tier may have
        stepped up."

        Design: Corner/validations/hall_spare_capacity_aggregate_violation_on_second_feed
        """
        ctx = self._small_room_with_one_reservation_already_made()
        feed = reserve_feed(ctx["rack_2"]["id"], ctx["bw_a"]["id"], "A", 35.00, 100)
        assert feed["status"] == "RESERVED"
        assert feed["allocated_kw"] == pytest.approx(35.000, abs=0.0005)

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(75.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005), (
            "75.00 kW committed is still inside the first tier"
        )
        assert hall["spare_kw"] == pytest.approx(0.00, abs=0.005), (
            "a room with nothing left to give is not a room in breach"
        )
        assert read_busway(ctx["bw_a"]["id"])["feed_count"] == 2


class TestNotificationRuleIsScopedToMultiTenantHalls:
    """The notification rule is keyed on the hall's own tenancy stance: an identical
    high-risk change schedules with an empty list in a single-tenant room and is refused
    in a multi-tenant room that has a cage in it."""

    def _skeleton(self, code, tenant_mode):
        hall = create_hall(code, tenant_mode=tenant_mode)
        pdu = create_pdu(hall["id"], "PDU-A1", "A")
        busway = create_busway(pdu["id"], "BW-A1")
        return {"hall": hall, "pdu": pdu, "busway": busway}

    def _approved_high_risk_change(self, skeleton, window_start, window_end):
        mop = create_mop(
            skeleton["hall"]["id"],
            "BUSWAY",
            skeleton["busway"]["id"],
            title="Isolate the run for tap-off works",
            risk_class="HIGH",
            window_start=window_start,
            window_end=window_end,
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        submit_mop(mop["id"], USER_IDS["ELECTRICAL_CONTRACTOR"])
        approve_mop(mop["id"], role_headers=CM, user_id=USER_IDS["CHANGE_MANAGER"])
        approve_mop(
            mop["id"], role_headers=OM, user_id=USER_IDS["OPERATIONS_MANAGER"]
        )
        return read_mop(mop["id"])

    def _two_rooms_each_with_an_approved_change(self):
        set_clock("2026-08-01T00:00:00Z")
        single = self._skeleton("CX56", "SINGLE_TENANT")
        multi = self._skeleton("CX57", "MULTI_TENANT")
        tenant = create_tenant("CXT57", contracted_kw=100.00)
        cage = create_cage(
            multi["hall"]["id"], tenant["id"], "CG-1", perimeter_length_m=40.0
        )
        single["mop"] = self._approved_high_risk_change(
            single, "2026-08-10T02:00:00Z", "2026-08-10T06:00:00Z"
        )
        multi["mop"] = self._approved_high_risk_change(
            multi, "2026-08-12T02:00:00Z", "2026-08-12T06:00:00Z"
        )
        multi["tenant"], multi["cage"] = tenant, cage
        return single, multi

    def test_single_tenant_schedules_on_an_empty_list_while_multi_tenant_refuses(self):
        """The single-tenant room takes the schedule with no notified tenants at all; the
        multi-tenant room, which houses one tenant's cage, is refused for the same
        omission.

        PRD: "When the hall's `tenant_mode` is `MULTI_TENANT` and the MOP's `risk_class`
        is `HIGH`, that list must contain every tenant that owns at least one cage in the
        hall — a neighbour whose cage sits beside the work must be told before the work is
        scheduled. An incomplete list is refused with
        `ERR_TENANT_NOTIFICATION_INCOMPLETE`."

        Design: Corner/validations/mop_schedule_notification_rule_applies_only_to_multi_tenant_halls
        """
        single, multi = self._two_rooms_each_with_an_approved_change()
        assert single["mop"]["status"] == "APPROVED"
        assert multi["mop"]["status"] == "APPROVED"

        scheduled = schedule_mop(single["mop"]["id"])
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["tenant_notified_ids"] == [], (
            "a room with no neighbours has nobody to tell"
        )

        validate_error(
            api_client.schedule_mop(multi["mop"]["id"], {}, CM),
            ApiErrorId.ERR_TENANT_NOTIFICATION_INCOMPLETE.value,
            422,
        )
        assert read_mop(multi["mop"]["id"])["status"] == "APPROVED", (
            "the refused change is still waiting to be scheduled"
        )
        assert read_hall(multi["hall"]["id"])["open_mop_count"] == 0

    def test_naming_the_caged_tenant_completes_the_multi_tenant_schedule(self):
        """Supplying the one tenant that owns a cage in CX57 satisfies the rule, and the
        hall then counts one open change while its release posture stays OPEN.

        PRD: "Alongside it, `open_mop_count` is the number of MOPs of that hall whose
        status is `SCHEDULED` or `IN_EXECUTION`."

        Design: Corner/validations/mop_schedule_notification_rule_applies_only_to_multi_tenant_halls
        """
        single, multi = self._two_rooms_each_with_an_approved_change()
        scheduled = schedule_mop(multi["mop"]["id"], [multi["tenant"]["id"]])
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["tenant_notified_ids"] == [multi["tenant"]["id"]]

        hall = read_hall(multi["hall"]["id"])
        assert hall["open_mop_count"] == 1
        assert hall["release_posture"] == "OPEN", (
            "only a change actually IN_EXECUTION locks the room"
        )
        assert read_hall(single["hall"]["id"])["open_mop_count"] == 0, (
            "the single-tenant room's own change is still merely APPROVED"
        )


class TestIsolatedRunOutranksTheBranchBreaker:
    """A reservation aimed at an isolated run with an undersized breaker fails twice
    over; the energisation gate is level 18 and the breaker derate is level 48, so the
    isolated run is what reports."""

    def _hall_with_one_run_held_out_of_service(self):
        ctx = setup_fit_out_hall("CX58", design_kw_capacity=400.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=20.00,
            required_feed_count=1,
        )
        ctx["mop"] = setup_executing_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="LOW",
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        return ctx

    def test_the_isolated_run_is_reported_before_the_undersized_breaker(self):
        """Twenty kilowatts on a 32 A breaker exceeds that breaker's 17.48 kW continuous
        rating, but the run has been isolated by a change in execution and that is the
        refusal that comes back.

        PRD: "The named run must not be `ISOLATED`; a feed cannot be reserved on a run
        that a change is currently holding out of service, and the attempt is refused with
        `ERR_BUSWAY_NOT_ENERGIZED`."

        Design: Corner/validations/rack_feed_busway_state_check_runs_before_breaker_derate
        """
        ctx = self._hall_with_one_run_held_out_of_service()
        assert ctx["mop"]["status"] == "IN_EXECUTION"
        assert read_busway(ctx["bw_a"]["id"])["status"] == "ISOLATED"
        assert read_hall(ctx["hall_id"])["release_posture"] == "LOCKED"

        validate_error(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack_1"]["id"],
                    "busway_id": ctx["bw_a"]["id"],
                    "feed_side": "A",
                    "requested_kw": 20.00,
                    "breaker_amps": 32,
                },
                EC,
            ),
            ApiErrorId.ERR_BUSWAY_NOT_ENERGIZED.value,
            409,
        )

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["status"] == "ISOLATED"
        assert busway["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert busway["feed_count"] == 0
        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(375.00, abs=0.005)

    def test_the_same_request_on_an_energised_run_reports_the_breaker(self):
        """Aimed at BW-B1, which no change has touched, the identical 20.00 kW request on a
        32 A breaker is refused on the breaker instead — proof that the energisation gate
        was reported first.

        PRD: "That rating is the breaker's ampacity multiplied by the run's line-to-line
        voltage, multiplied by 1.732, multiplied by the power factor 0.95, divided by
        1000, then multiplied by the continuous-load factor 0.80, with the result rounded
        to two decimal places; `allocated_kw` must be no greater than it."

        Design: Corner/validations/rack_feed_busway_state_check_runs_before_breaker_derate
        """
        ctx = self._hall_with_one_run_held_out_of_service()
        assert read_busway(ctx["bw_b"]["id"])["status"] == "ENERGIZED"

        validate_error(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack_1"]["id"],
                    "busway_id": ctx["bw_b"]["id"],
                    "feed_side": "B",
                    "requested_kw": 20.00,
                    "breaker_amps": 32,
                },
                EC,
            ),
            ApiErrorId.ERR_BREAKER_DERATE_EXCEEDED.value,
            422,
        )

        accepted = reserve_feed(
            ctx["rack_1"]["id"], ctx["bw_b"]["id"], "B", 15.00, 32
        )
        assert accepted["status"] == "RESERVED", (
            "15.00 kW sits inside the same breaker's 17.48 kW rating"
        )
        assert accepted["allocated_kw"] == pytest.approx(15.000, abs=0.0005)
        assert read_busway(ctx["bw_b"]["id"])["committed_kw"] == pytest.approx(
            15.000, abs=0.0005
        )


class TestAirflowAcceptanceFloorIsInclusive:
    """The cooling acceptance floor at level 49 is a "reach at least" test: a machine
    measured at exactly ninety percent of its design airflow is accepted, one cubic foot
    per minute below it is not."""

    def _hall_with_a_small_cooling_unit(self):
        return setup_fit_out_hall(
            "CX59",
            cu_rated_sensible_kw=20.00,
            cu_design_airflow_cfm=3000,
            cu_supply_delta_t_f=12.0,
        )

    def test_exactly_twenty_seven_hundred_of_three_thousand_is_accepted(self):
        """2700 cfm is precisely ninety percent of the specified 3000 cfm, so the unit is
        commissioned and publishes 10.25557 kW of airflow capacity.

        PRD: "It requires the hall to be in `FIT_OUT`, `COMMISSIONING` or `LIVE`, and it
        requires the measured airflow to reach at least ninety percent of
        `design_airflow_cfm`; a unit that cannot move the air it was specified for is
        refused with `ERR_AIRFLOW_BELOW_DESIGN`."

        Design: Corner/validations/cooling_commission_accepts_airflow_exactly_at_ninety_percent_floor
        """
        ctx = self._hall_with_a_small_cooling_unit()
        commissioned = commission_cooling_unit(ctx["cu_1"]["id"], 2700)
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["measured_airflow_cfm"] == 2700
        assert commissioned["airflow_capacity_kw"] == pytest.approx(
            10.25557, abs=0.000005
        ), "2700 cfm, no leakage deduction, 12.0 F delta-T, 1.08 over 3412"

        place_unit_in_service(ctx["cu_1"]["id"])
        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["worst_leakage_pct"] == pytest.approx(0.00, abs=0.005), (
            "the aisle has never been tested, so no zone contributes a measurement"
        )
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            20.00, abs=0.005
        )
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            10.26, abs=0.005
        ), "10.25557 rounded half up to two decimal places for publication"
        assert summary["cooling_capacity_kw"] == pytest.approx(10.26, abs=0.005)
        assert summary["cooling_margin_kw"] == pytest.approx(10.26, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL"

    def test_one_cubic_foot_below_the_floor_is_refused(self):
        """A sibling machine of the same specification measured at 2699 cfm is refused with
        ERR_AIRFLOW_BELOW_DESIGN and stays at INSTALLED with no capacity of its own.

        PRD: "A unit that has not been commissioned carries 0.00 here."

        Design: Corner/validations/cooling_commission_accepts_airflow_exactly_at_ninety_percent_floor
        """
        ctx = self._hall_with_a_small_cooling_unit()
        sibling = create_cooling_unit(
            ctx["hall_id"],
            "CU-2",
            rated_sensible_kw=20.00,
            design_airflow_cfm=3000,
            supply_delta_t_f=12.0,
            redundancy_role="REDUNDANT",
        )
        validate_error(
            api_client.commission_cooling_unit(
                sibling["id"], {"measured_airflow_cfm": 2699}, MC
            ),
            ApiErrorId.ERR_AIRFLOW_BELOW_DESIGN.value,
            422,
        )

        refused = read_cooling_unit(sibling["id"])
        assert refused["status"] == "INSTALLED"
        assert refused["measured_airflow_cfm"] is None
        assert refused["airflow_capacity_kw"] == pytest.approx(0.00, abs=0.005)

        commission_cooling_unit(sibling["id"], 2700)
        assert read_cooling_unit(sibling["id"])["status"] == "COMMISSIONED", (
            "the very next cubic foot per minute clears the floor"
        )


class TestFeedTopologyMustMatchExactly:
    """Energisation asks for exactly as many reserved feeds as the position declares —
    one too few and one too many are both refused with the same identifier."""

    def _hall_with_a_short_position_and_a_surplus_position(self):
        ctx = setup_fit_out_hall("CX60", design_kw_capacity=400.00)
        prove_zone_and_cooling(ctx, measured_leakage_pct=5.00)

        short = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=10.00,
            required_feed_count=2,
        )
        ctx["rack_short"] = short
        ctx["short_feed_a"] = reserve_feed(
            short["id"], ctx["bw_a"]["id"], "A", 5.00, 32
        )
        ctx["rack_short"] = install_rack(short["id"], "AT-0060")

        surplus = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            2,
            design_kw=10.00,
            required_feed_count=1,
        )
        ctx["rack_surplus"] = surplus
        reserve_feed(surplus["id"], ctx["bw_a"]["id"], "A", 5.00, 32)
        reserve_feed(surplus["id"], ctx["bw_b"]["id"], "B", 5.00, 32)
        ctx["rack_surplus"] = install_rack(surplus["id"], "AT-0061")
        return ctx

    def test_a_dual_corded_position_on_one_feed_cannot_take_load(self):
        """The position declares two feeds and holds one, so energisation is refused even
        though the aisle has passed and the room has cooling to spare.

        PRD: "The position holds exactly as many `RESERVED` feeds as its
        `required_feed_count`, and when that count is 2 the two feeds carry different
        `feed_side` values. Neither a short count, nor a surplus, nor two feeds on the
        same side is acceptable; all three are refused with
        `ERR_FEED_TOPOLOGY_INCOMPLETE`."

        Design: Corner/validations/rack_power_on_rejects_single_feed_when_two_are_required
        """
        ctx = self._hall_with_a_short_position_and_a_surplus_position()
        assert read_rack(ctx["rack_short"]["id"])["required_feed_count"] == 2

        validate_error(
            api_client.power_on_rack(ctx["rack_short"]["id"], EC),
            ApiErrorId.ERR_FEED_TOPOLOGY_INCOMPLETE.value,
            422,
        )

        rack = read_rack(ctx["rack_short"]["id"])
        assert rack["status"] == "INSTALLED"
        assert rack["energized_feed_count"] == 0
        assert read_feed(ctx["short_feed_a"]["id"])["status"] == "RESERVED", (
            "the one feed it does hold is untouched by the refusal"
        )

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["thermal_load_kw"] == pytest.approx(0.00, abs=0.005)
        assert summary["cooling_margin_kw"] == pytest.approx(119.08, abs=0.005), (
            "the room has plenty of cooling; topology is the only problem"
        )
        assert summary["thermal_posture"] == "NOMINAL"
        assert summary["custody_ops_count"] == 0

    def test_a_surplus_is_refused_and_the_matching_topology_energises(self):
        """A single-corded position holding two feeds is refused with the same identifier,
        while the dual-corded position energises the moment its second side is reserved.

        PRD: "On success every `RESERVED` feed of the position moves to `ENERGIZED` and
        `energized_feed_count` is re-derived, the position's status becomes `POWERED`, the
        hall's `custody_ops_count` grows by one while its `custody_fitout_count` falls by
        one, the hall cooling model is re-derived so that thermal load rises, the custody
        partition is re-derived, and the hall's `version` increments."

        Design: Corner/validations/rack_power_on_rejects_single_feed_when_two_are_required
        """
        ctx = self._hall_with_a_short_position_and_a_surplus_position()
        validate_error(
            api_client.power_on_rack(ctx["rack_surplus"]["id"], EC),
            ApiErrorId.ERR_FEED_TOPOLOGY_INCOMPLETE.value,
            422,
        )
        assert read_rack(ctx["rack_surplus"]["id"])["status"] == "INSTALLED", (
            "one feed too many is as fatal as one too few"
        )

        second = reserve_feed(
            ctx["rack_short"]["id"], ctx["bw_b"]["id"], "B", 5.00, 32
        )
        assert second["feed_side"] == "B"
        powered = power_on_rack(ctx["rack_short"]["id"])
        assert powered["status"] == "POWERED"
        assert powered["energized_feed_count"] == 2

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["custody_ops_count"] == 1
        assert summary["custody_fitout_count"] == 1
        assert summary["thermal_load_kw"] == pytest.approx(8.50, abs=0.005)
        assert summary["cooling_margin_kw"] == pytest.approx(110.58, abs=0.005)
