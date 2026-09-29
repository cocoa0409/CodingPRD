"""Weighted governance: the amendment loop, the approval boundary and the budget precondition."""

from test_helpers import (
    ActionType,
    ApiErrorId,
    BallotChoice,
    approve_annual_budget,
    assert_fields_equal,
    assert_tally,
    cast_action_ballot,
    cast_action_ballots,
    close_action_voting,
    create_petitioned_member,
    execute_membership_action,
    make_action_amend_payload,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_membership_action_payload,
    open_action_voting,
    propose_membership_action,
    read_conference,
    read_member,
    read_membership_action,
    setup_admit_action_in_voting,
    setup_charter_roster,
    validate_error,
    validate_success,
)


def _amend(api, action_id, **overrides):
    return validate_success(
        api.amend_membership_action(
            action_id,
            make_action_amend_payload(**overrides),
            headers=make_commissioner_headers(),
        )
    )


def _ballots(api, action_id):
    return validate_success(
        api.list_action_ballots(action_id, headers=make_compliance_officer_headers())
    )


def test_amendment_voids_cast_ballots_and_the_third_amendment_is_refused(api):
    """PRD §3.2: "Amending returns the action `VOTING` → `PROPOSED`, transitions every `CAST`
    ballot on it to `VOIDED`, resets `cast_weight_bps`, `for_weight_bps` and
    `approval_ratio_bps` to 0, increments `amend_count` by 1 and advances the action's
    `version`."
    PRD §3.2: "The membership can therefore be re-canvassed on revised terms, but not
    indefinitely: the loop terminates because an amendment is only accepted while
    `amend_count` is below the amendment limit of 2, and the third attempt is refused with
    `ERR_AMEND_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/membership_action_amend_cycle_then_reject_branch
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    ids = ctx["member_ids"]
    cast_action_ballot(api, action_id, ids["north"], BallotChoice.FOR.value)
    cast_action_ballot(api, action_id, ids["south"], BallotChoice.FOR.value)

    first = _amend(api, action_id, effective_fiscal_year=2029, rationale="Revised terms")

    assert_fields_equal(
        first,
        status="PROPOSED",
        amend_count=1,
        effective_fiscal_year=2029,
        cast_weight_bps=0,
        for_weight_bps=0,
        approval_ratio_bps=0,
    )
    for ballot in _ballots(api, action_id):
        assert ballot["status"] == "VOIDED", "an amendment voids every ballot cast so far"

    open_action_voting(api, action_id)
    second = _amend(api, action_id, effective_fiscal_year=2030, rationale="Second pass")
    assert_fields_equal(second, status="PROPOSED", amend_count=2)

    open_action_voting(api, action_id)
    refused = api.amend_membership_action(
        action_id,
        make_action_amend_payload(effective_fiscal_year=2031),
        headers=make_commissioner_headers(),
    )

    validate_error(refused, ApiErrorId.ERR_AMEND_LIMIT_REACHED.value, 409)
    still_voting = read_membership_action(api, action_id)
    assert_fields_equal(
        still_voting, status="VOTING", amend_count=2, effective_fiscal_year=2030
    )


def test_admit_rejected_after_the_amend_cycle_denies_the_petitioner(api):
    """PRD §3.2: "The decisive weight is `for_weight_bps` plus `against_weight_bps`, which
    deliberately excludes abstentions, and `approval_ratio_bps` is `for_weight_bps`
    multiplied by 10000 and divided by that decisive weight, rounded down to a whole basis
    point; when no decisive weight was cast at all the ratio is 0."
    PRD §3.2: "The two branches differ in their consequences: an approval leaves the subject
    member untouched and merely unlocks execution, while a rejection of an `ADMIT` also
    drives the subject institution `PETITIONED` → `ADMISSION_DENIED` with `voting_weight_bps`
    set to 0 and its `version` advanced."

    Design: Difficulty/non_linear_state_machine/membership_action_amend_cycle_then_reject_branch
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    ids = ctx["member_ids"]
    _amend(api, action_id, effective_fiscal_year=2029, rationale="Revised terms")
    open_action_voting(api, action_id)
    cast_action_ballots(
        api,
        action_id,
        (
            (ids["north"], BallotChoice.FOR.value),
            (ids["south"], BallotChoice.FOR.value),
            (ids["east"], BallotChoice.AGAINST.value),
            (ids["west"], BallotChoice.ABSTAIN.value),
        ),
    )

    closed = close_action_voting(api, action_id)

    # The abstention lifts the cast weight into quorum but stays out of the decisive
    # denominator, so 20000 for against 10000 against lands at 6666 basis points.
    assert_tally(
        closed,
        eligible_weight_bps=40000,
        cast_weight_bps=40000,
        for_weight_bps=20000,
        against_weight_bps=10000,
        quorum_met=True,
        approval_ratio_bps=6666,
        status="REJECTED",
    )
    subject = read_member(api, ids["central"])
    assert_fields_equal(
        subject,
        status="ADMISSION_DENIED",
        voting_weight_bps=0,
        distribution_phase_bps=0,
    )


def test_admit_vote_at_exactly_7500_bps_is_approved(api):
    """PRD §3.2: "It requires at least one member to carry a positive `voting_weight_bps` — a
    conference with nobody eligible to vote cannot hold a vote — and it fixes the approval
    threshold: `required_approval_bps` becomes 7500 for an `ADMIT` and 6000 for a `WITHDRAW`,
    reflecting that admitting a new school is a higher bar than releasing one."
    PRD §3.2: "The outcome is `APPROVED` when quorum was met and `approval_ratio_bps` is
    greater than or equal to `required_approval_bps`, and `REJECTED` otherwise; both
    comparisons are inclusive, so an `ADMIT` whose ratio lands on exactly 7500 basis points
    passes, and a `WITHDRAW` at exactly 6000 passes."

    Design: Difficulty/boundary_precision_check/admit_vote_approval_ratio_exactly_7500_bps_passes
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    ids = ctx["member_ids"]
    assert read_membership_action(api, action_id)["required_approval_bps"] == 7500
    cast_action_ballots(
        api,
        action_id,
        (
            (ids["north"], BallotChoice.FOR.value),
            (ids["south"], BallotChoice.FOR.value),
            (ids["east"], BallotChoice.FOR.value),
            (ids["west"], BallotChoice.AGAINST.value),
        ),
    )

    closed = close_action_voting(api, action_id)

    assert_tally(
        closed,
        eligible_weight_bps=40000,
        cast_weight_bps=40000,
        for_weight_bps=30000,
        against_weight_bps=10000,
        quorum_met=True,
        approval_ratio_bps=7500,
        status="APPROVED",
    )
    assert_fields_equal(closed, required_approval_bps=7500)


def test_admit_approved_on_the_inclusive_boundary_can_be_executed(api):
    """PRD §3.2: "The outcome is `APPROVED` when quorum was met and `approval_ratio_bps` is
    greater than or equal to `required_approval_bps`, and `REJECTED` otherwise; both
    comparisons are inclusive, so an `ADMIT` whose ratio lands on exactly 7500 basis points
    passes, and a `WITHDRAW` at exactly 6000 passes."
    PRD §3.2: "For an `ADMIT`, the subject member moves `PETITIONED` → `ADMITTED_PHASING`
    with `phase_year` set to 1, the phase multiplier re-derived from that (2500 basis points
    under the default three-year ladder), `voting_weight_bps` set equal to
    `distribution_phase_bps`, and the action's `entry_fee_cents` copied onto the member as
    its assessment; an execution attempted while the institution still owes an assessed entry
    fee is refused with `ERR_ENTRY_FEE_OUTSTANDING`."

    Design: Difficulty/boundary_precision_check/admit_vote_approval_ratio_exactly_7500_bps_passes
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    ids = ctx["member_ids"]
    cast_action_ballots(
        api,
        action_id,
        (
            (ids["north"], BallotChoice.FOR.value),
            (ids["south"], BallotChoice.FOR.value),
            (ids["east"], BallotChoice.FOR.value),
            (ids["west"], BallotChoice.AGAINST.value),
        ),
    )
    close_action_voting(api, action_id)

    executed = execute_membership_action(api, action_id)

    assert_fields_equal(executed, status="EXECUTED", approval_ratio_bps=7500)
    admitted = read_member(api, ids["central"])
    assert_fields_equal(
        admitted,
        status="ADMITTED_PHASING",
        phase_year=1,
        distribution_phase_bps=2500,
        voting_weight_bps=2500,
        entry_fee_cents=0,
    )


def test_admit_proposal_without_an_approved_budget_is_refused(api):
    """PRD §3.2: "An `ADMIT` proposal additionally requires the conference to have an approved
    budget in place for its `current_fiscal_year`; without one the proposal fails with
    `ERR_NO_APPROVED_BUDGET`, because the office may not commit to a new member's phased
    shares before the membership has adopted a budget."

    Design: Difficulty/cross_entity_state_dependency/admit_action_depends_on_approved_budget_for_current_year
    """
    ctx = setup_charter_roster(api)
    petitioner = create_petitioned_member(api, ctx)
    assert read_conference(api)["governance_status"] == "FORMING"

    refused = api.create_membership_action(
        make_membership_action_payload(
            ctx["conference_id"],
            petitioner["id"],
            action_type=ActionType.ADMIT.value,
            effective_fiscal_year=2028,
            entry_fee_cents=0,
        ),
        headers=make_commissioner_headers(),
    )

    validate_error(refused, ApiErrorId.ERR_NO_APPROVED_BUDGET.value, 409)
    actions = validate_success(
        api.list_membership_actions(headers=make_commissioner_headers())
    )
    assert actions == [], "a refused proposal leaves no membership action behind"


def test_admit_proposal_is_accepted_once_the_annual_budget_is_approved(api):
    """PRD §3.2: "An `ADMIT` proposal additionally requires the conference to have an approved
    budget in place for its `current_fiscal_year`; without one the proposal fails with
    `ERR_NO_APPROVED_BUDGET`, because the office may not commit to a new member's phased
    shares before the membership has adopted a budget."
    PRD §3.3: "An approval, by contrast, records `approved_by_user_id` from the acting
    `X-User-ID`, copies `proposed_operating_expense_cents` into the conference's
    `approved_operating_expense_cents` and `proposed_governance_expense_cents` into its
    `approved_governance_expense_cents`, recomputes `reserve_target_cents` as 15 percent of
    the newly approved operating expense rounded up to the next cent, re-derives
    `reserve_posture` and `funded_ratio_bps` from that new target, moves `governance_status`
    `FORMING` → `OPERATING` if the conference was still forming, and advances the
    conference's `version` by 1 in addition to the proposal's."

    Design: Difficulty/cross_entity_state_dependency/admit_action_depends_on_approved_budget_for_current_year
    """
    ctx = setup_charter_roster(api)
    charter_voter_ids = list(ctx["member_ids"].values())
    petitioner = create_petitioned_member(api, ctx)

    proposal = approve_annual_budget(api, ctx["conference_id"], charter_voter_ids)

    assert_fields_equal(
        proposal, status="APPROVED", approval_ratio_bps=10000, required_approval_bps=6670
    )
    conference = read_conference(api)
    assert_fields_equal(
        conference,
        governance_status="OPERATING",
        approved_operating_expense_cents=120_000_000,
        reserve_target_cents=18_000_000,
        reserve_balance_cents=0,
        reserve_posture="FROZEN",
    )

    action = propose_membership_action(
        api,
        ctx["conference_id"],
        petitioner["id"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
        entry_fee_cents=0,
    )

    assert_fields_equal(
        action,
        status="PROPOSED",
        amend_count=0,
        quorum_weight_bps=6000,
        member_id=petitioner["id"],
        version=1,
    )
