"""Walk-in queue: FIFO position, the CALLED<->WAITING requeue cycle, recall limit,
queue-order (allow_skip) enforcement, no-show strikes, and member-blocking.

Covers difficulty queue A rules `non_linear_state_machine` (requeue cycle) and
`boundary_precision_check` (suspend boundary), plus corner queue B instances under
`calculations` (queue_position), `state_machines` (recall limit), `validations`
(queue order, member blocked), and `endpoints` (single no-show).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
import test_helpers as th

FRONT_DESK = TEST_USERS["front_desk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Difficulty A: non_linear_state_machine / queue_ticket_called_requeue_cycle
# ===========================================================================
def test_requeue_returns_ticket_to_waiting_and_bumps_called_count(api):
    """PRD §3.3: "Because `joined_at` is left unchanged, the guest keeps their original
    FIFO place; the requeue increments `called_count` by one and recomputes positions
    across the salon's waiting set."

    Design: Difficulty/non_linear_state_machine/queue_ticket_called_requeue_cycle
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    resp = api.requeue_queue_ticket(ticket["id"], FRONT_DESK)
    data = validate_success(resp)
    assert data["status"] == "WAITING"
    assert data["called_count"] == 1


def test_requeue_preserves_fifo_position(api):
    """PRD §3.3: "If a called guest steps away, the agent can put the ticket back with
    a requeue, moving it from `CALLED` to `WAITING`. Because `joined_at` is left
    unchanged, the guest keeps their original FIFO place."

    Design: Difficulty/non_linear_state_machine/queue_ticket_called_requeue_cycle
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    api.requeue_queue_ticket(ticket["id"], FRONT_DESK)
    reread = validate_success(api.get_queue_ticket(ticket["id"], FRONT_DESK))
    assert reread["status"] == "WAITING"
    assert reread["position"] == 1, f"sole waiting ticket should be position 1, got {reread['position']}"


# ===========================================================================
# Difficulty A: boundary_precision_check / suspend_at_exactly_two_strikes
# ===========================================================================
def test_second_strike_suspends_member(api):
    """PRD §3.7: "otherwise a member whose strike count is at least two is moved to
    `SUSPENDED`; below two strikes the member remains `ACTIVE`."

    Design: Difficulty/boundary_precision_check/suspend_at_exactly_two_strikes
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 2)
    assert member["no_show_strikes"] == 2
    assert member["status"] == "SUSPENDED"


def test_first_strike_leaves_member_active(api):
    """PRD §3.7: "otherwise a member whose strike count is at least two is moved to
    `SUSPENDED`; below two strikes the member remains `ACTIVE`."

    Design: Difficulty/boundary_precision_check/suspend_at_exactly_two_strikes
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 1)
    assert member["no_show_strikes"] == 1
    assert member["status"] == "ACTIVE"


# ===========================================================================
# Corner B: calculations / queue_position_fifo_ordering
# ===========================================================================
def test_queue_position_fifo_ordering(api):
    """PRD §3.3: "A ticket's `position` is a one-based FIFO rank computed over only the
    `WAITING` tickets in the same salon, ordered by `joined_at` ascending ... A ticket
    that is not `WAITING` has a `position` of 0. This position is recomputed on every
    queue event — join, call, requeue, cancel, no-show."

    Design: Corner/calculations/queue_position_fifo_ordering
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    m_a = th.add_member(salon["id"])
    m_b = th.add_member(salon["id"])
    t_a = th.join_queue(salon["id"], m_a["id"], svc["id"])
    t_b = th.join_queue(salon["id"], m_b["id"], svc["id"])
    # Call A (lowest position). B should move to position 1; A leaves WAITING -> position 0.
    th.call_ticket(t_a["id"])
    reread_b = validate_success(api.get_queue_ticket(t_b["id"], FRONT_DESK))
    reread_a = validate_success(api.get_queue_ticket(t_a["id"], FRONT_DESK))
    assert reread_b["position"] == 1, f"expected B position 1, got {reread_b['position']}"
    assert reread_a["position"] == 0, f"called ticket should have position 0, got {reread_a['position']}"


# ===========================================================================
# Corner B: state_machines / requeue_beyond_recall_limit_rejected
# ===========================================================================
def test_requeue_beyond_recall_limit_rejected(api):
    """PRD §3.3: "This cyclic edge is bounded: a ticket may be requeued at most twice —
    the recall limit is two — and a requeue attempted when `called_count` has already
    reached two is rejected with `ERR_RECALL_LIMIT_REACHED`."

    Design: Corner/state_machines/requeue_beyond_recall_limit_rejected
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    # requeue (cc=1) -> call -> requeue (cc=2) -> call -> requeue should now fail.
    validate_success(api.requeue_queue_ticket(ticket["id"], FRONT_DESK))
    th.call_ticket(ticket["id"])
    validate_success(api.requeue_queue_ticket(ticket["id"], FRONT_DESK))
    th.call_ticket(ticket["id"])
    resp = api.requeue_queue_ticket(ticket["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_RECALL_LIMIT_REACHED.value, expected_status=409)
    reread = validate_success(api.get_queue_ticket(ticket["id"], FRONT_DESK))
    assert reread["called_count"] == 2


# ===========================================================================
# Corner B: validations / call_skip_queue_order_without_allow_skip_rejected
# ===========================================================================
def test_call_skip_queue_order_without_allow_skip_rejected(api):
    """PRD §3.3: "Calling a ticket that is not the lowest-position waiting ticket
    without setting `allow_skip` is rejected with `ERR_QUEUE_ORDER_VIOLATION`."

    Design: Corner/validations/call_skip_queue_order_without_allow_skip_rejected
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    m_a = th.add_member(salon["id"])
    m_b = th.add_member(salon["id"])
    th.join_queue(salon["id"], m_a["id"], svc["id"])  # position 1
    t_b = th.join_queue(salon["id"], m_b["id"], svc["id"])  # position 2
    resp = api.call_queue_ticket(t_b["id"], FRONT_DESK, {})
    validate_error(resp, ApiErrorId.ERR_QUEUE_ORDER_VIOLATION.value, expected_status=409)


# ===========================================================================
# Corner B: validations / member_blocked_join_queue_when_open
# ===========================================================================
def test_member_blocked_join_queue_when_open(api):
    """PRD §3.3: "Joining the queue requires the salon to be `OPEN` (otherwise
    `ERR_SALON_NOT_OPEN`) and the member to be `ACTIVE`; a `SUSPENDED` or `BANNED`
    member attempting to join is refused with `ERR_MEMBER_BLOCKED`."

    Design: Corner/validations/member_blocked_join_queue_when_open
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 2)
    assert member["status"] == "SUSPENDED"
    resp = api.create_queue_ticket(
        th.create_queue_ticket_payload(salon["id"], member["id"], svc["id"]), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_BLOCKED.value, expected_status=403)


# ===========================================================================
# Corner B: endpoints / no_show_records_strike_first_below_threshold
# ===========================================================================
def test_no_show_records_strike_first_below_threshold(api):
    """PRD §3.7: "Each un-expired no-show contributes one strike to `no_show_strikes`,
    and at the moment a no-show is recorded the member's standing is re-evaluated ...
    below two strikes the member remains `ACTIVE`."
    PRD §3.3: "A called guest who does not appear is recorded as a no-show by the
    agent, moving the ticket from `CALLED` to `NO_SHOW`."

    Design: Corner/endpoints/no_show_records_strike_first_below_threshold
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    resp = api.no_show_queue_ticket(ticket["id"], FRONT_DESK)
    data = validate_success(resp)
    assert data["status"] == "NO_SHOW"
    reread = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert reread["no_show_strikes"] == 1
    assert reread["status"] == "ACTIVE"
