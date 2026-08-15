"""Session lifecycle forks at the sweep, the minimum-enrollment cancellation
chain, sweep payment-timeout expiry, and money conservation on cancellation."""
from test_helpers import (
    PC,
    ApiErrorId,
    activate_session_by_sweep,
    assert_instant_eq,
    drop_registration,
    find_refund_transaction,
    get_contract,
    get_household_credit,
    get_registration,
    get_session,
    register_and_pay,
    register_participant,
    run_sweep,
    set_clock,
    setup_household_with_participants,
    setup_household_with_scholarship,
    setup_multi_session_catalog,
    setup_published_session,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api


def test_cancel_cancelled_session_rejected(api):
    """PRD §2.8: "Generic state-machine legality — the attempted trigger must
    be defined for the entity's current state. Publishing an already-published
    session, dropping an already-dropped registration, verifying an
    already-verified form, withdrawing a denied application, closing a season
    before its registration deadline, or completing a session with unfinished
    meetings are all `ERR_INVALID_STATE`."
    PRD §3.9: "The coordinator may cancel a `PUBLISHED` or `ACTIVE` session
    outright, and the season sweep may cancel a `PUBLISHED` session that fails
    its enrollment check; both paths land on `CANCELLED`, setting
    `cancellation_reason` to `ADMIN` for a manual cancel or `LOW_ENROLLMENT`
    for a sweep cancel, and both run the same full cascade."

    Design: Corner/state_machines/cancel_cancelled_session_rejected
    """
    ctx = setup_published_session(clock=None)
    session_id = ctx["session"]["id"]
    cancelled = validate_success(_api.cancel_class_session(session_id, PC))
    assert cancelled["status"] == "CANCELLED"

    resp = _api.cancel_class_session(session_id, PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def _two_sessions_under_check() -> dict:
    """Sessions SG (will reach 2 enrolled) and SL (will reach 1), both
    min_enrollment 2. The family threshold is raised so every pinned fee
    stays 3000 for the household's three registrations."""
    catalog = setup_multi_session_catalog(
        [
            {"title": "SG", "min_enrollment": 2, "fee_resident_cents": 3000,
             "fee_nonresident_cents": 3000},
            {"title": "SL", "min_enrollment": 2, "fee_resident_cents": 3000,
             "fee_nonresident_cents": 3000},
        ],
        season_overrides={"family_discount_threshold": 99},
        clock=None,
    )
    sg, sl = catalog["sessions"]
    household, parts = setup_household_with_participants(count=3, account_name="HB",
                                                         name_prefix="Art")
    set_clock("2026-08-17T00:00:00Z")
    register_and_pay(sg["session"]["id"], parts[0]["id"], household["id"])
    register_and_pay(sg["session"]["id"], parts[1]["id"], household["id"])
    register_and_pay(sl["session"]["id"], parts[2]["id"], household["id"])
    set_clock("2026-09-08T00:00:00Z")
    return {"catalog": catalog, "sg": sg, "sl": sl}


def test_min_enrollment_equality_activates(api):
    """PRD §3.9: "Step two evaluates minimum enrollment for every session of a
    `PUBLISHED` season whose own status is still `PUBLISHED` and whose
    `enrollment_check_at` is at or before now, processed in
    `enrollment_check_at` ascending order with `created_at` ascending
    tie-breaks: a session whose `enrolled_count` reaches its `min_enrollment`
    — equality passes — activates from `PUBLISHED` to `ACTIVE`, while one that
    falls short is cancelled with `cancellation_reason` `LOW_ENROLLMENT` and
    the full cascade above. The sweep responds with a summary of the run:
    `activated_session_ids`, `cancelled_session_ids`,
    `expired_registration_ids`, and `promoted_registration_ids`, and every
    mutated entity's `version` increments."

    Design: Difficulty/boundary_precision_check/min_enrollment_equality_survives_vs_below_cancels
    """
    scenario = _two_sessions_under_check()
    sg, sl = scenario["sg"], scenario["sl"]

    summary = run_sweep(scenario["catalog"]["season"]["id"])
    # enrolled_count == min_enrollment == 2: equality passes.
    assert get_session(sg["session"]["id"])["status"] == "ACTIVE"
    assert sg["session"]["id"] in summary["activated_session_ids"]
    assert sg["session"]["id"] not in summary["cancelled_session_ids"]


def test_min_enrollment_below_cancels(api):
    """PRD §3.9: "a session whose `enrolled_count` reaches its
    `min_enrollment` — equality passes — activates from `PUBLISHED` to
    `ACTIVE`, while one that falls short is cancelled with
    `cancellation_reason` `LOW_ENROLLMENT` and the full cascade above. The
    sweep responds with a summary of the run: `activated_session_ids`,
    `cancelled_session_ids`, `expired_registration_ids`, and
    `promoted_registration_ids`, and every mutated entity's `version`
    increments."

    Design: Difficulty/boundary_precision_check/min_enrollment_equality_survives_vs_below_cancels
    """
    scenario = _two_sessions_under_check()
    sg, sl = scenario["sg"], scenario["sl"]

    summary = run_sweep(scenario["catalog"]["season"]["id"])
    # enrolled_count 1 == min_enrollment - 1: falls short.
    session = get_session(sl["session"]["id"])
    assert session["status"] == "CANCELLED"
    assert session["cancellation_reason"] == "LOW_ENROLLMENT"
    assert sl["session"]["id"] in summary["cancelled_session_ids"]
    assert sl["session"]["id"] not in summary["activated_session_ids"]


def _branching_sessions() -> dict:
    """SA (2 enrolled, paid) and SB (1 enrolled, paid; contract cancellation
    guarantee 700), both min_enrollment 2 under one published season."""
    catalog = setup_multi_session_catalog(
        [
            {"title": "SA", "min_enrollment": 2, "fee_resident_cents": 5000,
             "fee_nonresident_cents": 5000},
            {"title": "SB", "min_enrollment": 2, "fee_resident_cents": 5000,
             "fee_nonresident_cents": 5000,
             "contract_overrides": {"cancellation_guarantee_cents": 700}},
        ],
        season_overrides={"family_discount_threshold": 99},
        clock=None,
    )
    sa, sb = catalog["sessions"]
    household, parts = setup_household_with_participants(count=3, account_name="HF",
                                                         name_prefix="Dancer")
    set_clock("2026-08-17T00:00:00Z")
    register_and_pay(sa["session"]["id"], parts[0]["id"], household["id"])
    register_and_pay(sa["session"]["id"], parts[1]["id"], household["id"])
    r3 = register_and_pay(sb["session"]["id"], parts[2]["id"], household["id"])
    set_clock("2026-09-08T00:00:00Z")
    return {"catalog": catalog, "sa": sa, "sb": sb, "r3": r3}


def test_sweep_fork_passing_branch(api):
    """PRD §3.9: "a session whose `enrolled_count` reaches its
    `min_enrollment` — equality passes — activates from `PUBLISHED` to
    `ACTIVE`, while one that falls short is cancelled with
    `cancellation_reason` `LOW_ENROLLMENT` and the full cascade above."

    Design: Difficulty/non_linear_state_machine/class_session_branching_terminal_paths
    """
    scenario = _branching_sessions()
    sa = scenario["sa"]

    summary = run_sweep(scenario["catalog"]["season"]["id"])
    assert get_session(sa["session"]["id"])["status"] == "ACTIVE"
    assert sa["session"]["id"] in summary["activated_session_ids"]
    # The passing branch leaves the ACCEPTED contract untouched.
    assert get_contract(sa["contract"]["id"])["status"] == "ACCEPTED"


def test_sweep_fork_failing_branch(api):
    """PRD §3.9: "both paths land on `CANCELLED`, setting
    `cancellation_reason` to `ADMIN` for a manual cancel or `LOW_ENROLLMENT`
    for a sweep cancel, and both run the same full cascade. Every `ENROLLED`
    registration moves to `CANCELLED` with `drop_reason` matching the
    session's reason, and each runs the cancellation variant of the refund
    rule: a full one hundred percent of `net_paid_cents`, regardless of
    timing, issued through the standard ledger path — `PENDING` and
    `REFUND_PENDING` at or above the review threshold, auto-`COMPLETED` and
    `REFUNDED` below it with the household credited, a never-paid `PENDING`
    axis voided, and `WAIVED` left alone." and "The contract follows:
    `ACCEPTED` moves to `TERMINATED` with `payout_cents` equal to
    `cancellation_guarantee_cents`, `OFFERED` moves to `VOID` with
    `payout_cents` zero, and `DECLINED` is unchanged."

    Design: Difficulty/non_linear_state_machine/class_session_branching_terminal_paths
    """
    scenario = _branching_sessions()
    sb, r3 = scenario["sb"], scenario["r3"]

    summary = run_sweep(scenario["catalog"]["season"]["id"])
    session = get_session(sb["session"]["id"])
    assert session["status"] == "CANCELLED"
    assert session["cancellation_reason"] == "LOW_ENROLLMENT"
    assert sb["session"]["id"] in summary["cancelled_session_ids"]

    registration = get_registration(r3["id"])
    assert registration["enrollment_status"] == "CANCELLED"
    assert registration["drop_reason"] == "LOW_ENROLLMENT"
    assert registration["refund_total_cents"] == 5000   # 100%, auto-approved
    assert registration["payment_status"] == "REFUNDED"

    contract = get_contract(sb["contract"]["id"])
    assert contract["status"] == "TERMINATED"
    assert contract["payout_cents"] == 700


def _sweep_chain_scenario() -> dict:
    """Session with capacity 2 / min_enrollment 2 (contract cancellation
    guarantee 2500) holding R1 ENROLLED+paid and R2 WAITLISTED unpaid; swept at
    the enrollment check with enrolled_count 1 < min_enrollment 2.

    PRD §2.8/§3.2 forbid creating a session with min_enrollment above
    capacity, so the geometry is built PRD-legally: the session starts at
    capacity 1 / min_enrollment 1, R1 fills the seat, R2 waitlists, and an
    OCC-guarded patch (§3.2) then raises capacity and min_enrollment to 2 —
    the patch's only floor check is capacity >= enrolled_count, and no
    promotion trigger fires on a capacity increase (§3.8), so R2 stays
    WAITLISTED with the seat formally open."""
    ctx = setup_published_session(
        capacity=1, min_enrollment=1, fee_resident_cents=5000,
        fee_nonresident_cents=5000,
        contract_overrides={"cancellation_guarantee_cents": 2500},
        clock=None,
    )
    session_id = ctx["session"]["id"]
    household_1, parts_1 = setup_household_with_participants(count=1, account_name="H1")
    household_2, parts_2 = setup_household_with_participants(count=1, account_name="H2")
    set_clock("2026-08-17T00:00:00Z")
    r1 = register_and_pay(session_id, parts_1[0]["id"], household_1["id"])
    r2 = register_participant(session_id, parts_2[0]["id"], household_2["id"])
    assert r2["enrollment_status"] == "WAITLISTED"
    validate_success(_api.patch_class_session(
        session_id,
        {"capacity": 2, "min_enrollment": 2,
         "expected_class_session_version": get_session(session_id)["version"]},
        PC,
    ))
    set_clock("2026-09-08T00:00:00Z")
    return {"ctx": ctx, "h1": household_1, "r1": r1, "r2": r2}


def test_sweep_cancellation_chain_registration_hops(api):
    """PRD §3.9: "Every `ENROLLED` registration moves to `CANCELLED` with
    `drop_reason` matching the session's reason, and each runs the
    cancellation variant of the refund rule: a full one hundred percent of
    `net_paid_cents`, regardless of timing, issued through the standard ledger
    path — `PENDING` and `REFUND_PENDING` at or above the review threshold,
    auto-`COMPLETED` and `REFUNDED` below it with the household credited, a
    never-paid `PENDING` axis voided, and `WAIVED` left alone. Every
    `WAITLISTED` registration likewise moves to `CANCELLED` with the same
    `drop_reason`, its `PENDING` axis voided and `WAIVED` untouched, and no
    promotion runs because the session is terminal."
    PRD §3.9: "The sweep responds with a summary of the run:
    `activated_session_ids`, `cancelled_session_ids`,
    `expired_registration_ids`, and `promoted_registration_ids`, and every
    mutated entity's `version` increments."

    Design: Difficulty/transitive_cascade/sweep_min_enrollment_cancellation_chain
    """
    scenario = _sweep_chain_scenario()
    ctx = scenario["ctx"]

    summary = run_sweep(ctx["season"]["id"])
    assert summary["cancelled_session_ids"] == [ctx["session"]["id"]]

    session = get_session(ctx["session"]["id"])
    assert session["status"] == "CANCELLED"
    assert session["cancellation_reason"] == "LOW_ENROLLMENT"

    r1 = get_registration(scenario["r1"]["id"])
    assert r1["enrollment_status"] == "CANCELLED"
    assert r1["drop_reason"] == "LOW_ENROLLMENT"

    r2 = get_registration(scenario["r2"]["id"])
    assert r2["enrollment_status"] == "CANCELLED"
    assert r2["drop_reason"] == "LOW_ENROLLMENT"
    assert r2["payment_status"] == "VOID"          # never paid: voided
    assert r2["refund_total_cents"] == 0


def test_sweep_cancellation_chain_money_and_contract_hops(api):
    """PRD §3.9: "each runs the cancellation variant of the refund rule: a
    full one hundred percent of `net_paid_cents`, regardless of timing, issued
    through the standard ledger path — `PENDING` and `REFUND_PENDING` at or
    above the review threshold, auto-`COMPLETED` and `REFUNDED` below it with
    the household credited, a never-paid `PENDING` axis voided, and `WAIVED`
    left alone." and "The contract follows: `ACCEPTED` moves to `TERMINATED`
    with `payout_cents` equal to `cancellation_guarantee_cents`, `OFFERED`
    moves to `VOID` with `payout_cents` zero, and `DECLINED` is unchanged."
    PRD §3.7: "Every refund the center owes flows back as household credit."

    Design: Difficulty/transitive_cascade/sweep_min_enrollment_cancellation_chain
    """
    scenario = _sweep_chain_scenario()
    ctx = scenario["ctx"]

    run_sweep(ctx["season"]["id"])

    r1 = get_registration(scenario["r1"]["id"])
    assert r1["payment_status"] == "REFUNDED"      # 5000 < 10000 auto-approved
    assert r1["refund_total_cents"] == 5000
    refund = find_refund_transaction(scenario["r1"]["id"])
    assert refund["status"] == "COMPLETED"
    assert refund["amount_cents"] == 5000
    assert get_household_credit(scenario["h1"]["id"]) == 5000

    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "TERMINATED"
    assert contract["payout_cents"] == 2500


def test_sweep_payment_timeout_expiry(api):
    """PRD §3.9: "Step one expires stalled payments: every registration in the
    season that is `ENROLLED` with a `PENDING` payment axis whose
    `payment_due_at` is set and at or before now moves to `EXPIRED` with
    `drop_reason` `PAYMENT_TIMEOUT`; its payment axis voids — nothing was
    paid, so there is nothing to refund — the session's `enrolled_count`
    decreases by one, and the promotion selector runs immediately for that
    session before the next expiry is processed." and "because an in-sweep
    promotion sets the new enrollee's deadline forty-eight hours ahead, a
    registration promoted during the sweep never expires within the same
    sweep."

    Design: Corner/cross_cutting_complexity_layers/sweep_payment_timeout_expiry
    """
    # enrollment_check_at (2026-09-08) is after the test clock, so the sweep's
    # step two skips this session and it stays PUBLISHED.
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000, clock=None)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    household_c, parts_c = setup_household_with_participants(count=1, account_name="HC")
    set_clock("2026-08-17T00:00:00Z")
    ra = register_and_pay(session_id, parts_a[0]["id"], household_a["id"])
    rb = register_participant(session_id, parts_b[0]["id"], household_b["id"])
    rc = register_participant(session_id, parts_c[0]["id"], household_c["id"])

    # RA drops; RB is promoted with a 48h deadline (2026-08-19T00:00:00Z).
    drop_registration(ra["id"], household_a["id"])
    assert_instant_eq(get_registration(rb["id"])["payment_due_at"],
                      "2026-08-19T00:00:00Z")

    # One second past RB's deadline; RB never paid. The next sweep expires it
    # and immediately promotes RC with a fresh 48h deadline anchored at sweep
    # time.
    set_clock("2026-08-19T00:00:01Z")
    summary = run_sweep(ctx["season"]["id"])
    assert rb["id"] in summary["expired_registration_ids"]
    assert rc["id"] in summary["promoted_registration_ids"]

    expired = get_registration(rb["id"])
    assert expired["enrollment_status"] == "EXPIRED"
    assert expired["drop_reason"] == "PAYMENT_TIMEOUT"
    assert expired["payment_status"] == "VOID"

    promoted = get_registration(rc["id"])
    assert promoted["enrollment_status"] == "ENROLLED"
    assert promoted["payment_status"] == "PENDING"
    assert_instant_eq(promoted["payment_due_at"], "2026-08-21T00:00:01Z")
    assert get_session(session_id)["enrolled_count"] == 1


def _conservation_scenario() -> dict:
    """Session at 6000/6000: R1 paid in full; R2 carries a 100% scholarship
    (fee 0, WAIVED)."""
    catalog = setup_multi_session_catalog(
        [{"title": "Woodwork", "fee_resident_cents": 6000,
          "fee_nonresident_cents": 6000}],
        season_overrides={"scholarship_budget_cents": 100000},
    )
    session_id = catalog["sessions"][0]["session"]["id"]
    household_1, parts_1 = setup_household_with_participants(count=1, account_name="H1")
    r1 = register_and_pay(session_id, parts_1[0]["id"], household_1["id"])
    household_2, parts_2, _app = setup_household_with_scholarship(
        catalog["season"]["id"], 100, 6000, count=1, account_name="H2",
        name_prefix="Chip",
    )
    r2 = register_participant(session_id, parts_2[0]["id"], household_2["id"])
    return {"catalog": catalog, "h1": household_1, "h2": household_2,
            "r1": r1, "r2": r2}


def test_cancellation_conserves_participant_money(api):
    """PRD §3.9: "each runs the cancellation variant of the refund rule: a
    full one hundred percent of `net_paid_cents`, regardless of timing, issued
    through the standard ledger path — `PENDING` and `REFUND_PENDING` at or
    above the review threshold, auto-`COMPLETED` and `REFUNDED` below it with
    the household credited, a never-paid `PENDING` axis voided, and `WAIVED`
    left alone."

    Design: Difficulty/compensating_invariant/cancellation_money_conservation
    """
    scenario = _conservation_scenario()
    session_id = scenario["catalog"]["sessions"][0]["session"]["id"]

    validate_success(_api.cancel_class_session(session_id, PC))

    r1 = get_registration(scenario["r1"]["id"])
    # Money conserved: the household gets back exactly what it paid.
    assert r1["net_paid_cents"] == 6000
    assert r1["refund_total_cents"] == 6000 == r1["net_paid_cents"]
    assert r1["payment_status"] == "REFUNDED"    # 6000 < 10000 auto-approved
    assert get_household_credit(scenario["h1"]["id"]) == 6000


def test_cancellation_waived_registration_has_zero_movement(api):
    """PRD §3.6: "One whose pinned fee is zero moves straight from `PENDING`
    to `WAIVED`, with no deadline."
    PRD §3.9: "Every `ENROLLED` registration moves to `CANCELLED` with
    `drop_reason` matching the session's reason, and each runs the
    cancellation variant of the refund rule: a full one hundred percent of
    `net_paid_cents`, regardless of timing, issued through the standard ledger
    path — `PENDING` and `REFUND_PENDING` at or above the review threshold,
    auto-`COMPLETED` and `REFUNDED` below it with the household credited, a
    never-paid `PENDING` axis voided, and `WAIVED` left alone."

    Design: Difficulty/compensating_invariant/cancellation_money_conservation
    """
    scenario = _conservation_scenario()
    r2 = scenario["r2"]
    assert r2["fee_charged_cents"] == 0
    assert r2["payment_status"] == "WAIVED"

    session_id = scenario["catalog"]["sessions"][0]["session"]["id"]
    validate_success(_api.cancel_class_session(session_id, PC))

    after = get_registration(r2["id"])
    assert after["enrollment_status"] == "CANCELLED"
    assert after["payment_status"] == "WAIVED"     # untouched
    assert after["refund_total_cents"] == 0
    assert get_household_credit(scenario["h2"]["id"]) == 0
