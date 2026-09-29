"""Multi-hop cascades that reach entities the triggering request never names."""
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx

STANDARD_INCOMES = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
    {
        "source_type": "UNEARNED_CHILD_SUPPORT",
        "gross_monthly_cents": 20000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _shortfall_ready_case(api):
    """An ACTIVE case with a pending service request and a submitted 40-hour month."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Cascade A Household"},
        incomes=STANDARD_INCOMES,
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    authorization = fx.request_authorization(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=30000,
    )
    report = fx.file_report(
        api,
        assignment["id"],
        report_month="2026-08",
        reported_hours=40,
        verification_source="TIMESHEET",
    )
    return context, assignment["id"], authorization["id"], report["id"]


def test_verified_shortfall_opens_a_system_episode_on_the_case(api):
    """PRD §3.6: "The predicate drives the assignment's `compliance_flag`, which
    becomes `SHORTFALL` when the predicate is false for the reported month and
    `NONE` when it is true."
    PRD §3.6: "When the flag becomes `SHORTFALL` *and* the case's
    `compliance_status` is `ASSIGNED` at that moment, the same request opens a
    **compliance episode** on the case in `status` `ALLEGED`, with
    `allegation_reason` `HOURS_SHORTFALL` and `origin` `SYSTEM_SHORTFALL`, and moves
    the case's `compliance_status` to `CONCILIATION_PENDING`."

    Design: Difficulty/transitive_cascade/verified_shortfall_report_cascades_to_episode_and_service_hold
    """
    context, assignment_id, _authorization_id, report_id = _shortfall_ready_case(api)

    fx.verify_report(api, report_id, 40)

    report = fx.read_report(api, assignment_id, report_id)
    assert report["status"] == "VERIFIED"
    asrt.assert_report_credits(
        report, verified_hours=40, core_hours_credited=40, non_core_hours_credited=0
    )
    assignment = fx.read_assignment(api, assignment_id)
    assert assignment["cumulative_verified_hours"] == 40
    assert assignment["compliance_flag"] == "SHORTFALL"

    episodes = fx.search_episodes(api, case_id=context.case_id)
    assert len(episodes) == 1, f"expected exactly one episode, got {len(episodes)}"
    assert episodes[0]["status"] == "ALLEGED"
    assert episodes[0]["origin"] == "SYSTEM_SHORTFALL"
    assert episodes[0]["allegation_reason"] == "HOURS_SHORTFALL"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        compliance_status="CONCILIATION_PENDING",
        sanction_level=0,
        benefit_amount_cents=17000,
    )


def test_the_same_shortfall_puts_pending_service_money_on_hold(api):
    """PRD §3.6: "Because that move happened, the request continues one step
    further: every supportive service authorization of the case still in `REQUESTED`
    status is put on hold, moving to `HELD`."
    PRD §3.8: "Holds are the one status change no client requests directly."

    Design: Difficulty/transitive_cascade/verified_shortfall_report_cascades_to_episode_and_service_hold
    """
    _context, _assignment_id, authorization_id, report_id = _shortfall_ready_case(api)

    fx.verify_report(api, report_id, 40)

    asrt.assert_authorization(
        fx.read_authorization(api, authorization_id),
        status="HELD",
        authorized_amount_cents=0,
    )


def _case_at_level_two_with_supported_activity(api):
    """A SUSPENDED level-2 case in cure, still holding authorized service money."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Cascade B Household"},
        incomes=STANDARD_INCOMES,
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    authorization = fx.build_authorized_service(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=45000,
    )
    episode = fx.open_episode(api, context.case_id, allegation_reason="HOURS_SHORTFALL")
    conciliating = fx.start_conciliation(api, episode["id"])
    fx.advance_clock_to_deadline(api, conciliating)
    fx.impose_sanction(api, episode["id"])
    fx.begin_cure(api, episode["id"], cure_plan_note="First cure plan.")
    fx.impose_sanction(api, episode["id"])
    fx.begin_cure(api, episode["id"], cure_plan_note="Second cure plan.")
    return context, episode["id"], assignment["id"], authorization["id"]


def test_third_imposition_zeroes_the_grant_and_closes_the_case(api):
    """PRD §3.7: "When it is 3, the case closes as a full-family sanction:
    `benefit_status` moves `ACTIVE → CLOSED` or `SUSPENDED → CLOSED`,
    `closure_reason` becomes `FULL_FAMILY_SANCTION`, `benefit_amount_cents` is set
    to 0, and every work assignment of the case still in `PROPOSED` or `ACTIVE` is
    moved to `TERMINATED` with `termination_reason` `CASE_CLOSED`."
    PRD §3.7: "In both branches `sanction_pct` is then read from the level: level 0
    is 0.00, level 1 is 0.25, level 2 is 0.50 and level 3 is 1.00, meaning a quarter,
    a half, and the whole grant respectively."

    Design: Difficulty/transitive_cascade/level_three_sanction_cascades_to_closure_termination_and_void
    """
    context, episode_id, assignment_id, _authorization_id = (
        _case_at_level_two_with_supported_activity(api)
    )

    fx.impose_sanction(api, episode_id)

    episode = fx.read_episode(api, episode_id)
    assert episode["sanction_level"] == 3
    asrt.assert_pct(episode["sanction_pct"], 1.00, "episode sanction_pct")
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="CLOSED",
        compliance_status="SANCTIONED",
        closure_reason="FULL_FAMILY_SANCTION",
        sanction_level=3,
        benefit_amount_cents=0,
    )
    assignment = fx.read_assignment(api, assignment_id)
    assert assignment["status"] == "TERMINATED"
    assert assignment["termination_reason"] == "CASE_CLOSED"


def test_closure_driven_termination_voids_the_service_money_it_supported(api):
    """PRD §3.7: "every work assignment of the case still in `PROPOSED` or `ACTIVE`
    is moved to `TERMINATED` with `termination_reason` `CASE_CLOSED`."
    PRD §3.5: "The adverse branch covers `NONCOMPLIANCE`, `CASE_CLOSED` and
    `PLAN_CHANGE`: the assignment lands in `status` `TERMINATED`, and every
    supportive service authorization of *that assignment* in `REQUESTED`, `HELD` or
    `AUTHORIZED` status is voided — its `void_reason` is recorded as
    `ASSIGNMENT_TERMINATED`, its `authorized_amount_cents` returns to 0, and the
    case's `supportive_fy_authorized_cents` is recomputed so that the freed
    fiscal-year headroom is restored exactly, as §2.11 requires."

    Design: Difficulty/transitive_cascade/level_three_sanction_cascades_to_closure_termination_and_void
    """
    context, episode_id, _assignment_id, authorization_id = (
        _case_at_level_two_with_supported_activity(api)
    )
    before = fx.read_case(api, context.case_id)
    asrt.assert_money(
        before["supportive_fy_authorized_cents"], 45000, "supportive fiscal-year total"
    )

    fx.impose_sanction(api, episode_id)

    asrt.assert_authorization(
        fx.read_authorization(api, authorization_id),
        status="VOIDED",
        authorized_amount_cents=0,
        void_reason="ASSIGNMENT_TERMINATED",
    )
    case = fx.read_case(api, context.case_id)
    asrt.assert_money(
        case["supportive_fy_authorized_cents"], 0, "supportive fiscal-year total"
    )


def _household_one_shielded_month_from_the_state_limit(api):
    """State clock at 23 of 24, with 2026-10 shielded by a granted extension."""
    household = fx.create_household(api, head_of_household_name="Cascade C Household")
    fx.record_prior_assistance(
        api, household["id"], state_clock_months=21, federal_clock_months=21
    )
    application = fx.create_application(api, household["id"])
    for spec in STANDARD_INCOMES:
        spec = dict(spec)
        status = spec.pop("verification_status")
        fx.add_income_source(api, application["id"], verification_status=status, **spec)
    fx.determine(api, application["id"])
    case = fx.approve(api, application["id"])
    fx.issue_month(api, case["id"], "2026-08")
    fx.issue_month(api, case["id"], "2026-09")
    extension = fx.request_extension(
        api,
        case["id"],
        extension_type="HARDSHIP_LOCAL_LABOR_MARKET",
        months_requested=1,
        first_effective_month="2026-10",
    )
    fx.grant_extension(api, extension["id"], 1)
    fx.issue_month(api, case["id"], "2026-10")
    return household["id"], case["id"], extension["id"]


def test_revocation_restores_the_state_months_the_extension_had_shielded(api):
    """PRD §3.4: "Every time-limit month this extension had shielded is restored to
    state-countable with `non_countable_reason` `NONE`, *unless* another
    still-`GRANTED` extension of the case also covers that month, in which case it
    stays shielded and keeps its `GRANTED_EXTENSION` reason."
    PRD §3.4: "The extension's `months_granted` returns to 0 and its
    `last_effective_month` returns to null."

    Design: Difficulty/transitive_cascade/extension_revocation_cascades_through_clocks_to_time_limit_closure
    """
    household_id, case_id, extension_id = _household_one_shielded_month_from_the_state_limit(api)

    fx.revoke_extension(
        api,
        extension_id,
        revocation_reason="Local labor market hardship no longer documented.",
    )

    stored = fx.read_extension(api, case_id, extension_id)
    assert stored["status"] == "REVOKED"
    assert stored["months_granted"] == 0
    rows = fx.list_time_limit_months(api, case_id)
    asrt.assert_time_limit_month(
        asrt.find_time_limit_month(rows, "2026-10"),
        assistance_issued=True,
        state_clock_countable=True,
        federal_clock_countable=True,
        non_countable_reason="NONE",
    )
    asrt.assert_household_clocks(
        fx.read_household(api, household_id),
        state_clock_months_used=24,
        federal_clock_months_used=24,
        extension_months_used=0,
        issued_countable_months=3,
    )


def test_restored_state_clock_closes_the_case_on_the_time_limit(api):
    """PRD §3.4: "If the restored state clock has reached or passed 24 months, the
    case closes as a consequence: `benefit_status` moves `ACTIVE → CLOSED` with
    `closure_reason` `TIME_LIMIT`."
    PRD §3.4: "Hardship extension months are state-funded and therefore do not stop
    the federal clock at all."

    Design: Difficulty/transitive_cascade/extension_revocation_cascades_through_clocks_to_time_limit_closure
    """
    household_id, case_id, extension_id = _household_one_shielded_month_from_the_state_limit(api)
    before = fx.read_household(api, household_id)
    asrt.assert_household_clocks(
        before,
        state_clock_months_used=23,
        federal_clock_months_used=24,
        extension_months_used=1,
        issued_countable_months=3,
    )
    asrt.assert_case_state(fx.read_case(api, case_id), benefit_status="ACTIVE")

    fx.revoke_extension(
        api,
        extension_id,
        revocation_reason="Local labor market hardship no longer documented.",
    )

    asrt.assert_case_state(
        fx.read_case(api, case_id),
        benefit_status="CLOSED",
        closure_reason="TIME_LIMIT",
    )
