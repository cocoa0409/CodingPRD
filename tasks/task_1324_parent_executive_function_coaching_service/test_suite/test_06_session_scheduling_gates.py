"""Session scheduling gates: state, shape, track, cadence, and the
plan-state-vs-credit priority conflict (PRD §3.6, §2.8)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    purchase_package,
    schedule_session,
    schedule_session_ok,
    set_clock,
    setup_active_plan_scenario,
    validate_error,
    validate_success,
)


def test_scheduling_succeeds_while_plan_and_package_active(api, admin_headers):
    """PRD §3.6: "Sessions are scheduled under an `ACTIVE` plan by the plan's
    coach, supplying the `package_id` of the individual-track package that will
    fund the session"
    PRD §3.6: "A successfully created session starts with `attendance_state`
    `SCHEDULED` and `billing_state` `RESERVED`, raises the funding package's
    `reserved_count` by one, and recomputes the plan's posture."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_gated_by_plan_and_package_states
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam GD",
        primary_email="gd@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 4},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")
    assert session["attendance_state"] == "SCHEDULED"
    assert session["billing_state"] == "RESERVED"
    assert session["coach_id"] == coach["id"], "coach_id copied from the plan"

    after = validate_success(api.get_package(package["id"], admin_headers))
    assert after["reserved_count"] == 1
    assert after["credits_remaining"] == 4, "a reservation never decrements remaining"


def test_scheduling_rejected_after_package_refund(api, admin_headers):
    """PRD §3.6: "The named package must be `ACTIVE` — an `EXPIRED`,
    `EXHAUSTED`, or `REFUNDED` package is rejected with
    `ERR_PACKAGE_NOT_ACTIVE`"
    PRD §3.3: "it is `SCHEDULING_BLOCKED` when any of four conditions holds —
    the family is not `ACTIVE`, the client is not `ACTIVE`, the plan's coach is
    `INACTIVE`, or the family holds no package of track `INDIVIDUAL` in
    `ACTIVE` status whose `credits_remaining` minus `reserved_count` is at
    least 1."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_gated_by_plan_and_package_states
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam GD2",
        primary_email="gd2@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 4},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    schedule_session_ok(plan["id"], coach["id"], package["id"],
                        "2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")

    refunded = validate_success(api.refund_package(package["id"], admin_headers))
    assert refunded["status"] == "REFUNDED"

    posture = validate_success(api.get_plan(plan["id"], admin_headers))["posture"]
    assert posture == "SCHEDULING_BLOCKED", (
        "no ACTIVE INDIVIDUAL package with available credit remains"
    )

    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-12T15:00:00Z", "2026-08-12T16:00:00Z")
    validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACTIVE)


def test_terminated_plan_with_zero_credits_returns_plan_not_active(api, admin_headers):
    """PRD §2.8: "When several validation rules could reject the same request,
    the server evaluates them in a strict priority order, and the first failure
    wins — later checks never mask earlier ones." The order places "the plan
    status gate (`ERR_PLAN_NOT_ACTIVE`)" before "credit availability
    (`ERR_NO_CREDITS_AVAILABLE`)".
    PRD §3.6: "The package must hold at least one available credit:
    `credits_remaining` minus `reserved_count` must be at least 1, else
    `ERR_NO_CREDITS_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/plan_terminated_with_zero_credits_returns_plan_not_active
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam PC",
        primary_email="pc@example.com",
        num_clients=2,
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    coach, package = ctx["coach"], ctx["packages"][0]
    plan1, plan2 = ctx["plans"]
    # The single credit is fully reserved by plan 1's session.
    schedule_session_ok(plan1["id"], coach["id"], package["id"],
                        "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    fam_h = make_family_headers(ctx["family"]["id"])
    terminated = validate_success(api.transition_plan(plan2["id"], "TERMINATED", fam_h))
    assert terminated["status"] == "TERMINATED"

    # Both violations hold: plan not ACTIVE, and remaining(1) - reserved(1) = 0.
    resp = schedule_session(plan2["id"], coach["id"], package["id"],
                            "2026-08-10T17:00:00Z", "2026-08-10T18:00:00Z")
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


def test_terminated_plan_rejection_leaves_package_untouched(api, admin_headers):
    """PRD §2.8: "the first failure wins — later checks never mask earlier
    ones." A scheduling request that fails the plan status gate
    (`ERR_PLAN_NOT_ACTIVE`) must not consume or reserve package credit:
    PRD §3.5: "The derived `credits_remaining` must always equal
    `credits_total` minus `credits_consumed` minus `credits_forfeited` — the
    INV-CREDITS identity — and a reservation never decrements
    `credits_remaining`; it merely raises `reserved_count`."

    Design: Difficulty/priority_pair_validation_conflict/plan_terminated_with_zero_credits_returns_plan_not_active
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam PC2",
        primary_email="pc2@example.com",
        num_clients=2,
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    coach, package = ctx["coach"], ctx["packages"][0]
    plan1, plan2 = ctx["plans"]
    schedule_session_ok(plan1["id"], coach["id"], package["id"],
                        "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    fam_h = make_family_headers(ctx["family"]["id"])
    api.transition_plan(plan2["id"], "TERMINATED", fam_h)

    resp = schedule_session(plan2["id"], coach["id"], package["id"],
                            "2026-08-10T17:00:00Z", "2026-08-10T18:00:00Z")
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["reserved_count"] == 1
    assert package_after["credits_remaining"] == 1
    assert package_after["credits_consumed"] == 0
    plan2_after = validate_success(api.get_plan(plan2["id"], admin_headers))
    assert plan2_after["status"] == "TERMINATED"


def test_session_in_past_rejected(api):
    """PRD §3.6: "Request shape requires the start to be strictly in the future
    at creation (a start at or before now is rejected with
    `ERR_SESSION_IN_PAST`), the end to be strictly after the start, and the
    duration to be no more than 120 minutes (`ERR_VALIDATION` on range
    violations)."

    Design: Corner/errors/session_in_past_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam SP",
        primary_email="sp@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    # Advance the clock past activation so the past-dated start still lies
    # inside the 14-day first-session cadence window (§3.6). §2.8 evaluates
    # cadence windows before temporal rules, so only a start that passes the
    # cadence window can surface ERR_SESSION_IN_PAST.
    set_clock("2026-08-05T00:00:00Z")
    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SESSION_IN_PAST)


def test_session_duration_over_120_minutes_rejected(api):
    """PRD §3.6: "Request shape requires the start to be strictly in the future
    at creation (a start at or before now is rejected with
    `ERR_SESSION_IN_PAST`), the end to be strictly after the start, and the
    duration to be no more than 120 minutes (`ERR_VALIDATION` on range
    violations)."

    Design: Corner/validations/session_duration_over_120_minutes_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam DU",
        primary_email="du@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 2},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-05T15:00:00Z", "2026-08-05T17:30:00Z")
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_session_against_group_package_rejected(api):
    """PRD §3.6: "The named package must be `ACTIVE` — an `EXPIRED`,
    `EXHAUSTED`, or `REFUNDED` package is rejected with
    `ERR_PACKAGE_NOT_ACTIVE` — and its track must be `INDIVIDUAL`, since
    individual sessions cannot draw group credits (`ERR_TRACK_MISMATCH`)."

    Design: Corner/validations/session_against_group_package_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam TM",
        primary_email="tm@example.com",
        tracks=["HYBRID"],
        package={"track": "GROUP", "credits_total": 4},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")
    validate_error(resp, ApiErrorId.ERR_TRACK_MISMATCH)


def test_cadence_gap_below_minimum_rejected_then_maximum_allowed(api):
    """PRD §3.6: "For a `WEEKLY` cadence, the first session of the plan must
    start within 14 days of the plan's `activated_at` (a start on the
    activation instant itself up to and including day 14 is acceptable), and
    each subsequent session must start at least 4 days and at most 10 days
    after the anchor, both bounds inclusive, compared to the exact second."
    PRD §3.6: "A violation of either window is rejected with
    `ERR_CADENCE_WINDOW_VIOLATION`."

    Design: Corner/calculations/cadence_gap_below_minimum_rejected_then_maximum_allowed
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam CG2",
        primary_email="cg2@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 4},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    schedule_session_ok(plan["id"], coach["id"], package["id"],
                        "2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z")

    # 3-day gap: below the inclusive 4-day minimum.
    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-06T15:00:00Z", "2026-08-06T16:00:00Z")
    validate_error(resp, ApiErrorId.ERR_CADENCE_WINDOW_VIOLATION)

    # 10-day gap: exactly the inclusive maximum.
    ok = schedule_session_ok(plan["id"], coach["id"], package["id"],
                             "2026-08-13T15:00:00Z", "2026-08-13T16:00:00Z")
    assert ok["attendance_state"] == "SCHEDULED"
