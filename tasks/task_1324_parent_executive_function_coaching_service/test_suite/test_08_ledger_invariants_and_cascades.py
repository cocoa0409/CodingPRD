"""Family ledger invariants, delinquency boundary, and depth-3 cascades
(PRD §2.6, §3.5, §3.6, §3.10)."""
from test_helpers import (
    ApiErrorId,
    activate_family,
    add_client,
    assert_inv_credits,
    assert_inv_money,
    create_family,
    create_open_workshop,
    enroll_ok,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    schedule_session,
    set_clock,
    setup_active_plan_scenario,
    setup_one_credit_session,
    setup_three_session_package,
    validate_error,
    validate_success,
)


def test_no_show_exhausts_package_and_blocks_plan(api, admin_headers):
    """PRD §3.5: "When `credits_remaining` reaches zero after a consume or
    forfeit mutation, an `ACTIVE` package moves to `EXHAUSTED`, and the posture
    of every `ACTIVE` plan of the family's clients is recomputed — to
    `SCHEDULING_BLOCKED` when no other `ACTIVE` individual-track package with
    an available credit exists."
    PRD §3.6: "the session moves to `NO_SHOW` with billing `FORFEITED`,
    `cancellation_fee_cents` equal to the full `per_credit_value_cents`"

    Design: Difficulty/transitive_cascade/no_show_exhaustion_posture_cascade
    """
    ctx = setup_one_credit_session()
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    set_clock("2026-08-03T16:00:00Z")
    no_show = validate_success(
        api.mark_no_show(ctx["session"]["id"], make_coach_headers(coach["id"]))
    )
    # 1-credit package: price 15000 + 2500 = 17500, pcv = 17500.
    assert no_show["cancellation_fee_cents"] == 17500

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["status"] == "EXHAUSTED"
    assert package_after["credits_remaining"] == 0
    assert package_after["credits_forfeited"] == 1

    posture = validate_success(api.get_plan(plan["id"], admin_headers))["posture"]
    assert posture == "SCHEDULING_BLOCKED"


def test_no_show_fee_suspends_family(api, admin_headers):
    """PRD §2.6: "When such a fee leaves the family's outstanding balance
    strictly above 20000 cents and the family is `ACTIVE`, the family is
    automatically moved to `SUSPENDED`, and every `ACTIVE` coaching plan of
    every client of the family has its posture recomputed to
    `SCHEDULING_BLOCKED`."
    PRD §2.8: the validation order places "the family status gate
    (`ERR_FAMILY_NOT_ACTIVE`)" before "package status
    (`ERR_PACKAGE_NOT_ACTIVE`)".

    Design: Difficulty/transitive_cascade/no_show_exhaustion_posture_cascade
    """
    ctx = setup_one_credit_session()
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    set_clock("2026-08-03T16:00:00Z")
    get_success_data(api.mark_no_show(ctx["session"]["id"], make_coach_headers(coach["id"])))

    family = validate_success(api.get_family(ctx["family"]["id"], admin_headers))
    # 17500 purchase + 17500 no-show fee.
    assert family["total_charged_cents"] == 35000
    assert family["status"] == "SUSPENDED"
    assert_inv_money(family)

    # Scheduling against the now-suspended family fails the family gate first,
    # ahead of the exhausted package.
    resp = schedule_session(plan["id"], coach["id"], package["id"],
                            "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    validate_error(resp, ApiErrorId.ERR_FAMILY_NOT_ACTIVE)


def test_credit_conservation_complete_and_early_cancel(api, admin_headers):
    """PRD §3.6: "Notice of at least 24 hours — exactly 24 hours to the second
    qualifies — is free: the session moves to `CANCELLED_EARLY`, billing moves
    from `RESERVED` to `RETURNED`, `cancellation_fee_cents` is zero, the
    package's `reserved_count` falls by one"
    PRD §3.6: "Completion moves attendance to `COMPLETED`, billing from
    `RESERVED` to `CONSUMED`, stamps `resolved_at`, increments the package's
    `credits_consumed` by one while decrementing `reserved_count` by one"

    Design: Difficulty/compensating_invariant/credit_conservation_under_complete_and_early_cancel
    """
    ctx = setup_three_session_package()
    coach, package = ctx["coach"], ctx["packages"][0]
    s1, s2, _s3 = ctx["sessions"]
    fam_h = make_family_headers(ctx["family"]["id"])

    set_clock("2026-08-03T15:30:00Z")
    get_success_data(api.complete_session(s1["id"], make_coach_headers(coach["id"])))
    set_clock("2026-08-06T00:00:00Z")  # 48h notice => FREE cancel
    cancelled = validate_success(api.cancel_session(s2["id"], fam_h))
    assert cancelled["billing_state"] == "RETURNED"
    assert cancelled["cancellation_fee_cents"] == 0

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["credits_consumed"] == 1
    assert package_after["credits_forfeited"] == 0
    assert package_after["credits_remaining"] == 7
    assert package_after["reserved_count"] == 1  # only s3 still holds one


def test_credit_conservation_inv_credits_identity(api, admin_headers):
    """PRD §3.5: "The derived `credits_remaining` must always equal
    `credits_total` minus `credits_consumed` minus `credits_forfeited` — the
    INV-CREDITS identity — and a reservation never decrements
    `credits_remaining`; it merely raises `reserved_count`."

    Design: Difficulty/compensating_invariant/credit_conservation_under_complete_and_early_cancel
    """
    ctx = setup_three_session_package()
    coach, package = ctx["coach"], ctx["packages"][0]
    s1, s2, _s3 = ctx["sessions"]
    fam_h = make_family_headers(ctx["family"]["id"])

    set_clock("2026-08-03T15:30:00Z")
    get_success_data(api.complete_session(s1["id"], make_coach_headers(coach["id"])))
    set_clock("2026-08-06T00:00:00Z")
    get_success_data(api.cancel_session(s2["id"], fam_h))

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert_inv_credits(package_after)
    assert package_after["credits_total"] == 8


def test_money_conservation_enroll_then_workshop_cancel(api, admin_headers):
    """PRD §2.6: "the family's `outstanding_balance_cents` must always equal
    its `total_charged_cents` minus its `total_refunded_cents` minus its
    `total_paid_cents`. This identity, known as INV-MONEY, is an invariant the
    server re-establishes after every ledger mutation; it is never permitted to
    drift."
    PRD §3.10: "When no candidate exists, the enrollment bills in money:
    `billing_source` is `MONEY`, `charged_cents` equals the workshop's
    `price_cents`, and the amount is added to the family's
    `total_charged_cents`"

    Design: Difficulty/compensating_invariant/money_conservation_under_enroll_and_workshop_cancel
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam MC", primary_email="mc@example.com", tracks=["HYBRID"]
    )
    family, client, coach = ctx["family"], ctx["clients"][0], ctx["coach"]
    workshop = create_open_workshop(coach["id"], title="Money Lab", capacity=5,
                                    price_cents=15000)
    enrollment = enroll_ok(workshop["id"], client["id"], family["id"])
    assert enrollment["billing_source"] == "MONEY"
    assert enrollment["charged_cents"] == 15000

    family_mid = validate_success(api.get_family(family["id"], admin_headers))
    assert family_mid["total_charged_cents"] == 15000
    assert family_mid["outstanding_balance_cents"] == 15000
    assert_inv_money(family_mid)


def test_money_conservation_inv_money_identity(api, admin_headers):
    """PRD §3.10: "Cancelling — from either `OPEN` or `LOCKED` — runs the
    refund cascade: every `ENROLLED` enrollment moves to `REFUNDED`, refunding
    money-billed enrollments into the family's `total_refunded_cents`"
    PRD §2.6: "the family's `outstanding_balance_cents` must always equal its
    `total_charged_cents` minus its `total_refunded_cents` minus its
    `total_paid_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_under_enroll_and_workshop_cancel
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam MC2", primary_email="mc2@example.com", tracks=["HYBRID"]
    )
    family, client, coach = ctx["family"], ctx["clients"][0], ctx["coach"]
    workshop = create_open_workshop(coach["id"], title="Money Lab", capacity=5,
                                    price_cents=15000)
    enroll_ok(workshop["id"], client["id"], family["id"])

    cancelled = validate_success(
        api.transition_workshop(workshop["id"], "CANCELLED", admin_headers)
    )
    assert cancelled["status"] == "CANCELLED"

    enrollments = validate_success(api.list_enrollments(workshop["id"], admin_headers))
    assert enrollments[0]["status"] == "REFUNDED"

    family_end = validate_success(api.get_family(family["id"], admin_headers))
    assert family_end["total_charged_cents"] == 15000, "charges are immutable"
    assert family_end["total_refunded_cents"] == 15000
    assert family_end["outstanding_balance_cents"] == 0, (
        "enroll + cancel pair nets zero"
    )
    assert_inv_money(family_end)


def test_family_closed_terminal_lockdown_rejected(api, admin_headers):
    """PRD §3.1: "Closing a family is permitted from either `ACTIVE` or
    `SUSPENDED`, but only when the household carries no live commitments"
    PRD §2.8: "a state transition requested for a from-state the machine does
    not permit — including any write against a terminal state — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/family_closed_terminal_lockdown_rejected
    """
    family = create_family("Fam TL", "tl@example.com")
    add_client(family["id"], full_name="Kid TL", date_of_birth="2014-03-01")
    activate_family(family["id"])
    closed = validate_success(api.transition_family(family["id"], "CLOSED", admin_headers))
    assert closed["status"] == "CLOSED"

    resp = api.transition_family(family["id"], "ACTIVE", admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_delinquency_threshold_exact_20000_boundary(api, admin_headers):
    """PRD §2.6: "The family is `DELINQUENT` if and only if its
    `outstanding_balance_cents` is strictly greater than 20000 cents; an
    outstanding balance of exactly 20000 cents remains `CURRENT`."
    PRD §3.1: "A payment may clear `DELINQUENT` back to `CURRENT`, but it never
    un-suspends the family — only the administrator's explicit reinstatement
    transition does that."
    PRD §3.1: "Reinstating a `SUSPENDED` family to `ACTIVE` requires the
    family's `outstanding_balance_cents` to be no more than 20000 cents — a
    balance strictly above the threshold is rejected with
    `ERR_FAMILY_DELINQUENT`"

    Design: Corner/calculations/delinquency_threshold_exact_20000_boundary
    """
    ctx = setup_one_credit_session()
    coach = ctx["coach"]
    fam_id = ctx["family"]["id"]
    set_clock("2026-08-03T16:00:00Z")
    get_success_data(api.mark_no_show(ctx["session"]["id"], make_coach_headers(coach["id"])))

    family_mid = validate_success(api.get_family(fam_id, admin_headers))
    assert family_mid["status"] == "SUSPENDED"
    assert family_mid["outstanding_balance_cents"] == 35000

    # Pay 15000: outstanding lands exactly on the 20000 threshold.
    paid = validate_success(
        api.record_payment(fam_id, 15000, make_family_headers(fam_id)),
        expected_status=201,
    )
    assert paid["outstanding_balance_cents"] == 20000
    assert paid["billing_status"] == "CURRENT", "strict >: exactly 20000 is CURRENT"
    assert paid["status"] == "SUSPENDED", "a payment never un-suspends"

    reactivated = validate_success(api.transition_family(fam_id, "ACTIVE", admin_headers))
    assert reactivated["status"] == "ACTIVE", "20000 <= 20000 allows reinstatement"
