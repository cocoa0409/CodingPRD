"""Leagues: prize-pool pinned order, cancel cascade, scorecard cycles,
standings input set, and scorecard OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_league_pool_invariants,
    get_league,
    get_league_entry,
    get_member,
    get_scorecard_via_list,
    make_member_headers,
    register_ready_member,
    scorecard_payload,
    set_clock,
    setup_closed_league_with_scorecard,
    setup_league_with_entries,
    validate_error,
    validate_success,
)

LEAGUE_DIRECTOR = TEST_USERS["league_director_headers"]

NINES = [[9, 9, 9]] * 10
TENS = [[10, 10, 10]] * 10
EIGHTS = [[8, 8, 8]] * 10


class TestLeaguePrizePoolPinnedOrder:
    def test_gross_and_range_share_computed_from_gross(self, api):
        """PRD §3.8: "first `gross_entry_fees_cents` is the sum of
        `fee_paid_cents` over entries in `CONFIRMED` only (cancelled entries are
        excluded); then `range_share_cents` is 15% of the **gross**, rounded
        half up — never a percentage of the pool".

        Design: Difficulty/combinatorial_formula/league_prize_pool_pinned_evaluation_order
        """
        set_clock("2026-05-01T08:00:00Z")
        league, _, _ = setup_league_with_entries(4, entry_fee_cents=5000,
                                                 wallet_cents=5000,
                                                 league_name="Pool League")
        after = get_league(league["id"])
        assert after["gross_entry_fees_cents"] == 20000
        assert after["range_share_cents"] == 3000, (
            "round_half_up(20000 x 0.15) computed FROM GROSS"
        )

    def test_prize_pool_is_gross_minus_share(self, api):
        """PRD §3.8: "finally `prize_pool_cents` is the gross minus the range
        share."
        PRD §3.8: "then `range_share_cents` is 15% of the **gross**, rounded
        half up — never a percentage of the pool".

        Design: Difficulty/combinatorial_formula/league_prize_pool_pinned_evaluation_order
        """
        set_clock("2026-05-01T08:00:00Z")
        league, _, _ = setup_league_with_entries(4, entry_fee_cents=5000,
                                                 wallet_cents=5000,
                                                 league_name="Pool League")
        after = get_league(league["id"])
        # Share-of-pool reading would imply a different split; pinned order wins.
        assert after["prize_pool_cents"] == 17000
        assert_league_pool_invariants(after)


class TestLeagueCancelTwoHopRefundCascade:
    def _setup_open_league_with_entry(self, api):
        set_clock("2026-05-01T08:00:00Z")
        league, members, entries = setup_league_with_entries(
            1, entry_fee_cents=5000, wallet_cents=10000, league_name="Refund Open"
        )
        return league, members[0], entries[0]

    def test_cancel_cascades_entry_cancellation_and_refund_flag(self, api):
        """PRD §3.8: "Cancellation fires a two-hop cascade: every `CONFIRMED`
        entry transitions to terminal `CANCELLED`, and each cancelled entry
        credits its `fee_paid_cents` back to its member's wallet and sets
        `refund_status` to `REFUNDED`".

        Design: Difficulty/transitive_cascade/league_cancel_two_hop_refund_cascade
        """
        league, member, entry = self._setup_open_league_with_entry(api)
        cancelled = validate_success(api.cancel_league(league["id"], LEAGUE_DIRECTOR), 200)
        assert cancelled["status"] == "CANCELLED"

        entry_after = get_league_entry(entry["id"])
        assert entry_after["status"] == "CANCELLED"
        assert entry_after["refund_status"] == "REFUNDED"

    def test_cancel_restores_wallet_and_zeroes_pool(self, api):
        """PRD §3.8: "each cancelled entry credits its `fee_paid_cents` back to
        its member's wallet and sets `refund_status` to `REFUNDED`; with no
        `CONFIRMED` entries remaining, the pool recompute leaves all three pool
        fields at 0."

        Design: Difficulty/transitive_cascade/league_cancel_two_hop_refund_cascade
        """
        league, member, entry = self._setup_open_league_with_entry(api)
        assert get_member(member["id"])["wallet_balance_cents"] == 5000

        validate_success(api.cancel_league(league["id"], LEAGUE_DIRECTOR), 200)
        # 5000 fee credited back onto the 5000 remaining balance.
        assert get_member(member["id"])["wallet_balance_cents"] == 10000
        after = get_league(league["id"])
        assert after["gross_entry_fees_cents"] == 0
        assert after["range_share_cents"] == 0
        assert after["prize_pool_cents"] == 0


class TestScorecardDisputeCorrectionCycle:
    def test_disputed_card_corrected_back_to_submitted(self, api):
        """PRD §3.8: "verify moves a `SUBMITTED` card to `VERIFIED` — gated
        cross-entity on the parent entry still being `CONFIRMED` — dispute
        returns a `VERIFIED` card to `DISPUTED` for the member to correct".
        PRD §3.8: "Correction is the member's OCC-guarded edit of §2.7: from
        `SUBMITTED` it is a self-transition edit before verification, and from
        `DISPUTED` it returns the card to `SUBMITTED`; both require the acting
        member to own the parent entry and recompute `total_points` from the new
        `ends` while incrementing the card's `version` by one."

        Design: Difficulty/non_linear_state_machine/scorecard_dispute_correction_cycle
        """
        set_clock("2026-05-01T08:00:00Z")
        league, member, entry, card = setup_closed_league_with_scorecard(
            ends=TENS, x_hits=30, league_name="Cycle Cup"
        )
        assert card["total_points"] == 300

        validate_success(api.verify_scorecard(card["id"], LEAGUE_DIRECTOR), 200)
        disputed = validate_success(
            api.dispute_scorecard(card["id"], LEAGUE_DIRECTOR), 200
        )
        assert disputed["status"] == "DISPUTED"

        corrected = validate_success(
            api.update_scorecard(
                card["id"],
                {"ends": NINES, "x_hits": 0,
                 "expected_scorecard_version": disputed["version"]},
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert corrected["status"] == "SUBMITTED", (
            "VERIFIED -> DISPUTED -> SUBMITTED cycle completed"
        )
        assert corrected["total_points"] == 270, "recomputed from corrected ends"

    def test_correction_increments_version_by_one_per_mutation(self, api):
        """PRD §3.8: "both require the acting member to own the parent entry and
        recompute `total_points` from the new `ends` while incrementing the
        card's `version` by one."
        PRD §2.4: "The `version` is an integer that starts at its initial value
        on creation and increments by one on every mutation of the resource".

        Design: Difficulty/non_linear_state_machine/scorecard_dispute_correction_cycle
        """
        set_clock("2026-05-01T08:00:00Z")
        league, member, entry, card = setup_closed_league_with_scorecard(
            ends=TENS, x_hits=30, league_name="Cycle Cup"
        )
        v0 = card["version"]
        verified = validate_success(
            api.verify_scorecard(card["id"], LEAGUE_DIRECTOR), 200
        )
        assert verified["version"] == v0 + 1
        disputed = validate_success(
            api.dispute_scorecard(card["id"], LEAGUE_DIRECTOR), 200
        )
        assert disputed["version"] == v0 + 2

        corrected = validate_success(
            api.update_scorecard(
                card["id"],
                {"ends": NINES, "x_hits": 0,
                 "expected_scorecard_version": disputed["version"]},
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert corrected["version"] == v0 + 3, (
            "submit, verify, dispute, correction: one increment per mutation"
        )


class TestStandingsInputSet:
    def test_standings_exclude_non_locked_scorecards(self, api):
        """PRD §3.8: "Standings are computed on demand over the `LOCKED`
        scorecards of `CONFIRMED` entries only, in two variants selected by the
        `variant` query parameter; the response carries the echoed `variant` and
        the ranked `rows`."

        Design: Corner/calculations/standings_exclude_non_locked_scorecards
        """
        set_clock("2026-05-01T08:00:00Z")
        league, member, entry, card = setup_closed_league_with_scorecard(
            ends=TENS, x_hits=30, league_name="Filter Cup"
        )
        # The sole card stays SUBMITTED (never verified/locked).
        standings = validate_success(
            api.get_standings(league["id"], LEAGUE_DIRECTOR), 200
        )
        assert standings["rows"] == [], (
            "SUBMITTED cards are outside the standings input set"
        )


class TestScorecardEditGates:
    def test_scorecard_put_from_verified_rejected(self, api):
        """PRD §3.8: "Editing a card in `VERIFIED` or `LOCKED` is rejected with
        `ERR_SCORECARD_NOT_EDITABLE`."
        PRD §2.7: "A scorecard correction — the edit/correction capability on an
        existing scorecard — must carry `expected_scorecard_version` holding the
        client's last observed `version` of that scorecard."

        Design: Corner/state_machines/scorecard_put_from_verified_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        league, member, entry, card = setup_closed_league_with_scorecard(
            ends=TENS, x_hits=30, league_name="Edit Cup"
        )
        verified = validate_success(
            api.verify_scorecard(card["id"], LEAGUE_DIRECTOR), 200
        )

        # Even carrying the correct current version, VERIFIED is not editable.
        resp = api.update_scorecard(
            card["id"],
            {"ends": NINES, "x_hits": 0,
             "expected_scorecard_version": verified["version"]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCORECARD_NOT_EDITABLE)
        after = get_scorecard_via_list(entry["id"], card["id"])
        assert after["status"] == "VERIFIED"
        assert after["total_points"] == 300


class TestLeagueEntryUniqueness:
    def test_duplicate_league_entry_rejected(self, api):
        """PRD §3.8: "the entrant — recorded from the caller's identity, with
        the league recorded as the entry's `league_id` — must be active and
        waivered, may hold only one entry per league
        (`ERR_DUPLICATE_LEAGUE_ENTRY`)".

        Design: Corner/validations/duplicate_league_entry_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        league, members, entries = setup_league_with_entries(
            1, entry_fee_cents=5000, wallet_cents=10000, league_name="Dup Cup"
        )
        member = members[0]

        resp = api.enter_league(league["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LEAGUE_ENTRY)
        # The member was charged exactly once.
        assert get_member(member["id"])["wallet_balance_cents"] == 5000


class TestScorecardOcc:
    def test_occ_stale_scorecard_version_rejected(self, api):
        """PRD §2.7: "If another writer has advanced the card's version since
        the client last read it, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412): the newer edit legitimately supersedes the prior content
        under the correction-cycle rules of §3.8, and the stale writer must
        re-read the card before editing."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_scorecard_version_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        league, member, entry, card = setup_closed_league_with_scorecard(
            ends=TENS, x_hits=30, league_name="OCC Cup"
        )
        stale_version = card["version"]

        first = validate_success(
            api.update_scorecard(
                card["id"],
                {"ends": NINES, "x_hits": 0,
                 "expected_scorecard_version": stale_version},
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert first["total_points"] == 270
        assert first["version"] == stale_version + 1

        # Replaying the same captured version is now stale.
        resp = api.update_scorecard(
            card["id"],
            {"ends": EIGHTS, "x_hits": 0,
             "expected_scorecard_version": stale_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_scorecard_via_list(entry["id"], card["id"])
        assert after["total_points"] == 270, "stale write must not mutate"
        assert after["version"] == stale_version + 1
