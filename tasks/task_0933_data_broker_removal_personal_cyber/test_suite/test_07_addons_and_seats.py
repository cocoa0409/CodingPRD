"""Add-on purchase and proration, and the device-seat pool."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_addon, assert_device_seat, assert_seat_conservation,
    assert_cycle_money_arithmetic, assert_same_instant, fixtures as fx,
)


def test_resuming_an_addon_rebinds_its_voided_seats_without_a_cooloff(api):
    """PRD §3.8: "Resuming requires the add-on to be `SUSPENDED` and its account to be
    `ACTIVE`, clears `suspended_at` to null, and — caused by that transition — moves every
    seat of the add-on sitting in `VOIDED` whose member is `ACTIVE` along the edge
    `VOIDED → BOUND`, incrementing each seat's `bind_count` by 1."
    PRD §3.8: "The 72-hour cool-off does **not** apply on that path, because the seat was
    never voluntarily released — its `released_at` is null."

    Design: Corner/state_machines/addon_resume_rebinds_voided_seats_preserving_bind_count
    """
    household = fx.open_household()
    addon, seat = fx.setup_addon_with_seat(household, addon_type="VPN", seats_total=2,
                                           per_seat_fee_cents=300,
                                           device_label="Dana Laptop")
    validate_success(api.suspend_addon(addon["id"], household["owner"]))
    voided = fx.read_seat(seat["id"])
    assert voided["status"] == "VOIDED"
    assert_same_instant(voided["voided_at"], "2026-05-01T00:00:00Z", "voided_at")
    assert voided["bind_count"] == 1
    assert voided["released_at"] is None

    data = validate_success(api.resume_addon(addon["id"], household["owner"]))

    assert_addon(data)
    assert data["status"] == "ACTIVE"
    assert data["suspended_at"] is None
    assert data["seats_bound"] == 1
    assert data["seats_available"] == 1
    assert_seat_conservation(data)

    restored = fx.read_seat(seat["id"])
    assert restored["status"] == "BOUND"
    assert restored["bind_count"] == 2
    assert restored["voided_at"] is None
    assert_same_instant(restored["bound_at"], "2026-05-01T00:00:00Z", "bound_at")


def test_addon_charges_round_up_while_credits_round_down(api):
    """PRD §3.8: "Under the **`SEAT_RELEASED`** variant — used when an add-on moves
    `ACTIVE → SUSPENDED` — the credit is the same product divided by 30 and rounded **down**
    to the whole cent below, and it is added to the open cycle's `addon_credit_cents`."
    PRD §3.8: "Charges round up and credits round down, so a suspend-then-resume round trip
    inside a single cycle is not value-neutral whenever the product is not an exact multiple
    of 30."

    Design: Corner/calculations/addon_proration_ceil_on_add_versus_floor_on_release
    """
    household = fx.open_household(plan=fx.create_solo_plan())
    fx.set_clock("2026-05-11T00:00:00Z")

    addon = fx.buy_addon(household, addon_type="VPN", seats_total=1,
                         per_seat_fee_cents=305)
    # remaining days exclusive = 20; inclusive = 21. 305 * 1 * 21 = 6405;
    # 6405 / 30 = 213.5 exactly, so the charge ceils to 214.
    assert addon["prorated_charge_cents"] == 214

    validate_success(api.suspend_addon(addon["id"], household["owner"]))

    cycle = fx.first_cycle(household)
    assert cycle["addon_charge_cents"] == 214
    # The identical 213.5 floors to 213 on the credit side.
    assert cycle["addon_credit_cents"] == 213
    # 1200 base + 214 - 213 = 1201, which is below the 1500 tier-1 threshold.
    assert cycle["pre_discount_total_cents"] == 1201
    assert cycle["loyalty_discount_cents"] == 0
    assert cycle["total_charged_cents"] == 1201
    assert_cycle_money_arithmetic(cycle)
    assert fx.read_addon(addon["id"])["status"] == "SUSPENDED"


def test_seat_rebinding_is_admitted_at_exactly_seventy_two_hours(api):
    """PRD §3.8: "A released seat carries a derived `rebind_eligible_at`, which is its
    `released_at` advanced by 72 hours and is null while `released_at` is null."
    PRD §3.8: "Rebinding — which supplies a fresh `device_label` — moves
    `RELEASED → BOUND`, and requires the current instant to be at or after
    `rebind_eligible_at` (an **inclusive** boundary: rebinding at exactly 72 hours after
    release is allowed, and one millisecond earlier is rejected with
    `ERR_SEAT_REBIND_COOLOFF`), the add-on to be `ACTIVE`, and at least one seat's worth of
    capacity to remain available."

    Design: Corner/calculations/seat_rebind_cooloff_inclusive_boundary_at_seventy_two_hours
    """
    household = fx.open_household()
    addon, seat = fx.setup_addon_with_seat(household, addon_type="VPN", seats_total=2,
                                           per_seat_fee_cents=300,
                                           device_label="Dana Laptop")
    released = fx.release_seat(seat["id"], household["owner"])
    assert_same_instant(released["released_at"], "2026-05-01T00:00:00Z", "released_at")
    # 2026-05-01T00:00:00Z + 72 hours = 2026-05-04T00:00:00Z.
    assert_same_instant(released["rebind_eligible_at"], "2026-05-04T00:00:00Z",
                        "rebind_eligible_at")

    fx.set_clock("2026-05-03T23:59:59Z")
    validate_error(api.rebind_seat(seat["id"], "Dana Laptop 2", household["owner"]),
                   ApiErrorId.ERR_SEAT_REBIND_COOLOFF.value, 409)
    early = fx.read_seat(seat["id"])
    assert early["status"] == "RELEASED"
    assert early["bind_count"] == 1

    fx.set_clock("2026-05-04T00:00:00Z")
    data = validate_success(api.rebind_seat(seat["id"], "Dana Laptop 2",
                                            household["owner"]))

    assert_device_seat(data)
    assert data["status"] == "BOUND"
    assert data["bind_count"] == 2
    assert data["released_at"] is None
    assert data["device_label"] == "Dana Laptop 2"
    addon_row = fx.read_addon(addon["id"])
    assert addon_row["seats_bound"] == 1
    assert addon_row["seats_available"] == 1


def test_a_second_live_addon_of_the_same_type_is_rejected(api):
    """PRD §3.8: "Uniqueness is scoped to live rows: an add-on of the same type already
    sitting in `ACTIVE` or `SUSPENDED` on this account rejects the purchase with
    `ERR_DUPLICATE_ADDON`, while a `CANCELLED` one does not block a repurchase."
    PRD §3.8: "Households may buy at most one live add-on of each kind."

    Design: Corner/validations/duplicate_addon_of_the_same_type_is_rejected
    """
    household = fx.open_household()
    fx.buy_addon(household, addon_type="VPN", seats_total=2, per_seat_fee_cents=300)

    response = api.create_addon(household["account_id"],
                                {"addon_type": "VPN", "seats_total": 1,
                                 "per_seat_fee_cents": 400},
                                household["owner"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ADDON.value, 409)
    _, meta = validate_paginated(api.list_account_addons(household["account_id"],
                                                         household["owner"]))
    assert meta["total_count"] == 1

    # A different add-on type on the same account is admitted.
    other = validate_success(api.create_addon(
        household["account_id"],
        {"addon_type": "DEVICE_PROTECTION", "seats_total": 2, "per_seat_fee_cents": 300},
        household["owner"]), 201)
    assert other["addon_type"] == "DEVICE_PROTECTION"
