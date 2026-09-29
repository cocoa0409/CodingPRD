"""Ordering conflicts on the validation ladder of PRD §2.9.

Each pair of rules below is provoked twice. First with both violations present at
once, where the lower-numbered rule must be the one that answers; then with only
the higher-numbered violation present, which proves the first answer came from
the ordering rather than from a coincidence of the fixture.
"""

from test_helpers import (
    CASE_ACTION_COMMIT,
    CASE_OPEN,
    CHURN_PRODUCT_GAP,
    COMMITMENT_PROPOSED,
    ENGAGEMENT_TYPE_EBR,
    EXECUTIVE_HEADERS,
    HEALTH_AMBER,
    LIFECYCLE_ACTION_CHURN,
    LIFECYCLE_CHURNED,
    OPPORTUNITY_ACTION_HANDOFF,
    OPPORTUNITY_IDENTIFIED,
    OPS_ADMIN_HEADERS,
    PLAY_TYPE_EXEC_ALIGNMENT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    RISK_SPONSOR_LOSS,
    SALES_AE_USER_ID,
    SEVERITY_CRITICAL,
    SPONSOR_ACTIVE,
    SPONSOR_DEPARTED,
    ApiErrorId,
    add_buyer_sponsor,
    add_outcome_goal,
    add_usage_signal,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_ok,
    assert_score,
    build_roster_and_account,
    draft_save_play,
    drive_lifecycle,
    factories,
    identify_opportunity,
    list_rows,
    make_csm_headers,
    open_coverage,
    propose_commitment,
    raise_escalation,
    read_account,
    read_case,
    read_commitment,
    read_opportunity,
    schedule_engagement,
    validate_error,
)

# The sponsor's standing booking, and the two candidate windows measured against
# it: 15:15 sits inside the 30-minute buffer that follows a 15:00 end.
EXISTING_START = "2026-08-10T14:00:00Z"
EXISTING_END = "2026-08-10T15:00:00Z"
BUFFERED_START = "2026-08-10T15:15:00Z"
BUFFERED_END = "2026-08-10T16:00:00Z"


def _set_sponsor_status(api, state, status):
    """Amend the account's sponsor to a new `status`."""
    return assert_ok(
        api.patch_sponsor_contact(
            state["sponsor_id"],
            factories.sponsor_patch(status=status),
            make_csm_headers(state["csm_id"]),
        )
    )


def _sponsor_with_a_standing_engagement(api):
    """An account whose CXO economic buyer already holds a 14:00-15:00 window."""
    state = build_roster_and_account(api)
    add_buyer_sponsor(api, state)
    state["engagement"] = schedule_engagement(
        api,
        state["account_id"],
        state["csm_id"],
        state["sponsor_id"],
        EXISTING_START,
        EXISTING_END,
    )
    return state


def _amber_account_below_the_qualification_floor(api, with_coverage):
    """An AMBER account whose single opportunity scores 54.75.

    One usage period of index 40.00 plus an ACTIVE economic buyer gives
    `snapshot_health_score` and `trended_health_score` 61.50, so the tier is
    AMBER and the health rule of PRD §2.9 rule 18 cannot fire. Committing
    coverage is the only thing that lifts the posture from RESTRICTED to OPEN.
    """
    state = build_roster_and_account(api, capacity_units_total=17)
    add_buyer_sponsor(api, state)
    add_usage_signal(
        api, state["account_id"], state["csm_id"], "2026-07-31", 40, 100, 40.00
    )
    if with_coverage:
        open_coverage(api, state, csm_id=state["csm_id"])
    state["account"] = read_account(api, state["account_id"])
    state["opportunity"] = identify_opportunity(
        api,
        state["account_id"],
        state["csm_id"],
        estimated_value_cents=4_000_000,
    )
    state["opportunity_id"] = state["opportunity"]["id"]
    return state


def _open_case_with_only_a_proposed_commitment(api):
    """An OPEN case at round 1 whose single commitment was never accepted."""
    state = build_roster_and_account(api)
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
        SEVERITY_CRITICAL,
        summary="Economic buyer left mid-term",
    )
    commitment = propose_commitment(
        api,
        case["id"],
        500_000,
        "2026-09-30",
        case["version"],
        description="Executive alignment workshop",
    )
    state["save_play"] = play
    state["case"] = case
    state["case_id"] = case["id"]
    state["commitment"] = commitment
    state["commitment_id"] = commitment["id"]
    return state


class TestFrozenPostureOutranksTheWeightBudget:
    """Outcome-goal creation answers with the posture error, not the fiscal one."""

    def test_frozen_posture_answers_when_the_goal_also_overflows_the_budget(self, api):
        """A churned account refuses a 1,000 bp goal that would also reach 10,500 bp.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "This ordering is observable: a request that violates several rules at once must surface the lowest-numbered violation."
        PRD §2.9: "**Posture not frozen.** The owning account's `coverage_posture` is not `FROZEN`. Violation: `ERR_COVERAGE_POSTURE_FROZEN` (409). Applies to nine operations: outcome-goal creation, executive-engagement creation, onboarding-milestone creation, the `COMPLETE` action of an onboarding-milestone transition (and only that action), expansion-opportunity creation, every action of an expansion-opportunity transition, advocacy-enrollment creation, renewal-forecast creation and renewal-forecast submit, plus save-play creation."
        PRD §2.9: "**Outcome weight budget.** The sum of `weight_bp` over the account's outcome goals that are not `WAIVED`, counting the row being created, does not exceed 10,000 basis points. Violation: `ERR_WEIGHT_TOTAL_INVALID` (422). Applies to outcome-goal creation."
        PRD §3.9: "Every churn requires a `churn_root_cause_code`, drawn from `PRODUCT_GAP`, `PRICE`, `SPONSOR_CHURN`, `POOR_ONBOARDING`, `SUPPORT_QUALITY` and `MERGER_ACQUISITION`, stores it on the account, and ends by re-deriving `coverage_posture`, which necessarily yields `FROZEN` because the first posture clause matches on lifecycle alone."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_outcome_weight_overflow_on_goal_create
        """
        state = build_roster_and_account(api)
        add_outcome_goal(
            api,
            state["account_id"],
            state["csm_id"],
            9500,
            100,
            title="Adoption of the analytics module",
            actual_value=40,
        )
        churned = drive_lifecycle(
            api,
            state["account_id"],
            LIFECYCLE_ACTION_CHURN,
            churn_root_cause_code=CHURN_PRODUCT_GAP,
        )
        assert_fields(
            churned,
            {
                "lifecycle_state": LIFECYCLE_CHURNED,
                "coverage_posture": POSTURE_FROZEN,
            },
        )

        response = api.create_outcome_goal(
            state["account_id"],
            factories.outcome_goal(1000, 100, title="Second workspace rollout"),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.COVERAGE_POSTURE_FROZEN)

        rows = list_rows(
            api.list_outcome_goals(
                state["account_id"], OPS_ADMIN_HEADERS, {"limit": 100}
            )
        )
        assert len(rows) == 1, f"the refused goal must not be written: {rows}"

    def test_weight_budget_answers_alone_while_the_posture_is_not_frozen(self, api):
        """The same 1,000 bp goal on a RESTRICTED account surfaces the budget error.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "**Posture not frozen.** The owning account's `coverage_posture` is not `FROZEN`. Violation: `ERR_COVERAGE_POSTURE_FROZEN` (409). Applies to nine operations: outcome-goal creation, executive-engagement creation, onboarding-milestone creation, the `COMPLETE` action of an onboarding-milestone transition (and only that action), expansion-opportunity creation, every action of an expansion-opportunity transition, advocacy-enrollment creation, renewal-forecast creation and renewal-forecast submit, plus save-play creation."
        PRD §2.9: "**Outcome weight budget.** The sum of `weight_bp` over the account's outcome goals that are not `WAIVED`, counting the row being created, does not exceed 10,000 basis points. Violation: `ERR_WEIGHT_TOTAL_INVALID` (422). Applies to outcome-goal creation."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_outcome_weight_overflow_on_goal_create
        """
        state = build_roster_and_account(api)
        add_outcome_goal(
            api,
            state["account_id"],
            state["csm_id"],
            9500,
            100,
            title="Adoption of the analytics module",
            actual_value=40,
        )
        assert_field(
            read_account(api, state["account_id"]),
            "coverage_posture",
            POSTURE_RESTRICTED,
        )

        response = api.create_outcome_goal(
            state["account_id"],
            factories.outcome_goal(1000, 100, title="Second workspace rollout"),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.WEIGHT_TOTAL_INVALID)

        rows = list_rows(
            api.list_outcome_goals(
                state["account_id"], OPS_ADMIN_HEADERS, {"limit": 100}
            )
        )
        assert len(rows) == 1, f"the refused goal must not be written: {rows}"


class TestDepartedSponsorOutranksTheCalendarConflict:
    """Engagement creation answers with the sponsor error, not the calendar one."""

    def test_departed_sponsor_answers_when_the_window_also_collides(self, api, clock):
        """A 15:15 booking against a departed sponsor's 14:00-15:00 window is a 422.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "This ordering is observable: a request that violates several rules at once must surface the lowest-numbered violation."
        PRD §2.9: "**Sponsor availability.** Any sponsor contact the operation involves has `status` `ACTIVE`, and where the operation requires executive cover the account has a sponsor contact whose `is_economic_buyer` is true and whose `status` is `ACTIVE`. Violation: `ERR_SPONSOR_DEPARTED` (422). Applies to executive-engagement creation and to the `COMMIT` action of an escalation-case transition."
        PRD §2.9: "**Sponsor calendar conflict.** The proposed engagement window does not conflict with any `SCHEDULED` or `HELD` engagement of the same `sponsor_contact_id`, under the buffered comparison described in §3.3. Violation: `ERR_ENGAGEMENT_WINDOW_CONFLICT` (409). Applies to executive-engagement creation."
        PRD §3.3: "The strictness matters at the seam: against an existing engagement running 14:00 to 15:00, a candidate starting at 15:15 conflicts, a candidate starting at exactly 15:30 does not, and a candidate running 13:00 to 13:30 does not, because ending exactly at the buffered lower bound is not "strictly later" than it."

        Design: Difficulty/priority_pair_validation_conflict/departed_sponsor_outranks_engagement_window_conflict
        """
        state = _sponsor_with_a_standing_engagement(api)
        departed = _set_sponsor_status(api, state, SPONSOR_DEPARTED)
        assert_field(departed, "status", SPONSOR_DEPARTED)

        response = api.create_executive_engagement(
            state["account_id"],
            factories.executive_engagement(
                state["sponsor_id"],
                BUFFERED_START,
                BUFFERED_END,
                engagement_type=ENGAGEMENT_TYPE_EBR,
            ),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.SPONSOR_DEPARTED)

        calendar = list_rows(
            api.list_sponsor_engagements(
                state["sponsor_id"], OPS_ADMIN_HEADERS, {"limit": 100}
            )
        )
        assert [row["id"] for row in calendar] == [state["engagement"]["id"]], (
            f"the refused engagement must not join the calendar: {calendar}"
        )

    def test_calendar_conflict_answers_alone_while_the_sponsor_is_active(
        self, api, clock
    ):
        """The same 15:15 booking against an ACTIVE sponsor surfaces the 409 instead.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "**Sponsor availability.** Any sponsor contact the operation involves has `status` `ACTIVE`, and where the operation requires executive cover the account has a sponsor contact whose `is_economic_buyer` is true and whose `status` is `ACTIVE`. Violation: `ERR_SPONSOR_DEPARTED` (422). Applies to executive-engagement creation and to the `COMMIT` action of an escalation-case transition."
        PRD §2.9: "**Sponsor calendar conflict.** The proposed engagement window does not conflict with any `SCHEDULED` or `HELD` engagement of the same `sponsor_contact_id`, under the buffered comparison described in §3.3. Violation: `ERR_ENGAGEMENT_WINDOW_CONFLICT` (409). Applies to executive-engagement creation."
        PRD §3.3: "Sponsors are created in `status` `ACTIVE`; the only other value is `DEPARTED`, and a departed sponsor drops out of every eligibility set the system evaluates."

        Design: Difficulty/priority_pair_validation_conflict/departed_sponsor_outranks_engagement_window_conflict
        """
        state = _sponsor_with_a_standing_engagement(api)
        assert_field(state["sponsor"], "status", SPONSOR_ACTIVE)

        response = api.create_executive_engagement(
            state["account_id"],
            factories.executive_engagement(
                state["sponsor_id"],
                BUFFERED_START,
                BUFFERED_END,
                engagement_type=ENGAGEMENT_TYPE_EBR,
            ),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.ENGAGEMENT_WINDOW_CONFLICT)

        calendar = list_rows(
            api.list_sponsor_engagements(
                state["sponsor_id"], OPS_ADMIN_HEADERS, {"limit": 100}
            )
        )
        assert [row["id"] for row in calendar] == [state["engagement"]["id"]], (
            f"the refused engagement must not join the calendar: {calendar}"
        )


class TestRestrictedPostureOutranksTheQualificationFloor:
    """The handoff answers with the posture error, not the qualification one."""

    def test_restricted_posture_answers_when_the_score_is_also_too_low(self, api):
        """An unstaffed AMBER account refuses a handoff scored 54.75 with a 409.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "This ordering is observable: a request that violates several rules at once must surface the lowest-numbered violation."
        PRD §2.9: "**Posture open.** The owning account's `coverage_posture` is `OPEN` rather than `RESTRICTED`. Violation: `ERR_COVERAGE_POSTURE_RESTRICTED` (409). Applies to exactly two operations: the `HANDOFF` action of an expansion-opportunity transition, and the `APPROVE` action of an advocacy-enrollment transition."
        PRD §2.9: "**Qualification floor.** For a `HANDOFF` expansion action, the opportunity's `qualification_score` is at least 65.00. Violation: `ERR_QUALIFICATION_SCORE_TOO_LOW` (422). Applies to the expansion-opportunity transition endpoint."
        PRD §2.9: "**Health-tier eligibility.** The account's `health_tier` belongs to the set the operation requires: `RED` or `AMBER` to activate a save play; `AMBER` or `GREEN` to hand off an expansion opportunity or to activate an advocacy enrollment; `GREEN` alone to approve an advocacy nomination. Violation: `ERR_HEALTH_TIER_INELIGIBLE` (422). Applies to the `ACTIVATE` action of a save-play transition, the `HANDOFF` action of an expansion-opportunity transition, and the `APPROVE` and `ACTIVATE` actions of an advocacy-enrollment transition."

        Design: Difficulty/priority_pair_validation_conflict/restricted_posture_outranks_low_qualification_score_on_handoff
        """
        state = _amber_account_below_the_qualification_floor(api, with_coverage=False)
        assert_fields(
            state["account"],
            {
                "coverage_posture": POSTURE_RESTRICTED,
                "health_tier": HEALTH_AMBER,
            },
        )
        assert_score(
            state["opportunity"]["qualification_score"], 54.75, "qualification_score"
        )

        response = api.transition_expansion_opportunity(
            state["opportunity_id"],
            factories.opportunity_transition(
                OPPORTUNITY_ACTION_HANDOFF, handoff_ae_user_id=SALES_AE_USER_ID
            ),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.COVERAGE_POSTURE_RESTRICTED)

        opportunity = read_opportunity(api, state["opportunity_id"])
        assert_fields(
            opportunity,
            {"state": OPPORTUNITY_IDENTIFIED, "handoff_ae_user_id": None},
        )

    def test_qualification_floor_answers_alone_once_the_posture_is_open(self, api):
        """The same 54.75 handoff on a staffed account surfaces the 422 instead.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "**Posture open.** The owning account's `coverage_posture` is `OPEN` rather than `RESTRICTED`. Violation: `ERR_COVERAGE_POSTURE_RESTRICTED` (409). Applies to exactly two operations: the `HANDOFF` action of an expansion-opportunity transition, and the `APPROVE` action of an advocacy-enrollment transition."
        PRD §2.9: "**Qualification floor.** For a `HANDOFF` expansion action, the opportunity's `qualification_score` is at least 65.00. Violation: `ERR_QUALIFICATION_SCORE_TOO_LOW` (422). Applies to the expansion-opportunity transition endpoint."
        PRD §3.7: "The `qualification_score` must be at least 65.00, an inclusive floor, so a score of exactly 65.00 qualifies while 64.99 is refused with `ERR_QUALIFICATION_SCORE_TOO_LOW`."

        Design: Difficulty/priority_pair_validation_conflict/restricted_posture_outranks_low_qualification_score_on_handoff
        """
        state = _amber_account_below_the_qualification_floor(api, with_coverage=True)
        assert_fields(
            state["account"],
            {
                "coverage_posture": POSTURE_OPEN,
                "health_tier": HEALTH_AMBER,
            },
        )
        assert_score(
            state["opportunity"]["qualification_score"], 54.75, "qualification_score"
        )

        response = api.transition_expansion_opportunity(
            state["opportunity_id"],
            factories.opportunity_transition(
                OPPORTUNITY_ACTION_HANDOFF, handoff_ae_user_id=SALES_AE_USER_ID
            ),
            make_csm_headers(state["csm_id"]),
        )
        validate_error(response, ApiErrorId.QUALIFICATION_SCORE_TOO_LOW)

        opportunity = read_opportunity(api, state["opportunity_id"])
        assert_fields(
            opportunity,
            {"state": OPPORTUNITY_IDENTIFIED, "handoff_ae_user_id": None},
        )


class TestDepartedSponsorOutranksTheCommitmentRequirement:
    """The COMMIT action answers with the sponsor error, not the referential one."""

    def test_departed_sponsor_answers_when_no_commitment_is_accepted_either(self, api):
        """A case with only a PROPOSED commitment and a departed buyer is a 422 sponsor error.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "This ordering is observable: a request that violates several rules at once must surface the lowest-numbered violation."
        PRD §2.9: "**Sponsor availability.** Any sponsor contact the operation involves has `status` `ACTIVE`, and where the operation requires executive cover the account has a sponsor contact whose `is_economic_buyer` is true and whose `status` is `ACTIVE`. Violation: `ERR_SPONSOR_DEPARTED` (422). Applies to executive-engagement creation and to the `COMMIT` action of an escalation-case transition."
        PRD §2.9: "**Commitment support for the escalation action.** For a `COMMIT` escalation action, at least one remediation commitment of the case is in state `ACCEPTED` with a `round_index` equal to the case's current `remediation_round`. For a `RESOLVE` escalation action, every commitment of the case is in state `DELIVERED`, `REJECTED` or `WITHDRAWN`, and at least one is `DELIVERED`. Violation: `ERR_NO_ACCEPTED_COMMITMENT` (422). Applies to the escalation-case transition endpoint."
        PRD §3.5: "Both edges require executive cover — the account must have a sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, or the request is refused with `ERR_SPONSOR_DEPARTED` — and at least one commitment of the case in state `ACCEPTED` whose `round_index` equals the case's current `remediation_round`, or the request is refused with `ERR_NO_ACCEPTED_COMMITMENT`."

        Design: Difficulty/priority_pair_validation_conflict/departed_sponsor_outranks_missing_accepted_commitment_on_commit
        """
        state = _open_case_with_only_a_proposed_commitment(api)
        _set_sponsor_status(api, state, SPONSOR_DEPARTED)

        response = api.transition_escalation_case(
            state["case_id"],
            factories.escalation_transition(CASE_ACTION_COMMIT),
            EXECUTIVE_HEADERS,
        )
        validate_error(response, ApiErrorId.SPONSOR_DEPARTED)

        case = read_case(api, state["case_id"])
        assert_fields(case, {"state": CASE_OPEN, "remediation_round": 1})
        commitment = read_commitment(api, state["case_id"], state["commitment_id"])
        assert_field(commitment, "state", COMMITMENT_PROPOSED)
        assert_credit_ledger(read_account(api, state["account_id"]), 0, 0)

    def test_commitment_requirement_answers_alone_while_the_buyer_is_active(self, api):
        """The same COMMIT with an ACTIVE buyer surfaces the referential error.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "**Sponsor availability.** Any sponsor contact the operation involves has `status` `ACTIVE`, and where the operation requires executive cover the account has a sponsor contact whose `is_economic_buyer` is true and whose `status` is `ACTIVE`. Violation: `ERR_SPONSOR_DEPARTED` (422). Applies to executive-engagement creation and to the `COMMIT` action of an escalation-case transition."
        PRD §2.9: "**Commitment support for the escalation action.** For a `COMMIT` escalation action, at least one remediation commitment of the case is in state `ACCEPTED` with a `round_index` equal to the case's current `remediation_round`. For a `RESOLVE` escalation action, every commitment of the case is in state `DELIVERED`, `REJECTED` or `WITHDRAWN`, and at least one is `DELIVERED`. Violation: `ERR_NO_ACCEPTED_COMMITMENT` (422). Applies to the escalation-case transition endpoint."
        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."

        Design: Difficulty/priority_pair_validation_conflict/departed_sponsor_outranks_missing_accepted_commitment_on_commit
        """
        state = _open_case_with_only_a_proposed_commitment(api)
        assert_field(state["sponsor"], "status", SPONSOR_ACTIVE)

        response = api.transition_escalation_case(
            state["case_id"],
            factories.escalation_transition(CASE_ACTION_COMMIT),
            EXECUTIVE_HEADERS,
        )
        validate_error(response, ApiErrorId.NO_ACCEPTED_COMMITMENT)

        case = read_case(api, state["case_id"])
        assert_fields(case, {"state": CASE_OPEN, "remediation_round": 1})
        commitment = read_commitment(api, state["case_id"], state["commitment_id"])
        assert_field(commitment, "state", COMMITMENT_PROPOSED)
        assert_credit_ledger(read_account(api, state["account_id"]), 0, 0)
