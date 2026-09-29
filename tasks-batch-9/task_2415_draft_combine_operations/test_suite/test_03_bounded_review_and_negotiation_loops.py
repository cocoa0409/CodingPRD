"""State machines that are not a single linear ladder.

A prospect carries five status dimensions on one row that advance without
touching each other, an eligibility waiver cycles between review and an
information request a bounded number of times, and a pick trade loops from
countered back to countered while alternating actors until the round cap is
reached.
"""

from typing import Dict, Optional

import pytest

from test_helpers import (
    ADMIN,
    COMMITTEE_DECIDER_USER_ID,
    COMMITTEE_REVIEWER_USER_ID,
    ERR_TRADE_ROUNDS_EXHAUSTED,
    ApiClient,
    accept_invitation,
    api_errors,
    assert_imbalance_ratio,
    assert_prospect_dimensions,
    build_declaration_open,
    consent_payload,
    declare_prospect,
    file_waiver,
    find_by_id,
    invite_prospect,
    make_club_gm_headers,
    make_committee_headers,
    make_prospect_agent_headers,
    pick_trade_payload,
    read_pick,
    read_prospect,
    read_trade,
    register_prospect,
    rule_prospect_eligible,
    trade_counter_payload,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_review_payload,
)

ERR_WAIVER_ROUNDS_EXHAUSTED = api_errors.ERR_WAIVER_ROUNDS_EXHAUSTED

# The logical instant every scenario in this module starts from.
_SETUP_INSTANT = "2027-01-02T00:00:00.000Z"


def _grant_consent(
    api: ApiClient,
    prospect_id: str,
    scope: str,
    consent_expires_at: str,
) -> Dict:
    response = api.act_on_prospect_consent(
        prospect_id,
        consent_payload("GRANT", scope, consent_expires_at),
        make_prospect_agent_headers(prospect_id),
    )
    return validate_success(response, expected_status=200)


def _revoke_consent(api: ApiClient, prospect_id: str) -> Dict:
    response = api.act_on_prospect_consent(
        prospect_id,
        consent_payload("REVOKE", scope=None, consent_expires_at=None),
        make_prospect_agent_headers(prospect_id),
    )
    return validate_success(response, expected_status=200)


def _review(
    api: ApiClient,
    waiver_id: str,
    action: str,
    user_id: str,
    decision_note: Optional[str] = None,
):
    extra = {} if decision_note is None else {"decision_note": decision_note}
    return api.review_eligibility_waiver(
        waiver_id,
        waiver_review_payload(action, **extra),
        make_committee_headers(user_id),
    )


def _read_waiver(api: ApiClient, prospect_id: str, waiver_id: str) -> Dict:
    rows, _ = validate_paginated(
        api.list_eligibility_waivers(prospect_id, ADMIN, {"limit": 100})
    )
    return find_by_id(rows, waiver_id)


@pytest.fixture
def prospect_with_accepted_invitation(api: ApiClient) -> Dict:
    """A declared, eligible prospect that has accepted its combine invitation."""
    state = build_declaration_open(api)
    prospect = register_prospect(api, state["cycle"]["id"])
    prospect = declare_prospect(api, prospect)
    prospect = rule_prospect_eligible(api, prospect)
    prospect = invite_prospect(api, prospect)
    state["prospect"] = accept_invitation(api, prospect)
    return state


@pytest.fixture
def early_entry_waiver(api: ApiClient) -> Dict:
    """A two-season prospect with a submitted early-entry waiver on file."""
    state = build_declaration_open(api)
    prospect = register_prospect(
        api,
        state["cycle"]["id"],
        full_name="Dane Cobb",
        position_group="OL",
        school_code="WST",
        seasons_played=2,
        scouting_grade=90.00,
        position_group_scarcity_rank=4,
    )
    state["prospect"] = prospect
    state["waiver"] = file_waiver(
        api,
        prospect,
        "EARLY_ENTRY",
        rationale="Two seasons played; hardship declaration on file",
    )
    return state


class TestProspectParallelDimensions:
    """Five status dimensions sharing one row."""

    def test_consent_grant_moves_only_the_consent_dimension(
        self, api: ApiClient, prospect_with_accepted_invitation: Dict
    ) -> None:
        """Granting disclosure consent leaves the other four dimensions alone.

        "These dimensions advance independently of one another; a prospect can be
        `DECLARED` and `UNREVIEWED` and `INVITED` and `NONE` and `UNSIGNED` all at
        once."

        Design: Difficulty/non_linear_state_machine/prospect_parallel_dimensions_advance_without_disturbing_each_other
        """
        prospect = prospect_with_accepted_invitation["prospect"]

        data = _grant_consent(
            api, prospect["id"], "FULL", "2027-06-30T00:00:00.000Z"
        )

        assert_prospect_dimensions(
            data,
            consent_status="GRANTED",
            consent_scope="FULL",
            consent_expires_at="2027-06-30T00:00:00.000Z",
            declaration_status="DECLARED",
            declared_at=_SETUP_INSTANT,
            eligibility_status="ELIGIBLE",
            invitation_status="ACCEPTED",
            medical_clearance_status="PENDING",
            signing_status="UNSIGNED",
            drafted_pick_overall_number=0,
        )

    def test_consent_revocation_clears_the_window_only(
        self, api: ApiClient, prospect_with_accepted_invitation: Dict
    ) -> None:
        """Revoking empties the consent window and no other dimension moves.

        "Both `consent_scope` and `consent_expires_at` are null whenever
        `consent_status` is not `GRANTED`."

        Design: Difficulty/non_linear_state_machine/prospect_parallel_dimensions_advance_without_disturbing_each_other
        """
        prospect = prospect_with_accepted_invitation["prospect"]
        _grant_consent(api, prospect["id"], "FULL", "2027-06-30T00:00:00.000Z")

        data = _revoke_consent(api, prospect["id"])

        assert_prospect_dimensions(
            data,
            consent_status="REVOKED",
            consent_scope=None,
            consent_expires_at=None,
            declaration_status="DECLARED",
            eligibility_status="ELIGIBLE",
            invitation_status="ACCEPTED",
            signing_status="UNSIGNED",
            drafted_pick_overall_number=0,
        )

    def test_consent_dimension_cycles_back_to_granted_with_a_narrower_scope(
        self, api: ApiClient, prospect_with_accepted_invitation: Dict
    ) -> None:
        """A second grant reopens the window at SUMMARY without touching the rest.

        "The consent dimension is the prospect's own, driven by a `ProspectAgent`
        with an `action` of `GRANT` or `REVOKE`, and it is genuinely cyclic —
        consent may be granted, revoked and granted again without bound."

        Design: Difficulty/non_linear_state_machine/prospect_parallel_dimensions_advance_without_disturbing_each_other
        """
        prospect = prospect_with_accepted_invitation["prospect"]
        _grant_consent(api, prospect["id"], "FULL", "2027-06-30T00:00:00.000Z")
        _revoke_consent(api, prospect["id"])

        data = _grant_consent(
            api, prospect["id"], "SUMMARY", "2027-07-31T00:00:00.000Z"
        )

        assert_prospect_dimensions(
            data,
            consent_status="GRANTED",
            consent_scope="SUMMARY",
            consent_expires_at="2027-07-31T00:00:00.000Z",
            declaration_status="DECLARED",
            eligibility_status="ELIGIBLE",
            invitation_status="ACCEPTED",
            signing_status="UNSIGNED",
            drafted_pick_overall_number=0,
        )


class TestWaiverInformationRequestLoop:
    """Two laps around review and an information request, then no more."""

    def test_two_information_requests_traverse_the_loop_and_return_to_review(
        self, api: ApiClient, early_entry_waiver: Dict
    ) -> None:
        """The counter climbs 0, 1, 2 while the waiver returns to UNDER_REVIEW.

        "`OPEN_REVIEW` from `INFO_REQUESTED` returns the waiver to `UNDER_REVIEW`
        with no precondition, and records the acting identifier as
        `opened_by_user_id` — overwriting whatever was there."

        Design: Difficulty/non_linear_state_machine/waiver_review_loop_survives_two_info_requests_and_third_is_rejected
        """
        waiver = early_entry_waiver["waiver"]
        reviewer = COMMITTEE_REVIEWER_USER_ID

        opened = validate_success(
            _review(api, waiver["id"], "OPEN_REVIEW", reviewer),
            expected_status=200,
        )
        assert opened["status"] == "UNDER_REVIEW"
        assert opened["info_request_count"] == 0
        assert opened["opened_by_user_id"] == reviewer

        first = validate_success(
            _review(
                api, waiver["id"], "REQUEST_INFO", reviewer, "Need transcript"
            ),
            expected_status=200,
        )
        assert first["status"] == "INFO_REQUESTED"
        assert first["info_request_count"] == 1

        reopened = validate_success(
            _review(api, waiver["id"], "OPEN_REVIEW", reviewer),
            expected_status=200,
        )
        assert reopened["status"] == "UNDER_REVIEW"
        assert reopened["info_request_count"] == 1

        second = validate_success(
            _review(
                api, waiver["id"], "REQUEST_INFO", reviewer, "Need medical letter"
            ),
            expected_status=200,
        )
        assert second["status"] == "INFO_REQUESTED"
        assert second["info_request_count"] == 2

        reopened_again = validate_success(
            _review(api, waiver["id"], "OPEN_REVIEW", reviewer),
            expected_status=200,
        )
        assert reopened_again["status"] == "UNDER_REVIEW"
        assert reopened_again["info_request_count"] == 2

    def test_third_information_request_is_refused_and_the_counter_holds_at_two(
        self, api: ApiClient, early_entry_waiver: Dict
    ) -> None:
        """A third request fails while the waiver stays UNDER_REVIEW at two.

        "It requires `info_request_count` to be below two; a third information
        request is refused with `ERR_WAIVER_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/waiver_review_loop_survives_two_info_requests_and_third_is_rejected
        """
        prospect = early_entry_waiver["prospect"]
        waiver = early_entry_waiver["waiver"]
        reviewer = COMMITTEE_REVIEWER_USER_ID

        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)
        _review(api, waiver["id"], "REQUEST_INFO", reviewer, "Need transcript")
        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)
        _review(
            api, waiver["id"], "REQUEST_INFO", reviewer, "Need medical letter"
        )
        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)

        refusal = _review(
            api, waiver["id"], "REQUEST_INFO", reviewer, "Third request"
        )
        validate_error(refusal, ERR_WAIVER_ROUNDS_EXHAUSTED, expected_status=409)

        after = _read_waiver(api, prospect["id"], waiver["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["info_request_count"] == 2
        assert after["opened_by_user_id"] == reviewer
        assert after["decided_by_user_id"] is None
        assert read_prospect(api, prospect["id"])["early_entry_waived"] is False

    def test_exhausted_loop_can_still_be_decided_by_a_second_reviewer(
        self, api: ApiClient, early_entry_waiver: Dict
    ) -> None:
        """After the cap the waiver is still granted, releasing the relief.

        "It also grants the relief itself: a `LATE_DECLARATION` waiver sets the
        prospect's `late_declaration_waived` to true, and an `EARLY_ENTRY` waiver
        sets the prospect's `early_entry_waived` to true."

        Design: Difficulty/non_linear_state_machine/waiver_review_loop_survives_two_info_requests_and_third_is_rejected
        """
        prospect = early_entry_waiver["prospect"]
        waiver = early_entry_waiver["waiver"]
        reviewer = COMMITTEE_REVIEWER_USER_ID

        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)
        _review(api, waiver["id"], "REQUEST_INFO", reviewer, "Need transcript")
        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)
        _review(
            api, waiver["id"], "REQUEST_INFO", reviewer, "Need medical letter"
        )
        _review(api, waiver["id"], "OPEN_REVIEW", reviewer)

        granted = validate_success(
            _review(
                api,
                waiver["id"],
                "GRANT",
                COMMITTEE_DECIDER_USER_ID,
                "Hardship documentation accepted",
            ),
            expected_status=200,
        )
        assert granted["status"] == "GRANTED"
        assert granted["info_request_count"] == 2
        assert granted["decided_by_user_id"] == COMMITTEE_DECIDER_USER_ID
        assert read_prospect(api, prospect["id"])["early_entry_waived"] is True


class TestTradeCounterLoop:
    """The countered-to-countered self-loop and its round cap."""

    def _propose_round_two_swap(self, api: ApiClient, state: Dict) -> Dict:
        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]
        offered = state["pick"]["r2p1"]
        requested = state["pick"]["r2p2"]
        assert offered["owning_club_id"] == elm["id"]
        assert requested["owning_club_id"] == har["id"]
        return validate_success(
            api.create_pick_trade(
                pick_trade_payload(
                    state["cycle"]["id"],
                    elm["id"],
                    har["id"],
                    [offered["id"]],
                    [requested["id"]],
                ),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=201,
        )

    def test_counter_loop_alternates_actors_and_climbs_to_the_round_cap(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """Proposal one, Harbor City two, Elmwood three, always alternating.

        "Every counter increments `round_index` by one, replaces `offered_pick_ids`
        and `requested_pick_ids` with the new package, recomputes
        `chart_balance_points`, `imbalance_ratio` and `surplus_balance_points`, and
        sets `last_actor_club_id` to the acting club."

        A counter's package keeps the proposal's orientation: "every pick in
        `offered_pick_ids` is owned by `proposing_club_id`, every pick in
        `requested_pick_ids` is owned by `receiving_club_id`, and all of them are
        `PENDING`, else `ERR_PICK_NOT_OWNED_BY_CLUB`. Applies to
        `POST /draft-ops/pick-trades`, `POST /draft-ops/pick-trades/{id}/counter`
        and `POST /draft-ops/pick-trades/{id}/accept`." — so each counter varies
        which of the proposing club's picks are offered, not which side owns them.

        Design: Difficulty/non_linear_state_machine/trade_counter_cycle_consumes_three_rounds_and_fourth_counter_rejected
        """
        state = order_final
        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]
        elm_pick = state["pick"]["r2p1"]
        har_pick = state["pick"]["r2p2"]
        elm_alt = state["pick"]["r1p1"]

        trade = self._propose_round_two_swap(api, state)
        assert trade["status"] == "PROPOSED"
        assert trade["round_index"] == 1
        assert trade["last_actor_club_id"] == elm["id"]

        first_counter = validate_success(
            api.counter_pick_trade(
                trade["id"],
                trade_counter_payload([elm_alt["id"]], [har_pick["id"]]),
                make_club_gm_headers(har["id"]),
            ),
            expected_status=200,
        )
        assert first_counter["status"] == "COUNTERED"
        assert first_counter["round_index"] == 2
        assert first_counter["last_actor_club_id"] == har["id"]
        assert first_counter["offered_pick_ids"] == [elm_alt["id"]]

        second_counter = validate_success(
            api.counter_pick_trade(
                trade["id"],
                trade_counter_payload([elm_pick["id"]], [har_pick["id"]]),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=200,
        )
        assert second_counter["status"] == "COUNTERED"
        assert second_counter["round_index"] == 3
        assert second_counter["last_actor_club_id"] == elm["id"]
        assert second_counter["offered_pick_ids"] == [elm_pick["id"]]

    def test_fourth_counter_is_refused_with_the_round_index_frozen_at_three(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """Harbor City's fourth lap fails and the package is left untouched.

        "Both paths require that the acting club is not the current
        `last_actor_club_id` — clubs must alternate — and that `round_index` is below
        three, else `ERR_TRADE_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/trade_counter_cycle_consumes_three_rounds_and_fourth_counter_rejected
        """
        state = order_final
        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]
        elm_pick = state["pick"]["r2p1"]
        har_pick = state["pick"]["r2p2"]
        elm_alt = state["pick"]["r1p1"]

        trade = self._propose_round_two_swap(api, state)
        api.counter_pick_trade(
            trade["id"],
            trade_counter_payload([elm_alt["id"]], [har_pick["id"]]),
            make_club_gm_headers(har["id"]),
        )
        api.counter_pick_trade(
            trade["id"],
            trade_counter_payload([elm_pick["id"]], [har_pick["id"]]),
            make_club_gm_headers(elm["id"]),
        )

        refusal = api.counter_pick_trade(
            trade["id"],
            trade_counter_payload([elm_alt["id"]], [har_pick["id"]]),
            make_club_gm_headers(har["id"]),
        )
        validate_error(refusal, ERR_TRADE_ROUNDS_EXHAUSTED, expected_status=409)

        after = read_trade(api, trade["id"])
        assert after["status"] == "COUNTERED"
        assert after["round_index"] == 3
        assert after["last_actor_club_id"] == elm["id"]
        assert after["offered_pick_ids"] == [elm_pick["id"]]
        assert after["conditional_status"] == "NONE"

    def test_trade_at_the_round_cap_remains_acceptable_by_the_other_side(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """Harbor City may still accept the third-round package it did not send.

        "Acceptance is available from both `PROPOSED` and `COUNTERED`, with
        identical preconditions and identical effects on both paths."

        Design: Difficulty/non_linear_state_machine/trade_counter_cycle_consumes_three_rounds_and_fourth_counter_rejected
        """
        state = order_final
        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]
        elm_pick = state["pick"]["r2p1"]
        har_pick = state["pick"]["r2p2"]
        elm_alt = state["pick"]["r1p1"]

        trade = self._propose_round_two_swap(api, state)
        api.counter_pick_trade(
            trade["id"],
            trade_counter_payload([elm_alt["id"]], [har_pick["id"]]),
            make_club_gm_headers(har["id"]),
        )
        api.counter_pick_trade(
            trade["id"],
            trade_counter_payload([elm_pick["id"]], [har_pick["id"]]),
            make_club_gm_headers(elm["id"]),
        )

        accepted = validate_success(
            api.accept_pick_trade(
                trade["id"], None, make_club_gm_headers(har["id"])
            ),
            expected_status=200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["round_index"] == 3
        assert_imbalance_ratio(accepted["imbalance_ratio"], 0.0600)
        assert read_pick(api, elm_pick["id"])["owning_club_id"] == har["id"]
        assert read_pick(api, har_pick["id"])["owning_club_id"] == elm["id"]
