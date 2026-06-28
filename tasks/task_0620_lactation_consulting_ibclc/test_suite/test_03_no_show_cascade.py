"""No-show suspension cascade, package-credit conservation on cancel, and the
state-vs-fiscal validation-priority conflict.

Depth instances (queue A): transitive_cascade, compensating_invariant,
priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_practice_with_consultant_and_client, create_consult,
    setup_client_with_two_strikes, no_show_consult,
    create_package, create_client, create_consultant, set_clock,
    create_completed_consult,
    create_consult_payload, create_feeding_assessment_payload,
    make_consultant_headers,
    TEST_USERS,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── transitive_cascade / no_show_strike_suspend_autocancel_depth3 ──────────

def test_third_no_show_suspends_client_and_autocancels_other_consult(api):
    """PRD §3.6: "when the freshly incremented strike count reaches three or more,
    the client's `status` is set to `SUSPENDED`."
    PRD §3.6: "the suspension itself fans out: every other consult of that client
    still in `SCHEDULED` status is automatically cancelled to `CANCELLED`".

    Two prior strikes plus a third no-show take strikes to 3, flip the client to
    SUSPENDED, and auto-cancel the client's other still-SCHEDULED future consult.

    Design: Difficulty/transitive_cascade/no_show_strike_suspend_autocancel_depth3
    """
    ctx = setup_client_with_two_strikes()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]

    future = create_consult(prac["id"], client["id"], cons["id"],
                            "2026-06-12T15:00:00Z", "2026-06-12T16:00:00Z")
    ns3 = create_consult(prac["id"], client["id"], cons["id"],
                         "2026-06-10T09:45:00Z", "2026-06-10T10:00:00Z")

    validate_success(api.no_show_consult(ns3["id"], FRONT_DESK), 200)

    client_after = get_success_data(api.get_client(client["id"], FRONT_DESK))
    assert client_after["no_show_strikes"] == 3, (
        f"expected 3 strikes, got {client_after['no_show_strikes']}")
    assert client_after["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {client_after['status']}")

    future_after = get_success_data(api.get_consult(future["id"], FRONT_DESK))
    assert future_after["status"] == "CANCELLED", (
        f"expected CANCELLED, got {future_after['status']}")


def test_no_show_increments_strike_count(api):
    """PRD §3.6: "First, the client's `no_show_strikes` is increased by one — a
    mutation on the client caused by this transition."

    A single no-show on an otherwise-clean client takes no_show_strikes from 0 to 1
    while the client stays ACTIVE (below the inclusive threshold of three).

    Design: Difficulty/transitive_cascade/no_show_strike_suspend_autocancel_depth3
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T10:00:00Z")
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    c1 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T09:00:00Z", "2026-06-10T09:15:00Z")
    validate_success(api.no_show_consult(c1["id"], FRONT_DESK), 200)

    client_after = get_success_data(api.get_client(client["id"], FRONT_DESK))
    assert client_after["no_show_strikes"] == 1
    assert client_after["status"] == "ACTIVE", (
        "two strikes do not suspend; one certainly does not")


# ─── compensating_invariant / package_credit_conserved_on_cancel ────────────

def test_package_credit_conserved_across_complete_and_cancel(api):
    """PRD §3.2: "`package_credits_remaining` is `package_credits_total` minus
    `package_credits_consumed` and is never allowed to go negative."
    PRD §3.6: "that credit is returned by decreasing the client's
    `package_credits_consumed` by one, never below zero, and
    `package_credits_remaining` is recomputed."

    From a 3-visit package: completing one PACKAGE consult consumes 1; cancelling a
    second committed one returns it. After both, total 3, consumed 1, remaining 2.

    Design: Difficulty/compensating_invariant/package_credit_conserved_on_cancel
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons = ctx["practice"], ctx["consultant"]
    pkg = create_package(prac["id"], "THREE_VISIT", included_visits=3, price_cents=30000)
    client = create_client(prac["id"], package_id=pkg["id"])

    # Consult 1: PACKAGE, completed (consumes a credit at completion).
    done = create_consult(prac["id"], client["id"], cons["id"],
                          "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z", pay_method="PACKAGE")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(done["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(done["id"], make_consultant_headers(cons["id"])))
    get_success_data(api.complete_consult(done["id"], make_consultant_headers(cons["id"])))

    # Consult 2: PACKAGE, scheduled then cancelled.
    cancel = create_consult(prac["id"], client["id"], cons["id"],
                            "2026-06-11T15:00:00Z", "2026-06-11T16:00:00Z", pay_method="PACKAGE")
    validate_success(api.cancel_consult(cancel["id"], FRONT_DESK), 200)

    client_after = get_success_data(api.get_client(client["id"], FRONT_DESK))
    assert client_after["package_credits_total"] == 3
    assert client_after["package_credits_consumed"] == 1, (
        f"expected consumed 1, got {client_after['package_credits_consumed']}")
    assert client_after["package_credits_remaining"] == 2, (
        f"expected remaining 2, got {client_after['package_credits_remaining']}")


def test_completing_package_consult_commits_one_credit(api):
    """PRD §3.5: "On completion, if the consult's `pay_method` is `PACKAGE`, the
    package credit is committed: `package_credit_redeemed` is set true, the client's
    `package_credits_consumed` is increased by one, and `package_credits_remaining`
    is recomputed accordingly."

    Completing a single PACKAGE consult from a 3-visit package takes consumed to 1
    and remaining to 2.

    Design: Difficulty/compensating_invariant/package_credit_conserved_on_cancel
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons = ctx["practice"], ctx["consultant"]
    pkg = create_package(prac["id"], "THREE_VISIT", included_visits=3, price_cents=30000)
    client = create_client(prac["id"], package_id=pkg["id"])

    done = create_consult(prac["id"], client["id"], cons["id"],
                          "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z", pay_method="PACKAGE")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(done["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(done["id"], make_consultant_headers(cons["id"])))
    completed = get_success_data(api.complete_consult(done["id"], make_consultant_headers(cons["id"])))
    assert completed["package_credit_redeemed"] is True

    client_after = get_success_data(api.get_client(client["id"], FRONT_DESK))
    assert client_after["package_credits_consumed"] == 1
    assert client_after["package_credits_remaining"] == 2


# ─── priority_pair / state_vs_fiscal_suspended_beats_no_credits ─────────────

def test_suspended_client_with_no_credits_reports_suspended_first(api):
    """PRD §2.7: "8. Client active-status — on consult scheduling and rescheduling,
    the target client is `ACTIVE` rather than `SUSPENDED`, else `ERR_CLIENT_SUSPENDED`."
    PRD §2.7: "13. Package-credit sufficiency — on consult scheduling with package
    payment, the client must hold at least one remaining credit, else
    `ERR_NO_PACKAGE_CREDITS`."

    A SUSPENDED client with zero package credits posting a PACKAGE consult violates
    both checks; the higher-priority client active-status check (8) wins over the
    package-credit check (13), so ERR_CLIENT_SUSPENDED is returned.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_suspended_beats_no_credits
    """
    # Practice + 1-visit package; client whose single credit is consumed, then 3 no-shows.
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T10:00:00Z")
    prac, cons = ctx["practice"], ctx["consultant"]
    pkg = create_package(prac["id"], "ONE_VISIT", included_visits=1, price_cents=10000)
    client = create_client(prac["id"], package_id=pkg["id"])

    # Consume the single package credit via a completed PACKAGE consult.
    c1 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T09:00:00Z", "2026-06-10T09:15:00Z", pay_method="PACKAGE")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(c1["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(c1["id"], make_consultant_headers(cons["id"])))
    get_success_data(api.complete_consult(c1["id"], make_consultant_headers(cons["id"])))

    # Three no-shows to suspend the client.
    for start, end in (("2026-06-10T09:15:00Z", "2026-06-10T09:30:00Z"),
                       ("2026-06-10T09:30:00Z", "2026-06-10T09:45:00Z"),
                       ("2026-06-10T09:45:00Z", "2026-06-10T09:55:00Z")):
        c = create_consult(prac["id"], client["id"], cons["id"], start, end)
        no_show_consult(c["id"])

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-15T15:00:00Z", "2026-06-15T16:00:00Z", pay_method="PACKAGE"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value)


def test_active_client_no_credits_reports_no_package_credits(api):
    """PRD §2.7: "13. Package-credit sufficiency — on consult scheduling with package
    payment, the client must hold at least one remaining credit, else
    `ERR_NO_PACKAGE_CREDITS`."

    Isolates the lower-priority fiscal check: an ACTIVE client whose only package
    credit is already consumed gets ERR_NO_PACKAGE_CREDITS — confirming the rule the
    suspension check pre-empts in the conflict scenario.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_suspended_beats_no_credits
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons = ctx["practice"], ctx["consultant"]
    pkg = create_package(prac["id"], "ONE_VISIT", included_visits=1, price_cents=10000)
    client = create_client(prac["id"], package_id=pkg["id"])

    c1 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z", pay_method="PACKAGE")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(c1["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(c1["id"], make_consultant_headers(cons["id"])))
    get_success_data(api.complete_consult(c1["id"], make_consultant_headers(cons["id"])))

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-11T15:00:00Z", "2026-06-11T16:00:00Z", pay_method="PACKAGE"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_NO_PACKAGE_CREDITS.value)
