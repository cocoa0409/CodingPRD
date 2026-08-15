"""Stewardship endowment: unitization, the waterfall draw allocation, dual
capacity lenses, fiscal-year close, OCC, and the append-only ledger
(PRD §3.9, §2.4, §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_endowment_transaction,
    close_fund_year,
    create_draft_easement,
    create_endowment_fund_payload,
    create_fund,
    fund_version,
    get_fund,
    list_fund_transactions,
    make_board_reviewer_headers,
    make_coordinator_headers,
    post_contribution,
    post_draw,
    post_draw_payload,
    post_return,
    setup_active_fund,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers("coord-1")
BOARD = make_board_reviewer_headers("board-1")


class TestLedgerShape:
    def test_endowment_transaction_immutable_ledger_shape(self, api, trust_admin_headers):
        """PRD §2.4: "An `EndowmentTransaction` is an immutable, append-only
        ledger event: it carries `id` and `created_at` only. It has no
        `updated_at` and no `version`, and it is never modified after posting."
        PRD §3.9: "Before any posting, the unit value is anchored at exactly
        100.0000 cents (one dollar), and the first contribution activates the
        fund from `INITIALIZING` to `ACTIVE` at that anchor."

        Design: Corner/entities/endowment_transaction_immutable_ledger_shape
        """
        easement = create_draft_easement(name="E-TX", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=1000)
        post_contribution(fund["id"], 100000)

        txns = list_fund_transactions(fund["id"])
        assert len(txns) == 1
        entry = txns[0]
        assert_endowment_transaction(entry)
        assert entry["txn_type"] == "CONTRIBUTION"
        assert entry["amount_cents"] == 100000
        assert entry["units"] == pytest.approx(1000.0000, abs=1e-9), "100000 cents at the 100.0000 anchor"


class TestFundUniqueness:
    def test_second_fund_rejected(self, api, trust_admin_headers):
        """PRD §3.9: "Each easement may be backed by a single stewardship
        endowment — a second fund for the same easement is rejected with
        `ERR_FUND_ALREADY_EXISTS`."

        Design: Corner/validations/second_fund_rejected
        """
        easement = create_draft_easement(name="E-DF", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        create_fund(easement["id"], spending_rate_bps=400, principal_floor_cents=1000)
        resp = api.create_endowment_fund(
            create_endowment_fund_payload(
                easement["id"], spending_rate_bps=300, principal_floor_cents=2000
            ),
            trust_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_ALREADY_EXISTS)


class TestDrawOccAndStateGate:
    def test_occ_stale_fund_version_on_draw(self, api):
        """PRD §2.8: "Posting an endowment draw requires `expected_fund_version`
        equal to the fund's current `version`. The caller computed its allocation
        against a snapshot of `market_value_cents`, `unit_value_cents`, and the
        draw allowance that a prior write may already have moved, and a fresh
        draw would otherwise still pass every balance check against the new
        state; a mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_fund_version_on_draw
        """
        easement = create_draft_easement(name="E-OC2", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=100000)
        stale_version = fund["version"]
        post_contribution(fund["id"], 500000)

        resp = api.post_draw(
            fund["id"],
            post_draw_payload(5000, "MONITORING", stale_version),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FUND_VERSION)

    def test_draw_on_initializing_fund_state_gate_wins(self, api):
        """PRD §2.9: "Validations run in a fixed order, and an earlier failure
        masks every later check."
        PRD §2.9: "Cross-entity gates — child operational creates require a
        `RECORDED` easement (`ERR_EASEMENT_NOT_RECORDED`); recordation requires
        an `ACCEPTED` baseline and an `ACTIVE` landowner
        (`ERR_BASELINE_NOT_ACCEPTED`, `ERR_OPEN_OBLIGATIONS_EXIST`); investment
        returns, draws, and fiscal-year close require an `ACTIVE` fund
        (`ERR_FUND_NOT_ACTIVE`)."
        PRD §2.9: "Draw authority — `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD` and
        `ERR_DRAW_EXCEEDS_AUTHORITY` (402)."
        PRD §3.9: "a stale version is rejected with `ERR_STALE_FUND_VERSION`
        (412), and a draw against an `INITIALIZING` fund with
        `ERR_FUND_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/draw_state_gate_beats_fiscal_check
        """
        easement = create_draft_easement(name="E-PP1", parcel_acreage=500,
                                         matrix={"AGRICULTURE": "PERMITTED",
                                                 "SUBDIVISION": "PROHIBITED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=100000)
        assert fund["status"] == "INITIALIZING"

        # This amount also exceeds every fiscal ceiling; the state gate (an
        # earlier pipeline stage) must be the error reported.
        resp = api.post_draw(
            fund["id"],
            post_draw_payload(999999999, "ENFORCEMENT", fund["version"]),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_NOT_ACTIVE)

    def test_return_and_close_on_initializing_fund_rejected(self, api, trust_admin_headers,
                                                            board_reviewer_headers):
        """PRD §3.9: "investment returns are signed and may be negative, but
        returns (like draws and the fiscal-year close) require an `ACTIVE` fund
        — against an `INITIALIZING` fund they are rejected with
        `ERR_FUND_NOT_ACTIVE` (409)."
        PRD §3.9: "The fiscal-year close is a `TrustBoardReviewer` act on an
        `ACTIVE` fund"

        Design: Difficulty/priority_pair_validation_conflict/draw_state_gate_beats_fiscal_check
        """
        easement = create_draft_easement(name="E-PP1B", parcel_acreage=500,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=100000)

        resp_return = api.post_return(fund["id"], {"amount_cents": 1000},
                                      trust_admin_headers)
        validate_error(resp_return, ApiErrorId.ERR_FUND_NOT_ACTIVE)

        resp_close = api.close_fund_year(fund["id"], board_reviewer_headers)
        validate_error(resp_close, ApiErrorId.ERR_FUND_NOT_ACTIVE)


class TestUnitization:
    def test_contribution_at_par_keeps_unit_value(self, api):
        """PRD §3.9: "First, the units delta is computed as the posting's
        absolute `amount_cents` divided by the current `unit_value_cents`,
        rounded half-up to four decimal places."
        PRD §3.9: "Third, `unit_value_cents` is recomputed as market value
        divided by units outstanding, rounded half-up to four decimal places — a
        step skipped while `units_outstanding` is zero, when the unit value reads
        null."
        PRD §3.9: "Before any posting, the unit value is anchored at exactly
        100.0000 cents (one dollar), and the first contribution activates the
        fund from `INITIALIZING` to `ACTIVE` at that anchor."

        Design: Corner/calculations/contribution_at_par_keeps_unit_value
        """
        easement = create_draft_easement(name="E-UV", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=1000)
        post_contribution(fund["id"], 100000)
        second = post_contribution(fund["id"], 50000)
        assert second["units"] == pytest.approx(500.0000, abs=1e-9), "issued at the current rounded unit value"

        after = get_fund(fund["id"])
        assert after["unit_value_cents"] == pytest.approx(100.0000, abs=1e-9), "par issuance leaves the unit value unchanged"
        assert after["units_outstanding"] == pytest.approx(1500.0000, abs=1e-9)
        assert after["market_value_cents"] == 150000
        assert after["status"] == "ACTIVE"

    def test_unitization_rounding_order_anchor_and_revalue(self, api):
        """PRD §3.9: "Every posting follows a pinned three-step rounding order.
        First, the units delta is computed as the posting's absolute
        `amount_cents` divided by the current `unit_value_cents`, rounded half-up
        to four decimal places. Second, the aggregates are applied per
        `txn_type`: a `CONTRIBUTION` adds its units delta to `units_outstanding`
        and its amount to `market_value_cents`; a `DRAW` subtracts its units
        delta and its absolute amount; an `INVESTMENT_RETURN` leaves units
        untouched and adds its signed amount to market value. Third,
        `unit_value_cents` is recomputed as market value divided by units
        outstanding, rounded half-up to four decimal places"

        Design: Difficulty/combinatorial_formula/unitization_nested_rounding_order
        """
        easement = create_draft_easement(name="E-UN", parcel_acreage=500,
                                         matrix={"AGRICULTURE": "PERMITTED",
                                                 "SUBDIVISION": "PROHIBITED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=100000)

        first = post_contribution(fund["id"], 333333)
        assert first["units"] == pytest.approx(3333.3300, abs=1e-9), "333333 cents at the 100.0000 anchor"

        post_return(fund["id"], 77777)
        after_return = get_fund(fund["id"])
        # round(411110 / 3333.3300, 4) half-up.
        assert after_return["unit_value_cents"] == pytest.approx(123.3331, abs=1e-9)
        assert after_return["market_value_cents"] == 411110
        assert after_return["units_outstanding"] == pytest.approx(3333.3300, abs=1e-9)

    def test_unitization_second_contribution_uses_rounded_uv(self, api):
        """PRD §3.9: "The rounding order is pinned because computing units from
        an unrounded intermediate unit value — rather than the rounded value
        carried from the previous posting — yields different fourth-decimal
        units."

        Design: Difficulty/combinatorial_formula/unitization_nested_rounding_order
        """
        easement = create_draft_easement(name="E-UN2", parcel_acreage=500,
                                         matrix={"AGRICULTURE": "PERMITTED",
                                                 "SUBDIVISION": "PROHIBITED"})
        fund = create_fund(easement["id"], spending_rate_bps=400,
                           principal_floor_cents=100000)
        post_contribution(fund["id"], 333333)
        post_return(fund["id"], 77777)

        second = post_contribution(fund["id"], 100000)
        # round(100000 / 123.3331, 4) = 810.8123 under the pinned order; the
        # unrounded-intermediate order would produce 810.8122.
        assert second["units"] == pytest.approx(810.8123, abs=1e-9)

        after = get_fund(fund["id"])
        assert after["units_outstanding"] == pytest.approx(4144.1423, abs=1e-9)
        assert after["unit_value_cents"] == pytest.approx(123.3331, abs=1e-9)
        assert after["market_value_cents"] == 511110


class TestDualCapacityLenses:
    def test_draw_capacity_unitized_vs_policy_after_close(self, api):
        """PRD §3.9: "`unitized_draw_capacity_cents` is instantaneous: the fund's
        market value less the principal floor, floored at zero, blind to spending
        policy. `policy_draw_allowance_cents` is the policy lens: the
        current-year policy amount — frozen at the last fiscal-year close — plus
        `carryover_allowance_cents`."
        PRD §3.9: "Step four snapshots `prior_year_close_mv_cents` as the current
        `market_value_cents`, freezes next year's policy amount as that snapshot
        multiplied by `spending_rate_bps` and divided by ten thousand, rounded
        half-up to whole cents, resets `provisional_draws_ytd_cents` to zero, and
        increments `fiscal_year` by one"

        Design: Difficulty/dual_variant_calc/endowment_draw_capacity_unitized_vs_policy
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund = ctx["fund"]
        close_fund_year(fund["id"])

        after = get_fund(fund["id"])
        assert after["market_value_cents"] == 500000
        assert after["fiscal_year"] == 2
        assert after["unitized_draw_capacity_cents"] == 400000, (
            "instantaneous lens: 500000 - 100000 floor"
        )
        assert after["policy_draw_allowance_cents"] == 20000, (
            "policy lens: round(500000 * 400bps / 10000) + 0 carryover"
        )
        assert after["unitized_draw_capacity_cents"] - after["policy_draw_allowance_cents"] == 380000

    def test_policy_allowance_frozen_while_unitized_tracks_market(self, api):
        """PRD §3.9: "Two capacity lenses frame every draw, and they legitimately
        disagree. `unitized_draw_capacity_cents` is instantaneous: the fund's
        market value less the principal floor, floored at zero, blind to spending
        policy."
        PRD §3.9: "the current-year policy amount — frozen at the last
        fiscal-year close — plus `carryover_allowance_cents`"

        Design: Difficulty/dual_variant_calc/endowment_draw_capacity_unitized_vs_policy
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund = ctx["fund"]
        close_fund_year(fund["id"])

        # An intrayear return moves the market value; the policy lens was frozen
        # at the close and does not move until the next one.
        post_return(fund["id"], 100000)
        after = get_fund(fund["id"])
        assert after["market_value_cents"] == 600000
        assert after["unitized_draw_capacity_cents"] == 500000
        assert after["policy_draw_allowance_cents"] == 20000


class TestWaterfallDrawAllocation:
    def test_waterfall_draw_policy_then_excess_buckets(self, api):
        """PRD §3.9: "Bucket one is the spending-policy allowance: the remaining
        allowance is `policy_draw_allowance_cents` less
        `provisional_draws_ytd_cents`, floored at zero, and
        `from_policy_allowance_cents` absorbs the draw up to that remainder.
        Bucket two is excess over the principal floor: `from_excess_cents`
        absorbs the smaller of the remaining draw amount and the unitized
        capacity — `market_value_cents` less `principal_floor_cents`, floored at
        zero — less what the first bucket already absorbed."
        PRD §3.9: "The posted `DRAW` transaction records all three bucket fields
        along with its `purpose`, carries an `amount_cents` equal to the negated
        draw amount, and redeems units under the pinned unitization order"

        Design: Difficulty/combinatorial_formula/waterfall_draw_allocation_three_bucket_branch
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        close_fund_year(fund_id)  # policy allowance 20000, unitized capacity 400000

        small = post_draw(fund_id, 5000, "MONITORING", fund_version(fund_id))
        assert small["txn_type"] == "DRAW"
        assert small["amount_cents"] == -5000
        assert small["from_policy_allowance_cents"] == 5000
        assert small["from_excess_cents"] == 0
        assert small["from_principal_invasion_cents"] == 0

        large = post_draw(fund_id, 300000, "ENFORCEMENT", fund_version(fund_id))
        # Remaining allowance is 20000 - 5000 = 15000; the rest fits under the
        # 400000 unitized ceiling less the 15000 already absorbed.
        assert large["from_policy_allowance_cents"] == 15000
        assert large["from_excess_cents"] == 285000
        assert large["from_principal_invasion_cents"] == 0

    def test_waterfall_invasion_requires_board_and_version_unconsumed(self, api):
        """PRD §3.9: "Whatever still remains after both buckets is principal
        invasion: it is rejected with `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD`
        (402) unless the actor is a `TrustBoardReviewer`, and even for the board
        a draw larger than the fund's entire `market_value_cents` is rejected
        with `ERR_DRAW_EXCEEDS_AUTHORITY` (402). An authorized invasion is
        recorded in `from_principal_invasion_cents`; otherwise that field is
        zero."
        PRD §2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly one on every mutation of the resource"

        Design: Difficulty/combinatorial_formula/waterfall_draw_allocation_three_bucket_branch
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        close_fund_year(fund_id)
        post_draw(fund_id, 5000, "MONITORING", fund_version(fund_id))
        post_draw(fund_id, 300000, "ENFORCEMENT", fund_version(fund_id))

        # Fund now: MV 195000, allowance exhausted, excess headroom 95000.
        current_version = fund_version(fund_id)
        resp = api.post_draw(
            fund_id, post_draw_payload(150000, "ENFORCEMENT", current_version),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_PRINCIPAL_INVASION_REQUIRES_BOARD)

        # The rejected draw consumed no version, so the board retry with the
        # same expected version succeeds.
        retried = validate_success(
            api.post_draw(
                fund_id, post_draw_payload(150000, "ENFORCEMENT", current_version),
                BOARD,
            ),
            201,
        )
        assert retried["from_policy_allowance_cents"] == 0
        assert retried["from_excess_cents"] == 95000
        assert retried["from_principal_invasion_cents"] == 55000

        after = get_fund(fund_id)
        assert after["market_value_cents"] == 45000, (
            "only board authority could take the fund below the 100000 floor"
        )


class TestDrawAuthorityBoundary:
    def test_board_draw_above_market_value_rejected(self, api):
        """PRD §3.9: "Whatever still remains after both buckets is principal
        invasion: it is rejected with `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD`
        (402) unless the actor is a `TrustBoardReviewer`, and even for the board
        a draw larger than the fund's entire `market_value_cents` is rejected
        with `ERR_DRAW_EXCEEDS_AUTHORITY` (402)."
        PRD §3.9: "In `fiscal_year` 1 both components are zero, so first-year
        draws draw entirely on the excess bucket."

        Design: Corner/validations/board_draw_above_market_value_rejected
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        current_version = fund_version(fund_id)

        resp = api.post_draw(
            fund_id, post_draw_payload(600000, "ENFORCEMENT", current_version),
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_AUTHORITY)

        # The over-market rejection consumed no version: one cent past the
        # 400000 unitized ceiling succeeds for the board via the invasion branch.
        invasion = validate_success(
            api.post_draw(
                fund_id, post_draw_payload(400001, "ENFORCEMENT", current_version),
                BOARD,
            ),
            201,
        )
        assert invasion["from_policy_allowance_cents"] == 0
        assert invasion["from_excess_cents"] == 400000
        assert invasion["from_principal_invasion_cents"] == 1


class TestCarryover:
    def test_carryover_pinned_evaluation_order(self, api):
        """PRD §3.9: "Step two computes the year's underuse: the closed year's
        policy amount plus `carryover_allowance_cents`, less
        `provisional_draws_ytd_cents`, floored at zero. Step three sets the new
        `carryover_allowance_cents` to the smaller of that underuse and the
        closed year's policy amount — capped by the closed year's policy, never
        by next year's; substituting next year's amount here is the forbidden
        evaluation order and produces a different carryover whenever market value
        shrank during the closed year."

        Design: Difficulty/combinatorial_formula/carryover_allowance_pinned_evaluation_order
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        close_fund_year(fund_id)  # year 1 -> 2: policy frozen at 20000
        post_return(fund_id, -200000)  # market value shrinks to 300000
        close_fund_year(fund_id)  # year 2 -> 3

        after = get_fund(fund_id)
        assert after["fiscal_year"] == 3
        assert after["prior_year_close_mv_cents"] == 300000
        # underuse = max(0, 20000 + 0 - 0) = 20000; carryover = min(20000, 20000).
        assert after["carryover_allowance_cents"] == 20000
        # New policy = round(300000 * 400 / 10000) = 12000; allowance = 12000 + 20000.
        assert after["policy_draw_allowance_cents"] == 32000

    def test_carryover_spendable_next_year_proves_cap(self, api):
        """PRD §3.9: "Step three sets the new `carryover_allowance_cents` to the
        smaller of that underuse and the closed year's policy amount — capped by
        the closed year's policy, never by next year's"
        PRD §3.9: "From that moment the new `policy_draw_allowance_cents` reads
        as the freshly frozen policy amount plus the new carryover."

        Design: Difficulty/combinatorial_formula/carryover_allowance_pinned_evaluation_order
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        close_fund_year(fund_id)
        post_return(fund_id, -200000)
        close_fund_year(fund_id)

        # A 30000-cent draw is absorbed entirely by bucket one iff the allowance
        # really is 32000; the forbidden evaluation order would cap it at 24000
        # and spill 6000 into the excess bucket.
        draw = post_draw(fund_id, 30000, "GENERAL_STEWARDSHIP", fund_version(fund_id))
        assert draw["from_policy_allowance_cents"] == 30000
        assert draw["from_excess_cents"] == 0
        assert draw["from_principal_invasion_cents"] == 0


class TestLedgerConservation:
    def _posting_sequence(self, fund_id):
        """contribution 500000, return +50000, draw 120000, return -20000."""
        post_return(fund_id, 50000)
        draw = post_draw(fund_id, 120000, "GENERAL_STEWARDSHIP", fund_version(fund_id))
        post_return(fund_id, -20000)
        return draw

    def test_fund_ledger_conservation_across_posting_types(self, api):
        """PRD §3.9: "Second, the aggregates are applied per `txn_type`: a
        `CONTRIBUTION` adds its units delta to `units_outstanding` and its amount
        to `market_value_cents`; a `DRAW` subtracts its units delta and its
        absolute amount; an `INVESTMENT_RETURN` leaves units untouched and adds
        its signed amount to market value."

        Design: Difficulty/compensating_invariant/fund_ledger_conservation_across_posting_types
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        assert ctx["contribution_txn"]["units"] == pytest.approx(5000.0000, abs=1e-9), (
            "500000 cents at the 100.0000 anchor"
        )

        draw = self._posting_sequence(fund_id)
        # After the +50000 return the unit value is 550000/5000 = 110.0000.
        assert draw["amount_cents"] == -120000
        assert draw["units"] == pytest.approx(1090.9091, abs=1e-9), (
            "round(120000 / 110.0000, 4)"
        )

        after = get_fund(fund_id)
        assert after["market_value_cents"] == 410000, (
            "500000 + 50000 - 120000 - 20000, the exact sum of ledger amount_cents"
        )
        assert after["units_outstanding"] == pytest.approx(3909.0909, abs=1e-9), (
            "5000.0000 - 1090.9091, the exact sum of ledger units"
        )

    def test_fund_ledger_posting_order(self, api):
        """PRD §3.9: "The fund's books are an append-only ledger of
        `EndowmentTransaction` entries, processed strictly in posting order — by
        `posted_on`, then by `created_at` — and the fund's transaction listing
        returns entries in that same order."

        Design: Difficulty/compensating_invariant/fund_ledger_conservation_across_posting_types
        """
        ctx = setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                                contribution_cents=500000)
        fund_id = ctx["fund"]["id"]
        self._posting_sequence(fund_id)

        txns = list_fund_transactions(fund_id)
        assert len(txns) == 4
        for entry in txns:
            assert_endowment_transaction(entry)
        assert [(t["txn_type"], t["amount_cents"]) for t in txns] == [
            ("CONTRIBUTION", 500000),
            ("INVESTMENT_RETURN", 50000),
            ("DRAW", -120000),
            ("INVESTMENT_RETURN", -20000),
        ]
