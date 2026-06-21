"""Invalid-transition and terminal-state-lockdown tests for the service-call lifecycle."""
from test_helpers import (
    validate_error,
    setup_completed_call,
    ApiErrorId, TEST_USERS, make_member_headers, make_provider_headers,
)

OP = TEST_USERS["dispatch_operator_headers"]


def test_cancel_completed_call_terminal_lockdown(api):
    """PRD §3.9: "Attempting to cancel from any other state is rejected as an illegal
    state change."
    PRD §3.5: "The full lifecycle states are `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`,
    `COMPLETED`, `CANCELLED`, and `UNFULFILLED`, of which the last three are terminal."

    A COMPLETED (terminal) call cannot be cancelled.

    Design: Corner/state_machines/cancel_completed_call_terminal_lockdown_returns_invalid_state
    """
    ctx = setup_completed_call(final_towed_miles=20)
    resp = api.cancel_call(ctx["call"]["id"], make_member_headers(ctx["member"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
