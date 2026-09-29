"""The state machines: declared initial states, terminal lockdown, replayed triggers and cascades."""

from test_helpers import (
    FINANCE_OFFICER_USER_ID,
    ActionType,
    ApiErrorId,
    RunVariant,
    approve_annual_budget,
    assert_compliance_breakdown,
    assert_fields_equal,
    assert_posture,
    assert_tally,
    award_championship_event,
    begin_bowl_review,
    cancel_game,
    cast_action_ballot,
    compute_run,
    create_petitioned_member,
    create_protected_rivalry,
    create_revenue_pool,
    create_schedule_game,
    draft_budget_proposal,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_distribution_run_payload,
    make_finance_officer_headers,
    make_schedule_coordinator_headers,
    make_treasurer_headers,
    open_action_voting,
    open_revenue_pool,
    play_game,
    propose_membership_action,
    read_conference,
    read_member,
    read_membership_action,
    read_revenue_pool,
    read_run_lines,
    setup_admit_action_in_voting,
    setup_charter_roster,
    setup_closed_media_pool,
    setup_computed_fy2026_final_run,
    setup_operating_conference,
    setup_operating_conference_with_reserve,
    setup_posted_fy2026_distribution,
    submit_bowl_appearance,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_run(api, run_id):
    return validate_success(
        api.get_distribution_run(run_id, headers=make_finance_officer_headers())
    )


def _read_game(api, game_id):
    return validate_success(
        api.get_schedule_game(game_id, headers=make_schedule_coordinator_headers())
    )


def _read_rivalry(api, rivalry_id):
    return validate_success(
        api.get_protected_rivalry(rivalry_id, headers=make_schedule_coordinator_headers())
    )


def _read_event(api, event_id):
    return validate_success(
        api.get_championship_event(event_id, headers=make_schedule_coordinator_headers())
    )


def _read_appearance(api, appearance_id):
    return validate_success(
        api.get_bowl_appearance(appearance_id, headers=make_compliance_officer_headers())
    )


def _read_proposal(api, proposal_id):
    return validate_success(
        api.get_budget_proposal(proposal_id, headers=make_finance_officer_headers())
    )


def _read_compliance(api, member_id):
    return validate_success(
        api.get_schedule_compliance(member_id, headers=make_compliance_officer_headers())
    )


def test_closing_a_unanimous_budget_ballot_also_graduates_the_conference(api):
    """PRD §3.3: "Closing the budget ballot is the `FinanceOfficer`'s act and uses the same
    tally arithmetic as a membership action: only `CAST` ballots count, `eligible_weight_bps` is
    snapshotted at close, abstentions raise `cast_weight_bps` but stay out of the decisive
    denominator, `approval_ratio_bps` is the for-weight multiplied by 10000 divided by the
    decisive weight rounded down, and `quorum_met` is true when `cast_weight_bps` multiplied by
    10000 is at least `eligible_weight_bps` multiplied by 6000."
    PRD §3.3: "The proposal is `APPROVED` when quorum was met and the ratio is greater than or
    equal to 6670 basis points, and `REJECTED` otherwise; in both cases the tally fields
    `eligible_weight_bps`, `cast_weight_bps`, `for_weight_bps`, `against_weight_bps`,
    `quorum_met` and `approval_ratio_bps` are written and the proposal's `version` advances."
    PRD §3.3: "An approval, by contrast, records `approved_by_user_id` from the acting
    `X-User-ID`, copies `proposed_operating_expense_cents` into the conference's
    `approved_operating_expense_cents` and `proposed_governance_expense_cents` into its
    `approved_governance_expense_cents`, recomputes `reserve_target_cents` as 15 percent of the
    newly approved operating expense rounded up to the next cent, re-derives `reserve_posture`
    and `funded_ratio_bps` from that new target, moves `governance_status` `FORMING` →
    `OPERATING` if the conference was still forming, and advances the conference's `version` by
    1 in addition to the proposal's."
    PRD §2.10: "The posture, `reserve_posture`, is one of `OPEN`, `RESERVE_RESTRICTED` or
    `FROZEN`, and is derived by comparing the balance against the target without dividing:
    when the target is 0 the posture is `OPEN`; otherwise, if the balance multiplied by 10000
    is less than the target multiplied by 2500 basis points the posture is `FROZEN`;
    otherwise, if the balance multiplied by 10000 is less than the target multiplied by 6000
    basis points the posture is `RESERVE_RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Corner/state_machines/corner_budget_approval_transitions_conference_to_operating
    """
    ctx = setup_charter_roster(api)
    assert read_conference(api)["governance_status"] == "FORMING"

    # Draft the FY2027 budget, put it to the membership, collect four FOR ballots and close.
    proposal = approve_annual_budget(
        api, ctx["conference_id"], list(ctx["member_ids"].values())
    )

    assert_fields_equal(
        proposal,
        status="APPROVED",
        approved_by_user_id=FINANCE_OFFICER_USER_ID,
        required_approval_bps=6670,
    )
    assert_tally(
        proposal,
        eligible_weight_bps=40000,
        cast_weight_bps=40000,
        for_weight_bps=40000,
        against_weight_bps=0,
        quorum_met=True,
        approval_ratio_bps=10000,
    )
    # One call moves two aggregates: the proposal and the conference record.
    conference = read_conference(api)
    assert_fields_equal(
        conference,
        governance_status="OPERATING",
        approved_operating_expense_cents=120_000_000,
        approved_governance_expense_cents=20_000_000,
        reserve_target_cents=18_000_000,
        reserve_balance_cents=0,
    )
    assert_posture(conference, "FROZEN", 0)


def test_the_finance_side_creates_land_on_their_declared_initial_states(api):
    """PRD §3.7: "The pool is created in `DRAFT` with `audited_expense_cents` null and `version`
    1."
    PRD §3.1: "`PETITIONED` is the other path: the institution is created in status
    `PETITIONED` with `distribution_phase_bps` of 0, `voting_weight_bps` of 0, `phase_year` of
    0 and `entry_fee_paid_cents` of 0."
    PRD §3.2: "A new action is created in `PROPOSED` with `amend_count` of 0,
    `quorum_weight_bps` of 6000, `proposed_by_user_id` taken from the acting `X-User-ID`, and
    `version` 1."
    PRD §3.3: "The draft is created in `DRAFT` with `version` 1, `required_approval_bps` of
    6670, and `prepared_by_user_id` recording the acting `X-User-ID`."

    Design: Corner/state_machines/corner_initial_states_match_declared_initial_state
    """
    ctx = setup_operating_conference_with_reserve(api)

    pool = create_revenue_pool(api, ctx["conference_id"])
    petitioner = create_petitioned_member(api, ctx)
    action = propose_membership_action(
        api,
        ctx["conference_id"],
        petitioner["id"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
        entry_fee_cents=0,
        rationale="Footprint expansion",
    )
    proposal_2028 = draft_budget_proposal(
        api,
        ctx["conference_id"],
        fiscal_year=2028,
        proposed_operating_expense_cents=130_000_000,
        proposed_governance_expense_cents=21_000_000,
    )

    # A pool starts DRAFT rather than OPEN, and a petitioner is not a seated member.
    assert_fields_equal(pool, status="DRAFT", audited_expense_cents=None, version=1)
    assert_fields_equal(
        petitioner,
        status="PETITIONED",
        distribution_phase_bps=0,
        voting_weight_bps=0,
        phase_year=0,
        entry_fee_paid_cents=0,
    )
    assert_fields_equal(
        action, status="PROPOSED", amend_count=0, quorum_weight_bps=6000, version=1
    )
    assert_fields_equal(
        proposal_2028, status="DRAFT", required_approval_bps=6670, version=1
    )


def test_the_competition_side_creates_land_on_their_declared_initial_states(api):
    """PRD §3.6: "The appearance is created in `SUBMITTED`, and submitting it mints
    `units_claimed` postseason units in status `PROVISIONAL`, each carrying its parent's
    identifier as `bowl_appearance_id`, the credited `member_id`, a `fiscal_year` copied from
    the parent appearance, and a 1-based `unit_index` giving its ordinal within the appearance."
    PRD §3.6: "Approving therefore moves the appearance `UNDER_REVIEW` → `APPROVED`, writes
    `allowable_expense_cents`, `travel_allowance_cents`, `reimbursement_ceiling_cents`,
    `reimbursed_cents` and `residual_to_pool_cents`, adds `residual_to_pool_cents` to the
    conference's `escrow_balance_cents`, transitions every postseason unit of the appearance
    `PROVISIONAL` → `VALIDATED`, advances the conference's `validated_postseason_unit_count` by
    `units_claimed`, and increments the conference's `version` by 1."
    PRD §3.5: "A successful award creates the event in `SCHEDULED` and snapshots the host's
    score at that moment as `host_compliance_score_at_award`."
    PRD §3.4: "A rivalry is created `ACTIVE` and has exactly one other status, `LAPSED`, which
    is terminal."
    PRD §3.4: "A game is created in `SCHEDULED` and immediately triggers a recomputation of
    `schedule_compliance_score` for both participants."

    Design: Corner/state_machines/corner_initial_states_match_declared_initial_state
    """
    ctx = setup_operating_conference_with_reserve(api)
    ids = ctx["member_ids"]
    pool = create_revenue_pool(api, ctx["conference_id"])

    appearance = submit_bowl_appearance(api, ids["north"])
    event = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_east"]["id"],
        ids["south"],
        pool["id"],
        "2027-03-01T00:00:00Z",
        "2027-03-05T00:00:00Z",
        sport="WRESTLING",
    )
    rivalry = create_protected_rivalry(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        required_annual_meetings=1,
        label="Harbor Cup",
    )
    game = create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
        protected_rivalry_id=rivalry["id"],
    )

    assert appearance["status"] == "SUBMITTED"
    units = validate_success(
        api.list_appearance_postseason_units(
            appearance["id"], headers=make_compliance_officer_headers()
        )
    )
    assert len(units) == 2
    assert sorted(unit["unit_index"] for unit in units) == [1, 2]
    for unit in units:
        assert_fields_equal(
            unit,
            status="PROVISIONAL",
            fiscal_year=2027,
            bowl_appearance_id=appearance["id"],
            member_id=ids["north"],
        )
    assert event["status"] == "SCHEDULED"
    assert rivalry["status"] == "ACTIVE"
    assert game["status"] == "SCHEDULED"
    # Provisional units are not validated ones, so the conference counter stays at 0.
    assert read_conference(api)["validated_postseason_unit_count"] == 0


def test_a_closed_pool_refuses_every_transition_and_any_further_run(api):
    """PRD §3.7: "Reopening a `BOOKS_CLOSED` pool takes a `reason`, returns it to `OPEN`, clears
    `audited_expense_cents` back to null and supersedes every run on the pool still in
    `COMPUTED`; it is only permitted while no run on the pool has been posted."
    PRD §3.7: "Closing a `BOOKS_CLOSED` pool permanently sets it `CLOSED`, and requires that at
    least one run on the pool has reached `POSTED`."
    PRD §3.7: "Every one of these four transitions advances the pool's `version` by 1, and an
    operation addressed to a pool in the wrong status is refused with
    `ERR_POOL_STATE_INVALID`."
    PRD §3.7: "The variant and the pool status are paired: a `PROVISIONAL` run is only accepted
    while the pool is `OPEN`, and a `FINAL_AUDITED` run only while it is `BOOKS_CLOSED`; a
    mismatch is refused with `ERR_POOL_STATE_INVALID`."

    Design: Corner/state_machines/corner_closed_pool_terminal_state_cannot_reopen
    """
    ctx = setup_closed_media_pool(api)
    pool_id = ctx["pool_2026_id"]
    closed = read_revenue_pool(api, pool_id)
    assert_fields_equal(closed, status="CLOSED", audited_expense_cents=4_000_000)

    # Reopen is the interesting one: it is legal from BOOKS_CLOSED, the state CLOSED
    # was reached from, and the run attempt echoes the pool's current version so that
    # no optimistic-concurrency check can mask the terminal-state refusal.
    attempts = (
        api.reopen_revenue_pool(
            pool_id, {"reason": "late restatement"}, headers=make_finance_officer_headers()
        ),
        api.open_revenue_pool(pool_id, headers=make_finance_officer_headers()),
        api.close_revenue_pool_books(
            pool_id, {"audited_expense_cents": 5_000_000}, headers=make_finance_officer_headers()
        ),
        api.close_revenue_pool(pool_id, headers=make_finance_officer_headers()),
        api.create_distribution_run(
            pool_id,
            make_distribution_run_payload(
                closed["version"], RunVariant.FINAL_AUDITED.value, memo="post-closure attempt"
            ),
            headers=make_finance_officer_headers(),
        ),
    )

    for response in attempts:
        validate_error(response, ApiErrorId.ERR_POOL_STATE_INVALID.value, 409)
    assert_fields_equal(
        read_revenue_pool(api, pool_id),
        status="CLOSED",
        audited_expense_cents=4_000_000,
        version=closed["version"],
    )
    runs, meta = validate_paginated(
        api.list_pool_distribution_runs(pool_id, headers=make_finance_officer_headers())
    )
    assert meta["total_count"] == 1, "no sixth call created a run behind the closed pool"
    assert runs[0]["status"] == "POSTED"


def test_replaying_an_action_endpoint_is_refused_rather_than_absorbed(api):
    """PRD §3.7: "Opening a `DRAFT` pool, which additionally requires the conference to be
    `OPERATING`, sets it `OPEN` and makes it eligible for provisional runs."
    PRD §3.7: "Every one of these four transitions advances the pool's `version` by 1, and an
    operation addressed to a pool in the wrong status is refused with
    `ERR_POOL_STATE_INVALID`."
    PRD §3.3: "A proposal's lifecycle is short — `DRAFT` → `VOTING` → either `APPROVED` or
    `REJECTED`, both of which are final — and any operation addressed to a proposal in the
    wrong status is refused with `ERR_PROPOSAL_STATE_INVALID`."
    PRD §3.6: "Every one of these transitions advances the appearance's `version` by 1, and any
    of them addressed to an appearance in the wrong status is refused with
    `ERR_APPEARANCE_STATE_INVALID`: review may only begin from `SUBMITTED`, revision may only
    be requested from `UNDER_REVIEW`, resubmission only from `REVISION_REQUESTED`, approval
    only from `UNDER_REVIEW`, and voiding from any status that is not already `VOIDED`."
    PRD §3.4: "Any game-level operation addressed to a game that is not `SCHEDULED` is refused
    with `ERR_GAME_STATE_INVALID`."

    Design: Corner/state_machines/corner_repeated_action_endpoints_second_attempt_rejected
    """
    ctx = setup_operating_conference(api)
    ids = ctx["member_ids"]
    pool = open_revenue_pool(api, create_revenue_pool(api, ctx["conference_id"])["id"])
    proposal = draft_budget_proposal(api, ctx["conference_id"], fiscal_year=2028)
    validate_success(
        api.open_budget_voting(proposal["id"], headers=make_finance_officer_headers())
    )
    appearance = begin_bowl_review(api, submit_bowl_appearance(api, ids["north"])["id"])
    game = play_game(
        api,
        create_schedule_game(
            api,
            ctx["conference_id"],
            ids["north"],
            ids["south"],
            ctx["venue_north"]["id"],
            "2026-09-05T19:00:00Z",
        )["id"],
    )

    pool_replay = api.open_revenue_pool(pool["id"], headers=make_finance_officer_headers())
    proposal_replay = api.open_budget_voting(
        proposal["id"], headers=make_finance_officer_headers()
    )
    appearance_replay = api.begin_bowl_review(
        appearance["id"], headers=make_compliance_officer_headers()
    )
    game_replay = api.play_schedule_game(
        game["id"], headers=make_schedule_coordinator_headers()
    )

    validate_error(pool_replay, ApiErrorId.ERR_POOL_STATE_INVALID.value, 409)
    assert read_revenue_pool(api, pool["id"])["status"] == "OPEN"
    validate_error(proposal_replay, ApiErrorId.ERR_PROPOSAL_STATE_INVALID.value, 409)
    assert _read_proposal(api, proposal["id"])["status"] == "VOTING"
    validate_error(appearance_replay, ApiErrorId.ERR_APPEARANCE_STATE_INVALID.value, 409)
    assert _read_appearance(api, appearance["id"])["status"] == "UNDER_REVIEW"
    validate_error(game_replay, ApiErrorId.ERR_GAME_STATE_INVALID.value, 409)
    assert _read_game(api, game["id"])["status"] == "PLAYED"


def test_each_trigger_from_an_undeclared_source_state_carries_its_own_code(api):
    """PRD §3.5: "Any event operation addressed to an event in an incompatible status — settling
    one that was never hosted, for instance — is refused with `ERR_EVENT_STATE_INVALID`."
    PRD §3.7: "Reversing a posted run takes a `reason`, is a `Treasurer` action, is available
    only from `POSTED`, and requires the parent pool not to be `CLOSED`."
    PRD §3.9: "The attested run must be in `COMPUTED`, and drafting against a run in any other
    status is refused with `ERR_RUN_STATE_INVALID`."
    PRD §3.2: "Executing an approved action is the `Commissioner`'s final step, and it is
    refused with `ERR_ACTION_STATE_INVALID` unless the action is `APPROVED` and the subject
    member is in the status the action type expects — `PETITIONED` for an `ADMIT`,
    `WITHDRAWAL_NOTICED` for a `WITHDRAW`."
    PRD §3.8: "Rescinding a notice is also a `Commissioner` action and is only available while
    the member is `WITHDRAWAL_NOTICED`; otherwise it is refused with
    `ERR_MEMBER_STATE_INVALID`."
    PRD §3.4: "Any game-level operation addressed to a game that is not `SCHEDULED` is refused
    with `ERR_GAME_STATE_INVALID`."

    Design: Corner/state_machines/corner_triggers_from_undeclared_source_state_are_rejected
    """
    ctx = setup_operating_conference_with_reserve(api)
    ids = ctx["member_ids"]
    run = setup_computed_fy2026_final_run(api, ctx)
    petitioner = create_petitioned_member(api, ctx)
    action = propose_membership_action(
        api,
        ctx["conference_id"],
        petitioner["id"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
        entry_fee_cents=0,
        rationale="Footprint expansion",
    )
    pool_2027 = create_revenue_pool(api, ctx["conference_id"])
    event = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_east"]["id"],
        ids["south"],
        pool_2027["id"],
        "2027-03-01T00:00:00Z",
        "2027-03-05T00:00:00Z",
        sport="WRESTLING",
    )
    game = play_game(
        api,
        create_schedule_game(
            api,
            ctx["conference_id"],
            ids["north"],
            ids["east"],
            ctx["venue_north"]["id"],
            "2026-09-05T19:00:00Z",
        )["id"],
    )

    settle = api.settle_championship_event(
        event["id"],
        {
            "ticket_revenue_cents": 48_000_000,
            "sponsorship_revenue_cents": 12_000_000,
            "event_expense_cents": 21_000_000,
        },
        headers=make_finance_officer_headers(),
    )
    reverse = api.reverse_distribution_run(
        run["id"], {"reason": "premature reversal"}, headers=make_treasurer_headers()
    )
    execute = api.execute_membership_action(action["id"], headers=make_commissioner_headers())
    rescind = api.rescind_withdrawal_notice(
        ids["north"], headers=make_commissioner_headers()
    )
    cancel = api.cancel_schedule_game(
        game["id"], {"reason": "too late"}, headers=make_schedule_coordinator_headers()
    )

    validate_error(settle, ApiErrorId.ERR_EVENT_STATE_INVALID.value, 409)
    assert _read_event(api, event["id"])["net_event_revenue_cents"] == 0
    validate_error(reverse, ApiErrorId.ERR_RUN_STATE_INVALID.value, 409)
    assert _read_run(api, run["id"])["status"] == "COMPUTED"
    validate_error(execute, ApiErrorId.ERR_ACTION_STATE_INVALID.value, 409)
    assert read_member(api, petitioner["id"])["status"] == "PETITIONED"
    validate_error(rescind, ApiErrorId.ERR_MEMBER_STATE_INVALID.value, 409)
    assert read_member(api, ids["north"])["status"] == "FULL_SHARE"
    validate_error(cancel, ApiErrorId.ERR_GAME_STATE_INVALID.value, 409)
    assert _read_game(api, game["id"])["status"] == "PLAYED"
    # The refused settlement moved no revenue into the FY2027 pool.
    assert read_revenue_pool(api, pool_2027["id"])["gross_revenue_cents"] == 500_000_000


def test_recomputing_supersedes_the_prior_run_and_voids_only_its_lines(api):
    """PRD §3.7: "A successful computation creates the run in `COMPUTED` with one `ACTIVE` line
    per line member, records the acting user as `computed_by_user_id`, writes `net_pool_cents`,
    `reserve_draw_cents`, `distributable_cents` and `total_weight_bps`, sets any earlier run on
    the same pool that is still `COMPUTED` to `SUPERSEDED` with `superseded_by_run_id` pointing
    at the new run and every one of that older run's `ACTIVE` lines moved to `VOIDED`, and
    advances the pool's `version` by 1."

    Design: Corner/state_machines/corner_superseding_run_cascades_prior_lines_to_voided
    """
    ctx = setup_operating_conference_with_reserve(api)
    first = setup_computed_fy2026_final_run(api, ctx)
    assert len(read_run_lines(api, first["id"])) == 4

    second = compute_run(
        api, ctx["pool_2026_id"], RunVariant.FINAL_AUDITED.value, memo="recompute"
    )

    assert_fields_equal(
        _read_run(api, first["id"]), status="SUPERSEDED", superseded_by_run_id=second["id"]
    )
    old_lines = read_run_lines(api, first["id"])
    assert len(old_lines) == 4, "the cascade voids the older lines rather than deleting them"
    for line in old_lines:
        assert line["status"] == "VOIDED"
    new_lines = read_run_lines(api, second["id"])
    assert second["status"] == "COMPUTED"
    assert len(new_lines) == 4
    for line in new_lines:
        assert line["status"] == "ACTIVE"


def test_the_replacement_run_repeats_the_arithmetic_without_moving_a_counter(api):
    """PRD §3.7: "The `net_pool_cents` is `gross_revenue_cents` minus that basis, and it may be
    negative if expenses exceed receipts."
    PRD §3.7: "The `reserve_draw_cents` is the smaller of `net_pool_cents` multiplied by the
    sweep rate divided by 10000 and rounded up to the next whole cent, and that shortfall — so
    a fully funded reserve draws nothing at all no matter what the rate says."
    PRD §3.7: "Under `EQUAL_SHARE` the raw weight is the base weight of 10000 basis points for
    everyone."
    PRD §3.7: "Each line's `gross_share_cents` is first `distributable_cents` multiplied by
    that line's `weight_bps` and divided by `total_weight_bps`, rounded down."
    PRD §3.7: "The `governance_fee_cents` is the flat governance and compliance service fee of
    1,250,000 cents (12,500 dollars), charged identically on every line regardless of its size,
    which means a small line can be driven negative by it."
    PRD §3.7: "The draw is computed here but does not touch `reserve_balance_cents` until the
    run is posted."

    Design: Corner/state_machines/corner_superseding_run_cascades_prior_lines_to_voided
    """
    ctx = setup_operating_conference_with_reserve(api)
    setup_computed_fy2026_final_run(api, ctx)

    second = compute_run(
        api, ctx["pool_2026_id"], RunVariant.FINAL_AUDITED.value, memo="recompute"
    )

    assert_fields_equal(
        second,
        net_pool_cents=596_000_000,
        reserve_draw_cents=6_000_000,
        distributable_cents=590_000_000,
        total_weight_bps=40000,
    )
    for line in read_run_lines(api, second["id"]):
        assert_fields_equal(
            line,
            gross_share_cents=147_500_000,
            governance_fee_cents=1_250_000,
            withheld_cents=0,
            net_payable_cents=146_250_000,
        )
    # Neither run was posted, so the cascade stayed inside the run aggregate.
    assert_fields_equal(
        read_conference(api),
        reserve_balance_cents=12_000_000,
        escrow_balance_cents=0,
        governance_fee_revenue_cents=0,
    )
    for member_id in ctx["member_ids"].values():
        assert read_member(api, member_id)["last_full_annual_distribution_cents"] == 0


def test_reversing_a_posted_run_puts_every_conference_counter_back(api):
    """PRD §3.7: "It is an exact compensation: every `ACTIVE` line moves to `VOIDED`,
    `reserve_balance_cents` falls by `reserve_draw_cents` and `reserve_posture` is re-derived,
    `escrow_balance_cents` falls by the sum of `withheld_cents`, `governance_fee_revenue_cents`
    falls by the sum of `governance_fee_cents`, each member's `exit_settlement_paid_cents` is
    rolled back by that line's `gor_offset_cents`, and the conference's `version` advances by
    1."
    PRD §3.7: "Reversal leaves every conference-level counter exactly where it stood before the
    post."
    PRD §2.10: "The funded ratio, `funded_ratio_bps`, is 10000 when the target is 0; otherwise
    it is `reserve_balance_cents` multiplied by 10000 and divided by `reserve_target_cents`,
    rounded down to a whole basis point."
    PRD §2.10: "The posture, `reserve_posture`, is one of `OPEN`, `RESERVE_RESTRICTED` or
    `FROZEN`, and is derived by comparing the balance against the target without dividing:
    when the target is 0 the posture is `OPEN`; otherwise, if the balance multiplied by 10000
    is less than the target multiplied by 2500 basis points the posture is `FROZEN`;
    otherwise, if the balance multiplied by 10000 is less than the target multiplied by 6000
    basis points the posture is `RESERVE_RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Corner/state_machines/corner_run_reverse_compensates_every_conference_counter
    """
    ctx = setup_operating_conference_with_reserve(api)
    posted = setup_posted_fy2026_distribution(api, ctx)
    before = read_conference(api)
    assert_fields_equal(
        before,
        reserve_balance_cents=18_000_000,
        escrow_balance_cents=0,
        governance_fee_revenue_cents=5_000_000,
    )
    assert_posture(before, "OPEN", 10000)

    reversed_run = validate_success(
        api.reverse_distribution_run(
            posted["id"],
            {"reason": "restatement required by the membership"},
            headers=make_treasurer_headers(),
        )
    )

    assert reversed_run["status"] == "REVERSED"
    lines = read_run_lines(api, posted["id"])
    assert len(lines) == 4
    for line in lines:
        assert line["status"] == "VOIDED"
    after = read_conference(api)
    assert_fields_equal(
        after,
        reserve_balance_cents=12_000_000,
        escrow_balance_cents=0,
        governance_fee_revenue_cents=0,
    )
    assert_posture(after, "OPEN", 6666)
    for member_id in ctx["member_ids"].values():
        member = read_member(api, member_id)
        assert member["exit_settlement_paid_cents"] == 0
        # The reversal's side-effect list does not name this figure, so it stands.
        assert member["last_full_annual_distribution_cents"] == 147_500_000


def test_cancelling_the_only_meeting_lapses_the_rivalry_and_rescores_both_schools(api):
    """PRD §3.4: "Cancelling it, which requires a `reason` and is available to a
    `ScheduleCoordinator` or `Commissioner`, moves it `SCHEDULED` → `CANCELLED` and starts a
    chain: if the game carried a `protected_rivalry_id` and no meeting for that rivalry in the
    conference's `current_fiscal_year` remains in status `SCHEDULED` or `PLAYED`, that rivalry
    moves `ACTIVE` → `LAPSED`; the `schedule_compliance_score` of both participants and of
    every counterpart of a rivalry that just lapsed is recomputed; and any championship event
    still `SCHEDULED` whose host member's recomputed score has dropped below 90 moves
    `SCHEDULED` → `HOST_AT_RISK`."
    PRD §3.4: "It is computed for the conference's `current_fiscal_year` only, and it counts
    only games in status `SCHEDULED` or `PLAYED` — cancelled games are excluded from every
    count, which is exactly why a cancellation lowers a score."
    PRD §3.4: "The first is 15 points for each **unmet protected rivalry** involving the
    member, where a rivalry counts as unmet if it is `LAPSED`, or if it is `ACTIVE` but the
    number of games referencing it in the current fiscal year with status `SCHEDULED` or
    `PLAYED` is fewer than its `required_annual_meetings`."
    PRD §3.4: "The third is 5 points for each unit of **home-schedule imbalance**, measured as
    the member's `home_game_count` minus its `away_game_count` minus 1, treated as 0 when that
    difference is negative or zero; both counts cover the current fiscal year in status
    `SCHEDULED` or `PLAYED`."

    Design: Corner/state_machines/corner_rivalry_lapses_when_its_last_game_is_cancelled
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    rivalry = create_protected_rivalry(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        required_annual_meetings=1,
        label="Prairie Trophy",
    )
    game = create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
        protected_rivalry_id=rivalry["id"],
    )
    assert_compliance_breakdown(
        _read_compliance(api, ids["north"]),
        unmet_rivalry_count=0,
        travel_partner_gap_count=0,
        home_game_count=1,
        away_game_count=0,
        schedule_compliance_score=100,
    )

    cancelled = cancel_game(api, game["id"], reason="hurricane")

    assert cancelled["status"] == "CANCELLED"
    assert _read_rivalry(api, rivalry["id"])["status"] == "LAPSED"
    for key in ("north", "south"):
        assert_compliance_breakdown(
            _read_compliance(api, ids[key]),
            unmet_rivalry_count=1,
            travel_partner_gap_count=0,
            home_game_count=0,
            away_game_count=0,
            schedule_compliance_score=85,
        )
        assert read_member(api, ids[key])["schedule_compliance_score"] == 85


def test_the_third_amendment_is_refused_and_the_loop_terminates(api):
    """PRD §3.2: "While an action is under vote, its terms may be amended — a new
    `effective_fiscal_year`, a revised `entry_fee_cents`, a rewritten `rationale`, in any
    combination."
    PRD §3.2: "Amending returns the action `VOTING` → `PROPOSED`, transitions every `CAST`
    ballot on it to `VOIDED`, resets `cast_weight_bps`, `for_weight_bps` and
    `approval_ratio_bps` to 0, increments `amend_count` by 1 and advances the action's
    `version`."
    PRD §3.2: "The membership can therefore be re-canvassed on revised terms, but not
    indefinitely: the loop terminates because an amendment is only accepted while `amend_count`
    is below the amendment limit of 2, and the third attempt is refused with
    `ERR_AMEND_LIMIT_REACHED`."
    PRD §3.2: "Opening the ballot moves the action `PROPOSED` → `VOTING` and is refused with
    `ERR_ACTION_STATE_INVALID` from any other status."

    Design: Corner/state_machines/corner_third_amend_rejected_at_amend_limit
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    cast_action_ballot(api, action_id, ctx["member_ids"]["north"])

    first = validate_success(
        api.amend_membership_action(
            action_id,
            {"effective_fiscal_year": 2029, "rationale": "Deferred one cycle"},
            headers=make_commissioner_headers(),
        )
    )
    assert_fields_equal(
        first, status="PROPOSED", amend_count=1, cast_weight_bps=0, for_weight_bps=0
    )
    ballots, meta = validate_paginated(
        api.list_action_ballots(action_id, headers=make_commissioner_headers())
    )
    assert meta["total_count"] == 1
    assert ballots[0]["status"] == "VOIDED"

    open_action_voting(api, action_id)
    second = validate_success(
        api.amend_membership_action(
            action_id,
            {"entry_fee_cents": 0, "rationale": "Fee terms restated"},
            headers=make_commissioner_headers(),
        )
    )
    # The fee-only amendment leaves the year the first amendment set.
    assert_fields_equal(second, amend_count=2, effective_fiscal_year=2029)

    open_action_voting(api, action_id)
    third = api.amend_membership_action(
        action_id,
        {"rationale": "One change too many"},
        headers=make_commissioner_headers(),
    )

    validate_error(third, ApiErrorId.ERR_AMEND_LIMIT_REACHED.value, 409)
    assert_fields_equal(
        read_membership_action(api, action_id), status="VOTING", amend_count=2
    )
