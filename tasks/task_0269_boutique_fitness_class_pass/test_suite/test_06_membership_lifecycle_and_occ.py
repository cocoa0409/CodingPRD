"""Membership freeze/unfreeze cycle and expiry extension, terminal-state lockdown,
invalid-transition guards, the check-in lead-time window, and the two OCC-guarded
writes. Translates the relevant corner state_machines / validations instances and
the cross_cutting_complexity_layers OCC instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_network, setup_member_with_membership, create_published_session, reserve,
    get_membership, get_session, set_clock, api_client, make_member_headers, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


def test_freeze_then_unfreeze_extends_expiry(api):
    """PRD §3.3: "The frozen span is computed as the number of whole days between
    `frozen_at` and the current clock, rounded up to the next whole day, and then capped
    so that `freeze_days_used` plus this span never exceeds the plan's `freeze_max_days`.
    That capped span is added to `freeze_days_used`, and `expires_at` is advanced by the
    same capped number of days".

    Design: Corner/state_machines/membership_freeze_unfreeze_extends_expiry
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly", "price_cents": 8000, "grant_credits": 20, "validity_days": 30,
        "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # ACTIVE captured 2026-06-01 -> expires 2026-07-01.
    mv0 = membership["version"]
    set_clock("2026-06-06T00:00:00Z")
    validate_success(api.freeze_membership(
        membership["id"], {"expected_membership_version": mv0}, make_member_headers(member["id"])), 200)
    set_clock("2026-06-13T00:00:00Z")  # 7 frozen days

    unfrozen = validate_success(api.unfreeze_membership(membership["id"], make_member_headers(member["id"])), 200)
    assert unfrozen["status"] == "ACTIVE"
    assert unfrozen["freeze_days_used"] == 7, f"expected 7, got {unfrozen['freeze_days_used']}"
    assert unfrozen["expires_at"] == "2026-07-08T00:00:00Z" or unfrozen["expires_at"].startswith("2026-07-08"), (
        f"expected expiry extended to 2026-07-08, got {unfrozen['expires_at']}")


def test_cancelled_membership_cannot_freeze(api):
    """PRD §2.9: "if the targeted resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE`. This is the
    default state error for transitions such as freezing a membership that is not
    `ACTIVE`".
    PRD §3.4: "`EXPIRED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/terminal_membership_cancelled_cannot_freeze
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly", "price_cents": 8000, "grant_credits": 20, "validity_days": 30,
        "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    cancelled = validate_success(api.cancel_membership(membership["id"], make_member_headers(member["id"])), 200)

    res = api.freeze_membership(
        membership["id"], {"expected_membership_version": cancelled["version"]},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_publish_already_open_session_invalid_state(api):
    """PRD §2.9: "if the targeted resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE`. This is the
    default state error for transitions such as ... publishing a session that is not
    `SCHEDULED`".

    Design: Corner/state_machines/publish_already_open_session_returns_invalid_state
    """
    net = setup_network()
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    assert session["status"] == "OPEN"
    res = api.publish_session(session["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_released_reservation_invalid_state(api):
    """PRD §2.9: "if the targeted resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "tracks seat holding through `WAITLISTED`, `BOOKED`, and the terminal
    `RELEASED`."

    Design: Corner/state_machines/cancel_reservation_already_released_returns_invalid_state
    """
    set_clock("2026-06-25T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-07-01T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], member["id"], membership["id"])
    validate_success(api.cancel_reservation(r1["id"], make_member_headers(member["id"])), 200)

    res = api.cancel_reservation(r1["id"], make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    # The first (early) cancel already refunded; a rejected second cancel must not double-refund.
    assert get_membership(membership["id"], member["id"])["credit_balance"] == 20


def test_check_in_before_lead_window_rejected(api):
    """PRD §3.7: "the current clock is at or after the session's `starts_at` minus 2
    hours; a check-in attempted before that lead time is rejected with
    `ERR_INVALID_CANCEL_WINDOW`."

    Design: Corner/validations/error_invalid_cancel_window_early_checkin
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], member["id"], membership["id"])
    set_clock("2026-06-10T00:00:00Z")  # well before the 08:00 check-in window

    res = api.check_in_reservation(r1["id"], MANAGER)
    validate_error(res, "ERR_INVALID_CANCEL_WINDOW")


def test_stale_session_version_on_second_reservation_rejected(api):
    """PRD §2.6: "The check is applied after the session has been confirmed bookable: if
    `expected_session_version` does not equal the session's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_reservation
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    s_v_pre = get_session(session["id"])["version"]

    # First booking succeeds, bumping the session version.
    validate_success(api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": s_v_pre},
        make_member_headers(m1["id"])), 201)
    # Second still carries the now-stale s_v_pre.
    res = api.create_reservation(
        session["id"], {"membership_id": sub2["id"], "expected_session_version": s_v_pre},
        make_member_headers(m2["id"]))
    validate_error(res, "ERR_STALE_VERSION")
    assert get_session(session["id"])["booked_count"] == 1, "stale second booking took no seat"


def test_freeze_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.3: "On a successful freeze the membership moves `ACTIVE → FROZEN`,
    `frozen_at` is set to the current clock".
    PRD §2.4: "The `version` is an integer that begins at its initial value when the
    resource is created and increments by one on every mutation".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_membership_version_freeze_succeeds_and_bumps
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly", "price_cents": 8000, "grant_credits": 20, "validity_days": 30,
        "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    mv = membership["version"]
    set_clock("2026-06-05T00:00:00Z")

    frozen = validate_success(api.freeze_membership(
        membership["id"], {"expected_membership_version": mv}, make_member_headers(member["id"])), 200)
    assert frozen["status"] == "FROZEN"
    assert frozen["version"] == mv + 1, f"freeze must bump version from {mv} to {mv + 1}, got {frozen['version']}"
