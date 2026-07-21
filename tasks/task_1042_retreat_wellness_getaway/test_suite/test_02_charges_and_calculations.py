"""Charge breakdown, tiered discounts, per-line tax rounding, and add-on snapshots."""
from test_helpers import (
    validate_success, ApiErrorId, TEST_USERS,
    set_clock, setup_published_retreat, setup_booking, new_guest, new_addon,
    attach_addon,
)
from test_helpers.constants import DEFAULT_CLOCK, PARTY2_BASE150000
from test_helpers.factories import create_booking_payload
from test_helpers.test_users import make_guest_headers

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / booking_total_nonlinear_tiered_mode_a
# ---------------------------------------------------------------------------
def test_total_charge_party4_private_room_with_addon_and_diet(api):
    """PRD §3.2: "The `subtotal_cents` is the per-person base price multiplied by the party size, plus the chosen room's `tier_delta_cents`, plus the sum of the snapshotted prices of every attached add-on."
    PRD §3.2: "parties of four or more receive a fifteen percent discount, parties of two
    or three receive an eight percent discount, and a solo party receives no discount."
    PRD §3.2: "The pre-tax `total_cents` is the subtotal minus the discount plus the special-diet surcharge."

    Design: Difficulty/combinatorial_formula/booking_total_nonlinear_tiered_mode_a
    """
    base = setup_published_retreat(
        api, retreat_overrides={"base_price_cents": 150000},
        room_overrides={"tier": "PRIVATE", "tier_delta_cents": 40000, "bed_count": 4, "label": "Suite"},
    )
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    addon = new_addon(api, name="Deep Tissue", category="SPA", price_cents=25000)
    payload = create_booking_payload(
        base["retreat"]["id"], guest["id"], base["room"]["id"], 4, base["version"],
        has_special_diet=True)
    booking = validate_success(api.create_booking(payload, gh), 201)
    attach_addon(api, booking["id"], addon["id"], gh)

    data = validate_success(api.get_booking(booking["id"], gh), 200)
    assert data["subtotal_cents"] == 665000
    assert data["group_discount_pct"] == 0.15
    assert data["discount_cents"] == 99750
    assert data["special_diet_surcharge_cents"] == 5000
    assert data["total_cents"] == 570250


def test_solo_party_receives_no_group_discount(api):
    """PRD §3.2: "parties of four or more receive a fifteen percent discount, parties of
    two or three receive an eight percent discount, and a solo party receives no discount."

    Design: Difficulty/combinatorial_formula/booking_total_nonlinear_tiered_mode_a
    """
    ctx = setup_booking(api, party_size=1, retreat_overrides={"base_price_cents": 150000})
    data = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert data["group_discount_pct"] == 0.00
    assert data["discount_cents"] == 0
    assert data["subtotal_cents"] == 150000
    assert data["total_cents"] == 150000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / booking_tax_per_line_rounding_mode_b
# ---------------------------------------------------------------------------
def test_tax_computed_per_line_then_summed(api):
    """PRD §2.6: "booking tax is computed by rounding the tax on each pre-discount line item
    individually and then summing those rounded per-line amounts. Rounding the summed base
    and then taxing it can differ by a cent, so the per-line-then-sum order is mandatory."
    PRD §3.2: "taxes each line at eight and one-half percent, rounds each line's tax half up to a whole cent, and sums those rounded amounts to produce `tax_cents`."

    Design: Difficulty/combinatorial_formula/booking_tax_per_line_rounding_mode_b
    """
    base = setup_published_retreat(
        api, retreat_overrides={"base_price_cents": 202},
        room_overrides={"tier_delta_cents": 202, "bed_count": 4},
    )
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    addon = new_addon(api, name="Box Lunch", category="MEAL", price_cents=202)
    payload = create_booking_payload(
        base["retreat"]["id"], guest["id"], base["room"]["id"], 1, base["version"])
    booking = validate_success(api.create_booking(payload, gh), 201)
    attach_addon(api, booking["id"], addon["id"], gh)

    data = validate_success(api.get_booking(booking["id"], gh), 200)
    assert data["subtotal_cents"] == 606
    assert data["tax_cents"] == 51  # round(17.17)*3, NOT round(51.51)=52


def test_grand_total_and_deposit_split_from_per_line_tax(api):
    """PRD §3.2: "The grand_total_cents is the pre-tax total plus that tax ... The
    deposit_cents is thirty percent of the grand total, rounded half up, and the
    balance_due_cents is the grand total minus the deposit."

    Design: Difficulty/combinatorial_formula/booking_tax_per_line_rounding_mode_b
    """
    base = setup_published_retreat(
        api, retreat_overrides={"base_price_cents": 202},
        room_overrides={"tier_delta_cents": 202, "bed_count": 4},
    )
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    addon = new_addon(api, name="Box Lunch", category="MEAL", price_cents=202)
    payload = create_booking_payload(
        base["retreat"]["id"], guest["id"], base["room"]["id"], 1, base["version"])
    booking = validate_success(api.create_booking(payload, gh), 201)
    attach_addon(api, booking["id"], addon["id"], gh)

    data = validate_success(api.get_booking(booking["id"], gh), 200)
    assert data["grand_total_cents"] == 657   # 606 + 51
    assert data["deposit_cents"] == 197       # round(657 * 0.30) = round(197.1)
    assert data["balance_due_cents"] == 460   # 657 - 197


# ---------------------------------------------------------------------------
# Corner: calculations / corner_deposit_and_balance_computed_party2
# ---------------------------------------------------------------------------
def test_deposit_and_balance_computed_for_party_two(api):
    """PRD §3.2: "The `deposit_cents` is thirty percent of the grand total, rounded half up, and the `balance_due_cents` is the grand total minus the deposit."

    Design: Corner/calculations/corner_deposit_and_balance_computed_party2
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    data = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert data["total_cents"] == PARTY2_BASE150000["total_cents"]
    assert data["tax_cents"] == PARTY2_BASE150000["tax_cents"]
    assert data["grand_total_cents"] == PARTY2_BASE150000["grand_total_cents"]
    assert data["deposit_cents"] == PARTY2_BASE150000["deposit_cents"]
    assert data["balance_due_cents"] == PARTY2_BASE150000["balance_due_cents"]


# ---------------------------------------------------------------------------
# Corner: cross_cutting / corner_addon_price_snapshot_immune_to_edit
# ---------------------------------------------------------------------------
def test_addon_attach_snapshots_price(api):
    """PRD §3.8: "At attach time the server snapshots the add-on's current `price_cents` into the link's `price_cents_snapshot`, so later edits to the catalog price never disturb an existing booking."

    Design: Corner/cross_cutting/corner_addon_price_snapshot_immune_to_edit
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    addon = new_addon(api, name="Massage", category="SPA", price_cents=25000)
    resp = api.create_booking_addon(
        {"booking_id": ctx["booking"]["id"], "addon_id": addon["id"]}, gh)
    link = validate_success(resp, 201)
    assert link["price_cents_snapshot"] == 25000
