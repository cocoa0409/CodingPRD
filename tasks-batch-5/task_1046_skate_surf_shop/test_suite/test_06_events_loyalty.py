"""Loyalty accrual and event registration: tier multiplier + double points + cap,
the ordered registration preconditions, the derived registration_count, and the
event-close and register/cancel conservation cascades.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, get_success_data,
    create_member, create_booked_lesson, create_member_with_points,
    create_open_event, create_event_with_registration,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]


def _complete_lesson_for_points(api, tier, fee_cents, double_points=False):
    member = create_member(api, tier=tier)
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SKATE", fee_cents=fee_cents,
        start_at="2026-07-05T10:00:00Z", end_at="2026-07-05T11:00:00Z", member=member)
    api.confirm_lesson(lesson["id"], SM)
    payload = {"double_points": True} if double_points else None
    api.complete_lesson(lesson["id"], SM, payload)
    return get_success_data(api.get_member(member["id"], SM))


def test_loyalty_team_double_points_earns_360(api):
    """PRD §2.9: "That base is multiplied by the member's tier multiplier — 1 for
    `STANDARD`, 2 for `PRO`, and 3 for `TEAM` — and then doubled again if the
    completing request set its optional `double_points` flag to true (the flag
    defaults to false when omitted)."

    Design: Difficulty/combinatorial_formula/loyalty_earn_tier_multiplier_double_points
    """
    member = _complete_lesson_for_points(api, "TEAM", 6000, double_points=True)
    # floor(6000/100)=60; 60*3*2=360; under the 500 cap.
    assert member["points_balance"] == 360


def test_loyalty_team_double_points_lifetime_matches(api):
    """PRD §2.9: "The earned amount is added to the member's `points_balance` and also
    added to `lifetime_points`, which only ever accumulates and is never decremented."

    Design: Difficulty/combinatorial_formula/loyalty_earn_tier_multiplier_double_points
    """
    member = _complete_lesson_for_points(api, "TEAM", 6000, double_points=True)
    assert member["lifetime_points"] == 360


def test_loyalty_min_cap_applies(api):
    """PRD §2.9: "The earned points are the product of base times multiplier, but
    capped at a maximum of 500 points per transaction; the cap is applied after the
    multiplier, not before."

    Design: Corner/calculations/loyalty_earn_min_cap_applies
    """
    member = _complete_lesson_for_points(api, "STANDARD", 60000, double_points=False)
    # floor(60000/100)=600; *1 = 600; capped at 500.
    assert member["points_balance"] == 500


def test_register_points_exactly_equal_cost_succeeds(api):
    """PRD §3.8: "the member's `points_balance` to be at least the event's
    `entry_points_cost` (else `ERR_INSUFFICIENT_POINTS`)".

    Design: Difficulty/boundary_precision_check/register_points_exactly_equal_cost_allowed
    """
    member = create_member_with_points(api, 300)
    event = create_open_event(api, capacity=5, entry_points_cost=300)
    resp = api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "REGISTERED"


def test_register_points_exactly_equal_cost_debits_to_zero(api):
    """PRD §3.8: "its `points_charged` is set to the event's `entry_points_cost`, that
    many points are debited from the member's `points_balance`, and `registration_count`
    rises by one."

    Design: Difficulty/boundary_precision_check/register_points_exactly_equal_cost_allowed
    """
    member = create_member_with_points(api, 300)
    event = create_open_event(api, capacity=5, entry_points_cost=300)
    api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["points_balance"] == 0


def test_register_insufficient_points(api):
    """PRD §3.8: "the member's `points_balance` to be at least the event's
    `entry_points_cost` (else `ERR_INSUFFICIENT_POINTS`)".

    Design: Corner/errors/register_insufficient_points_returns_error
    """
    member = create_member(api)  # 0 points
    event = create_open_event(api, capacity=5, entry_points_cost=100)
    resp = api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    assert resp.status_code == 402
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_register_duplicate(api):
    """PRD §3.8: "no existing `REGISTERED` registration for the same event and member
    (else `ERR_DUPLICATE_REGISTRATION`)".

    Design: Corner/errors/register_duplicate_returns_duplicate_registration
    """
    event, reg, member = create_event_with_registration(api, capacity=10, entry_points_cost=0)
    resp = api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)


def test_register_event_full(api):
    """PRD §3.8: "the `registration_count` to be strictly below `capacity` (else
    `ERR_EVENT_FULL`)".

    Design: Corner/errors/register_event_full_returns_event_full
    """
    event, reg, member1 = create_event_with_registration(api, capacity=1, entry_points_cost=0)
    member2 = create_member(api)
    resp = api.register_event(event["id"], {"member_id": member2["id"]}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)


def test_register_closed_event_beats_insufficient_points(api):
    """PRD §2.5: "Within event registration specifically, this means a closed-event or
    suspended-member rejection surfaces before a duplicate-registration check, which
    surfaces before the capacity check, which surfaces before the insufficient-points check."

    Design: Difficulty/priority_pair_validation_conflict/register_event_closed_beats_insufficient_points
    """
    member = create_member(api)  # 0 points
    event = create_open_event(api, capacity=5, entry_points_cost=100)
    api.close_event(event["id"], SM)
    resp = api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_EVENT_CLOSED.value)


def test_register_closed_event_precedence_status_409(api):
    """PRD §2.5: "Within event registration specifically, this means a closed-event or
    suspended-member rejection surfaces before a duplicate-registration check, which
    surfaces before the capacity check, which surfaces before the insufficient-points check."

    Design: Difficulty/priority_pair_validation_conflict/register_event_closed_beats_insufficient_points
    """
    member = create_member(api)  # 0 points
    event = create_open_event(api, capacity=5, entry_points_cost=100)
    api.close_event(event["id"], SM)
    resp = api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    # State-level closed-event rejection (409) pre-empts the fiscal points check (402).
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_EVENT_CLOSED.value)


def test_registration_count_incremented(api):
    """PRD §3.8: "An event starts `OPEN` with its `registration_count` at 0; this count
    is a derived tally of `REGISTERED` registrations, incremented on each registration
    and decremented on each registration cancellation."

    Design: Corner/cross_cutting_complexity_layers/registration_count_reconciled_on_register
    """
    member = create_member(api)
    event = create_open_event(api, capacity=5, entry_points_cost=0)
    api.register_event(event["id"], {"member_id": member["id"]}, ASSOC)
    event_after = get_success_data(api.get_event(event["id"], SM))
    assert event_after["registration_count"] == 1


def test_event_close_cancels_registration_refunds_points(api):
    """PRD §2.10: "Closing an event triggers a depth-two cascade: every `REGISTERED`
    registration for the event is cancelled, and each cancellation refunds the member's
    `points_charged` back to their `points_balance` and decrements the event's
    `registration_count`."

    Design: Difficulty/transitive_cascade/event_close_cascade_event_registration_member
    """
    member = create_member_with_points(api, 300)
    event, reg, member = create_event_with_registration(
        api, capacity=5, entry_points_cost=300, member=member)
    close = validate_success(api.close_event(event["id"], SM), 200)
    assert close["status"] == "CLOSED"
    reg_after = get_success_data(api.get_event_registration(reg["id"], SM))
    assert reg_after["status"] == "CANCELLED"
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["points_balance"] == 300


def test_event_close_decrements_registration_count(api):
    """PRD §2.10: "Closing an event triggers a depth-two cascade: every `REGISTERED`
    registration for the event is cancelled, and each cancellation refunds the member's
    `points_charged` back to their `points_balance` and decrements the event's
    `registration_count`."

    Design: Difficulty/transitive_cascade/event_close_cascade_event_registration_member
    """
    member = create_member_with_points(api, 300)
    event, reg, member = create_event_with_registration(
        api, capacity=5, entry_points_cost=300, member=member)
    api.close_event(event["id"], SM)
    event_after = get_success_data(api.get_event(event["id"], SM))
    assert event_after["registration_count"] == 0


def test_register_then_cancel_restores_points(api):
    """PRD §3.8: "A registration may be cancelled by the owning `Member` or a
    `ShopManager` from `REGISTERED`, which refunds exactly the `points_charged` back to
    the member's `points_balance` and decrements the event's `registration_count`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_register_then_cancel
    """
    member = create_member_with_points(api, 300)
    event, reg, member = create_event_with_registration(
        api, capacity=5, entry_points_cost=300, member=member)
    api.cancel_event_registration(reg["id"], SM)
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["points_balance"] == 300


def test_register_then_cancel_count_zero(api):
    """PRD §3.8: "A registration may be cancelled by the owning `Member` or a
    `ShopManager` from `REGISTERED`, which refunds exactly the `points_charged` back to
    the member's `points_balance` and decrements the event's `registration_count`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_register_then_cancel
    """
    member = create_member_with_points(api, 300)
    event, reg, member = create_event_with_registration(
        api, capacity=5, entry_points_cost=300, member=member)
    cancelled = validate_success(api.cancel_event_registration(reg["id"], SM), 200)
    assert cancelled["status"] == "CANCELLED"
    event_after = get_success_data(api.get_event(event["id"], SM))
    assert event_after["registration_count"] == 0
