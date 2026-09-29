"""Parent-version freshness on the two superseding creates, the monotonic
version walk on the cycle, the once-only draft-order mint, and the immediate
reconciliation of every derived figure a forfeit touches.

Covers the contract offer and the share request that must prove they have seen
the parent's latest state, the exact version arithmetic a phase write performs,
the finalize checkpoint that refuses a replay rather than double-minting, and the
single forfeit response that already carries the recomputed aggregates.
"""

from test_helpers import (
    ADMIN,
    CYCLE_SETUP_NOW,
    ERR_CYCLE_PHASE_INVALID,
    ERR_STALE_PARENT_VERSION,
    assert_cents_equal,
    assert_chart_points,
    build_cycle_with_clubs,
    build_draft_live_on_clock,
    build_medical_evaluation,
    build_order_final,
    clock_action_payload,
    declare_prospect,
    grant_consent,
    make_club_gm_headers,
    medical_record_share_payload,
    phase_payload,
    player_contract_payload,
    read_club,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    register_prospect,
    make_selection,
    request_share,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleParentVersionRejection:
    """The two creates that supersede an earlier row must prove their view."""

    def test_contract_offer_on_a_pre_selection_prospect_version_is_refused(self, api):
        """A prospect version read before the selection is stale at offer time.

        The selection stamped the drafted pick on the prospect and so bumped its
        version; the offer replaying the earlier number is refused and no
        contract comes into being, leaving the club's rookie pool untouched.

        "If that number does not equal the prospect's current `version`, the request is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/contract_offer_with_a_prospect_version_captured_before_the_selection_is_rejected
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        prospect = state["prospect"]
        first_overall = state["pick"]["r1p1"]

        stale_version = read_prospect(api, prospect["id"])["version"]
        make_selection(api, first_overall, prospect, elm)

        response = api.create_player_contract(
            player_contract_payload(
                prospect["id"],
                elm["id"],
                "DRAFTED",
                stale_version,
                draft_pick_id=first_overall["id"],
            ),
            make_club_gm_headers(elm["id"]),
        )

        validate_error(response, ERR_STALE_PARENT_VERSION, expected_status=412)
        contracts, meta = validate_paginated(
            api.list_player_contracts(ADMIN, {"prospect_id": prospect["id"]})
        )
        assert contracts == []
        assert meta["total_count"] == 0
        after_prospect = read_prospect(api, prospect["id"])
        assert after_prospect["signing_status"] == "UNSIGNED"
        assert after_prospect["drafted_pick_overall_number"] == 1
        assert read_pick(api, first_overall["id"])["status"] == "USED"
        assert_cents_equal(
            read_club(api, elm["id"])["rookie_pool_remaining_cents"], 896721432
        )

    def test_second_share_request_replaying_the_consumed_version_is_refused(self, api):
        """A second club replaying the version the first request consumed is refused.

        The accepted request bumped the evaluation's version, so the peer club's
        stale number is rejected: the first club's request is not superseded and
        the evaluation's disclosure ledger is unmoved.

        "If that number does not equal the evaluation's current `version`, the request is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/second_share_request_reusing_the_first_requests_evaluation_version_is_rejected
        """
        state = build_medical_evaluation(api)
        elm = state["clubs"]["ELM"]
        harbor = state["clubs"]["HAR"]
        grant_consent(api, state["prospect"])

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        consumed_version = evaluation["version"]
        elm_share = request_share(api, evaluation, elm, scope="FULL")

        response = api.create_medical_record_share(
            medical_record_share_payload(
                evaluation["id"], harbor["id"], consumed_version, scope="SUMMARY"
            ),
            make_club_gm_headers(harbor["id"]),
        )

        validate_error(response, ERR_STALE_PARENT_VERSION, expected_status=412)
        surviving = validate_success(
            api.get_medical_record_share(elm_share["id"], ADMIN)
        )
        assert surviving["status"] == "REQUESTED"
        assert surviving["club_id"] == elm["id"]
        after = read_evaluation(api, evaluation["id"])
        assert after["active_share_count"] == 0
        assert after["disclosure_state"] == "DISCLOSABLE"


class TestCycleVersionWalk:
    """Each write on the parent that optimistic concurrency guards costs one."""

    def test_each_phase_write_advances_the_cycle_version_by_exactly_one(self, api):
        """Two consecutive phase writes walk the cycle version up one at a time.

        Each phase call takes the cycle's version from its pre-trigger value to
        exactly that value plus one — never plus two — and a cycle write leaves
        the prospect's own version alone.

        "Each phase change increments the cycle's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/every_phase_write_increments_the_cycle_version
        """
        state = build_cycle_with_clubs(api)
        cycle_id = state["cycle"]["id"]

        at_setup = read_cycle(api, cycle_id)["version"]
        opened = validate_success(
            api.set_cycle_phase(
                cycle_id, phase_payload("DECLARATION_OPEN"), ADMIN
            )
        )
        assert opened["status"] == "DECLARATION_OPEN"
        assert opened["version"] == at_setup + 1

        prospect = register_prospect(api, cycle_id)
        declare_prospect(api, prospect)
        prospect_version = read_prospect(api, prospect["id"])["version"]
        before_trigger = read_cycle(api, cycle_id)["version"]
        assert before_trigger == at_setup + 1

        combine = validate_success(
            api.set_cycle_phase(cycle_id, phase_payload("COMBINE_WEEK"), ADMIN)
        )
        assert combine["status"] == "COMBINE_WEEK"
        assert combine["version"] == before_trigger + 1

        assert read_cycle(api, cycle_id)["version"] == before_trigger + 1
        after_prospect = read_prospect(api, prospect["id"])
        assert after_prospect["version"] == prospect_version
        assert after_prospect["declaration_status"] == "DECLARED"


class TestDraftOrderMintCheckpoint:
    """The mint runs exactly once and refuses a replay rather than repeating."""

    def test_draft_order_finalize_cannot_run_a_second_time(self, api):
        """A replayed finalize is refused instead of minting the ledger twice.

        The recorded finalize instant is the checkpoint: the second call is
        rejected, the cycle stays at ORDER_FINAL, and the minted inventory keeps
        its four picks and their combined chart value. The first finalize already
        advanced the cycle out of `ORDER_PENDING`, and the phase guard is rule 7,
        so the replay is refused there rather than on transition legality.

        "Finalizing requires `lottery_completed` to be true and `order_finalized_at` to still be null — the mint runs exactly once."

        "the lottery and the draft-order finalize only while it is `ORDER_PENDING`"

        Design: Corner/cross_cutting_complexity_layers/draft_order_finalize_cannot_run_a_second_time
        """
        state = build_order_final(api)
        cycle_id = state["cycle"]["id"]

        response = api.finalize_draft_order(cycle_id, None, ADMIN)

        validate_error(response, ERR_CYCLE_PHASE_INVALID, expected_status=409)
        after = read_cycle(api, cycle_id)
        assert after["status"] == "ORDER_FINAL"
        assert after["pick_inventory_count"] == 4
        assert_chart_points(after["pick_inventory_chart_points"], 2754.8)
        assert after["order_finalized_at"] == CYCLE_SETUP_NOW
        picks, meta = validate_paginated(
            api.list_draft_picks(ADMIN, {"draft_cycle_id": cycle_id, "limit": 100})
        )
        assert meta["total_count"] == 4
        assert len(picks) == 4


class TestForfeitImmediateReconciliation:
    """One forfeit answers with every derived figure already recomputed."""

    def test_forfeit_response_carries_every_reconciled_derived_field(self, api):
        """The forfeit response itself already shows the reconciled figures.

        Consistency is immediate: the single call answers with the pick zeroed
        out, and the owning club's negotiating capital, its trade tier, its
        forfeited rounds and the cycle inventory are all recomputed with no
        follow-up write and no lag.

        "A pick changing owner, status or chart value recomputes the owning club's `draft_capital_points` and re-derives its `trade_authorization_tier`, and recomputes the cycle's `pick_inventory_chart_points` and `pick_inventory_count`."

        Design: Corner/consistency_model/forfeit_response_shows_every_derived_field_already_reconciled
        """
        state = build_order_final(api)
        cycle_id = state["cycle"]["id"]
        harbor = state["clubs"]["HAR"]
        harbor_first_rounder = state["pick"]["r1p2"]

        response = api.act_on_pick_clock(
            harbor_first_rounder["id"], clock_action_payload("FORFEIT"), ADMIN
        )

        forfeited = validate_success(response)
        assert forfeited["status"] == "FORFEITED"
        assert_chart_points(forfeited["chart_value_points"], 0.0)
        assert read_pick(api, harbor_first_rounder["id"])["status"] == "FORFEITED"
        after_club = read_club(api, harbor["id"])
        assert_chart_points(after_club["draft_capital_points"], 394.8)
        assert after_club["trade_authorization_tier"] == "SUSPENDED"
        assert after_club["forfeited_round_numbers"] == [1]
        after_cycle = read_cycle(api, cycle_id)
        assert_chart_points(after_cycle["pick_inventory_chart_points"], 1814.8)
        assert after_cycle["pick_inventory_count"] == 3
