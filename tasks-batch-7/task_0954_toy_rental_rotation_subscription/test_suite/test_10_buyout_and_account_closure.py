"""Buy-out pricing (multi-factor price, pinned wallet-application order) and
support-driven member account closure gated on open boxes."""

from test_helpers import (
    SUPPORT,
    ApiErrorId,
    cancel_subscription,
    create_next_box,
    list_ledger,
    make_member_headers,
    read_box_item,
    read_copy,
    read_member,
    setup_buyout_context,
    setup_member_with_subscription,
    validate_error,
    validate_success,
)


class TestBuyoutPrice:
    def test_buyout_price_combines_discount_depreciation_and_credit(self, api):
        """PRD §3.7: "Start with the gross: the catalog item's
        `retail_value_cents` reduced by the plan's `buyout_discount_pct`
        fraction. Apply condition depreciation by multiplying the gross by the
        copy's `condition_grade` at buy-out time — 100% for `NEW`, 85% for
        `GOOD`, 70% for `FAIR`, 55% for `WORN` — rounding the product half up
        to whole cents. Compute the rental credit: the whole calendar months
        between the box's `delivered_at` date and the logical clock date each
        earn 4% of `retail_value_cents`, the running credit is capped at 30% of
        `retail_value_cents`, and the capped figure is rounded half up. The
        price is the depreciated gross minus the rental credit, but never below
        the 499-cent floor."
        PRD §2.7: "Buy-out pricing rounds the discounted-and-depreciated gross
        figure and the rental credit separately, both half up, before
        subtracting the credit from the gross."

        Retail 12000, discount 0.10 -> gross 10800; FAIR copy at buy-out ->
        round_half_up(10800 x 0.70) = 7560; delivered 2026-06-03, clock
        2026-08-05 -> 2 whole months -> credit round_half_up(min(2 x 0.04 x
        12000, 0.30 x 12000)) = 960; price 7560 - 960 = 6600 (floor 499 not
        binding); wallet 0 applies nothing.

        Design: Difficulty/combinatorial_formula/buyout_price_multi_factor_mode_a
        """
        ctx = setup_buyout_context(member_email="m.buy@x.com")
        member, item2 = ctx["member"], ctx["item"]
        assert read_copy(ctx["copy"]["id"])["condition_grade"] == "FAIR"

        bought = validate_success(api.buyout_box_item(
            item2["id"], make_member_headers(member["id"])))
        assert bought["buyout_price_cents"] == 6600
        assert bought["wallet_applied_cents"] == 0
        assert bought["net_charge_cents"] == 6600

    def test_buyout_terminal_effects_on_item_and_copy(self, api):
        """PRD §3.7: "The item moves to `KEPT_BUYOUT` with `resolution_status`
        `RESOLVED`, and the copy moves `OUT_ON_LOAN` → `SOLD`."
        PRD §3.7: "All three figures are recorded on the item as
        `buyout_price_cents`, `wallet_applied_cents`, and `net_charge_cents`."

        Design: Difficulty/combinatorial_formula/buyout_price_multi_factor_mode_a
        """
        ctx = setup_buyout_context(member_email="m.buy@x.com")
        member, item2 = ctx["member"], ctx["item"]

        bought = validate_success(api.buyout_box_item(
            item2["id"], make_member_headers(member["id"])))
        assert bought["loan_status"] == "KEPT_BUYOUT"
        assert bought["resolution_status"] == "RESOLVED"
        assert bought["buyout_price_cents"] == 6600

        copy_now = read_copy(ctx["copy"]["id"])
        assert copy_now["status"] == "SOLD"

        item_now = read_box_item(item2["id"], member)
        assert item_now["loan_status"] == "KEPT_BUYOUT"
        assert item_now["net_charge_cents"] == 6600


class TestBuyoutWalletApplication:
    def test_wallet_application_clamps_to_min_net_charge(self, api):
        """PRD §3.7: "Wallet application follows a pinned evaluation order —
        the dependency only looks circular. The member's `wallet_credit_cents`
        is read once, at the start of the transaction. The wallet-funded
        portion `wallet_applied_cents` is the smaller of that balance (floored
        at zero, so a negative wallet applies nothing) and the price minus 100
        cents — at least 100 cents always goes to the card. The remainder
        `net_charge_cents`, the price minus the wallet portion, is charged to
        the member's card."

        With wallet 8000 and price 6600 the 100-cent card minimum binds:
        applied = min(8000, 6600 - 100) = 6500, net = 100.

        Design: Difficulty/combinatorial_formula/buyout_wallet_application_order_mode_c
        """
        ctx = setup_buyout_context(member_email="m.wal@x.com", wallet_seed=8000)
        member, item2 = ctx["member"], ctx["item"]
        assert read_member(member["id"])["wallet_credit_cents"] == 8000

        bought = validate_success(api.buyout_box_item(
            item2["id"], make_member_headers(member["id"])))
        assert bought["buyout_price_cents"] == 6600
        assert bought["wallet_applied_cents"] == 6500
        assert bought["net_charge_cents"] == 100

    def test_wallet_application_appends_ledger_entry_and_recomputes(self, api):
        """PRD §3.7: "When the wallet portion is positive, a
        `BUYOUT_CREDIT_APPLIED` ledger entry for its negative amount is
        appended and the wallet recompute runs, suspension check included."
        PRD §2.9: "The invariant is absolute: a member's `wallet_credit_cents`
        always equals the sum of `amount_cents` across all of that member's
        ledger entries."

        Wallet 8000 - 6500 via one BUYOUT_CREDIT_APPLIED entry of -6500 leaves
        1500.

        Design: Difficulty/combinatorial_formula/buyout_wallet_application_order_mode_c
        """
        ctx = setup_buyout_context(member_email="m.wal@x.com", wallet_seed=8000)
        member, item2 = ctx["member"], ctx["item"]

        validate_success(api.buyout_box_item(
            item2["id"], make_member_headers(member["id"])))

        assert read_member(member["id"])["wallet_credit_cents"] == 1500
        entries = list_ledger(member["id"])
        buyout_entries = [e for e in entries if e["reason"] == "BUYOUT_CREDIT_APPLIED"]
        assert len(buyout_entries) == 1
        assert buyout_entries[0]["amount_cents"] == -6500
        assert sum(e["amount_cents"] for e in entries) == 1500


class TestMemberAccountClosure:
    def test_member_close_blocked_by_open_box_then_succeeds(self, api):
        """PRD §3.9: "Closing a member is allowed from `ACTIVE` or `SUSPENDED`
        and is gated on a clean account: no rotation box of any of the member's
        subscriptions may sit in `PLANNED`, `SHIPPED`, `DELIVERED`,
        `RETURNING`, `RECEIVED`, or `INSPECTED` (`ERR_MEMBER_HAS_OPEN_BOX`,
        HTTP 409), and no fee of the member may remain `INVOICED` or
        `DISPUTED` (`ERR_FEES_OUTSTANDING`)."
        PRD §3.3: "every `PLANNED` box is cancelled with the same copy-release
        cascade"

        Design: Corner/endpoints/member_close_blocked_by_open_box
        """
        ctx = setup_member_with_subscription(member_email="m.mcl@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        create_next_box(member, sub["id"])  # PLANNED box blocks closure

        resp = api.close_member(member["id"], SUPPORT)
        validate_error(resp, ApiErrorId.ERR_MEMBER_HAS_OPEN_BOX.value, 409)
        assert read_member(member["id"])["status"] == "ACTIVE"

        # Cancelling the subscription cascades the PLANNED box to CANCELLED.
        cancel_subscription(sub["id"], member)

        closed = validate_success(api.close_member(member["id"], SUPPORT))
        assert closed["status"] == "CLOSED"
