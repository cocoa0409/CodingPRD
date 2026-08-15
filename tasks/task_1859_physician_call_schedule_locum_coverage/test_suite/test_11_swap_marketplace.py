"""The swap marketplace: posting and claiming guards, the claim/decline cycle,
equity-band approval, cutoff boundary precision, execution side effects, and
fairness-point conservation."""
from test_helpers import (
    ApiErrorId,
    assign_staff,
    claim_swap,
    create_locum_physician,
    create_published_program,
    create_staff_physician,
    fairness_entry_for,
    get_fairness_report,
    get_slot_for_date,
    list_assignments,
    make_physician_headers,
    numeric_values,
    post_swap,
    serve_assignment,
    set_clock,
    setup_claimed_swap,
    setup_posted_swap,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CHIEF = TEST_USERS["chief_headers"]


# ─── Posting and claiming guards ─────────────────────────────────────

def test_self_swap_claim_rejected(api):
    """PRD §3.4: "The claimant must be a STAFF physician
    (`ERR_SWAP_CLAIMANT_INELIGIBLE`), ACTIVE (`ERR_PHYSICIAN_INACTIVE`), and
    someone other than the offerer (`ERR_SELF_SWAP`)".

    Design: Corner/validations/self_swap_claim_rejected
    """
    ctx = setup_posted_swap()
    resp = api.claim_swap(
        ctx["swap"]["id"], make_physician_headers(ctx["offerer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SELF_SWAP, 409)
    swap = validate_success(api.get_swap(ctx["swap"]["id"], ADMIN))
    assert swap["status"] == "POSTED"


def test_duplicate_active_swap_rejected(api):
    """PRD §3.4: "must not already be referenced by another swap in POSTED,
    CLAIMED, or APPROVED status (`ERR_DUPLICATE_ACTIVE_SWAP`)".

    Design: Corner/validations/duplicate_active_swap_rejected
    """
    ctx = setup_posted_swap()
    resp = api.create_swap(
        {"assignment_id": ctx["assignment"]["id"]},
        make_physician_headers(ctx["offerer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_SWAP, 409)
    swaps, _meta = validate_paginated(
        api.list_swaps(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
    )
    assert len(swaps) == 1
    assert swaps[0]["id"] == ctx["swap"]["id"]


def test_locum_claiming_swap_rejected(api):
    """PRD §3.4: "The claimant must be a STAFF physician
    (`ERR_SWAP_CLAIMANT_INELIGIBLE`)".

    Design: Corner/errors/locum_claiming_swap_rejected
    """
    ctx = setup_posted_swap()
    locum = create_locum_physician("Dr Locum")
    resp = api.claim_swap(ctx["swap"]["id"], make_physician_headers(locum["id"]))
    validate_error(resp, ApiErrorId.ERR_SWAP_CLAIMANT_INELIGIBLE, 409)
    swap = validate_success(api.get_swap(ctx["swap"]["id"], ADMIN))
    assert swap["status"] == "POSTED"


def test_approve_posted_swap_returns_not_claimed(api):
    """PRD §3.4: "Approval is the `ChiefOfStaff`'s equity review, moving CLAIMED
    → APPROVED (anything else is `ERR_SWAP_NOT_CLAIMED`)."

    Design: Corner/errors/approve_posted_swap_returns_not_claimed
    """
    ctx = setup_posted_swap()
    resp = api.approve_swap(ctx["swap"]["id"], CHIEF)
    validate_error(resp, ApiErrorId.ERR_SWAP_NOT_CLAIMED, 409)
    swap = validate_success(api.get_swap(ctx["swap"]["id"], ADMIN))
    assert swap["status"] == "POSTED"


# ─── Non-linear state machine: claim -> decline -> reclaim cycle ─────

def test_swap_claim_decline_reclaim_cycle(api):
    """PRD §3.4: "Decline is the sibling action, moving CLAIMED back to POSTED,
    clearing `claimant_physician_id` to null, and recording the optional
    `decline_reason`. A swap may cycle through claim and decline repeatedly
    before it is finally approved or withdrawn."

    Design: Difficulty/non_linear_state_machine/swap_request_claim_decline_reclaim_cycle
    """
    ctx = setup_claimed_swap()
    third = create_staff_physician("Dr Chen")

    resp = api.decline_swap(ctx["swap"]["id"], CHIEF, decline_reason="equity review")
    declined = validate_success(resp, 200)
    assert declined["status"] == "POSTED"
    assert declined["claimant_physician_id"] is None

    reclaimed = claim_swap(ctx["swap"]["id"], third["id"])
    assert reclaimed["status"] == "CLAIMED"
    assert reclaimed["claimant_physician_id"] == third["id"]


def test_swap_cycle_ends_in_execute_with_replacement_assignment(api):
    """PRD §3.4: "Execution moves the original assignment SCHEDULED → SWAPPED
    and creates the replacement CallAssignment for the claimant with `origin`
    SWAP, `source_swap_id` set to the swap, SCHEDULED status, and projected pay
    computed for the claimant. The slot remains ASSIGNED throughout."

    Design: Difficulty/non_linear_state_machine/swap_request_claim_decline_reclaim_cycle
    """
    ctx = setup_claimed_swap()
    third = create_staff_physician("Dr Chen")
    api.decline_swap(ctx["swap"]["id"], CHIEF, decline_reason="equity review")
    claim_swap(ctx["swap"]["id"], third["id"])
    validate_success(api.approve_swap(ctx["swap"]["id"], CHIEF))
    resp = api.execute_swap(ctx["swap"]["id"], ADMIN)
    executed = validate_success(resp, 200)
    assert executed["status"] == "EXECUTED"

    original = validate_success(api.get_assignment(ctx["assignment"]["id"], ADMIN))
    assert original["status"] == "SWAPPED"

    replacements, _meta = validate_paginated(
        api.list_assignments(ADMIN, params={"source_swap_id": ctx["swap"]["id"]})
    )
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["physician_id"] == third["id"]
    assert replacement["origin"] == "SWAP"
    assert replacement["source_swap_id"] == ctx["swap"]["id"]
    assert replacement["status"] == "SCHEDULED"

    slot = validate_success(api.get_slot(ctx["slot"]["id"], ADMIN))
    assert slot["status"] == "ASSIGNED", "the slot stays ASSIGNED throughout"


# ─── Cross-entity dependency: approve requires assignment SCHEDULED ──

def test_swap_approve_requires_assignment_still_scheduled(api):
    """PRD §3.4: "The referenced assignment must still be SCHEDULED
    (`ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`) and the program still PUBLISHED
    (`ERR_PROGRAM_NOT_PUBLISHED`)."

    The offered assignment is served after the claim; approval of the now-stale
    swap fails.

    Design: Difficulty/cross_entity_state_dependency/swap_approve_requires_assignment_still_scheduled
    """
    ctx = setup_claimed_swap()
    set_clock("2026-09-09T08:00:00Z")  # past the 2026-09-08 window end
    serve_assignment(ctx["assignment"]["id"])

    resp = api.approve_swap(ctx["swap"]["id"], CHIEF)
    validate_error(resp, ApiErrorId.ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED, 409)
    swap = validate_success(api.get_swap(ctx["swap"]["id"], ADMIN))
    assert swap["status"] == "CLAIMED"


def test_swap_approve_rejection_leaves_served_work_untouched(api):
    """PRD §3.4: "The referenced assignment must still be SCHEDULED
    (`ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`)" — the rejected approval has no side
    effects on the served assignment or its slot.

    Design: Difficulty/cross_entity_state_dependency/swap_approve_requires_assignment_still_scheduled
    """
    ctx = setup_claimed_swap()
    set_clock("2026-09-09T08:00:00Z")
    serve_assignment(ctx["assignment"]["id"])

    resp = api.approve_swap(ctx["swap"]["id"], CHIEF)
    validate_error(resp, ApiErrorId.ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED, 409)

    assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], ADMIN))
    assert assignment["status"] == "SERVED"
    slot = validate_success(api.get_slot(ctx["slot"]["id"], ADMIN))
    assert slot["status"] == "COVERED"


# ─── Priority pair: state beats temporal on claim ────────────────────

def test_swap_claim_state_beats_temporal_cutoff(api):
    """PRD §2.11: "When a request would fail several checks at once, the server
    reports the earliest failure in a fixed evaluation order rather than an
    arbitrary one: ... 6. State preconditions — ... 9. Temporal rules — ..."

    The swap is already CLAIMED (state violation) and the claim arrives inside
    the 48-hour cutoff (temporal violation); ERR_SWAP_NOT_POSTED must win.

    Design: Difficulty/priority_pair_validation_conflict/swap_claim_state_beats_temporal_cutoff
    """
    ctx = setup_claimed_swap(date="2026-09-10")
    # Cutoff for the 2026-09-10T07:00:00Z window start is 2026-09-08T07:00:00Z;
    # 2026-09-09T12:00:00Z is inside it.
    set_clock("2026-09-09T12:00:00Z")
    third = create_staff_physician("Dr Chen")
    resp = api.claim_swap(ctx["swap"]["id"], make_physician_headers(third["id"]))
    validate_error(resp, ApiErrorId.ERR_SWAP_NOT_POSTED, 409)


def test_swap_claim_rejection_leaves_claimed_swap_unchanged(api):
    """PRD §3.4: "Claiming moves a swap from POSTED to CLAIMED — any other phase
    is `ERR_SWAP_NOT_POSTED`." — a rejected claim mutates nothing.

    Design: Difficulty/priority_pair_validation_conflict/swap_claim_state_beats_temporal_cutoff
    """
    ctx = setup_claimed_swap(date="2026-09-10")
    set_clock("2026-09-09T12:00:00Z")
    third = create_staff_physician("Dr Chen")
    resp = api.claim_swap(ctx["swap"]["id"], make_physician_headers(third["id"]))
    validate_error(resp, ApiErrorId.ERR_SWAP_NOT_POSTED, 409)

    swap = validate_success(api.get_swap(ctx["swap"]["id"], ADMIN))
    assert swap["status"] == "CLAIMED"
    assert swap["claimant_physician_id"] == ctx["claimant"]["id"]


# ─── Swap cutoff boundary (equality allowed) ─────────────────────────

def _setup_cutoff_boundary():
    """PUBLISHED two-day program; offerer assigned to both days (adjacent
    half-open windows are allowed) with a swap posted for each."""
    program = create_published_program(
        name="Cards Cutoff Boundary",
        period_start="2026-09-10",
        period_end="2026-09-11",
    )
    offerer = create_staff_physician("Dr Alvarez")
    claimant = create_staff_physician("Dr Becker")
    slot1 = get_slot_for_date(program["id"], "2026-09-10")
    slot2 = get_slot_for_date(program["id"], "2026-09-11")
    a1 = assign_staff(slot1["id"], offerer["id"])
    a2 = assign_staff(slot2["id"], offerer["id"])
    sw1 = post_swap(a1["id"], offerer["id"])
    sw2 = post_swap(a2["id"], offerer["id"])
    return program, offerer, claimant, sw1, sw2


def test_swap_cutoff_exactly_48h_allowed(api):
    """PRD §3.4: "the slot's `window_start` must be at least `swap_cutoff_hours`
    (default 48 hours) in the future — a claim exactly at the cutoff is allowed,
    anything later is `ERR_SWAP_CUTOFF_VIOLATION`."

    The 2026-09-10 slot starts 2026-09-10T07:00:00Z; the claim lands at exactly
    2026-09-08T07:00:00Z, 48 hours earlier.

    Design: Difficulty/boundary_precision_check/swap_cutoff_exactly_48h_allowed_one_second_late_rejected
    """
    _program, _offerer, claimant, sw1, _sw2 = _setup_cutoff_boundary()
    set_clock("2026-09-08T07:00:00Z")
    resp = api.claim_swap(sw1["id"], make_physician_headers(claimant["id"]))
    claimed = validate_success(resp, 200)
    assert claimed["status"] == "CLAIMED"
    assert claimed["claimant_physician_id"] == claimant["id"]


def test_swap_cutoff_one_second_late_rejected(api):
    """PRD §3.4: "a claim exactly at the cutoff is allowed, anything later is
    `ERR_SWAP_CUTOFF_VIOLATION`."

    The 2026-09-11 slot's cutoff is 2026-09-09T07:00:00Z; the claim arrives one
    second later.

    Design: Difficulty/boundary_precision_check/swap_cutoff_exactly_48h_allowed_one_second_late_rejected
    """
    _program, _offerer, claimant, _sw1, sw2 = _setup_cutoff_boundary()
    set_clock("2026-09-09T07:00:01Z")
    resp = api.claim_swap(sw2["id"], make_physician_headers(claimant["id"]))
    validate_error(resp, ApiErrorId.ERR_SWAP_CUTOFF_VIOLATION, 409)
    swap = validate_success(api.get_swap(sw2["id"], ADMIN))
    assert swap["status"] == "POSTED"
    assert swap["claimant_physician_id"] is None


# ─── Equity band at approval ─────────────────────────────────────────

def _setup_equity_program(equity_band_points=None):
    """PUBLISHED program 2026-09-07..2026-09-12 with 2026-09-07 a HOLIDAY;
    A holds 09-07 (3.0 pts) and 09-08 (1.0); B holds 09-12 (2.0); B has claimed
    A's offered holiday assignment."""
    overrides = dict(
        name="Cards Equity",
        period_start="2026-09-07",
        period_end="2026-09-12",
        holiday_dates=["2026-09-07"],
        payroll_budget_cents=5_000_000,
        weekday_primary_required=1,
        weekend_primary_required=1,
        holiday_primary_required=1,
    )
    if equity_band_points is not None:
        overrides["equity_band_points"] = equity_band_points
    program = create_published_program(**overrides)
    pa = create_staff_physician("Dr Alvarez")
    pb = create_staff_physician("Dr Becker")
    a_hol = assign_staff(get_slot_for_date(program["id"], "2026-09-07")["id"], pa["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-08")["id"], pa["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-12")["id"], pb["id"])
    swap = post_swap(a_hol["id"], pa["id"])
    claim_swap(swap["id"], pb["id"])
    return program, pa, pb, a_hol, swap


def test_swap_approve_equity_breach_rejected(api):
    """PRD §3.4: "The equity check then recomputes prospective points as they
    would stand after the swap ... and rejects the approval with
    `ERR_SWAP_EQUITY_BREACH` when the claimant's post-swap prospective total
    would be strictly greater than the post-swap population mean of prospective
    points plus the program's `equity_band_points`; landing exactly on that
    boundary is permitted."

    With equity_band_points 1.0: B would reach 2.0 + 3.0 = 5.0 > post-swap mean
    3.0 + 1.0.

    Design: Corner/validations/swap_approve_equity_breach_rejected
    """
    _program, _pa, pb, _a_hol, swap = _setup_equity_program(equity_band_points=1.0)
    resp = api.approve_swap(swap["id"], CHIEF)
    validate_error(resp, ApiErrorId.ERR_SWAP_EQUITY_BREACH, 409)
    swap_after = validate_success(api.get_swap(swap["id"], ADMIN))
    assert swap_after["status"] == "CLAIMED"
    assert swap_after["claimant_physician_id"] == pb["id"]


# ─── Compensating invariant: fairness conservation under execute ─────

def test_fairness_points_conserved_under_swap_execute(api):
    """PRD §2.8: "Prospective points sum the physician's assignments in
    SCHEDULED, ACTIVATED, or SERVED status. ... SWAPPED and CANCELLED
    assignments feed neither variant."
    PRD §3.4: "fairness-point ownership passes from offerer to claimant through
    the status-filtered sets".

    Total prospective points are 6.0 before the execute and 6.0 after — the
    SWAPPED original leaves the prospective set exactly as the SCHEDULED
    replacement enters it.

    Design: Difficulty/compensating_invariant/fairness_points_conserved_under_swap_execute
    """
    program, _pa, _pb, _a_hol, swap = _setup_equity_program()
    before = get_fairness_report(program["id"])
    assert before["total_prospective_points"] == 6.0

    validate_success(api.approve_swap(swap["id"], CHIEF))
    validate_success(api.execute_swap(swap["id"], ADMIN))

    after = get_fairness_report(program["id"])
    assert after["total_prospective_points"] == 6.0
    assert after["mean_prospective_points"] == 3.0
    assert after["population_size"] == 2


def test_fairness_points_transfer_between_offerer_and_claimant(api):
    """PRD §3.4: "fairness-point ownership passes from offerer to claimant
    through the status-filtered sets"; "Execution moves the original assignment
    SCHEDULED → SWAPPED and creates the replacement CallAssignment for the
    claimant with `origin` SWAP".

    The holiday slot's 3.0 points move from A (4.0 -> 1.0) to B (2.0 -> 5.0).

    Design: Difficulty/compensating_invariant/fairness_points_conserved_under_swap_execute
    """
    program, pa, pb, a_hol, swap = _setup_equity_program()
    validate_success(api.approve_swap(swap["id"], CHIEF))
    validate_success(api.execute_swap(swap["id"], ADMIN))

    report = get_fairness_report(program["id"])
    entry_a = fairness_entry_for(report, pa["id"])
    entry_b = fairness_entry_for(report, pb["id"])
    nums_a = numeric_values(entry_a)
    nums_b = numeric_values(entry_b)
    assert 1.0 in nums_a and 4.0 not in nums_a, (
        f"offerer relieved of the holiday 3.0 points: {entry_a!r}"
    )
    assert 5.0 in nums_b, f"claimant credited with the holiday slot: {entry_b!r}"

    original = validate_success(api.get_assignment(a_hol["id"], ADMIN))
    assert original["status"] == "SWAPPED"
    replacements, _meta = validate_paginated(
        api.list_assignments(ADMIN, params={"source_swap_id": swap["id"]})
    )
    assert len(replacements) == 1
    assert replacements[0]["physician_id"] == pb["id"]
    assert replacements[0]["origin"] == "SWAP"


# ─── Terminal lockdown on EXECUTED swaps ─────────────────────────────

def test_execute_executed_swap_rejected_terminal_lockdown(api):
    """PRD §3.4: "Execution, performed by a `SchedulerAdmin`, turns APPROVED
    into EXECUTED (`ERR_SWAP_NOT_APPROVED` otherwise)".

    Design: Corner/state_machines/execute_executed_swap_rejected_terminal_lockdown
    """
    ctx = setup_claimed_swap()
    validate_success(api.approve_swap(ctx["swap"]["id"], CHIEF))
    validate_success(api.execute_swap(ctx["swap"]["id"], ADMIN))

    resp = api.execute_swap(ctx["swap"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SWAP_NOT_APPROVED, 409)

    replacements, _meta = validate_paginated(
        api.list_assignments(ADMIN, params={"source_swap_id": ctx["swap"]["id"]})
    )
    assert len(replacements) == 1, "no double execution"
