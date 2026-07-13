"""Operator registration, activation, and the suspension/reinstatement cycle.

Covers queue-A difficulty instance non_linear_state_machine/operator_suspend_reinstate_cycle
and queue-B corner entity/state-machine instances for the operator lifecycle.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_operator_payload, assert_operator,
    TEST_USERS,
    set_clock, create_operator, transition_operator,
)

AA = TEST_USERS["airport_authority_headers"]


def test_create_operator_returns_201_pending_version_one(api):
    """PRD §3.1: "A freshly registered operator begins in `PENDING` status with
    `suspended_reason` null."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by
    one on every subsequent mutation."

    Design: Corner/entities/create_operator_returns_201_all_fields
    """
    resp = api.create_operator(
        create_operator_payload(legal_name="New Co", operator_type="TNC", contact_email="n@x.com"),
        AA,
    )
    data = validate_success(resp, 201)
    assert_operator(data)
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"
    assert data["suspended_reason"] is None
    assert data["version"] == 1, f"expected version 1 on creation, got {data['version']}"


def test_create_operator_default_pledge_pct_is_zero(api):
    """PRD §3.1: "An optional `wheelchair_pledge_pct` records the minimum fraction
    of the operator's monthly trips that the operator commits to serving with
    wheelchair-accessible vehicles, a value between 0.0 and 1.0 that defaults to
    0.0 when omitted."

    Design: Corner/entities/create_operator_default_pledge_pct_applied
    """
    resp = api.create_operator(
        create_operator_payload(legal_name="Def Co", operator_type="TAXI", contact_email="d@x.com"),
        AA,
    )
    data = validate_success(resp, 201)
    assert data["wheelchair_pledge_pct"] == 0.0, (
        f"expected default pledge 0.0, got {data['wheelchair_pledge_pct']}"
    )


def test_get_operator_nonexistent_returns_not_found(api):
    """PRD §2.4: "the first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier or business rule is evaluated."

    Design: Corner/entities/get_operator_nonexistent_returns_not_found
    """
    resp = api.get_operator("00000000-0000-4000-8000-000000000000", AA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_suspend_revoked_operator_returns_invalid_state(api):
    """PRD §3.1: "`REVOKED` is terminal."
    PRD §3.1: "Any transition requested from a state that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/suspend_revoked_operator_terminal_lockdown
    """
    op = create_operator(api, operator_type="LIMO", legal_name="Rev Co", activate=True)
    transition_operator(api, op["id"], "REVOKE")
    resp = api.transition_operator(op["id"], {"action": "SUSPEND"}, AA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_activate_already_active_operator_returns_invalid_state(api):
    """PRD §3.1: "The regulator moves an operator from `PENDING` to `ACTIVE` by
    activating it."
    PRD §3.1: "Any transition requested from a state that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_operator_twice_idempotency_rejected
    """
    op = create_operator(api, operator_type="TNC", legal_name="Idem Co", activate=True)
    resp = api.transition_operator(op["id"], {"action": "ACTIVATE"}, AA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_operator_suspend_then_reinstate_returns_to_active(api):
    """PRD §3.1: "a reinstatement triggers the credential-restoring reverse cascade,
    clearing `suspended_reason` back to null on the operator."

    Design: Difficulty/non_linear_state_machine/operator_suspend_reinstate_cycle
    """
    set_clock(api, "2026-03-05T00:00:00Z")
    op = create_operator(api, operator_type="SHUTTLE", legal_name="Cyc Co", activate=True)
    transition_operator(api, op["id"], "SUSPEND")
    reinstated = transition_operator(api, op["id"], "REINSTATE")
    assert reinstated["status"] == "ACTIVE", f"expected ACTIVE after reinstate, got {reinstated['status']}"
    assert reinstated["suspended_reason"] is None, (
        f"expected suspended_reason cleared to null, got {reinstated['suspended_reason']}"
    )


def test_operator_admin_suspend_sets_reason_admin(api):
    """PRD §3.1: "an operator may be administratively suspended (transitioning
    `ACTIVE → SUSPENDED` and setting `suspended_reason` to `ADMIN`)"

    Design: Difficulty/non_linear_state_machine/operator_suspend_reinstate_cycle
    """
    set_clock(api, "2026-03-05T00:00:00Z")
    op = create_operator(api, operator_type="SHUTTLE", legal_name="Cyc Co", activate=True)
    suspended = transition_operator(api, op["id"], "SUSPEND")
    assert suspended["status"] == "SUSPENDED", f"expected SUSPENDED, got {suspended['status']}"
    assert suspended["suspended_reason"] == "ADMIN", (
        f"expected suspended_reason ADMIN, got {suspended['suspended_reason']}"
    )
