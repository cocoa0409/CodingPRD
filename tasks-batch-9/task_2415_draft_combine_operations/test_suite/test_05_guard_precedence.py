"""Which rejection wins when a single request violates two guards at once.

Three pairs are exercised, each on an endpoint where two independent rules are
simultaneously broken: the privacy gate on a medical record share against the
same-cycle bookkeeping gate, the running-clock gate on a timeout against the
club's timeout budget, and the declaration window against declaration
idempotence. Each pair is asserted twice — once with both rules broken, so the
earlier rule must be the one reported, and once with the earlier rule satisfied,
so the later rule finally surfaces.
"""

from typing import Dict

from test_helpers import (
    ADMIN,
    ERR_ALREADY_DECLARED,
    ERR_CLOCK_ALREADY_EXPIRED,
    ERR_CONSENT_NOT_GRANTED,
    ERR_CROSS_CYCLE_REFERENCE,
    ERR_DECLARATION_DEADLINE_PASSED,
    ERR_NO_TIMEOUTS_REMAINING,
    ApiClient,
    build_declaration_open,
    build_draft_live_on_clock,
    build_medical_evaluation,
    build_waiver_under_review,
    clock_action_payload,
    create_cycle,
    declaration_payload,
    declare_prospect,
    get_success_data,
    grant_consent,
    make_club_gm_headers,
    make_club_medical_director_headers,
    make_prospect_agent_headers,
    medical_record_share_payload,
    read_club,
    read_evaluation,
    read_pick,
    read_prospect,
    register_club,
    register_prospect,
    review_waiver,
    set_clock,
    validate_error,
    validate_paginated,
)

CONSENT_EXPIRES_AT = "2027-06-30T00:00:00.000Z"
DECLARED_AT = "2027-01-02T00:00:00.000Z"
PAST_THE_DEADLINE = "2027-01-16T00:00:00.000Z"
TWO_TIMEOUT_DEADLINE = "2027-04-22T18:14:00.000Z"


# ---------------------------------------------------------------------------
# Scenario composition
# ---------------------------------------------------------------------------


def _evaluation_plus_foreign_club(api: ApiClient) -> Dict:
    """A 2027 PASS evaluation with no consent, plus a club from a 2028 cycle."""
    state = build_medical_evaluation(api)
    other_cycle = create_cycle(
        api,
        season_year=2028,
        declaration_deadline_at="2028-01-15T23:59:59.000Z",
        combine_week_start_at="2028-02-21T08:00:00.000Z",
        combine_week_end_at="2028-02-27T20:00:00.000Z",
        draft_start_at="2028-04-20T18:00:00.000Z",
        rounds_count=2,
    )
    state["other_cycle"] = other_cycle
    state["other_club"] = register_club(
        api,
        other_cycle["id"],
        "ZEN",
        market_name="Zenith Park",
        prior_season_win_pct=0.400,
        strength_of_schedule=0.490,
        head_to_head_rank=2,
        rookie_pool_total_cents=500000000,
        lottery_combinations=100,
    )
    return state


def _request_share_for_foreign_club(api: ApiClient, state: Dict):
    evaluation = read_evaluation(api, state["evaluation"]["id"])
    zen_id = state["other_club"]["id"]
    return api.create_medical_record_share(
        medical_record_share_payload(
            evaluation["id"], zen_id, evaluation["version"], scope="FULL"
        ),
        make_club_medical_director_headers(zen_id),
    )


def _pick_one_with_both_timeouts_spent(api: ApiClient) -> Dict:
    """Overall pick 1 ON_CLOCK from 18:00 with ELM's two timeouts already spent."""
    state = build_draft_live_on_clock(api)
    elm = state["clubs"]["ELM"]
    pick_id = state["pick"]["r1p1"]["id"]
    for _ in range(2):
        get_success_data(
            api.act_on_pick_clock(
                pick_id,
                clock_action_payload("TIMEOUT"),
                make_club_gm_headers(elm["id"]),
            )
        )
    return state


def _take_a_timeout(api: ApiClient, state: Dict):
    return api.act_on_pick_clock(
        state["pick"]["r1p1"]["id"],
        clock_action_payload("TIMEOUT"),
        make_club_gm_headers(state["clubs"]["ELM"]["id"]),
    )


def _declared_prospect(api: ApiClient) -> Dict:
    state = build_declaration_open(api)
    prospect = register_prospect(api, state["cycle"]["id"])
    state["prospect"] = declare_prospect(api, prospect)
    return state


def _declare_again(api: ApiClient, prospect: Dict):
    return api.declare_prospect(
        prospect["id"],
        declaration_payload("DECLARE"),
        make_prospect_agent_headers(prospect["id"]),
    )


# ---------------------------------------------------------------------------
# Consent (rule 11) before cycle cohesion (rule 20)
# ---------------------------------------------------------------------------


class TestConsentGateBeforeCycleCohesion:
    """A share request that breaks both privacy and cycle scope reports privacy."""

    def test_missing_consent_is_reported_before_the_foreign_cycle_club(
        self, api: ApiClient
    ) -> None:
        """Both rules are broken, so the earlier privacy gate answers with 403.

        PRD: "Guards are therefore evaluated in a single fixed order, top to bottom; the first guard that fails determines the response, and no later guard runs."

        PRD: "Consent — the prospect's `consent_status` is `GRANTED`, `consent_expires_at` is strictly after the current logical instant, and the requested `scope` does not exceed `consent_scope`, else `ERR_CONSENT_NOT_GRANTED` (403)."

        Design: Difficulty/priority_pair_validation_conflict/consent_gate_priority_11_outranks_cross_cycle_reference_priority_20
        """
        state = _evaluation_plus_foreign_club(api)
        assert state["prospect"]["consent_status"] == "NONE"

        response = _request_share_for_foreign_club(api, state)
        validate_error(response, ERR_CONSENT_NOT_GRANTED, expected_status=403)

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "DISCLOSABLE"
        assert read_prospect(api, state["prospect"]["id"])["consent_status"] == "NONE"

        rows, meta = validate_paginated(
            api.list_medical_record_shares(
                ADMIN, {"medical_evaluation_id": state["evaluation"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_foreign_cycle_club_surfaces_once_consent_is_granted(
        self, api: ApiClient
    ) -> None:
        """With consent in place the later cohesion rule answers with 422.

        PRD: "Cycle cohesion — every referenced `Club`, `Prospect`, `DraftPick` and `CompensatoryClaim` belongs to the same `DraftCycle` as the operation, else `ERR_CROSS_CYCLE_REFERENCE` (422)."

        Design: Difficulty/priority_pair_validation_conflict/consent_gate_priority_11_outranks_cross_cycle_reference_priority_20
        """
        state = _evaluation_plus_foreign_club(api)
        state["prospect"] = grant_consent(
            api,
            state["prospect"],
            scope="FULL",
            consent_expires_at=CONSENT_EXPIRES_AT,
        )
        assert state["prospect"]["consent_status"] == "GRANTED"

        response = _request_share_for_foreign_club(api, state)
        validate_error(response, ERR_CROSS_CYCLE_REFERENCE, expected_status=422)

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "DISCLOSABLE"


# ---------------------------------------------------------------------------
# Running clock (rule 18) before timeout inventory (rule 38)
# ---------------------------------------------------------------------------


class TestRunningClockBeforeTimeoutInventory:
    """A third timeout at the extended deadline reports the expired clock."""

    def test_expired_clock_is_reported_before_the_empty_timeout_budget(
        self, api: ApiClient
    ) -> None:
        """At exactly 18:14:00.000Z the temporal rule answers with 409.

        PRD: "Running clock — the current logical instant is strictly before the pick's `deadline_at` for any action that assumes a running clock, else `ERR_CLOCK_ALREADY_EXPIRED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/expired_clock_priority_18_outranks_timeout_exhaustion_priority_38
        """
        state = _pick_one_with_both_timeouts_spent(api)
        assert read_club(api, state["clubs"]["ELM"]["id"])["timeouts_remaining"] == 0
        set_clock(api, TWO_TIMEOUT_DEADLINE)

        response = _take_a_timeout(api, state)
        validate_error(response, ERR_CLOCK_ALREADY_EXPIRED, expected_status=409)

        pick = read_pick(api, state["pick"]["r1p1"]["id"])
        assert pick["status"] == "ON_CLOCK"
        assert pick["timeouts_used"] == 2
        assert pick["deadline_at"] == TWO_TIMEOUT_DEADLINE
        assert read_club(api, state["clubs"]["ELM"]["id"])["timeouts_remaining"] == 0

    def test_empty_timeout_budget_surfaces_while_the_clock_still_runs(
        self, api: ApiClient
    ) -> None:
        """Strictly before the deadline the budget rule answers with 409.

        PRD: "Timeout inventory — the owning club's `timeouts_remaining` is greater than zero when the action is `TIMEOUT`, else `ERR_NO_TIMEOUTS_REMAINING` (409)."

        Design: Difficulty/priority_pair_validation_conflict/expired_clock_priority_18_outranks_timeout_exhaustion_priority_38
        """
        state = _pick_one_with_both_timeouts_spent(api)
        running = read_pick(api, state["pick"]["r1p1"]["id"])
        assert running["deadline_at"] == TWO_TIMEOUT_DEADLINE

        response = _take_a_timeout(api, state)
        validate_error(response, ERR_NO_TIMEOUTS_REMAINING, expected_status=409)

        pick = read_pick(api, state["pick"]["r1p1"]["id"])
        assert pick["status"] == "ON_CLOCK"
        assert pick["timeouts_used"] == 2
        assert pick["deadline_at"] == TWO_TIMEOUT_DEADLINE


# ---------------------------------------------------------------------------
# Declaration deadline (rule 16) before declaration idempotence (rule 28)
# ---------------------------------------------------------------------------


class TestDeclarationDeadlineBeforeIdempotence:
    """A late second DECLARE reports the closed window, not the repeat."""

    def test_closed_window_is_reported_before_the_repeated_declaration(
        self, api: ApiClient
    ) -> None:
        """Past the deadline the window rule answers and declared_at is kept.

        PRD: "Declaration deadline — the current logical instant is at or before the cycle's `declaration_deadline_at`, unless the prospect's `late_declaration_waived` is true, else `ERR_DECLARATION_DEADLINE_PASSED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/declaration_deadline_priority_16_outranks_already_declared_priority_28
        """
        state = _declared_prospect(api)
        assert state["prospect"]["declared_at"] == DECLARED_AT
        set_clock(api, PAST_THE_DEADLINE)

        response = _declare_again(api, state["prospect"])
        validate_error(response, ERR_DECLARATION_DEADLINE_PASSED, expected_status=409)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["declaration_status"] == "DECLARED"
        assert prospect["declared_at"] == DECLARED_AT
        assert prospect["late_declaration_waived"] is False

    def test_repeated_declaration_surfaces_while_the_window_is_still_open(
        self, api: ApiClient
    ) -> None:
        """Inside the window the idempotence rule answers with 409.

        PRD: "Declaration idempotence — the prospect's `declaration_status` is `UNDECLARED` when the action is `DECLARE`, else `ERR_ALREADY_DECLARED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/declaration_deadline_priority_16_outranks_already_declared_priority_28
        """
        state = _declared_prospect(api)

        response = _declare_again(api, state["prospect"])
        validate_error(response, ERR_ALREADY_DECLARED, expected_status=409)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["declaration_status"] == "DECLARED"
        assert prospect["declared_at"] == DECLARED_AT

    def test_granted_late_relief_lets_the_repeated_declaration_surface(
        self, api: ApiClient
    ) -> None:
        """A waived prospect clears the window rule, so the repeat is reported.

        PRD: "It also grants the relief itself: a `LATE_DECLARATION` waiver sets the prospect's `late_declaration_waived` to true, and an `EARLY_ENTRY` waiver sets the prospect's `early_entry_waived` to true."

        PRD: "Declaration deadline — the current logical instant is at or before the cycle's `declaration_deadline_at`, unless the prospect's `late_declaration_waived` is true, else `ERR_DECLARATION_DEADLINE_PASSED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/declaration_deadline_priority_16_outranks_already_declared_priority_28
        """
        state = build_waiver_under_review(api, "LATE_DECLARATION")
        review_waiver(
            api,
            state["waiver"],
            "GRANT",
            state["decider_headers"],
            decision_note="Registrar confirmed the filing delay.",
        )
        relieved = read_prospect(api, state["prospect"]["id"])
        assert relieved["late_declaration_waived"] is True
        declared = declare_prospect(api, relieved)
        assert declared["declared_at"] == DECLARED_AT

        set_clock(api, PAST_THE_DEADLINE)
        response = _declare_again(api, declared)
        validate_error(response, ERR_ALREADY_DECLARED, expected_status=409)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["declaration_status"] == "DECLARED"
        assert prospect["late_declaration_waived"] is True
