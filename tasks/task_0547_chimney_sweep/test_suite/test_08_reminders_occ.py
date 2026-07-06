"""Recurring reminders and the chimney-version optimistic concurrency on reminder create."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, validate_success, validate_error,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------- corner: recurrence on ack
def test_acknowledge_due_reminder_advances_cycle():
    """PRD §3.8: "On acknowledgement the `next_due_date` advances by
    `cadence_months` and the `acknowledged_count` increases by one."
    PRD §3.8: "Acknowledgement is a self-loop that keeps the schedule `ACTIVE`: it
    is permitted only when the schedule is `ACTIVE` — otherwise
    `ERR_INVALID_STATE_TRANSITION` — and only when the reminder is due, meaning the
    clock has reached its `next_due_date`; acknowledging a not-yet-due reminder is
    `ERR_REMINDER_NOT_DUE`."

    Design: Corner/calculations/reminder_recurrence_on_acknowledge
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    reminder = fx.create_reminder(customer["id"], chimney["id"], chimney["version"], cadence_months=12)
    fx.set_clock("2027-06-01T00:00:00Z")  # past next_due_date (2027-05-01), so is_due
    resp = api_client.acknowledge_reminder_schedule(reminder["id"], DISPATCHER)
    data = validate_success(resp, 200)
    assert data["acknowledged_count"] == 1
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------- corner: reminder not due
def test_acknowledge_not_due_reminder_rejected():
    """PRD §3.8: "acknowledging a not-yet-due reminder is `ERR_REMINDER_NOT_DUE`."

    Design: Corner/validations/error_reminder_not_due_on_acknowledge
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    reminder = fx.create_reminder(customer["id"], chimney["id"], chimney["version"], cadence_months=12)
    # Clock unchanged (default 2026-05-01); next_due_date is 2027-05-01, so not due.
    resp = api_client.acknowledge_reminder_schedule(reminder["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_REMINDER_NOT_DUE)


# ---------------------------------------------------------------- occ stale version
def test_reminder_create_with_stale_chimney_version_rejected():
    """PRD §2.10: "If that value does not match the chimney's current `version` —
    because another writer has already superseded the reminder and advanced the
    version — the create is rejected with `ERR_STALE_CHIMNEY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_chimney_version_rejected
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    observed_version = chimney["version"]
    # First create supersedes/creates and advances the chimney version.
    fx.create_reminder(customer["id"], chimney["id"], observed_version, cadence_months=12)
    # Second create still carrying the originally observed (now stale) version.
    resp = api_client.create_reminder_schedule(
        F.create_reminder_schedule_payload(customer_id=customer["id"], chimney_id=chimney["id"],
                                           cadence_months=12, expected_chimney_version=observed_version),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CHIMNEY_VERSION)


# ---------------------------------------------------------------- occ supersede success
def test_reminder_create_with_fresh_version_supersedes_prior():
    """PRD §2.10: "Creating a new reminder legitimately supersedes any prior
    `ACTIVE` schedule for that chimney (deactivating it) and, as part of that act,
    increments the chimney's `version`."
    PRD §3.8: "creating a new schedule supersedes any prior `ACTIVE` one for the
    same chimney, moving that older schedule `ACTIVE → DEACTIVATED`, and — as the
    act of superseding — increments the chimney's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_success_supersedes_prior_reminder
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    reminder1 = fx.create_reminder(customer["id"], chimney["id"], chimney["version"], cadence_months=12)
    fresh = fx.get_chimney_version(chimney["id"])
    reminder2 = fx.create_reminder(customer["id"], chimney["id"], fresh, cadence_months=6)
    assert fx.get_reminder(reminder1["id"])["status"] == "DEACTIVATED"
    assert fx.get_reminder(reminder2["id"])["status"] == "ACTIVE"
