"""Behaviour exactly at the instants and thresholds the contract pins down.

Three boundaries are exercised at millisecond and last-decimal resolution: the
selection clock, which is still running one millisecond before its deadline and
expired at the deadline itself, with the successor's clock pinned to the expired
pick's deadline rather than to the call instant; the trade imbalance tolerance,
which is inclusive, so a package landing on exactly 0.1500 must be acceptable;
and the compensatory qualifying score, which is inclusive at 250.00 while a
claim one tenth of a unit lower is not qualifying.
"""

from typing import Dict

from test_helpers import (
    ADMIN,
    ERR_TRADE_VALUE_IMBALANCED,
    ApiClient,
    assert_chart_points,
    assert_imbalance_ratio,
    assert_score,
    build_draft_live_on_clock,
    compensatory_claim_payload,
    make_club_gm_headers,
    propose_trade,
    read_club,
    read_cycle,
    read_pick,
    read_trade,
    set_clock,
    validate_error,
    validate_success,
)

ON_CLOCK_STARTED_AT = "2027-04-22T18:00:00.000Z"
ONE_MS_BEFORE_DEADLINE = "2027-04-22T18:09:59.999Z"
PICK_ONE_DEADLINE = "2027-04-22T18:10:00.000Z"
PICK_TWO_DEADLINE = "2027-04-22T18:20:00.000Z"


# ---------------------------------------------------------------------------
# Scenario composition
# ---------------------------------------------------------------------------


def _advance(api: ApiClient, cycle_id: str) -> Dict:
    response = api.advance_selection_clock(cycle_id, None, ADMIN)
    return validate_success(response, expected_status=200)


def _clock_at_the_deadline_after_an_early_no_op(api: ApiClient) -> Dict:
    """Overall pick 1 on the clock, one harmless early advance behind us."""
    state = build_draft_live_on_clock(api)
    set_clock(api, ONE_MS_BEFORE_DEADLINE)
    state["early_advance"] = _advance(api, state["cycle"]["id"])
    set_clock(api, PICK_ONE_DEADLINE)
    return state


def _propose(api: ApiClient, state: Dict, offered_keys, requested_keys) -> Dict:
    return propose_trade(
        api,
        state["cycle"],
        state["clubs"]["ELM"],
        state["clubs"]["HAR"],
        [state["pick"][key] for key in offered_keys],
        [state["pick"][key] for key in requested_keys],
    )


def _accept_as_receiving_club(api: ApiClient, state: Dict, trade: Dict):
    return api.accept_pick_trade(
        trade["id"], None, make_club_gm_headers(state["clubs"]["HAR"]["id"])
    )


def _file_claim(api: ApiClient, state: Dict, player_name: str, apy_cents: int) -> Dict:
    club = state["clubs"]["ELM"]
    response = api.create_compensatory_claim(
        compensatory_claim_payload(
            state["cycle"]["id"],
            club["id"],
            claim_type="DEPARTURE",
            player_name=player_name,
            departed_apy_cents=apy_cents,
            snap_pct=0.70,
            postseason_honor="NONE",
        ),
        make_club_gm_headers(club["id"]),
    )
    return validate_success(response, expected_status=201)


# ---------------------------------------------------------------------------
# The selection clock deadline instant
# ---------------------------------------------------------------------------


class TestSelectionClockDeadlineInstant:
    """Expiry is inclusive at the deadline and the cascade re-anchors on it."""

    def test_advance_one_millisecond_before_the_deadline_passes_nothing(
        self, api: ApiClient
    ) -> None:
        """At 18:09:59.999Z the clock is still running and nothing moves.

        PRD: "A pick's clock is expired when the current logical instant is at or after `deadline_at`, and a timeout may only be spent while the current logical instant is strictly before `deadline_at`."

        Design: Difficulty/boundary_precision_check/selection_clock_expires_at_the_deadline_instant_not_one_millisecond_before
        """
        state = build_draft_live_on_clock(api)
        set_clock(api, ONE_MS_BEFORE_DEADLINE)

        result = _advance(api, state["cycle"]["id"])
        assert result["passed_count"] == 0
        assert result["lapsed_count"] == 0

        first = read_pick(api, state["pick"]["r1p1"]["id"])
        assert first["status"] == "ON_CLOCK"
        assert first["on_clock_started_at"] == ON_CLOCK_STARTED_AT
        assert first["deadline_at"] == PICK_ONE_DEADLINE
        assert read_pick(api, state["pick"]["r1p2"]["id"])["status"] == "PENDING"

    def test_advance_at_the_deadline_instant_expires_the_pick_on_the_clock(
        self, api: ApiClient
    ) -> None:
        """At exactly 18:10:00.000Z overall pick 1 is passed as EXPIRED.

        PRD: "When the clock advance finds an expired pick, that pick moves from `ON_CLOCK` to `PASSED` with `pass_reason` set to `EXPIRED`, and the `PENDING` pick with the next-lowest `overall_number` is put on the clock — but with `on_clock_started_at` set to the *expired pick's* `deadline_at`, not to the current instant."

        Design: Difficulty/boundary_precision_check/selection_clock_expires_at_the_deadline_instant_not_one_millisecond_before
        """
        state = _clock_at_the_deadline_after_an_early_no_op(api)
        assert state["early_advance"]["passed_count"] == 0

        result = _advance(api, state["cycle"]["id"])
        assert result["passed_count"] == 1
        assert result["lapsed_count"] == 0
        assert result["expired_pick_id"] == state["pick"]["r1p1"]["id"]
        assert result["on_clock_pick_id"] == state["pick"]["r1p2"]["id"]

        expired = read_pick(api, state["pick"]["r1p1"]["id"])
        assert expired["status"] == "PASSED"
        assert expired["pass_reason"] == "EXPIRED"
        assert expired["deadline_at"] == PICK_ONE_DEADLINE

    def test_successor_clock_starts_at_the_expired_deadline_not_the_call_instant(
        self, api: ApiClient
    ) -> None:
        """Overall pick 2 starts at 18:10:00.000Z and runs ten minutes to 18:20.

        PRD: "The allotted minutes are 10 for round one, 7 for round two, 5 for rounds three, four, five and six, and 4 for round seven."

        Design: Difficulty/boundary_precision_check/selection_clock_expires_at_the_deadline_instant_not_one_millisecond_before
        """
        state = _clock_at_the_deadline_after_an_early_no_op(api)

        _advance(api, state["cycle"]["id"])

        successor = read_pick(api, state["pick"]["r1p2"]["id"])
        assert successor["status"] == "ON_CLOCK"
        assert successor["on_clock_started_at"] == PICK_ONE_DEADLINE
        assert successor["deadline_at"] == PICK_TWO_DEADLINE
        assert read_cycle(api, state["cycle"]["id"])["status"] == "DRAFT_LIVE"


# ---------------------------------------------------------------------------
# The trade imbalance tolerance
# ---------------------------------------------------------------------------


class TestTradeImbalanceTolerance:
    """A package landing on exactly 0.1500 is inside the inclusive tolerance."""

    def test_ratio_of_exactly_one_five_zero_zero_is_accepted(
        self, api: ApiClient, seven_round_order_final: Dict
    ) -> None:
        """470.0 out against 399.5 in gives -70.5 and 0.1500, so accept succeeds.

        PRD: "Acceptance is allowed only when `imbalance_ratio` is at most 0.15, inclusive at that boundary; a wider gap is refused with `ERR_TRADE_VALUE_IMBALANCED`."

        Design: Difficulty/boundary_precision_check/trade_imbalance_ratio_exactly_at_tolerance_is_accepted
        """
        state = seven_round_order_final
        trade = _propose(
            api, state, ["r2p1", "r6p1"], ["r3p2", "r4p2", "r7p2"]
        )
        assert_chart_points(trade["chart_balance_points"], -70.5)
        assert_imbalance_ratio(trade["imbalance_ratio"], 0.1500)

        accepted = validate_success(
            _accept_as_receiving_club(api, state, trade), expected_status=200
        )
        assert accepted["status"] == "ACCEPTED"
        assert_chart_points(accepted["chart_balance_points"], -70.5)
        assert_imbalance_ratio(accepted["imbalance_ratio"], 0.1500)

    def test_boundary_acceptance_swaps_ownership_and_recomputes_both_capitals(
        self, api: ApiClient, seven_round_order_final: Dict
    ) -> None:
        """ELM settles at 1914.5 and HAR at 1936.4 with inventory untouched.

        PRD: "On success the trade moves to `ACCEPTED`, `owning_club_id` is swapped on every offered and every requested pick, and `draft_capital_points` and `trade_authorization_tier` are recomputed for both clubs."

        Design: Difficulty/boundary_precision_check/trade_imbalance_ratio_exactly_at_tolerance_is_accepted
        """
        state = seven_round_order_final
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        trade = _propose(
            api, state, ["r2p1", "r6p1"], ["r3p2", "r4p2", "r7p2"]
        )

        validate_success(
            _accept_as_receiving_club(api, state, trade), expected_status=200
        )

        for key in ("r2p1", "r6p1"):
            assert read_pick(api, state["pick"][key]["id"])["owning_club_id"] == har["id"]
        for key in ("r3p2", "r4p2", "r7p2"):
            assert read_pick(api, state["pick"][key]["id"])["owning_club_id"] == elm["id"]

        assert_chart_points(read_club(api, elm["id"])["draft_capital_points"], 1914.5)
        assert_chart_points(read_club(api, har["id"])["draft_capital_points"], 1936.4)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert_chart_points(cycle["pick_inventory_chart_points"], 3850.9)
        assert cycle["pick_inventory_count"] == 14

    def test_ratio_above_the_tolerance_is_refused_and_leaves_ownership_alone(
        self, api: ApiClient, seven_round_order_final: Dict
    ) -> None:
        """670.0 out against 559.3 in gives 0.1652, just past the tolerance.

        PRD: "The `imbalance_ratio` is the absolute value of `chart_balance_points` divided by the largest of the incoming total, the outgoing total and 1.0, rounded half up to four decimal places; the 1.0 floor keeps the ratio well defined when both sides are worthless."

        Design: Difficulty/boundary_precision_check/trade_imbalance_ratio_exactly_at_tolerance_is_accepted
        """
        state = seven_round_order_final
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        trade = _propose(
            api, state, ["r2p1", "r3p1"], ["r2p2", "r4p2", "r7p2"]
        )
        assert_chart_points(trade["chart_balance_points"], -110.7)
        assert_imbalance_ratio(trade["imbalance_ratio"], 0.1652)

        response = _accept_as_receiving_club(api, state, trade)
        validate_error(response, ERR_TRADE_VALUE_IMBALANCED, expected_status=422)

        assert read_trade(api, trade["id"])["status"] == "PROPOSED"
        assert read_pick(api, state["pick"]["r2p1"]["id"])["owning_club_id"] == elm["id"]
        assert read_pick(api, state["pick"]["r2p2"]["id"])["owning_club_id"] == har["id"]


# ---------------------------------------------------------------------------
# The compensatory qualifying score
# ---------------------------------------------------------------------------


class TestCompensatoryQualifyingScore:
    """250.00 qualifies, 249.90 does not, and the advisory figure decides nothing."""

    def test_score_of_exactly_two_hundred_fifty_qualifies(
        self, api: ApiClient, cycle_with_two_clubs: Dict
    ) -> None:
        """250,000,000 cents at a 0.70 share scores 250.00 and qualifies.

        PRD: "The `qualifies` flag is true when `claim_score` is at least 250.00, inclusive at that boundary."

        Design: Difficulty/boundary_precision_check/compensatory_claim_score_exactly_at_qualify_minimum_qualifies
        """
        claim = _file_claim(api, cycle_with_two_clubs, "Mason Reed", 250000000)

        assert_score(claim["claim_score"], 250.00)
        assert claim["qualifies"] is True
        assert claim["status"] == "SUBMITTED"

    def test_score_one_tenth_below_the_minimum_does_not_qualify(
        self, api: ApiClient, cycle_with_two_clubs: Dict
    ) -> None:
        """249,900,000 cents at the same share scores 249.90 and falls short.

        PRD: "The `claim_score` is the base figure multiplied by the banded snap factor, plus the honours bonus, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/compensatory_claim_score_exactly_at_qualify_minimum_qualifies
        """
        claim = _file_claim(api, cycle_with_two_clubs, "Nolan Frey", 249900000)

        assert_score(claim["claim_score"], 249.90)
        assert claim["qualifies"] is False
        assert claim["status"] == "SUBMITTED"
        assert claim["awarded_round"] == 0

    def test_advisory_score_uses_the_raw_share_and_never_drives_qualification(
        self, api: ApiClient, cycle_with_two_clubs: Dict
    ) -> None:
        """The advisory figures read 175.00 and 174.93, both under the minimum.

        PRD: "`advisory_snap_adjusted_score` is the same base figure multiplied by the *raw* `snap_pct` rather than by the band, plus the same honours bonus, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/compensatory_claim_score_exactly_at_qualify_minimum_qualifies
        """
        at_minimum = _file_claim(api, cycle_with_two_clubs, "Mason Reed", 250000000)
        below_minimum = _file_claim(api, cycle_with_two_clubs, "Nolan Frey", 249900000)

        assert_score(at_minimum["advisory_snap_adjusted_score"], 175.00)
        assert_score(below_minimum["advisory_snap_adjusted_score"], 174.93)
        assert at_minimum["qualifies"] is True
        assert below_minimum["qualifies"] is False
