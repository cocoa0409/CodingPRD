"""Deep cascades: a settlement that unwinds a run, a withdrawal that reaches a host, closed books."""

from test_helpers import (
    ApiErrorId,
    RunVariant,
    assert_compliance_breakdown,
    assert_fields_equal,
    execute_membership_action,
    make_compliance_officer_headers,
    make_distribution_run_payload,
    make_finance_officer_headers,
    make_schedule_coordinator_headers,
    read_conference,
    read_member,
    read_revenue_pool,
    read_run_lines,
    setup_championship_settlement_fixture,
    setup_full_media_fixture,
    setup_withdraw_cascade_fixture,
    settle_championship_event,
    validate_error,
    validate_success,
    void_bowl_appearance,
)

FY2027_AUDITED_EXPENSE_CENTS = 26_500_000


def _read_game(api, game_id):
    return validate_success(
        api.get_schedule_game(game_id, headers=make_schedule_coordinator_headers())
    )


def _read_rivalry(api, rivalry_id):
    return validate_success(
        api.get_protected_rivalry(
            rivalry_id, headers=make_schedule_coordinator_headers()
        )
    )


def _read_event(api, event_id):
    return validate_success(
        api.get_championship_event(
            event_id, headers=make_schedule_coordinator_headers()
        )
    )


def _read_compliance(api, member_id):
    return validate_success(
        api.get_schedule_compliance(
            member_id, headers=make_schedule_coordinator_headers()
        )
    )


def _read_run(api, run_id):
    return validate_success(
        api.get_distribution_run(run_id, headers=make_finance_officer_headers())
    )


def test_settling_a_championship_restates_the_pool_gross_and_reverts_the_pool(api):
    """PRD §3.5: "From them the system derives `net_event_revenue_cents` as ticket receipts
    plus sponsorship receipts minus event expense."
    PRD §3.5: "The `host_share_cents` is that net figure multiplied by the host share of 2000
    basis points and divided by 10000, rounded up to the next whole cent — but only when the
    net figure is strictly positive; when the net is zero or negative the host share is 0."
    PRD §3.5: "The `participant_pool_cents` is then `net_event_revenue_cents` minus
    `host_share_cents`, which means that a loss-making event passes its entire negative net
    through to the participant pool while the host is shielded from it."
    PRD §3.5: "The `participant_pool_cents` is added to the linked revenue pool's
    `gross_revenue_cents`."
    PRD §3.5: "Because that gross figure has now been restated, a pool sitting in `OPEN` or
    `BOOKS_CLOSED` is driven back to `DRAFT`, and if it was `BOOKS_CLOSED` its
    `audited_expense_cents` is cleared to null — the audited figure was an assertion about a
    gross that no longer holds."

    Design: Difficulty/transitive_cascade/championship_settlement_invalidates_computed_run_depth_five
    """
    ctx = setup_championship_settlement_fixture(api)
    pool_before = read_revenue_pool(api, ctx["pool_id"])
    assert_fields_equal(pool_before, status="OPEN", gross_revenue_cents=500_000_000)

    settled = settle_championship_event(
        api,
        ctx["event_id"],
        ticket_revenue_cents=48_000_000,
        sponsorship_revenue_cents=12_000_000,
        event_expense_cents=21_000_000,
    )

    assert_fields_equal(
        settled,
        status="SETTLED",
        net_event_revenue_cents=39_000_000,
        host_share_cents=7_800_000,
        participant_pool_cents=31_200_000,
    )
    pool_after = read_revenue_pool(api, ctx["pool_id"])
    assert_fields_equal(
        pool_after,
        status="DRAFT",
        gross_revenue_cents=531_200_000,
        audited_expense_cents=None,
        version=pool_before["version"] + 1,
    )


def test_settling_a_championship_supersedes_the_computed_run_and_voids_its_lines(api):
    """PRD §3.5: "Because the pool has reverted, every distribution run on that pool still in
    `COMPUTED` moves to `SUPERSEDED`."
    PRD §3.5: "And because those runs are superseded, every one of their lines still `ACTIVE`
    moves to `VOIDED`."
    PRD §3.5: "The pool's `version` advances by 1, which is what makes any client holding an
    older `expected_pool_version` fail its next attempt to compute a run."

    Design: Difficulty/transitive_cascade/championship_settlement_invalidates_computed_run_depth_five
    """
    ctx = setup_championship_settlement_fixture(api)
    stale_pool_version = read_revenue_pool(api, ctx["pool_id"])["version"]
    lines_before = read_run_lines(api, ctx["run_id"])
    assert len(lines_before) == 4
    for line in lines_before:
        assert line["status"] == "ACTIVE"

    settle_championship_event(
        api,
        ctx["event_id"],
        ticket_revenue_cents=48_000_000,
        sponsorship_revenue_cents=12_000_000,
        event_expense_cents=21_000_000,
    )

    assert _read_run(api, ctx["run_id"])["status"] == "SUPERSEDED"
    lines_after = read_run_lines(api, ctx["run_id"])
    assert len(lines_after) == 4, "the cascade voids the lines rather than deleting them"
    for line in lines_after:
        assert line["status"] == "VOIDED"
    stale = api.create_distribution_run(
        ctx["pool_id"],
        make_distribution_run_payload(stale_pool_version, RunVariant.PROVISIONAL.value),
        headers=make_finance_officer_headers(),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_POOL_VERSION.value, 412)


def test_executing_a_withdrawal_cancels_the_games_and_lapses_the_rivalry(api):
    """PRD §3.2: "The subject member moves `WITHDRAWAL_NOTICED` → `DEPARTED` with
    `distribution_phase_bps` and `voting_weight_bps` both set to 0."
    PRD §3.2: "Every game still `SCHEDULED` with that member as either the home or the away
    participant becomes `CANCELLED`."
    PRD §3.2: "Every `ACTIVE` protected rivalry involving that member which is left with no
    non-cancelled meeting in the conference's `current_fiscal_year` moves `ACTIVE` →
    `LAPSED`."

    Design: Difficulty/transitive_cascade/withdraw_execution_cascades_to_host_at_risk_depth_five
    """
    ctx = setup_withdraw_cascade_fixture(api)
    assert read_member(api, ctx["member_ids"]["north"])["status"] == "WITHDRAWAL_NOTICED"

    executed = execute_membership_action(api, ctx["action_id"])

    assert executed["status"] == "EXECUTED"
    assert_fields_equal(
        read_member(api, ctx["member_ids"]["north"]),
        status="DEPARTED",
        distribution_phase_bps=0,
        voting_weight_bps=0,
    )
    assert _read_game(api, ctx["game_border"]["id"])["status"] == "CANCELLED"
    assert (
        _read_game(api, ctx["game_harbor"]["id"])["status"] == "SCHEDULED"
    ), "the game that does not involve the departing member is untouched"
    assert _read_rivalry(api, ctx["rivalry_border"]["id"])["status"] == "LAPSED"
    assert (
        _read_rivalry(api, ctx["rivalry_harbor"]["id"])["status"] == "ACTIVE"
    ), "the rivalry that still has a scheduled meeting stays active"


def test_executing_a_withdrawal_puts_an_unrelated_hosts_event_at_risk(api):
    """PRD §3.2: "The `schedule_compliance_score` of every counterpart member of a lapsed
    rivalry is recomputed."
    PRD §3.2: "And finally, any championship event still `SCHEDULED` whose host member's
    recomputed score has fallen below the hosting minimum of 90 moves `SCHEDULED` →
    `HOST_AT_RISK`."
    PRD §3.2: "All five hops are part of the same operation; none of them is optional."
    PRD §3.4: "The first is 15 points for each **unmet protected rivalry** involving the
    member, where a rivalry counts as unmet if it is `LAPSED`, or if it is `ACTIVE` but the
    number of games referencing it in the current fiscal year with status `SCHEDULED` or
    `PLAYED` is fewer than its `required_annual_meetings`."

    Design: Difficulty/transitive_cascade/withdraw_execution_cascades_to_host_at_risk_depth_five
    """
    ctx = setup_withdraw_cascade_fixture(api)
    host_id = ctx["member_ids"]["south"]
    assert_compliance_breakdown(
        _read_compliance(api, host_id),
        unmet_rivalry_count=0,
        travel_partner_gap_count=0,
        home_game_count=2,
        away_game_count=0,
        schedule_compliance_score=95,
    )
    event_before = _read_event(api, ctx["event_id"])
    assert event_before["status"] == "SCHEDULED"

    execute_membership_action(api, ctx["action_id"])

    # South is never named in the execute request, yet the lapsed trophy costs it 15
    # points and drops it under the hosting minimum.
    assert_compliance_breakdown(
        _read_compliance(api, host_id),
        unmet_rivalry_count=1,
        travel_partner_gap_count=0,
        home_game_count=1,
        away_game_count=0,
        schedule_compliance_score=85,
    )
    event_after = _read_event(api, ctx["event_id"])
    assert_fields_equal(
        event_after,
        status="HOST_AT_RISK",
        host_member_id=host_id,
        version=event_before["version"] + 1,
    )


def test_close_books_is_blocked_by_an_appearance_still_awaiting_review(api):
    """PRD §3.7: "Closing the books on an `OPEN` pool supplies the `audited_expense_cents` and
    sets the pool `BOOKS_CLOSED`, which is the only status from which a final audited run may
    be computed; before that is allowed, every bowl appearance whose `fiscal_year` equals the
    pool's `fiscal_year` must have reached `APPROVED` or `VOIDED`, and a single appearance
    still `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED` refuses the operation with
    `ERR_BOWL_REVIEW_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/close_books_depends_on_terminal_bowl_reviews
    """
    ctx = setup_full_media_fixture(api)
    assert ctx["appearance_north"]["status"] == "APPROVED"
    assert ctx["appearance_west"]["status"] == "SUBMITTED"

    response = api.close_revenue_pool_books(
        ctx["pool_id"],
        {"audited_expense_cents": FY2027_AUDITED_EXPENSE_CENTS},
        headers=make_finance_officer_headers(),
    )

    validate_error(response, ApiErrorId.ERR_BOWL_REVIEW_PENDING.value, 409)
    assert_fields_equal(
        read_revenue_pool(api, ctx["pool_id"]),
        status="OPEN",
        audited_expense_cents=None,
    )


def test_voiding_the_pending_appearance_lets_the_books_close(api):
    """PRD §3.6: "From `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED` it simply moves the
    appearance to `VOIDED` and transitions each of its still-`PROVISIONAL` units to `VOIDED`,
    permanently excluding them from every valuation; the appearance's `version` advances by 1."
    PRD §3.7: "Closing the books on an `OPEN` pool supplies the `audited_expense_cents` and
    sets the pool `BOOKS_CLOSED`, which is the only status from which a final audited run may
    be computed; before that is allowed, every bowl appearance whose `fiscal_year` equals the
    pool's `fiscal_year` must have reached `APPROVED` or `VOIDED`, and a single appearance
    still `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED` refuses the operation with
    `ERR_BOWL_REVIEW_PENDING`."
    PRD §3.7: "Every one of these four transitions advances the pool's `version` by 1, and an
    operation addressed to a pool in the wrong status is refused with
    `ERR_POOL_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/close_books_depends_on_terminal_bowl_reviews
    """
    ctx = setup_full_media_fixture(api)
    pool_before = read_revenue_pool(api, ctx["pool_id"])
    conference_before = read_conference(api)

    voided = void_bowl_appearance(api, ctx["appearance_west"]["id"])
    closed = validate_success(
        api.close_revenue_pool_books(
            ctx["pool_id"],
            {"audited_expense_cents": FY2027_AUDITED_EXPENSE_CENTS},
            headers=make_finance_officer_headers(),
        )
    )

    assert_fields_equal(
        voided,
        status="VOIDED",
        version=ctx["appearance_west"]["version"] + 1,
    )
    units = validate_success(
        api.list_appearance_postseason_units(
            ctx["appearance_west"]["id"], headers=make_compliance_officer_headers()
        )
    )
    for unit in units:
        assert unit["status"] == "VOIDED"
    assert_fields_equal(
        closed,
        status="BOOKS_CLOSED",
        audited_expense_cents=FY2027_AUDITED_EXPENSE_CENTS,
        version=pool_before["version"] + 1,
    )
    # Voiding a never-approved appearance moves no conference counter.
    assert_fields_equal(
        read_conference(api),
        escrow_balance_cents=conference_before["escrow_balance_cents"],
        validated_postseason_unit_count=2,
    )
