"""Curbside bookings: capacity boundaries, lifecycle cycle, dual tonnage,
attestation, validation precedence, listing, and ops-run expiry."""
import pytest

from test_helpers import (
    ADMIN,
    SUPERVISOR,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_zone,
    api_client,
    assert_booking,
    assert_same_instant,
    assert_zone_capacity_invariant,
    create_active_program,
    create_confirmed_booking,
    get_booking,
    get_zone,
    make_resident_headers,
    patch_zone,
    record_booking_outcome,
    register_household,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

WINDOW_MID = "2027-01-05T00:00:00Z"


class TestBookingCreationGates:

    def test_prep_attestation_false_rejected(self):
        """PRD section 3.2: "The attestation is the resident's sworn statement
        that the trees carry no stands, decorations, tinsel, or flocking; it
        must be true, and a missing or false attestation is rejected with
        `ERR_PREP_ATTESTATION_REQUIRED`."

        Design: Corner/entities/prep_attestation_false_rejected
        """
        ctx = create_active_program()
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        resp = api_client.create_booking(
            {"household_id": household["id"], "zone_id": ctx["zone"]["id"],
             "tree_count": 1, "size_class": "SMALL", "prep_attestation": False},
            make_resident_headers(household["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PREP_ATTESTATION_REQUIRED)
        data, meta = validate_paginated(api_client.list_bookings(
            ADMIN, params={"household_id": household["id"]}))
        assert data == [], "a rejected booking must not be persisted"

    def test_booking_get_not_found_returns_404(self):
        """PRD section 2.7: "Fourth, existence: every path identifier — all
        resource paths in this API are flat, addressed by a single `id` — and
        every foreign-key reference in the request body (program, site, zone,
        household, booking, event, volunteer, ticket, run, claim, report) must
        exist, failing which the request is rejected with `ERR_NOT_FOUND`."

        Design: Corner/entities/booking_get_not_found_returns_404
        """
        resp = api_client.get_booking(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.json()["response_type"] == "error"

    def test_cancel_serviced_booking_returns_invalid_state(self):
        """PRD section 3.2: "`SERVICED`, `CANCELLED`, and
        `REJECTED_CONTAMINATED` are terminal, and any transition not declared
        here — from a terminal state above all — is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_serviced_booking_returns_invalid_state
        """
        ctx = create_active_program()
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        booking = create_confirmed_booking(household, ctx["zone"]["id"])
        record_booking_outcome(booking["id"], "SERVICED")

        resp = api_client.cancel_booking(
            booking["id"], make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_booking(booking["id"])["status"] == "SERVICED"

    def test_reschedule_wrong_date_rejected(self):
        """PRD section 3.2: "Rescheduling moves `MISSED → CONFIRMED` and is
        guarded four ways: the `new_service_date` must equal the zone's
        current `collection_date` (`ERR_BOOKING_DATE_MISMATCH` otherwise)".

        Design: Corner/validations/reschedule_wrong_date_rejected
        """
        ctx = create_active_program()
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        booking = create_confirmed_booking(household, ctx["zone"]["id"])
        record_booking_outcome(booking["id"], "MISSED")
        assert get_zone(ctx["zone"]["id"])["reserved_trees"] == 0

        set_clock(WINDOW_MID)
        resp = api_client.reschedule_booking(
            booking["id"], {"new_service_date": "2027-01-12T00:00:00Z"},
            make_resident_headers(household["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_DATE_MISMATCH)
        assert get_booking(booking["id"])["status"] == "MISSED"
        assert get_zone(ctx["zone"]["id"])["reserved_trees"] == 0


class TestRouteCapacityExactFit:

    def test_exact_fit_booking_admitted(self):
        """PRD section 3.2: "Finally the route's tree capacity is checked: the
        booking is admitted only while the zone's `reserved_trees` plus the
        new `tree_count` stays at or below `daily_tree_capacity` — exact
        equality is admitted, and a single tree over the limit is rejected
        with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        h1 = register_household(ctx["program"]["id"], zone["id"])
        create_confirmed_booking(h1, zone["id"], tree_count=3,
                                 size_class="MEDIUM")

        h2 = register_household(ctx["program"]["id"], zone["id"])
        booking = create_confirmed_booking(h2, zone["id"], tree_count=2,
                                           size_class="SMALL")
        assert booking["status"] == "CONFIRMED", \
            "reserved 3 + 2 == capacity 5 must be admitted (equality)"

        zone_after = get_zone(zone["id"])
        assert zone_after["reserved_trees"] == 5
        assert zone_after["remaining_capacity"] == 0
        assert_zone_capacity_invariant(zone_after)

    def test_one_tree_over_capacity_rejected(self):
        """PRD section 3.2: "the booking is admitted only while the zone's
        `reserved_trees` plus the new `tree_count` stays at or below
        `daily_tree_capacity` — exact equality is admitted, and a single tree
        over the limit is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        h1 = register_household(ctx["program"]["id"], zone["id"])
        create_confirmed_booking(h1, zone["id"], tree_count=3,
                                 size_class="MEDIUM")
        h2 = register_household(ctx["program"]["id"], zone["id"])
        create_confirmed_booking(h2, zone["id"], tree_count=2,
                                 size_class="SMALL")

        h3 = register_household(ctx["program"]["id"], zone["id"])
        resp = api_client.create_booking(
            {"household_id": h3["id"], "zone_id": zone["id"], "tree_count": 1,
             "size_class": "SMALL", "prep_attestation": True},
            make_resident_headers(h3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        zone_after = get_zone(zone["id"])
        assert zone_after["reserved_trees"] == 5, \
            "a rejected booking must not reserve capacity"


class TestBookingCapacityConservation:

    def test_create_reserves_route_capacity(self):
        """PRD section 3.2: "A booking is created directly in `CONFIRMED`
        status... Creation immediately adds the `tree_count` to the zone's
        `reserved_trees` and recomputes the zone's tonnage figures."

        Design: Difficulty/compensating_invariant/booking_create_cancel_capacity_conservation
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=2, size_class="MEDIUM")
        assert booking["status"] == "CONFIRMED"

        zone_after = get_zone(zone["id"])
        assert zone_after["reserved_trees"] == 2
        assert zone_after["remaining_capacity"] == 3
        assert_zone_capacity_invariant(zone_after)

    def test_cancel_releases_route_capacity(self):
        """PRD section 3.2: "Cancellation is available to the resident or an
        administrator from either `CONFIRMED` or `MISSED`, moving the booking
        to `CANCELLED`; when the booking was `CONFIRMED`, its `tree_count`
        comes off `reserved_trees`."

        Design: Difficulty/compensating_invariant/booking_create_cancel_capacity_conservation
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=2, size_class="MEDIUM")
        assert get_zone(zone["id"])["reserved_trees"] == 2

        resp = api_client.cancel_booking(
            booking["id"], make_resident_headers(household["id"]))
        cancelled = validate_success(resp, 200)
        assert cancelled["status"] == "CANCELLED"

        zone_after = get_zone(zone["id"])
        assert zone_after["reserved_trees"] == 0
        assert zone_after["remaining_capacity"] == 5
        assert_zone_capacity_invariant(zone_after)


class TestMissedReconfirmCycle:

    def _setup_missed_booking(self):
        """ACTIVE program, zone capacity 5; booking MISSED via ops-run after
        its service_date passed; zone then moved to a makeup day."""
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=2, size_class="MEDIUM")
        set_clock("2027-01-10T00:00:00Z")  # day after the 2027-01-09 service
        api_client.ops_run_program(ctx["program"]["id"], ADMIN)
        # Makeup-day move: the current collection date has already passed.
        patch_zone(zone["id"], collection_date="2027-01-12T00:00:00Z")
        return ctx, household, booking

    def test_ops_run_expires_booking_and_releases_capacity(self):
        """PRD section 3.2: "The operational checkpoint applies the same
        expiry automatically: any booking still `CONFIRMED` whose
        `service_date` has fallen into the past is moved to `MISSED` with its
        capacity released."

        Design: Difficulty/non_linear_state_machine/booking_missed_reconfirm_cycle
        """
        ctx, household, booking = self._setup_missed_booking()
        booking_after = get_booking(booking["id"])
        assert booking_after["status"] == "MISSED"
        assert get_zone(ctx["zone"]["id"])["reserved_trees"] == 0, \
            "expiry to MISSED must release the reserved route capacity"

    def test_missed_booking_reconfirmed_then_serviced(self):
        """PRD section 3.2: "Rescheduling moves `MISSED → CONFIRMED` and is
        guarded four ways... On success the booking's `service_date` is
        updated to the new date."
        PRD section 3.2: "Recording an `outcome` of `SERVICED` moves the
        booking `CONFIRMED → SERVICED` and stores the optional `actual_tons`
        scale weight if provided, recomputing the zone's
        `collected_tons_actual`".

        Design: Difficulty/non_linear_state_machine/booking_missed_reconfirm_cycle
        """
        ctx, household, booking = self._setup_missed_booking()
        zone = ctx["zone"]

        resp = api_client.reschedule_booking(
            booking["id"], {"new_service_date": "2027-01-12T00:00:00Z"},
            make_resident_headers(household["id"]))
        reconfirmed = validate_success(resp, 200)
        assert reconfirmed["status"] == "CONFIRMED"
        assert_same_instant(reconfirmed["service_date"], "2027-01-12T00:00:00Z")
        assert get_zone(zone["id"])["reserved_trees"] == 2, \
            "re-confirmation must re-reserve the route capacity"

        serviced = record_booking_outcome(booking["id"], "SERVICED",
                                          actual_tons=0.07)
        assert serviced["status"] == "SERVICED"
        assert serviced["actual_tons"] == pytest.approx(0.07)


class TestDualVariantTonnage:

    def test_provisional_counts_confirmed_actual_prefers_scale_weight(self):
        """PRD section 3.2: "Those figures are deliberately dual:
        `projected_tons_provisional` looks forward, summing over the zone's
        `CONFIRMED` bookings the product of each booking's `tree_count` and
        its size-class estimate, while `collected_tons_actual` reconciles
        after the fact, summing over `SERVICED` bookings only and preferring
        each booking's recorded `actual_tons` scale weight when one is
        present, falling back to the same per-tree estimate when it is not.
        Both figures are rounded half-up to three decimal places."
        PRD section 2.8: "a `SMALL` tree is estimated at 0.020 tons, a
        `MEDIUM` tree at 0.035 tons, a `LARGE` tree at 0.050 tons, and a
        `MIXED` load at 0.030 tons per tree."

        Design: Difficulty/dual_variant_calc/route_projection_provisional_vs_actual
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10})
        zone = ctx["zone"]
        h1 = register_household(ctx["program"]["id"], zone["id"])
        create_confirmed_booking(h1, zone["id"], tree_count=2,
                                 size_class="LARGE")  # 2 * 0.050
        h2 = register_household(ctx["program"]["id"], zone["id"])
        b2 = create_confirmed_booking(h2, zone["id"], tree_count=1,
                                      size_class="MEDIUM")
        record_booking_outcome(b2["id"], "SERVICED", actual_tons=0.040)

        zone_after = get_zone(zone["id"])
        assert zone_after["projected_tons_provisional"] == pytest.approx(0.1)
        assert zone_after["collected_tons_actual"] == pytest.approx(0.04)
        assert zone_after["projected_tons_provisional"] != \
            zone_after["collected_tons_actual"], \
            "the two variants must diverge on identical zone data"

    def test_actual_falls_back_to_estimate_without_scale_weight(self):
        """PRD section 3.2: "`collected_tons_actual` reconciles after the
        fact, summing over `SERVICED` bookings only and preferring each
        booking's recorded `actual_tons` scale weight when one is present,
        falling back to the same per-tree estimate when it is not."
        PRD section 2.8: "a `MEDIUM` tree at 0.035 tons, a `LARGE` tree at
        0.050 tons".

        Design: Difficulty/dual_variant_calc/route_projection_provisional_vs_actual
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10})
        zone = ctx["zone"]
        h1 = register_household(ctx["program"]["id"], zone["id"])
        create_confirmed_booking(h1, zone["id"], tree_count=1,
                                 size_class="LARGE")  # provisional only
        h2 = register_household(ctx["program"]["id"], zone["id"])
        b2 = create_confirmed_booking(h2, zone["id"], tree_count=2,
                                      size_class="MEDIUM")
        record_booking_outcome(b2["id"], "SERVICED")  # no actual_tons

        zone_after = get_zone(zone["id"])
        # PROVISIONAL counts only the CONFIRMED booking: 1 * 0.050.
        assert zone_after["projected_tons_provisional"] == \
            pytest.approx(0.05)
        # ACTUAL counts only the SERVICED booking at the estimate: 2 * 0.035.
        assert zone_after["collected_tons_actual"] == pytest.approx(0.07)


class TestZoneStatusGate:

    def test_booking_rejected_while_zone_suspended(self):
        """PRD section 3.1: "an administrator may move a zone
        `ACTIVE → SUSPENDED`, which rejects new bookings against it with
        `ERR_ZONE_SUSPENDED` while leaving existing `CONFIRMED` bookings
        unaffected".

        Design: Difficulty/cross_entity_state_dependency/booking_requires_zone_active
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])

        patch_zone(zone["id"], status="SUSPENDED")
        resp = api_client.create_booking(
            {"household_id": household["id"], "zone_id": zone["id"],
             "tree_count": 1, "size_class": "SMALL", "prep_attestation": True},
            make_resident_headers(household["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_SUSPENDED)

    def test_booking_admitted_after_zone_reactivated(self):
        """PRD section 3.1: "an administrator may move a zone
        `ACTIVE → SUSPENDED`, which rejects new bookings against it with
        `ERR_ZONE_SUSPENDED` while leaving existing `CONFIRMED` bookings
        unaffected, and may later reactivate it (`SUSPENDED → ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_zone_active
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])

        patch_zone(zone["id"], status="SUSPENDED")
        patch_zone(zone["id"], status="ACTIVE")
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=1, size_class="SMALL")
        assert booking["status"] == "CONFIRMED"
        assert get_zone(zone["id"])["reserved_trees"] == 1


class TestValidationPrecedence:

    def test_reschedule_state_before_temporal(self):
        """PRD section 2.7: "A failure at any stage short-circuits all later
        stages, and the relative order below is normative — it determines
        which error surfaces when several rules are violated at once."
        PRD section 2.7: "Fifth, state legality: the target resource must be
        in a state from which the requested transition is declared, including
        terminal-state lockdown; violations surface as `ERR_INVALID_STATE`."
        PRD section 3.2: "that collection date must still lie in the future
        (`ERR_OUTSIDE_COLLECTION_WINDOW`)".

        Design: Difficulty/priority_pair_validation_conflict/reschedule_state_before_temporal
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        booking = create_confirmed_booking(household, ctx["zone"]["id"])
        record_booking_outcome(booking["id"], "SERVICED")

        # SERVICED is terminal for reschedule AND the target date is outside
        # the collection window; the state error must win (stage 5 before
        # stage 9).
        resp = api_client.reschedule_booking(
            booking["id"], {"new_service_date": "2027-02-01T00:00:00Z"},
            make_resident_headers(household["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_booking(booking["id"])["status"] == "SERVICED"

    def test_reschedule_state_before_temporal_cancelled_booking(self):
        """PRD section 2.7: "A failure at any stage short-circuits all later
        stages, and the relative order below is normative — it determines
        which error surfaces when several rules are violated at once."
        PRD section 3.2: "`SERVICED`, `CANCELLED`, and
        `REJECTED_CONTAMINATED` are terminal, and any transition not declared
        here — from a terminal state above all — is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/reschedule_state_before_temporal
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        household = register_household(ctx["program"]["id"],
                                       ctx["zone"]["id"])
        booking = create_confirmed_booking(household, ctx["zone"]["id"])
        api_client.cancel_booking(booking["id"],
                                  make_resident_headers(household["id"]))

        # CANCELLED is terminal for reschedule AND the date is out of window;
        # the state error must win.
        resp = api_client.reschedule_booking(
            booking["id"], {"new_service_date": "2027-02-01T00:00:00Z"},
            make_resident_headers(household["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_booking(booking["id"])["status"] == "CANCELLED"

    def test_zone_mismatch_wins_over_full_route(self):
        """PRD section 2.7: "Eighth, referential coherence: a booking's zone
        must equal its household's zone (`ERR_ZONE_MISMATCH`)".
        PRD section 2.7: "Eleventh and last, capacity and quota checks always
        run after every other rule has passed: route tree capacity
        (`ERR_ROUTE_CAPACITY_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/booking_referential_before_fiscal
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 1})
        program = ctx["program"]
        z1 = ctx["zone"]
        z2 = add_zone(program["id"], zone_code="NE-9",
                      collection_date="2027-01-10T00:00:00Z",
                      daily_tree_capacity=5)

        h1 = register_household(program["id"], z1["id"])
        create_confirmed_booking(h1, z1["id"], tree_count=1,
                                 size_class="SMALL")  # z1 now full
        h2 = register_household(program["id"], z2["id"])

        # z1 is full (capacity 1) AND z1 != h2's zone: referential (stage 8)
        # must surface before the capacity check (stage 11).
        resp = api_client.create_booking(
            {"household_id": h2["id"], "zone_id": z1["id"], "tree_count": 1,
             "size_class": "MEDIUM", "prep_attestation": True},
            make_resident_headers(h2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH)
        assert get_zone(z1["id"])["reserved_trees"] == 1

    def test_zone_mismatch_wins_over_oversized_request(self):
        """PRD section 2.7: "Eighth, referential coherence: a booking's zone
        must equal its household's zone (`ERR_ZONE_MISMATCH`)".
        PRD section 2.7: "Eleventh and last, capacity and quota checks always
        run after every other rule has passed: route tree capacity
        (`ERR_ROUTE_CAPACITY_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/booking_referential_before_fiscal
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 1})
        program = ctx["program"]
        z1 = ctx["zone"]  # empty, capacity 1
        z2 = add_zone(program["id"], zone_code="NE-9",
                      collection_date="2027-01-10T00:00:00Z",
                      daily_tree_capacity=5)
        h2 = register_household(program["id"], z2["id"])

        # 5 trees cannot fit z1's capacity 1 AND z1 != h2's zone; the
        # referential mismatch (stage 8) must surface first.
        resp = api_client.create_booking(
            {"household_id": h2["id"], "zone_id": z1["id"], "tree_count": 5,
             "size_class": "MEDIUM", "prep_attestation": True},
            make_resident_headers(h2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH)
        assert get_zone(z1["id"])["reserved_trees"] == 0


class TestBookingListing:

    def test_bookings_list_pagination_envelope(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; when omitted it defaults to 10, and it accepts a minimum of
        1 and a maximum of 100. The `offset` parameter specifies how many
        items to skip and defaults to 0. Every list response carries `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."
        PRD section 2.3: "bookings by `household_id`, `zone_id`, and
        `status`".

        Design: Corner/endpoints/bookings_list_pagination_envelope
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])
        for trees, size in ((1, "SMALL"), (2, "MEDIUM"), (1, "LARGE")):
            create_confirmed_booking(household, zone["id"],
                                     tree_count=trees, size_class=size)

        page1, meta1 = validate_paginated(api_client.list_bookings(
            ADMIN, params={"household_id": household["id"],
                           "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_bookings(
            ADMIN, params={"household_id": household["id"],
                           "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for booking in page1 + page2:
            assert_booking(booking)

    def test_bookings_list_combined_filters(self):
        """PRD section 2.3: "List endpoints also accept filter parameters
        drawn from their resource's references and status: ... bookings by
        `household_id`, `zone_id`, and `status`".

        Design: Corner/endpoints/bookings_list_combined_filters
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10})
        program, z1 = ctx["program"], ctx["zone"]
        z2 = add_zone(program["id"], zone_code="NW-2",
                      collection_date="2027-01-10T00:00:00Z",
                      daily_tree_capacity=10)
        h1 = register_household(program["id"], z1["id"])
        h2 = register_household(program["id"], z2["id"])
        b1 = create_confirmed_booking(h1, z1["id"])
        create_confirmed_booking(h1, z1["id"])
        create_confirmed_booking(h2, z2["id"])
        api_client.cancel_booking(b1["id"], make_resident_headers(h1["id"]))

        data, meta = validate_paginated(api_client.list_bookings(
            SUPERVISOR, params={"zone_id": z1["id"], "status": "CONFIRMED"}))
        assert len(data) == 1, "only the uncancelled z1 booking may match"
        assert data[0]["zone_id"] == z1["id"]
        assert data[0]["status"] == "CONFIRMED"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestOpsRunExpiry:

    def test_ops_run_expires_stale_confirmed_booking(self):
        """PRD section 3.8: "Every booking still `CONFIRMED` whose
        `service_date` has fallen into the past is moved to `MISSED` with its
        reserved capacity released."

        Design: Corner/complexity_layers/ops_run_expires_stale_confirmed_booking
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        zone = ctx["zone"]
        household = register_household(ctx["program"]["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=2, size_class="MEDIUM")
        assert get_zone(zone["id"])["reserved_trees"] == 2

        set_clock("2027-01-10T00:00:00Z")  # service_date 2027-01-09 is past
        validate_success(
            api_client.ops_run_program(ctx["program"]["id"], ADMIN), 200)

        assert get_booking(booking["id"])["status"] == "MISSED"
        zone_after = get_zone(zone["id"])
        assert zone_after["reserved_trees"] == 0
        assert_zone_capacity_invariant(zone_after)
