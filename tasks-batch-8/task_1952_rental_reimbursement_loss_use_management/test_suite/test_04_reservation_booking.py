"""Reservation booking: shape gates, referential gates, interval rules, fleet
capacity, and RBAC on the booking pipeline."""
import pytest

from test_helpers import (
    ADJUSTER,
    ADMIN,
    DESK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    ReservationStatus,
    add_approved_repair_order,
    api_client,
    approve_repair_order,
    assert_rental_reservation,
    authorize_reservation,
    book_reservation,
    create_rental_reservation_payload,
    create_repair_order,
    get_claim_view,
    get_reservation_view,
    make_customer_headers,
    open_claim,
    register_policyholder,
    register_rental_partner,
    register_repair_shop,
    set_clock,
    setup_verified_claim_context,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim_coverage,
)


class TestBookingShapeGates:
    def test_reservation_invalid_enum_rejected(self, api):
        """PRD §3.4: "selects a `vehicle_class` of `ECONOMY`, `STANDARD`, or
        `PREMIUM`"
        PRD §2.7: "a missing required field, a type mismatch, an invalid enum
        value, a decision-specific required field that is absent (a
        `denial_reason` on a denial, a `new_estimated_completion_date` on a delay
        report), or an amount outside its permitted range fails with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/reservation_invalid_enum_rejected
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        claim = get_claim_view(ctx["claim"]["id"])
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                claim["version"], vehicle_class="LUXURY"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_reservation_create_body_fk_not_found(self, api):
        """PRD §2.8: "The same codes apply when a body-referenced identifier does
        not exist — creating a reservation against a missing repair order fails
        with `ERR_REPAIR_ORDER_NOT_FOUND`, and creating an extension request
        against a missing milestone fails with `ERR_MILESTONE_NOT_FOUND`."

        The repair order referenced here is real, so the only missing body
        reference is the claim itself.

        Design: Corner/entities/reservation_create_body_fk_not_found
        """
        policyholder = register_policyholder()
        shop = register_repair_shop()
        partner = register_rental_partner()
        claim = open_claim(policyholder["id"])
        order = create_repair_order(claim["id"], shop["id"])

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                NON_EXISTENT_UUID, partner["id"], order["id"],
                expected_claim_version=1),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    def test_repair_order_claim_mismatch_rejected(self, api):
        """PRD §3.4: "the repair order must belong to the same claim as the
        reservation — a cross-claim reference fails with
        `ERR_REPAIR_ORDER_MISMATCH`"

        Design: Corner/validations/repair_order_claim_mismatch_rejected
        """
        policyholder = register_policyholder()
        shop = register_repair_shop()
        partner = register_rental_partner()

        claim_a = open_claim(policyholder["id"], incident_date="2026-07-28")
        verify_claim_coverage(claim_a["id"], rental_eligible=True,
                              loss_of_use_eligible=False)
        order_a = create_repair_order(claim_a["id"], shop["id"])
        approve_repair_order(order_a["id"])

        claim_b = open_claim(policyholder["id"], incident_date="2026-07-29")
        verify_claim_coverage(claim_b["id"], rental_eligible=True,
                              loss_of_use_eligible=False)
        claim_b_view = get_claim_view(claim_b["id"])

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                claim_b["id"], partner["id"], order_a["id"],
                claim_b_view["version"]),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_REPAIR_ORDER_MISMATCH)

    def test_rental_zero_length_window_rejected(self, api):
        """PRD §3.4: "the `authorized_return_date` must be strictly later than the
        `pickup_date` (`ERR_INVALID_PERIOD`)"
        PRD §2.4: "An interval whose start equals its end therefore contains zero
        days."

        Design: Corner/calculations/rental_zero_length_window_rejected
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        claim = get_claim_view(ctx["claim"]["id"])
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                claim["version"],
                pickup_date="2026-08-05", authorized_return_date="2026-08-05"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


class TestBookingDefaultsAndConsistency:
    def test_reservation_create_initial_state_and_snapshot(self, api):
        """PRD §3.4: "The reservation lands in `DRAFT` status, with
        `actual_pickup_date`, `actual_return_date`, and `consumed_days` all null,
        `unnecessary_days` zero, and `audited_charge_cents` — the running total of
        settled invoice amounts — starting at zero."
        PRD §3.4: "The partner's three class rates are copied into an immutable
        `rate_card_snapshot` at booking time — later rate-card edits at the
        partner never reach an existing reservation — and the applicable
        `daily_rate_cents` is read off that snapshot for the booked
        `vehicle_class`. The system then derives `authorized_days` as the
        half-open day count of the authorized window and the provisional
        `estimated_charge_cents` as exactly `authorized_days` times the applicable
        `daily_rate_cents`."

        Design: Corner/state_machines/reservation_create_initial_state_and_snapshot
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        reservation = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                       ctx["repair_order"]["id"])
        assert_rental_reservation(reservation)
        assert reservation["status"] == ReservationStatus.DRAFT.value
        assert reservation["authorized_days"] == 10, (
            f"Expected 10 half-open days for 2026-08-05..2026-08-15, "
            f"got {reservation['authorized_days']}"
        )
        assert reservation["daily_rate_cents"] == 6000
        assert reservation["estimated_charge_cents"] == 60000, (
            f"Expected provisional estimate 60000 (10 x 6000), "
            f"got {reservation['estimated_charge_cents']}"
        )
        assert isinstance(reservation["rate_card_snapshot"], dict)
        assert len(reservation["rate_card_snapshot"]) == 3, (
            "The snapshot must carry the partner's three class rates"
        )
        assert reservation["actual_pickup_date"] is None
        assert reservation["actual_return_date"] is None
        assert reservation["consumed_days"] is None
        assert reservation["unnecessary_days"] == 0
        assert reservation["audited_charge_cents"] == 0

    def test_immediate_consistency_response_shows_post_state(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_response_shows_post_state
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        claim = get_claim_view(ctx["claim"]["id"])
        create_resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                claim["version"]),
            DESK,
        )
        created = validate_success(create_resp, 201)
        assert created["status"] == "DRAFT"
        assert created["estimated_charge_cents"] == 60000

        authorize_resp = api.authorize_rental_reservation(created["id"], DESK)
        authorized = validate_success(authorize_resp, 200)
        assert authorized["status"] == "AUTHORIZED", (
            "The authorize response itself must show AUTHORIZED — no re-read needed"
        )


class TestReservationListing:
    def test_reservations_filtered_by_partner(self, api):
        """PRD §3.4: "Reservations can be listed per claim, and the global
        reservation collection accepts optional `rental_partner_id` and
        `repair_order_id` filters."

        Design: Corner/endpoints/reservations_filtered_by_partner
        """
        ctx = setup_verified_claim_context()
        partner_b = register_rental_partner(
            partner_name="RentCo B", partner_code="RC-B",
            economy_rate_cents=5000, standard_rate_cents=6500,
            premium_rate_cents=9500)
        add_approved_repair_order(ctx)
        reservation = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                       ctx["repair_order"]["id"])

        page_a, meta_a = validate_paginated(api.list_rental_reservations(
            DESK, params={"rental_partner_id": ctx["partner"]["id"]}))
        assert meta_a["total_count"] == 1
        assert page_a[0]["id"] == reservation["id"]

        page_b, meta_b = validate_paginated(api.list_rental_reservations(
            DESK, params={"rental_partner_id": partner_b["id"]}))
        assert meta_b["total_count"] == 0
        assert page_b == []


class TestBookingRbac:
    def test_customer_authorize_forbidden(self, api):
        """PRD §2.1: "A caller whose role is not on an endpoint's authorized list
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "| POST | `/rental-reservations/{id}/authorize` | Authorize a
        draft reservation against reserve, cap, and fleet | RentalDeskAgent |"

        Design: Corner/rbac/customer_authorize_forbidden
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        reservation = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                       ctx["repair_order"]["id"])

        resp = api.authorize_rental_reservation(
            reservation["id"], make_customer_headers(ctx["policyholder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_reservation_view(reservation["id"])["status"] == "DRAFT"


class TestReservationWindowOverlap:
    def test_back_to_back_booking_allowed(self, api):
        """PRD §3.4: "The new half-open window must not overlap any existing
        reservation on the same claim in `DRAFT`, `AUTHORIZED`, `ACTIVE`, or
        `EXTENSION_REVIEW` status — overlaps fail with
        `ERR_RESERVATION_PERIOD_OVERLAP`, though back-to-back bookings, where the
        new pickup date equals the earlier reservation's authorized return date,
        are permitted."

        Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_claim
        """
        ctx = setup_verified_claim_context(
            partner_overrides={"standard_capacity": 2})
        add_approved_repair_order(ctx)
        first = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                 ctx["repair_order"]["id"])
        authorize_reservation(first["id"])

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                get_claim_view(ctx["claim"]["id"])["version"],
                pickup_date="2026-08-15", authorized_return_date="2026-08-18"),
            DESK,
        )
        second = validate_success(resp, 201)
        assert second["status"] == ReservationStatus.DRAFT.value, (
            "Back-to-back booking (pickup == prior authorized_return_date) must "
            "be created"
        )

    def test_overlapping_booking_rejected(self, api):
        """PRD §3.4: "The new half-open window must not overlap any existing
        reservation on the same claim in `DRAFT`, `AUTHORIZED`, `ACTIVE`, or
        `EXTENSION_REVIEW` status — overlaps fail with
        `ERR_RESERVATION_PERIOD_OVERLAP`, though back-to-back bookings, where the
        new pickup date equals the earlier reservation's authorized return date,
        are permitted."

        Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_claim
        """
        ctx = setup_verified_claim_context(
            partner_overrides={"standard_capacity": 2})
        add_approved_repair_order(ctx)
        first = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                 ctx["repair_order"]["id"])
        authorize_reservation(first["id"])
        book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                         ctx["repair_order"]["id"],
                         pickup_date="2026-08-15", authorized_return_date="2026-08-18")

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                get_claim_view(ctx["claim"]["id"])["version"],
                pickup_date="2026-08-14", authorized_return_date="2026-08-16"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_PERIOD_OVERLAP)
        _, meta = validate_paginated(
            api.list_claim_rental_reservations(ctx["claim"]["id"], DESK))
        assert meta["total_count"] == 2, (
            f"The rejected overlapping booking must not persist; "
            f"expected 2 reservations, got {meta['total_count']}"
        )


class TestBookingPrecedence:
    def _setup_suspended_partner_scenario(self):
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        set_clock("2026-08-05T09:00:00Z")
        resp = api_client.suspend_rental_partner(ctx["partner"]["id"], ADMIN)
        validate_success(resp, 200)
        return ctx

    def test_past_pickup_beats_suspended_partner(self, api):
        """PRD §2.7: "Two precedence pairs are pinned explicitly because they are
        easy to get wrong: a state-precondition failure (rung 8) is always
        reported before a fiscal failure (rung 13), and a temporal failure (rung
        10) is always reported before a referential one (rung 11)."
        PRD §3.4: "The `pickup_date` must not be strictly before the logical
        clock's current date (`ERR_PICKUP_DATE_IN_PAST`)"

        Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
        """
        ctx = self._setup_suspended_partner_scenario()
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                get_claim_view(ctx["claim"]["id"])["version"],
                pickup_date="2026-08-04", authorized_return_date="2026-08-10"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_DATE_IN_PAST)

    def test_suspended_partner_reached_when_pickup_valid(self, api):
        """PRD §3.1: "Suspending a partner moves its `status` to `SUSPENDED`,
        which blocks the creation of any new reservation with that partner — the
        booking fails with `ERR_PARTNER_SUSPENDED` — while leaving existing
        reservations entirely unaffected"
        PRD §2.7: "a temporal failure (rung 10) is always reported before a
        referential one (rung 11)"

        Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
        """
        ctx = self._setup_suspended_partner_scenario()
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
                get_claim_view(ctx["claim"]["id"])["version"],
                pickup_date="2026-08-06", authorized_return_date="2026-08-10"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_PARTNER_SUSPENDED)
        _, meta = validate_paginated(
            api.list_claim_rental_reservations(ctx["claim"]["id"], DESK))
        assert meta["total_count"] == 0, (
            "Both rejected bookings must leave the claim reservation list empty"
        )


class TestFleetCapacityPerDay:
    def _setup_two_claim_scenario(self):
        """Claim A with R-A STANDARD 08-05..08-15 AUTHORIZED; claim B with R-B
        (same window) and R-C (adjacent window) in DRAFT. Partner capacity 1."""
        policyholder = register_policyholder()
        shop = register_repair_shop()
        partner = register_rental_partner()  # standard_capacity 1

        claim_a = open_claim(policyholder["id"], incident_date="2026-07-28")
        verify_claim_coverage(claim_a["id"], rental_eligible=True,
                              loss_of_use_eligible=False)
        order_a = create_repair_order(claim_a["id"], shop["id"])
        approve_repair_order(order_a["id"])
        res_a = book_reservation(claim_a["id"], partner["id"], order_a["id"])
        authorize_reservation(res_a["id"])

        claim_b = open_claim(policyholder["id"], incident_date="2026-07-29")
        verify_claim_coverage(claim_b["id"], rental_eligible=True,
                              loss_of_use_eligible=False)
        order_b = create_repair_order(claim_b["id"], shop["id"],
                                      estimated_completion_date="2026-08-19",
                                      labor_hours_estimate=8)
        approve_repair_order(order_b["id"])
        res_b = book_reservation(claim_b["id"], partner["id"], order_b["id"])
        res_c = book_reservation(claim_b["id"], partner["id"], order_b["id"],
                                 pickup_date="2026-08-15",
                                 authorized_return_date="2026-08-20")
        return {"partner": partner, "claim_b": claim_b,
                "res_b": res_b, "res_c": res_c}

    def test_same_class_same_days_exceeds_capacity(self, api):
        """PRD §3.4: "And the partner's fleet must physically support the booking:
        for every calendar day of the authorized window, the number of that
        partner's reservations occupying that day in the same vehicle class and
        currently in `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` must remain
        strictly below the partner's capacity for that class, else
        `ERR_FLEET_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/fleet_capacity_per_day_aggregate
        """
        ctx = self._setup_two_claim_scenario()
        resp = api.authorize_rental_reservation(ctx["res_b"]["id"], DESK)
        validate_error(resp, ApiErrorId.ERR_FLEET_CAPACITY_EXCEEDED)
        assert get_reservation_view(ctx["res_b"]["id"])["status"] == "DRAFT", (
            "The rejected authorization must leave the reservation DRAFT"
        )

    def test_adjacent_window_within_capacity(self, api):
        """PRD §3.4: "for every calendar day of the authorized window, the number
        of that partner's reservations occupying that day in the same vehicle
        class and currently in `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` must
        remain strictly below the partner's capacity for that class, else
        `ERR_FLEET_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/fleet_capacity_per_day_aggregate
        """
        ctx = self._setup_two_claim_scenario()
        resp = api.authorize_rental_reservation(ctx["res_c"]["id"], DESK)
        authorized = validate_success(resp, 200)
        assert authorized["status"] == "AUTHORIZED", (
            "The adjacent window [08-15, 08-20) shares no calendar day with "
            "[08-05, 08-15) and must authorize"
        )
