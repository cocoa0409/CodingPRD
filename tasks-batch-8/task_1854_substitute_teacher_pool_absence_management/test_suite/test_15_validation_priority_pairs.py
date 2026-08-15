"""Validation-pipeline priority pairs: an expired offer's state error beats a
simultaneously expired clearance, and the assignment day-overlap rule beats
the deliberately-last budget check."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    basic_world,
    cancel_assignment_ok,
    get_assignment,
    get_school,
    make_coordinator_headers,
    make_district_admin_headers,
    make_school,
    make_staff,
    make_substitute_headers,
    offer_assignment,
    onboard_substitute,
    report_absence,
    set_logical_clock,
    validate_error,
    validate_paginated,
)


def _expired_offer_and_clearance_ctx():
    """Default 120-minute offer window; sub A's BACKGROUND_CHECK expires
    2026-08-05; absence Tue 2026-08-04..Wed 2026-08-05; manual offer created
    at 2026-08-03T09:00:00Z (expires 11:00); clock advanced to
    2026-08-21T00:00:00Z so the offer is long expired AND the background check
    has lapsed."""
    ctx = basic_world(clock=None)
    ctx["sub"] = onboard_substitute(background_expires_on="2026-08-05")
    ctx["absence"] = report_absence(
        ctx["teacher"], start_date="2026-08-04", end_date="2026-08-05"
    )
    set_logical_clock("2026-08-03T09:00:00Z")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    ctx["offer"] = offer_assignment(ctx["absence"]["id"], ctx["sub"]["id"], coord_headers)
    set_logical_clock("2026-08-21T00:00:00Z")
    return ctx


def test_expired_offer_state_beats_clearance_safety(api):
    """PRD 3.4: "Acceptance is gated in pipeline order: the offer must still
    be `OFFERED` — and if the clock has reached `offer_expires_at`, the offer
    auto-flips to `EXPIRED` first, so the late answer fails with
    `ERR_ASSIGNMENT_INVALID_STATE`"
    PRD 2.8: "Every request is evaluated against a fixed validation pipeline,
    and an earlier failure masks every later one — the pipeline does not
    collect errors, it stops at the first."

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_state_beats_clearance_safety
    """
    ctx = _expired_offer_and_clearance_ctx()
    res = api.respond_assignment(
        ctx["offer"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE, expected_status=409)
    assert res.json()["data"]["error_id"] != "ERR_CLEARANCE_INVALID"

    offer = get_assignment(ctx["offer"]["id"])
    assert offer["status"] == "EXPIRED", (
        "the respond attempt applied the offer's lazy expiry"
    )


def test_expired_offer_clearance_expiry_visible_but_not_reported(api):
    """PRD 3.2: "The flip is applied eagerly at dispatch batches, at
    substitute activation, and at any validation that reads the clearance, and
    lazily when a substitute's clearances are listed."
    PRD 3.4: "and if the clock has reached `offer_expires_at`, the offer
    auto-flips to `EXPIRED` first, so the late answer fails with
    `ERR_ASSIGNMENT_INVALID_STATE`"

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_state_beats_clearance_safety
    """
    ctx = _expired_offer_and_clearance_ctx()
    res = api.respond_assignment(
        ctx["offer"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE, expected_status=409)

    data, _ = validate_paginated(
        api.list_clearances(ctx["sub"]["id"], make_district_admin_headers())
    )
    by_type = {row["clearance_type"]: row for row in data}
    assert by_type["BACKGROUND_CHECK"]["status"] == "EXPIRED", (
        "the background check is also expired, yet the state-layer error won"
    )


def _overlap_vs_budget_ctx():
    """School S1 with 1 cent of budget, school S2 with 1000000; sub X
    qualified MATH/HIGH and SCIENCE/HIGH; absence1 at S1 Mon
    2026-08-03..Wed 2026-08-05 offered to X; absence2 at S2 Tue
    2026-08-04..Thu 2026-08-06 offered to X and ACCEPTED first."""
    ctx = basic_world(budget=1)
    school2 = make_school(ctx["district"]["id"], name="S2", budget=1_000_000)
    teacher2 = make_staff(
        school2["id"], full_name="Teach Two", subject="SCIENCE", grade_band="HIGH"
    )
    sub_x = onboard_substitute(
        full_name="Sub X", rate_cents=20000,
        qualifications=(("MATH", "HIGH"), ("SCIENCE", "HIGH")),
    )
    admin = make_district_admin_headers()

    abs1 = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-05")
    abs2 = report_absence(
        teacher2, start_date="2026-08-04", end_date="2026-08-06",
        required_subject="SCIENCE",
    )
    offer1 = offer_assignment(abs1["id"], sub_x["id"], admin)
    offer2 = offer_assignment(abs2["id"], sub_x["id"], admin)
    accept_offer(offer2["id"], sub_x["id"])
    ctx.update({
        "school2": school2, "sub_x": sub_x,
        "abs1": abs1, "abs2": abs2, "offer1": offer1, "offer2": offer2,
    })
    return ctx


def test_assignment_overlap_temporal_beats_budget_fiscal(api):
    """PRD 2.8: "One substitute may not hold two overlapping committed
    assignments, else `ERR_ASSIGNMENT_DATE_OVERLAP` (409)."
    PRD 2.8: "The school's available coverage budget must cover the
    provisional pay of the assignment being accepted, else
    `ERR_COVERAGE_BUDGET_INSUFFICIENT` (402). This check is deliberately last:
    a budget shortfall surfaces only once every other rule has passed."
    PRD 2.8: "Every request is evaluated against a fixed validation pipeline,
    and an earlier failure masks every later one — the pipeline does not
    collect errors, it stops at the first."

    Design: Difficulty/priority_pair_validation_conflict/assignment_overlap_temporal_beats_budget_fiscal
    """
    ctx = _overlap_vs_budget_ctx()
    res = api.respond_assignment(
        ctx["offer1"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub_x"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_DATE_OVERLAP, expected_status=409)
    assert res.json()["data"]["error_id"] != "ERR_COVERAGE_BUDGET_INSUFFICIENT", (
        "the temporal layer fires even though S1's 1-cent budget also fails"
    )
    assert get_assignment(ctx["offer1"]["id"])["status"] == "OFFERED", (
        "the failed accept leaves the offer live"
    )


def test_overlap_cleared_then_budget_error_surfaces(api):
    """PRD 2.8: "The school's available coverage budget must cover the
    provisional pay of the assignment being accepted, else
    `ERR_COVERAGE_BUDGET_INSUFFICIENT` (402). This check is deliberately last:
    a budget shortfall surfaces only once every other rule has passed."
    PRD 3.5: "Cancelling an `ACCEPTED` one releases the full
    `provisional_pay_cents` from the school's committed budget, reopens the
    absence from `ASSIGNED` back to `DISPATCHING`, and re-runs the selector"

    Design: Difficulty/priority_pair_validation_conflict/assignment_overlap_temporal_beats_budget_fiscal
    """
    ctx = _overlap_vs_budget_ctx()
    # Remove the temporal violation, leaving only the broke school.
    cancel_assignment_ok(ctx["offer2"]["id"], make_substitute_headers(ctx["sub_x"]["id"]))

    res = api.respond_assignment(
        ctx["offer1"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub_x"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_COVERAGE_BUDGET_INSUFFICIENT, expected_status=402)
    assert get_school(ctx["school"]["id"])["coverage_budget_committed_cents"] == 0
