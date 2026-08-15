"""Premium reservation, shipping, waiver, release, and lot counter reconciliation."""
from test_helpers import (
    ApiErrorId,
    assert_lot_quantity_conserved,
    capture_pledge,
    create_premium,
    create_reservation_payload,
    get_lot_of_premium,
    get_pledge,
    get_pledge_reservation,
    pay_in_full,
    receive_lot,
    setup_station,
    validate_error,
    validate_success,
)


class TestReservationInventoryBoundary:
    def test_reservation_rejected_at_exact_zero_available(
            self, api, coordinator_headers):
        """PRD §3.6: "When `lot_id` is omitted the server selects the lot
        deterministically: eligible lots are those of the pledge's
        `premium_id` with `available_qty` at least `quantity`; ranking is by
        `received_at` ascending, tie-break by `created_at` ascending; an empty
        candidate set is rejected with `ERR_INSUFFICIENT_INVENTORY` (422). An
        exact-zero `available_qty` rejects."
        PRD §3.5: "Inventory availability is deliberately **not** checked at
        capture. A capture that selects a premium with no stock simply lands in
        `fulfillment_status` `AWAITING_RESERVATION`; availability is enforced
        only on the explicit reservation endpoint (§3.6)."

        Design: Difficulty/boundary_precision_check/reservation_rejected_at_exact_zero_available
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 1})
        # The single unit auto-reserves against the first pledge.
        first = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        assert first["fulfillment_status"] == "RESERVED"
        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["available_qty"] == 0

        # Stock exhausted at capture: the second pledge awaits reservation.
        second = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        assert second["fulfillment_status"] == "AWAITING_RESERVATION"

        resp = api.create_premium_reservation(
            second["id"], create_reservation_payload(quantity=1),
            coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
        assert get_pledge(second["id"])["fulfillment_status"] == (
            "AWAITING_RESERVATION")

    def test_reservation_accepted_when_available_equals_quantity(
            self, api, coordinator_headers):
        """PRD §3.6: "When `lot_id` is omitted the server selects the lot
        deterministically: eligible lots are those of the pledge's
        `premium_id` with `available_qty` at least `quantity`; ranking is by
        `received_at` ascending, tie-break by `created_at` ascending; an empty
        candidate set is rejected with `ERR_INSUFFICIENT_INVENTORY` (422)."
        PRD §3.6: "The reservation is created in `HELD` status, the lot's
        `reserved_qty` increments by `quantity`, `available_qty` decrements by
        `quantity`, the pledge's `fulfillment_status` moves to `RESERVED`, and
        the pledge's `net_collected_cents` is recomputed (premium FMV is now
        deductible)."

        Design: Difficulty/boundary_precision_check/reservation_rejected_at_exact_zero_available
        """
        station = setup_station()
        premium = create_premium(
            membership_level_code=station["level"]["code"])
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=premium["id"])
        assert pledge["fulfillment_status"] == "AWAITING_RESERVATION", (
            "no lot exists yet, so nothing can auto-reserve")

        receive_lot(premium["id"], total_qty=1)
        resp = api.create_premium_reservation(
            pledge["id"], create_reservation_payload(quantity=1),
            coordinator_headers)
        reservation = validate_success(resp, 201)
        assert reservation["status"] == "HELD", (
            "available_qty exactly equal to quantity satisfies 'at least'")

        assert get_pledge(pledge["id"])["fulfillment_status"] == "RESERVED"
        lot = get_lot_of_premium(premium["id"])
        assert lot["available_qty"] == 0
        assert lot["reserved_qty"] == 1
        assert_lot_quantity_conserved(lot)


class TestReservationReleaseConservation:
    def test_reservation_release_conserves_lot_quantity_identity(
            self, api, coordinator_headers):
        """PRD §3.1: "The `available_qty` is server-maintained thereafter as
        `total_qty` minus `reserved_qty` minus `committed_qty` minus
        `written_off_qty` and never goes negative."
        PRD §3.6: "A `MembershipCoordinator` can also release a `HELD`
        reservation directly — for example when the donor changed their mind
        before shipment — which moves the reservation `HELD` → `RELEASED`,
        compensates the lot counters, and drops the parent pledge's
        `fulfillment_status` back to `AWAITING_RESERVATION`."

        Design: Difficulty/compensating_invariant/reservation_release_conserves_lot_quantity_identity
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 5})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        reservation = get_pledge_reservation(pledge["id"])
        assert reservation["status"] == "HELD"

        resp = api.release_reservation(reservation["id"], coordinator_headers)
        released = validate_success(resp, 200)
        assert released["status"] == "RELEASED"

        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["available_qty"] == 5
        assert lot["reserved_qty"] == 0
        assert lot["committed_qty"] == 0
        assert lot["written_off_qty"] == 0
        assert_lot_quantity_conserved(lot)

        assert get_pledge(pledge["id"])["fulfillment_status"] == (
            "AWAITING_RESERVATION")

    def test_reserve_release_reserve_cycle_keeps_identity(
            self, api, coordinator_headers):
        """PRD §3.1: "The `available_qty` is server-maintained thereafter as
        `total_qty` minus `reserved_qty` minus `committed_qty` minus
        `written_off_qty` and never goes negative."
        PRD §3.6: "The reservation is created in `HELD` status, the lot's
        `reserved_qty` increments by `quantity`, `available_qty` decrements by
        `quantity`, the pledge's `fulfillment_status` moves to `RESERVED`, and
        the pledge's `net_collected_cents` is recomputed (premium FMV is now
        deductible)."

        Design: Difficulty/compensating_invariant/reservation_release_conserves_lot_quantity_identity
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 5})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])

        lot = get_lot_of_premium(station["premium"]["id"])
        assert (lot["available_qty"], lot["reserved_qty"]) == (4, 1)
        assert_lot_quantity_conserved(lot)

        reservation = get_pledge_reservation(pledge["id"])
        validate_success(
            api.release_reservation(reservation["id"], coordinator_headers),
            200)
        lot = get_lot_of_premium(station["premium"]["id"])
        assert (lot["available_qty"], lot["reserved_qty"]) == (5, 0)
        assert_lot_quantity_conserved(lot)

        # A fresh explicit reservation re-holds the unit.
        re_reservation = validate_success(
            api.create_premium_reservation(
                pledge["id"], create_reservation_payload(quantity=1),
                coordinator_headers), 201)
        assert re_reservation["status"] == "HELD"
        lot = get_lot_of_premium(station["premium"]["id"])
        assert (lot["available_qty"], lot["reserved_qty"]) == (4, 1)
        assert_lot_quantity_conserved(lot)
        assert get_pledge(pledge["id"])["fulfillment_status"] == "RESERVED"


class TestShipPremium:
    def test_ship_premium_from_reserved_succeeds_and_updates_lot(
            self, api, coordinator_headers):
        """PRD §3.6: "Once a pledge is fully paid (`payment_status` is `PAID`),
        the premium ships. Shipping moves the pledge's `fulfillment_status`
        `RESERVED` → `SHIPPED` and the reservation `HELD` → `COMMITTED`,
        transferring the quantity from the lot's `reserved_qty` to its
        `committed_qty` (the lot's `available_qty` is unchanged)."

        Design: Corner/state_machines/ship_premium_from_reserved_succeeds_and_updates_lot
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 3})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        pay_in_full(pledge)

        resp = api.ship_premium(pledge["id"], coordinator_headers)
        shipped = validate_success(resp, 200)
        assert shipped["fulfillment_status"] == "SHIPPED"

        reservation = get_pledge_reservation(pledge["id"])
        assert reservation["status"] == "COMMITTED"
        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["available_qty"] == 2, "available is unchanged by shipping"
        assert lot["reserved_qty"] == 0
        assert lot["committed_qty"] == 1
        assert_lot_quantity_conserved(lot)

    def test_ship_premium_before_payment_rejected_cross_dimension_guard(
            self, api, coordinator_headers):
        """PRD §3.6: "Shipping before full payment is rejected with
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/ship_premium_before_payment_rejected_cross_dimension_guard
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 5})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        assert pledge["fulfillment_status"] == "RESERVED"
        assert pledge["payment_status"] == "PLEDGED"

        resp = api.ship_premium(pledge["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_pledge(pledge["id"])["fulfillment_status"] == "RESERVED"

    def test_error_premium_not_selected_on_ship(
            self, api, coordinator_headers):
        """PRD §3.6: "Reservation, ship, and waive operations on a pledge with
        no premium selected — one whose `fulfillment_status` is `NO_PREMIUM` or
        already `WAIVED` — are rejected with `ERR_PREMIUM_NOT_SELECTED` (422)."

        Design: Corner/errors/error_premium_not_selected_on_ship
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        pay_in_full(pledge)

        resp = api.ship_premium(pledge["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_SELECTED)


class TestWaiverAndNetCollected:
    def test_waive_premium_after_capture_recomputes_net(
            self, api, coordinator_headers):
        """PRD §3.6: "A donor who calls back to decline the gift triggers a
        waiver: `AWAITING_RESERVATION` or `RESERVED` → `WAIVED`. If the pledge
        was in `RESERVED`, the reservation transitions to `RELEASED`, the lot's
        `reserved_qty` decrements, and `available_qty` increments by the same
        amount. The pledge's `net_collected_cents` is recomputed with the
        premium FMV no longer deducted, and the drive and donor totals resync
        by the net delta."

        Design: Corner/endpoints/waive_premium_after_capture_recomputes_net
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 5})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        paid = pay_in_full(pledge)
        assert paid["net_collected_cents"] == 9500, (
            "12000 gross minus 2500 FMV while RESERVED")

        resp = api.waive_premium(pledge["id"], coordinator_headers)
        waived = validate_success(resp, 200)
        assert waived["fulfillment_status"] == "WAIVED"
        assert waived["net_collected_cents"] == 12000, (
            "the FMV deduction is removed on waiver")

        reservation = get_pledge_reservation(pledge["id"])
        assert reservation["status"] == "RELEASED"
        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["available_qty"] == 5
        assert lot["reserved_qty"] == 0
        assert_lot_quantity_conserved(lot)

    def test_premium_fmv_constant_applied_in_net_collected(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.8: "The FMV deduction is 0 unless three things are all true:
        the pledge has a `premium_id`, the pledge's `fulfillment_status` is
        `RESERVED` or `SHIPPED`, and `premium_waived` is false. When all three
        hold, the deduction is the premium's `fair_market_value_cents`
        multiplied by the reserved quantity (the quantity on the active
        reservation, whether `HELD` or `COMMITTED`). The result is the pledge's
        `collected_cents` minus the deduction, floored at 0."

        Design: Corner/calculations/premium_fmv_constant_applied_in_net_collected
        """
        station = setup_station(with_premium=True,
                                premium_overrides={
                                    "fair_market_value_cents": 2500},
                                lot_overrides={"total_qty": 5})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])

        resp = api.post_payment(
            pledge["id"],
            {"amount_cents": 12000,
             "expected_pledge_version": pledge["version"]},
            phone_volunteer_headers)
        assert 200 <= resp.status_code < 300
        paid = resp.json()["data"]
        assert paid["collected_cents"] == 12000
        assert paid["net_collected_cents"] == 9500, (
            "the premium's declared fair_market_value_cents is the deduction")

        reread = get_pledge(pledge["id"])
        assert reread["net_collected_cents"] == 9500

    def test_donor_computed_lifetime_given_accumulates_paid_net(
            self, api, coordinator_headers):
        """PRD §3.2: "The server maintains `lifetime_given_cents` (sum of
        `net_collected_cents` over the donor's pledges whose `payment_status`
        is `PAID` or `PARTIAL`) and `lapse_count` (the number of times any of
        the donor's memberships has entered `LAPSED`)."

        Design: Corner/entities/donor_computed_lifetime_given_accumulates_paid_net
        """
        station = setup_station(with_premium=True,
                                premium_overrides={
                                    "fair_market_value_cents": 2500},
                                lot_overrides={"total_qty": 10})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        pay_in_full(pledge)

        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lifetime_given_cents"] == 9500, (
            "12000 gross collected minus the 2500 premium FMV")
        assert donor["lapse_count"] == 0


class TestDerivedLotCounters:
    def test_derived_field_lot_counters_reconciled_on_reserve(
            self, api, coordinator_headers):
        """PRD §3.1: "The lot is initialized with `available_qty` equal to
        `total_qty`, and `reserved_qty`, `committed_qty`, and `written_off_qty`
        all at 0. The `available_qty` is server-maintained thereafter as
        `total_qty` minus `reserved_qty` minus `committed_qty` minus
        `written_off_qty` and never goes negative."
        PRD §3.5: "when a premium was selected, not waived, and stock is
        available, an automatic `PremiumReservation` is created in `HELD`
        status and the pledge's `fulfillment_status` becomes `RESERVED`"

        Design: Corner/cross_cutting_layers/derived_field_lot_counters_reconciled_on_reserve
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 4})
        capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])

        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["total_qty"] == 4
        assert lot["available_qty"] == 3
        assert lot["reserved_qty"] == 1
        assert lot["committed_qty"] == 0
        assert lot["written_off_qty"] == 0
        assert_lot_quantity_conserved(lot)
