"""The rulemaking transition schedule and the enforcement gates."""
from test_helpers import (
    ADMIN_EFFECTIVE_ID,
    ApiErrorId,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_error,
)


def test_01_backlog_annualization_uses_the_sixty_day_window_and_the_notice_clamp(api):
    """"`projected_permit_backlog` is the approved backlog multiplied by 60 and
    divided by 365, with the result taken down to the next lower whole permit by
    floor division. The annualization always uses the 60-day provisional window,
    never the notice period this same calculation goes on to produce." A backlog
    of 2,410 annualizes to 396, which is "below 500" so the grace tier is 90
    days, and then "`notice_days` clamps that tier up to the statutory minimum of
    120 days".

    Design: Difficulty/combinatorial_formula/adoption_schedule_pinned_evaluation_order_and_notice_clamp
    """
    world = fixtures.setup_rulemaking_cycle(api)

    rule = get_success_data(
        api.create_adoption_rule(
            {
                "code_cycle_id": world["cycle_id"],
                "title": "2027 State Code Adoption Order",
            },
            make_council_admin_headers(),
        ),
        201,
    )

    assert rule["status"] == "DRAFT"
    assert rule["projected_permit_backlog"] == 396
    assert rule["transition_grace_days"] == 90
    assert rule["notice_days"] == 120

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_permit_backlog_count"] == 2410


def test_02_the_schedule_dates_hang_off_the_midnight_base_date(api):
    """"`base_date` is the order's `created_at` truncated to midnight UTC",
    "`effective_date` is then `base_date` advanced by `notice_days` whole days,
    expressed at midnight UTC", "`transition_cutoff_date` equals `effective_date`
    exactly", and "`prior_code_expiry_date` is `effective_date` advanced by a
    further 365 whole days".

    Design: Difficulty/combinatorial_formula/adoption_schedule_pinned_evaluation_order_and_notice_clamp
    """
    world = fixtures.setup_rulemaking_cycle(api)

    rule = get_success_data(
        api.create_adoption_rule(
            {
                "code_cycle_id": world["cycle_id"],
                "title": "2027 State Code Adoption Order",
            },
            make_council_admin_headers(),
        ),
        201,
    )

    assert rule["base_date"] == "2026-10-05T00:00:00Z"
    assert rule["effective_date"] == "2027-02-02T00:00:00Z"
    assert rule["transition_cutoff_date"] == "2027-02-02T00:00:00Z"
    assert rule["prior_code_expiry_date"] == "2028-02-02T00:00:00Z"


def _untrained_statewide_world(api):
    """A published order whose effective date has arrived, with one large
    jurisdiction trained to 80.00 on the attendance basis and one untrained."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_harborview(api, world)
    fixtures.setup_delivered_session_riverbend_only(api, world=world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_EFFECTIVE_DATE)
    return world


def test_03_statewide_readiness_is_weighted_over_every_jurisdiction(api):
    """"Statewide readiness is a population-weighted average computed over
    **every** registered jurisdiction with no filter whatsoever — including a
    jurisdiction registered moments earlier that has done no training at all —
    because enforcement begins statewide." At 1,200,000 residents on 80.00
    against 300,000 residents on 0.00 the weighted average is 64.00, and "if the
    result is below 80.00 the transition fails".

    Design: Difficulty/cross_entity_state_dependency/rule_effective_blocked_by_statewide_training_readiness
    """
    world = _untrained_statewide_world(api)

    response = fixtures.advance_rule(
        api, world, "EFFECTIVE", make_council_admin_headers(ADMIN_EFFECTIVE_ID)
    )
    validate_error(response, ApiErrorId.ERR_TRAINING_READINESS_NOT_MET, 422)


def test_04_a_blocked_enforcement_leaves_the_order_and_cycle_untouched(api):
    """A failed enforcement move snapshots nothing: only a successful transition
    "supersedes rivals ... and bubbles up to the cycle, taking it `RULEMAKING` →
    `ADOPTED`", and only then "the value is snapshotted onto
    `statewide_readiness_pct_at_effective`".

    Design: Difficulty/cross_entity_state_dependency/rule_effective_blocked_by_statewide_training_readiness
    """
    world = _untrained_statewide_world(api)

    fixtures.advance_rule(
        api, world, "EFFECTIVE", make_council_admin_headers(ADMIN_EFFECTIVE_ID)
    )

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["status"] == "PUBLISHED"
    assert rule["statewide_readiness_pct_at_effective"] is None

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "RULEMAKING"

    riverbend = get_success_data(
        api.get_jurisdiction(world["riverbend_id"], make_council_admin_headers())
    )
    harborview = get_success_data(
        api.get_jurisdiction(world["harborview_id"], make_council_admin_headers())
    )
    assert riverbend["compliance_pct_attendance_basis"] == 80.00
    assert harborview["compliance_pct_attendance_basis"] == 0.00
