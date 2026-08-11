"""Pausing the subscription and the seasonal capsule waves — two opposite
interval geometries over the same `ERR_WINDOW_OVERLAP` code."""

from test_helpers import (
    ADMIN,
    BILLING,
    LOGISTICS,
    PLANNER,
    WAREHOUSE,
    ApiErrorId,
    assert_capsule,
    assert_pause_request,
    assert_same_instant,
    activate_pause,
    allocate_unit,
    announce_capsule,
    claim_capsule_allocation,
    close_cycle,
    complete_one_empty_cycle,
    create_box,
    create_capsule,
    create_capsule_payload,
    create_cycle,
    create_open_cycle,
    create_style,
    create_unit,
    depart_shipment,
    drive_cycle_to_return_due,
    end_pause,
    get_box_item,
    get_capsule,
    get_capsule_allocation,
    get_cycle,
    get_member,
    get_pause_request,
    make_member_headers,
    mint_buy_out_quote,
    mint_label,
    open_capsule,
    pack_box,
    receive_shipment,
    request_pause,
    set_clock,
    setup_basic_delivered_scenario,
    setup_delivered_box,
    setup_open_capsule,
    setup_paused_member,
    setup_plan_and_member,
    setup_returned_items,
    ship_box,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPauseRequests:
    def test_the_end_instant_is_the_exclusive_endpoint_of_the_half_open_window(self, api):
        """PRD §3.10: "The request's `end_at` is derived as `start_at` plus
        `days_requested` days, and the pause window is **half-open**: it
        includes `start_at` and excludes `end_at`. A new request is born
        `REQUESTED` with `proration_credit_cents` at 0 and `denial_reason`
        null."

        Design: Corner/entities/corner_pause_request_end_at_computed_from_days_requested
        """
        _, member = setup_plan_and_member()
        pause = validate_success(
            api.create_pause_request(member["id"],
                                     {"start_at": "2026-05-05T00:00:00Z",
                                      "days_requested": 12},
                                     make_member_headers(member["id"])),
            201,
        )
        assert_pause_request(pause)
        assert_same_instant(pause["end_at"], "2026-05-17T00:00:00.000Z",
                            "PauseRequest.end_at")
        assert pause["status"] == "REQUESTED"
        assert pause["proration_credit_cents"] == 0

        after = get_member(member["id"])
        assert after["status"] == "ACTIVE"
        assert after["pause_days_used_lifetime"] == 0

    def test_a_pause_shorter_than_the_minimum_is_out_of_range(self, api):
        """PRD §3.10: "A pause request names a `start_at` and a `days_requested`
        count of whole days that must be at least `PAUSE_MIN_DAYS`, seven, and
        at most `PAUSE_MAX_DAYS_PER_PERIOD`, thirty; a value outside that range
        is refused with `ERR_PAUSE_DAYS_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/corner_val_pause_shorter_than_the_minimum_is_rejected
        """
        _, member = setup_plan_and_member()
        resp = api.create_pause_request(member["id"],
                                        {"start_at": "2026-05-05T00:00:00Z",
                                         "days_requested": 3},
                                        make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_PAUSE_DAYS_OUT_OF_RANGE.value, 422)
        _, meta = validate_paginated(api.list_pause_requests(ADMIN,
                                                             {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_cancelling_an_activated_pause_is_an_invalid_transition(self, api):
        """PRD §3.10: "A `REQUESTED` pause may instead be cancelled by the
        household or denied by a `PlatformAdmin` with a `denial_reason`; in both
        cases **no pause days are consumed**, which is why the period and
        lifetime budgets count only pauses that reached `ACTIVE` or `ENDED`."
        PRD §2.6 rung 32: "`Member.status`, `Capsule.status`,
        `CapsuleAllocation.status`, `BuyOutOrder.status`, `PauseRequest.status`
        and `LostShipmentClaim.status` are declared from-states for the
        requested transition. Otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/corner_sm_pause_cancel_after_activation_is_rejected
        """
        _, member = setup_plan_and_member()
        pause = setup_paused_member(member["id"], "2026-05-02T00:00:00Z", 7)

        resp = api.cancel_pause_request(pause["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        assert get_pause_request(pause["id"])["status"] == "ACTIVE"
        assert get_member(member["id"])["status"] == "PAUSED"

    def test_the_thirty_day_basis_prorates_the_overlapping_cycle(self, api):
        """PRD §3.10: "Under the `THIRTY_DAY` variant the credit is the plan's
        `monthly_fee_cents` multiplied by the overlap days and divided by
        `PAUSE_PRORATION_DAY_BASIS`, a fixed 30-day basis that ignores the
        cycle's real length, rounded half up."
        PRD §3.10: "The overlap is the whole number of days shared by the
        half-open pause window and the half-open cycle window running from the
        cycle's `start_at` up to but not including its `return_due_at`."
        PRD §3.2: "`paused_days`, the days of the cycle window covered by an
        `ACTIVE` or `ENDED` pause"

        Design: Corner/calculations/corner_calc_pause_proration_on_the_thirty_day_basis
        """
        _, member = setup_plan_and_member(
            plan={"monthly_fee_cents": 6000, "proration_basis": "THIRTY_DAY"}
        )
        cycle = create_cycle(member["id"])
        pause = request_pause(member["id"], "2026-05-05T00:00:00Z", 10)

        activate_pause(pause["id"])

        after = get_pause_request(pause["id"])
        assert after["status"] == "ACTIVE"
        assert after["proration_credit_cents"] == 2000
        assert get_member(member["id"])["status"] == "PAUSED"
        assert get_cycle(cycle["id"])["paused_days"] == 10

    def test_the_period_cap_binds_inside_the_rolling_year(self, api):
        """PRD §2.6 rung 48: "The member's `pause_days_used_period` plus the
        request's `days_requested` must not exceed thirty. Otherwise
        `ERR_PAUSE_PERIOD_CAP_EXCEEDED` (409). Applies to
        `POST /kidswear/pause-requests/{pause_request_id}/activate`."
        PRD §3.10: "The member's `pause_days_used_period` — the sum of
        `days_requested` over the member's pauses whose `status` is `ACTIVE` or
        `ENDED` and whose `start_at` falls inside the trailing
        `PAUSE_PERIOD_LENGTH_DAYS` window of 365 days — plus this request's
        `days_requested` must not exceed thirty, or the activation is refused
        with `ERR_PAUSE_PERIOD_CAP_EXCEEDED`."

        Design: Corner/validations/corner_val_pause_period_cap_is_enforced_within_the_rolling_year
        """
        _, member = setup_plan_and_member()
        first = request_pause(member["id"], "2026-05-02T00:00:00Z", 30)
        activate_pause(first["id"])
        end_pause(member["id"], first["id"])
        set_clock("2026-06-05T00:00:00Z")
        second = request_pause(member["id"], "2026-06-05T00:00:00Z", 7)

        resp = api.activate_pause_request(second["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_PAUSE_PERIOD_CAP_EXCEEDED.value, 409)

        assert get_pause_request(second["id"])["status"] == "REQUESTED"
        after = get_member(member["id"])
        assert after["status"] == "ACTIVE"
        assert after["pause_days_used_period"] == 30
        assert after["pause_days_used_lifetime"] == 30

    def test_the_lifetime_cap_binds_across_rolling_years(self, api):
        """PRD §2.6 rung 49: "The member's `pause_days_used_lifetime` plus the
        request's `days_requested` must not exceed ninety. Otherwise
        `ERR_PAUSE_LIFETIME_CAP_EXCEEDED` (409). Applies to
        `POST /kidswear/pause-requests/{pause_request_id}/activate`."
        PRD §3.10: "The member's `pause_days_used_lifetime`, the same sum over
        all time with no window at all, plus this request's `days_requested`
        must not exceed `PAUSE_MAX_DAYS_LIFETIME`, ninety, or the activation is
        refused with `ERR_PAUSE_LIFETIME_CAP_EXCEEDED`."

        Design: Corner/validations/corner_val_pause_lifetime_cap_is_enforced_across_rolling_years
        """
        _, member = setup_plan_and_member()
        for start, clock in (("2026-05-02T00:00:00Z", None),
                             ("2027-06-01T00:00:00Z", "2027-06-01T00:00:00Z"),
                             ("2028-07-01T00:00:00Z", "2028-07-01T00:00:00Z")):
            if clock:
                set_clock(clock)
            pause = request_pause(member["id"], start, 30)
            activate_pause(pause["id"])
            end_pause(member["id"], pause["id"])

        set_clock("2029-08-01T00:00:00Z")
        fourth = request_pause(member["id"], "2029-08-01T00:00:00Z", 7)

        resp = api.activate_pause_request(fourth["id"], BILLING)
        error = validate_error(resp, ApiErrorId.ERR_PAUSE_LIFETIME_CAP_EXCEEDED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_PAUSE_PERIOD_CAP_EXCEEDED.value

        after = get_member(member["id"])
        assert after["pause_days_used_lifetime"] == 90
        assert after["pause_days_used_period"] == 0
        assert after["status"] == "ACTIVE"

    def test_a_past_due_garment_blocks_the_pause(self, api):
        """PRD §3.10: "It requires that **no** shipment of that member is
        currently `IN_TRANSIT`, otherwise it is refused with
        `ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE`, and that **no** box item of that
        member has a `days_late` greater than zero, otherwise it is refused with
        `ERR_UNIT_PAST_DUE_BLOCKS_PAUSE`."
        PRD §3.2: "Under the `PER_DAY` variant the fee is
        `LATE_FEE_PER_UNIT_PER_DAY_CENTS`, 150 cents, for each late day, capped
        at `LATE_FEE_CAP_PER_UNIT_CENTS`, 4500 cents per unit — the cap binds at
        thirty late days."

        Design: Corner/errors/corner_err_pause_blocked_by_a_past_due_unit
        """
        scenario = setup_basic_delivered_scenario(
            plan={"late_fee_mode": "PER_DAY"},
            style={"sku": "SKU-XPD-5", "name": "Past Due Tee", "size_code": "5"},
        )
        member, cycle = scenario["member"], scenario["cycle"]
        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))
        set_clock("2026-06-08T00:00:00Z")
        validate_success(api.assess_late(cycle["id"], BILLING))
        pause = request_pause(member["id"], "2026-06-10T00:00:00Z", 7)

        resp = api.activate_pause_request(pause["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_UNIT_PAST_DUE_BLOCKS_PAUSE.value, 409)

        item = get_box_item(scenario["items"][0]["id"])
        assert item["days_late"] == 3
        assert item["late_fee_cents"] == 450
        assert get_pause_request(pause["id"])["status"] == "REQUESTED"
        after = get_member(member["id"])
        assert after["status"] == "ACTIVE"
        assert after["pause_days_used_lifetime"] == 0


class TestPauseBlockedByShipment:
    def _in_transit_world(self, sku):
        plan, member = setup_plan_and_member()
        style = create_style(sku=sku, name="XDep Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=unit["id"])
        pack_box(box["id"])
        label = mint_label(member["id"], "OUTBOUND")
        shipment = ship_box(box["id"], label["id"])
        depart_shipment(shipment["id"])
        pause = request_pause(member["id"], "2026-05-05T00:00:00Z", 10)
        return {"member": member, "shipment": shipment, "pause": pause}

    def test_an_in_transit_parcel_blocks_the_activation(self, api):
        """PRD §3.10: "It requires that **no** shipment of that member is
        currently `IN_TRANSIT`, otherwise it is refused with
        `ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE`, and that **no** box item of that
        member has a `days_late` greater than zero, otherwise it is refused with
        `ERR_UNIT_PAST_DUE_BLOCKS_PAUSE`."
        PRD §3.5: "**Departure** moves it `CREATED → IN_TRANSIT`, requires the
        label to be `ISSUED` and unexpired, sets `shipped_at` to the logical
        clock, sets `ever_scanned` true, and advances the label `ISSUED →
        IN_TRANSIT`."

        Design: Difficulty/cross_entity_state_dependency/pause_activation_blocked_by_an_in_transit_shipment
        """
        world = self._in_transit_world("SKU-X1-5")
        resp = api.activate_pause_request(world["pause"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE.value, 409)

        assert validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS)
        )["status"] == "IN_TRANSIT"
        assert get_pause_request(world["pause"]["id"])["status"] == "REQUESTED"

    def test_the_blocked_activation_consumes_no_pause_days(self, api):
        """PRD §3.10: "A successful activation moves the request `REQUESTED →
        ACTIVE`, moves the member `ACTIVE → PAUSED`, computes the proration
        credit, and grants every one of the member's credit entries whose
        `status` is `AVAILABLE` or `PARTIALLY_APPLIED` a `paused_days_extension`
        equal to `days_requested`."
        PRD §3.10: "in both cases **no pause days are consumed**, which is why
        the period and lifetime budgets count only pauses that reached `ACTIVE`
        or `ENDED`."

        Design: Difficulty/cross_entity_state_dependency/pause_activation_blocked_by_an_in_transit_shipment
        """
        world = self._in_transit_world("SKU-X1B-5")
        validate_error(api.activate_pause_request(world["pause"]["id"], BILLING),
                       ApiErrorId.ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE.value, 409)

        after = get_member(world["member"]["id"])
        assert after["status"] == "ACTIVE"
        assert after["pause_days_used_lifetime"] == 0


class TestPauseWindowGeometry:
    def _adjacent_pauses(self):
        _, member = setup_plan_and_member(plan={"proration_basis": "THIRTY_DAY"})
        first = request_pause(member["id"], "2026-05-05T00:00:00Z", 10)
        activate_pause(first["id"])
        end_pause(member["id"], first["id"])
        second = request_pause(member["id"], "2026-05-15T00:00:00Z", 7)
        return member, first, second

    def test_a_pause_starting_at_the_prior_end_instant_does_not_collide(self, api):
        """PRD §3.10: "Overlap is judged under **half-open** semantics: two
        windows conflict when the new `start_at` is strictly before the other's
        `end_at` and the other's `start_at` is strictly before the new `end_at`.
        **Adjacency is allowed** — a pause starting at exactly a prior pause's
        `end_at` does not conflict, because the prior interval excludes its own
        endpoint."
        PRD §2.6 rung 68: "A pause window does not overlap another `ACTIVE` or
        `ENDED` pause of the same member under half-open interval semantics, and
        a capsule window does not overlap another capsule of the same season
        under closed interval semantics. Otherwise `ERR_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/adjacent_pause_windows_on_a_member_do_not_collide
        """
        member, first, second = self._adjacent_pauses()
        validate_success(api.activate_pause_request(second["id"], BILLING))

        assert_same_instant(get_pause_request(first["id"])["end_at"],
                            "2026-05-15T00:00:00.000Z", "PauseRequest.end_at")
        assert get_pause_request(second["id"])["status"] == "ACTIVE"
        assert get_member(member["id"])["status"] == "PAUSED"

    def test_adjacent_pauses_accumulate_against_the_lifetime_budget(self, api):
        """PRD §3.10: "The member's `pause_days_used_lifetime`, the same sum over
        all time with no window at all, plus this request's `days_requested`
        must not exceed `PAUSE_MAX_DAYS_LIFETIME`, ninety, or the activation is
        refused with `ERR_PAUSE_LIFETIME_CAP_EXCEEDED`."
        PRD §3.1: "`total_paused_days` — which always equals
        `pause_days_used_lifetime` — is the cumulative paused-day figure used to
        extend credit expiry."

        Design: Difficulty/resource_temporal_overlap/adjacent_pause_windows_on_a_member_do_not_collide
        """
        member, _, second = self._adjacent_pauses()
        validate_success(api.activate_pause_request(second["id"], BILLING))

        after = get_member(member["id"])
        assert after["pause_days_used_lifetime"] == 17
        assert after["total_paused_days"] == 17


class TestCapsuleCalendar:
    def test_announcing_stamps_an_embargo_that_may_outlive_the_wave(self, api):
        """PRD §3.8: "Announcing it moves it `DRAFT → ANNOUNCED`, is permitted
        only while the logical clock is strictly before `release_at`, and
        computes `embargo_until` as `release_at` plus `CAPSULE_EMBARGO_DAYS`,
        twenty-one days."
        PRD §3.8: "The capsule calendar and the embargo calendar are genuinely
        not the same calendar: `close_at` may precede `embargo_until`, and a
        capsule item can stay embargoed past its own cycle's `return_due_at`."

        Design: Corner/entities/corner_capsule_embargo_until_computed_on_announce
        """
        capsule = create_capsule(season="SS", name="Short Window",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-06-15T00:00:00Z", quota_per_member=2)
        assert_capsule(capsule)
        validate_success(api.announce_capsule(capsule["id"], PLANNER))

        after = get_capsule(capsule["id"])
        assert after["status"] == "ANNOUNCED"
        assert_same_instant(after["embargo_until"], "2026-06-22T00:00:00.000Z",
                            "Capsule.embargo_until")
        assert_same_instant(after["close_at"], "2026-06-15T00:00:00.000Z",
                            "Capsule.close_at")

    def test_lifting_the_embargo_early_is_refused(self, api):
        """PRD §3.8: "Lifting the embargo moves it `OPEN → EMBARGO_LIFTED` and is
        permitted only when the clock has reached `embargo_until`; an earlier
        attempt is refused with `ERR_CAPSULE_EMBARGO_NOT_REACHED`."

        Design: Corner/state_machines/corner_sm_capsule_lift_embargo_before_the_instant_is_rejected
        """
        capsule = setup_open_capsule(release_at="2026-06-01T00:00:00Z",
                                     close_at="2026-08-01T00:00:00Z",
                                     name="Embargo Wave",
                                     open_at="2026-06-05T00:00:00Z")

        resp = api.lift_capsule_embargo(capsule["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_CAPSULE_EMBARGO_NOT_REACHED.value, 409)

        after = get_capsule(capsule["id"])
        assert after["status"] == "OPEN"
        assert_same_instant(after["embargo_until"], "2026-06-22T00:00:00.000Z",
                            "Capsule.embargo_until")

    def test_closing_a_wave_before_its_close_instant_is_refused(self, api):
        """PRD §3.8: "Closing is permitted from `EMBARGO_LIFTED` and equally from
        `OPEN`, in both cases only once the clock has reached `close_at`; an
        earlier attempt is refused with `ERR_CAPSULE_CLOSE_NOT_DUE`."

        Design: Corner/errors/corner_err_capsule_closed_before_its_close_instant_is_rejected
        """
        capsule = setup_open_capsule(release_at="2026-06-01T00:00:00Z",
                                     close_at="2026-08-01T00:00:00Z",
                                     name="Early Close Wave",
                                     open_at="2026-06-05T00:00:00Z")

        resp = api.close_capsule(capsule["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_CAPSULE_CLOSE_NOT_DUE.value, 409)
        assert get_capsule(capsule["id"])["status"] == "OPEN"

    def test_same_season_waves_collide_on_a_touching_endpoint(self, api):
        """PRD §3.8: "Two capsules **of the same season** may not overlap, and
        the interval semantics here are **closed at both ends**: a new wave
        conflicts with an existing non-closed wave of the same season whenever
        the new `release_at` is at or before the existing `close_at` and the
        existing `release_at` is at or before the new `close_at`. Adjacency is
        therefore a **conflict** — a wave opening at exactly another wave's
        `close_at` collides."
        PRD §3.8: "A collision is refused with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/same_season_capsule_windows_collide_on_a_touching_endpoint
        """
        create_capsule(season="SS", name="SS26 Early",
                       release_at="2026-06-01T00:00:00Z",
                       close_at="2026-07-01T00:00:00Z", quota_per_member=2)

        resp = api.create_capsule(
            create_capsule_payload(season="SS", name="SS26 Late",
                                   release_at="2026-07-01T00:00:00Z",
                                   close_at="2026-08-01T00:00:00Z",
                                   quota_per_member=2),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)

    def test_the_conflict_scope_is_partitioned_by_season(self, api):
        """PRD §3.8: "Waves of *different* seasons never conflict with each
        other."
        PRD §3.8: "A `MerchandisePlanner` creates a wave by supplying a
        `season`, which is one of the two members of `CAPSULE_SEASONS`, `SS` or
        `AW`; a `name`; a `release_at` instant; a `close_at` instant; and
        optionally a `quota_per_member` between 0 and 6 that defaults to
        `CAPSULE_QUOTA_PER_MEMBER_DEFAULT`, which is 2. The wave begins
        `DRAFT`."

        Design: Difficulty/resource_temporal_overlap/same_season_capsule_windows_collide_on_a_touching_endpoint
        """
        create_capsule(season="SS", name="SS26 Early",
                       release_at="2026-06-01T00:00:00Z",
                       close_at="2026-07-01T00:00:00Z", quota_per_member=2)

        twin = validate_success(
            api.create_capsule(
                create_capsule_payload(season="AW", name="AW26 Same Window",
                                       release_at="2026-06-01T00:00:00Z",
                                       close_at="2026-07-01T00:00:00Z",
                                       quota_per_member=2),
                PLANNER,
            ),
            201,
        )
        assert twin["status"] == "DRAFT"
        assert twin["season"] == "AW"


class TestCapsuleAllocation:
    def test_an_announced_wave_is_not_yet_allocatable(self, api):
        """PRD §3.8: "the wave's `status` is `OPEN`, and any other status is
        refused with `ERR_CAPSULE_NOT_OPEN`"
        PRD §3.8: "Opening it moves it `ANNOUNCED → OPEN` and is permitted only
        when the clock has reached `release_at` and has not reached `close_at`;
        from that moment the wave's units are allocatable."

        Design: Corner/errors/corner_err_capsule_allocation_before_the_wave_opens_is_rejected
        """
        _, member = setup_plan_and_member()
        capsule = create_capsule(season="SS", name="Not Open Yet",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-08-01T00:00:00Z", quota_per_member=2)
        announce_capsule(capsule["id"])

        resp = api.create_capsule_allocation(capsule["id"],
                                             {"member_id": member["id"],
                                              "units_allocated": 1},
                                             make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPSULE_NOT_OPEN.value, 409)
        assert get_capsule(capsule["id"])["status"] == "ANNOUNCED"
        _, meta = validate_paginated(api.list_capsule_allocations(
            PLANNER, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_a_household_with_no_completed_cycle_is_not_yet_eligible(self, api):
        """PRD §3.8: "the member's `completed_cycles` is at least
        `CAPSULE_ELIGIBILITY_MIN_COMPLETED_CYCLES`, which is 1, and a household
        short of that is refused with `ERR_CAPSULE_ELIGIBILITY_NOT_MET`"
        PRD §3.1: "`completed_cycles` counts the member's cycles whose `status`
        is `CLOSED`"

        Design: Corner/errors/corner_err_capsule_allocation_without_a_completed_cycle_is_rejected
        """
        _, member = setup_plan_and_member()
        capsule = setup_open_capsule(name="Eligibility Wave")

        resp = api.create_capsule_allocation(capsule["id"],
                                             {"member_id": member["id"],
                                              "units_allocated": 1},
                                             make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPSULE_ELIGIBILITY_NOT_MET.value, 409)
        assert get_member(member["id"])["completed_cycles"] == 0
        assert get_capsule(capsule["id"])["status"] == "OPEN"

    def test_the_tighter_of_the_two_quota_ceilings_binds(self, api):
        """PRD §3.8: "The quota available to a household is the **smaller** of
        the wave's `quota_per_member` and the plan's `capsule_quota_per_wave`,
        less the sum of `units_allocated` over the household's `ACTIVE`
        allocations on that same wave; exceeding it is refused with
        `ERR_CAPSULE_QUOTA_EXCEEDED`."
        PRD §2.6 rung 47: "A capsule allocation must not exceed the smaller of
        the capsule's `quota_per_member` and the plan's `capsule_quota_per_wave`,
        less the units the member has already allocated on that capsule.
        Otherwise `ERR_CAPSULE_QUOTA_EXCEEDED` (409)."

        Design: Corner/errors/corner_err_capsule_quota_is_the_minimum_of_plan_and_wave
        """
        plan, member = setup_plan_and_member(
            plan={"capsule_quota_per_wave": 1},
            member={"auto_apply_credit": False},
        )
        capsule = create_capsule(season="SS", name="Quota Wave",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-08-01T00:00:00Z", quota_per_member=2)
        announce_capsule(capsule["id"])
        complete_one_empty_cycle(member["id"])
        set_clock("2026-06-01T00:00:00Z")
        open_capsule(capsule["id"])

        resp = api.create_capsule_allocation(capsule["id"],
                                             {"member_id": member["id"],
                                              "units_allocated": 2},
                                             make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPSULE_QUOTA_EXCEEDED.value, 409)

        assert get_member(member["id"])["completed_cycles"] == 1
        assert get_capsule(capsule["id"])["quota_per_member"] == 2
        assert validate_success(api.get_plan(plan["id"], ADMIN))["capsule_quota_per_wave"] == 1
        _, meta = validate_paginated(api.list_capsule_allocations(
            PLANNER, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_an_allocation_after_close_at_is_outside_the_window(self, api):
        """PRD §3.8: "and the logical clock is at or after `release_at` and
        strictly before `close_at`, with any other instant refused with
        `ERR_CAPSULE_WINDOW_CLOSED`."
        PRD §2.6 rung 39: "A capsule allocation is permitted only when the
        logical clock is at or after the capsule's `release_at` and strictly
        before its `close_at`. Otherwise `ERR_CAPSULE_WINDOW_CLOSED` (409).
        Applies to `POST /kidswear/capsules/{capsule_id}/allocations`."

        Design: Corner/errors/corner_err_capsule_allocation_after_close_at_is_rejected
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        capsule = create_capsule(season="SS", name="Late Window Wave",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-08-01T00:00:00Z", quota_per_member=2)
        announce_capsule(capsule["id"])
        complete_one_empty_cycle(member["id"])
        set_clock("2026-06-01T00:00:00Z")
        open_capsule(capsule["id"])
        set_clock("2026-08-02T00:00:00Z")

        resp = api.create_capsule_allocation(capsule["id"],
                                             {"member_id": member["id"],
                                              "units_allocated": 1},
                                             make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPSULE_WINDOW_CLOSED.value, 409)

        assert get_member(member["id"])["completed_cycles"] == 1
        assert get_capsule(capsule["id"])["status"] == "OPEN"

    def test_a_capsule_unit_needs_a_live_allocation_before_it_may_be_boxed(self, api):
        """PRD §2.6 rung 56: "A capsule unit may be allocated only when the
        member holds an `ACTIVE` `CapsuleAllocation` for that capsule and the
        capsule's `status` is `OPEN` or `EMBARGO_LIFTED`. Otherwise
        `ERR_CAPSULE_ALLOCATION_MISSING` (409)."
        PRD §3.3: "allocating a capsule unit without an `ACTIVE` allocation on
        an `OPEN` or `EMBARGO_LIFTED` capsule is refused with
        `ERR_CAPSULE_ALLOCATION_MISSING`."

        Design: Corner/errors/corner_err_capsule_unit_allocated_without_an_allocation_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2})
        capsule = create_capsule(season="SS", name="Unallocated Wave",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-08-01T00:00:00Z", quota_per_member=2)
        announce_capsule(capsule["id"])
        style = create_style(sku="SKU-Y8-5", name="Capsule Only Tee", brand_tier="PREMIUM",
                             retail_price_cents=9000, size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-04-01T00:00:00Z",
                           capsule_id=capsule["id"])
        set_clock("2026-06-01T00:00:00Z")
        open_capsule(capsule["id"])
        cycle = create_open_cycle(member["id"], start_at="2026-06-01T00:00:00Z")
        box = create_box(cycle["id"])

        resp = api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_CAPSULE_ALLOCATION_MISSING.value, 409)

        assert validate_success(
            api.get_garment_unit(unit["id"], PLANNER)
        )["state"] == "IN_STOCK"
        assert get_capsule(capsule["id"])["status"] == "OPEN"
        _, meta = validate_paginated(api.list_capsule_allocations(
            PLANNER, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0


class TestCapsuleEmbargoBlocksBuyOut:
    def _embargoed_capsule_item(self, base_sku, capsule_sku):
        plan, member = setup_plan_and_member(member={"auto_apply_credit": False})
        capsule = create_capsule(season="SS", name="SS26 Wave One",
                                 release_at="2026-06-01T00:00:00Z",
                                 close_at="2026-08-01T00:00:00Z", quota_per_member=2)
        announce_capsule(capsule["id"])

        base_style = create_style(sku=base_sku, name="Base Tee", size_code="5")
        base_unit = create_unit(base_style["id"], acquired_at="2026-01-01T00:00:00Z")
        first = setup_delivered_box(member, [base_unit])
        setup_returned_items(member, [first["items"][0]["id"]])
        drive_cycle_to_return_due(first["cycle"]["id"],
                                  swap_close_at="2026-05-22T00:00:00Z",
                                  return_due_at="2026-06-01T00:00:00Z")
        close_cycle(first["cycle"]["id"])

        open_capsule(capsule["id"])
        allocation = claim_capsule_allocation(member["id"], capsule["id"], 1)

        capsule_style = create_style(sku=capsule_sku, name="Capsule Coat",
                                     brand_tier="PREMIUM", retail_price_cents=12000,
                                     size_code="5", season="SS", category="OUTERWEAR",
                                     demand_band="HIGH")
        capsule_unit = create_unit(capsule_style["id"], acquired_at="2026-04-01T00:00:00Z",
                                   capsule_id=capsule["id"])
        second = setup_delivered_box(member, [capsule_unit],
                                     start_at="2026-06-01T00:00:00Z")
        return {"member": member, "capsule": capsule, "allocation": allocation,
                "item": second["items"][0]}

    def test_an_embargoed_capsule_item_may_not_be_bought_out(self, api):
        """PRD §2.6 rung 38: "A capsule box item may not be swapped or bought out
        while the logical clock is strictly before that item's `embargo_until`.
        Otherwise `ERR_CAPSULE_EMBARGOED` (409). Applies to
        `POST /kidswear/cycles/{cycle_id}/swap-requests` and
        `POST /kidswear/box-items/{box_item_id}/buy-out`."
        PRD §3.8: "While an item is embargoed, it may be neither swapped nor
        bought out; the check compares the logical clock against the *item's*
        `embargo_until`, which is copied from its capsule when the item is a
        capsule item and is null otherwise, and a strictly-before-embargo
        attempt is refused with `ERR_CAPSULE_EMBARGOED`."

        Design: Difficulty/cross_entity_state_dependency/capsule_embargo_on_the_capsule_row_blocks_a_box_item_buy_out
        """
        world = self._embargoed_capsule_item("SKU-X2-BASE", "SKU-X2-CAP")
        item = world["item"]
        version = get_box_item(item["id"])["version"]

        resp = api.create_buy_out_quote(
            item["id"],
            {"quote_variant": "CYCLES_WORN", "expected_box_item_version": version},
            make_member_headers(world["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPSULE_EMBARGOED.value, 409)
        assert get_box_item(item["id"])["settlement_status"] == "OPEN"

    def test_the_embargo_instant_is_copied_from_the_capsule_onto_the_item(self, api):
        """PRD §3.3: "sets `is_capsule_item` true exactly when the allocated
        unit's `capsule_id` is non-null, copies `embargo_until` from that capsule
        when it is, and decrements the box's `slots_free` by 1."
        PRD §3.8: "Announcing it moves it `DRAFT → ANNOUNCED`, is permitted only
        while the logical clock is strictly before `release_at`, and computes
        `embargo_until` as `release_at` plus `CAPSULE_EMBARGO_DAYS`, twenty-one
        days."
        PRD §3.8: "A created allocation is `ACTIVE`; a planner may release one
        directly, moving it `ACTIVE → RELEASED`, and the wave's closure releases
        the rest."

        Design: Difficulty/cross_entity_state_dependency/capsule_embargo_on_the_capsule_row_blocks_a_box_item_buy_out
        """
        world = self._embargoed_capsule_item("SKU-X2B-BASE", "SKU-X2B-CAP")
        capsule = get_capsule(world["capsule"]["id"])
        item = get_box_item(world["item"]["id"])

        assert_same_instant(capsule["embargo_until"], "2026-06-22T00:00:00.000Z",
                            "Capsule.embargo_until")
        assert_same_instant(item["embargo_until"], "2026-06-22T00:00:00.000Z",
                            "BoxItem.embargo_until")
        assert item["is_capsule_item"] is True
        assert get_member(world["member"]["id"])["completed_cycles"] == 1
        assert get_capsule_allocation(world["allocation"]["id"])["status"] == "ACTIVE"
