"""Line, PortRequest, and AddOn state-machine behavior.

Translates difficulty queue (A) non_linear_state_machine instances and several
corner queue (B) state_machines instances.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_subscriber_headers,
    create_addon_payload,
    setup_active_line, setup_completed_portin_line,
    open_port_request, set_clock,
)

CA = TEST_USERS["carrier_agent_headers"]
PO = TEST_USERS["porting_ops_headers"]


# ─── Queue A: non_linear_state_machine ────────────────────────────────────

def test_line_suspend_then_reconnect_returns_to_active(api):
    """PRD §3.4: "Reconnecting reverses the park, moving the line from
    `SUSPENDED` back to `ACTIVE`." "A successful reconnect clears the line's
    `suspend_reason` and returns the SIM assignment from `DEACTIVATED` to
    `ACTIVATED`."

    Design: Difficulty/non_linear_state_machine/line_suspend_reconnect_cycle
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA), 200)

    reconnected = validate_success(api.reconnect_line(line["id"], CA), 200)
    assert reconnected["status"] == "ACTIVE", "line returns to ACTIVE via the cycle"
    assert reconnected.get("suspend_reason") in (None, ""), \
        "suspend_reason cleared after reconnect"


def test_suspend_reconnect_reactivates_sim(api):
    """PRD §3.4: "When a line is suspended, its linked SIM assignment moves from
    `ACTIVATED` to `DEACTIVATED`". PRD §3.4: "A successful reconnect clears the
    line's `suspend_reason` and returns the SIM assignment from `DEACTIVATED` to
    `ACTIVATED`."

    Design: Difficulty/non_linear_state_machine/line_suspend_reconnect_cycle
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA), 200)
    sims = _sims_for_line(api, line["id"])
    assert sims[0]["status"] == "DEACTIVATED"

    validate_success(api.reconnect_line(line["id"], CA), 200)
    sims = _sims_for_line(api, line["id"])
    assert sims[0]["status"] == "ACTIVATED", "SIM returns to ACTIVATED on reconnect"


def test_completed_portin_can_be_reverted(api):
    """PRD §3.7: "Finally, `PortingOps` may revert a completed port, but only a
    completed `PORT_IN`: revert is defined only from `COMPLETED`, and only for a
    port-in." PRD §3.7: "A successful port-in revert clears the line's
    `phone_number` back to null, returning the number to the donor and restoring
    the conserved number-pool invariant."

    Design: Difficulty/non_linear_state_machine/port_request_branching_reject_then_revert
    """
    account, plan, line, pr = setup_completed_portin_line(
        external_number="12025550111", account_pin="9999")
    assert pr["status"] == "COMPLETED"

    reverted = validate_success(api.revert_port_request(pr["id"], PO), 200)
    assert reverted["status"] == "REVERTED"
    line_after = validate_success(api.get_line(line["id"], CA), 200)
    assert line_after.get("phone_number") is None, "number returned to donor on revert"


def test_portin_validate_then_complete_imports_number(api):
    """PRD §3.7: "On a port-in, the line's `phone_number` is set to the imported
    `external_number`".

    Design: Difficulty/non_linear_state_machine/port_request_branching_reject_then_revert
    """
    account, plan, line, pr = setup_completed_portin_line(
        external_number="12025550111", account_pin="9999")
    assert pr["status"] == "COMPLETED"
    line_after = validate_success(api.get_line(line["id"], CA), 200)
    assert line_after["phone_number"] == "12025550111", \
        "completed PORT_IN sets phone_number to the imported number"


# ─── Queue B: state_machines corners ──────────────────────────────────────

def test_suspend_already_suspended_returns_invalid_state(api):
    """PRD §3.4: "Suspension is only defined from `ACTIVE`; attempting it from
    any other state fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/suspend_already_suspended_line_returns_invalid_state
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA), 200)

    res = api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA)
    validate_error(res, "ERR_INVALID_STATE")
    line_after = validate_success(api.get_line(line["id"], CA), 200)
    assert line_after["status"] == "SUSPENDED", "line stays SUSPENDED"


def test_cancel_terminal_line_returns_invalid_state(api):
    """PRD §3.5: "the transition is defined from either `ACTIVE` or `SUSPENDED`,
    and an attempt from any other state fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_line_returns_invalid_state
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    set_clock("2026-06-01T00:00:00Z")
    sub = make_subscriber_headers(account["id"])
    validate_success(api.cancel_line(line["id"], sub), 200)

    res = api.cancel_line(line["id"], sub)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_blocked_by_in_progress_port_request(api):
    """PRD §3.5: "if any port request on the line is in `REQUESTED` or
    `VALIDATED` status, the cancel is rejected with `ERR_PORT_IN_PROGRESS` (HTTP
    409)."

    Design: Corner/state_machines/cancel_blocked_by_in_progress_port_request
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    open_port_request(account["id"], line["id"], direction="PORT_OUT",
                      external_number="12025550133", account_pin="2468",
                      donor_carrier="RivalCo")

    res = api.cancel_line(line["id"], make_subscriber_headers(account["id"]))
    validate_error(res, "ERR_PORT_IN_PROGRESS")


def test_revert_portout_returns_not_revertable(api):
    """PRD §3.7: "A revert attempted on a port-out, or on any port not in
    `COMPLETED`, is rejected with `ERR_PORT_NOT_REVERTABLE` (HTTP 409)".

    Design: Corner/state_machines/revert_portout_returns_not_revertable
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    pr = open_port_request(account["id"], line["id"], direction="PORT_OUT",
                           external_number="12025550144", account_pin="1357",
                           donor_carrier="RivalCo")
    validate_success(api.validate_port_request(pr["id"], {"account_pin": "1357"}, PO), 200)
    validate_success(api.complete_port_request(pr["id"], PO), 200)

    res = api.revert_port_request(pr["id"], PO)
    validate_error(res, "ERR_PORT_NOT_REVERTABLE")


def test_validate_port_pin_mismatch_rejects(api):
    """PRD §3.7: "if it does not match the PIN stored on the port request, the
    port is not validated but instead transitions to `REJECTED` with its
    `reject_reason` set to `PIN_MISMATCH`."

    Design: Corner/state_machines/validate_port_pin_mismatch_rejects
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    pr = open_port_request(account["id"], line["id"], direction="PORT_IN",
                           external_number="12025550155", account_pin="1111")

    res = api.validate_port_request(pr["id"], {"account_pin": "2222"}, PO)
    pr_after = validate_success(res, 200)
    assert pr_after["status"] == "REJECTED"
    assert pr_after["reject_reason"] == "PIN_MISMATCH"


def test_addon_activate_before_window_start_rejected(api):
    """PRD §3.8: "in both cases the current UTC must be at or past `window_start`
    (otherwise `ERR_ADDON_WINDOW_NOT_STARTED`, HTTP 409)".

    Design: Corner/state_machines/addon_activate_before_window_start_rejected
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    set_clock("2026-06-10T00:00:00Z")
    addon = validate_success(api.create_addon(
        create_addon_payload(line["id"], "INTL_MONTHLY",
                             "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
                             monthly_fee_cents=3000),
        make_subscriber_headers(account["id"])), 201)

    res = api.activate_addon(addon["id"], make_subscriber_headers(account["id"]))
    validate_error(res, "ERR_ADDON_WINDOW_NOT_STARTED")


def _sims_for_line(api, line_id):
    """Return the SimAssignment list for a line (the list endpoint's data array)."""
    res = api.list_sim_assignments(CA, params={"line_id": line_id})
    return validate_success(res, 200)
