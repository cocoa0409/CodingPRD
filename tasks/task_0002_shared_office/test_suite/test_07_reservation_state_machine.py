"""Reservation state-machine tests: confirm, cancel, check-in, check-out, sweep.

Covers PRD §3.3 (PENDING → CONFIRMED → IN_USE → COMPLETED plus CANCELLED and
NO_SHOW branches) and PRD §2.6 (sweep semantics).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    check_in_reservation,
    check_out_reservation,
    confirm_reservation,
    create_access_event_payload,
    create_and_confirm_reservation,
    create_reservation,
    create_resource,
    get_reservation,
    make_tenant_member_headers,
    run_sweep,
    setup_tenant_member_badge,
    validate_error,
    validate_success,
)


def test_confirm_pending_reservation(api, admin_headers):
    """PRD §3.3: "Acting as a `TenantMember` or `TenantAdmin`, the caller confirms a
    reservation that is currently `PENDING`, which requires the tenant's
    `access_posture` to be `OPEN`, the resource's `status` to be `AVAILABLE`, the
    reserving member's `status` to be `ACTIVE`, and no other reservation on the
    same resource in `CONFIRMED` or `IN_USE` to overlap the requested interval.
    Confirmation transitions the reservation from `PENDING` to `CONFIRMED` and
    computes the provisional fee, which is stored on `provisional_fee_cents`."

    Claim: PENDING → CONFIRMED writes non-negative provisional_fee_cents.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(
        kind="WORKSTATION", code="WS-CONF-1", hourly_rate_cents=800
    )
    advance_clock_to("2026-07-11T07:00:00.000Z")
    pending = create_reservation(
        tenant, member, resource,
        "2026-07-11T09:00:00.000Z", "2026-07-11T11:00:00.000Z",
    )
    confirmed = confirm_reservation(pending, member)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["provisional_fee_cents"] >= 0


def test_confirm_non_pending_reservation_rejected(api, admin_headers):
    """PRD §2.8: "an illegal state transition yields the per-entity state error
    (`ERR_INVALID_RESERVATION_STATE`, ...)."

    Claim: calling /confirm on an already-CONFIRMED reservation →
    ERR_INVALID_RESERVATION_STATE (409).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-CONF-2")
    advance_clock_to("2026-07-12T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-12T09:00:00.000Z", "2026-07-12T10:00:00.000Z",
    )
    headers = make_tenant_member_headers(member["id"])
    res = api.confirm_reservation(confirmed["id"], headers)
    validate_error(res, "ERR_INVALID_RESERVATION_STATE", expected_status=409)


def test_cancel_pending_reservation(api, admin_headers):
    """PRD §3.3: "Cancelling a `PENDING` reservation is always permitted."

    Claim: /cancel on PENDING → CANCELLED.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    resource = create_resource(kind="WORKSTATION", code="WS-CANC-1")
    advance_clock_to("2026-07-13T07:00:00.000Z")
    pending = create_reservation(
        tenant, member, resource,
        "2026-07-13T09:00:00.000Z", "2026-07-13T10:00:00.000Z",
    )
    headers = make_tenant_member_headers(member["id"])
    res = api.cancel_reservation(pending["id"], headers)
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED"


def test_cancel_confirmed_pre_start_clears_provisional_fee(api, admin_headers):
    """PRD §3.3: "cancelling a `CONFIRMED` reservation is only permitted while the
    current clock remains strictly earlier than `start_at`, and it clears
    `provisional_fee_cents` back to 0 because a future refund has not yet been
    consolidated."

    Claim: /cancel on CONFIRMED reservation with now() < start_at → CANCELLED
    with provisional_fee_cents = 0.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-CANC-2", hourly_rate_cents=800)
    advance_clock_to("2026-07-14T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-14T09:00:00.000Z", "2026-07-14T10:00:00.000Z",
    )
    assert confirmed["provisional_fee_cents"] > 0
    headers = make_tenant_member_headers(member["id"])
    res = api.cancel_reservation(confirmed["id"], headers)
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["provisional_fee_cents"] == 0


def test_check_in_transitions_confirmed_to_in_use(api, admin_headers):
    """PRD §3.3: "On success, the reservation transitions from `CONFIRMED` to
    `IN_USE`, `actual_start_at` is stamped with the current clock, and the badge's
    `last_used_at` is refreshed."

    Claim: CHECK_IN access event → IN_USE with actual_start_at populated.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-CKIN-1", hourly_rate_cents=800)
    advance_clock_to("2026-07-15T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-15T09:00:00.000Z", "2026-07-15T11:00:00.000Z",
    )
    advance_clock_to("2026-07-15T09:00:00.000Z")
    check_in_reservation(confirmed, member, badge)
    post = get_reservation(confirmed["id"])
    assert post["status"] == "IN_USE"
    assert post["actual_start_at"] is not None


def test_check_out_transitions_in_use_to_completed(api, admin_headers):
    """PRD §3.3: "Check-out is performed by the same member through an access
    event with `kind` equal to `CHECK_OUT` ... On success, the reservation
    transitions from `IN_USE` to `COMPLETED`."

    Claim: CHECK_OUT after CHECK_IN → COMPLETED with final_fee_cents and
    actual_end_at populated.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-CKOUT-1", hourly_rate_cents=800)
    advance_clock_to("2026-07-16T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-16T09:00:00.000Z", "2026-07-16T10:00:00.000Z",
    )
    advance_clock_to("2026-07-16T09:00:00.000Z")
    check_in_reservation(confirmed, member, badge)
    advance_clock_to("2026-07-16T10:00:00.000Z")
    check_out_reservation(confirmed, member, badge)
    post = get_reservation(confirmed["id"])
    assert post["status"] == "COMPLETED"
    assert post["final_fee_cents"] >= 0
    assert post["actual_end_at"] is not None


def test_sweep_confirmed_past_end_transitions_to_no_show(api, admin_headers):
    """PRD §3.3: "A reservation that never gets a check-in also has to be
    reconciled: when the sweep observes a reservation still in `CONFIRMED` after
    `end_at` has passed, it transitions the reservation from `CONFIRMED` to `NO_SHOW`,
    sets `final_fee_cents` equal to the already-stored `provisional_fee_cents`
    (no-shows still bill), consolidates the reservation onto the tenant's
    current `DRAFT` bill, and recomputes the bill totals."

    Claim: sweep past end_at on a CONFIRMED (no-checkin) reservation → NO_SHOW
    with final_fee_cents == provisional_fee_cents.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-NOSHOW-1", hourly_rate_cents=800)
    advance_clock_to("2026-07-17T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-17T09:00:00.000Z", "2026-07-17T10:00:00.000Z",
    )
    provisional = confirmed["provisional_fee_cents"]
    advance_clock_to("2026-07-17T10:30:00.000Z")
    run_sweep()
    post = get_reservation(confirmed["id"])
    assert post["status"] == "NO_SHOW"
    assert post["final_fee_cents"] == provisional, (
        "PRD §3.3 mandates final_fee_cents == provisional_fee_cents on NO_SHOW"
    )


def test_check_in_outside_grace_window_rejected(api, admin_headers):
    """PRD §3.3: "Four preconditions must hold: the reservation must be in
    `CONFIRMED`, the member's `AccessBadge` must be `ACTIVE`, the tenant's
    `access_posture` must be `OPEN` or `RESTRICTED` (not `FROZEN`), and the current
    clock must lie within the 15-minute early-entry grace window before
    `start_at` through the reservation's `end_at` (exclusive)."

    Claim: CHECK_IN more than 15 minutes before start_at must be rejected.
    (The PRD does not name a specific error_id for this precondition violation;
    we assert only that the server rejects it — the framework's behaviour of
    returning a 4xx is what PRD requires.)
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION", code="WS-GRACE-1")
    advance_clock_to("2026-07-18T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-07-18T09:00:00.000Z", "2026-07-18T10:00:00.000Z",
    )
    # Clock is at 07:00, start_at is 09:00 → 2 hours early, outside 15-min grace.
    headers = make_tenant_member_headers(member["id"])
    res = api.create_access_event(
        create_access_event_payload(
            kind="CHECK_IN", reservation_id=confirmed["id"], badge_id=badge["id"]
        ),
        headers,
    )
    assert res.status_code >= 400 and res.status_code < 500, (
        "PRD §3.3 prohibits CHECK_IN more than 15 minutes before start_at"
    )
