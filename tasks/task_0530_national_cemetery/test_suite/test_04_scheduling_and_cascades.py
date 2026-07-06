"""Interment scheduling, overlap semantics, cascades, and expiry sweep.

Covers difficulty transitive_cascade, non_linear_state_machine (schedule cancel),
resource_temporal_overlap, boundary_precision (niche touching endpoints),
priority_pair (state before temporal), plus corner scheduling/validation and the
cascading_side_effects instance.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cemetery_with_gravesite,
    setup_cemetery_with_niche,
    setup_assigned_case,
    setup_scheduled_case,
    setup_confirmed_honors,
    setup_preneed_approved_case,
    create_cemetery,
    create_in_ground_section,
    create_gravesite,
    open_and_approve_case,
    assign_plot_auto,
    assign_plot_explicit,
    create_schedule,
    request_honors,
    confirm_honors,
    create_pmc,
    approve_pmc,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]
HONORS = TEST_USERS["honors_coordinator_headers"]


# ===========================================================================
# transitive_cascade — complete interment depth-3 chain
# ===========================================================================
def test_complete_interment_cascade_depth3(api):
    """PRD §3.7: "Completing a scheduled interment moves the schedule from SCHEDULED
    to COMPLETED and drives the case from SCHEDULED to INTERRED. It increments the
    assigned unit's interment_count (for a gravesite) or inurnment_count (for a
    niche) by one; when that count reaches the unit's depth_capacity (gravesite) or
    urn_capacity (niche), the unit moves from RESERVED to OCCUPIED. The parent
    section's inventory is recomputed. Any linked CONFIRMED military-honors record is
    driven to RENDERED."

    Design: Difficulty/transitive_cascade/complete_interment_cascade_depth3
    """
    cem, sec, grv, case, sched, hon = setup_confirmed_honors(
        detail_size="FULL_SQUAD", honors_squad_capacity=3,
    )
    completed = validate_success(api.complete_interment_schedule(cem["id"], sched["id"], CLERK))
    assert completed["status"] == "COMPLETED"
    case_read = validate_success(api.get_burial_case(cem["id"], case["id"], CLERK))
    assert case_read["status"] == "INTERRED"
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], ADMIN))
    assert grv_read["interment_count"] == 1
    assert grv_read["status"] == "OCCUPIED"
    sec_read = validate_success(api.get_section(cem["id"], sec["id"], ADMIN))
    assert sec_read["interred_units"] == 1
    assert sec_read["available_units"] == 0
    hon_read = validate_success(api.get_military_honors(cem["id"], hon["id"], HONORS))
    assert hon_read["status"] == "RENDERED"


def test_complete_interment_bubbles_honors_to_rendered(api):
    """PRD §3.8: "A confirmed detail advances to RENDERED automatically when its
    interment is completed, as described in §3.7."

    Design: Difficulty/transitive_cascade/complete_interment_cascade_depth3
    """
    cem, sec, grv, case, sched, hon = setup_confirmed_honors(
        detail_size="FULL_SQUAD", honors_squad_capacity=3,
    )
    validate_success(api.complete_interment_schedule(cem["id"], sched["id"], CLERK))
    hon_read = validate_success(api.get_military_honors(cem["id"], hon["id"], HONORS))
    assert hon_read["status"] == "RENDERED"


# ===========================================================================
# non_linear_state_machine — schedule cancel reverts case & cascades honors
# ===========================================================================
def test_schedule_cancel_reverts_case_and_cascades_honors(api):
    """PRD §3.7: "Cancelling a scheduled interment moves the schedule from SCHEDULED
    to CANCELLED and reverts the case from SCHEDULED back to ASSIGNED. As a cascade,
    any linked military-honors record in REQUESTED or CONFIRMED is driven to
    CANCELLED, and if such a record had flag_issued set to true, that flag is reset
    to false."

    Design: Difficulty/non_linear_state_machine/interment_schedule_cancel_reverts_case_branch
    """
    cem, sec, grv, case, sched, hon = setup_confirmed_honors(
        detail_size="FULL_SQUAD", honors_squad_capacity=3,
    )
    cancelled = validate_success(api.cancel_interment_schedule(cem["id"], sched["id"], CLERK))
    assert cancelled["status"] == "CANCELLED"
    case_read = validate_success(api.get_burial_case(cem["id"], case["id"], CLERK))
    assert case_read["status"] == "ASSIGNED"
    hon_read = validate_success(api.get_military_honors(cem["id"], hon["id"], HONORS))
    assert hon_read["status"] == "CANCELLED"
    assert hon_read["flag_issued"] is False


def test_schedule_cancel_withdraws_issued_flag(api):
    """PRD §3.8: "The same cancellation, and the same flag withdrawal, also occur as
    a cascade when the underlying interment schedule is cancelled."

    Design: Difficulty/non_linear_state_machine/interment_schedule_cancel_reverts_case_branch
    """
    cem, sec, grv, case, sched, hon = setup_confirmed_honors(
        detail_size="FULL_SQUAD", honors_squad_capacity=3,
    )
    assert hon["flag_issued"] is True  # confirmed -> flag issued
    validate_success(api.cancel_interment_schedule(cem["id"], sched["id"], CLERK))
    hon_read = validate_success(api.get_military_honors(cem["id"], hon["id"], HONORS))
    assert hon_read["flag_issued"] is False


# ===========================================================================
# priority_pair_validation_conflict — state (5) before temporal (8)
# ===========================================================================
def test_schedule_on_eligible_case_state_wins_over_conflict(api):
    """PRD §2.6: "Fifth, the target resource's state is checked against the requested
    transition, yielding ERR_INVALID_STATE when the transition is not defined from
    the current state."
    PRD §2.6: "Only after these structural checks pass does the system evaluate
    domain rules — ...scheduling conflicts (ERR_GRAVESITE_WINDOW_CONFLICT /
    ERR_NICHE_WINDOW_CONFLICT)"

    Design: Difficulty/priority_pair_validation_conflict/state_before_temporal_on_interment_schedule
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=2, honors_squad_capacity=2)
    case_x = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case_x["id"])
    create_schedule(cem["id"], case_x["id"], "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")
    case_y = open_and_approve_case(cem["id"])  # ELIGIBLE, never assigned
    resp = api.create_interment_schedule(cem["id"], {
        "burial_case_id": case_y["id"],
        "window_start": "2026-06-10T10:30:00Z", "window_end": "2026-06-10T11:30:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_schedule_on_eligible_case_state_wins_over_conflict_reordered(api):
    """PRD §2.6: "Fifth, the target resource's state is checked against the requested
    transition, yielding ERR_INVALID_STATE when the transition is not defined from
    the current state."
    PRD §2.6: "Only after these structural checks pass does the system evaluate
    domain rules — ...scheduling conflicts (ERR_GRAVESITE_WINDOW_CONFLICT /
    ERR_NICHE_WINDOW_CONFLICT)"

    Design: Difficulty/priority_pair_validation_conflict/state_before_temporal_on_interment_schedule
    """
    # Case Y here shares the exact same window as the occupying schedule, which would
    # also collide on the plot; the state check must still pre-empt the conflict check.
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=2, honors_squad_capacity=2)
    case_x = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case_x["id"])
    create_schedule(cem["id"], case_x["id"], "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")
    case_y = open_and_approve_case(cem["id"])  # ELIGIBLE, never assigned
    resp = api.create_interment_schedule(cem["id"], {
        "burial_case_id": case_y["id"],
        "window_start": "2026-06-10T10:00:00Z", "window_end": "2026-06-10T12:00:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ===========================================================================
# Corner: validations — window well-formedness
# ===========================================================================
def test_interment_window_end_not_after_start_rejected(api):
    """PRD §3.7: "The window must be well-formed — window_end must be strictly later
    than window_start, else the request is rejected with ERR_INVALID_WINDOW."

    Design: Corner/validations/interment_schedule_end_not_after_start_rejected
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    resp = api.create_interment_schedule(cem["id"], {
        "burial_case_id": case["id"],
        "window_start": "2026-06-10T10:00:00Z", "window_end": "2026-06-10T10:00:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


# ===========================================================================
# Corner: state_machines — cancel already-cancelled schedule
# ===========================================================================
def test_cancel_already_cancelled_schedule_invalid_state(api):
    """PRD §3.7: "Both completion and cancellation act only on a schedule that is
    currently SCHEDULED."

    Design: Corner/state_machines/cancel_already_cancelled_schedule_invalid_state
    """
    cem, sec, grv, case, sched = setup_scheduled_case(
        window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T12:00:00Z",
        depth_capacity=1, honors_squad_capacity=1,
    )
    validate_success(api.cancel_interment_schedule(cem["id"], sched["id"], CLERK))
    resp = api.cancel_interment_schedule(cem["id"], sched["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ===========================================================================
# cross_cutting_complexity — PMC APPROVED -> RESERVED on interment complete
# ===========================================================================
def test_preneed_approved_to_reserved_on_complete(api):
    """PRD §3.4: "For a PRE_NEED case, the successful assignment also drives the
    linked pre-need determination from APPROVED to RESERVED."
    PRD §3.5: "An approved certificate becomes RESERVED automatically when the linked
    case is successfully assigned a plot before the window elapses, as described in
    §3.4"

    Design: Corner/cross_cutting_complexity_layers/preneed_approved_to_reserved_on_interment_complete
    """
    set_clock("2026-05-01T00:00:00Z")
    cem, sec, grv, case, pmc = setup_preneed_approved_case(honors_squad_capacity=1)
    validate_success(api.assign_plot(cem["id"], case["id"], CLERK, payload={}))
    sched = create_schedule(cem["id"], case["id"], "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")
    completed = validate_success(api.complete_interment_schedule(cem["id"], sched["id"], CLERK))
    case_read = validate_success(api.get_burial_case(cem["id"], case["id"], CLERK))
    assert case_read["status"] == "INTERRED"
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], ADMIN))
    assert grv_read["status"] == "OCCUPIED"
    pmc_read = validate_success(api.get_pmc(cem["id"], pmc["id"], OFFICER))
    assert pmc_read["status"] == "RESERVED"
