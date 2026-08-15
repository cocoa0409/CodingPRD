"""Session completion, cancellation tiers, and no-show fees (PRD §3.6, §2.6)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    schedule_session_ok,
    set_clock,
    setup_active_plan_scenario,
    setup_one_credit_session,
    setup_three_session_package,
    validate_error,
    validate_success,
)


def test_cancel_at_exactly_24h_notice_is_free(api):
    """PRD §3.6: "Notice of at least 24 hours — exactly 24 hours to the second
    qualifies — is free: the session moves to `CANCELLED_EARLY`, billing moves
    from `RESERVED` to `RETURNED`, `cancellation_fee_cents` is zero, the
    package's `reserved_count` falls by one, and the package status and plan
    posture recompute."

    Design: Difficulty/boundary_precision_check/cancel_notice_exactly_24h_boundary
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam CB",
        primary_email="cb@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 8},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    # Clock to exactly 24h00m00s before the start.
    set_clock("2026-08-09T15:00:00Z")
    cancelled = validate_success(
        api.cancel_session(session["id"], make_family_headers(ctx["family"]["id"]))
    )
    assert cancelled["attendance_state"] == "CANCELLED_EARLY"
    assert cancelled["billing_state"] == "RETURNED"
    assert cancelled["cancellation_fee_cents"] == 0


def test_cancel_at_24h_releases_reservation_without_forfeiture(api, admin_headers):
    """PRD §3.6: "Notice of at least 24 hours — exactly 24 hours to the second
    qualifies — is free: the session moves to `CANCELLED_EARLY`, billing moves
    from `RESERVED` to `RETURNED`, `cancellation_fee_cents` is zero, the
    package's `reserved_count` falls by one"
    PRD §3.5: "a reservation never decrements `credits_remaining`; it merely
    raises `reserved_count`."

    Design: Difficulty/boundary_precision_check/cancel_notice_exactly_24h_boundary
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam CB2",
        primary_email="cb2@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 8},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    set_clock("2026-08-09T15:00:00Z")
    validate_success(
        api.cancel_session(session["id"], make_family_headers(ctx["family"]["id"]))
    )
    after = validate_success(api.get_package(package["id"], admin_headers))
    assert after["reserved_count"] == 0
    assert after["credits_forfeited"] == 0
    assert after["credits_remaining"] == 8
    assert after["credits_consumed"] == 0


def test_cancel_late_fee_nested_rounding(api, admin_headers):
    """PRD §3.6: "notice of at least 4 hours but under 24 hours — exactly 4
    hours qualifies for the half tier — charges 50 percent of the package's
    `per_credit_value_cents`, rounded half-up (the per-credit value was already
    rounded at purchase, and the fee rounds again); notice under 4 hours
    charges the full `per_credit_value_cents`."
    PRD §3.6: "Notice under 24 hours moves the session to `CANCELLED_LATE` and
    billing to `FORFEITED`: the package's `credits_forfeited` rises by one,
    `reserved_count` falls by one, and the package status recomputes."

    Design: Difficulty/combinatorial_formula/cancellation_fee_nested_rounding
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam NR",
        primary_email="nr@example.com",
        num_clients=2,
        package={"track": "INDIVIDUAL", "credits_total": 8},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    # 23h notice => HALF tier. pcv = round_half_up(110500/8) = 13813;
    # fee = round_half_up(0.5 x 13813) = 6907.
    set_clock("2026-08-09T16:00:00Z")
    cancelled = validate_success(
        api.cancel_session(session["id"], make_family_headers(ctx["family"]["id"]))
    )
    assert cancelled["attendance_state"] == "CANCELLED_LATE"
    assert cancelled["billing_state"] == "FORFEITED"
    assert cancelled["cancellation_fee_cents"] == 6907

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["price_paid_cents"] == 110500  # 120000 x 0.9 + 2500
    assert package_after["per_credit_value_cents"] == 13813
    assert package_after["credits_forfeited"] == 1
    assert package_after["credits_remaining"] == 7


def test_cancel_late_fee_triggers_family_suspension(api, admin_headers):
    """PRD §2.6: "When such a fee leaves the family's outstanding balance
    strictly above 20000 cents and the family is `ACTIVE`, the family is
    automatically moved to `SUSPENDED`, and every `ACTIVE` coaching plan of
    every client of the family has its posture recomputed to
    `SCHEDULING_BLOCKED`."
    PRD §3.6: "The fee is added to the family's `total_charged_cents`, and the
    delinquency cascade of §2.6 applies"

    Design: Difficulty/combinatorial_formula/cancellation_fee_nested_rounding
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam NR2",
        primary_email="nr2@example.com",
        num_clients=2,
        package={"track": "INDIVIDUAL", "credits_total": 8},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    set_clock("2026-08-09T16:00:00Z")
    validate_success(
        api.cancel_session(session["id"], make_family_headers(ctx["family"]["id"]))
    )
    family = validate_success(api.get_family(ctx["family"]["id"], admin_headers))
    assert family["total_charged_cents"] == 110500 + 6907 == 117407
    assert family["outstanding_balance_cents"] == 117407
    assert family["billing_status"] == "DELINQUENT"
    assert family["status"] == "SUSPENDED", "fee charge triggers auto-suspension"


def test_session_parallel_dimensions_three_exits(api):
    """PRD §3.6: "Completion moves attendance to `COMPLETED`, billing from
    `RESERVED` to `CONSUMED`, stamps `resolved_at`"
    PRD §3.6: cancel with >= 24h notice: "the session moves to
    `CANCELLED_EARLY`, billing moves from `RESERVED` to `RETURNED`,
    `cancellation_fee_cents` is zero"
    PRD §3.6: no-show: "the session moves to `NO_SHOW` with billing
    `FORFEITED`, `cancellation_fee_cents` equal to the full
    `per_credit_value_cents`"

    Design: Difficulty/non_linear_state_machine/session_parallel_dimensions
    """
    ctx = setup_three_session_package()
    plan, coach = ctx["plans"][0], ctx["coach"]
    s1, s2, s3 = ctx["sessions"]
    fam_h = make_family_headers(ctx["family"]["id"])
    coach_h = make_coach_headers(coach["id"])

    set_clock("2026-08-03T15:30:00Z")
    r1 = validate_success(api.complete_session(s1["id"], coach_h))
    assert (r1["attendance_state"], r1["billing_state"]) == ("COMPLETED", "CONSUMED")

    set_clock("2026-08-06T00:00:00Z")  # 48h notice => FREE
    r2 = validate_success(api.cancel_session(s2["id"], fam_h))
    assert (r2["attendance_state"], r2["billing_state"]) == ("CANCELLED_EARLY", "RETURNED")
    assert r2["cancellation_fee_cents"] == 0

    set_clock("2026-08-13T16:00:00Z")  # at the end => started
    r3 = validate_success(api.mark_no_show(s3["id"], coach_h))
    assert (r3["attendance_state"], r3["billing_state"]) == ("NO_SHOW", "FORFEITED")
    # 8-credit INDIVIDUAL, one client: pcv = round_half_up(122500/8) = 15313.
    assert r3["cancellation_fee_cents"] == 15313


def test_session_parallel_dimensions_package_counters(api, admin_headers):
    """PRD §3.6: completion "increments the package's `credits_consumed` by one
    while decrementing `reserved_count` by one"; no-show increments
    `credits_forfeited` and decrements `reserved_count`; a free cancel only
    releases the reservation.
    PRD §3.5: "The derived `credits_remaining` must always equal
    `credits_total` minus `credits_consumed` minus `credits_forfeited` — the
    INV-CREDITS identity"

    Design: Difficulty/non_linear_state_machine/session_parallel_dimensions
    """
    ctx = setup_three_session_package()
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    s1, s2, s3 = ctx["sessions"]
    fam_h = make_family_headers(ctx["family"]["id"])
    coach_h = make_coach_headers(coach["id"])

    set_clock("2026-08-03T15:30:00Z")
    get_success_data(api.complete_session(s1["id"], coach_h))
    set_clock("2026-08-06T00:00:00Z")
    get_success_data(api.cancel_session(s2["id"], fam_h))
    set_clock("2026-08-13T16:00:00Z")
    get_success_data(api.mark_no_show(s3["id"], coach_h))

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["credits_consumed"] == 1
    assert package_after["credits_forfeited"] == 1
    assert package_after["credits_remaining"] == 6
    assert package_after["reserved_count"] == 0


def test_no_show_before_start_rejected(api):
    """PRD §3.6: "A no-show is the coach's mirror of the full-fee tier: the
    acting coach must be the session's `coach_id` (`ERR_FORBIDDEN_SCOPE`), the
    session must have started (`ERR_SESSION_NOT_STARTED`)"

    Design: Corner/state_machines/no_show_before_start_rejected
    """
    ctx = setup_one_credit_session("2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")
    coach = ctx["coach"]
    # Clock is still the startup default 2026-08-01, ahead of the start.
    resp = api.mark_no_show(ctx["session"]["id"], make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED)


def test_cancel_after_start_rejected(api):
    """PRD §3.6: "A cancellation attempted at or after the start is rejected
    with `ERR_SESSION_ALREADY_STARTED`."

    Design: Corner/state_machines/cancel_after_start_rejected
    """
    ctx = setup_one_credit_session("2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z")
    set_clock("2026-08-03T16:00:00Z")
    resp = api.cancel_session(
        ctx["session"]["id"], make_family_headers(ctx["family"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_ALREADY_STARTED)
