"""Guards that read state off a parent or sibling row rather than the target.

Three arbitration points are covered: a selection refused because the
grandparent draft cycle has been suspended, a medical record share refused
because the prospect authorised a narrower disclosure scope than the club
asked for, and a slotted rookie contract refused because the draft pick it
names has not yet been used on a selection.
"""

from typing import Dict

from test_helpers import (
    ADMIN,
    ERR_CONSENT_NOT_GRANTED,
    ERR_CONTRACT_PICK_MISMATCH,
    ERR_CYCLE_PHASE_INVALID,
    assert_cents_equal,
    assert_prospect_dimensions,
    build_draft_live_on_clock,
    build_medical_evaluation,
    grant_consent,
    make_club_gm_headers,
    make_club_medical_director_headers,
    medical_record_share_payload,
    move_phase,
    player_contract_payload,
    read_club,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    selection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CONSENT_UNTIL = "2027-06-30T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Local scenario compositions
# ---------------------------------------------------------------------------


def _suspended_draft_with_pick_on_clock(api) -> Dict:
    """Overall pick one is ON_CLOCK, then the league suspends the draft."""
    state = build_draft_live_on_clock(api)
    state["cycle"] = move_phase(api, state["cycle"]["id"], "DRAFT_SUSPENDED")
    return state


def _summary_consent_over_a_disclosable_evaluation(api) -> Dict:
    """A PASS evaluation on file while the agent authorised SUMMARY only."""
    state = build_medical_evaluation(api)
    state["prospect"] = grant_consent(
        api, state["prospect"], scope="SUMMARY", consent_expires_at=CONSENT_UNTIL
    )
    return state


def _request_share(api, state: Dict, scope: str):
    """Ask for club access as the medical director of the ELM club."""
    club = state["clubs"]["ELM"]
    evaluation = read_evaluation(api, state["evaluation"]["id"])
    return api.create_medical_record_share(
        medical_record_share_payload(
            evaluation["id"], club["id"], evaluation["version"], scope=scope
        ),
        make_club_medical_director_headers(club["id"]),
    )


def _offer_drafted_contract_against(api, state: Dict, pick: Dict):
    """Offer a DRAFTED contract slotted to a pick, as the owning club."""
    club = state["clubs"]["ELM"]
    prospect = read_prospect(api, state["prospect"]["id"])
    return api.create_player_contract(
        player_contract_payload(
            prospect["id"],
            club["id"],
            "DRAFTED",
            prospect["version"],
            draft_pick_id=pick["id"],
        ),
        make_club_gm_headers(club["id"]),
    )


# ---------------------------------------------------------------------------
# A suspended cycle blocks the club that holds the clock
# ---------------------------------------------------------------------------


class TestSuspendedCycleBlocksSelections:
    def test_selection_during_a_suspended_draft_reports_the_phase_guard(self, api):
        """A selection against a suspended cycle fails on the phase guard.

        "Cycle phase — the governing `DraftCycle` is in a `status` that permits
        the operation, else `ERR_CYCLE_PHASE_INVALID` (409)."

        "Because cycle phase (rule 7) precedes cycle posture (rule 8), an
        operation attempted in the wrong phase reports
        `ERR_CYCLE_PHASE_INVALID` even when the cycle is also frozen."

        Design: Difficulty/cross_entity_state_dependency/selection_blocked_while_parent_cycle_is_suspended
        """
        state = _suspended_draft_with_pick_on_clock(api)
        elm = state["clubs"]["ELM"]
        pick = state["pick"]["r1p1"]

        response = api.create_selection(
            pick["id"],
            selection_payload(state["prospect"]["id"]),
            make_club_gm_headers(elm["id"]),
        )

        error = validate_error(response, ERR_CYCLE_PHASE_INVALID)
        assert error["error_id"] == ERR_CYCLE_PHASE_INVALID

    def test_refused_selection_leaves_the_pick_on_the_clock(self, api):
        """The refused selection changes nothing on the pick or the prospect.

        "`posture` is `FROZEN` when `status` is `DRAFT_SUSPENDED` or `CLOSED`;
        it is `RESTRICTED` when `status` is `DRAFT_LIVE`, `DRAFT_COMPLETE` or
        `UDFA_WINDOW`; and it is `OPEN` in every other phase."

        "Guards are therefore evaluated in a single fixed order, top to bottom;
        the first guard that fails determines the response, and no later guard
        runs."

        Design: Difficulty/cross_entity_state_dependency/selection_blocked_while_parent_cycle_is_suspended
        """
        state = _suspended_draft_with_pick_on_clock(api)
        elm = state["clubs"]["ELM"]
        pick = state["pick"]["r1p1"]

        api.create_selection(
            pick["id"],
            selection_payload(state["prospect"]["id"]),
            make_club_gm_headers(elm["id"]),
        )

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["status"] == "DRAFT_SUSPENDED"
        assert cycle["posture"] == "FROZEN"

        held = read_pick(api, pick["id"])
        assert held["status"] == "ON_CLOCK"
        assert held["selected_prospect_id"] is None

        prospect = read_prospect(api, state["prospect"]["id"])
        assert_prospect_dimensions(prospect, drafted_pick_overall_number=0)


# ---------------------------------------------------------------------------
# The prospect's consent scope gates the club's share request
# ---------------------------------------------------------------------------


class TestConsentScopeGatesShareRequests:
    def test_full_scope_request_is_refused_against_summary_consent(self, api):
        """A FULL request exceeds a SUMMARY consent and is refused.

        "Consent — the prospect's `consent_status` is `GRANTED`,
        `consent_expires_at` is strictly after the current logical instant, and
        the requested `scope` does not exceed `consent_scope`, else
        `ERR_CONSENT_NOT_GRANTED` (403)."

        Design: Difficulty/cross_entity_state_dependency/full_scope_share_blocked_by_narrower_prospect_consent_scope
        """
        state = _summary_consent_over_a_disclosable_evaluation(api)

        response = _request_share(api, state, "FULL")

        validate_error(response, ERR_CONSENT_NOT_GRANTED)

    def test_refused_full_request_leaves_the_evaluation_unshared(self, api):
        """No share row appears and the evaluation ledger stays at zero.

        "Consent — the prospect's `consent_status` is `GRANTED`,
        `consent_expires_at` is strictly after the current logical instant, and
        the requested `scope` does not exceed `consent_scope`, else
        `ERR_CONSENT_NOT_GRANTED` (403)."

        "`disclosure_state` starts at `DISCLOSABLE` and `active_share_count`
        starts at 0."

        Design: Difficulty/cross_entity_state_dependency/full_scope_share_blocked_by_narrower_prospect_consent_scope
        """
        state = _summary_consent_over_a_disclosable_evaluation(api)

        _request_share(api, state, "FULL")

        prospect = read_prospect(api, state["prospect"]["id"])
        assert_prospect_dimensions(
            prospect,
            consent_status="GRANTED",
            consent_scope="SUMMARY",
            medical_clearance_status="CLEARED",
        )

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "DISCLOSABLE"
        assert evaluation["confidentiality_tier"] == "STANDARD"

        shares, meta = validate_paginated(
            api.list_medical_record_shares(
                ADMIN, {"medical_evaluation_id": evaluation["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert shares == []

    def test_summary_request_within_the_authorised_scope_is_admitted(self, api):
        """A SUMMARY request does not exceed a SUMMARY consent and is created.

        "Consent — the prospect's `consent_status` is `GRANTED`,
        `consent_expires_at` is strictly after the current logical instant, and
        the requested `scope` does not exceed `consent_scope`, else
        `ERR_CONSENT_NOT_GRANTED` (403)."

        "The share is created in `REQUESTED`, the requester's identifier is
        stored as `requested_by_user_id` and the requester's declared capacity
        as `requested_by_role`, and any earlier share for the same
        `medical_evaluation_id` and the same `club_id` still sitting in
        `REQUESTED` is immediately marked `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/full_scope_share_blocked_by_narrower_prospect_consent_scope
        """
        state = _summary_consent_over_a_disclosable_evaluation(api)

        share = validate_success(
            _request_share(api, state, "SUMMARY"), expected_status=201
        )

        assert share["status"] == "REQUESTED"
        assert share["scope"] == "SUMMARY"
        assert share["requested_by_role"] == "ClubMedicalDirector"
        assert share["club_id"] == state["clubs"]["ELM"]["id"]


# ---------------------------------------------------------------------------
# A drafted contract needs a pick that has already been used
# ---------------------------------------------------------------------------


class TestContractSlottingRequiresAUsedPick:
    def test_drafted_offer_against_an_on_clock_pick_is_refused(self, api):
        """The referenced pick is ON_CLOCK, so there is no selection to slot.

        "A `DRAFTED` offer must additionally name the `draft_pick_id` it is
        slotted to, and that pick's `status` must be `USED`, its
        `selected_prospect_id` must equal the supplied `prospect_id`, and its
        `owning_club_id` must equal the supplied `club_id`."

        "Any mismatch on either path is refused with
        `ERR_CONTRACT_PICK_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/rookie_contract_offer_blocked_because_pick_is_not_used_yet
        """
        state = build_draft_live_on_clock(api)

        response = _offer_drafted_contract_against(api, state, state["pick"]["r1p1"])

        validate_error(response, ERR_CONTRACT_PICK_MISMATCH)

    def test_refused_offer_leaves_the_prospect_and_the_pool_untouched(self, api):
        """No offer exists, so the prospect stays UNSIGNED and the pool is full.

        "A new offer is created in `OFFERED`, advances the prospect's
        `signing_status` from `UNSIGNED` to `OFFER_OUT`, and increments
        `Prospect.version` by one."

        "`rookie_pool_remaining_cents` is `rookie_pool_total_cents` minus the
        sum of `first_year_cap_charge_cents` over that club's contracts whose
        `status` is `SIGNED`; contracts in `OFFERED`, `VOIDED` or `LAPSED` are
        excluded from that sum entirely."

        Design: Difficulty/cross_entity_state_dependency/rookie_contract_offer_blocked_because_pick_is_not_used_yet
        """
        state = build_draft_live_on_clock(api)
        pick = state["pick"]["r1p1"]

        _offer_drafted_contract_against(api, state, pick)

        held = read_pick(api, pick["id"])
        assert held["status"] == "ON_CLOCK"
        assert held["selected_prospect_id"] is None

        prospect = read_prospect(api, state["prospect"]["id"])
        assert_prospect_dimensions(
            prospect, signing_status="UNSIGNED", drafted_pick_overall_number=0
        )

        elm = read_club(api, state["clubs"]["ELM"]["id"])
        assert_cents_equal(elm["rookie_pool_remaining_cents"], 896721432)

    def test_no_contract_row_is_created_for_the_unused_pick(self, api):
        """The rejected offer leaves the contract collection empty.

        "Any mismatch on either path is refused with
        `ERR_CONTRACT_PICK_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/rookie_contract_offer_blocked_because_pick_is_not_used_yet
        """
        state = build_draft_live_on_clock(api)

        _offer_drafted_contract_against(api, state, state["pick"]["r1p1"])

        contracts, meta = validate_paginated(
            api.list_player_contracts(
                ADMIN,
                {"prospect_id": state["prospect"]["id"], "origin": "DRAFTED"},
            )
        )
        assert meta["total_count"] == 0
        assert contracts == []
