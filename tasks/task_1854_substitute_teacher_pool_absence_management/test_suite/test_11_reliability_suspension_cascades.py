"""Reliability scoring, suspension, and the transitive cascades: lifetime vs
trailing windows, flag escalation into the do-not-return cascade, and
self-cancel-driven auto-suspension cascading across schools."""
from test_helpers import (
    TEST_USERS,
    accept_offer,
    basic_world,
    cancel_assignment_ok,
    get_absence,
    get_assignment,
    get_school,
    get_substitute,
    make_coordinator_headers,
    make_school,
    make_staff,
    make_substitute_headers,
    offer_assignment,
    onboard_substitute,
    raise_flag,
    report_absence,
    report_outcome,
    review_flag,
    set_logical_clock,
    validate_paginated,
)


def _no_show_ctx():
    """1-day absence Mon 2026-08-03 filled by sub A; NO_SHOW reported at
    2026-08-03T13:00:00Z."""
    ctx = basic_world()
    ctx["sub"] = onboard_substitute()
    ctx["absence"] = report_absence(
        ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03"
    )
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    offer = offer_assignment(ctx["absence"]["id"], ctx["sub"]["id"], coord_headers)
    accept_offer(offer["id"], ctx["sub"]["id"])
    set_logical_clock("2026-08-03T13:00:00Z")
    ctx["assignment"] = report_outcome(offer["id"], "NO_SHOW", coord_headers)
    return ctx


def test_no_show_event_never_ages_out_of_lifetime_score(api):
    """PRD 2.10: "Six event types exist with pinned deltas: `COMPLETION` at
    +1, `SUB_CANCEL_EARLY` at −5, `SUB_CANCEL_LATE` at −15, `NO_SHOW` at −25,
    `FLAG_MINOR` at −3, and `FLAG_MAJOR` at −10."
    PRD 2.10: "The `reliability_lifetime_score` starts from a baseline of 100,
    adds the deltas of every event ever recorded, and is clamped to the
    inclusive range 0 through 100; it is the score displayed on the
    substitute's profile, and old events never age out of it."

    Design: Difficulty/dual_variant_calc/reliability_lifetime_vs_trailing_window
    """
    ctx = _no_show_ctx()
    set_logical_clock("2026-11-20T00:00:00Z")
    sub = get_substitute(ctx["sub"]["id"])
    assert sub["reliability_lifetime_score"] == 75, (
        "100 - 25; the event never ages out of the lifetime variant"
    )


def test_trailing_score_recovers_once_event_leaves_window(api):
    """PRD 2.10: "The `reliability_trailing_score` applies the identical
    baseline, summation, and clamp, but counts only events whose `occurred_at`
    falls within the trailing window — by default the last 90 days, governed
    by the district's `reliability_window_days` — so an identical event log
    yields a different trailing score once events age past the window."
    PRD 2.10: "The trailing variant, never the lifetime one, drives dispatch
    ranking and suspension evaluation."

    Design: Difficulty/dual_variant_calc/reliability_lifetime_vs_trailing_window
    """
    ctx = _no_show_ctx()
    set_logical_clock("2026-11-20T00:00:00Z")
    sub = get_substitute(ctx["sub"]["id"])
    assert sub["reliability_trailing_score"] == 100, (
        "the NO_SHOW at 2026-08-03T13:00 lies outside the 90-day window "
        "ending 2026-11-20"
    )
    assert sub["reliability_lifetime_score"] == 75
    assert sub["reliability_trailing_score"] != sub["reliability_lifetime_score"]


def _flag_escalation_ctx():
    """Subs X (20000, registered first) and Y (18000) both ACTIVE and
    MATH/HIGH qualified; absence Mon 2026-08-03..Tue 2026-08-04; manual offer
    to X; X ACCEPTED (committed 40000); MAJOR CONDUCT flag raised on X."""
    ctx = basic_world()
    ctx["sub_x"] = onboard_substitute(full_name="Sub X", rate_cents=20000)
    ctx["sub_y"] = onboard_substitute(full_name="Sub Y", rate_cents=18000)
    ctx["absence"] = report_absence(
        ctx["teacher"], start_date="2026-08-03", end_date="2026-08-04"
    )
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    offer = offer_assignment(ctx["absence"]["id"], ctx["sub_x"]["id"], coord_headers)
    ctx["assignment"] = accept_offer(offer["id"], ctx["sub_x"]["id"])
    ctx["flag"] = raise_flag(
        ctx["sub_x"]["id"], ctx["school"]["id"], "CONDUCT", "MAJOR",
        coord_headers, assignment_id=ctx["assignment"]["id"],
    )
    return ctx


def test_escalate_flag_creates_sourced_dnr_mark(api, district_admin_headers):
    """PRD 3.8: "Escalation closes it `ESCALATED` and converts it into
    exclusion: an `ACTIVE` do-not-return mark is created for that school and
    substitute with `source_flag_id` pointing back at the flag — unless one
    already exists — and the full do-not-return cascade runs."
    PRD 3.8: "and, significantly, raising one immediately appends the matching
    reliability event, `FLAG_MINOR` (−3) or `FLAG_MAJOR` (−10), and runs
    suspension evaluation: flags move scores before any human review."

    Design: Difficulty/transitive_cascade/escalate_flag_dnr_cancel_reopen_reoffer
    """
    ctx = _flag_escalation_ctx()
    escalated = review_flag(ctx["flag"]["id"], "ESCALATE")
    assert escalated["status"] == "ESCALATED"

    marks, meta = validate_paginated(
        api.list_school_marks(
            ctx["school"]["id"],
            district_admin_headers,
            params={"mark_type": "DO_NOT_RETURN", "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1
    assert marks[0]["mark_type"] == "DO_NOT_RETURN"
    assert marks[0]["status"] == "ACTIVE"
    assert marks[0]["source_flag_id"] == ctx["flag"]["id"]
    assert marks[0]["substitute_id"] == ctx["sub_x"]["id"]

    sub_x = get_substitute(ctx["sub_x"]["id"])
    assert sub_x["reliability_trailing_score"] == 90, (
        "only the FLAG_MAJOR (-10) event; the DNR cascade carries no penalty"
    )


def test_escalate_flag_cascades_cancel_reopen_reoffer(api, district_admin_headers):
    """PRD 3.8: "Creating a `DO_NOT_RETURN` mark fires immediately: the
    substitute's future-dated `OFFERED` and `ACCEPTED` assignments at that
    school — those whose `end_date` is on or after the clock date — are
    cancelled with `cancel_reason` `DNR_CANCEL` and no reliability penalty,
    and each cancelled accepted assignment's absence reopens from `ASSIGNED`
    to `DISPATCHING` and re-runs the selector, from which the marked
    substitute is now excluded by §2.11."
    PRD 3.4: "its `offer_sequence` is a per-absence monotonically increasing
    number starting at 1, so the audit trail of who was asked first is never
    lost."

    Design: Difficulty/transitive_cascade/escalate_flag_dnr_cancel_reopen_reoffer
    """
    ctx = _flag_escalation_ctx()
    review_flag(ctx["flag"]["id"], "ESCALATE")

    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "CANCELLED"
    assert assignment["cancel_reason"] == "DNR_CANCEL"

    assert get_absence(ctx["absence"]["id"])["fill_status"] == "DISPATCHING"

    data, meta = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": ctx["absence"]["id"], "status": "OFFERED"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["substitute_id"] == ctx["sub_y"]["id"], (
        "X is excluded by the DNR eligibility filter"
    )
    assert data[0]["offer_sequence"] == 2

    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 0, (
        "the DNR cancel released the 40000 provisional reserve"
    )


def _suspension_cascade_ctx():
    """District with suspension_min_completions 0; schools S1 and S2; sub A
    qualified MATH/HIGH + SCIENCE/HIGH carrying 3 MAJOR flags (trailing 70);
    sub B qualified SCIENCE/HIGH only; A holds ACCEPTED assignments A1 (S1,
    Mon 2026-08-03..Tue 2026-08-04, MATH) and A2 (S2, Thu 2026-08-06..Fri
    2026-08-07, SCIENCE). Clock parked at 2026-08-02T12:00:00Z so cancelling
    A1 is a late cancel (12h lead < 24h)."""
    ctx = basic_world(district_config={"suspension_min_completions": 0}, clock=None)
    school2 = make_school(ctx["district"]["id"], name="S2", budget=1_000_000)
    teacher2 = make_staff(
        school2["id"], full_name="Teach Two", subject="SCIENCE", grade_band="HIGH"
    )
    sub_a = onboard_substitute(
        full_name="Sub A", rate_cents=20000,
        qualifications=(("MATH", "HIGH"), ("SCIENCE", "HIGH")),
    )
    sub_b = onboard_substitute(
        full_name="Sub B", rate_cents=18000, qualifications=(("SCIENCE", "HIGH"),)
    )
    admin = TEST_USERS["district_admin_headers"]
    for flag_type in ("CONDUCT", "TARDINESS", "QUALITY"):
        raise_flag(sub_a["id"], ctx["school"]["id"], flag_type, "MAJOR", admin)
    assert get_substitute(sub_a["id"])["reliability_trailing_score"] == 70

    set_logical_clock("2026-07-29T00:00:00Z")
    abs1 = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-04")
    abs2 = report_absence(
        teacher2, start_date="2026-08-06", end_date="2026-08-07",
        required_subject="SCIENCE",
    )
    asg1 = accept_offer(offer_assignment(abs1["id"], sub_a["id"], admin)["id"], sub_a["id"])
    asg2 = accept_offer(offer_assignment(abs2["id"], sub_a["id"], admin)["id"], sub_a["id"])
    set_logical_clock("2026-08-02T12:00:00Z")
    ctx.update({
        "school2": school2, "teacher2": teacher2,
        "sub_a": sub_a, "sub_b": sub_b,
        "abs1": abs1, "abs2": abs2, "asg1": asg1, "asg2": asg2,
    })
    return ctx


def test_late_self_cancel_drops_score_and_auto_suspends(api):
    """PRD 3.5: "A substitute's self-cancel of an accepted assignment also
    writes a reliability event: `SUB_CANCEL_LATE` (−15) when the cancellation
    lands before the absence's first day with strictly less than the
    district's short-notice lead remaining, otherwise `SUB_CANCEL_EARLY`
    (−5); either append triggers the suspension evaluation of §2.10."
    PRD 2.10: "An `ACTIVE` substitute is automatically suspended when — and
    only when — their trailing score is strictly below the district's
    `suspension_score_threshold` (60 by default) and their
    `completions_trailing` is at least the district's
    `suspension_min_completions` (5 by default)."

    Design: Difficulty/transitive_cascade/self_cancel_score_suspension_cross_school_cascade
    """
    ctx = _suspension_cascade_ctx()
    cancelled = cancel_assignment_ok(
        ctx["asg1"]["id"], make_substitute_headers(ctx["sub_a"]["id"])
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "SUB_CANCEL"

    sub_a = get_substitute(ctx["sub_a"]["id"])
    assert sub_a["reliability_trailing_score"] == 55, "70 - 15 for the late cancel"
    assert sub_a["status"] == "SUSPENDED", (
        "55 < 60 with completions_trailing 0 >= suspension_min_completions 0"
    )


def test_suspension_cascade_cancels_cross_school_and_reoffers(api, district_admin_headers):
    """PRD 3.2: "every `OFFERED` assignment of the substitute is cancelled
    with `cancel_reason` `SUSPENSION_CANCEL` and its absence, already
    `DISPATCHING`, simply re-runs the selector; every `ACCEPTED` assignment is
    cancelled the same way and its absence falls back from `ASSIGNED` to
    `DISPATCHING` and re-dispatches."
    PRD 3.2: "System cancellations carry no reliability penalty — the score
    drop that triggered the suspension is penalty enough."

    Design: Difficulty/transitive_cascade/self_cancel_score_suspension_cross_school_cascade
    """
    ctx = _suspension_cascade_ctx()
    cancel_assignment_ok(ctx["asg1"]["id"], make_substitute_headers(ctx["sub_a"]["id"]))

    asg2 = get_assignment(ctx["asg2"]["id"])
    assert asg2["status"] == "CANCELLED"
    assert asg2["cancel_reason"] == "SUSPENSION_CANCEL", (
        "the second cancellation is caused by the suspension, not the original cancel"
    )

    assert get_absence(ctx["abs1"]["id"])["fill_status"] == "DISPATCHING"
    assert get_absence(ctx["abs2"]["id"])["fill_status"] == "DISPATCHING"

    data, meta = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": ctx["abs2"]["id"], "status": "OFFERED"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["substitute_id"] == ctx["sub_b"]["id"]
    assert data[0]["offer_sequence"] == 2

    _, meta_abs1 = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": ctx["abs1"]["id"], "status": "OFFERED"},
        )
    )
    assert meta_abs1["total_count"] == 0, (
        "A is SUSPENDED and B is not MATH-qualified: no new offer on absence 1"
    )
