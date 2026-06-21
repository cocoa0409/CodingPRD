"""Pass issuance, activation field effects, and the non-linear pass state machine.

Covers the ISSUED->ACTIVE->SUSPENDED->ACTIVE cycle, the side effects of first
activation, default counters on issuance, magnetic-token minting, and invalid
transitions out of the pass machine.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]
OPS = TEST_USERS["resort_ops_headers"]


def test_pass_issue_mints_non_empty_unique_magnetic_token(api):
    """PRD §3.2: "On issuance the server mints a unique `magnetic_token` and the
    pass is created in `status` `ISSUED`."
    PRD §2.8: "When a pass is issued, the server mints a unique `magnetic_token`
    and prints it on the media; at every gate the scanned `presented_token` must
    equal that stored token."

    Design: Corner/entities/pass_issue_mints_unique_magnetic_token
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    p1 = validate_success(
        api.create_pass(factories.create_pass_payload(product["id"], holder_name="Tok A"), OPS),
        201,
    )
    p2 = validate_success(
        api.create_pass(factories.create_pass_payload(product["id"], holder_name="Tok B"), OPS),
        201,
    )
    assert isinstance(p1["magnetic_token"], str) and len(p1["magnetic_token"]) > 0, \
        "magnetic_token must be a non-empty string"
    assert p2["magnetic_token"] != p1["magnetic_token"], \
        "two passes must receive distinct magnetic tokens"


def test_pass_issue_defaults_status_issued_and_zero_counters(api):
    """PRD §3.2: "At this point its computed fields sit at their initial values:
    `scan_count` is 0, `buddy_tickets_remaining` is 0, `refund_basis_cents` is 0,
    and `activated_on` is unset."

    Design: Corner/entities/pass_issue_defaults_status_issued_and_counters_zero
    """
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, buddy_ticket_allotment=3,
        buddy_ticket_price_cents=1000,
    )
    data = validate_success(
        api.create_pass(factories.create_pass_payload(product["id"], holder_name="Fresh"), OPS),
        201,
    )
    assert data["status"] == "ISSUED"
    assert data["scan_count"] == 0
    assert data["buddy_tickets_remaining"] == 0
    assert data["activated_on"] is None


def test_pass_activate_sets_refund_basis_buddy_remaining_and_activated_on(api):
    """PRD §3.2: "on success it sets `activated_on` to the current clock instant in
    UTC, copies the referenced product's `price_cents` into the pass's
    `refund_basis_cents`, and sets `buddy_tickets_remaining` to the product's
    `buddy_ticket_allotment`."

    Design: Corner/entities/pass_activate_sets_refund_basis_and_buddy_remaining
    """
    fixtures.set_clock(api, "2026-01-03T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=6000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=1000,
    )
    issued = fixtures.issue_pass(api, product["id"], holder_name="Activate Me")
    data = validate_success(api.activate_pass(issued["id"], OPS), 200)
    assert data["status"] == "ACTIVE"
    assert data["refund_basis_cents"] == 6000
    assert data["buddy_tickets_remaining"] == 2
    assert data["activated_on"] is not None


def test_pass_cycle_active_suspended_active(api):
    """PRD §3.2: "Moving a pass from `ACTIVE` to `SUSPENDED` is permitted only when
    the pass is currently `ACTIVE`."
    PRD §3.2: "The same action also reinstates a suspended pass: moving a pass from
    `SUSPENDED` back to `ACTIVE` is permitted only when the pass is currently
    `SUSPENDED`".

    Design: Difficulty/non_linear_state_machine/pass_branching_active_to_suspended_refunded_expired
    """
    fixtures.set_clock(api, "2026-01-05T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Cycle Holder")
    fixtures.activate_pass(api, issued["id"])
    suspended = validate_success(api.suspend_pass(issued["id"], OPS), 200)
    assert suspended["status"] == "SUSPENDED", "after suspend, status must be SUSPENDED"
    reactivated = validate_success(api.activate_pass(issued["id"], OPS), 200)
    assert reactivated["status"] == "ACTIVE", "after re-activate, status must be ACTIVE"


def test_pass_reactivate_preserves_basis_and_does_not_restore_buddies(api):
    """PRD §3.2: "on reinstatement `activated_on` and `refund_basis_cents` are left
    exactly as they were at first activation — they are not recomputed — and buddy
    tickets that were previously cancelled are not restored."

    Design: Difficulty/non_linear_state_machine/pass_branching_active_to_suspended_refunded_expired
    """
    fixtures.set_clock(api, "2026-02-05T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, buddy_ticket_allotment=1,
        buddy_ticket_price_cents=1000,
    )
    resort = fixtures.create_resort(api, name="Reinstate Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Reinstate Host")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-06", guest_name="G1")
    validate_success(api.suspend_pass(issued["id"], OPS), 200)
    reactivated = validate_success(api.activate_pass(issued["id"], OPS), 200)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["refund_basis_cents"] == 5000, \
        "refund_basis_cents must be unchanged from first activation"
    bt_now = validate_success(api.get_buddy_ticket(bt["id"], OPS), 200)
    assert bt_now["status"] == "CANCELLED", \
        "a buddy ticket cancelled by suspend must NOT be restored on reinstatement"
    assert reactivated["buddy_tickets_remaining"] == 1


def test_activate_already_active_pass_returns_invalid_state(api):
    """PRD §3.2: "Attempting to activate a pass that is in neither `ISSUED` nor
    `SUSPENDED` is rejected as an invalid state transition with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_pass_returns_invalid_state
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Active Already")
    fixtures.activate_pass(api, issued["id"])
    resp = api.activate_pass(issued["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_suspend_issued_pass_returns_invalid_state(api):
    """PRD §3.2: "A suspend attempt on a pass that is not `ACTIVE` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/suspend_issued_pass_returns_invalid_state
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Issued Only")
    resp = api.suspend_pass(issued["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
