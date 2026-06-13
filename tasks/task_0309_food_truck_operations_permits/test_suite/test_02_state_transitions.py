"""State-machine guards: invalid transitions, terminal-state lockdown, and idempotency
rejections that do not require the full revenue setup.

Queue B: state_machines-section corner instances (non-stub).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_commissary, create_truck, issue_permit, add_menu_item, add_prep_batch,
    create_event,
    api_client, TEST_USERS, make_operator_truck_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
HEALTH_INSPECTOR = TEST_USERS["health_inspector_headers"]


def test_revoke_already_revoked_permit_returns_not_active(api):
    """PRD §3.2: "An inspector may **revoke** an active permit, the transition
    `ACTIVE → REVOKED`; revocation requires the permit to currently be `ACTIVE`, failing which it
    is rejected with `ERR_PERMIT_NOT_ACTIVE`."

    Revoking a permit that is already REVOKED fails with ERR_PERMIT_NOT_ACTIVE.

    Design: Corner/state_machines/revoke_already_revoked_permit_returns_not_active
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    permit = issue_permit(truck["id"])
    validate_success(api.revoke_health_permit(permit["id"], HEALTH_INSPECTOR), 200)
    res = api.revoke_health_permit(permit["id"], HEALTH_INSPECTOR)
    validate_error(res, "ERR_PERMIT_NOT_ACTIVE")


def test_discard_already_discarded_batch_returns_not_open(api):
    """PRD §3.5: "A batch can later be discarded, the transition `OPEN → DISCARDED`; the batch
    must currently be `OPEN`, otherwise `ERR_BATCH_NOT_OPEN`."

    Discarding a prep batch twice: the second discard fails with ERR_BATCH_NOT_OPEN.

    Design: Corner/state_machines/discard_already_discarded_batch_returns_not_open
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    item = add_menu_item(truck["id"], unit_price_cents=300, par_units=5)
    batch = add_prep_batch(truck["id"], item["id"], units_made=5)
    h = make_operator_truck_headers(truck["id"])
    validate_success(api.discard_prep_batch(batch["id"], h), 200)
    res = api.discard_prep_batch(batch["id"], h)
    validate_error(res, "ERR_BATCH_NOT_OPEN")


def test_cancel_event_already_cancelled_returns_not_scheduled(api):
    """PRD §3.3: "An event may be cancelled, the transition `SCHEDULED → CANCELLED`, which
    requires it to currently be `SCHEDULED` and is otherwise rejected with
    `ERR_EVENT_NOT_SCHEDULED`."

    Cancelling an Event that is already CANCELLED returns ERR_EVENT_NOT_SCHEDULED.

    Design: Corner/state_machines/cancel_event_already_cancelled_returns_not_scheduled
    """
    event = create_event("2026-07-06T17:00:00.000Z", "2026-07-06T22:00:00.000Z")
    validate_success(api.cancel_event(event["id"], DISPATCHER), 200)
    res = api.cancel_event(event["id"], DISPATCHER)
    validate_error(res, "ERR_EVENT_NOT_SCHEDULED")


def test_commissary_reinstate_requires_suspended(api):
    """PRD §3.1: "Reinstating a commissary is the reverse transition `SUSPENDED → ACTIVE`; it
    requires the commissary to currently be `SUSPENDED`, failing which it is rejected with
    `ERR_COMMISSARY_NOT_SUSPENDED`."

    Reinstating a commissary that is ACTIVE (never suspended) is rejected with
    ERR_COMMISSARY_NOT_SUSPENDED.

    Design: Corner/state_machines/commissary_reinstate_requires_suspended
    """
    commissary = create_commissary()
    res = api.reinstate_commissary(commissary["id"], DISPATCHER)
    validate_error(res, "ERR_COMMISSARY_NOT_SUSPENDED")
