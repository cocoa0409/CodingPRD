"""Leave bidding: award cascade, closed-interval overlap, cancellation (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_employee,
    create_leave_bid_payload,
    get_employee,
    make_employee_headers,
    set_clock,
    setup_board_with_employees,
    setup_employee_on_board,
    setup_submitted_leave_bid,
    slot_for_employee,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]


def test_award_moves_employee_on_leave(api):
    """PRD §3.5: "A successful award stamps `decided_at` and cascades three
    levels deep: the employee — who must be `AVAILABLE` — transitions from
    `AVAILABLE` to `ON_LEAVE`, every `ACTIVE` board slot flips to `VACATED`,
    and the board-rotation discipline renumbers the survivors."

    Design: Difficulty/transitive_cascade/leave_award_cascades_employee_board_positions
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    e1 = ctx["employees"][0]["id"]
    bid = setup_submitted_leave_bid(e1, start_date="2026-08-10T00:00:00Z",
                                    end_date="2026-08-12T00:00:00Z")

    resp = api_client.award_leave_bid(bid["id"], MANAGER)
    data = validate_success(resp)
    assert data["bid_status"] == "AWARDED"
    assert data["decided_at"] is not None

    emp = get_employee(e1)
    assert emp["availability_status"] == "ON_LEAVE", (
        "link 1: the award must drive the employee AVAILABLE -> ON_LEAVE"
    )


def test_award_vacates_slot_and_renumbers_survivors(api):
    """PRD §3.5: "A successful award stamps `decided_at` and cascades three
    levels deep: the employee — who must be `AVAILABLE` — transitions from
    `AVAILABLE` to `ON_LEAVE`, every `ACTIVE` board slot flips to `VACATED`,
    and the board-rotation discipline renumbers the survivors."
    PRD §3.1: "A vacate — on leave award or suspension — flips the slot to
    `VACATED` and releases its position entirely."

    Design: Difficulty/transitive_cascade/leave_award_cascades_employee_board_positions
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    board_id = ctx["board"]["id"]
    e1, e2 = (e["id"] for e in ctx["employees"])
    bid = setup_submitted_leave_bid(e1)

    resp = api_client.award_leave_bid(bid["id"], MANAGER)
    validate_success(resp)

    assert slot_for_employee(board_id, e1)["slot_status"] == "VACATED", (
        "link 2: the awardee's ACTIVE slot must flip to VACATED"
    )
    survivor = slot_for_employee(board_id, e2)
    assert survivor["slot_status"] == "ACTIVE"
    assert survivor["standing_position"] == 1, (
        f"link 3: the survivor must renumber from 2 to 1, got {survivor['standing_position']}"
    )


def test_leave_bid_closed_interval_shared_boundary_conflicts(api):
    """PRD §3.5: "First, no other `AWARDED` bid for the same employee may
    overlap the requested window, with closed-interval semantics — a shared
    boundary day is a conflict."
    PRD §3.5: "Either violation is rejected with `ERR_LEAVE_CONFLICT`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/leave_bid_closed_interval_shared_boundary_conflicts
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]
    bid1 = setup_submitted_leave_bid(emp_id, start_date="2026-08-10T00:00:00Z",
                                     end_date="2026-08-12T00:00:00Z")
    resp = api_client.award_leave_bid(bid1["id"], MANAGER)
    validate_success(resp)
    resp = api_client.return_from_leave(emp_id, make_employee_headers(emp_id))
    validate_success(resp)

    # Shares the boundary day 2026-08-12 with the AWARDED 08-10..08-12 leave.
    bid2 = setup_submitted_leave_bid(emp_id, leave_type="PERSONAL_DAY",
                                     start_date="2026-08-12T00:00:00Z",
                                     end_date="2026-08-14T00:00:00Z")
    resp = api_client.award_leave_bid(bid2["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_LEAVE_CONFLICT)


def test_leave_bid_adjacent_non_overlapping_award_succeeds(api):
    """PRD §3.5: "Both dates are UTC midnights and the interval is closed — the
    end day is itself part of the leave."
    PRD §3.5: "First, no other `AWARDED` bid for the same employee may overlap
    the requested window, with closed-interval semantics — a shared boundary day
    is a conflict."

    Design: Difficulty/resource_temporal_overlap/leave_bid_closed_interval_shared_boundary_conflicts
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]
    bid1 = setup_submitted_leave_bid(emp_id, start_date="2026-08-10T00:00:00Z",
                                     end_date="2026-08-12T00:00:00Z")
    api_client.award_leave_bid(bid1["id"], MANAGER)
    api_client.return_from_leave(emp_id, make_employee_headers(emp_id))

    # Starts the day AFTER the awarded window ends: no shared day, no conflict.
    bid2 = setup_submitted_leave_bid(emp_id, leave_type="PERSONAL_DAY",
                                     start_date="2026-08-13T00:00:00Z",
                                     end_date="2026-08-14T00:00:00Z")
    resp = api_client.award_leave_bid(bid2["id"], MANAGER)
    data = validate_success(resp)
    assert data["bid_status"] == "AWARDED"


def test_leave_bid_cancel_submitted_is_terminal_noop_free(api):
    """PRD §3.5: "Cancelling a still-`SUBMITTED` bid moves it to `CANCELLED`
    with no side effects."

    Design: Corner/state_machines/leave_bid_cancel_submitted_is_terminal_noop_free
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]
    bid = setup_submitted_leave_bid(emp_id, leave_type="PERSONAL_DAY",
                                    start_date="2026-08-20T00:00:00Z",
                                    end_date="2026-08-20T00:00:00Z")

    resp = api_client.cancel_leave_bid(bid["id"], make_employee_headers(emp_id))
    data = validate_success(resp)
    assert data["bid_status"] == "CANCELLED"

    emp = get_employee(emp_id)
    assert emp["availability_status"] == "AVAILABLE", (
        "cancelling a never-awarded bid must not touch availability"
    )
    slot = slot_for_employee(ctx["board"]["id"], emp_id)
    assert slot["slot_status"] == "ACTIVE"
    assert slot["standing_position"] == 1


def test_inverted_leave_window_rejected_temporal(api):
    """PRD §3.5: "Submission validates the temporal window: `start_date` must
    fall on or before `end_date` and must not be in the past, else
    `ERR_TEMPORAL_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_leave_bid_and_pay_create
    """
    set_clock()
    emp = create_employee()
    payload = create_leave_bid_payload(
        emp["id"], leave_type="PERSONAL_DAY",
        start_date="2026-08-20T00:00:00Z", end_date="2026-08-18T00:00:00Z",
    )
    resp = api_client.create_leave_bid(payload, make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)
