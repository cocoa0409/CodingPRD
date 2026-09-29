"""
Three conserved quantities and the compensating writes that must leave each of
them balanced at every stage: the cents on one reservation's append-only
ledger, the seats of one ticket class, and the face value of one goodwill
credit.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as A
from test_helpers import fixtures as FX
from test_helpers.test_users import make_guest_headers, make_restaurant_headers

# The Saturday evening every scenario below sells, at the 12500 basis-point
# day-of-week factor and the HIGH demand tier.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
SETUP_CLOCK = "2026-09-01T00:00:00Z"
# Exactly 48.0 hours before the seating instant: the 5000 basis-point row of
# the STANDARD ladder.
CANCEL_AT_48H = "2026-09-10T22:00:00Z"
# Two and a half hours before the seating instant: the release window opened
# half an hour earlier, and the 10000 basis-point row of the ladder applies.
RELEASE_AND_CANCEL_AT = "2026-09-12T19:30:00Z"


def _sale_world(api, *, seats_allocated=20, seats_capacity=20, tables=0):
    """A published Saturday HIGH service carrying one ticket class of the given
    allocation, priced at 18000 cents per cover, plus one guest.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=seats_capacity,
        demand_tier="HIGH",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="YIELD_WEIGHTED",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=seats_allocated,
        min_party_size=1,
        max_party_size=6,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(api, display_name="Conserved Guest")
    table_rows = [
        FX.create_table(
            api,
            restaurant["id"],
            seats_min=1,
            seats_max=6,
            turn_buffer_minutes=15,
        )
        for _ in range(tables)
    ]
    return {
        "restaurant_id": restaurant["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "service": service,
        "service_id": service["id"],
        "ticket_class": ticket_class,
        "ticket_class_id": ticket_class["id"],
        "guest": guest,
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
        "tables": table_rows,
    }


class TestReservationCashLedgerConservedThroughForfeitureReversal:
    """A deposit of 11583 cents, split by the ladder into 6292 forfeited and
    5291 refunded, then partly reversed by an approved exception."""

    def test_the_reversal_is_a_new_row_and_never_a_mutation(self, api):
        """The approval appends two rows and leaves the FORFEITURE row alone.

        "Rows are never edited and never deleted; a correction is always a new
        compensating row."

        Design: Difficulty/compensating_invariant/reservation_cash_ledger_conserved_through_forfeiture_reversal
        """
        world = _sale_world(api, tables=1)
        guest_headers = world["guest_headers"]
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        A.assert_money_breakdown(
            reservation, grand_total=38610, deposit_due=11583, amount_paid=11583
        )

        # The table pins the instant the cancellation window closes against.
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation["id"],
            world["tables"][0]["id"],
            SEATING_START,
        )
        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, reservation["id"], world["guest_id"])
        before = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert [row["kind"] for row in before] == [
            "DEPOSIT_CHARGE",
            "FORFEITURE",
            "REFUND",
        ]
        forfeiture_before = [
            row for row in before if row["kind"] == "FORFEITURE"
        ][0]
        assert forfeiture_before["amount_cents"] == 6292

        exception = FX.file_refund_exception(api, reservation["id"], 3000)
        FX.decide_refund_exception(
            api,
            exception["id"],
            decision="APPROVED",
            approved_cents=3000,
            decision_note_code="PARTIAL_GOODWILL",
        )

        after = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert len(after) == 5
        A.assert_created_at_ascending(after)

        # The original forfeiture row is still there, byte for byte.
        forfeiture_after = [row for row in after if row["kind"] == "FORFEITURE"]
        assert len(forfeiture_after) == 1
        assert forfeiture_after[0]["id"] == forfeiture_before["id"]
        assert forfeiture_after[0]["amount_cents"] == 6292
        assert forfeiture_after[0]["signed_amount_cents"] == -6292
        assert forfeiture_after[0]["created_at"] == forfeiture_before["created_at"]

        # The compensation is two brand-new rows of the exception's own memo.
        exception_rows = [
            row for row in after if row["memo_code"] == "REFUND_EXCEPTION"
        ]
        assert sorted(row["kind"] for row in exception_rows) == [
            "FORFEITURE_REVERSAL",
            "REFUND",
        ]
        by_kind = {row["kind"]: row for row in exception_rows}
        assert by_kind["FORFEITURE_REVERSAL"]["amount_cents"] == 3000
        assert by_kind["FORFEITURE_REVERSAL"]["signed_amount_cents"] == 3000
        assert by_kind["REFUND"]["amount_cents"] == 3000
        assert by_kind["REFUND"]["signed_amount_cents"] == -3000
        for row in after:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)

    def test_the_signed_sum_and_settled_identity_hold_at_every_stage(self, api):
        """Payment, settlement and reversal each leave both identities intact.

        "First, the sum of `signed_amount_cents` across a reservation's rows
        equals `amount_paid_cents` minus `refunded_cents` minus
        `forfeited_cents`."

        Design: Difficulty/compensating_invariant/reservation_cash_ledger_conserved_through_forfeiture_reversal
        """
        world = _sale_world(api, tables=1)
        guest_headers = world["guest_headers"]
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )

        # Stage one — the deposit alone.
        paid_rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert len(paid_rows) == 1
        assert sum(row["signed_amount_cents"] for row in paid_rows) == 11583
        A.assert_signed_sum_matches(reservation, paid_rows)
        A.assert_derived_ledger_figures(reservation, paid_rows)

        # Stage two — the ladder splits the deposit in two.
        # The table pins the instant the cancellation window closes against.
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation["id"],
            world["tables"][0]["id"],
            SEATING_START,
        )
        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, reservation["id"], world["guest_id"])
        settled = FX.read_reservation(api, reservation["id"], guest_headers)
        settled_rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert settled["forfeited_cents"] == 6292
        assert settled["refunded_cents"] == 5291
        assert sum(row["signed_amount_cents"] for row in settled_rows) == 0
        A.assert_signed_sum_matches(settled, settled_rows)
        A.assert_settled_ledger_identity(settled)
        A.assert_payment_status(settled, "PARTIALLY_REFUNDED")

        # Stage three — the reversal moves cents between the two buckets
        # without changing what the guest paid.
        exception = FX.file_refund_exception(api, reservation["id"], 3000)
        FX.decide_refund_exception(
            api,
            exception["id"],
            decision="APPROVED",
            approved_cents=3000,
            decision_note_code="PARTIAL_GOODWILL",
        )
        reversed_reservation = FX.read_reservation(
            api, reservation["id"], guest_headers
        )
        reversed_rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert reversed_reservation["amount_paid_cents"] == 11583
        assert reversed_reservation["refunded_cents"] == 8291
        assert reversed_reservation["forfeited_cents"] == 3292
        assert sum(row["signed_amount_cents"] for row in reversed_rows) == 0
        A.assert_signed_sum_matches(reversed_reservation, reversed_rows)
        A.assert_settled_ledger_identity(reversed_reservation)
        A.assert_derived_ledger_figures(reversed_reservation, reversed_rows)

    def test_forfeited_cents_is_the_difference_of_the_two_row_kinds(self, api):
        """The reversal is netted off, not decremented from a stored counter.

        "`forfeited_cents` is the sum of the magnitudes of the `FORFEITURE` rows
        minus the sum of the magnitudes of the `FORFEITURE_REVERSAL` rows."

        Design: Difficulty/compensating_invariant/reservation_cash_ledger_conserved_through_forfeiture_reversal
        """
        world = _sale_world(api, tables=1)
        guest_headers = world["guest_headers"]
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )

        # The table pins the instant the cancellation window closes against.
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation["id"],
            world["tables"][0]["id"],
            SEATING_START,
        )
        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, reservation["id"], world["guest_id"])
        exception = FX.file_refund_exception(api, reservation["id"], 3000)
        decided = FX.decide_refund_exception(
            api,
            exception["id"],
            decision="APPROVED",
            approved_cents=3000,
            decision_note_code="PARTIAL_GOODWILL",
        )
        assert decided["approved_cents"] == 3000
        assert decided["shortfall_cents"] == 0

        final = FX.read_reservation(api, reservation["id"], guest_headers)
        rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        forfeitures = sum(
            row["amount_cents"] for row in rows if row["kind"] == "FORFEITURE"
        )
        reversals = sum(
            row["amount_cents"]
            for row in rows
            if row["kind"] == "FORFEITURE_REVERSAL"
        )
        refunds = sum(
            row["amount_cents"] for row in rows if row["kind"] == "REFUND"
        )
        assert forfeitures == 6292
        assert reversals == 3000
        assert refunds == 8291
        assert final["forfeited_cents"] == forfeitures - reversals == 3292
        assert final["refunded_cents"] == refunds == 8291
        A.assert_payment_status(final, "PARTIALLY_REFUNDED")
        A.assert_derived_ledger_figures(final, rows)
        A.assert_settled_ledger_identity(final)


class TestSeatPoolConservedAcrossReleaseAndCancel:
    """Six physical seats moving between the sold, held, released and available
    pools of one ticket class."""

    def test_the_four_counters_resum_to_the_allocation_at_every_stage(self, api):
        """Hold, confirm, release run and cancellation each re-balance the pool.

        "The invariant is absolute: `seats_allocated` always equals `seats_sold`
        plus `seats_held` plus `seats_released` plus `seats_available`."

        Design: Difficulty/compensating_invariant/seat_pool_conserved_across_release_and_cancel
        """
        world = _sale_world(api, seats_allocated=6, seats_capacity=6, tables=1)
        manager = world["manager"]

        # Stage one — the hold moves two seats out of availability.
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        held = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            held, sold=0, held=2, released=0, available=4, status="OPEN"
        )
        assert held["seats_allocated"] == 6

        # Stage two — confirming moves the same two from held to sold.
        FX.pay_deposit(api, reservation["id"], world["guest_id"])
        FX.confirm(api, reservation["id"], world["guest_id"])
        confirmed = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            confirmed, sold=2, held=0, released=0, available=4, status="OPEN"
        )
        assert confirmed["sell_through_bp"] == 3333

        # Stage three — the release run moves half the availability aside.
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation["id"],
            world["tables"][0]["id"],
            SEATING_START,
        )
        FX.set_clock(api, RELEASE_AND_CANCEL_AT)
        FX.run_release(api, world["restaurant_id"], world["service_id"])
        released = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            released, sold=2, held=0, released=2, available=2, status="RELEASED"
        )

        # Stage four — the cancellation hands the sold seats back.
        FX.cancel(api, reservation["id"], world["guest_id"])
        cancelled = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            cancelled, sold=0, held=0, released=2, available=4, status="RELEASED"
        )
        assert cancelled["seats_allocated"] == 6

    def test_the_cancellation_does_not_unwind_the_released_pool(self, api):
        """Freed seats go back to availability and leave the release standing.

        "`seats_released` is a persisted pool of unsold seats that a release run
        has moved aside for waitlist promotion and that no promotion has yet
        consumed — it is credited only by a release run and debited only when a
        release-priced hold draws from it."

        Design: Difficulty/compensating_invariant/seat_pool_conserved_across_release_and_cancel
        """
        world = _sale_world(api, seats_allocated=6, seats_capacity=6, tables=1)
        manager = world["manager"]
        guest_headers = world["guest_headers"]

        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation["id"],
            world["tables"][0]["id"],
            SEATING_START,
        )
        FX.set_clock(api, RELEASE_AND_CANCEL_AT)
        FX.run_release(api, world["restaurant_id"], world["service_id"])
        FX.cancel(api, reservation["id"], world["guest_id"])

        after = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        # The released pool is untouched by the cancellation.
        assert after["seats_released"] == 2
        assert after["seats_available"] == 4
        assert after["seats_sold"] == 0
        # A positive released pool outranks a positive availability.
        assert after["status"] == "RELEASED"
        A.assert_seat_pool_identity(after)
        A.assert_ladder_status(after)

        # Inside the last day the whole deposit is retained, so the seats came back
        # without any cash coming back with them.
        settled = FX.read_reservation(api, reservation["id"], guest_headers)
        assert settled["forfeited_cents"] == 11583
        assert settled["refunded_cents"] == 0
        A.assert_payment_status(settled, "FORFEITED")
        A.assert_fulfillment_status(settled, "CANCELLED")

    def test_the_release_run_only_moves_seats_between_available_and_released(
        self, api
    ):
        """Two of four available seats are released; sold and held do not move.

        "For each, it computes the number of seats to release as the floor of
        that class's `seats_available` multiplied by the service's
        `unsold_release_bp`, divided by 10000 — a partial seat is never released
        — debits that count from `seats_available`, credits it to
        `seats_released`, adds it to the run's release total, and re-evaluates
        the class against the precedence ladder."

        Design: Difficulty/compensating_invariant/seat_pool_conserved_across_release_and_cancel
        """
        world = _sale_world(api, seats_allocated=6, seats_capacity=6, tables=1)
        manager = world["manager"]

        FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        before = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        assert before["seats_available"] == 4
        assert before["sell_through_bp"] == 3333

        FX.set_clock(api, RELEASE_AND_CANCEL_AT)
        FX.run_release(api, world["restaurant_id"], world["service_id"])

        after = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        assert after["seats_released"] == 2
        assert after["seats_available"] == 2
        # Neither committed pool moved, so the committed share is unchanged.
        assert after["seats_sold"] == before["seats_sold"] == 2
        assert after["seats_held"] == before["seats_held"] == 0
        assert after["sell_through_bp"] == 3333
        A.assert_seat_pool_identity(after)

        service = FX.read_service(api, world["service_id"], manager)
        assert service["release_run_count"] == 1
        assert service["seats_released_total"] == 2
        assert service["last_release_released_count"] == 2
        assert service["last_release_promoted_count"] == 0


# The credit outlives the Saturday it was born from.
CREDIT_EXPIRES = "2027-01-01T00:00:00Z"


def _credit_world(api):
    """One cancelled party of 2 whose 3292-cent shortfall has been turned into a
    goodwill credit, plus a fresh PENDING hold of the same guest on the same
    class to spend part of that credit against.
    """
    world = _sale_world(api, tables=1)
    first = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    FX.assign_table(
        api,
        world["restaurant_id"],
        first["id"],
        world["tables"][0]["id"],
        SEATING_START,
    )
    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, first["id"], world["guest_id"])
    # 6292 cents were retained; 3000 of the 6292 requested are approved, so
    # 3292 cents of the guest's loss go uncompensated in cash.
    exception = FX.approved_exception_with_shortfall(api, first["id"], 6292, 3000)
    credit = FX.issue_goodwill_credit(
        api, exception["id"], 3292, CREDIT_EXPIRES
    )
    second = FX.hold_seats(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    world.update(
        {
            "first": first,
            "exception": exception,
            "credit": credit,
            "credit_id": credit["id"],
            "second": second,
            "second_id": second["id"],
        }
    )
    return world


class TestGoodwillLiabilityConservedThroughPartialRedeemThenRevoke:
    """A 3292-cent face value split between what the guest spent and what the
    restaurant clawed back."""

    def test_the_face_value_resums_at_issue_after_redemption_and_after_revocation(
        self, api
    ):
        """Every stage keeps the four figures summing to the 3292 issued.

        "**Invariant I3** holds at all times: `issued_cents` equals
        `redeemed_cents` plus `revoked_cents` plus `remaining_cents`."

        Design: Difficulty/compensating_invariant/goodwill_liability_conserved_through_partial_redeem_then_revoke
        """
        world = _credit_world(api)
        guest_headers = world["guest_headers"]

        # Stage one — the whole face value is still a live liability.
        issued = FX.read_credit(api, world["credit_id"], guest_headers)
        assert issued["issued_cents"] == 3292
        assert issued["redeemed_cents"] == 0
        assert issued["revoked_cents"] == 0
        assert issued["remaining_cents"] == 3292
        assert issued["status"] == "ISSUED"
        A.assert_credit_status(issued)

        # Stage two — 1000 cents move from remaining to redeemed.
        FX.redeem_goodwill_credit(
            api,
            world["credit_id"],
            world["second_id"],
            1000,
            guest_id=world["guest_id"],
        )
        partly = FX.read_credit(api, world["credit_id"], guest_headers)
        assert partly["issued_cents"] == 3292
        assert partly["redeemed_cents"] == 1000
        assert partly["revoked_cents"] == 0
        assert partly["remaining_cents"] == 2292
        assert partly["status"] == "PARTIALLY_REDEEMED"
        A.assert_credit_status(partly)
        A.assert_version_advanced_by(partly["version"], issued["version"])

        # Stage three — the remainder moves from remaining to revoked.
        FX.revoke_goodwill_credit(api, world["credit_id"])
        revoked = FX.read_credit(api, world["credit_id"], guest_headers)
        assert revoked["issued_cents"] == 3292
        assert revoked["redeemed_cents"] == 1000
        assert revoked["revoked_cents"] == 2292
        assert revoked["remaining_cents"] == 0
        # The revocation test runs before the partial-redemption test.
        assert revoked["status"] == "REVOKED"
        A.assert_credit_status(revoked)

    def test_revocation_claws_back_the_remainder_and_writes_no_ledger_row(self, api):
        """The spent 1000 cents stay on the reservation they were spent against.

        "Revocation sets `revoked_cents` to whatever `remaining_cents` stood at
        and sets `remaining_cents` to 0, so invariant I3 still holds, and moves
        the credit along `ISSUED → REVOKED` or `PARTIALLY_REDEEMED → REVOKED` as
        its prior state dictates." "It writes **no** `PaymentTransaction` row at
        all: cents the guest has already spent stay spent, on the reservations
        they were spent against."

        Design: Difficulty/compensating_invariant/goodwill_liability_conserved_through_partial_redeem_then_revoke
        """
        world = _credit_world(api)
        guest_headers = world["guest_headers"]

        FX.redeem_goodwill_credit(
            api,
            world["credit_id"],
            world["second_id"],
            1000,
            guest_id=world["guest_id"],
        )
        before_rows = FX.ledger_rows(api, world["second_id"], guest_headers)
        assert [row["kind"] for row in before_rows] == ["GOODWILL_REDEMPTION"]
        before_reservation = FX.read_reservation(
            api, world["second_id"], guest_headers
        )
        assert before_reservation["amount_paid_cents"] == 1000

        revoked = FX.revoke_goodwill_credit(api, world["credit_id"])
        assert revoked["revoked_cents"] == 2292
        assert revoked["remaining_cents"] == 0
        assert revoked["redeemed_cents"] == 1000
        A.assert_credit_identity(revoked)

        # No new row, and the one row that exists is the very same row.
        after_rows = FX.ledger_rows(api, world["second_id"], guest_headers)
        assert len(after_rows) == 1
        assert after_rows[0]["id"] == before_rows[0]["id"]
        assert after_rows[0]["amount_cents"] == 1000
        assert after_rows[0]["created_at"] == before_rows[0]["created_at"]
        A.assert_ledger_row_shape(after_rows[0])
        A.assert_signed_amount(after_rows[0])

        after_reservation = FX.read_reservation(api, world["second_id"], guest_headers)
        assert after_reservation["amount_paid_cents"] == 1000
        assert after_reservation["goodwill_applied_cents"] == 1000
        assert after_reservation["version"] == before_reservation["version"]

    def test_redeemed_cents_land_on_the_reservation_exactly_like_cash(self, api):
        """The redemption writes one positive row and moves the balance down.

        "A successful redemption writes a `GOODWILL_REDEMPTION`
        `PaymentTransaction` of `amount_cents` on the target reservation with
        `memo_code` `CREDIT_APPLIED` and `goodwill_credit_id` set, credits
        `redeemed_cents` and debits `remaining_cents`, raises the reservation's
        `amount_paid_cents` — possibly advancing its `payment_status` all the way
        to `FULLY_PAID` — and advances the credit's `version` by one."

        Design: Difficulty/compensating_invariant/goodwill_liability_conserved_through_partial_redeem_then_revoke
        """
        world = _credit_world(api)
        guest_headers = world["guest_headers"]

        # The hold starts owing its whole grand total.
        A.assert_money_breakdown(
            world["second"],
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=0,
        )
        assert world["second"]["balance_due_cents"] == 38610
        A.assert_balance_due(world["second"])

        row = FX.redeem_goodwill_credit(
            api,
            world["credit_id"],
            world["second_id"],
            1000,
            guest_id=world["guest_id"],
        )
        assert row["kind"] == "GOODWILL_REDEMPTION"
        assert row["memo_code"] == "CREDIT_APPLIED"
        assert row["amount_cents"] == 1000
        assert row["signed_amount_cents"] == 1000
        assert row["goodwill_credit_id"] == world["credit_id"]
        assert row["reservation_id"] == world["second_id"]
        A.assert_ledger_row_shape(row)
        A.assert_signed_amount(row)

        reservation = FX.read_reservation(api, world["second_id"], guest_headers)
        assert reservation["amount_paid_cents"] == 1000
        assert reservation["goodwill_applied_cents"] == 1000
        assert reservation["balance_due_cents"] == 37610
        A.assert_balance_due(reservation)
        # 1000 cents is short of the 11583-cent deposit, so the money dimension
        # has not advanced.
        A.assert_payment_status(reservation, "UNPAID")
        A.assert_signed_sum_matches(
            reservation, FX.ledger_rows(api, world["second_id"], guest_headers)
        )
