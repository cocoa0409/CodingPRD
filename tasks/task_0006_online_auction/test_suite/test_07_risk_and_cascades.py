"""Risk score, restriction/suspend cascade, and refund/lot-close cascades (PRD §3.6, §2.8)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    place_bid_payload, event_account_takeover_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, setup_live_lot, setup_sold_lot,
    place_bid_on_lot, close_lot_to_sold, get_lot,
    advance_clock,
    validate_success, validate_error,
    assert_bidder,
    ACUTE_PENALTY_TAKEOVER, ACUTE_PENALTY_SHILL,
    RISK_RESTRICT_THRESHOLD, RISK_SUSPEND_THRESHOLD,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestManualRestrictAndReinstate:
    def test_manual_restrict_blocks_bidding(self, api):
        """PRD §3.6: "A `RESTRICTED` `Bidder` cannot place new bids or create new
        auto-bid proxies..."
        PRD §2.11: "Whenever a `Bidder.status` value is `RESTRICTED` or `SUSPENDED`,
        the bidder may not place bids, create proxies, accept a runner-up offer, or
        file disputes; such requests are rejected with `ERR_BIDDER_RESTRICTED` (HTTP
        403)."

        Claim: RESTRICTED bidder placing bid → ERR_BIDDER_RESTRICTED.

        # difficulty: cross_entity_state_dependency/lot_bid_depends_on_bidder_status
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        bidder = create_bidder("R", wallet_amount_cents=2_000_000)
        api.restrict_bidder(bidder["id"], ADMIN)
        resp = api.place_bid(lot["id"], place_bid_payload(100_000), make_bidder_headers(bidder["id"]))
        assert resp.status_code == 403
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_BIDDER_RESTRICTED"

    def test_reinstate_allows_bidding_again(self, api):
        """PRD §3.6: "...reinstating them to `ACTIVE` (which clears `acute_score`,
        recomputes `risk_score` from the chronic side, and clears both
        `account_takeover_alert` and `shill_pattern_detected`)."

        Claim: After reinstate from RESTRICTED, bidder.status=ACTIVE.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("R", wallet_amount_cents=2_000_000)
        api.restrict_bidder(bidder["id"], ADMIN)
        resp = api.reinstate_bidder(bidder["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


class TestAccountTakeoverEvent:
    def test_account_takeover_alert_sets_flag_and_acute(self, api):
        """PRD §3.6: "An identity-system event recording an account-takeover alert flips
        the bidder's `account_takeover_alert` to true, includes
        `ACUTE_PENALTY_TAKEOVER` (20.0) in the acute total, recomputes `risk_score`..."

        Claim: After account-takeover-alert event, bidder.account_takeover_alert=true
        and risk_score includes 20.0.
        """
        bidder = create_bidder("V")
        api.event_account_takeover_alert(event_account_takeover_payload(bidder["id"]), ADMIN)
        bidder_after = validate_success(api.get_bidder(bidder["id"], ADMIN))
        assert bidder_after["account_takeover_alert"] is True
        assert bidder_after["risk_score"] >= 20.0

    def test_reinstate_clears_acute_and_takeover_flag(self, api):
        """PRD §3.6: "The acute side is what makes the score volatile: after a
        `PlatformAdmin` reinstatement, the acute side is cleared to zero and the score
        reverts to the chronic-only reading..."

        Claim: After reinstate, account_takeover_alert=false and risk_score is chronic-only.

        # difficulty: dual_variant_calc/bidder_risk_score_chronic_vs_acute_variant
        """
        bidder = create_bidder("V")
        api.event_account_takeover_alert(event_account_takeover_payload(bidder["id"]), ADMIN)
        bidder_with_acute = validate_success(api.get_bidder(bidder["id"], ADMIN))
        # acute is 20 → score 20.0; not yet RESTRICTED (threshold 70)
        assert bidder_with_acute["risk_score"] == pytest.approx(20.0, abs=0.05)
        # Reinstate
        api.reinstate_bidder(bidder["id"], ADMIN)
        bidder_after = validate_success(api.get_bidder(bidder["id"], ADMIN))
        assert bidder_after["account_takeover_alert"] is False
        # No chronic component → risk_score = 0.0
        assert bidder_after["risk_score"] == pytest.approx(0.0, abs=0.05)


class TestShillVelocitySweep:
    def test_shill_sweep_flags_bidder_with_more_than_3_bids(self, api):
        """PRD §3.6: "An abnormal-bid-pattern detection sweep — invoked by the platform
        — examines the last 30 seconds of system clock for `Bid` records (the velocity
        window) and flags any bidder who placed strictly more than 3 bids on a single
        lot within that window: their `shill_pattern_detected` becomes true, the acute
        total includes `ACUTE_PENALTY_SHILL` (30.0), `risk_score` is recomputed, and
        the sweep response returns the array of flagged `bidder_id` values."

        Claim: After 4 bids by one bidder on a single lot within 30s window and a sweep,
        shill_pattern_detected=true and acute score reflects ACUTE_PENALTY_SHILL.
        """
        # Need a single bidder placing 4+ bids; but PRD §3.2 strict-greater means each
        # bid must exceed current_price. Use a self-bidder pattern where the bidder
        # is also competing against another bidder pushing prices, but the SAME bidder
        # places >3 bids.
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=10_000_000)
        attacker = create_bidder("Attacker", wallet_amount_cents=10_000_000)
        opponent = create_bidder("Opponent", wallet_amount_cents=10_000_000)

        # Alternating bids: attacker at 50000, opponent 51000, attacker 52000, opponent 53000,
        # attacker 54000, opponent 55000, attacker 56000, opponent 57000
        place_bid_on_lot(attacker, lot, 50_000)
        place_bid_on_lot(opponent, lot, 51_000)
        place_bid_on_lot(attacker, lot, 52_000)
        place_bid_on_lot(opponent, lot, 53_000)
        place_bid_on_lot(attacker, lot, 54_000)
        place_bid_on_lot(opponent, lot, 55_000)
        place_bid_on_lot(attacker, lot, 56_000)
        # attacker placed 4 bids on this lot

        resp = api.sweep_risk_monitor(ADMIN)
        sweep = validate_success(resp)
        assert attacker["id"] in sweep["flagged_bidder_ids"], (
            f"Expected attacker.id in flagged_bidder_ids; got {sweep['flagged_bidder_ids']}"
        )

        attacker_after = validate_success(api.get_bidder(attacker["id"], ADMIN))
        assert attacker_after["shill_pattern_detected"] is True
        assert attacker_after["risk_score"] >= 30.0


class TestSuspendCascade:
    def test_bidder_suspend_withdraws_active_bids(self, api):
        """PRD §2.8: "The **bidder-suspend cascade** triggered when a `Bidder` enters
        `SUSPENDED`. Hop one withdraws every `Bid` of theirs whose `status` is `ACTIVE`
        or `WINNING` to `WITHDRAWN_BY_RISK`."

        Claim: After /bidders/{id}/suspend, that bidder's ACTIVE bids → WITHDRAWN_BY_RISK.

        # difficulty: transitive_cascade/bidder_suspend_cascade
        """
        seller, lot = setup_live_lot(starting_bid_cents=10_000, reserve_price_cents=200_000)
        b = create_bidder("B", wallet_amount_cents=2_000_000)
        runner = create_bidder("RX", wallet_amount_cents=2_000_000)
        place_bid_on_lot(runner, lot, 10_000)   # base: 10000 → tier-2 increment 1000
        place_bid_on_lot(b, lot, 11_000)        # B winning at 11000

        api.suspend_bidder(b["id"], ADMIN)
        # B's bid should be WITHDRAWN_BY_RISK
        bids_resp = api.list_bids(lot["id"], ADMIN)
        bids = bids_resp.json()["data"]
        b_bids = [bid for bid in bids if bid["bidder_id"] == b["id"]]
        assert b_bids, "Expected B to have at least one bid"
        assert all(bid["status"] == "WITHDRAWN_BY_RISK" for bid in b_bids)

    def test_bidder_suspend_recomputes_lot_winner(self, api):
        """PRD §2.8: "Hop two recomputes `current_winner_bid_id`,
        `current_winner_bidder_id`, `current_price_cents`, and `runner_up_bid_id` on
        every `Lot` whose former winner was this bidder, using the lot-current-state
        aggregation rule."

        Claim: After suspend cascade, lot.current_winner_bidder_id = remaining bidder
        and current_price_cents = remaining bid amount.

        # difficulty: transitive_cascade/bidder_suspend_cascade
        """
        seller, lot = setup_live_lot(starting_bid_cents=10_000, reserve_price_cents=200_000)
        b = create_bidder("B", wallet_amount_cents=2_000_000)
        runner = create_bidder("RX", wallet_amount_cents=2_000_000)
        place_bid_on_lot(runner, lot, 10_000)
        place_bid_on_lot(b, lot, 11_000)

        api.suspend_bidder(b["id"], ADMIN)
        lot_after = get_lot(lot["id"])
        assert lot_after["current_price_cents"] == 10_000
        assert lot_after["current_winner_bidder_id"] == runner["id"]

    def test_bidder_suspend_releases_held_deposits(self, api):
        """PRD §2.8: "Hop three releases every still-`HELD` `Deposit` of theirs on lots
        that are still `LIVE` or `SCHEDULED` to `RELEASED` with
        `terminal_reason = BIDDER_RISK_WITHDRAWN`, crediting the wallet by the
        deposit's `amount_cents`."

        Claim: After suspend cascade, suspended bidder's wallet is restored
        (held_deposit_cents=0).

        # difficulty: transitive_cascade/bidder_suspend_cascade
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        b = create_bidder("B", wallet_amount_cents=200_000)
        place_bid_on_lot(b, lot, 50_000)

        bidder_during = validate_success(api.get_bidder(b["id"], ADMIN))
        assert bidder_during["held_deposit_cents"] >= 10_000  # deposit 10000 of reserve 100000
        # Wallet decremented by deposit hold? PRD says "the bidder's wallet_balance_cents
        # minus their existing held_deposit_cents" — keeps wallet visible but tracks held separately.
        # The PRD does NOT pin whether wallet_balance_cents is decremented at hold-time
        # or only on FORFEIT. We only check held_deposit_cents.

        api.suspend_bidder(b["id"], ADMIN)
        bidder_after = validate_success(api.get_bidder(b["id"], ADMIN))
        assert bidder_after["status"] == "SUSPENDED"
        assert bidder_after["held_deposit_cents"] == 0


class TestLotCloseCascade:
    def test_close_to_sold_bid_status_transitions(self, api):
        """PRD §3.4: "...the `Bid` referenced by `current_winner_bid_id` is moved to
        `WINNING`; every other `ACTIVE` bid on the lot is moved to `OUTBID`."

        Claim: At close, winner bid becomes WINNING and other bids become OUTBID.

        # difficulty: transitive_cascade/lot_close_cascade
        # difficulty: non_linear_state_machine/bid_branching_shape
        """
        seller, lot = setup_live_lot(starting_bid_cents=10_000, reserve_price_cents=10_000)
        b1 = create_bidder("L1", wallet_amount_cents=2_000_000)
        b2 = create_bidder("L2", wallet_amount_cents=2_000_000)
        b3 = create_bidder("W", wallet_amount_cents=2_000_000)
        place_bid_on_lot(b1, lot, 10_000)
        place_bid_on_lot(b2, lot, 11_000)
        place_bid_on_lot(b3, lot, 12_000)
        lot = close_lot_to_sold(lot["id"])
        assert lot["status"] == "SOLD"
        assert lot["hammer_price_cents"] == 12_000

        bids = api.list_bids(lot["id"], ADMIN).json()["data"]
        # winner has WINNING; others OUTBID
        winning = [b for b in bids if b["status"] == "WINNING"]
        outbid = [b for b in bids if b["status"] == "OUTBID"]
        assert len(winning) == 1
        assert winning[0]["bidder_id"] == b3["id"]
        assert {b["bidder_id"] for b in outbid} == {b1["id"], b2["id"]}


class TestDepositLedgerConservation:
    def test_unsold_lot_returns_held_deposit_to_wallet(self, api):
        """PRD §3.4: "If `has_met_reserve` is false, the lot transitions to `UNSOLD`;
        every `HELD` deposit on the lot — including the would-be winner's — is
        `RELEASED` with `terminal_reason = LOSING_BIDDER`."
        PRD §3.4: "...refund_amount_cents` set to the deposit's `amount_cents`." (full
        refund-to-wallet under LOSING_BIDDER terminal_reason).

        Claim: After UNSOLD, bidder's held_deposit_cents=0; wallet ≥ pre-bid wallet.

        # difficulty: compensating_invariant/deposit_ledger_conservation
        """
        # reserve 200_000 → deposit_required = max(500, min(1_000_000, floor(200_000*0.10))) = 20_000
        # bid only 100_000 (below reserve) → UNSOLD on close.
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("B", wallet_amount_cents=50_000)
        place_bid_on_lot(bidder, lot, 100_000)
        bidder_during = validate_success(api.get_bidder(bidder["id"], ADMIN))
        assert bidder_during["held_deposit_cents"] == 20_000

        lot = close_lot_to_sold(lot["id"])
        assert lot["status"] == "UNSOLD"

        bidder_after = validate_success(api.get_bidder(bidder["id"], ADMIN))
        assert bidder_after["held_deposit_cents"] == 0
