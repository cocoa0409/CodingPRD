"""Mulch giveback: event lifecycle gates, tiered allocation waterfall,
waitlist promotion sweep, claim window and pickup window rules."""
import pytest

from test_helpers import (
    ADMIN,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    assert_mulch_claim,
    complete_run,
    create_active_program,
    create_claim,
    create_mulch_event,
    create_open_event,
    create_serviced_booking,
    get_claim,
    get_program,
    list_notifications,
    make_resident_headers,
    open_mulch_event,
    open_site,
    record_intake,
    register_household,
    schedule_run,
    set_clock,
    setup_mulch_pool,
    site_stockpile,
    validate_error,
    validate_success,
)

CLAIM_CLOCK = "2027-01-18T12:00:00Z"


def _list_claims(household_id):
    resp = api_client.list_mulch_claims(ADMIN,
                                        params={"household_id": household_id})
    body = resp.json()
    return body["data"], body["meta"]


class TestClaimEntryGates:

    def test_claim_rejected_while_event_scheduled(self):
        """PRD section 3.6: "Five gates stand in front of allocation: the
        event must be `OPEN` (`ERR_EVENT_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/claim_requires_event_open
        """
        ctx = create_active_program()
        event = create_mulch_event(ctx["program"]["id"])
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        set_clock(CLAIM_CLOCK)  # inside the claim window

        resp = api_client.create_mulch_claim(
            {"event_id": event["id"], "household_id": household["id"],
             "requested_cy": 1.0},
            make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPEN)

    def test_claim_admitted_after_event_opens_with_empty_pool(self):
        """PRD section 3.6: "Five gates stand in front of allocation: the
        event must be `OPEN` (`ERR_EVENT_NOT_OPEN`)".
        PRD section 3.6: "If that allocation reaches at least 0.5 cubic yards,
        the claim is created `CONFIRMED` — partial allocation below the
        requested amount is explicitly allowed — and its `allocated_cy` joins
        the tier allocation counter immediately. Otherwise the allocation is
        zero and the claim is created `WAITLISTED`."
        PRD section 3.6: "a household with at least one `SERVICED` booking
        anywhere in the program is a `PARTICIPANT`; every other household is
        `GENERAL`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_event_open
        """
        ctx = create_active_program()
        event = create_mulch_event(ctx["program"]["id"])
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        set_clock(CLAIM_CLOCK)

        open_mulch_event(event["id"])
        # The pool is empty (no completed run): the claim is admitted but
        # waitlisted with a zero allocation.
        claim = create_claim(event["id"], household, requested_cy=1.0)
        assert_mulch_claim(claim)
        assert claim["status"] == "WAITLISTED"
        assert claim["allocated_cy"] == pytest.approx(0.0)
        assert claim["tier"] == "GENERAL"

    def test_claim_outside_claim_window_rejected(self):
        """PRD section 3.6: "the clock must sit inside the claim window
        inclusive of both ends (`ERR_CLAIM_WINDOW_INVALID`)".

        Design: Corner/validations/claim_outside_claim_window_rejected
        """
        ctx = create_active_program()
        event = create_open_event(ctx["program"]["id"])
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])

        # Clock before claim_open_at (2027-01-18), event already OPEN.
        set_clock("2027-01-10T00:00:00Z")
        resp = api_client.create_mulch_claim(
            {"event_id": event["id"], "household_id": household["id"],
             "requested_cy": 1.0},
            make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_INVALID)
        data, _ = _list_claims(household["id"])
        assert data == [], "a rejected claim must not be persisted"

    def test_claim_requested_outside_limits_rejected(self):
        """PRD section 3.6: "the `requested_cy` must be at least half a cubic
        yard and no more than the event's `per_household_cap_cy`
        (`ERR_CLAIM_CAP_EXCEEDED`)".
        PRD section 3.6: "An optional `per_household_cap_cy` caps how much any
        household may receive from the event and defaults to 2.0 cubic yards."

        Design: Corner/validations/claim_requested_outside_limits_rejected
        """
        ctx = create_active_program()
        event = create_open_event(ctx["program"]["id"])
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        set_clock(CLAIM_CLOCK)

        over_cap = api_client.create_mulch_claim(
            {"event_id": event["id"], "household_id": household["id"],
             "requested_cy": 3.0},
            make_resident_headers(household["id"]))
        validate_error(over_cap, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED)

        under_min = api_client.create_mulch_claim(
            {"event_id": event["id"], "household_id": household["id"],
             "requested_cy": 0.4},
            make_resident_headers(household["id"]))
        validate_error(under_min, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED)

    def test_duplicate_active_claim_rejected(self):
        """PRD section 3.6: "the household must not already hold a
        `CONFIRMED` or `WAITLISTED` claim on the same event
        (`ERR_DUPLICATE_CLAIM`)".

        Design: Corner/validations/duplicate_active_claim_rejected
        """
        ctx = create_active_program()
        event = create_open_event(ctx["program"]["id"])
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        set_clock(CLAIM_CLOCK)

        # Empty pool: the first claim is admitted as WAITLISTED (active).
        first = create_claim(event["id"], household, requested_cy=1.0)
        assert first["status"] == "WAITLISTED"

        resp = api_client.create_mulch_claim(
            {"event_id": event["id"], "household_id": household["id"],
             "requested_cy": 0.5},
            make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


class TestTieredAllocation:

    def test_participant_and_general_tiers_allocate_from_split_pools(self):
        """PRD section 3.6: "The participant pool is sixty percent of
        `mulch_produced_cy`, rounded half-up to two decimal places first; the
        general pool is whatever remains, computed as `mulch_produced_cy`
        minus that already-rounded participant pool."
        PRD section 3.6: "The claim's `allocated_cy` is then the smallest of
        three figures: the `requested_cy`, the event's
        `per_household_cap_cy`, and the current remainder for the claim's
        tier."

        Design: Difficulty/combinatorial_formula/mulch_allocation_tiered_minmax
        """
        ctx = setup_mulch_pool(produced_cy=10.0, num_general_households=3)
        event = ctx["event"]
        hp, (g1, g2, g3) = ctx["participant"], ctx["generals"]

        # Pools: participant round2(0.6 * 10.00) = 6.00; general 4.00.
        c_p = create_claim(event["id"], hp, requested_cy=2.0)
        assert c_p["tier"] == "PARTICIPANT"
        assert c_p["allocated_cy"] == pytest.approx(2.0)
        assert c_p["status"] == "CONFIRMED"  # min(2.0, cap 2.0, 6.00)

        c_g1 = create_claim(event["id"], g1, requested_cy=2.0)
        assert c_g1["tier"] == "GENERAL"
        assert c_g1["allocated_cy"] == pytest.approx(2.0)
        assert c_g1["status"] == "CONFIRMED"  # general remaining 4.00 -> 2.00

        c_g2 = create_claim(event["id"], g2, requested_cy=2.0)
        assert c_g2["allocated_cy"] == pytest.approx(2.0)
        assert c_g2["status"] == "CONFIRMED"  # general pool now exhausted

        c_g3 = create_claim(event["id"], g3, requested_cy=1.0)
        assert c_g3["tier"] == "GENERAL"
        assert c_g3["allocated_cy"] == pytest.approx(0.0)
        assert c_g3["status"] == "WAITLISTED", \
            "allocation below the 0.5 cy minimum waitlists the claim"

    def test_program_tier_remainders_after_allocations(self):
        """PRD section 3.6: "The participant remainder
        (`participant_remaining_cy`) is the participant pool minus
        `mulch_allocated_participant_cy` — the sum of `allocated_cy` over
        `PARTICIPANT` claims in `CONFIRMED` or `FULFILLED` — and the general
        remainder (`general_remaining_cy`) is the general pool minus
        `mulch_allocated_general_cy` over `GENERAL` claims in those same two
        statuses."

        Design: Difficulty/combinatorial_formula/mulch_allocation_tiered_minmax
        """
        ctx = setup_mulch_pool(produced_cy=10.0, num_general_households=3)
        event = ctx["event"]
        hp, (g1, g2, g3) = ctx["participant"], ctx["generals"]

        create_claim(event["id"], hp, requested_cy=2.0)
        create_claim(event["id"], g1, requested_cy=2.0)
        create_claim(event["id"], g2, requested_cy=2.0)
        create_claim(event["id"], g3, requested_cy=1.0)

        program = get_program(ctx["program"]["id"])
        assert program["mulch_produced_cy"] == pytest.approx(10.0)
        # participant pool 6.00 minus 2.00 allocated
        assert program["participant_remaining_cy"] == pytest.approx(4.0)
        # general pool 4.00 minus 4.00 allocated
        assert program["general_remaining_cy"] == pytest.approx(0.0)


class TestWaitlistPromotion:

    def _setup_waitlisted_scenario(self):
        """Pool 10.00 produced with a stockpile remainder left for a second
        run; PARTICIPANT claim 2.0 and GENERAL claims 2.0 + 2.0 confirmed
        (general pool exhausted); a 1.0 GENERAL claim sits WAITLISTED."""
        ctx = create_active_program()
        program, site, zone = ctx["program"], ctx["site"], ctx["zone"]
        open_site(site)
        hp = register_household(program["id"], zone["id"])
        create_serviced_booking(hp, zone["id"], tree_count=1,
                                size_class="SMALL")

        # First run draws most of the pile, leaving a remainder for run 2.
        # (The PRD pins the exact-draw rule, not the per-class cubic-yard
        # factor, so the split is computed from the live stockpile.)
        record_intake(site["id"], tree_count=20, size_class="MEDIUM")
        stockpile = site_stockpile(site["id"])
        remainder = round(stockpile / 6, 2)
        run1 = schedule_run(program["id"], site["id"])
        complete_run(run1, input_cy=round(stockpile - remainder, 2),
                     measured_input_tons=5.0, measured_output_cy=10.0)

        event = create_open_event(program["id"])
        set_clock(CLAIM_CLOCK)
        g1 = register_household(program["id"], zone["id"])
        g2 = register_household(program["id"], zone["id"])
        g3 = register_household(program["id"], zone["id"])

        create_claim(event["id"], hp, requested_cy=2.0)
        create_claim(event["id"], g1, requested_cy=2.0)
        create_claim(event["id"], g2, requested_cy=2.0)
        c_g3 = create_claim(event["id"], g3, requested_cy=1.0)
        assert c_g3["status"] == "WAITLISTED"
        assert c_g3["allocated_cy"] == pytest.approx(0.0)

        run2 = schedule_run(program["id"], site["id"],
                            scheduled_start="2027-01-18T13:00:00Z",
                            scheduled_end="2027-01-18T15:00:00Z")
        return ctx, c_g3, g3, run2

    def test_run_completion_promotes_waitlisted_claim_with_partial(self):
        """PRD section 3.5: "First, the run's `measured_output_cy` is added to
        the program's `mulch_produced_cy`, and the tier remainders
        `participant_remaining_cy` and `general_remaining_cy` are recomputed
        under the pool rules of Section 3.6. Second, the waitlist promotion
        sweep described in Section 3.6 runs against the enlarged pool."
        PRD section 3.6: "Each candidate in turn re-runs the full allocation
        algorithm against the tier remainder current at that moment; a
        candidate whose recomputed allocation reaches the half-cubic-yard
        minimum is promoted to `CONFIRMED` — again, partial allocation is
        allowed".

        Design: Difficulty/transitive_cascade/run_completion_waitlist_promotion
        """
        ctx, c_g3, g3, run2 = self._setup_waitlisted_scenario()

        # Second run adds 2.00 cy: produced 12.00, participant pool
        # round2(7.20) = 7.20, general pool 4.80, general remaining 0.80.
        complete_run(run2, measured_input_tons=1.0, measured_output_cy=2.0,
                     clock="2027-01-18T13:30:00Z")

        program = get_program(ctx["program"]["id"])
        assert program["mulch_produced_cy"] == pytest.approx(12.0)

        promoted = get_claim(c_g3["id"])
        assert promoted["status"] == "CONFIRMED"
        # partial: min(requested 1.0, cap 2.0, general remaining 0.80)
        assert promoted["allocated_cy"] == pytest.approx(0.8)
        assert program["general_remaining_cy"] == pytest.approx(0.0)

    def test_promotion_writes_claim_promoted_notification(self):
        """PRD section 3.5: "Third, one `CLAIM_PROMOTED` notification is
        written for each claim the sweep promotes."
        PRD section 3.5: "The `input_cy` may not exceed the site's current
        `stockpile_cy` — exact equality draws the pile to zero and is
        allowed".

        Design: Difficulty/transitive_cascade/run_completion_waitlist_promotion
        """
        ctx, c_g3, g3, run2 = self._setup_waitlisted_scenario()
        complete_run(run2, measured_input_tons=1.0, measured_output_cy=2.0,
                     clock="2027-01-18T13:30:00Z")

        entries = list_notifications(ctx["program"]["id"],
                                     params={"kind": "CLAIM_PROMOTED"})
        if isinstance(entries, dict) and "data" in entries:
            entries = entries["data"]
        matching = [e for e in entries if e["kind"] == "CLAIM_PROMOTED"
                    and e.get("household_id") == g3["id"]]
        assert len(matching) >= 1, \
            "the promoted claim's household must be notified"
        # The second run drew the remainder of the pile exactly.
        assert site_stockpile(ctx["site"]["id"]) == pytest.approx(0.0)

    def test_claim_cancel_triggers_promotion_sweep(self):
        """PRD section 3.6: "Cancellation — by the resident who owns the claim
        or an administrator — moves `CONFIRMED` or `WAITLISTED` to
        `CANCELLED`; when the claim was `CONFIRMED`, its `allocated_cy` is
        released from the tier allocation and a promotion sweep runs."
        PRD section 3.6: "Its candidates are every `WAITLISTED` claim on the
        program's `OPEN` events, taken in ascending `created_at` order".

        Design: Corner/complexity_layers/claim_cancel_triggers_promotion_sweep
        """
        ctx = setup_mulch_pool(produced_cy=10.0, num_general_households=3)
        event = ctx["event"]
        g1, g2, g3 = ctx["generals"]
        c_g1 = create_claim(event["id"], g1, requested_cy=2.0)
        create_claim(event["id"], g2, requested_cy=2.0)
        c_g3 = create_claim(event["id"], g3, requested_cy=1.0)
        assert c_g3["status"] == "WAITLISTED"

        resp = api_client.patch_mulch_claim(
            c_g1["id"], {"status": "CANCELLED"},
            make_resident_headers(g1["id"]))
        assert validate_success(resp, 200)["status"] == "CANCELLED"

        promoted = get_claim(c_g3["id"])
        assert promoted["status"] == "CONFIRMED"
        assert promoted["allocated_cy"] == pytest.approx(1.0)

        program = get_program(ctx["program"]["id"])
        # general pool 4.00 - 2.00 (g2) - 1.00 (g3) = 1.00
        assert program["general_remaining_cy"] == pytest.approx(1.0)

        entries = list_notifications(ctx["program"]["id"],
                                     params={"kind": "CLAIM_PROMOTED"})
        if isinstance(entries, dict) and "data" in entries:
            entries = entries["data"]
        assert any(e.get("household_id") == g3["id"]
                   and e["kind"] == "CLAIM_PROMOTED" for e in entries)


class TestClaimResolution:

    def test_fulfill_outside_pickup_window_rejected(self):
        """PRD section 3.6: "Fulfillment — by a `SiteSupervisor` or
        `ProgramAdmin` — moves `CONFIRMED → FULFILLED` and is only valid while
        the clock sits inside the pickup window inclusive of both ends;
        outside it the attempt is rejected with `ERR_PICKUP_WINDOW_CLOSED`."

        Design: Corner/validations/fulfill_outside_pickup_window_rejected
        """
        ctx = setup_mulch_pool(produced_cy=3.0, num_general_households=1,
                               with_participant=False)
        claim = create_claim(ctx["event"]["id"], ctx["generals"][0],
                             requested_cy=1.0)
        assert claim["status"] == "CONFIRMED"

        # 2027-01-20 is inside the claim window but before pickup_start.
        set_clock("2027-01-20T00:00:00Z")
        early = api_client.patch_mulch_claim(
            claim["id"], {"status": "FULFILLED"}, SUPERVISOR)
        validate_error(early, ApiErrorId.ERR_PICKUP_WINDOW_CLOSED)
        assert get_claim(claim["id"])["status"] == "CONFIRMED"

        set_clock("2027-01-23T10:00:00Z")  # inside pickup 09:00-15:00
        fulfilled = api_client.patch_mulch_claim(
            claim["id"], {"status": "FULFILLED"}, SUPERVISOR)
        data = validate_success(fulfilled, 200)
        assert data["status"] == "FULFILLED"
        assert data["allocated_cy"] == pytest.approx(1.0)

    def test_event_close_expires_claims_and_releases_pool(self):
        """PRD section 3.6: "Closing (`OPEN → CLOSED`) happens manually or
        automatically when the checkpoint finds the clock past `pickup_end`,
        and it expires every claim still `CONFIRMED` or `WAITLISTED` on the
        event to `EXPIRED`, releasing their allocations back to the tier pools
        and running the promotion sweep".

        Design: Corner/state_machines/event_close_expires_claims_and_releases_pool
        """
        ctx = setup_mulch_pool(produced_cy=3.0, num_general_households=1,
                               with_participant=False)
        event = ctx["event"]
        claim = create_claim(event["id"], ctx["generals"][0],
                             requested_cy=1.0)
        assert claim["status"] == "CONFIRMED"

        # Before close: general pool 3.00 - round2(1.80) = 1.20, minus the
        # 1.00 allocation leaves 0.20.
        program = get_program(ctx["program"]["id"])
        assert program["general_remaining_cy"] == pytest.approx(0.2)

        resp = api_client.patch_mulch_event(event["id"], {"status": "CLOSED"},
                                            ADMIN)
        assert validate_success(resp, 200)["status"] == "CLOSED"
        assert get_claim(claim["id"])["status"] == "EXPIRED"

        program_after = get_program(ctx["program"]["id"])
        assert program_after["general_remaining_cy"] == pytest.approx(1.2), \
            "the expired claim's allocation returns to the general pool"
