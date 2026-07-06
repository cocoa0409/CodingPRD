"""Ticket pricing and group-deposit calculations.

Covers the four-step ticket-pricing sequence (age tier, pass discount, resident
discount, single rounding), the group-deposit tiered per-head computation, and
the add-on round-per-unit-then-multiply order.
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    make_guest_patron_headers,
    make_group_host_headers,
    create_ticket_payload,
    create_add_on_payload,
    create_group_reservation_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty/dual_variant_calc/ticket_pricing_walkup_vs_pass_redeemed
# ===========================================================================

def _make_resident_gold_pass_holder():
    """Park with resident prefix 9001, a resident patron, a GOLD pass."""
    state = fx.setup_pass_holder(
        clock="2026-03-02T09:00:00Z", tier="GOLD",
        resident_zip_prefixes=["9001"], patron_zip="90011",
        block_starts="2026-03-02T10:00:00Z", block_ends="2026-03-02T12:00:00Z",
    )
    return state


def test_walkup_resident_adult_price_excludes_pass_discount(api):
    """PRD §3.4: "A walk-up ticket with no `season_pass_id` skips the pass-discount
    step entirely, so only the resident 5% can apply."
    PRD §3.4: "otherwise (ages 13 through 64) the base is 3500 cents."

    Design: Difficulty/dual_variant_calc/ticket_pricing_walkup_vs_pass_redeemed
    """
    state = _make_resident_gold_pass_holder()
    patron = state["patron"]
    payload = create_ticket_payload(
        park_id=state["park"]["id"], time_block_id=state["block"]["id"],
        holder_patron_id=patron["id"], rider_height_cm=175, rider_age_years=30,
    )
    data = validate_success(api.create_ticket(payload, make_guest_patron_headers(patron["id"])), 201)
    # 3500 * 0.95 (resident only) = 3325
    assert data["base_price_cents"] == 3325, f"walkup resident adult expected 3325, got {data['base_price_cents']}"
    assert data["is_resident"] is True


def test_gold_pass_redeemed_resident_adult_stacks_pass_and_resident(api):
    """PRD §3.4: "if the ticket was issued via a season pass, multiply that factor by one minus the
    pass discount — 0.10 for a `SILVER` pass, 0.25 for a `GOLD` pass, or 0.40 for a
    `RESIDENT_GOLD` pass."
    PRD §3.4: "the resident 5% stacks on top of the pass discount except when the pass is already
    `RESIDENT_GOLD`, in which case the resident discount is not applied."

    Design: Difficulty/dual_variant_calc/ticket_pricing_walkup_vs_pass_redeemed
    """
    state = _make_resident_gold_pass_holder()
    patron = state["patron"]
    payload = create_ticket_payload(
        park_id=state["park"]["id"], time_block_id=state["block"]["id"],
        holder_patron_id=patron["id"], rider_height_cm=175, rider_age_years=30,
        season_pass_id=state["season_pass"]["id"],
    )
    data = validate_success(api.create_ticket(payload, make_guest_patron_headers(patron["id"])), 201)
    # 3500 * 0.75 * 0.95 = 2493.75 -> round_half_up -> 2494
    assert data["base_price_cents"] == 2494, f"GOLD resident adult expected 2494, got {data['base_price_cents']}"


# ===========================================================================
# Difficulty/dual_variant_calc/group_deposit_shared_floor_vs_exclusive_flat
# ===========================================================================

def test_shared_seats_small_party_hits_floor_deposit(api):
    """PRD §3.7: "For a shared-seats party the deposit is the larger of the seats
    subtotal and a floor of 8000 cents."
    PRD §3.7: "a party of 5 or fewer bills at 3000 cents per head".

    Design: Difficulty/dual_variant_calc/group_deposit_shared_floor_vs_exclusive_flat
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=10,
                            block_starts="2026-03-05T10:00:00Z", block_ends="2026-03-05T12:00:00Z",
                            clock="2026-03-05T09:00:00Z")
    host_id = g["host"]["id"]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="SHARED_SEATS", party_size=2)
    held = fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    # 3000 * 2 = 6000 < 8000 floor -> 8000
    assert held["deposit_cents"] == 8000, f"shared party_size 2 expected 8000 floor, got {held['deposit_cents']}"


def test_exclusive_lane_small_party_adds_flat_to_seats(api):
    """PRD §3.7: "For an exclusive-lane party the deposit is the seats subtotal
    plus a flat 20000 cents exclusive-lane charge."
    PRD §3.7: "a party of 5 or fewer bills at 3000 cents per head".

    Design: Difficulty/dual_variant_calc/group_deposit_shared_floor_vs_exclusive_flat
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=10,
                            block_starts="2026-03-05T10:00:00Z", block_ends="2026-03-05T12:00:00Z",
                            clock="2026-03-05T09:00:00Z")
    host_id = g["host"]["id"]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="EXCLUSIVE_LANE", party_size=2,
                                      lane_id=g["lanes"][1]["id"])
    held = fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    # 3000 * 2 + 20000 = 26000
    assert held["deposit_cents"] == 26000, f"exclusive party_size 2 expected 26000, got {held['deposit_cents']}"


# ===========================================================================
# Difficulty/combinatorial_formula/ticket_pricing_nested_tier_and_stacked_discounts_mode_a
# ===========================================================================

def test_senior_resident_gold_suppresses_resident_stack(api):
    """PRD §3.4: "otherwise if `rider_age_years` is at least 65, the base is 2000 cents".
    PRD §3.4: "the resident 5% stacks on top of the pass discount except when the pass is already
    `RESIDENT_GOLD`, in which case the resident discount is not applied."

    Design: Difficulty/combinatorial_formula/ticket_pricing_nested_tier_and_stacked_discounts_mode_a
    """
    state = fx.setup_pass_holder(
        clock="2026-03-03T09:00:00Z", tier="RESIDENT_GOLD",
        resident_zip_prefixes=["8002"], patron_zip="80021",
        block_starts="2026-03-03T10:00:00Z", block_ends="2026-03-03T12:00:00Z",
    )
    patron = state["patron"]
    payload = create_ticket_payload(
        park_id=state["park"]["id"], time_block_id=state["block"]["id"],
        holder_patron_id=patron["id"], rider_height_cm=170, rider_age_years=70,
        season_pass_id=state["season_pass"]["id"],
    )
    data = validate_success(api.create_ticket(payload, make_guest_patron_headers(patron["id"])), 201)
    # senior base 2000 * 0.60 (RESIDENT_GOLD) with resident 5% suppressed = 1200
    assert data["base_price_cents"] == 1200, f"senior RESIDENT_GOLD expected 1200, got {data['base_price_cents']}"
    assert data["is_resident"] is True


def test_resident_gold_pricing_distinct_from_naive_stack(api):
    """PRD §3.4: "the resident 5% stacks on top of the pass discount except when the pass is already
    `RESIDENT_GOLD`, in which case the resident discount is not applied."

    Design: Difficulty/combinatorial_formula/ticket_pricing_nested_tier_and_stacked_discounts_mode_a
    """
    state = fx.setup_pass_holder(
        clock="2026-03-03T09:00:00Z", tier="RESIDENT_GOLD",
        resident_zip_prefixes=["8002"], patron_zip="80021",
        block_starts="2026-03-03T10:00:00Z", block_ends="2026-03-03T12:00:00Z",
    )
    patron = state["patron"]
    payload = create_ticket_payload(
        park_id=state["park"]["id"], time_block_id=state["block"]["id"],
        holder_patron_id=patron["id"], rider_height_cm=170, rider_age_years=70,
        season_pass_id=state["season_pass"]["id"],
    )
    data = validate_success(api.create_ticket(payload, make_guest_patron_headers(patron["id"])), 201)
    # A naive resident-stack would give 2000*0.60*0.95 = 1140; the pinned rule forbids it.
    assert data["base_price_cents"] == 1200
    assert data["base_price_cents"] != 1140, "resident 5% must NOT stack onto RESIDENT_GOLD"


# ===========================================================================
# Difficulty/combinatorial_formula/addon_line_total_round_per_unit_then_multiply_mode_b
# ===========================================================================

def test_gold_food_addon_rounds_per_unit_before_multiply(api):
    """PRD §3.8: "If the linked ticket's holder has an `ACTIVE` `GOLD` or `RESIDENT_GOLD` season pass
    and the `category` is `FOOD`, the per-unit price is multiplied by one minus 0.15."
    PRD §3.8: "Round that discounted per-unit price half up to whole cents first, then multiply the
    rounded per-unit amount by `quantity` to get `line_total_cents`."

    Design: Difficulty/combinatorial_formula/addon_line_total_round_per_unit_then_multiply_mode_b
    """
    state = fx.setup_pass_holder(
        clock="2026-03-04T09:00:00Z", tier="GOLD",
        block_starts="2026-03-04T10:00:00Z", block_ends="2026-03-04T12:00:00Z",
    )
    patron = state["patron"]
    ticket = fx.create_ticket(state["park"]["id"], state["block"]["id"], patron["id"],
                              season_pass_id=state["season_pass"]["id"])
    payload = create_add_on_payload(park_id=state["park"]["id"], ticket_id=ticket["id"],
                                    category="FOOD", unit_price_cents=199, quantity=4)
    data = validate_success(api.create_add_on(payload, make_guest_patron_headers(patron["id"])), 201)
    # 199*0.85 = 169.15 -> round per unit -> 169; *4 = 676
    assert data["line_total_cents"] == 676, f"GOLD FOOD 199x4 expected 676, got {data['line_total_cents']}"


def test_gold_food_addon_not_677_from_multiply_then_round(api):
    """PRD §3.8: "The rounding happens once, per unit, before the multiplication —
    never after — so the final product is exact."

    Design: Difficulty/combinatorial_formula/addon_line_total_round_per_unit_then_multiply_mode_b
    """
    state = fx.setup_pass_holder(
        clock="2026-03-04T09:00:00Z", tier="GOLD",
        block_starts="2026-03-04T10:00:00Z", block_ends="2026-03-04T12:00:00Z",
    )
    patron = state["patron"]
    ticket = fx.create_ticket(state["park"]["id"], state["block"]["id"], patron["id"],
                              season_pass_id=state["season_pass"]["id"])
    payload = create_add_on_payload(park_id=state["park"]["id"], ticket_id=ticket["id"],
                                    category="FOOD", unit_price_cents=199, quantity=4)
    data = validate_success(api.create_add_on(payload, make_guest_patron_headers(patron["id"])), 201)
    # multiply-then-round would yield 169.15*4 = 676.6 -> 677; pinned order forbids this.
    assert data["line_total_cents"] != 677, "must round per-unit first, not multiply-then-round"
    assert data["line_total_cents"] == 676


# ===========================================================================
# Corner/calculations/addon_no_discount_when_not_eligible_plain_multiply
# ===========================================================================

def test_rental_upgrade_addon_no_discount_plain_multiply(api):
    """PRD §3.8: "Otherwise the per-unit price is unchanged."
    PRD §3.8: "multiply the rounded per-unit amount by `quantity` to get `line_total_cents`."

    Design: Corner/calculations/addon_no_discount_when_not_eligible_plain_multiply
    """
    # Non-resident patron, no pass, RENTAL_UPGRADE category -> no discount branch.
    fx.set_clock("2026-03-28T09:00:00Z")
    park = fx.create_park(name="Plain", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90007")
    block = fx.create_time_block(park["id"], starts_at="2026-03-28T10:00:00Z", ends_at="2026-03-28T12:00:00Z")
    ticket = fx.create_ticket(park["id"], block["id"], patron["id"])
    payload = create_add_on_payload(park_id=park["id"], ticket_id=ticket["id"],
                                    category="RENTAL_UPGRADE", unit_price_cents=333, quantity=3)
    data = validate_success(api.create_add_on(payload, make_guest_patron_headers(patron["id"])), 201)
    # 333 * 3 = 999 (no discount)
    assert data["line_total_cents"] == 999, f"RENTAL_UPGRADE 333x3 expected 999, got {data['line_total_cents']}"


# ===========================================================================
# Corner/calculations/group_deposit_tier_boundary_party_size_5_vs_6
# ===========================================================================

def test_group_deposit_party_size_5_bills_tier1_flat(api):
    """PRD §3.7: "the **whole** party bills at the tier its size falls into, not marginally across
    tier boundaries: a party of 5 or fewer bills at 3000 cents per head".

    Design: Corner/calculations/group_deposit_tier_boundary_party_size_5_vs_6
    """
    g = fx.setup_group_park(num_lanes=1, lane_capacity=20,
                            block_starts="2026-03-29T10:00:00Z", block_ends="2026-03-29T12:00:00Z",
                            clock="2026-03-29T09:00:00Z")
    host_id = g["host"]["id"]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="SHARED_SEATS", party_size=5)
    held = fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    # 3000 * 5 = 15000 (TIER1, flat per-head)
    assert held["deposit_cents"] == 15000, f"shared party_size 5 expected 15000, got {held['deposit_cents']}"
