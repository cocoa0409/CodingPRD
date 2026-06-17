"""Cascades and the deposit ledger: booking-cancel three-hop release, damaged-
return two-hop maintenance + forfeit, deposit conservation, and the derived
available-count reconciliation.

Queue A (Difficulty) — transitive_cascade, compensating_invariant,
dual_variant_calc (rental deposit split).
Queue B (Corner) — cross_cutting_complexity_layers (derived_field_reconciliation).
"""
import pytest
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_equipment, reserve_rental, check_in_booking,
    create_referee, assign_referee, setup_checked_out_rental,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — transitive_cascade: cancel booking three-hop (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def _setup_confirmed_with_held_vest_rental(deposit=4000):
    arena = create_arena(clock="2026-06-15T09:00:00Z", vest_pool_total=1)
    field = create_field(arena["id"], name="F7", game_mode="LASER_TAG", capacity_max=8)
    unit = create_equipment(arena["id"], unit_type="VEST", asset_tag="V-7", deposit_cents=deposit)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    return arena, field, unit, booking, rental


def test_cancel_booking_cascades_rental_release_and_equipment_available(api):
    """PRD §3.8: "Cancellation runs the full cascade in order: first, every rental for
    the booking that is `HELD` or `CHECKED_OUT` is moved to `RELEASED`; then each of
    those released rentals' equipment units returns to `AVAILABLE`; then the arena's
    `deposit_held_cents` is decremented by each released rental's `deposit_hold_cents`;
    then the arena's equipment available counts are recomputed; ..."

    Design: Difficulty/transitive_cascade/cancel_booking_three_hop_rental_equipment_deposit
    """
    arena, field, unit, booking, rental = _setup_confirmed_with_held_vest_rental(deposit=4000)
    cancelled = validate_success(api.cancel_booking(booking["id"], FD), 200)
    assert cancelled["status"] == "CANCELLED"
    rental_after = validate_success(api.get_rental(rental["id"], FD), 200)
    assert rental_after["status"] == "RELEASED", \
        f"cancel must release the rental (hop1), got {rental_after['status']}"
    unit_after = validate_success(api.get_equipment_unit(unit["id"], AM), 200)
    assert unit_after["status"] == "AVAILABLE", \
        f"released rental's unit must return AVAILABLE (hop2), got {unit_after['status']}"


def test_cancel_booking_cascades_deposit_ledger_credit(api):
    """PRD §3.8: "then the arena's `deposit_held_cents` is decremented by each released
    rental's `deposit_hold_cents`; then the arena's equipment available counts are
    recomputed; ..."

    Design: Difficulty/transitive_cascade/cancel_booking_three_hop_rental_equipment_deposit
    """
    arena, field, unit, booking, rental = _setup_confirmed_with_held_vest_rental(deposit=4000)
    arena_before = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_before["deposit_held_cents"] == 4000, \
        f"held deposit must be 4000 before cancel, got {arena_before['deposit_held_cents']}"
    validate_success(api.cancel_booking(booking["id"], FD), 200)
    arena_after = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_after["deposit_held_cents"] == 0, \
        f"deposit_held must fall to 0 after cancel (hop3), got {arena_after['deposit_held_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — transitive_cascade: damaged return two-hop maintenance + forfeit (two)
# ─────────────────────────────────────────────────────────────────────────────
def test_damaged_return_moves_equipment_to_maintenance(api):
    """PRD §3.4: "the unit returns to `AVAILABLE` when `damage_fee_cents` is zero, but
    moves to `MAINTENANCE` when any damage fee was charged (and its `condition_grade` is
    downgraded one notch on that path, `A` to `B`, `B` to `C`, with `C` staying `C`) ..."

    Design: Difficulty/transitive_cascade/return_damaged_two_hop_equipment_maintenance_ledger
    """
    arena, field, unit, booking, rental = setup_checked_out_rental(
        deposit_cents=6000, unit_type="MARKER", game_mode="PAINTBALL", party_size=6
    )
    returned = validate_success(api.return_rental(rental["id"], {"damage_fee_cents": 1500}, FM), 200)
    assert returned["status"] == "RETURNED"
    unit_after = validate_success(api.get_equipment_unit(unit["id"], AM), 200)
    assert unit_after["status"] == "MAINTENANCE", \
        f"damaged return must move unit to MAINTENANCE (hop1), got {unit_after['status']}"


def test_damaged_return_credits_forfeit_ledger(api):
    """PRD §3.4: "the arena's `deposit_held_cents` falls by the held amount, its
    `deposit_refunded_cents` rises by the refund, and its `deposit_forfeited_cents`
    rises by the forfeit, with the available count reconciled."

    Design: Difficulty/transitive_cascade/return_damaged_two_hop_equipment_maintenance_ledger
    """
    arena, field, unit, booking, rental = setup_checked_out_rental(
        deposit_cents=6000, unit_type="MARKER", game_mode="PAINTBALL", party_size=6
    )
    validate_success(api.return_rental(rental["id"], {"damage_fee_cents": 1500}, FM), 200)
    arena_after = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_after["deposit_forfeited_cents"] == 1500, \
        f"forfeit ledger must hold 1500 (hop2), got {arena_after['deposit_forfeited_cents']}"
    assert arena_after["deposit_refunded_cents"] == 4500, \
        f"refunded ledger must hold 4500, got {arena_after['deposit_refunded_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — dual_variant_calc: rental deposit hold vs final split (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_rental_deposit_hold_pinned_at_reserve(api):
    """PRD §3.4: "On a successful reserve the rental is created in `HELD` status; its
    `deposit_hold_cents` is snapshotted from the unit's `deposit_cents` at that moment
    ..."

    Design: Difficulty/dual_variant_calc/deposit_hold_vs_final_diverge_on_rental
    """
    arena, field, unit, booking, rental = setup_checked_out_rental(
        deposit_cents=5000, unit_type="MARKER", game_mode="PAINTBALL", party_size=6
    )
    assert rental["deposit_hold_cents"] == 5000, \
        f"hold variant must snapshot 5000, got {rental['deposit_hold_cents']}"


def test_rental_deposit_final_split_at_return(api):
    """PRD §3.4: "Settlement is a waterfall: the forfeited amount,
    `deposit_forfeit_cents`, is the smaller of the held deposit and the damage fee
    (damage is drawn from the deposit first); the refunded amount,
    `deposit_refund_cents`, is the held deposit minus that forfeit, which is never
    negative. The two always sum back exactly to `deposit_hold_cents`."

    Design: Difficulty/dual_variant_calc/deposit_hold_vs_final_diverge_on_rental
    """
    arena, field, unit, booking, rental = setup_checked_out_rental(
        deposit_cents=5000, unit_type="MARKER", game_mode="PAINTBALL", party_size=6
    )
    returned = validate_success(api.return_rental(rental["id"], {"damage_fee_cents": 1200}, FM), 200)
    assert returned["deposit_hold_cents"] == 5000
    assert returned["deposit_forfeit_cents"] == 1200, \
        f"final forfeit must be 1200, got {returned['deposit_forfeit_cents']}"
    assert returned["deposit_refund_cents"] == 3800, \
        f"final refund must be 3800, got {returned['deposit_refund_cents']}"
    assert returned["deposit_refund_cents"] + returned["deposit_forfeit_cents"] == 5000


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — compensating_invariant: deposit ledger conserved reserve→release (two)
# ─────────────────────────────────────────────────────────────────────────────
def _setup_held_marker_rental(deposit=3500):
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field = create_field(arena["id"], name="F17", game_mode="LASER_TAG", capacity_max=8)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-17", deposit_cents=deposit)
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    return arena, field, unit, booking, rental


def test_deposit_held_returns_to_zero_after_release(api):
    """PRD §3.4: "Releasing a `HELD` rental moves it to `RELEASED`, returns its unit to
    `AVAILABLE`, lowers the arena's `deposit_held_cents` by the held amount, and
    reconciles the available count; no money is forfeited on a release."

    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_on_reserve_then_release
    """
    arena, field, unit, booking, rental = _setup_held_marker_rental(deposit=3500)
    arena_held = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_held["deposit_held_cents"] == 3500, \
        f"reserve must raise held deposit to 3500, got {arena_held['deposit_held_cents']}"
    released = validate_success(api.release_rental(rental["id"], FD), 200)
    assert released["status"] == "RELEASED"
    arena_after = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_after["deposit_held_cents"] == 0, \
        f"release must restore held deposit to 0, got {arena_after['deposit_held_cents']}"


def test_release_restores_equipment_and_available_count(api):
    """PRD §2.7: "Provisioning a new unit raises the relevant available count; reserving
    a unit lowers it; releasing, returning undamaged, or restoring from maintenance
    raises it again."

    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_on_reserve_then_release
    """
    arena, field, unit, booking, rental = _setup_held_marker_rental(deposit=3500)
    validate_success(api.release_rental(rental["id"], FD), 200)
    unit_after = validate_success(api.get_equipment_unit(unit["id"], AM), 200)
    assert unit_after["status"] == "AVAILABLE", \
        f"released unit must be AVAILABLE, got {unit_after['status']}"
    arena_after = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_after["marker_available_count"] == 1, \
        f"marker_available_count must return to 1 after release, got {arena_after['marker_available_count']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — derived_field_reconciliation: marker available count on reserve
# ─────────────────────────────────────────────────────────────────────────────
def test_derived_marker_available_count_reconciles_on_reserve(api):
    """PRD §2.7: "The live availability counts `marker_available_count` and
    `vest_available_count` are computed: they track how many marker and vest units
    currently sit in `AVAILABLE` status, and they are reconciled on every rental reserve
    and every release or return. Provisioning a new unit raises the relevant available
    count; reserving a unit lowers it; ..."

    Design: Corner/cross_cutting_complexity_layers/derived_marker_available_count_reconciles_on_reserve
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=2)
    field = create_field(arena["id"], name="Fx3", game_mode="LASER_TAG", capacity_max=8)
    unit_a = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-x3a", deposit_cents=2000)
    create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-x3b", deposit_cents=2000)
    arena_two = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_two["marker_available_count"] == 2, \
        f"two provisioned markers must yield count 2, got {arena_two['marker_available_count']}"
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    reserve_rental(arena["id"], booking["id"], unit_a["id"])
    arena_after = validate_success(api.get_arena(arena["id"], AM), 200)
    assert arena_after["marker_available_count"] == 1, \
        f"reserving one marker must reconcile count to 1, got {arena_after['marker_available_count']}"
