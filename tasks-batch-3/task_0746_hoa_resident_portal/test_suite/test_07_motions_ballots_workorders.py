"""Motion window buffer, motion close preconditions, ballot uniqueness,
work-order parallel dimensions, and their invalid-transitions."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    api_client,
    setup_open_motion,
    setup_board_member,
    setup_work_order_completed,
    create_work_order,
    create_motion_payload,
    create_ballot_payload,
    set_clock,
    create_homeowner,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue A — resource_temporal_overlap / motion_window_24h_buffer_conflict
# ===========================================================================
def test_motion_window_24h_buffer_conflict(api):
    """PRD §3.7: "A newly created motion carries `status` `OPEN`, `yes_count`
    and `no_count` initialised to `0`, and is subject to the category-overlap
    rule: within any single category, no two `OPEN` motions may have voting
    windows within 24 hours of one another (that is, a new motion is rejected
    with `ERR_MOTION_WINDOW_CONFLICT` if any existing `OPEN` motion of the
    same category has its own voting window overlapping the interval that
    extends the new motion's voting window by 24 hours on each side)."

    Design: Difficulty/resource_temporal_overlap/motion_window_24h_buffer_conflict
    """
    board_member, _ = setup_open_motion(
        board_email="bmmot@ex.com",
        title="Budget A", category="BUDGET",
        voting_window_start="2026-04-01T00:00:00Z",
        voting_window_end="2026-04-05T00:00:00Z",
        eligible_voter_count=10, quorum_pct=50,
    )
    resp = api.create_motion(
        create_motion_payload(
            title="Budget B", description="Approve budget B",
            category="BUDGET",
            voting_window_start="2026-04-05T12:00:00Z",  # 12h after M1 end
            voting_window_end="2026-04-10T00:00:00Z",
            eligible_voter_count=10, quorum_pct=50,
        ),
        make_board_member_headers(board_member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MOTION_WINDOW_CONFLICT)


# ===========================================================================
# Queue A — non_linear_state_machine / work_order_parallel_dimensions
# ===========================================================================
def test_work_order_parallel_dimensions_evolve_independently(api):
    """PRD §3.8: "Work orders evolve along **two parallel dimensions** whose
    transitions are independent of one another once the invoice branch
    begins."
    PRD §3.8: "The manager assigns a vendor by supplying `assigned_vendor_id`
    (an opaque external identifier); this stamps the vendor and moves
    `work_status` to `ASSIGNED`. Starting an assigned order moves it to
    `IN_PROGRESS`"
    PRD §3.8: "The payment dimension, `payment_status`, begins at `UNBILLED`.
    The manager may transition it to `INVOICED` only while `work_status` is
    `IN_PROGRESS` or `COMPLETED`"

    Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions
    """
    wo = create_work_order(title="Fence repair", cost_estimate_cents=50000)
    resp = api.assign_work_order(
        wo["id"], {"assigned_vendor_id": "vendor-abc"}, _MANAGER
    )
    validate_success(resp)
    resp = api.start_work_order(wo["id"], _MANAGER)
    validate_success(resp)
    resp = api.invoice_work_order(wo["id"], _MANAGER)
    data = validate_success(resp)
    assert data["work_status"] == "IN_PROGRESS"
    assert data["payment_status"] == "INVOICED"


# ===========================================================================
# Queue B — state_machines / motion_close_open_before_end_window
# ===========================================================================
def test_motion_close_before_window_end_returns_invalid_state(api):
    """PRD §3.7: "A board member closes an `OPEN` motion once the logical
    clock has reached or passed `voting_window_end`; a close attempt before
    that instant is rejected as an invalid state transition."

    Design: Corner/state_machines/motion_close_open_before_end_window
    """
    board_member, motion = setup_open_motion(
        board_email="bmc@ex.com",
        title="T", category="POLICY",
        voting_window_start="2026-04-01T00:00:00Z",
        voting_window_end="2026-04-05T00:00:00Z",
        eligible_voter_count=10, quorum_pct=50,
    )
    set_clock("2026-04-03T00:00:00Z")
    resp = api.close_motion(
        motion["id"], make_board_member_headers(board_member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue B — state_machines / workorder_cancel_after_completed_returns_invalid_state
# ===========================================================================
def test_cancel_after_completed_returns_invalid_state(api):
    """PRD §3.8: "From either `NEW` or `ASSIGNED`, the manager may cancel the
    order — but only while the payment dimension is still `UNBILLED`; a
    cancel attempt with `payment_status` already `INVOICED` or `PAID` is
    rejected as an invalid state transition. Cancellation is terminal."

    Design: Corner/state_machines/workorder_cancel_after_completed_returns_invalid_state
    """
    wo = setup_work_order_completed(title="T", cost=10000)
    resp = api.cancel_work_order(wo["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue B — validations / ballot_duplicate_rejected
# ===========================================================================
def test_second_ballot_from_same_homeowner_rejected(api):
    """PRD §3.7: "Any second ballot from the same homeowner on the same
    motion is rejected with `ERR_BALLOT_DUPLICATE`."

    Design: Corner/validations/ballot_duplicate_rejected
    """
    board_member, motion = setup_open_motion(
        board_email="bmbd@ex.com",
        title="T", category="POLICY",
        voting_window_start="2026-04-01T00:00:00Z",
        voting_window_end="2026-04-05T00:00:00Z",
        eligible_voter_count=5, quorum_pct=50,
    )
    voter = create_homeowner("v@ex.com", "V")
    set_clock("2026-04-02T00:00:00Z")
    resp = api.cast_ballot(
        motion["id"],
        create_ballot_payload(voter["id"], choice="YES"),
        make_homeowner_headers(voter["id"]),
    )
    validate_success(resp, expected_status=201)
    resp = api.cast_ballot(
        motion["id"],
        create_ballot_payload(voter["id"], choice="NO"),
        make_homeowner_headers(voter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BALLOT_DUPLICATE)
