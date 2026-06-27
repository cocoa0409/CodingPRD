"""Cross-entity cascades (suspension sweep, cancellation seat release) and
compensating-action invariants (occupied_seat_count, provider panel count).
PRD §3.3, §3.13.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_active_member, setup_sponsored_active_member,
    book_in_person_visit, drive_member_past_due,
    make_member_headers, make_employer_headers, ADMIN,
)


def test_suspension_sweep_three_hop_cascade(api):
    """PRD §3.13: "every `PAST_DUE` membership whose grace window has elapsed (the
    clock has reached or passed `past_due_since` plus the practice's
    `grace_period_days`) is moved to `SUSPENDED` with its full suspension cascade
    (panel recount and cancellation of that member's `BOOKED`/`CHECKED_IN` visits,
    each adjusting the affected slot's `booked_count` and `slot_state`)."

    Design: Difficulty/transitive_cascade/suspension_sweep_three_hop_cascade
    """
    ctx = setup_active_member(practice_overrides={"grace_period_days": 14})
    booked = book_in_person_visit(ctx, "2026-08-10T09:00:00Z", "2026-08-10T09:30:00Z")
    slot_id = booked["slot"]["id"]
    # ACTIVE -> PAST_DUE at rollover, then advance past grace (14 days).
    drive_member_past_due(ctx, rollover_clock="2026-07-01T00:00:00Z",
                          fail_clock="2026-07-20T00:00:00Z")
    get_success_data(api_client.run_suspension_sweep(ADMIN))

    member = validate_success(api_client.get_member(ctx["member"]["id"], ADMIN), 200)
    assert member["membership_status"] == "SUSPENDED"
    visit = validate_success(api_client.get_visit(booked["visit"]["id"], ADMIN), 200)
    assert visit["clinical_status"] == "CANCELLED"
    slot = validate_success(api_client.get_visit_slot(slot_id, ADMIN), 200)
    assert slot["booked_count"] == 0
    assert slot["slot_state"] == "OPEN"


def test_suspension_sweep_cancels_booked_visit_and_frees_slot(api):
    """PRD §3.13: "every `PAST_DUE` membership whose grace window has elapsed (the
    clock has reached or passed `past_due_since` plus the practice's
    `grace_period_days`) is moved to `SUSPENDED` with its full suspension cascade
    (panel recount and cancellation of that member's `BOOKED`/`CHECKED_IN` visits,
    each adjusting the affected slot's `booked_count` and `slot_state`)."

    Design: Difficulty/transitive_cascade/suspension_sweep_three_hop_cascade
    """
    ctx = setup_active_member(practice_overrides={"grace_period_days": 14})
    booked = book_in_person_visit(ctx, "2026-08-12T09:00:00Z", "2026-08-12T09:30:00Z")
    slot_before = validate_success(api_client.get_visit_slot(booked["slot"]["id"], ADMIN), 200)
    assert slot_before["booked_count"] == 1  # cascade precondition
    drive_member_past_due(ctx, rollover_clock="2026-07-01T00:00:00Z",
                          fail_clock="2026-07-20T00:00:00Z")
    get_success_data(api_client.run_suspension_sweep(ADMIN))

    visit = validate_success(api_client.get_visit(booked["visit"]["id"], ADMIN), 200)
    assert visit["clinical_status"] == "CANCELLED"
    slot_after = validate_success(api_client.get_visit_slot(booked["slot"]["id"], ADMIN), 200)
    assert slot_after["booked_count"] == 0


def test_cancel_releases_employer_seat_two_hop_cascade(api):
    """PRD §3.3: "if the membership has a non-null `employer_seat_id`, that seat is
    set to `RELEASED`, its `member_id` is cleared, and the employer's
    `occupied_seat_count` is recomputed."

    Design: Difficulty/transitive_cascade/cancel_releases_seat_two_hop_cascade
    """
    ctx = setup_sponsored_active_member(sponsorship_pct=1.0, plan_type="MONTHLY")
    member_h = make_member_headers(ctx["member"]["id"])
    validate_success(api_client.cancel_member(ctx["member"]["id"], member_h), 200)

    seat = validate_success(api_client.get_employer_seat(
        ctx["seat"]["id"], make_employer_headers(ctx["employer"]["id"])), 200)
    assert seat["seat_status"] == "RELEASED"
    assert seat["member_id"] is None
    employer = validate_success(api_client.get_employer(
        ctx["employer"]["id"], make_employer_headers(ctx["employer"]["id"])), 200)
    assert employer["occupied_seat_count"] == 0


def test_cancel_from_active_clears_seat_member_id(api):
    """PRD §3.3: "if the membership has a non-null `employer_seat_id`, that seat is
    set to `RELEASED`, its `member_id` is cleared, and the employer's
    `occupied_seat_count` is recomputed."

    Design: Difficulty/transitive_cascade/cancel_releases_seat_two_hop_cascade
    """
    ctx = setup_sponsored_active_member(sponsorship_pct=1.0, plan_type="MONTHLY")
    emp_h = make_employer_headers(ctx["employer"]["id"])
    seat_before = validate_success(api_client.get_employer_seat(ctx["seat"]["id"], emp_h), 200)
    assert seat_before["member_id"] == ctx["member"]["id"]  # occupied precondition

    validate_success(api_client.cancel_member(
        ctx["member"]["id"], make_member_headers(ctx["member"]["id"])), 200)

    seat_after = validate_success(api_client.get_employer_seat(ctx["seat"]["id"], emp_h), 200)
    assert seat_after["member_id"] is None
    assert seat_after["seat_status"] == "RELEASED"


def test_seat_occupy_then_cancel_conserves_occupied_seat_count(api):
    """PRD §3.2: "The employer's `occupied_seat_count` is incremented and the
    employer's `version` is incremented by one."
    PRD §3.3: "if the membership has a non-null `employer_seat_id`, that seat is set
    to `RELEASED`, its `member_id` is cleared, and the employer's
    `occupied_seat_count` is recomputed."

    Design: Difficulty/compensating_invariant/seat_occupy_then_cancel_conserves_occupied_seat_count
    """
    ctx = setup_sponsored_active_member(sponsorship_pct=1.0, plan_type="MONTHLY")
    emp_h = make_employer_headers(ctx["employer"]["id"])
    before = validate_success(api_client.get_employer(ctx["employer"]["id"], emp_h), 200)
    assert before["occupied_seat_count"] == 1

    member_h = make_member_headers(ctx["member"]["id"])
    validate_success(api_client.cancel_member(ctx["member"]["id"], member_h), 200)

    after = validate_success(api_client.get_employer(ctx["employer"]["id"], emp_h), 200)
    assert after["occupied_seat_count"] == 0
    seat = validate_success(api_client.get_employer_seat(ctx["seat"]["id"], emp_h), 200)
    assert seat["seat_status"] == "RELEASED"


def test_occupy_raises_occupied_seat_count_forward(api):
    """PRD §3.2: "On success the seat's `seat_status` becomes `OCCUPIED` and its
    `member_id` is set, the member's `Membership` records the `employer_seat_id`,
    and the member's monthly share is recomputed (per §3.7) to reflect the
    employer's sponsorship."
    PRD §3.2: "The employer's `occupied_seat_count` is incremented and the
    employer's `version` is incremented by one."

    Design: Difficulty/compensating_invariant/seat_occupy_then_cancel_conserves_occupied_seat_count
    """
    # The forward leg of the conserved quantity: occupy raises count 0 -> 1 and the
    # seat reads OCCUPIED with member_id set.
    ctx = setup_sponsored_active_member(sponsorship_pct=1.0, plan_type="MONTHLY")
    emp_h = make_employer_headers(ctx["employer"]["id"])
    employer = validate_success(api_client.get_employer(ctx["employer"]["id"], emp_h), 200)
    assert employer["occupied_seat_count"] == 1
    seat = validate_success(api_client.get_employer_seat(ctx["seat"]["id"], emp_h), 200)
    assert seat["seat_status"] == "OCCUPIED"
    assert seat["member_id"] == ctx["member"]["id"]


def test_activate_then_cancel_conserves_provider_panel_count(api):
    """PRD §3.3: "the assigned provider's `active_panel_count` and
    `panel_load_bucket` are recomputed because the newly active member now joins
    the active panel."
    PRD §3.3: "the assigned provider's `active_panel_count` and
    `panel_load_bucket` are recomputed as the member leaves the active panel."

    Design: Difficulty/compensating_invariant/activate_then_cancel_conserves_provider_panel_count
    """
    ctx = setup_active_member()  # activation raised panel count 0 -> 1.
    member_h = make_member_headers(ctx["member"]["id"])
    validate_success(api_client.cancel_member(ctx["member"]["id"], member_h), 200)

    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], ADMIN), 200)
    assert provider["active_panel_count"] == 0
    assert provider["panel_load_bucket"] == "UNDER_TARGET"


def test_activation_raises_provider_panel_count_forward(api):
    """PRD §3.3: "on success the membership's `current_period_start` is set to the
    clock's current instant, `current_period_end` is recomputed, and the assigned
    provider's `active_panel_count` and `panel_load_bucket` are recomputed because
    the newly active member now joins the active panel."

    Design: Difficulty/compensating_invariant/activate_then_cancel_conserves_provider_panel_count
    """
    # The forward leg of the conserved quantity: activation raises count 0 -> 1.
    ctx = setup_active_member()
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], ADMIN), 200)
    assert provider["active_panel_count"] == 1
