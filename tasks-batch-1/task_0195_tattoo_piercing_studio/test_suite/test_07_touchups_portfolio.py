"""Aftercare touch-ups and portfolio curation.

Covers the touch-up free-window fee policy (day-90 inclusive vs day-91 charged),
the parent-must-be-COMPLETED cross-entity dependency for requesting and
scheduling touch-ups, terminal-state lockdown, and portfolio publish gating on a
completed parent.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_artist_headers, make_client_headers,
    set_clock,
    setup_completed_appointment, setup_confirmed_appointment,
    setup_requested_touchup, setup_draft_portfolio_item,
    setup_draft_portfolio_item_on_confirmed,
)

MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Touch-up free-window fee (PRD §3.10)
# ---------------------------------------------------------------------------
def test_touchup_free_window_day_ninety_inclusive(api):
    """PRD §3.10: "The touch-up is free — `fee_cents` of 0 — when it is requested
    on or before the 90th day, that is, when the elapsed whole days are at most
    the free window of 90 days, **and** the original session's `ConsentWaiver`
    had `aftercare_acknowledged` set to true."

    Completion clock 2026-06-01; request at 2026-08-30 (exactly 90 days) -> free.

    Design: Difficulty/boundary_precision_check/touchup_free_window_day_ninety_inclusive
    """
    ctx = setup_requested_touchup(
        clock="2026-05-15T12:00:00Z", complete_clock="2026-06-01T12:00:00Z",
        request_clock="2026-08-30T12:00:00Z", aftercare_acknowledged=True,
    )
    assert ctx["touchup"]["fee_cents"] == 0, \
        f"day-90 touch-up must be free, got {ctx['touchup']['fee_cents']}"
    assert ctx["touchup"]["status"] == "REQUESTED", \
        f"new touch-up must be REQUESTED, got {ctx['touchup']['status']}"


def test_touchup_well_within_free_window_is_free(api):
    """PRD §3.10: "The touch-up is free — `fee_cents` of 0 — when it is requested
    on or before the 90th day, that is, when the elapsed whole days are at most
    the free window of 90 days, **and** the original session's `ConsentWaiver`
    had `aftercare_acknowledged` set to true."

    Second point on the inclusive free-window boundary: a touch-up requested only
    a few days after completion (well inside the 90-day window) is free.

    Design: Difficulty/boundary_precision_check/touchup_free_window_day_ninety_inclusive
    """
    ctx = setup_requested_touchup(
        clock="2026-05-15T12:00:00Z", complete_clock="2026-06-01T12:00:00Z",
        request_clock="2026-06-05T12:00:00Z", aftercare_acknowledged=True,
    )
    assert ctx["touchup"]["fee_cents"] == 0, \
        f"touch-up well inside the free window must be free, got {ctx['touchup']['fee_cents']}"


def test_touchup_day_ninetyone_charges_flat_fee(api):
    """PRD §3.10: "In every other case — requested after the 90-day free window,
    or where aftercare was not acknowledged — the `fee_cents` is the studio's
    flat touch-up fee of 6000 cents."

    Completion clock 2026-06-01; request at 2026-08-31 (91 days) -> 6000.

    Design: Corner/calculations/touchup_fee_day_ninetyone_charges_flat
    """
    ctx = setup_requested_touchup(
        clock="2026-05-15T12:00:00Z", complete_clock="2026-06-01T12:00:00Z",
        request_clock="2026-08-31T12:00:00Z", aftercare_acknowledged=True,
    )
    assert ctx["touchup"]["fee_cents"] == 6000, \
        f"day-91 touch-up must charge 6000, got {ctx['touchup']['fee_cents']}"


# ---------------------------------------------------------------------------
# Touch-up parent-must-be-COMPLETED (PRD §3.10)
# ---------------------------------------------------------------------------
def test_touchup_request_on_confirmed_parent_rejected(api):
    """PRD §3.10: "A touch-up may be requested only against a parent appointment
    that is `COMPLETED`; a request against a parent in any other state is rejected
    with `ERR_TOUCHUP_PARENT_NOT_COMPLETED`."

    Design: Corner/validations/error_touchup_parent_not_completed_corner
    """
    ctx = setup_confirmed_appointment(clock="2026-06-01T12:00:00Z")
    resp = api.request_touchup(ctx["appointment_id"], make_client_headers(ctx["client_id"]))
    validate_error(resp, ApiErrorId.ERR_TOUCHUP_PARENT_NOT_COMPLETED.value, expected_status=422)


def test_touchup_schedule_requires_parent_completed(api):
    """PRD §3.10: "Scheduling moves it from `REQUESTED` to `SCHEDULED`, and is
    permitted only when the touch-up is `REQUESTED` and its parent appointment is
    `COMPLETED`".

    The only way to create a touch-up is on a COMPLETED parent, so scheduling
    succeeds (positive cross-entity dependency).

    Design: Difficulty/cross_entity_state_dependency/touchup_schedule_requires_parent_completed
    """
    ctx = setup_requested_touchup(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
    )
    scheduled = validate_success(api.schedule_touchup(ctx["touchup_id"], MANAGER), expected_status=200)
    assert scheduled["status"] == "SCHEDULED", \
        f"touch-up on a COMPLETED parent must schedule, got {scheduled['status']}"


def test_touchup_schedule_parent_completed_appointment_unchanged(api):
    """PRD §3.10: "Scheduling moves it from `REQUESTED` to `SCHEDULED`, and is
    permitted only when the touch-up is `REQUESTED` and its parent appointment is
    `COMPLETED`".
    PRD §3.9: "An `Artist` completes a session, moving the appointment from
    `CONFIRMED` to `COMPLETED`".

    Second assertion on the positive cross-entity instance: the parent stays
    COMPLETED through the schedule.

    Design: Difficulty/cross_entity_state_dependency/touchup_schedule_requires_parent_completed
    """
    ctx = setup_requested_touchup(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
    )
    get_success_data(api.schedule_touchup(ctx["touchup_id"], MANAGER))
    parent = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    assert parent["status"] == "COMPLETED", f"parent must remain COMPLETED, got {parent['status']}"


def test_touchup_schedule_from_denied_invalid_state(api):
    """PRD §3.10: "Scheduling moves it from `REQUESTED` to `SCHEDULED`, and is
    permitted only when the touch-up is `REQUESTED` ... Denial moves it from
    `REQUESTED` to the terminal `DENIED`".
    PRD §2.9: "an operation requested against a resource that is not in a state
    permitting the transition fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/touchup_schedule_from_denied_invalid_state
    """
    ctx = setup_requested_touchup(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
    )
    get_success_data(api.deny_touchup(ctx["touchup_id"], MANAGER))
    resp = api.schedule_touchup(ctx["touchup_id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_touchup(ctx["touchup_id"], MANAGER))
    assert after["status"] == "DENIED", f"touch-up must stay DENIED, got {after['status']}"


# ---------------------------------------------------------------------------
# Portfolio publish gating (PRD §3.11)
# ---------------------------------------------------------------------------
def test_portfolio_publish_from_completed_parent_succeeds(api):
    """PRD §3.11: "Publishing moves a portfolio item from `DRAFT` to `PUBLISHED`;
    it is permitted only when the item is currently `DRAFT` and the linked
    appointment is `COMPLETED`."

    Design: Corner/state_machines/portfolio_publish_from_completed_parent_succeeds
    """
    ctx = setup_draft_portfolio_item(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
    )
    published = validate_success(
        api.publish_portfolio_item(ctx["portfolio_item_id"], make_artist_headers(ctx["artist_id"])),
        expected_status=200,
    )
    assert published["visibility"] == "PUBLISHED", \
        f"expected PUBLISHED, got {published['visibility']}"


def test_portfolio_publish_parent_not_completed_invalid_state(api):
    """PRD §3.11: "Publishing moves a portfolio item from `DRAFT` to `PUBLISHED`;
    it is permitted only when the item is currently `DRAFT` and the linked
    appointment is `COMPLETED`."
    PRD §3.11: "A transition requested from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/portfolio_publish_parent_not_completed_invalid_state
    """
    ctx = setup_draft_portfolio_item_on_confirmed()
    resp = api.publish_portfolio_item(ctx["portfolio_item_id"], make_artist_headers(ctx["artist_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_portfolio_item(ctx["portfolio_item_id"], MANAGER))
    assert after["visibility"] == "DRAFT", f"item must stay DRAFT, got {after['visibility']}"
