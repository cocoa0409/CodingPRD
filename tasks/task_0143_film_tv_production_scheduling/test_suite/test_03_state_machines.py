"""State-machine tests: parallel assignment axes, cyclic call sheet & dailies
loops, permit branching, and invalid-transition lockdowns."""
from test_helpers import validate_success, validate_error, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import LP, AD, PC, PS


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/assignment_parallel_attendance_and_payment
# --------------------------------------------------------------------------- #
def test_attendance_advances_while_payment_stays_unpaid(api):
    """PRD 3.4: "An assignment carries two independent state dimensions that are
    advanced by different actors. The attendance dimension runs SCHEDULED →
    CHECKED_IN → WRAPPED, with SCHEDULED → NO_SHOW as the alternate terminal path;
    the payment dimension runs UNPAID → APPROVED → PAID". PRD 3.4: "Checking a
    person in moves attendance from SCHEDULED to CHECKED_IN".

    After check-in and check-out, attendance advances but payment_status is still
    UNPAID.

    Design: Difficulty/non_linear_state_machine/assignment_parallel_attendance_and_payment
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA",
        call_time="2026-07-10T06:00:00.000Z", shoot_date="2026-07-10")
    checked_in = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert checked_in["attendance_status"] == "CHECKED_IN"
    assert checked_in["payment_status"] == "UNPAID"

    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-07-10T18:00:00.000Z", "meal_breaks_taken": 1}, AD))
    assert wrapped["attendance_status"] == "WRAPPED"
    assert wrapped["payment_status"] == "UNPAID"


def test_payment_axis_advances_independently_via_payroll(api):
    """PRD 3.5: "the PayrollCoordinator approves a wrapped assignment for payment,
    moving payment_status from UNPAID to APPROVED; this is permitted only while
    payment_status is UNPAID and the assignment's attendance_status is WRAPPED."

    After approve-pay the attendance axis stays WRAPPED while payment moves to
    APPROVED.

    Design: Difficulty/non_linear_state_machine/assignment_parallel_attendance_and_payment
    """
    ctx = fixtures.setup_wrapped_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA",
        call_time="2026-07-10T06:00:00.000Z", shoot_date="2026-07-10",
        wrap_time="2026-07-10T18:00:00.000Z", meal_breaks_taken=1)
    approved = validate_success(api.approve_pay_assignment(ctx["assignment"]["id"], PC))
    assert approved["attendance_status"] == "WRAPPED"
    assert approved["payment_status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/callsheet_publish_revise_cycle
# --------------------------------------------------------------------------- #
def _published_call_sheet(api):
    """ACTIVE production, day with one assignment, call sheet PUBLISHED."""
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-07-12T07:00:00.000Z", shoot_date="2026-07-12")
    cs = fixtures.create_call_sheet(ctx["day"]["id"], general_call_time="2026-07-12T07:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    return cs


def test_first_revise_sets_revised_and_revision_number_one(api):
    """PRD 3.6: "A PUBLISHED sheet can be revised by the FirstAD while the parent
    day is in CALLED or IN_PROGRESS; revision moves the sheet from PUBLISHED to
    REVISED, increases its revision_number by 1, and increments its version."

    Design: Difficulty/non_linear_state_machine/callsheet_publish_revise_cycle
    """
    cs = _published_call_sheet(api)
    revised = validate_success(api.revise_call_sheet(cs["id"], AD))
    assert revised["status"] == "REVISED"
    assert revised["revision_number"] == 1, \
        f"expected revision_number 1, got {revised['revision_number']}"


def test_revise_republish_loop_accumulates_revision_number(api):
    """PRD 3.6: "A REVISED sheet is then re-published back to PUBLISHED ... This
    revise-then-republish loop may repeat any number of times."
    PRD 3.6: "revision moves the sheet from PUBLISHED to REVISED, increases its
    revision_number by 1".

    Two revise+republish cycles leave revision_number == 2 and status PUBLISHED.

    Design: Difficulty/non_linear_state_machine/callsheet_publish_revise_cycle
    """
    cs = _published_call_sheet(api)
    r1 = validate_success(api.revise_call_sheet(cs["id"], AD))
    assert r1["status"] == "REVISED" and r1["revision_number"] == 1
    p2 = validate_success(api.publish_call_sheet(cs["id"], AD))
    assert p2["status"] == "PUBLISHED"
    r2 = validate_success(api.revise_call_sheet(cs["id"], AD))
    assert r2["revision_number"] == 2, \
        f"expected revision_number 2, got {r2['revision_number']}"
    final = validate_success(api.publish_call_sheet(cs["id"], AD))
    assert final["status"] == "PUBLISHED"


# --------------------------------------------------------------------------- #
# Corner/state_machines/callsheet_publish_calls_the_day
# --------------------------------------------------------------------------- #
def test_first_publish_calls_the_day(api):
    """PRD 3.6: "A successful first publish moves the sheet from DRAFT to
    PUBLISHED, stamps published_at, increments the sheet's version, and
    transitions the parent day from PLANNED to CALLED."

    Design: Corner/state_machines/callsheet_publish_calls_the_day
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-14T06:00:00.000Z", shoot_date="2026-09-14")
    cs = fixtures.create_call_sheet(ctx["day"]["id"], general_call_time="2026-09-14T06:00:00.000Z")
    published = validate_success(api.publish_call_sheet(cs["id"], AD))
    assert published["status"] == "PUBLISHED"
    day = validate_success(api.get_shooting_day(ctx["day"]["id"], AD))
    assert day["status"] == "CALLED", f"expected day CALLED, got {day['status']}"


# --------------------------------------------------------------------------- #
# Corner/state_machines/dailies_cyclic_flag_then_resume_review
# --------------------------------------------------------------------------- #
def test_dailies_flag_then_resume_review_loop(api):
    """PRD 3.10: "Flagging moves the footage from IN_REVIEW to FLAGGED ... Flagged
    footage can be sent back into review — the same begin-review action takes
    FLAGGED back to IN_REVIEW — and this flag-then-review loop may repeat any
    number of times before the footage is finally approved."

    Design: Corner/state_machines/dailies_cyclic_flag_then_resume_review
    """
    ctx = fixtures.setup_dailies_in_review(reel_label="A002")
    flagged = validate_success(api.flag_dailies(
        ctx["dailies"]["id"], {"flagged_reason": "soft focus"}, PS))
    assert flagged["status"] == "FLAGGED"
    resumed = validate_success(api.start_review_dailies(ctx["dailies"]["id"], PS))
    assert resumed["status"] == "IN_REVIEW", \
        f"expected IN_REVIEW after resume, got {resumed['status']}"


# --------------------------------------------------------------------------- #
# Corner/state_machines/start_review_dailies_from_pending_invalid_when_day_planned
# --------------------------------------------------------------------------- #
def test_start_review_blocked_when_day_planned(api):
    """PRD 3.10: "Review begins by moving footage to IN_REVIEW, which is permitted
    from PENDING only while the parent day is WRAPPED or IN_PROGRESS".
    PRD 3.10: "any transition attempted from a non-matching source state is
    refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/start_review_dailies_from_pending_invalid_when_day_planned
    """
    ctx = fixtures.setup_dailies_pending_on_planned_day(reel_label="A001")
    resp = api.start_review_dailies(ctx["dailies"]["id"], PS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/cancel_already_wrapped_shooting_day_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_cancel_wrapped_day_returns_invalid_state(api):
    """PRD 3.3: "Cancelling a day is the system's most far-reaching schedule
    action and is available to the FirstAD while the day is either PLANNED or
    CALLED." PRD 3.3: "Both WRAPPED and CANCELLED are terminal day states."

    Cancel on a WRAPPED (terminal) day is refused with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_wrapped_shooting_day_returns_invalid_state
    """
    ctx = fixtures.setup_wrapped_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-05T06:00:00.000Z", shoot_date="2026-09-05",
        wrap_time="2026-09-05T18:00:00.000Z", meal_breaks_taken=2)
    # the day still has an open WRAPPED assignment? attendance WRAPPED is not open;
    # wrap the day, then attempt cancel.
    validate_success(api.wrap_shooting_day(ctx["day"]["id"], AD))
    resp = api.cancel_shooting_day(ctx["day"]["id"], AD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/permit_branch_to_denied_terminal
# --------------------------------------------------------------------------- #
def test_denied_permit_is_terminal(api):
    """PRD 3.7: "Alternatively a REQUESTED permit may be denied, moving it to
    DENIED." PRD 3.7: "EXPIRED, DENIED, and REVOKED are terminal permit states."
    PRD 3.7: "each is allowed only from its stated source state — otherwise
    ERR_INVALID_STATE."

    Approving a DENIED permit is refused with ERR_INVALID_STATE.

    Design: Corner/state_machines/permit_branch_to_denied_terminal
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    loc = fixtures.create_location(prod["id"], name="Loc", address="1 St")
    perm = fixtures.create_permit(loc["id"], "P-9",
                                  "2026-09-10T08:00:00.000Z", "2026-09-10T12:00:00.000Z")
    validate_success(api.deny_location_permit(perm["id"], LP))
    resp = api.approve_location_permit(perm["id"], LP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/shooting_day_wrap_blocked_by_open_assignment
# --------------------------------------------------------------------------- #
def test_wrap_blocked_by_checked_in_assignment(api):
    """PRD 3.3: "a wrap is allowed only when no assignment on that day is still
    open, meaning none has an attendance_status of SCHEDULED or CHECKED_IN; an
    attempt to wrap a day with open assignments is refused with
    ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP."

    Design: Corner/state_machines/shooting_day_wrap_blocked_by_open_assignment
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-12T06:00:00.000Z", shoot_date="2026-09-12")
    resp = api.wrap_shooting_day(ctx["day"]["id"], AD)
    validate_error(resp, ApiErrorId.ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP.value)
