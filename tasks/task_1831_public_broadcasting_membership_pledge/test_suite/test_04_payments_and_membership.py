"""Payment posting, OCC on pledges, and the membership lapse/reinstate cycle."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_membership,
    assert_pledge,
    capture_pledge,
    create_payment_payload,
    create_premium,
    get_pledge,
    parse_utc,
    post_payment_ok,
    receive_lot,
    reserve_premium_ok,
    setup_lapsed_membership,
    setup_station,
    validate_error,
    validate_success,
)


class TestParallelPaymentFulfillmentDimensions:
    def test_pledge_parallel_payment_fulfillment_dimensions(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "when a premium was selected, not waived, and stock is
        available, an automatic `PremiumReservation` is created in `HELD`
        status and the pledge's `fulfillment_status` becomes `RESERVED`;
        otherwise it becomes `AWAITING_RESERVATION`."
        PRD §3.8: "The pledge's `payment_status` moves from `PLEDGED` (or
        `PARTIAL`) toward `PAID` or `PARTIAL` based on whether the payment
        covers the remaining balance (for `ONE_TIME`) or the first installment
        (for `SUSTAINER`)."

        Design: Difficulty/non_linear_state_machine/pledge_parallel_payment_fulfillment_dimensions
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 25})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        assert pledge["payment_status"] == "PLEDGED"
        assert pledge["fulfillment_status"] == "RESERVED", (
            "stock was available, so capture auto-reserved the premium")

        # A partial payment moves only the payment dimension.
        updated = post_payment_ok(pledge, 5000)
        assert updated["payment_status"] == "PARTIAL"
        assert updated["fulfillment_status"] == "RESERVED", (
            "fulfillment is an independent dimension and stays RESERVED")

        reread = get_pledge(pledge["id"])
        assert reread["payment_status"] == "PARTIAL"
        assert reread["fulfillment_status"] == "RESERVED"

    def test_pledge_paid_while_awaiting_reservation(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.5: "Inventory availability is deliberately **not** checked at
        capture. A capture that selects a premium with no stock simply lands in
        `fulfillment_status` `AWAITING_RESERVATION`; availability is enforced
        only on the explicit reservation endpoint (§3.6)."
        PRD §3.6: "The reservation is created in `HELD` status, the lot's
        `reserved_qty` increments by `quantity`, `available_qty` decrements by
        `quantity`, the pledge's `fulfillment_status` moves to `RESERVED`, and
        the pledge's `net_collected_cents` is recomputed (premium FMV is now
        deductible)."

        Design: Difficulty/non_linear_state_machine/pledge_parallel_payment_fulfillment_dimensions
        """
        station = setup_station()
        premium = create_premium(membership_level_code=station["level"]["code"])
        # No lot received yet — the premium has no stock.
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="ONE_TIME",
            amount_cents=12000, premium_id=premium["id"])
        assert pledge["fulfillment_status"] == "AWAITING_RESERVATION"

        # Paying in full moves payment to PAID while fulfillment stays put.
        paid = post_payment_ok(pledge, 12000)
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "AWAITING_RESERVATION", (
            "the payment dimension does not touch fulfillment")

        # Once stock arrives, the explicit reservation flips fulfillment.
        receive_lot(premium["id"], total_qty=3)
        reservation = reserve_premium_ok(pledge["id"], quantity=1)
        assert reservation["status"] == "HELD"
        reread = get_pledge(pledge["id"])
        assert reread["fulfillment_status"] == "RESERVED"
        assert reread["payment_status"] == "PAID"


class TestSustainerMembershipDependency:
    def test_sustainer_payment_depends_on_membership_status_lapsed_rejected(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.8: "A `SUSTAINER` pledge additionally requires its linked
        membership to be in `ACTIVE` or `GRACE` status."
        PRD §2.9: "Target resource state permits the operation (generic) →
        `ERR_INVALID_STATE` (409)."
        PRD §3.4: "When the clock then reaches `current_period_end` plus 30
        days, the membership moves `GRACE` → `LAPSED` and the donor's
        `lapse_count` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/sustainer_payment_depends_on_membership_status
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="SUSTAINER",
            amount_cents=500)

        # The membership was never paid: its zero-length paid-through window
        # ended at creation, so this clock jump lands it in LAPSED.
        advance_clock("2027-10-15T00:00:00Z")
        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert membership["status"] == "LAPSED"

        resp = api.post_payment(
            pledge["id"], create_payment_payload(500, pledge["version"]),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = get_pledge(pledge["id"])
        assert reread["payment_status"] == "PLEDGED", (
            "the rejected installment does not move the pledge")

    def test_sustainer_payment_depends_on_membership_status_active_accepted(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.8: "A `SUSTAINER` pledge additionally requires its linked
        membership to be in `ACTIVE` or `GRACE` status."
        PRD §3.8: "The pledge's `payment_status` moves from `PLEDGED` (or
        `PARTIAL`) toward `PAID` or `PARTIAL` based on whether the payment
        covers the remaining balance (for `ONE_TIME`) or the first installment
        (for `SUSTAINER`)."
        PRD §3.4: "a `SUSTAINER` installment extends it by exactly 1 month from
        the same baseline."

        Design: Difficulty/cross_entity_state_dependency/sustainer_payment_depends_on_membership_status
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="SUSTAINER",
            amount_cents=500)

        updated = post_payment_ok(pledge, 500)
        assert updated["payment_status"] == "PAID", (
            "the first SUSTAINER installment completes the pledge")
        assert updated["collected_cents"] == 500

        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        # Membership created at the 2026-08-01 startup clock with a zero-length
        # window; the installment extends one month from that baseline.
        assert parse_utc(membership["current_period_end"]) == datetime(
            2026, 9, 1, tzinfo=timezone.utc)
        assert membership["sustainer"] is True


class TestMembershipLapseReinstateCycle:
    def test_membership_lapse_reinstate_cycle(
            self, api, coordinator_headers):
        """PRD §3.4: "When the clock then reaches `current_period_end` plus 30
        days, the membership moves `GRACE` → `LAPSED` and the donor's
        `lapse_count` increments by 1."
        PRD §3.4: "A `MembershipCoordinator` moves it `LAPSED` →
        `REINSTATED_PENDING`, which is the win-back pending state awaiting a
        payment."

        Design: Difficulty/non_linear_state_machine/membership_lapse_reinstate_cycle
        """
        station = setup_lapsed_membership(payment_amount=6000)
        membership = station["membership"]
        assert membership["status"] == "LAPSED", (
            "clock 2027-10-15 is past period end 2027-08-01 plus 30-day grace")
        assert station["donor"]["lapse_count"] == 1, (
            "the LAPSED transition incremented the donor's lapse_count")

        resp = api.reinstate_membership(membership["id"], coordinator_headers)
        reinstated = validate_success(resp, 200)
        assert_membership(reinstated)
        assert reinstated["status"] == "REINSTATED_PENDING"

    def test_membership_grace_window_before_lapse(
            self, api, coordinator_headers):
        """PRD §3.4: "When the clock crosses a membership's
        `current_period_end`, the membership moves `ACTIVE` → `GRACE`, opening
        a 30-day grace window. When the clock then reaches
        `current_period_end` plus 30 days, the membership moves `GRACE` →
        `LAPSED` and the donor's `lapse_count` increments by 1."

        Design: Difficulty/non_linear_state_machine/membership_lapse_reinstate_cycle
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        post_payment_ok(pledge, 6000)
        # Paid on 2026-08-01: current_period_end becomes 2027-08-01.
        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert parse_utc(membership["current_period_end"]) == datetime(
            2027, 8, 1, tzinfo=timezone.utc)

        # Past the period end but inside the 30-day grace window.
        advance_clock("2027-08-15T00:00:00Z")
        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert membership["status"] == "GRACE"
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lapse_count"] == 0, (
            "lapse_count only increments on the GRACE → LAPSED transition")

        # Past period end + 30 days (2027-08-31): LAPSED.
        advance_clock("2027-09-15T00:00:00Z")
        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert membership["status"] == "LAPSED"
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lapse_count"] == 1


class TestReinstatementPaymentCascade:
    def test_lapsed_payment_reactivates_membership_resets_donor(
            self, api, coordinator_headers, phone_volunteer_headers):
        """PRD §3.4: "When a payment then completes on the reinstatement pledge
        — meaning the linked pledge's `payment_status` becomes `PAID` — the
        membership moves `REINSTATED_PENDING` → `ACTIVE`, `current_period_start`
        is set to the current logical time, `current_period_end` is set to 12
        months after that, and the donor's `lapse_count` resets to 0."

        Design: Difficulty/transitive_cascade/lapsed_payment_reactivates_membership_resets_donor
        """
        station = setup_lapsed_membership(payment_amount=6000)
        validate_success(
            api.reinstate_membership(station["membership"]["id"],
                                     coordinator_headers), 200)

        reinstatement_pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        paid = post_payment_ok(reinstatement_pledge, 6000)
        assert paid["payment_status"] == "PAID"

        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert membership["status"] == "ACTIVE", (
            "the completed reinstatement payment reactivates the membership")
        assert parse_utc(membership["current_period_start"]) == datetime(
            2027, 10, 15, tzinfo=timezone.utc)
        assert parse_utc(membership["current_period_end"]) == datetime(
            2028, 10, 15, tzinfo=timezone.utc), (
            "period end is set 12 months after the 2027-10-15 payment time")

        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lapse_count"] == 0, (
            "the membership transition resets the donor's lapse_count")

    def test_reinstated_pending_before_payment_keeps_lapse_count(
            self, api, coordinator_headers):
        """PRD §3.4: "A `MembershipCoordinator` moves it `LAPSED` →
        `REINSTATED_PENDING`, which is the win-back pending state awaiting a
        payment."
        PRD §3.4: "When a payment then completes on the reinstatement pledge —
        meaning the linked pledge's `payment_status` becomes `PAID` — the
        membership moves `REINSTATED_PENDING` → `ACTIVE`, `current_period_start`
        is set to the current logical time, `current_period_end` is set to 12
        months after that, and the donor's `lapse_count` resets to 0."

        Design: Difficulty/transitive_cascade/lapsed_payment_reactivates_membership_resets_donor
        """
        station = setup_lapsed_membership(payment_amount=6000)
        reinstated = validate_success(
            api.reinstate_membership(station["membership"]["id"],
                                     coordinator_headers), 200)
        assert reinstated["status"] == "REINSTATED_PENDING"

        # The reset is tied to payment completion, not to the reinstate call.
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lapse_count"] == 1, (
            "lapse_count is still 1 while the win-back awaits payment")


class TestPaymentValidationAndOcc:
    def test_payment_exceeding_remaining_balance_rejected(
            self, api, phone_volunteer_headers):
        """PRD §3.8: "For a `ONE_TIME` pledge the payment must not exceed the
        remaining balance; an over-payment is rejected with
        `ERR_PAYMENT_AMOUNT` (422)."

        Design: Corner/validations/payment_exceeding_remaining_balance_rejected
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)

        resp = api.post_payment(
            pledge["id"],
            create_payment_payload(6001, pledge["version"]),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT)

        reread = get_pledge(pledge["id"])
        assert reread["payment_status"] == "PLEDGED"
        assert reread["collected_cents"] == 0, (
            "the rejected over-payment is not applied")

    def test_occ_stale_pledge_version_on_payment(
            self, api, phone_volunteer_headers):
        """PRD §2.7: "Payment posting against a pledge requires
        `expected_pledge_version` carrying the client's last observed `version`
        of the target `Pledge`. A mismatch is rejected with
        `ERR_STALE_PLEDGE_VERSION` (HTTP 412)."
        PRD §3.8: "A successful payment also increments the pledge's `version`
        by 1."

        Design: Corner/cross_cutting_layers/occ_stale_pledge_version_on_payment
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000)
        stale_version = pledge["version"]

        first = post_payment_ok(pledge, 5000)
        assert first["version"] == stale_version + 1

        resp = api.post_payment(
            pledge["id"],
            create_payment_payload(7000, stale_version),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_PLEDGE_VERSION)

        reread = get_pledge(pledge["id"])
        assert reread["collected_cents"] == 5000, (
            "the stale second payment is rejected, not applied")

    def test_payment_effects_visible_in_same_response(
            self, api, phone_volunteer_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.8: "The pledge's `collected_cents` increments by the payment
        amount, `net_collected_cents` is recomputed per the rule below, and the
        drive's `collected_cents` increments by the resulting net delta."

        Design: Corner/consistency_model/payment_effects_visible_in_same_response
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)

        resp = api.post_payment(
            pledge["id"],
            create_payment_payload(6000, pledge["version"]),
            phone_volunteer_headers)
        assert 200 <= resp.status_code < 300, (
            f"payment posting failed: {resp.status_code} {resp.text}")
        updated = resp.json()["data"]
        assert_pledge(updated)
        assert updated["payment_status"] == "PAID", (
            "the payment response itself carries the new payment_status")
        assert updated["collected_cents"] == 6000
        assert updated["net_collected_cents"] == 6000, (
            "no premium selected, so net equals gross collected")
        assert updated["version"] == pledge["version"] + 1
