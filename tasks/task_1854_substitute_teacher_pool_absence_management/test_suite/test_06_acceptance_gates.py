"""Offer-creation and acceptance gates: budget sufficiency, qualification and
do-not-return screens at manual offer, clearance entity state at accept, and
the substitute's day-overlap rule with adjacency permitted."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    basic_world,
    create_mark_ok,
    get_absence,
    get_assignment,
    get_school,
    get_substitute,
    make_coordinator_headers,
    make_staff,
    make_substitute_headers,
    offer_assignment,
    onboard_substitute,
    report_absence,
    set_logical_clock,
    validate_error,
    validate_paginated,
)


def test_budget_insufficient_blocks_accept(api):
    """PRD 3.4: "and finally the school's `coverage_budget_available_cents`
    must cover the `provisional_pay_cents`
    (`ERR_COVERAGE_BUDGET_INSUFFICIENT`)."
    PRD 2.8: "The school's available coverage budget must cover the
    provisional pay of the assignment being accepted, else
    `ERR_COVERAGE_BUDGET_INSUFFICIENT` (402). This check is deliberately last:
    a budget shortfall surfaces only once every other rule has passed."

    Design: Corner/validations/budget_insufficient_blocks_accept
    """
    ctx = basic_world(budget=1)
    ctx["sub"] = onboard_substitute()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    offer = offer_assignment(absence["id"], ctx["sub"]["id"], coord_headers)
    assert offer["status"] == "OFFERED", "offer creation does not check the budget"

    res = api.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_substitute_headers(ctx["sub"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_COVERAGE_BUDGET_INSUFFICIENT, expected_status=402)

    assert get_assignment(offer["id"])["status"] == "OFFERED", (
        "the failed accept leaves the offer live"
    )
    assert get_school(ctx["school"]["id"])["coverage_budget_committed_cents"] == 0, (
        "no partial commit"
    )


def test_qualification_mismatch_and_dnr_block_offer_creation(api):
    """PRD 3.4: "A manual offer runs the identical eligibility filter as the
    selector — a coordinator cannot hand a job to a suspended, unqualified,
    uncleared, barred, double-booked, or already-asked substitute"
    PRD 2.8: "No `ACTIVE` `DO_NOT_RETURN` mark for the school and substitute,
    else `ERR_SUBSTITUTE_DO_NOT_RETURN` (409). This screen guards manual offer
    creation, self-claim, and offer acceptance."
    PRD 2.8: "The substitute holds the qualification the absence names, else
    `ERR_QUALIFICATION_MISMATCH` (409), guarding manual offers, self-claim,
    and acceptance."

    Design: Corner/validations/qualification_mismatch_and_dnr_block_offer_creation
    """
    ctx = basic_world()
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    sub_a = onboard_substitute(
        full_name="Sub A", rate_cents=20000, qualifications=(("SCIENCE", "HIGH"),)
    )
    sub_b = onboard_substitute(full_name="Sub B", rate_cents=18000)
    create_mark_ok(
        ctx["school"]["id"], sub_b["id"], "DO_NOT_RETURN",
        coord_headers, reason="classroom control",
    )
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")

    res = api.create_assignment(
        {"absence_id": absence["id"], "substitute_id": sub_a["id"]}, coord_headers
    )
    validate_error(res, ApiErrorId.ERR_QUALIFICATION_MISMATCH, expected_status=409)

    res = api.create_assignment(
        {"absence_id": absence["id"], "substitute_id": sub_b["id"]}, coord_headers
    )
    validate_error(res, ApiErrorId.ERR_SUBSTITUTE_DO_NOT_RETURN, expected_status=409)


def _expired_clearance_offer_ctx():
    """Sub A ACTIVE with BACKGROUND_CHECK expiring 2026-08-05 (verified while
    valid); 7-day offer window; absence Tue 2026-08-04..Wed 2026-08-05; manual
    offer created at 2026-08-03T09:00:00Z; clock then advanced past the
    clearance expiry while the offer is still live."""
    ctx = basic_world(
        district_config={"offer_response_window_minutes": 10080},
        clock="2026-07-29T00:00:00Z",
    )
    ctx["sub"] = onboard_substitute(background_expires_on="2026-08-05")
    ctx["absence"] = report_absence(
        ctx["teacher"], start_date="2026-08-04", end_date="2026-08-05"
    )
    set_logical_clock("2026-08-03T09:00:00Z")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    ctx["offer"] = offer_assignment(ctx["absence"]["id"], ctx["sub"]["id"], coord_headers)
    set_logical_clock("2026-08-06T00:00:00Z")
    return ctx


def test_accept_gated_by_clearance_entity_state(api):
    """PRD 2.8: "Required clearances `VERIFIED` and valid through the relevant
    date, else `ERR_CLEARANCE_INVALID` (409). This guards manual offers,
    self-claim, acceptance, substitute activation, and clearance verification
    itself."
    PRD 3.4: "both required clearances valid through the absence's `end_date`
    (`ERR_CLEARANCE_INVALID`)"

    Design: Difficulty/cross_entity_state_dependency/accept_gated_by_clearance_entity_state
    """
    ctx = _expired_clearance_offer_ctx()
    res = api.respond_assignment(
        ctx["offer"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLEARANCE_INVALID, expected_status=409)
    assert get_assignment(ctx["offer"]["id"])["status"] == "OFFERED", (
        "the failed accept does not consume the offer"
    )


def test_accept_clearance_flip_does_not_suspend_at_clock_jump(api, district_admin_headers):
    """PRD 3.2: "Consequences depend on where the expiry is detected: when
    detection happens at a dispatch batch or at activation, the clearance is a
    required one, and the substitute is `ACTIVE`, the substitute is suspended
    with the full cascade below; detection at any other validation flips the
    clearance's status only."
    PRD 3.2: "The flip is applied eagerly at dispatch batches, at substitute
    activation, and at any validation that reads the clearance, and lazily
    when a substitute's clearances are listed."

    Design: Difficulty/cross_entity_state_dependency/accept_gated_by_clearance_entity_state
    """
    ctx = _expired_clearance_offer_ctx()
    data, _ = validate_paginated(
        api.list_clearances(ctx["sub"]["id"], district_admin_headers)
    )
    by_type = {row["clearance_type"]: row for row in data}
    assert by_type["BACKGROUND_CHECK"]["status"] == "EXPIRED", (
        "the background check flipped once the clock passed 2026-08-05"
    )
    assert by_type["TEACHING_CREDENTIAL"]["status"] == "VERIFIED"
    assert get_substitute(ctx["sub"]["id"])["status"] == "ACTIVE", (
        "detection outside a batch or activation flips the clearance only"
    )


def _three_absence_overlap_ctx():
    """Sub X ACTIVE MATH/HIGH; offers on absence A (Mon 2026-08-03..Wed
    2026-08-05), absence B (Tue 2026-08-04..Thu 2026-08-06), and absence C
    (Thu 2026-08-06..Fri 2026-08-07) all exist for X before X accepts A —
    offers B and C are created while X holds only OFFERED assignments, so
    the double-booking screen does not fire at offer time; the overlap rule
    is then exercised at acceptance."""
    ctx = basic_world()
    teacher2 = make_staff(
        ctx["school"]["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
    )
    teacher3 = make_staff(
        ctx["school"]["id"], full_name="Teach Three", subject="MATH", grade_band="HIGH"
    )
    ctx["sub"] = onboard_substitute(full_name="Sub X", rate_cents=20000)
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    abs_a = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-05")
    abs_b = report_absence(teacher2, start_date="2026-08-04", end_date="2026-08-06")
    abs_c = report_absence(teacher3, start_date="2026-08-06", end_date="2026-08-07")

    offer_a = offer_assignment(abs_a["id"], ctx["sub"]["id"], coord_headers)
    offer_b = offer_assignment(abs_b["id"], ctx["sub"]["id"], coord_headers)
    offer_c = offer_assignment(abs_c["id"], ctx["sub"]["id"], coord_headers)
    accept_offer(offer_a["id"], ctx["sub"]["id"])
    ctx["abs_a"], ctx["abs_b"], ctx["abs_c"] = abs_a, abs_b, abs_c
    ctx["offer_b"], ctx["offer_c"] = offer_b, offer_c
    return ctx


def test_assignment_day_overlap_rejected_offer_stays_live(api):
    """PRD 3.4: "no overlap with the substitute's other `ACCEPTED`, `WORKED`,
    or `VERIFIED` assignments, adjacent ranges permitted
    (`ERR_ASSIGNMENT_DATE_OVERLAP`)"
    PRD 2.8: "One substitute may not hold two overlapping committed
    assignments, else `ERR_ASSIGNMENT_DATE_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/substitute_assignment_day_overlap_adjacency_allowed
    """
    ctx = _three_absence_overlap_ctx()
    res = api.respond_assignment(
        ctx["offer_b"]["id"], {"decision": "ACCEPT"},
        make_substitute_headers(ctx["sub"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_DATE_OVERLAP, expected_status=409)
    assert get_assignment(ctx["offer_b"]["id"])["status"] == "OFFERED", (
        "ranges 08-03..08-05 and 08-04..08-06 share 08-04 and 08-05; the "
        "rejection leaves the offer live"
    )


def test_assignment_day_overlap_adjacency_accepted(api):
    """PRD 3.4: "no overlap with the substitute's other `ACCEPTED`, `WORKED`,
    or `VERIFIED` assignments, adjacent ranges permitted
    (`ERR_ASSIGNMENT_DATE_OVERLAP`)"
    PRD 3.4: "A successful accept moves the offer to `ACCEPTED`, the absence
    from `DISPATCHING` to `ASSIGNED`, cancels every other `OFFERED` assignment
    on that absence with `cancel_reason` `ABSENCE_CANCEL` (no penalty — they
    simply lost the race), and adds the provisional pay into the school's
    committed budget."

    Design: Difficulty/resource_temporal_overlap/substitute_assignment_day_overlap_adjacency_allowed
    """
    ctx = _three_absence_overlap_ctx()
    accepted = accept_offer(ctx["offer_c"]["id"], ctx["sub"]["id"])
    assert accepted["status"] == "ACCEPTED", (
        "08-06..08-07 is adjacent to 08-03..08-05 with zero shared days"
    )
    assert get_absence(ctx["abs_c"]["id"])["fill_status"] == "ASSIGNED"
