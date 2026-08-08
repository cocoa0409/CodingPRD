"""Permit cyclic lifecycle and invalid/terminal transitions
(Difficulty: non_linear_state_machine; Corner: state_machines)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, make_vendor_headers,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]


# --------------------------------------------------------------------------- #
# non_linear_state_machine / permit_cycle_issued_suspended_reinstated
# --------------------------------------------------------------------------- #
def test_permit_suspend_moves_to_suspended(api):
    """PRD §2.7: "When a permit leaves ISSUED for SUSPENDED, every SpotAssignment
    that belongs to that permit and is still ACTIVE transitions to RELEASED."

    Design: Difficulty/non_linear_state_machine/permit_cycle_issued_suspended_reinstated
    """
    ctx = fx.setup_issued_permit()
    permit = ctx["permit"]
    suspended = validate_success(api.suspend_permit(permit["id"], PO, {"reason": "admin-hold"}), 200)
    assert suspended["status"] == "SUSPENDED"


def test_permit_reinstate_returns_to_issued(api):
    """PRD §3.9: "Once a permit has been suspended, a PermitOfficer may reinstate it
    (SUSPENDED → ISSUED), but only when the permit's violation_points is below the
    suspension threshold of 12 — otherwise ERR_INVALID_STATE — and its cart is
    APPROVED — otherwise ERR_CART_NOT_APPROVED"

    Design: Difficulty/non_linear_state_machine/permit_cycle_issued_suspended_reinstated
    """
    ctx = fx.setup_issued_permit()
    permit = ctx["permit"]
    get_success_data(api.suspend_permit(permit["id"], PO, {"reason": "hold"}))
    reinstated = validate_success(api.reinstate_permit(permit["id"], PO), 200)
    assert reinstated["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# Corner state_machines: submit_already_submitted_permit_invalid_state
# --------------------------------------------------------------------------- #
def test_submit_already_submitted_permit_invalid_state(api):
    """PRD §4: "A transition attempted on a resource in an illegal state returns
    ERR_INVALID_STATE"

    Design: Corner/state_machines/submit_already_submitted_permit_invalid_state
    """
    fx.set_clock()
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"], inspect=False, approve=False)
    zone = fx.create_zone(zone_type="STANDARD")
    permit = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    res = api.submit_permit(permit["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# --------------------------------------------------------------------------- #
# Corner state_machines: revoke_then_reinstate_terminal_lockdown
# --------------------------------------------------------------------------- #
def test_reinstate_revoked_permit_terminal_lockdown(api):
    """PRD §4: "one attempted from a terminal state returns ERR_TERMINAL_STATE"
    PRD §3.9: "a PermitOfficer may instead revoke the permit (SUSPENDED → REVOKED),
    a terminal state permitting no further transitions."

    Design: Corner/state_machines/revoke_then_reinstate_terminal_lockdown
    """
    ctx = fx.setup_issued_permit()
    permit = ctx["permit"]
    get_success_data(api.suspend_permit(permit["id"], PO, {"reason": "hold"}))
    get_success_data(api.revoke_permit(permit["id"], PO))
    res = api.reinstate_permit(permit["id"], PO)
    validate_error(res, "ERR_TERMINAL_STATE", expected_status=409)
