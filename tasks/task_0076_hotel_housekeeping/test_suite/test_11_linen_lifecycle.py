"""Linen lifecycle: creation, scheduled-interval boundary, laundry
hand-off, return-quantity invariant, and resolution (PRD §3.12).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MINUTES_PER_DAY,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_linen_conservation_invariant,
    assert_linen_movement,
    create_linen_movement_payload,
    laundry_return_payload,
    make_housekeeper_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    advance_clock,
    create_housekeeper_on_shift,
    create_linen_movement,
    create_linen_type,
    create_room,
    handover_linen,
    setup_linen_movement_at_handover,
)


# ===========================================================================
# Scheduled-interval boundary (PRD §3.12)
# ===========================================================================
def test_scheduled_replacement_before_interval_rejected(api):
    """PRD §3.12: "Creating a movement under a SCHEDULED policy before
    the scheduled interval has elapsed is rejected with
    ERR_LINEN_REPLACEMENT_NOT_DUE."

    Boundary: elapsed=2 < 3 must reject.
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(
        replacement_policy="SCHEDULED", scheduled_interval_days=3,
    )
    # First movement seeds a prior baseline; advance through the full
    # lifecycle so a "last movement" exists.
    seed = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=2,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    handover_linen(seed["id"], hk["id"])
    api.laundry_return_event(
        laundry_return_payload(seed["id"], 2, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    # Advance 2 days (less than 3-day interval).
    advance_clock(2 * MINUTES_PER_DAY)
    payload = create_linen_movement_payload(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=1,
    )
    res = api.create_linen_movement(
        payload, make_housekeeper_headers(hk["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LINEN_REPLACEMENT_NOT_DUE.value)


def test_scheduled_replacement_at_exact_interval_succeeds(api):
    """PRD §3.12: "replacement is required when that elapsed-days count
    is at least scheduled_interval_days. Zero elapsed days never
    triggers a scheduled replacement; the boundary is inclusive on
    the upper side, not strict-greater."

    Boundary: elapsed=3 == 3 must succeed.
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(
        replacement_policy="SCHEDULED", scheduled_interval_days=3,
    )
    seed = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=2,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    handover_linen(seed["id"], hk["id"])
    api.laundry_return_event(
        laundry_return_payload(seed["id"], 2, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    # Advance exactly 3 days (boundary).
    advance_clock(3 * MINUTES_PER_DAY)
    payload = create_linen_movement_payload(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=1,
    )
    res = api.create_linen_movement(
        payload, make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert_linen_movement(data)
    assert data["status"] == "COLLECTED"


# ===========================================================================
# Handover (PRD §3.12)
# ===========================================================================
def test_handover_copies_collected_to_sent(api):
    """PRD §3.12: "The housekeeper then hands off the collected linen
    to laundry, which advances the movement to SENT_TO_LAUNDRY and
    copies collected_quantity into sent_to_laundry_quantity."
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(replacement_policy="PER_STAY")
    movement = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=7,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    res = api.handover_laundry(
        movement["id"], make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res)
    assert data["status"] == "SENT_TO_LAUNDRY"
    assert data["sent_to_laundry_quantity"] == 7


def test_handover_with_zero_collected_quantity_rejected(api):
    """PRD §3.12: "hand-off requires collected_quantity strictly
    greater than zero." → ERR_MOVEMENT_NOT_COLLECTED is the state
    error; PRD §5 lists this id explicitly for the COLLECTED guard.
    However, PRD §3.12 names the precondition as a structural guard;
    accept either MOVEMENT_NOT_COLLECTED or INVALID_REQUEST.
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(replacement_policy="PER_STAY")
    movement = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=0,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    res = api.handover_laundry(
        movement["id"], make_housekeeper_headers(hk["id"]),
    )
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_MOVEMENT_NOT_COLLECTED.value,
        ApiErrorId.ERR_INVALID_REQUEST.value,
    ])


# ===========================================================================
# Laundry return invariant (PRD §3.12)
# ===========================================================================
def test_laundry_return_matched_quantity_succeeds(api):
    """PRD §3.12: "the server enforces the invariant that
    returned_quantity plus loss_quantity plus damage_quantity equals
    sent_to_laundry_quantity."

    Claim: 7 + 2 + 1 == 10 is accepted; the movement records the
    distribution.
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(movement["id"], 7, 2, 1),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["returned_quantity"] == 7
    assert data["loss_quantity"] == 2
    assert data["damage_quantity"] == 1
    assert_linen_conservation_invariant(data)


def test_laundry_return_mismatched_quantity_rejected(api):
    """PRD §3.12: "otherwise the event is rejected with
    ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH."
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(movement["id"], 7, 2, 0),  # 9 != 10
        TEST_USERS["system_integration_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH.value,
    )


def test_laundry_return_all_returned_advances_to_resolved(api):
    """PRD §3.12: "if loss_quantity plus damage_quantity is strictly
    greater than zero, the movement transitions further to
    LOSS_REPORTED, otherwise it transitions automatically to
    RESOLVED."

    Claim: 10 returned, 0 loss, 0 damage → RESOLVED.
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(movement["id"], 10, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "RESOLVED"


def test_laundry_return_with_loss_or_damage_enters_loss_reported(api):
    """PRD §3.12: "if loss_quantity plus damage_quantity is strictly
    greater than zero, the movement transitions further to
    LOSS_REPORTED."
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(movement["id"], 7, 2, 1),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "LOSS_REPORTED"


# ===========================================================================
# Resolve loss/damage and folio charge (PRD §3.12)
# ===========================================================================
def test_resolve_loss_damage_computes_folio_charge(api):
    """PRD §3.12: "the server computes folio_charge_cents as
    loss_quantity plus damage_quantity multiplied by the linen type's
    replacement_cost_cents, freezes that field, advances the movement
    to RESOLVED."

    Setup: replacement_cost_cents=2000, loss=2, damage=1 →
    folio_charge_cents = 3 * 2000 = 6000.
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    # Inject loss/damage:
    api.laundry_return_event(
        laundry_return_payload(movement["id"], 7, 2, 1),
        TEST_USERS["system_integration_headers"],
    )
    res = api.resolve_linen_loss_damage(
        movement["id"], TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "RESOLVED"
    assert data["folio_charge_cents"] == 3 * 2000  # 6000


def test_resolve_non_loss_reported_rejected(api):
    """PRD §5: "Operation requires LinenMovement.status ==
    LOSS_REPORTED" → ERR_MOVEMENT_NOT_LOSS_REPORTED.
    """
    room, hk, lt, movement = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    # Don't trigger loss/damage; movement is still SENT_TO_LAUNDRY.
    res = api.resolve_linen_loss_damage(
        movement["id"], TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_MOVEMENT_NOT_LOSS_REPORTED.value)
