"""Writes whose admissibility is decided by the state of a neighbouring row.

Three dependencies are exercised here. An escalation `COMMIT` reads the status
of the account's economic buyer; an expansion handoff reads the account's
derived `coverage_posture`, which in turn reads whether a coverage assignment is
still committed; and a forecast submit reads whether the account holds a
`COMMITTED` coverage assignment at all. In every case the row being written
never changes between the refused call and the accepted one; only the neighbour
does.
"""

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    ASSIGNMENT_RELEASED,
    CASE_ACTION_COMMIT,
    CASE_COMMITTED,
    CASE_OPEN,
    COMMITMENT_ACCEPTED,
    COMMITMENT_ACTION_ACCEPT,
    CS_STATE_DRAFT,
    CS_STATE_SUBMITTED,
    EXECUTIVE_HEADERS,
    FINANCE_STATE_PENDING,
    HEALTH_AMBER,
    OPPORTUNITY_ACTION_HANDOFF,
    OPPORTUNITY_HANDED_OFF,
    OPPORTUNITY_IDENTIFIED,
    PLAY_TYPE_EXEC_ALIGNMENT,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    RISK_SPONSOR_LOSS,
    SALES_AE_USER_ID,
    SENIORITY_DIRECTOR,
    SEVERITY_MEDIUM,
    SOURCE_FEATURE_DEPTH,
    SPONSOR_ACTIVE,
    SPONSOR_DEPARTED,
    ApiErrorId,
    add_buyer_sponsor,
    add_identified_opportunity,
    add_sponsor,
    assert_cents,
    assert_created,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assert_ok,
    assert_score,
    build_roster_and_account,
    build_trending_account,
    draft_save_play,
    factories,
    identify_opportunity,
    make_csm_headers,
    open_coverage,
    open_forecast,
    propose_commitment,
    raise_escalation,
    read_account,
    read_assignment,
    read_case,
    read_commitment,
    read_forecast,
    read_opportunity,
    release_coverage,
    transition_commitment,
    transition_opportunity,
    validate_error,
)

COMMITMENT_CREDIT_CENTS = 500_000
QUALIFIED_SCORE = 65.70

# PRD §3.6: an ENTERPRISE account at 30,000,000 cents judged UPSIDE takes the
# bottom-up weight 0.70, so the CS number is 21,000,000 cents.
UPSIDE_CS_AMOUNT_CENTS = 21_000_000
ENTERPRISE_AMBER_LOAD_UNITS = 17


def _set_sponsor_status(api, state, sponsor_id, status):
    """Amend one sponsor contact of the account to a new `status`."""
    return assert_ok(
        api.patch_sponsor_contact(
            sponsor_id,
            factories.sponsor_patch(status=status),
            make_csm_headers(state["csm_id"]),
        )
    )


def _case_awaiting_only_its_sponsor(api):
    """An OPEN case whose sole commitment is already ACCEPTED at round 1.

    The referential precondition of the `COMMIT` action is therefore satisfied
    before the first attempt, which leaves the buyer's status as the only thing
    that can decide the outcome.
    """
    state = build_roster_and_account(api, capacity_units_total=17)
    add_buyer_sponsor(api, state)
    play = draft_save_play(
        api,
        state["account_id"],
        state["csm_id"],
        "2026-08-05",
        "2026-09-05",
        risk_code=RISK_SPONSOR_LOSS,
        play_type=PLAY_TYPE_EXEC_ALIGNMENT,
    )
    case = raise_escalation(
        api,
        state["account_id"],
        play["id"],
        SEVERITY_MEDIUM,
        summary="Sponsor transition risk",
    )
    commitment = propose_commitment(
        api,
        case["id"],
        COMMITMENT_CREDIT_CENTS,
        "2026-09-30",
        case["version"],
        description="Named replacement sponsor within 30 days",
    )
    commitment = transition_commitment(
        api, commitment["id"], COMMITMENT_ACTION_ACCEPT
    )
    state["save_play"] = play
    state["case"] = case
    state["case_id"] = case["id"]
    state["commitment"] = commitment
    state["commitment_id"] = commitment["id"]
    return state


def _commit(api, case_id):
    """Attempt the `COMMIT` action as a CS executive."""
    return api.transition_escalation_case(
        case_id, factories.escalation_transition(CASE_ACTION_COMMIT), EXECUTIVE_HEADERS
    )


def _handoff(api, state, opportunity_id):
    """Attempt the `HANDOFF` action as the account's CSM."""
    return api.transition_expansion_opportunity(
        opportunity_id,
        factories.opportunity_transition(
            OPPORTUNITY_ACTION_HANDOFF, handoff_ae_user_id=SALES_AE_USER_ID
        ),
        make_csm_headers(state["csm_id"]),
    )


class TestEscalationCommitReadsTheSponsorStatus:
    """The `COMMIT` action of a case depends on the account's economic buyer."""

    def test_commit_is_refused_while_the_economic_buyer_is_departed(self, api):
        """A departed buyer blocks the COMMIT and moves nothing on the case.

        PRD §3.5: "Both edges require executive cover — the account must have a sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, or the request is refused with `ERR_SPONSOR_DEPARTED` — and at least one commitment of the case in state `ACCEPTED` whose `round_index` equals the case's current `remediation_round`, or the request is refused with `ERR_NO_ACCEPTED_COMMITMENT`."
        PRD §3.3: "Sponsors are created in `status` `ACTIVE`; the only other value is `DEPARTED`, and a departed sponsor drops out of every eligibility set the system evaluates."
        PRD §3.5: "Acceptance stamps `accepted_by_user_id` with the acting `X-User-ID` and increments the account's `remediation_credit_outstanding_cents` by the commitment's `credit_cents`."

        Design: Difficulty/cross_entity_state_dependency/escalation_commit_depends_on_sponsor_contact_status
        """
        state = _case_awaiting_only_its_sponsor(api)
        assert_field(state["commitment"], "state", COMMITMENT_ACCEPTED)
        _set_sponsor_status(api, state, state["sponsor_id"], SPONSOR_DEPARTED)

        validate_error(_commit(api, state["case_id"]), ApiErrorId.SPONSOR_DEPARTED)

        case = read_case(api, state["case_id"])
        assert_fields(case, {"state": CASE_OPEN, "remediation_round": 1})
        assert_null(case, "final_credit_cents")
        assert_credit_ledger(
            read_account(api, state["account_id"]), COMMITMENT_CREDIT_CENTS, 0
        )

    def test_the_identical_commit_succeeds_once_the_buyer_is_active_again(self, api):
        """Reactivating the same sponsor row is the only change the COMMIT needs.

        PRD §3.5: "Both edges require executive cover — the account must have a sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, or the request is refused with `ERR_SPONSOR_DEPARTED` — and at least one commitment of the case in state `ACCEPTED` whose `round_index` equals the case's current `remediation_round`, or the request is refused with `ERR_NO_ACCEPTED_COMMITMENT`."
        PRD §3.5: "It carries the case `OPEN → COMMITTED` or, closing the negotiation cycle, `DISPUTED → COMMITTED`."
        PRD §3.5: "Committing re-derives the account's `coverage_posture`."

        Design: Difficulty/cross_entity_state_dependency/escalation_commit_depends_on_sponsor_contact_status
        """
        state = _case_awaiting_only_its_sponsor(api)
        _set_sponsor_status(api, state, state["sponsor_id"], SPONSOR_DEPARTED)
        validate_error(_commit(api, state["case_id"]), ApiErrorId.SPONSOR_DEPARTED)

        restored = _set_sponsor_status(
            api, state, state["sponsor_id"], SPONSOR_ACTIVE
        )
        assert_field(restored, "status", SPONSOR_ACTIVE)

        committed = assert_ok(_commit(api, state["case_id"]))
        assert_fields(committed, {"state": CASE_COMMITTED, "remediation_round": 1})
        assert_field(
            read_commitment(api, state["case_id"], state["commitment_id"]),
            "state",
            COMMITMENT_ACCEPTED,
        )
        assert_credit_ledger(
            read_account(api, state["account_id"]), COMMITMENT_CREDIT_CENTS, 0
        )

    def test_a_departed_non_buyer_sponsor_does_not_block_the_commit(self, api):
        """Executive cover is read from the economic buyer, not from every contact.

        PRD §3.5: "Both edges require executive cover — the account must have a sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, or the request is refused with `ERR_SPONSOR_DEPARTED` — and at least one commitment of the case in state `ACCEPTED` whose `round_index` equals the case's current `remediation_round`, or the request is refused with `ERR_NO_ACCEPTED_COMMITMENT`."
        PRD §3.5: "It carries the case `OPEN → COMMITTED` or, closing the negotiation cycle, `DISPUTED → COMMITTED`."

        Design: Difficulty/cross_entity_state_dependency/escalation_commit_depends_on_sponsor_contact_status
        """
        state = _case_awaiting_only_its_sponsor(api)
        bystander = add_sponsor(
            api,
            state["account_id"],
            state["csm_id"],
            full_name="Lee Park",
            seniority=SENIORITY_DIRECTOR,
            is_economic_buyer=False,
        )
        _set_sponsor_status(api, state, bystander["id"], SPONSOR_DEPARTED)

        committed = assert_ok(_commit(api, state["case_id"]))
        assert_field(committed, "state", CASE_COMMITTED)


class TestExpansionHandoffReadsTheAccountPosture:
    """The `HANDOFF` action depends on the posture a coverage assignment derives."""

    def test_handoff_succeeds_while_a_committed_assignment_holds_the_posture_open(
        self, api
    ):
        """An AMBER account with committed coverage hands off a 65.70 opportunity.

        PRD §3.7: "The account's `coverage_posture` must be `OPEN`, not merely un-frozen; a `RESTRICTED` account — one with an open save play, a live escalation, or no committed coverage — is refused with `ERR_COVERAGE_POSTURE_RESTRICTED`, and a frozen one with `ERR_COVERAGE_POSTURE_FROZEN`."
        PRD §3.7: "The account's `health_tier` must be `AMBER` or `GREEN`, or the request is refused with `ERR_HEALTH_TIER_INELIGIBLE`."
        PRD §3.7: "The move carries the opportunity `IDENTIFIED → HANDED_OFF` and records that identifier, which from then on is the only user who may dispose of the row."

        Design: Difficulty/cross_entity_state_dependency/expansion_handoff_depends_on_account_posture_and_tier
        """
        state = build_trending_account(api, capacity_units_total=17)
        open_coverage(api, state, csm_id=state["csm_id"])
        assert_fields(
            state["account"],
            {"coverage_posture": POSTURE_OPEN, "health_tier": HEALTH_AMBER},
        )
        add_identified_opportunity(api, state)
        assert_score(
            state["opportunity"]["qualification_score"],
            QUALIFIED_SCORE,
            "qualification_score",
        )

        handed_off = assert_ok(_handoff(api, state, state["opportunity_id"]))
        assert_fields(
            handed_off,
            {
                "state": OPPORTUNITY_HANDED_OFF,
                "handoff_ae_user_id": SALES_AE_USER_ID,
            },
        )

    def test_releasing_the_assignment_blocks_the_next_handoff_of_the_same_account(
        self, api
    ):
        """Releasing coverage flips the posture and refuses a second 65.70 handoff.

        PRD §3.7: "The account's `coverage_posture` must be `OPEN`, not merely un-frozen; a `RESTRICTED` account — one with an open save play, a live escalation, or no committed coverage — is refused with `ERR_COVERAGE_POSTURE_RESTRICTED`, and a frozen one with `ERR_COVERAGE_POSTURE_FROZEN`."
        PRD §3.4: "Finally the released assignment's own account has `assigned_csm_id` cleared to null and its `coverage_posture` re-derived, yielding `RESTRICTED` because no `COMMITTED` assignment remains."
        PRD §3.7: "The `qualification_score` is computed at the moment the row is written and is never refreshed afterwards, so it records the account's condition when the opportunity was raised."

        Design: Difficulty/cross_entity_state_dependency/expansion_handoff_depends_on_account_posture_and_tier
        """
        state = build_trending_account(api, capacity_units_total=17)
        open_coverage(api, state, csm_id=state["csm_id"])
        first = identify_opportunity(api, state["account_id"], state["csm_id"])
        second = assert_created(
            api.create_expansion_opportunity(
                factories.expansion_opportunity(
                    state["account_id"], source_signal=SOURCE_FEATURE_DEPTH
                ),
                make_csm_headers(state["csm_id"]),
            )
        )
        transition_opportunity(
            api,
            first["id"],
            OPPORTUNITY_ACTION_HANDOFF,
            make_csm_headers(state["csm_id"]),
            handoff_ae_user_id=SALES_AE_USER_ID,
        )

        release_coverage(api, state["assignment_id"], release_reason="CSM went on leave")
        assert_field(
            read_assignment(api, state["assignment_id"]), "state", ASSIGNMENT_RELEASED
        )
        account = read_account(api, state["account_id"])
        assert_field(account, "coverage_posture", POSTURE_RESTRICTED)
        assert_null(account, "assigned_csm_id")

        validate_error(
            _handoff(api, state, second["id"]), ApiErrorId.COVERAGE_POSTURE_RESTRICTED
        )

        blocked = read_opportunity(api, second["id"])
        assert_fields(
            blocked,
            {"state": OPPORTUNITY_IDENTIFIED, "handoff_ae_user_id": None},
        )
        assert_score(
            blocked["qualification_score"], QUALIFIED_SCORE, "qualification_score"
        )

    def test_committing_coverage_unblocks_a_handoff_that_was_refused(self, api):
        """The identical handoff is admitted the moment an assignment is committed.

        PRD §3.7: "The account's `coverage_posture` must be `OPEN`, not merely un-frozen; a `RESTRICTED` account — one with an open save play, a live escalation, or no committed coverage — is refused with `ERR_COVERAGE_POSTURE_RESTRICTED`, and a frozen one with `ERR_COVERAGE_POSTURE_FROZEN`."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."
        PRD §3.7: "The `qualification_score` is computed at the moment the row is written and is never refreshed afterwards, so it records the account's condition when the opportunity was raised."

        Design: Difficulty/cross_entity_state_dependency/expansion_handoff_depends_on_account_posture_and_tier
        """
        state = build_trending_account(api, capacity_units_total=17)
        add_identified_opportunity(api, state)
        assert_fields(
            read_account(api, state["account_id"]),
            {"coverage_posture": POSTURE_RESTRICTED, "health_tier": HEALTH_AMBER},
        )
        assert_score(
            state["opportunity"]["qualification_score"],
            QUALIFIED_SCORE,
            "qualification_score",
        )

        validate_error(
            _handoff(api, state, state["opportunity_id"]),
            ApiErrorId.COVERAGE_POSTURE_RESTRICTED,
        )

        open_coverage(api, state, csm_id=state["csm_id"])
        assert_field(state["account"], "coverage_posture", POSTURE_OPEN)

        handed_off = assert_ok(_handoff(api, state, state["opportunity_id"]))
        assert_fields(
            handed_off,
            {
                "state": OPPORTUNITY_HANDED_OFF,
                "handoff_ae_user_id": SALES_AE_USER_ID,
            },
        )
        assert_score(
            handed_off["qualification_score"], QUALIFIED_SCORE, "qualification_score"
        )


def _unstaffed_account_with_a_draft_forecast(api):
    """A trending ENTERPRISE account, no coverage assignment, one DRAFT forecast.

    The account carries the three rising usage periods, so its trailing figure is
    67.20 with 152 days of term left and the forecast snapshots `UPSIDE`; nothing
    has been segmented or assigned, so the posture is `RESTRICTED`.
    """
    state = build_trending_account(api, capacity_units_total=ENTERPRISE_AMBER_LOAD_UNITS)
    forecast = open_forecast(
        api, state["account_id"], state["csm_id"], fiscal_period="2026Q4"
    )
    state["forecast"] = forecast
    state["forecast_id"] = forecast["id"]
    return state


def _submit(api, state):
    """Attempt the CS submit as the account's CSM."""
    return api.submit_renewal_forecast(
        state["forecast_id"], make_csm_headers(state["csm_id"])
    )


class TestForecastSubmitReadsTheCoverageAssignments:
    """The CS submit edge depends on a neighbouring `COMMITTED` assignment."""

    def test_submit_does_not_advance_an_unstaffed_account(self, api):
        """An account with no committed coverage may not submit its number.

        PRD §3.6: "The CS axis advances by submission. From `cs_state` `DRAFT` the forecast moves to `SUBMITTED`, requiring that at least one coverage assignment of the account be in state `COMMITTED` — an unstaffed account may not submit a number — and that `cs_amount_cents` not be null; the move stamps `submitted_at` with the logical clock and leaves `finance_state` untouched."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."
        PRD §3.6: "The new row starts with `cs_state` `DRAFT` and `finance_state` `PENDING`, with `finance_amount_cents`, `variance_cents`, `submitted_at` and `reconciled_at` all null, and it snapshots the account's current `renewal_likelihood` into `likelihood_category` — the forecast records the judgement of the moment it was written and does not track the account afterwards."

        Design: Difficulty/cross_entity_state_dependency/forecast_submit_depends_on_a_committed_coverage_assignment
        """
        state = _unstaffed_account_with_a_draft_forecast(api)
        assert_field(
            read_account(api, state["account_id"]),
            "coverage_posture",
            POSTURE_RESTRICTED,
        )

        refused = _submit(api, state)
        assert refused.status_code >= 400, (
            "an unstaffed account may not submit a number, but the submit "
            f"returned HTTP {refused.status_code}"
        )

        forecast = read_forecast(api, state["forecast_id"])
        assert_fields(
            forecast,
            {"cs_state": CS_STATE_DRAFT, "finance_state": FINANCE_STATE_PENDING},
        )
        assert_null(forecast, "submitted_at")
        assert_cents(
            forecast["cs_amount_cents"], UPSIDE_CS_AMOUNT_CENTS, "cs_amount_cents"
        )

    def test_the_identical_submit_succeeds_once_an_assignment_is_committed(self, api):
        """Committing coverage is the only change the untouched forecast needs.

        PRD §3.6: "The CS axis advances by submission. From `cs_state` `DRAFT` the forecast moves to `SUBMITTED`, requiring that at least one coverage assignment of the account be in state `COMMITTED` — an unstaffed account may not submit a number — and that `cs_amount_cents` not be null; the move stamps `submitted_at` with the logical clock and leaves `finance_state` untouched."
        PRD §3.4: "The single ceiling is load-bearing: a `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account at 30,000,000 cents gives 9 × 1.50 × 1.10 = 14.85, plus a surcharge of 2, giving 16.85, whose ceiling is `load_units` 17 — whereas taking a ceiling of the 13.50 sub-product before applying the risk multiplier would give 18, a different and incorrect cost."
        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."

        Design: Difficulty/cross_entity_state_dependency/forecast_submit_depends_on_a_committed_coverage_assignment
        """
        state = _unstaffed_account_with_a_draft_forecast(api)
        assert _submit(api, state).status_code >= 400

        open_coverage(api, state, csm_id=state["csm_id"])
        assignment = read_assignment(api, state["assignment_id"])
        assert_field(assignment, "state", ASSIGNMENT_COMMITTED)
        assert_field(assignment, "load_units", ENTERPRISE_AMBER_LOAD_UNITS)

        submitted = assert_ok(_submit(api, state))
        assert_fields(
            submitted,
            {"cs_state": CS_STATE_SUBMITTED, "finance_state": FINANCE_STATE_PENDING},
        )
        assert submitted["submitted_at"] is not None, "submitted_at was not stamped"
        assert_cents(
            submitted["cs_amount_cents"], UPSIDE_CS_AMOUNT_CENTS, "cs_amount_cents"
        )
