"""Multi-hop cascades fired by a single league or agent action.

Two chains are covered. A league forfeit of a pending pick walks from the pick
to its owner's negotiating capital, from the capital to the owner's trade
authorization tier, from the tier to that owner's open proposals and their
independent conditional dimension, and finally to the cycle's pick inventory
ledger. A prospect's consent revocation walks from the consent dimension to the
granted medical record share, from the share to its evaluation's share count and
disclosure state, from there to the prospect's medical clearance, and from the
clearance to the outstanding rookie contract offer.
"""

from typing import Dict

from test_helpers import (
    ADMIN,
    DRAFT_START_AT,
    ApiClient,
    advance_clock,
    assert_chart_points,
    build_draft_live,
    build_medical_evaluation,
    clock_action_payload,
    consent_payload,
    decide_share,
    finalize_order,
    grant_consent,
    list_picks,
    make_prospect_agent_headers,
    make_selection,
    move_phase,
    offer_drafted_contract,
    pick_index,
    propose_trade,
    read_club,
    read_contract,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    read_share,
    read_trade,
    request_share,
    rule_prospect_eligible,
    run_lottery,
    set_clock,
    validate_success,
)

CONSENT_EXPIRES_AT = "2027-06-30T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Scenario composition
# ---------------------------------------------------------------------------


def _live_draft_with_har_proposal(api: ApiClient) -> Dict:
    """DRAFT_LIVE, all four picks PENDING, HAR holding an open conditional offer.

    Chart ledger: overall 1 = 1000.0 (ELM), overall 2 = 940.0 (HAR),
    overall 3 = 420.0 (ELM), overall 4 = 394.8 (HAR); ELM capital 1420.0 and
    HAR capital 1334.8, so both clubs open at FULL.
    """
    state = build_draft_live(api)
    state["trade"] = propose_trade(
        api,
        state["cycle"],
        state["clubs"]["HAR"],
        state["clubs"]["ELM"],
        [state["pick"]["r2p2"]],
        [state["pick"]["r2p1"]],
        conditional_round_number=2,
        conditional_condition_code="PLAYOFF_BERTH",
    )
    return state


def _forfeit_hars_first_round_pick(api: ApiClient, state: Dict) -> Dict:
    response = api.act_on_pick_clock(
        state["pick"]["r1p2"]["id"], clock_action_payload("FORFEIT"), ADMIN
    )
    return validate_success(response, expected_status=200)


def _drafted_prospect_with_granted_share(api: ApiClient) -> Dict:
    """A CLEARED, drafted prospect whose file ELM holds under a granted share.

    Consent is granted with scope FULL through 2027-06-30, so the share's
    expires_at settles on the draft-start-plus-three-days cap of
    2027-04-25T18:00:00.000Z and survives the move to draft day.
    """
    state = build_medical_evaluation(api)
    state["prospect"] = grant_consent(
        api,
        state["prospect"],
        scope="FULL",
        consent_expires_at=CONSENT_EXPIRES_AT,
    )
    elm = state["clubs"]["ELM"]
    share = request_share(
        api, state["evaluation"], elm, scope="FULL", as_medical_director=True
    )
    state["share"] = decide_share(api, share, "GRANT")
    state["evaluation"] = read_evaluation(api, state["evaluation"]["id"])

    state["prospect"] = rule_prospect_eligible(api, state["prospect"])
    state["cycle"] = move_phase(api, state["cycle"]["id"], "ORDER_PENDING")
    state["cycle"] = run_lottery(api, state["cycle"]["id"])
    finalize_order(api, state["cycle"]["id"])
    state["picks"] = list_picks(api, state["cycle"]["id"])
    state["pick"] = pick_index(state["picks"])

    set_clock(api, DRAFT_START_AT)
    state["cycle"] = move_phase(api, state["cycle"]["id"], "DRAFT_LIVE")
    advance_clock(api, state["cycle"]["id"])
    state["used_pick"] = make_selection(
        api, state["pick"]["r1p1"], state["prospect"], elm
    )
    state["contract"] = offer_drafted_contract(
        api, state["prospect"], elm, state["used_pick"]
    )
    state["prospect"] = read_prospect(api, state["prospect"]["id"])
    return state


def _revoke_consent(api: ApiClient, state: Dict) -> Dict:
    prospect_id = state["prospect"]["id"]
    response = api.act_on_prospect_consent(
        prospect_id,
        consent_payload("REVOKE", scope=None, consent_expires_at=None),
        make_prospect_agent_headers(prospect_id),
    )
    return validate_success(response, expected_status=200)


# ---------------------------------------------------------------------------
# Forfeit cascade
# ---------------------------------------------------------------------------


class TestForfeitCascade:
    """One league FORFEIT propagates through club, trade and cycle ledgers."""

    def test_forfeit_zeroes_the_pick_and_records_the_round_on_its_original_club(
        self, api: ApiClient
    ) -> None:
        """The addressed pick lands in FORFEITED at 0.0 chart points.

        PRD: "That single action has five effects: the pick's `chart_value_points` is set to 0.0; its `round_number` is appended to the `forfeited_round_numbers` of the club named by `original_club_id`; the owning club's `draft_capital_points` and `trade_authorization_tier` are recomputed; every `PickTrade` of the owning club still in `PROPOSED` or `COUNTERED` becomes `VOIDED_BY_CAPITAL` if that recomputation drops the tier to `SUSPENDED`; and the cycle's `pick_inventory_chart_points` and `pick_inventory_count` are recomputed."

        Design: Difficulty/transitive_cascade/forfeit_drops_capital_then_suspends_tier_then_voids_trade_then_kills_conditional
        """
        state = _live_draft_with_har_proposal(api)
        har = state["clubs"]["HAR"]

        _forfeit_hars_first_round_pick(api, state)

        forfeited = read_pick(api, state["pick"]["r1p2"]["id"])
        assert forfeited["status"] == "FORFEITED"
        assert_chart_points(forfeited["chart_value_points"], 0.0)
        assert read_club(api, har["id"])["forfeited_round_numbers"] == [1]

    def test_forfeit_drops_owner_capital_to_394_8_and_suspends_its_tier(
        self, api: ApiClient
    ) -> None:
        """HAR's capital falls 1334.8 -> 394.8, which is below the 900.0 floor.

        PRD: "From that figure the club's `trade_authorization_tier` is derived on every read: it is `FULL` when `draft_capital_points` is at least 1200.0, `LIMITED` when it is at least 900.0 but below 1200.0, and `SUSPENDED` when it is below 900.0."

        Design: Difficulty/transitive_cascade/forfeit_drops_capital_then_suspends_tier_then_voids_trade_then_kills_conditional
        """
        state = _live_draft_with_har_proposal(api)
        har = state["clubs"]["HAR"]
        assert_chart_points(read_club(api, har["id"])["draft_capital_points"], 1334.8)

        _forfeit_hars_first_round_pick(api, state)

        after = read_club(api, har["id"])
        assert_chart_points(after["draft_capital_points"], 394.8)
        assert after["trade_authorization_tier"] == "SUSPENDED"

    def test_suspended_tier_voids_the_open_proposal_and_its_conditional_dimension(
        self, api: ApiClient
    ) -> None:
        """HAR's untouched PROPOSED trade dies with its OPEN condition.

        PRD: "When a forfeit drops either party club's `trade_authorization_tier` to `SUSPENDED`, every trade of that club still in `PROPOSED` moves to `VOIDED_BY_CAPITAL`, and so does every trade of that club still in `COUNTERED`; on both paths, if the trade's `conditional_status` was `OPEN`, it becomes `VOID`."

        Design: Difficulty/transitive_cascade/forfeit_drops_capital_then_suspends_tier_then_voids_trade_then_kills_conditional
        """
        state = _live_draft_with_har_proposal(api)
        opened = read_trade(api, state["trade"]["id"])
        assert opened["status"] == "PROPOSED"
        assert opened["conditional_status"] == "OPEN"

        _forfeit_hars_first_round_pick(api, state)

        voided = read_trade(api, state["trade"]["id"])
        assert voided["status"] == "VOIDED_BY_CAPITAL"
        assert voided["conditional_status"] == "VOID"
        assert voided["conditional_probability_tier"] == "LIKELY"

    def test_forfeit_recomputes_cycle_inventory_and_spares_the_counterparty(
        self, api: ApiClient
    ) -> None:
        """Inventory drops 2754.8 -> 1814.8 over three picks; ELM keeps 1420.0.

        PRD: "`pick_inventory_count` is the number of picks belonging to the cycle whose `status` is anything other than `FORFEITED`, and `pick_inventory_chart_points` is the sum of `chart_value_points` over that same set, carried to one decimal place."

        Design: Difficulty/transitive_cascade/forfeit_drops_capital_then_suspends_tier_then_voids_trade_then_kills_conditional
        """
        state = _live_draft_with_har_proposal(api)
        elm = state["clubs"]["ELM"]
        before = read_cycle(api, state["cycle"]["id"])
        assert_chart_points(before["pick_inventory_chart_points"], 2754.8)
        assert before["pick_inventory_count"] == 4

        _forfeit_hars_first_round_pick(api, state)

        after = read_cycle(api, state["cycle"]["id"])
        assert_chart_points(after["pick_inventory_chart_points"], 1814.8)
        assert after["pick_inventory_count"] == 3

        counterparty = read_club(api, elm["id"])
        assert_chart_points(counterparty["draft_capital_points"], 1420.0)
        assert counterparty["trade_authorization_tier"] == "FULL"


# ---------------------------------------------------------------------------
# Consent revocation cascade
# ---------------------------------------------------------------------------


class TestConsentRevocationCascade:
    """One agent REVOKE walks share, evaluation, clearance and contract."""

    def test_revocation_revokes_the_granted_share_and_seals_the_evaluation(
        self, api: ApiClient
    ) -> None:
        """The share leaves GRANTED and the emptied evaluation is sealed.

        PRD: "Moving `consent_status` from `GRANTED` to `REVOKED` requires no precondition, and then: every `MedicalRecordShare` in `GRANTED` that belongs to any evaluation of this prospect becomes `REVOKED`; each affected evaluation recomputes its `active_share_count` and, on reaching 0, has its `disclosure_state` set to `SEALED`; if that leaves every one of the prospect's evaluations `SEALED`, the prospect's `medical_clearance_status` becomes `UNVERIFIED`, because no club can any longer verify the file; because the clearance has left `CLEARED`, every `PlayerContract` for this prospect still in `OFFERED` becomes `LAPSED` and the prospect's `signing_status` returns to `UNSIGNED`; and finally `consent_scope` and `consent_expires_at` are cleared to null."

        Design: Difficulty/transitive_cascade/consent_revocation_revokes_share_seals_evaluation_unverifies_clearance_lapses_contract
        """
        state = _drafted_prospect_with_granted_share(api)
        assert state["share"]["status"] == "GRANTED"
        assert state["evaluation"]["active_share_count"] == 1
        assert state["evaluation"]["disclosure_state"] == "DISCLOSABLE"

        _revoke_consent(api, state)

        share = read_share(api, state["share"]["id"])
        assert share["status"] == "REVOKED"
        assert share["effective_access"] == "NONE"

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "SEALED"

    def test_revocation_unverifies_clearance_and_lapses_the_offered_contract(
        self, api: ApiClient
    ) -> None:
        """Sealing the whole file unverifies clearance and kills the offer.

        PRD: "A contract also reaches `LAPSED` without anyone acting on it, in three circumstances: a newer `OFFERED` contract arrives from the same club for the same prospect; the prospect revokes medical consent in a way that leaves the file unverifiable; or the cycle moves from `UDFA_WINDOW` to `CLOSED`."

        Design: Difficulty/transitive_cascade/consent_revocation_revokes_share_seals_evaluation_unverifies_clearance_lapses_contract
        """
        state = _drafted_prospect_with_granted_share(api)
        assert state["prospect"]["medical_clearance_status"] == "CLEARED"
        assert state["prospect"]["signing_status"] == "OFFER_OUT"
        assert state["contract"]["status"] == "OFFERED"

        _revoke_consent(api, state)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["medical_clearance_status"] == "UNVERIFIED"
        assert prospect["signing_status"] == "UNSIGNED"
        assert read_contract(api, state["contract"]["id"])["status"] == "LAPSED"

    def test_revocation_clears_the_consent_window_and_leaves_the_selection_standing(
        self, api: ApiClient
    ) -> None:
        """Scope and expiry go null while the used pick keeps its selection.

        PRD: "Both `consent_scope` and `consent_expires_at` are null whenever `consent_status` is not `GRANTED`."

        Design: Difficulty/transitive_cascade/consent_revocation_revokes_share_seals_evaluation_unverifies_clearance_lapses_contract
        """
        state = _drafted_prospect_with_granted_share(api)
        assert state["prospect"]["consent_status"] == "GRANTED"
        assert state["prospect"]["consent_scope"] == "FULL"

        revoked = _revoke_consent(api, state)
        assert revoked["consent_status"] == "REVOKED"
        assert revoked["consent_scope"] is None
        assert revoked["consent_expires_at"] is None

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["consent_status"] == "REVOKED"
        assert prospect["drafted_pick_overall_number"] == 1
        assert read_pick(api, state["used_pick"]["id"])["status"] == "USED"
