"""Two-window membership standing and the member-credit ledger.

Standing is derived twice — trailing 365 days versus fiscal year to date — and
the higher answer drives every benefit. Credit is a closed ledger: a refund
into credit and its later redemption must add back to the refunded total.
"""
from test_helpers import (
    lodge_donation,
    enrol_member,
    read_member,
    read_order,
    read_showtime,
    assert_member,
    assert_order_pricing,
    assert_seat_conservation,
    assert_ticket_order,
    sell_seats,
    set_logical_clock,
    setup_member_with_credit,
)


def _member_giving_across_both_windows():
    """Enrol one member with a pre-fiscal gift and a fiscal-year gift."""
    set_logical_clock("2026-08-03T09:00:00Z")
    member = enrol_member(
        full_name="Agnes Varda", email="agnes@example.com", join_date="2026-02-01"
    )
    lodge_donation(member["id"], 20000, "2026-03-01T10:00:00Z")
    lodge_donation(member["id"], 8000, "2026-07-15T10:00:00Z")
    return read_member(member["id"])


class TestRollingVersusFiscalStanding:
    """The trailing-365-day window and the fiscal-YTD window disagree by design."""

    def test_rolling_window_reaches_supporter_while_fiscal_window_reaches_basic(self):
        """Both gifts count rolling, only the July gift counts fiscal.

        PRD: "The two windows genuinely disagree in practice: a single 20000-cent gift made on 1 March 2026 makes `rolling_tier` `SUPPORTER` while `fiscal_tier` is still `PROSPECT`, and an 8000-cent gift on 15 July 2026 makes `fiscal_tier` `BASIC`."

        Design: Difficulty/dual_variant_calc/member_rolling_twelve_month_vs_fiscal_ytd_tier_divergence
        """
        member = _member_giving_across_both_windows()

        assert_member(member)
        assert member["rolling_donation_cents"] == 28000
        assert member["fiscal_ytd_donation_cents"] == 8000
        assert member["rolling_tier"] == "SUPPORTER"
        assert member["fiscal_tier"] == "BASIC"
        assert member["effective_tier"] == "SUPPORTER", (
            "the higher-ranking of the two windows wins"
        )

    def test_benefits_follow_the_higher_of_the_two_windows(self):
        """SUPPORTER benefits apply even though the fiscal window says BASIC.

        PRD: "`advance_access_hours` — the number of hours before a screening's `public_sale_opens_at` at which this member may already buy — is 0 for `PROSPECT`, 24 for `BASIC`, 48 for `SUPPORTER` and a full week, 168 hours, for `DONOR_CIRCLE`."

        Design: Difficulty/dual_variant_calc/member_rolling_twelve_month_vs_fiscal_ytd_tier_divergence
        """
        member = _member_giving_across_both_windows()

        assert member["discount_pct"] == 0.15, "SUPPORTER discount, not the BASIC 0.10"
        assert member["advance_access_hours"] == 48
        assert member["comp_tickets_granted"] == 2
        assert member["comp_tickets_remaining"] == 2

    def test_standing_activates_the_member_and_dates_expiry_from_the_latest_gift(self):
        """The July gift, not the March one, sets the expiry instant.

        PRD: "And `expires_at` is the latest `received_at` among the member's donations advanced by 365 days, or null when the member has never donated."

        Design: Difficulty/dual_variant_calc/member_rolling_twelve_month_vs_fiscal_ytd_tier_divergence
        """
        member = _member_giving_across_both_windows()

        assert member["status"] == "ACTIVE"
        assert member["expires_at"] == "2027-07-15T10:00:00.000Z"
        assert len(member["donations"]) == 2
        assert member["credit_balance_cents"] == 0, "giving is not credit"


class TestMemberCreditLedgerConservation:
    """A refund into credit and its redemption conserve the refunded total."""

    def test_refund_to_member_credit_banks_the_whole_order_total(self):
        """The 4149-cent paid order crosses into credit in full.

        PRD: "When the destination is `MEMBER_CREDIT` the member's `credit_balance_cents` rises by the order's `total_cents`; when it is `CASH` it does not."

        Design: Difficulty/compensating_invariant/member_credit_ledger_conserved_across_refund_then_redemption
        """
        world = setup_member_with_credit()

        refunded = world["refunded_order"]
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_destination"] == "MEMBER_CREDIT"
        assert refunded["total_cents"] == 4149

        member = read_member(world["member"]["id"])
        assert member["credit_balance_cents"] == 4149
        assert member["effective_tier"] == "SUPPORTER"

    def test_redeeming_credit_zeroes_the_new_order_without_going_negative(self):
        """One discounted seat plus the fee is 1383, all of it paid from credit.

        PRD: "Eighth `applied_credit_cents` is, when `apply_credit` is true and a `member_id` is present, the lesser of the member's `credit_balance_cents` and that order-before-credit figure, and 0 otherwise — so credit can zero an order out but `total_cents` never goes negative."

        Design: Difficulty/compensating_invariant/member_credit_ledger_conserved_across_refund_then_redemption
        """
        world = setup_member_with_credit()

        order = sell_seats(
            world["showtime"]["id"],
            1,
            purchaser_email="agnes@example.com",
            member_id=world["member"]["id"],
            apply_credit=True,
        )

        assert_ticket_order(order)
        assert order["status"] == "RESERVED"
        assert_order_pricing(order, 1233, 1233, 150, 0, applied_credit_cents=1383)

    def test_credit_spent_plus_credit_left_equals_the_refunded_total(self):
        """1383 redeemed and 2766 still banked account for all of 4149.

        PRD: "An admitted order is created in `RESERVED` with a null `refund_destination`, and it moves the ledgers immediately: the member's `credit_balance_cents` falls by `applied_credit_cents`, the member's `comp_tickets_remaining` falls by `comp_quantity`, the screening's `seats_sold` rises by `quantity`, `seats_available` is recomputed, and the screening flips `ON_SALE → SOLD_OUT` if that lands on exactly zero."

        Design: Difficulty/compensating_invariant/member_credit_ledger_conserved_across_refund_then_redemption
        """
        world = setup_member_with_credit()

        order = sell_seats(
            world["showtime"]["id"],
            1,
            purchaser_email="agnes@example.com",
            member_id=world["member"]["id"],
            apply_credit=True,
        )

        member = read_member(world["member"]["id"])
        assert member["credit_balance_cents"] == 2766
        assert order["applied_credit_cents"] + member["credit_balance_cents"] == 4149, (
            "the credit ledger neither mints nor destroys cents"
        )
        assert member["effective_tier"] == "SUPPORTER", "redeeming credit is not giving"
        assert member["discount_pct"] == 0.15
        assert read_order(order["id"])["refund_destination"] is None

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 1
        assert showtime["seats_available"] == 7
        assert_seat_conservation(showtime, world["venue"])
