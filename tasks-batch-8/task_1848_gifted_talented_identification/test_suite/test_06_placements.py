"""Service placements: offers, seats, waitlists, expiry, and exits."""
from test_helpers import (
    CLOCK_TODAY,
    TEST_USERS,
    ApiErrorId,
    accept_placement,
    api_client,
    assert_service_placement,
    assert_site_occupancy_invariants,
    create_placement_payload,
    create_site,
    create_student,
    create_transfer_honor_case,
    get_placement,
    get_site,
    get_student,
    make_parent_guardian_headers,
    offer_placement,
    set_clock,
    setup_active_placement,
    setup_cycle_in_state,
    setup_full_site_with_waitlist,
    setup_honored_student,
    setup_scored_case,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_placement,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestPlacementOffer:
    def test_placement_offer_stamps_accept_window(self, api):
        """PRD §3.6: "The new placement enters `OFFERED` with `offered_on` set
        to today and `accept_by` set to 30 days after `offered_on`."
        PRD §3.6: "The placement denormalizes the case's `student_id` at
        creation".

        Design: Corner/entities/placement_offer_stamps_accept_window
        """
        ctx = setup_honored_student()
        resp = api.create_placement(
            ctx["case"]["id"],
            create_placement_payload(site_id=ctx["site"]["id"],
                                     service_model="CLUSTER",
                                     start_on="2026-09-01"),
            GC)
        placement = validate_success(resp, 201)
        assert_service_placement(placement)
        assert placement["status"] == "OFFERED"
        assert placement["offered_on"] == "2026-08-20"
        assert placement["accept_by"] == "2026-09-19"
        assert placement["student_id"] == ctx["student"]["id"]
        assert placement["end_on"] is None

    def test_placement_offer_requires_identified_case_awaiting(self, api):
        """PRD §3.6: "A `GiftedCoordinator` offers a `ServicePlacement`
        against an `IDENTIFIED` case — offering against any other case state
        fails with `ERR_INVALID_CASE_STATE`".

        Design: Difficulty/cross_entity_state_dependency/placement_offer_requires_identified_case
        """
        ctx = setup_scored_case(99, 90, 88)  # composite 94 -> AWAITING_COMMITTEE
        assert ctx["case"]["status"] == "AWAITING_COMMITTEE"
        resp = api.create_placement(
            ctx["case"]["id"],
            create_placement_payload(site_id=ctx["site"]["id"],
                                     service_model="PULL_OUT",
                                     start_on="2026-09-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE.value)
        lst = validate_success(
            api.list_case_placements(ctx["case"]["id"], GC), 200)
        assert lst == [], "no placement row may be created for a non-IDENTIFIED case"

    def test_placement_offer_requires_identified_case_not_identified(self, api):
        """PRD §3.6: "offering against any other case state fails with
        `ERR_INVALID_CASE_STATE`".

        Design: Difficulty/cross_entity_state_dependency/placement_offer_requires_identified_case
        """
        ctx = setup_scored_case(80, 80, 80)  # composite 80 < floor 88
        assert ctx["case"]["status"] == "NOT_IDENTIFIED"
        resp = api.create_placement(
            ctx["case"]["id"],
            create_placement_payload(site_id=ctx["site"]["id"],
                                     service_model="PULL_OUT",
                                     start_on="2026-09-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE.value)
        lst = validate_success(
            api.list_case_placements(ctx["case"]["id"], GC), 200)
        assert lst == []


class TestSeatAcceptWaitlist:
    def test_accept_into_full_site_lands_waitlisted(self, api):
        """PRD §3.6: "Acceptance while the offer is `OFFERED` branches on
        seat availability, and this branch is **not an error path**: if the
        site's occupancy for the placement's model is strictly below that
        model's capacity, the placement becomes `ACTIVE` and the site's
        occupied counter for that model increments by one; if occupancy has
        already reached capacity, the placement instead becomes `WAITLISTED`,
        with `waitlisted_at` stamped to the current logical clock timestamp."

        Design: Difficulty/non_linear_state_machine/placement_waitlist_offer_cycle
        """
        ctx = setup_full_site_with_waitlist(capacity=1)
        pb = ctx["pb"]
        assert pb["status"] == "WAITLISTED"
        assert pb["waitlisted_at"] is not None, (
            "waitlisted_at must be stamped at entry into WAITLISTED")
        site = get_site(ctx["site"]["id"])
        assert site["pull_out_occupied"] == 1, (
            "the waitlisted placement holds no seat; only the ACTIVE one counts")
        assert_site_occupancy_invariants(site)

    def test_waitlist_promotion_restamps_offer_window(self, api):
        """PRD §3.6: "Promotion takes the `WAITLISTED` placements at the
        pair, orders them by `waitlisted_at` ascending with `created_at`
        ascending as the tie-break — never by entity id — and promotes
        exactly one, the head of the queue, per released seat: it re-enters
        `OFFERED` with `offered_on` set to today, a fresh `accept_by` of
        today plus 30 days, and `waitlisted_at` nulled."

        Design: Difficulty/non_linear_state_machine/placement_waitlist_offer_cycle
        """
        ctx = setup_full_site_with_waitlist(capacity=1)
        withdraw_placement(ctx["pa"]["id"])
        pb = get_placement(ctx["pb"]["id"])
        assert pb["status"] == "OFFERED"
        assert pb["offered_on"] == "2026-08-20"
        assert pb["accept_by"] == "2026-09-19"
        assert pb["waitlisted_at"] is None
        # The promoted offer holds no seat until accepted.
        assert get_site(ctx["site"]["id"])["pull_out_occupied"] == 0
        # Completing the loop: the promoted offer can now be accepted.
        accepted = accept_placement(pb["id"], "guard-b")
        assert accepted["status"] == "ACTIVE"
        site = get_site(ctx["site"]["id"])
        assert site["pull_out_occupied"] == 1
        assert_site_occupancy_invariants(site)


class TestOfferExpiry:
    def test_placement_offer_expires_via_clock(self, api):
        """PRD §3.6: "When the logical clock is set past a placement's
        `accept_by` — accept is allowed while today is no later than
        `accept_by` — the placement moves `OFFERED` → `EXPIRED`
        automatically as part of the clock-set sweep".
        PRD §3.6: "Accepting a placement not in `OFFERED` fails with
        `ERR_INVALID_PLACEMENT_STATE`."

        Design: Corner/state_machines/placement_offer_expires_via_clock
        """
        ctx = setup_honored_student()
        placement = offer_placement(ctx["case"]["id"], ctx["site"]["id"],
                                    "PULL_OUT")
        assert placement["accept_by"] == "2026-09-19"
        guardian = ctx["student"]["primary_guardian_user_id"]

        # On accept_by itself the offer is still acceptable.
        set_clock("2026-09-19T00:00:00Z")
        assert get_placement(placement["id"])["status"] == "OFFERED"

        # One day later the offer has expired.
        set_clock("2026-09-20T00:00:00Z")
        assert get_placement(placement["id"])["status"] == "EXPIRED"
        resp = api.accept_placement(
            placement["id"], make_parent_guardian_headers(guardian))
        validate_error(resp, ApiErrorId.ERR_INVALID_PLACEMENT_STATE.value)


class TestGuardianOwnershipPrecedence:
    def test_guardian_mismatch_beats_placement_state_on_accept(self, api):
        """PRD §2.5: "Checks run in this priority order: ... 3. Guardian
        ownership where the endpoint is guardian-scoped
        (`ERR_GUARDIAN_MISMATCH`). ... 7. State preconditions ...".
        PRD §3.6: "only the student's own guardian — the caller's `X-User-ID`
        must match the student's `primary_guardian_user_id`, else
        `ERR_GUARDIAN_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/guardian_ownership_beats_placement_state
        """
        ctx = setup_active_placement()  # placement already ACTIVE
        assert ctx["placement"]["status"] == "ACTIVE"
        # A different guardian calls accept: both the ownership rule (priority
        # 3) and the state rule (accept requires OFFERED, priority 7) are
        # violated; ownership wins.
        resp = api.accept_placement(
            ctx["placement"]["id"], make_parent_guardian_headers("guard-2"))
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_MISMATCH.value)
        assert get_placement(ctx["placement"]["id"])["status"] == "ACTIVE"

    def test_guardian_mismatch_beats_placement_state_on_decline(self, api):
        """PRD §2.5: "3. Guardian ownership where the endpoint is
        guardian-scoped (`ERR_GUARDIAN_MISMATCH`). ... 7. State preconditions
        (`ERR_INVALID_CYCLE_STATE`, ..., `ERR_INVALID_PLACEMENT_STATE`,
        ...)".
        PRD §3.6: "only the student's own guardian — the caller's `X-User-ID`
        must match the student's `primary_guardian_user_id`, else
        `ERR_GUARDIAN_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/guardian_ownership_beats_placement_state
        """
        ctx = setup_active_placement()  # ACTIVE: decline requires OFFERED/WAITLISTED
        resp = api.decline_placement(
            ctx["placement"]["id"], make_parent_guardian_headers("guard-2"))
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_MISMATCH.value)
        assert get_placement(ctx["placement"]["id"])["status"] == "ACTIVE"


class TestSeatInventoryInvariant:
    def test_seat_inventory_conserved_across_accept_withdraw(self, api):
        """PRD §3.6: "if the site's occupancy for the placement's model is
        strictly below that model's capacity, the placement becomes `ACTIVE`
        and the site's occupied counter for that model increments by one".
        PRD §3.6: "Either way the exit stamps `end_on` as today, flips the
        student's `gifted_status` to `EXITED`, decrements the site's occupied
        counter for the model by one, and then runs waitlist promotion for
        that site-and-model pair."

        Design: Difficulty/compensating_invariant/seat_inventory_conserved_across_accept_withdraw
        """
        ctx = setup_honored_student(
            site_overrides={"pull_out_capacity": 2})
        placement = offer_placement(ctx["case"]["id"], ctx["site"]["id"],
                                    "PULL_OUT")
        occ_before = get_site(ctx["site"]["id"])["pull_out_occupied"]
        assert occ_before == 0, "an OFFERED placement consumes no seat"

        accept_placement(placement["id"],
                         ctx["student"]["primary_guardian_user_id"])
        occ_mid = get_site(ctx["site"]["id"])["pull_out_occupied"]
        assert occ_mid == 1, "accept consumed exactly one seat"

        withdraw_placement(placement["id"])
        occ_after = get_site(ctx["site"]["id"])["pull_out_occupied"]
        assert occ_after == 0, "withdraw released exactly the accepted seat"
        assert occ_after == occ_before, (
            "the accept/withdraw round trip conserves seat inventory")

    def test_withdraw_stamps_exit_fields(self, api):
        """PRD §3.6: "Either way the exit stamps `end_on` as today, flips the
        student's `gifted_status` to `EXITED`, decrements the site's occupied
        counter for the model by one, and then runs waitlist promotion for
        that site-and-model pair."

        Design: Difficulty/compensating_invariant/seat_inventory_conserved_across_accept_withdraw
        """
        ctx = setup_active_placement()
        withdraw_placement(ctx["placement"]["id"])
        placement = get_placement(ctx["placement"]["id"])
        assert placement["status"] == "EXITED"
        assert placement["end_on"] == "2026-08-20"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "EXITED"
        site = get_site(ctx["site"]["id"])
        assert site["pull_out_occupied"] == 0
        assert_site_occupancy_invariants(site)


class TestPlacementPeriodOverlap:
    def test_open_ended_period_overlaps_any_future_start(self, api):
        """PRD §3.6: "one student may never hold two placements whose service
        periods overlap — an open-ended placement (its `end_on` still null)
        is treated as extending to infinity — and a clashing offer is
        rejected with `ERR_PLACEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/placement_open_ended_period_overlap
        """
        ctx = setup_active_placement()  # ACTIVE, start 2026-09-01, end null
        resp = api.create_placement(
            ctx["case"]["id"],
            create_placement_payload(site_id=ctx["site"]["id"],
                                     service_model="CLUSTER",
                                     start_on="2027-01-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_PERIOD_OVERLAP.value)
        placement = get_placement(ctx["placement"]["id"])
        assert placement["status"] == "ACTIVE"
        assert placement["end_on"] is None

    def test_period_overlap_lifted_after_exit(self, api):
        """PRD §3.6: "one student may never hold two placements whose service
        periods overlap — an open-ended placement (its `end_on` still null)
        is treated as extending to infinity".
        PRD §3.6: "the exit stamps `end_on` as today".

        Design: Difficulty/resource_temporal_overlap/placement_open_ended_period_overlap
        """
        ctx = setup_active_placement()
        withdraw_placement(ctx["placement"]["id"])
        # The exited placement's period now ends today (2026-08-20); a new
        # offer whose period starts after that no longer overlaps.
        new_placement = offer_placement(ctx["case"]["id"], ctx["site"]["id"],
                                        "CLUSTER", start_on="2026-08-21")
        assert new_placement["status"] == "OFFERED"


class TestWaitlistFifo:
    def test_waitlist_promotion_fifo_order(self, api):
        """PRD §3.6: "Promotion takes the `WAITLISTED` placements at the
        pair, orders them by `waitlisted_at` ascending with `created_at`
        ascending as the tie-break — never by entity id — and promotes
        exactly one, the head of the queue, per released seat".
        PRD §3.6: "The promoted placement consumes a seat only when it is
        later accepted; if the waitlist is empty, promotion is a no-op rather
        than an error."

        Design: Corner/state_machines/waitlist_promotion_fifo_order
        """
        set_clock(CLOCK_TODAY)
        site = create_site(pull_out_capacity=1)
        cycle, _ = setup_cycle_in_state("OPEN")
        students = {}
        cases = {}
        for tag, group in (("A", "WHITE"), ("B", "BLACK"), ("C", "HISPANIC")):
            stu = create_student(
                site["id"], student_number=f"ST-{tag}",
                legal_name=f"Stu {tag}", grade_level=3,
                demographic_group=group,
                primary_guardian_user_id=f"guard-{tag.lower()}")
            students[tag] = stu
            cases[tag] = create_transfer_honor_case(stu["id"], cycle["id"])
        pa = offer_placement(cases["A"]["id"], site["id"], "PULL_OUT")
        accept_placement(pa["id"], "guard-a")
        # B waitlists at 2026-08-20.
        pb = offer_placement(cases["B"]["id"], site["id"], "PULL_OUT")
        pb = accept_placement(pb["id"], "guard-b")
        assert pb["status"] == "WAITLISTED"
        # C waitlists a day later.
        set_clock("2026-08-21T00:00:00Z")
        pc = offer_placement(cases["C"]["id"], site["id"], "PULL_OUT")
        pc = accept_placement(pc["id"], "guard-c")
        assert pc["status"] == "WAITLISTED"

        withdraw_placement(pa["id"])

        pb_after = get_placement(pb["id"])
        assert pb_after["status"] == "OFFERED", (
            "the earlier-waitlisted placement is the head of the queue")
        assert pb_after["offered_on"] == "2026-08-21"
        assert pb_after["accept_by"] == "2026-09-20"
        assert pb_after["waitlisted_at"] is None
        pc_after = get_placement(pc["id"])
        assert pc_after["status"] == "WAITLISTED", (
            "exactly one promotion runs per released seat")
        assert pc_after["waitlisted_at"] is not None
        assert get_site(site["id"])["pull_out_occupied"] == 0
