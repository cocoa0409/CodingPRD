"""Non-linear lifecycles: independent dimensions, cycles and forked branches."""
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

CURE_NOTE = "Attend orientation and resume community service."


def _case_with_conciliated_episode(api, name, allegation_reason="MISSED_APPOINTMENT"):
    """An ACTIVE 17000-cent case whose episode may be sanctioned today."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=STANDARD_INCOMES,
    )
    episode = fx.open_episode(api, context.case_id, allegation_reason=allegation_reason)
    conciliating = fx.start_conciliation(api, episode["id"])
    fx.advance_clock_to_deadline(api, conciliating)
    return context, episode["id"]


def test_compliance_dimension_moves_while_the_benefit_dimension_holds(api):
    """PRD §3.7: "A `WorkProgramSpecialist` **begins a cure**, moving the episode
    `SANCTION_IMPOSED → CURE_PENDING` with a free-text `cure_plan_note`, and the
    case's `compliance_status` becomes `CURE_PENDING` to match."
    PRD §3.7: "The sanction percentage stays in force throughout the cure period —
    the reduced grant is not restored on the strength of a plan — which is precisely
    why a failed cure escalates the same episode by one level rather than restarting
    it at level 1."

    Design: Difficulty/non_linear_state_machine/case_benefit_and_compliance_dimensions_advance_independently
    """
    context, episode_id = _case_with_conciliated_episode(api, "Two Dimension Household")

    fx.impose_sanction(api, episode_id)
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        compliance_status="SANCTIONED",
        sanction_level=1,
        sanction_pct=0.25,
        benefit_amount_cents=12750,
        closure_reason="NONE",
    )

    fx.begin_cure(api, episode_id, cure_plan_note=CURE_NOTE)

    assert fx.read_episode(api, episode_id)["status"] == "CURE_PENDING"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        compliance_status="CURE_PENDING",
        sanction_level=1,
        sanction_pct=0.25,
        benefit_amount_cents=12750,
        closure_reason="NONE",
    )


def test_compliant_resolution_returns_the_compliance_dimension_and_the_grant(api):
    """PRD §3.7: "The episode moves to `RESOLVED_COMPLIANT`, its `sanction_level`
    returns to 0 and its `sanction_pct` to 0.00, and the case's `compliance_status`
    returns to `ASSIGNED`."
    PRD §3.7: "That same rollup runs after every episode transition, not only after
    impositions, which is how a resolution or a good-cause grant restores the
    family's full grant."

    Design: Difficulty/non_linear_state_machine/case_benefit_and_compliance_dimensions_advance_independently
    """
    context, episode_id = _case_with_conciliated_episode(api, "Two Dimension Household")
    fx.impose_sanction(api, episode_id)
    fx.begin_cure(api, episode_id, cure_plan_note=CURE_NOTE)

    fx.resolve_compliant(api, episode_id)

    episode = fx.read_episode(api, episode_id)
    assert episode["status"] == "RESOLVED_COMPLIANT"
    assert episode["sanction_level"] == 0
    asrt.assert_pct(episode["sanction_pct"], 0.00, "episode sanction_pct")
    assert episode["cure_plan_note"] == CURE_NOTE
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        compliance_status="ASSIGNED",
        sanction_level=0,
        sanction_pct=0.00,
        benefit_amount_cents=17000,
        closure_reason="NONE",
    )


def _case_sanctioned_once_with_recovery_underway(api):
    """A level-1 case in cure whose overpayment is actively being recouped."""
    context, episode_id = _case_with_conciliated_episode(
        api, "Escalation Household", allegation_reason="HOURS_SHORTFALL"
    )
    overpayment = fx.draft_overpayment(
        api,
        context.case_id,
        claim_type="CLIENT_ERROR",
        gross_amount_cents=5000,
        computation_method="GROSS",
    )
    fx.establish_overpayment(api, overpayment["id"])
    fx.post_recovery(api, overpayment["id"], method="CASH_PAYMENT", amount_cents=1000)
    fx.impose_sanction(api, episode_id)
    fx.begin_cure(api, episode_id, cure_plan_note="Submit two weeks of timesheets.")
    return context, episode_id, overpayment["id"]


def test_failed_cure_escalates_the_same_episode_instead_of_restarting_it(api):
    """PRD §3.7: "Coming from `CURE_PENDING` — the same-episode escalation that
    follows a failed cure — the episode's own `sanction_level` is raised by one,
    again capped at 3."
    PRD §3.7: "The rollup result then drives the payment dimension. When the
    recomputed case `sanction_level` is 2, an `ACTIVE` case moves
    `ACTIVE → SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/episode_cycles_sanction_imposed_to_cure_pending_and_back_with_escalation
    """
    context, episode_id, _overpayment_id = _case_sanctioned_once_with_recovery_underway(api)

    fx.impose_sanction(api, episode_id)

    episode = fx.read_episode(api, episode_id)
    assert episode["status"] == "SANCTION_IMPOSED"
    assert episode["sanction_level"] == 2
    asrt.assert_pct(episode["sanction_pct"], 0.50, "episode sanction_pct")
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="SUSPENDED",
        compliance_status="SANCTIONED",
        sanction_level=2,
        sanction_pct=0.50,
        benefit_amount_cents=8500,
        closure_reason="NONE",
    )


def test_second_visit_to_the_sanctioned_state_pauses_money_recovery(api):
    """PRD §3.7: "Either outcome, suspension or closure, then pauses money
    recovery: every overpayment claim of the case whose `recoupment_status` is
    `ACTIVE` becomes `PAUSED`."
    PRD §3.9: "The claim's `recoupment_status` becomes `ACTIVE` and the claim moves
    `ESTABLISHED → IN_RECOVERY`, or stays `IN_RECOVERY` on a subsequent entry, and
    each posting increments the claim's `version` by one."

    Design: Difficulty/non_linear_state_machine/episode_cycles_sanction_imposed_to_cure_pending_and_back_with_escalation
    """
    _context, episode_id, overpayment_id = _case_sanctioned_once_with_recovery_underway(api)
    before = fx.read_overpayment(api, overpayment_id)
    assert before["recoupment_status"] == "ACTIVE"

    fx.impose_sanction(api, episode_id)

    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, overpayment_id),
        status="IN_RECOVERY",
        recoupment_status="PAUSED",
        established_amount_cents=5000,
        total_recovered_cents=1000,
        balance_cents=4000,
    )


def _case_with_two_supported_activities(api):
    """Two ACTIVE activities, each carrying its own AUTHORIZED service money."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Fork Household"},
        incomes=STANDARD_INCOMES,
    )
    first = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    second = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="WORK_EXPERIENCE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    transportation = fx.build_authorized_service(
        api,
        context.case_id,
        first["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=45000,
    )
    child_care = fx.build_authorized_service(
        api,
        context.case_id,
        second["id"],
        service_type="CHILD_CARE",
        requested_amount_cents=50000,
    )
    return context, first["id"], second["id"], transportation["id"], child_care["id"]


def test_completed_activity_branch_leaves_its_service_money_untouched(api):
    """PRD §3.5: "The benign branch is `COMPLETED_ACTIVITY`: the assignment lands
    in `status` `COMPLETED`, its `cumulative_verified_hours` is frozen at whatever
    it had accumulated, and the assignment's supportive service authorizations are
    left completely untouched — a family that finished its activity keeps the child
    care it was awarded for the period."

    Design: Difficulty/non_linear_state_machine/assignment_termination_reason_forks_into_two_side_effect_sets
    """
    context, first_id, _second_id, transportation_id, _child_care_id = (
        _case_with_two_supported_activities(api)
    )

    fx.terminate_assignment(api, first_id, "COMPLETED_ACTIVITY")

    assignment = fx.read_assignment(api, first_id)
    assert assignment["status"] == "COMPLETED"
    assert assignment["termination_reason"] == "COMPLETED_ACTIVITY"
    asrt.assert_authorization(
        fx.read_authorization(api, transportation_id),
        status="AUTHORIZED",
        authorized_amount_cents=45000,
    )
    case = fx.read_case(api, context.case_id)
    asrt.assert_money(
        case["supportive_fy_authorized_cents"], 95000, "supportive fiscal-year total"
    )


def test_adverse_branch_voids_the_activity_service_money_and_frees_headroom(api):
    """PRD §3.5: "The adverse branch covers `NONCOMPLIANCE`, `CASE_CLOSED` and
    `PLAN_CHANGE`: the assignment lands in `status` `TERMINATED`, and every
    supportive service authorization of *that assignment* in `REQUESTED`, `HELD` or
    `AUTHORIZED` status is voided — its `void_reason` is recorded as
    `ASSIGNMENT_TERMINATED`, its `authorized_amount_cents` returns to 0, and the
    case's `supportive_fy_authorized_cents` is recomputed so that the freed
    fiscal-year headroom is restored exactly, as §2.11 requires."

    Design: Difficulty/non_linear_state_machine/assignment_termination_reason_forks_into_two_side_effect_sets
    """
    context, _first_id, second_id, transportation_id, child_care_id = (
        _case_with_two_supported_activities(api)
    )

    fx.terminate_assignment(api, second_id, "NONCOMPLIANCE")

    assignment = fx.read_assignment(api, second_id)
    assert assignment["status"] == "TERMINATED"
    assert assignment["termination_reason"] == "NONCOMPLIANCE"
    asrt.assert_authorization(
        fx.read_authorization(api, child_care_id),
        status="VOIDED",
        authorized_amount_cents=0,
        void_reason="ASSIGNMENT_TERMINATED",
    )
    asrt.assert_authorization(
        fx.read_authorization(api, transportation_id),
        status="AUTHORIZED",
        authorized_amount_cents=45000,
    )
    case = fx.read_case(api, context.case_id)
    asrt.assert_money(
        case["supportive_fy_authorized_cents"], 45000, "supportive fiscal-year total"
    )
