"""Reversals that must land exactly back on the ledger they left.

Three inverse operations are exercised: rescinding an accepted pick trade and
proving both clubs' negotiating capital and the cycle's pick inventory return
to their pre-acceptance figures, voiding a signed rookie contract and proving
the club's rookie pool is restored to the cent, and revoking the only granted
medical record share and proving the evaluation's share counter returns to zero
and seals the file.
"""

from typing import Dict

from test_helpers import (
    ADMIN,
    assert_cents_equal,
    assert_chart_points,
    assert_prospect_dimensions,
    accept_trade,
    build_medical_evaluation,
    build_order_final,
    build_signed_drafted_contract,
    contract_status_payload,
    decide_share,
    grant_consent,
    make_club_gm_headers,
    propose_trade,
    read_club,
    read_contract,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    read_share,
    request_share,
    share_decision_payload,
    trade_termination_payload,
    validate_success,
)

CONSENT_UNTIL = "2027-06-30T00:00:00.000Z"
SHARE_EXPIRES_AT = "2027-04-25T18:00:00.000Z"

RESCIND_REASON = "League review reversed the transaction"
REVOKE_REASON = "Club withdrew its evaluation request"

# Pre-trade chart ledger of the canonical two-club, two-round cycle.
ELM_CAPITAL_BEFORE = 1420.0
HAR_CAPITAL_BEFORE = 1334.8
ELM_CAPITAL_AFTER_SWAP = 1360.0
HAR_CAPITAL_AFTER_SWAP = 1394.8
CYCLE_INVENTORY_POINTS = 2754.8
CYCLE_INVENTORY_COUNT = 4
SWAP_CHART_BALANCE = -60.0

# Slotted money for overall pick one of round one.
FIRST_YEAR_CAP_CHARGE_CENTS = 196721432
ELM_POOL_TOTAL_CENTS = 896721432
ELM_POOL_AFTER_SIGNING_CENTS = 700000000


# ---------------------------------------------------------------------------
# Local scenario compositions
# ---------------------------------------------------------------------------


def _proposed_pick_swap(api) -> Dict:
    """ORDER_FINAL with ELM offering overall one for HAR's overall two."""
    state = build_order_final(api)
    state["trade"] = propose_trade(
        api,
        state["cycle"],
        state["clubs"]["ELM"],
        state["clubs"]["HAR"],
        [state["pick"]["r1p1"]],
        [state["pick"]["r1p2"]],
    )
    return state


def _rescind(api, trade: Dict):
    return api.terminate_pick_trade(
        trade["id"],
        trade_termination_payload("RESCIND", reason=RESCIND_REASON),
        ADMIN,
    )


def _void(api, contract: Dict, club: Dict):
    return api.set_contract_status(
        contract["id"],
        contract_status_payload("VOID"),
        make_club_gm_headers(club["id"]),
    )


def _granted_full_share(api) -> Dict:
    """A FULL share granted to ELM's medical director over a PASS evaluation."""
    state = build_medical_evaluation(api)
    state["prospect"] = grant_consent(
        api, state["prospect"], scope="FULL", consent_expires_at=CONSENT_UNTIL
    )
    share = request_share(
        api,
        state["evaluation"],
        state["clubs"]["ELM"],
        scope="FULL",
        as_medical_director=True,
    )
    state["share"] = decide_share(api, share, "GRANT")
    state["evaluation"] = read_evaluation(api, state["evaluation"]["id"])
    return state


def _revoke(api, share: Dict):
    return api.decide_medical_record_share(
        share["id"],
        share_decision_payload("REVOKE", denial_reason=REVOKE_REASON),
        ADMIN,
    )


# ---------------------------------------------------------------------------
# Rescinding an accepted trade
# ---------------------------------------------------------------------------


class TestTradeRescission:
    def test_rescission_returns_each_traded_pick_to_its_previous_owner(self, api):
        """Both picks go back to the club that held them before acceptance.

        "Rescission is a true compensating action: it restores `owning_club_id`
        on every traded pick to its pre-acceptance owner, recomputes
        `draft_capital_points` and `trade_authorization_tier` for both clubs,
        and sets `conditional_status` to `VOID` if it was `OPEN`."

        Design: Difficulty/compensating_invariant/trade_rescind_restores_both_capital_ledgers_with_no_inventory_drift
        """
        state = _proposed_pick_swap(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        offered, requested = state["pick"]["r1p1"], state["pick"]["r1p2"]
        accept_trade(api, state["trade"], har)

        trade = validate_success(_rescind(api, state["trade"]))

        assert trade["status"] == "RESCINDED"
        assert_chart_points(trade["chart_balance_points"], SWAP_CHART_BALANCE)

        restored_offered = read_pick(api, offered["id"])
        restored_requested = read_pick(api, requested["id"])
        assert restored_offered["owning_club_id"] == elm["id"]
        assert restored_requested["owning_club_id"] == har["id"]
        assert restored_offered["original_club_id"] == elm["id"]
        assert restored_requested["original_club_id"] == har["id"]

    def test_rescission_restores_both_clubs_negotiating_capital(self, api):
        """Capital swings on acceptance and swings all the way back on rescission.

        "`draft_capital_points` is the sum of `chart_value_points` over the
        picks whose `owning_club_id` is that club and whose `status` is
        `PENDING` or `ON_CLOCK`, carried to one decimal place; picks that are
        `USED`, `PASSED`, `FORFEITED` or `LAPSED` contribute nothing."

        "Rescission is a true compensating action: it restores `owning_club_id`
        on every traded pick to its pre-acceptance owner, recomputes
        `draft_capital_points` and `trade_authorization_tier` for both clubs,
        and sets `conditional_status` to `VOID` if it was `OPEN`."

        Design: Difficulty/compensating_invariant/trade_rescind_restores_both_capital_ledgers_with_no_inventory_drift
        """
        state = _proposed_pick_swap(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]

        assert_chart_points(
            read_club(api, elm["id"])["draft_capital_points"], ELM_CAPITAL_BEFORE
        )
        assert_chart_points(
            read_club(api, har["id"])["draft_capital_points"], HAR_CAPITAL_BEFORE
        )

        accept_trade(api, state["trade"], har)
        assert_chart_points(
            read_club(api, elm["id"])["draft_capital_points"], ELM_CAPITAL_AFTER_SWAP
        )
        assert_chart_points(
            read_club(api, har["id"])["draft_capital_points"], HAR_CAPITAL_AFTER_SWAP
        )

        validate_success(_rescind(api, state["trade"]))

        elm_after = read_club(api, elm["id"])
        har_after = read_club(api, har["id"])
        assert_chart_points(elm_after["draft_capital_points"], ELM_CAPITAL_BEFORE)
        assert_chart_points(har_after["draft_capital_points"], HAR_CAPITAL_BEFORE)
        assert elm_after["trade_authorization_tier"] == "FULL"
        assert har_after["trade_authorization_tier"] == "FULL"

    def test_rescission_leaves_the_cycle_pick_inventory_undisturbed(self, api):
        """Ownership moves but no chart points are minted or burned.

        "Rescinding an accepted trade restores every traded pick's
        `owning_club_id` to its pre-acceptance owner, so a cycle's
        `pick_inventory_chart_points` is numerically identical before the
        acceptance and after the rescission."

        Design: Difficulty/compensating_invariant/trade_rescind_restores_both_capital_ledgers_with_no_inventory_drift
        """
        state = _proposed_pick_swap(api)
        cycle_id = state["cycle"]["id"]

        before = read_cycle(api, cycle_id)
        assert_chart_points(
            before["pick_inventory_chart_points"], CYCLE_INVENTORY_POINTS
        )
        assert before["pick_inventory_count"] == CYCLE_INVENTORY_COUNT

        accept_trade(api, state["trade"], state["clubs"]["HAR"])
        validate_success(_rescind(api, state["trade"]))

        after = read_cycle(api, cycle_id)
        assert_chart_points(
            after["pick_inventory_chart_points"], CYCLE_INVENTORY_POINTS
        )
        assert after["pick_inventory_count"] == CYCLE_INVENTORY_COUNT


# ---------------------------------------------------------------------------
# Voiding a signed rookie contract
# ---------------------------------------------------------------------------


class TestSignedContractVoid:
    def test_voiding_a_signed_contract_restores_the_rookie_pool_exactly(self, api):
        """The pool gives back precisely the first-year charge it absorbed.

        "Voiding a signed contract restores the club's
        `rookie_pool_remaining_cents` to its pre-signing value, so that at every
        instant a club's `rookie_pool_remaining_cents` plus the sum of
        first-year charges on its signed contracts equals its
        `rookie_pool_total_cents`."

        Design: Difficulty/compensating_invariant/voiding_a_signed_rookie_contract_restores_the_rookie_pool_exactly
        """
        state = build_signed_drafted_contract(api)
        elm = state["clubs"]["ELM"]
        contract = state["contract"]

        assert_cents_equal(
            contract["first_year_cap_charge_cents"], FIRST_YEAR_CAP_CHARGE_CENTS
        )
        assert_cents_equal(
            read_club(api, elm["id"])["rookie_pool_remaining_cents"],
            ELM_POOL_AFTER_SIGNING_CENTS,
        )

        voided = validate_success(_void(api, contract, elm))
        assert voided["status"] == "VOIDED"
        assert_cents_equal(
            voided["first_year_cap_charge_cents"], FIRST_YEAR_CAP_CHARGE_CENTS
        )

        elm_after = read_club(api, elm["id"])
        assert_cents_equal(
            elm_after["rookie_pool_remaining_cents"], ELM_POOL_TOTAL_CENTS
        )
        assert_cents_equal(elm_after["rookie_pool_total_cents"], ELM_POOL_TOTAL_CENTS)

    def test_voided_contract_leaves_the_draft_record_standing(self, api):
        """Only the signing dimension reverses; the selection itself survives.

        "From `SIGNED` it also moves the contract to `VOIDED` and returns
        `signing_status` to `UNSIGNED`, and additionally restores the club's
        `rookie_pool_remaining_cents` to its pre-signing value."

        Design: Difficulty/compensating_invariant/voiding_a_signed_rookie_contract_restores_the_rookie_pool_exactly
        """
        state = build_signed_drafted_contract(api)
        elm = state["clubs"]["ELM"]
        pick_id = state["used_pick"]["id"]

        _void(api, state["contract"], elm)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert_prospect_dimensions(
            prospect, signing_status="UNSIGNED", drafted_pick_overall_number=1
        )

        used = read_pick(api, pick_id)
        assert used["status"] == "USED"
        assert used["selected_prospect_id"] == prospect["id"]

        assert read_contract(api, state["contract"]["id"])["status"] == "VOIDED"


# ---------------------------------------------------------------------------
# Revoking the only granted medical record share
# ---------------------------------------------------------------------------


class TestShareRevocationSealsTheEvaluation:
    def test_granting_the_share_raises_the_counter_and_caps_the_window(self, api):
        """The share opens at one and expires at the tightest of the three caps.

        "Whichever of those three instants comes first becomes the share's
        `expires_at`; the tightest cap always wins, so a consent that lapses a
        week after the combine ends overrides both league caps."

        "The share's `effective_access` reports what the club can actually read
        right now: it equals the share's `scope` — `SUMMARY` or `FULL` — while
        `status` is `GRANTED` and the current logical instant is strictly before
        `expires_at`, and it is `NONE` in every other case, including at the
        exact `expires_at` instant."

        Design: Difficulty/compensating_invariant/revoking_the_last_share_returns_the_evaluation_counter_to_zero_and_seals_it
        """
        state = _granted_full_share(api)

        share = read_share(api, state["share"]["id"])
        assert share["status"] == "GRANTED"
        assert share["effective_access"] == "FULL"
        assert share["expires_at"] == SHARE_EXPIRES_AT

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 1
        assert evaluation["disclosure_state"] == "DISCLOSABLE"

    def test_revoking_the_last_share_returns_the_counter_to_zero_and_seals(self, api):
        """The counter comes back to zero and the evaluation is sealed.

        "`REVOKE` advances `GRANTED` to `REVOKED`, requires `denial_reason` to
        be present when it is invoked directly rather than reached by the
        consent cascade, decrements the evaluation's `active_share_count` by
        one, and — when that count reaches 0 — sets the evaluation's
        `disclosure_state` to `SEALED`."

        Design: Difficulty/compensating_invariant/revoking_the_last_share_returns_the_evaluation_counter_to_zero_and_seals_it
        """
        state = _granted_full_share(api)

        revoked = validate_success(_revoke(api, state["share"]))

        assert revoked["status"] == "REVOKED"
        assert revoked["effective_access"] == "NONE"
        assert revoked["expires_at"] == SHARE_EXPIRES_AT

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "SEALED"

    def test_revoking_a_share_leaves_the_prospect_consent_intact(self, api):
        """Sealing the file does not touch the consent the agent granted.

        "`REVOKE` advances `GRANTED` to `REVOKED`, requires `denial_reason` to
        be present when it is invoked directly rather than reached by the
        consent cascade, decrements the evaluation's `active_share_count` by
        one, and — when that count reaches 0 — sets the evaluation's
        `disclosure_state` to `SEALED`."

        Design: Difficulty/compensating_invariant/revoking_the_last_share_returns_the_evaluation_counter_to_zero_and_seals_it
        """
        state = _granted_full_share(api)

        _revoke(api, state["share"])

        prospect = read_prospect(api, state["prospect"]["id"])
        assert_prospect_dimensions(
            prospect, consent_status="GRANTED", consent_scope="FULL"
        )
        assert prospect["consent_expires_at"] == CONSENT_UNTIL
