"""Fee settlement and the dispute loop, the state-before-fiscal error
ordering, wallet-sufficiency, the wallet conservation invariant under
charge+waive, immediate ledger visibility, and the box-closure fee gate."""

from test_helpers import (
    OPS,
    SUPPORT,
    ApiErrorId,
    adjust_wallet,
    assert_same_instant,
    assert_wallet_matches_ledger,
    create_dispute_payload,
    create_pay_fee_payload,
    create_resolve_dispute_payload,
    create_waive_payload,
    create_wallet_adjustment_payload,
    list_box_fees,
    list_item_fees,
    list_ledger,
    make_member_headers,
    read_box,
    read_box_item,
    read_member,
    read_subscription,
    register_member,
    set_clock,
    setup_inspected_box,
    setup_loss_fee,
    validate_error,
    validate_success,
)


class TestDisputeCycle:
    def _setup(self, api):
        return setup_loss_fee(
            member_email="m.disp@x.com",
            item_overrides={"title": "Train Set", "piece_count": 12,
                            "retail_value_cents": 10000,
                            "replacement_value_cents": 8000},
        )

    def test_dispute_cycle_two_rounds_then_limit(self, api):
        """PRD §3.8: "Only an `INVOICED` fee may be disputed, and only while
        `dispute_rounds` remains below 2 — a third attempt fails with
        `ERR_DISPUTE_LIMIT_REACHED` (HTTP 422). A successful dispute moves the
        fee `INVOICED` → `DISPUTED` and increments `dispute_rounds` by one."
        PRD §3.8: "`UPHELD` returns the fee `DISPUTED` → `INVOICED` with no
        ledger activity"

        The INVOICED -> DISPUTED -> INVOICED loop repeats twice; the third
        dispute is refused while the fee stays payable.

        Design: Difficulty/non_linear_state_machine/fee_dispute_cycle_round_limited
        """
        ctx = self._setup(api)
        member, fee = ctx["member"], ctx["fee"]
        headers = make_member_headers(member["id"])

        for expected_rounds in (1, 2):
            disputed = validate_success(api.dispute_fee(
                fee["id"], create_dispute_payload("still disputing"), headers))
            assert disputed["status"] == "DISPUTED"
            assert disputed["dispute_rounds"] == expected_rounds
            upheld = validate_success(api.resolve_dispute(
                fee["id"], create_resolve_dispute_payload("UPHELD"), SUPPORT))
            assert upheld["status"] == "INVOICED"
            assert upheld["dispute_rounds"] == expected_rounds

        resp = api.dispute_fee(fee["id"], create_dispute_payload("third attempt"),
                               headers)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value, 422)

    def test_dispute_cycle_fee_remains_payable_and_linked(self, api):
        """PRD §3.8: "Only an `INVOICED` fee may be disputed, and only while
        `dispute_rounds` remains below 2 — a third attempt fails with
        `ERR_DISPUTE_LIMIT_REACHED` (HTTP 422)."
        PRD §3.8: "Every financial charge materializes as a fee assessment
        carrying a `fee_type` of `DAMAGE`, `MISSING_PIECES`, `LOSS`, or
        `LATE_RETURN`, a positive `amount_cents`, the owning `subscription_id`,
        the source `rotation_box_id` present for all fee types, and — for every
        type except `LATE_RETURN` — the source `box_item_id`."

        After the limit is hit the LOSS fee remains INVOICED for its full
        replacement-value amount and stays linked to its source item and box.

        Design: Difficulty/non_linear_state_machine/fee_dispute_cycle_round_limited
        """
        ctx = self._setup(api)
        member, fee = ctx["member"], ctx["fee"]
        headers = make_member_headers(member["id"])

        for _ in range(2):
            validate_success(api.dispute_fee(fee["id"], create_dispute_payload(), headers))
            validate_success(api.resolve_dispute(
                fee["id"], create_resolve_dispute_payload("UPHELD"), SUPPORT))
        validate_error(api.dispute_fee(fee["id"], create_dispute_payload(), headers),
                       ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value, 422)

        fee_now = list_item_fees(ctx["item"]["id"], member)[0]
        assert fee_now["status"] == "INVOICED"
        assert fee_now["amount_cents"] == 8000
        assert fee_now["fee_type"] == "LOSS"
        assert fee_now["dispute_rounds"] == 2
        assert fee_now["box_item_id"] == ctx["item"]["id"]
        assert fee_now["rotation_box_id"] == ctx["box"]["id"]


class TestPayStateTrumpsFiscal:
    def _setup(self, api):
        """LOSS fee 600 INVOICED then waived (wallet -600 -> 0), then a -50
        support adjustment leaves the wallet at -50 — short of the 600 a
        WALLET_CREDIT payment would need."""
        ctx = setup_loss_fee(
            member_email="m.conf1@x.com",
            item_overrides={"title": "Rattle", "piece_count": 2,
                            "retail_value_cents": 1000, "replacement_value_cents": 600},
        )
        member, fee = ctx["member"], ctx["fee"]
        validate_success(api.waive_fee(fee["id"], create_waive_payload("goodwill"),
                                       SUPPORT))
        adjust_wallet(member["id"], -50, reason="SUPPORT_ADJUSTMENT", note="clawback")
        assert read_member(member["id"])["wallet_credit_cents"] == -50
        return ctx

    def test_pay_waived_fee_with_insufficient_wallet_surfaces_state_error(self, api):
        """PRD §2.6: "The pipeline evaluates, in order: ... (5) state-legality
        gates ... the state gates surface domain-specific codes such as ...
        `ERR_FEE_NOT_INVOICED` ... (10) fiscal rules — wallet sufficiency
        (`ERR_WALLET_INSUFFICIENT`), ..."
        PRD §3.8: "The fee must be `INVOICED`, else `ERR_FEE_NOT_INVOICED`
        (HTTP 409)."

        The pay violates both the state gate (fee WAIVED) and the fiscal gate
        (wallet -50 < 600); the priority-5 state error must surface.

        Design: Difficulty/priority_pair_validation_conflict/fee_pay_state_trumps_fiscal
        """
        ctx = self._setup(api)
        member, fee = ctx["member"], ctx["fee"]

        resp = api.pay_fee(fee["id"], create_pay_fee_payload("WALLET_CREDIT"),
                           make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_INVOICED.value, 409)

    def test_rejected_pay_leaves_no_trace(self, api):
        """PRD §3.8: "A `WALLET_CREDIT` payment requires `wallet_credit_cents`
        to cover the full `amount_cents` — anything less fails with
        `ERR_WALLET_INSUFFICIENT` (HTTP 422) — and appends a pair of entries:
        `FEE_SETTLED_WALLET` for the amount and `WALLET_DEBIT` for its
        negative, so the wallet's net movement from settlement is zero beyond
        the original charge."
        PRD §2.9: "The field is recomputed after every ledger append and is
        never written directly."

        The rejected pay appends nothing: the fee stays WAIVED and the wallet
        stays at -50 with exactly the three pre-existing ledger entries.

        Design: Difficulty/priority_pair_validation_conflict/fee_pay_state_trumps_fiscal
        """
        ctx = self._setup(api)
        member, fee = ctx["member"], ctx["fee"]

        validate_error(api.pay_fee(fee["id"], create_pay_fee_payload("WALLET_CREDIT"),
                                   make_member_headers(member["id"])),
                       ApiErrorId.ERR_FEE_NOT_INVOICED.value, 409)

        fee_now = list_item_fees(ctx["item"]["id"], member)[0]
        assert fee_now["status"] == "WAIVED"
        entries = list_ledger(member["id"])
        assert len(entries) == 3
        assert sorted((e["reason"], e["amount_cents"]) for e in entries) == [
            ("FEE_CHARGE", -600), ("FEE_WAIVER", 600), ("SUPPORT_ADJUSTMENT", -50)]
        assert read_member(member["id"])["wallet_credit_cents"] == -50


class TestWalletPayment:
    def test_wallet_credit_insufficient_then_card_succeeds(self, api):
        """PRD §3.8: "A `CARD` payment always succeeds and appends a single
        `FEE_SETTLED_CARD` entry for the amount. A `WALLET_CREDIT` payment
        requires `wallet_credit_cents` to cover the full `amount_cents` —
        anything less fails with `ERR_WALLET_INSUFFICIENT` (HTTP 422)"
        PRD §3.8: "Either way the wallet recompute runs (suspension toggle
        included), and when the payment leaves every fee of the owning item in
        a terminal state, that item's `resolution_status` advances to
        `RESOLVED`."

        Wallet 100 against the 600 fee fails; the CARD retry settles it and the
        +600 settlement entry brings the wallet to 700.

        Design: Corner/errors/wallet_credit_payment_insufficient_then_card_succeeds
        """
        ctx = setup_loss_fee(
            member_email="m.wpay@x.com",
            item_overrides={"title": "Rattle", "piece_count": 2,
                            "retail_value_cents": 1000, "replacement_value_cents": 600},
        )
        member, fee, item = ctx["member"], ctx["fee"], ctx["item"]
        headers = make_member_headers(member["id"])
        adjust_wallet(member["id"], 700, reason="SUPPORT_ADJUSTMENT", note="topup")
        assert read_member(member["id"])["wallet_credit_cents"] == 100

        resp = api.pay_fee(fee["id"], create_pay_fee_payload("WALLET_CREDIT"), headers)
        validate_error(resp, ApiErrorId.ERR_WALLET_INSUFFICIENT.value, 422)
        assert list_item_fees(item["id"], member)[0]["status"] == "INVOICED"

        paid = validate_success(api.pay_fee(fee["id"], create_pay_fee_payload("CARD"),
                                            headers))
        assert paid["status"] == "PAID"
        assert read_member(member["id"])["wallet_credit_cents"] == 700
        assert read_box_item(item["id"], member)["resolution_status"] == "RESOLVED"


class TestWalletConservation:
    def _setup(self, api):
        return setup_loss_fee(
            member_email="m.inv1@x.com",
            wallet_seed=500,
            item_overrides={"title": "Rattle", "piece_count": 2,
                            "retail_value_cents": 1000, "replacement_value_cents": 600},
        )

    def test_charge_then_waive_restores_wallet_exactly(self, api):
        """PRD §2.9: "The invariant is absolute: a member's
        `wallet_credit_cents` always equals the sum of `amount_cents` across
        all of that member's ledger entries. The field is recomputed after
        every ledger append and is never written directly."
        PRD §3.8: "Waiving appends a compensating `FEE_WAIVER` entry for the
        amount (offsetting the original `FEE_CHARGE`), recomputes the wallet,
        and advances the owning item's resolution as above."

        500 seed - 600 charge + 600 waiver returns the wallet to the pre-charge
        500 exactly.

        Design: Difficulty/compensating_invariant/wallet_charge_waive_conservation
        """
        ctx = self._setup(api)
        member, fee = ctx["member"], ctx["fee"]
        assert read_member(member["id"])["wallet_credit_cents"] == -100

        validate_success(api.waive_fee(fee["id"], create_waive_payload("goodwill"),
                                       SUPPORT))

        member_now = read_member(member["id"])
        assert member_now["wallet_credit_cents"] == 500
        entries = list_ledger(member["id"])
        assert len(entries) == 3
        assert sorted((e["reason"], e["amount_cents"]) for e in entries) == [
            ("FEE_CHARGE", -600), ("FEE_WAIVER", 600), ("PROMO_CREDIT", 500)]
        assert_wallet_matches_ledger(member_now, entries)

    def test_waived_fee_terminal_effects(self, api):
        """PRD §3.8: "Waiving appends a compensating `FEE_WAIVER` entry for the
        amount (offsetting the original `FEE_CHARGE`), recomputes the wallet,
        and advances the owning item's resolution as above."
        PRD §3.8: "when the payment leaves every fee of the owning item in a
        terminal state, that item's `resolution_status` advances to `RESOLVED`."
        PRD §2.9: "The boundary is exact: a balance of precisely −5,000 cents
        keeps the member `ACTIVE`."

        The wallet never crosses below -5,000 (worst point -100), so the member
        stays ACTIVE throughout; the waived fee moves the item to RESOLVED.

        Design: Difficulty/compensating_invariant/wallet_charge_waive_conservation
        """
        ctx = self._setup(api)
        member, fee, item = ctx["member"], ctx["fee"], ctx["item"]

        validate_success(api.waive_fee(fee["id"], create_waive_payload("goodwill"),
                                       SUPPORT))

        assert list_item_fees(item["id"], member)[0]["status"] == "WAIVED"
        assert read_box_item(item["id"], member)["resolution_status"] == "RESOLVED"
        assert read_member(member["id"])["status"] == "ACTIVE"


class TestImmediateVisibility:
    def test_wallet_adjustment_immediately_visible(self, api):
        """PRD §2.11: "The consistency model is immediate: when one operation
        mutates several resources — a pause cancelling a planned box, a swap
        releasing a copy that promotes a waiting wishlist entry, an inspection
        emitting fees that debit the wallet and suspend the member — every
        effect is applied atomically and is visible in that same request's
        response."
        PRD §2.9: "The field is recomputed after every ledger append and is
        never written directly."

        Design: Corner/consistency_model/wallet_adjustment_immediately_visible
        """
        member = register_member(email="m.cons@x.com")
        resp = api.create_wallet_adjustment(
            member["id"],
            create_wallet_adjustment_payload(250, "PROMO_CREDIT", "instant"),
            SUPPORT,
        )
        entry = validate_success(resp, 201)
        assert entry["amount_cents"] == 250
        assert entry["reason"] == "PROMO_CREDIT"

        member_now = read_member(member["id"])
        assert member_now["wallet_credit_cents"] == 250


class TestBoxClosureGate:
    def test_close_blocked_by_outstanding_fees_then_succeeds_after_card_pay(self, api):
        """PRD §3.8: "Closing an inspected box is an `OperationsManager`
        action, `INSPECTED` → `CLOSED`, with any other from-state rejected as
        `ERR_INVALID_STATE`; it demands every fee tied to the box already
        `PAID` or `WAIVED`, else `ERR_FEES_OUTSTANDING` (HTTP 422). Closure
        resets the subscription's `next_cycle_due_at` to the current clock plus
        the plan's `rotation_cadence_days` and increments the subscription's
        `version` by one."
        PRD §3.8: "A `CARD` payment always succeeds and appends a single
        `FEE_SETTLED_CARD` entry for the amount."

        MINOR damage on replacement 8000 -> round_half_up(8000 x 0.15) = 1200
        INVOICED; close is refused until the CARD settlement.

        Design: Corner/endpoints/close_box_blocked_by_outstanding_fees_then_succeeds
        """
        ctx = setup_inspected_box(
            member_email="m.cls@x.com",
            item_overrides={"title": "Drum", "piece_count": 4,
                            "retail_value_cents": 10000,
                            "replacement_value_cents": 8000},
            barcode="BC-CLS-1",
            damage_severity="MINOR",
            received_at="2026-05-09T00:00:00Z",
            return_in_transit_at="2026-05-08T00:00:00Z",
        )
        member, box = ctx["member"], ctx["box"]
        headers = make_member_headers(member["id"])
        fee = list_box_fees(box["id"], member)[0]
        assert fee["amount_cents"] == 1200

        set_clock("2026-05-10T00:00:00Z")
        resp = api.close_box(box["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FEES_OUTSTANDING.value, 422)
        assert read_box(box["id"], member)["status"] == "INSPECTED"

        paid = validate_success(api.pay_fee(fee["id"], create_pay_fee_payload("CARD"),
                                            headers))
        assert paid["status"] == "PAID"
        # FEE_SETTLED_CARD +1200 compensates the FEE_CHARGE -1200.
        assert read_member(member["id"])["wallet_credit_cents"] == 0

        closed = validate_success(api.close_box(box["id"], OPS))
        assert closed["status"] == "CLOSED"
        sub_now = read_subscription(ctx["subscription"]["id"], member)
        assert_same_instant(sub_now["next_cycle_due_at"], "2026-06-07T00:00:00Z",
                            "next_cycle_due_at (clock 2026-05-10 + 28 days)")
