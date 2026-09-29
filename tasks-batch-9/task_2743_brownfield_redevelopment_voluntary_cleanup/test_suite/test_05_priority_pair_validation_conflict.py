"""
Requests that break two rules at once and must report the earlier one.

Each pair below is wrong in two ways simultaneously, and the declared precedence order
decides which refusal comes back: a state error ahead of a fiscal floor, a safety rule
ahead of a referential pin check, and an ownership check ahead of the frozen-parcel gate.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_CREDITED_CONTROL_MISSING,
    ERR_INVALID_POLICY_STATE,
    ERR_LIMIT_BELOW_MINIMUM,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PINNED_GOAL_VERSION_STALE,
    ERR_SITE_FROZEN,
    REVIEWER_ALPHA,
    add_control,
    add_event,
    add_party,
    add_plan,
    add_policy,
    assert_fields,
    assert_number,
    close_comment,
    file_result,
    impose_obligation,
    make_redeveloper_headers,
    redeveloper_payload,
    run_sweep,
    single_monitoring_line,
    stage_assessed,
    stage_enrolled,
    stage_plan,
    stage_plan_approved,
    submit_plan,
    technical_review,
)

SMALL_PLAN_TOTAL_CENTS = 1714373
SMALL_LIMIT_CENTS = 10000000
SMALL_ATTACHMENT_CENTS = 2392057


def _two_quotes_on_a_small_remedy(api):
    """
    An approved but tiny remedy carrying two successive quotes.

    The remedy is small enough that thirty percent of its underwriting estimate rounds up
    to a limit below the carrier's binding floor, so both policies are unbindable on the
    fiscal rule — which is exactly what makes the precedence observable.
    """
    world = stage_enrolled(api)
    stage_plan(world, cost_lines=single_monitoring_line(), years_to_construction_start=2)
    stage_plan_approved(world)

    first = add_policy(
        world,
        expected_remedial_action_plan_version=world.read_plan()["version"],
        policy_reference="CCP-2743-S1",
        term_years=3,
    )
    second = add_policy(
        world,
        expected_remedial_action_plan_version=world.read_plan()["version"],
        policy_reference="CCP-2743-S2",
        term_years=5,
    )
    return world, first, second


# ─── bind_policy_state_error_precedes_limit_minimum_rejects_superseded_quote ────


def test_binding_the_superseded_quote_reports_the_state_error(api):
    """
    The superseded quote fails the state check long before the fiscal floor is reached.

    "Attempting to bind a policy that is not `QUOTED` — already `BOUND`, `SUPERSEDED` by a
    newer quote, or `CANCELLED` by a revision request or an enrollment withdrawal — is
    refused with `ERR_INVALID_POLICY_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/bind_policy_state_error_precedes_limit_minimum_rejects_superseded_quote
    """
    world, first, _second = _two_quotes_on_a_small_remedy(api)
    assert_fields(world.read_policy(first), limit_cents=SMALL_LIMIT_CENTS)

    response = world.api.bind_policy(first["id"], world.insurer_headers)
    validate_error(response, ERR_INVALID_POLICY_STATE, 409)


def test_binding_the_current_quote_reports_the_minimum_limit(api):
    """
    With the state check satisfied the fiscal rule finally speaks.

    "and `limit_cents` must be at least 25,000,000 cents, since carriers do not bind a cap
    below a 250,000.00 limit, else `ERR_LIMIT_BELOW_MINIMUM`"

    Design: Difficulty/priority_pair_validation_conflict/bind_policy_state_error_precedes_limit_minimum_rejects_superseded_quote
    """
    world, _first, second = _two_quotes_on_a_small_remedy(api)

    response = world.api.bind_policy(second["id"], world.insurer_headers)
    validate_error(response, ERR_LIMIT_BELOW_MINIMUM, 422)


def test_neither_refusal_binds_anything_or_moves_the_funding_need(api):
    """
    A superseded quote contributes nothing and a refused bind leaves the file alone.

    "Any prior policy on the same plan whose `status` is `QUOTED` becomes `SUPERSEDED`
    with its `version` incremented by 1 — a superseded quote's premium never enters the
    plan's funding need, since only bound premiums do."

    Design: Difficulty/priority_pair_validation_conflict/bind_policy_state_error_precedes_limit_minimum_rejects_superseded_quote
    """
    world, first, second = _two_quotes_on_a_small_remedy(api)
    world.api.bind_policy(first["id"], world.insurer_headers)
    world.api.bind_policy(second["id"], world.insurer_headers)

    assert_fields(
        world.read_policy(first),
        status="SUPERSEDED",
        bound_at=None,
        policy_reference="CCP-2743-S1",
        attachment_point_cents=SMALL_ATTACHMENT_CENTS,
        limit_cents=SMALL_LIMIT_CENTS,
    )
    assert_fields(
        world.read_policy(second),
        status="QUOTED",
        bound_at=None,
        policy_reference="CCP-2743-S2",
        attachment_point_cents=SMALL_ATTACHMENT_CENTS,
        limit_cents=SMALL_LIMIT_CENTS,
    )
    assert_fields(
        world.read_plan(),
        status="APPROVED",
        total_estimate_cents=SMALL_PLAN_TOTAL_CENTS,
        total_funding_need_cents=SMALL_PLAN_TOTAL_CENTS,
    )


# ─── approve_credited_control_error_precedes_pinned_goal_version ────────────────


def _plan_at_the_join_without_its_credited_control(api):
    """
    A remedy with both branches landed, no control built, and one goal re-versioned.

    The unrestricted goal's version is bumped after the pins were captured, so the pin
    check is guaranteed to fail as well — leaving the precedence to decide the answer.
    """
    world = stage_enrolled(api)
    world.plan = add_plan(world)
    submit_plan(world)
    technical_review(world, decision="PASS")
    close_comment(world, public_comment_count=3)

    event = add_event(
        world,
        cleanup_goal_id=world.goal_unrestricted["id"],
        monitoring_period_code="2026-M12",
        sample_date="2026-12-05",
        window_start="2026-12-01T00:00:00Z",
        window_end="2026-12-15T00:00:00Z",
    )
    file_result(world, event, 160.0)
    return world


def _add_credited_control(world):
    """Build the vapour-mitigation control the restricted goal credits."""
    return add_control(
        world,
        control_type="VAPOR_MITIGATION",
        sub_area_code="BLDG-A-SLAB",
        coverage_from="2027-01-01",
        coverage_to="2027-06-30",
        inspection_interval_days=90,
    )


def test_the_missing_credited_control_is_reported_before_the_stale_pin(api):
    """
    The safety rule speaks first even though the pin is stale too.

    "Placing the safety family ahead of the referential and fiscal families is deliberate:
    a request that is simultaneously unsafe and unaffordable reports the safety failure,
    because the safety failure is the one the reviewer must act on."

    Design: Difficulty/priority_pair_validation_conflict/approve_credited_control_error_precedes_pinned_goal_version
    """
    world = _plan_at_the_join_without_its_credited_control(api)

    response = world.api.approve_plan(world.plan["id"], REVIEWER_ALPHA)
    validate_error(response, ERR_CREDITED_CONTROL_MISSING, 422)


def test_building_the_control_uncovers_the_stale_pin(api):
    """
    With the remedy made safe, the server reports the divergence it was masking.

    "And every entry of `pinned_cleanup_goal_versions` must still match the referenced
    goal's current `version`, else `ERR_PINNED_GOAL_VERSION_STALE`."

    Design: Difficulty/priority_pair_validation_conflict/approve_credited_control_error_precedes_pinned_goal_version
    """
    world = _plan_at_the_join_without_its_credited_control(api)
    _add_credited_control(world)

    response = world.api.approve_plan(world.plan["id"], REVIEWER_ALPHA)
    validate_error(response, ERR_PINNED_GOAL_VERSION_STALE, 409)


def test_neither_refusal_approves_the_remedy_or_its_control(api):
    """
    Both branches stay where they landed and the proposed control is not promoted.

    "For every cleanup goal on the site whose `basis` is `RESTRICTED`, this plan must carry
    a site control whose `control_type` equals that goal's `control_credit_type` and whose
    `status` is `PROPOSED`, `APPROVED` or `OPERATING` — a risk-based goal that credits a
    control the remedy does not build is refused with `ERR_CREDITED_CONTROL_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/approve_credited_control_error_precedes_pinned_goal_version
    """
    world = _plan_at_the_join_without_its_credited_control(api)
    world.api.approve_plan(world.plan["id"], REVIEWER_ALPHA)
    control = _add_credited_control(world)
    world.api.approve_plan(world.plan["id"], REVIEWER_ALPHA)

    assert_fields(
        world.read_plan(),
        status="PUBLIC_COMMENT",
        technical_review_state="PASSED",
        public_comment_state="CLOSED",
        public_comment_count=3,
        approved_by_user_id=None,
        approved_at=None,
    )
    assert_fields(world.read_control(control), status="PROPOSED")
    assert_fields(world.read_enrollment(), status="ENROLLED")
    assert_fields(
        world.read_goal(world.goal_unrestricted),
        compliant_streak=1,
        attainment_status="NOT_ATTAINED",
    )

# ─── certify_owner_check_precedes_site_frozen_gate ──────────────────────────────

FROZEN_DUTIES = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls.", "2027-06-30"),
    (
        "LAND_USE_RESTRICTION_COMPLIANCE",
        "Comply with the recorded environmental covenant.",
        "2027-06-30",
    ),
    (
        "INSTITUTIONAL_CONTROL_MAINTENANCE",
        "Inspect and maintain the sub-slab depressurisation system.",
        "2027-02-05",
    ),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 48 hours notice.", "2027-02-05"),
    ("NOTIFICATION", "Report newly discovered releases within 10 days.", "2027-02-05"),
)

TARGET_DUTY = "INSTITUTIONAL_CONTROL_MAINTENANCE"


def _frozen_parcel_with_a_lapsed_duty(api):
    """
    A parcel frozen by a lapsed defence-critical duty, plus a second redeveloper.

    Every duty is past its deadline once the sweep runs, so the target duty is at once
    owned by somebody else, sitting on a frozen parcel, and in a state certification
    does not accept — three refusals competing for the same request.
    """
    world = stage_assessed(api)
    for category, description, due_date in FROZEN_DUTIES:
        world.obligations[category] = impose_obligation(
            world,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=90,
        )
    run_sweep(world, "2027-07-01")
    stranger = add_party(
        world, redeveloper_payload(legal_name="Harborline Property Group LLC")
    )
    return world, world.obligations[TARGET_DUTY], stranger


def test_the_wrong_redeveloper_is_told_it_does_not_own_the_parcel(api):
    """
    Ownership is settled before the parcel's posture is even consulted.

    "Ownership checks on any resource that references a `Party` in the owner slot compare
    that resource's site's `owner_party_id` to `X-User-ID`; a mismatch is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/certify_owner_check_precedes_site_frozen_gate
    """
    world, duty, stranger = _frozen_parcel_with_a_lapsed_duty(api)
    assert_fields(world.read_site(), cleanup_posture="FROZEN")

    response = world.api.certify_obligation(
        duty["id"], make_redeveloper_headers(stranger["id"])
    )
    validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)


def test_the_true_owner_is_told_the_parcel_is_frozen_not_that_the_duty_lapsed(api):
    """
    Once ownership holds, the frozen gate answers ahead of the duty's own state.

    "Placing the frozen-site gate ahead of every state-machine check is equally
    deliberate: a forfeited defence surfaces as `ERR_SITE_FROZEN` rather than being masked
    by whatever state the target child happens to be in."

    Design: Difficulty/priority_pair_validation_conflict/certify_owner_check_precedes_site_frozen_gate
    """
    world, duty, _stranger = _frozen_parcel_with_a_lapsed_duty(api)

    response = world.api.certify_obligation(duty["id"], world.redev_headers)
    validate_error(response, ERR_SITE_FROZEN, 409)


def test_neither_refusal_records_a_certification(api):
    """
    The lapsed duty keeps its closed period and the forfeited defence stays at zero.

    "Certifying a duty that is already `SATISFIED`, or one that has `LAPSED`, is refused
    with `ERR_INVALID_OBLIGATION_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/certify_owner_check_precedes_site_frozen_gate
    """
    world, duty, stranger = _frozen_parcel_with_a_lapsed_duty(api)
    world.api.certify_obligation(duty["id"], make_redeveloper_headers(stranger["id"]))
    world.api.certify_obligation(duty["id"], world.redev_headers)

    assert_fields(
        world.read_obligation(duty),
        status="LAPSED",
        certification_count=0,
        due_date="2027-02-05",
        prior_due_date=None,
        certified_at=None,
    )
    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="LAPSED",
        bfpp_status="FORFEITED",
        obligations_total_weight=20,
        current_weight=0,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=20,
    )
    assert_number(protection["compliance_pct"], "0.0000", "compliance_pct")
