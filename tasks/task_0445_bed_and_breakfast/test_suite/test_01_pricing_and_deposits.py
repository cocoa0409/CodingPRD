"""Pricing ladder and deposit policy: room_charge round-then-sum, package charge,
lodging tax, and the DIRECT-vs-OTA deposit divergence with its first-night floor.

Covers queue-A difficulty instances (dual_variant_calc deposit, combinatorial_formula)
and queue-B calculation/computed-field corners.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_booking,
    create_inn_payload,
    create_room_payload,
    create_rate_period_payload,
    create_package_payload,
    create_guest_payload,
    create_booking_payload,
    TEST_USERS,
    make_guest_headers,
    setup_inn_room_guest,
    create_booking,
)

INNKEEPER = TEST_USERS["innkeeper_headers"]


# ─── dual_variant_calc: deposit DIRECT vs OTA ────────────────────────────────
def test_deposit_direct_30pct_floored_at_first_night(api):
    """PRD §3.3: "For a `DIRECT` booking the deposit is 30% of `total_cents`,
    rounded half up to whole cents; for an `OTA` booking the deposit is the
    entire `total_cents`, since OTA stays prepay in full."
    PRD §3.3: "the deposit is never less than the nightly charge of the first
    occupied night (the same floored per-night figure that opened the
    room-charge sum), so `deposit_due_cents` is the larger of the channel-policy
    amount and that first-night charge."

    Design: Difficulty/dual_variant_calc/deposit_due_direct_vs_ota_diverge
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Maple Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Rose", "base_rate_cents": 10000, "max_occupancy": 2},
    )
    bk = create_booking(
        inn["id"], room["id"], guest["id"], "2026-03-10", "2026-03-12",
        as_guest=True, channel="DIRECT", guest_count=2,
    )
    assert bk["total_cents"] == 22000, f"room 20000 + tax 2000, got {bk['total_cents']}"
    # 30% of 22000 = 6600 < first-night 10000 -> floor wins.
    assert bk["deposit_due_cents"] == 10000


def test_deposit_ota_is_full_total(api):
    """PRD §3.3: "For a `DIRECT` booking the deposit is 30% of `total_cents`,
    rounded half up to whole cents; for an `OTA` booking the deposit is the
    entire `total_cents`, since OTA stays prepay in full."

    Design: Difficulty/dual_variant_calc/deposit_due_direct_vs_ota_diverge
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Maple Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Rose", "base_rate_cents": 10000, "max_occupancy": 2},
    )
    bk = create_booking(
        inn["id"], room["id"], guest["id"], "2026-03-10", "2026-03-12",
        as_guest=True, channel="OTA", guest_count=2,
    )
    assert bk["total_cents"] == 22000
    assert bk["deposit_due_cents"] == 22000, "OTA prepays full total"


def test_deposit_direct_and_ota_diverge_same_stay(api):
    """PRD §3.3: "For a `DIRECT` booking the deposit is 30% of `total_cents`,
    rounded half up to whole cents; for an `OTA` booking the deposit is the
    entire `total_cents`, since OTA stays prepay in full."

    Design: Difficulty/dual_variant_calc/deposit_due_direct_vs_ota_diverge
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Maple Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Rose", "base_rate_cents": 10000, "max_occupancy": 2},
    )
    direct = create_booking(
        inn["id"], room["id"], guest["id"], "2026-03-10", "2026-03-12",
        as_guest=True, channel="DIRECT", guest_count=2,
    )
    ota = create_booking(
        inn["id"], room["id"], guest["id"], "2026-03-10", "2026-03-12",
        as_guest=True, channel="OTA", guest_count=2,
    )
    assert direct["deposit_due_cents"] != ota["deposit_due_cents"]
    assert direct["deposit_due_cents"] == 10000
    assert ota["deposit_due_cents"] == 22000


# ─── combinatorial_formula: room charge round-then-sum ───────────────────────
def test_room_charge_floors_each_night_before_summing(api):
    """PRD §3.2: "That night's charge is the room's `base_rate_cents` multiplied
    by the chosen multiplier basis points divided by 10000, floored to whole
    cents, and these per-night figures are summed in that pinned order to yield
    `room_charge_cents`."
    PRD §2.6: "The per-night room charge is floored to whole cents for each night
    individually and only then summed — round-then-sum, never sum-then-round."

    Design: Difficulty/combinatorial_formula/room_charge_round_per_night_then_sum
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Birch Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="Fern", base_rate_cents=10001,
                                       max_occupancy=2), INNKEEPER))
    get_success_data(api.create_rate_period(
        inn["id"], create_rate_period_payload(
            inn["id"], "2026-08-01", "2026-08-31", label="Aug Peak",
            rate_multiplier_bps=13333, min_nights=1), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Cy G", email="cy@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-08-10",
                               "2026-08-13", channel="DIRECT", guest_count=1),
        make_guest_headers(guest["id"]),
    ))
    # nightly = floor(10001*13333/10000) = floor(13334.3333) = 13334; *3 = 40002.
    # sum-then-round would give 40003; round-then-sum is pinned -> 40002.
    assert bk["room_charge_cents"] == 40002
    assert bk["total_cents"] == 40002


def test_room_charge_round_then_sum_distinct_from_sum_then_round(api):
    """PRD §2.6: "The per-night room charge is floored to whole cents for each
    night individually and only then summed — round-then-sum, never
    sum-then-round."

    Design: Difficulty/combinatorial_formula/room_charge_round_per_night_then_sum
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Birch Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="Fern", base_rate_cents=10001,
                                       max_occupancy=2), INNKEEPER))
    get_success_data(api.create_rate_period(
        inn["id"], create_rate_period_payload(
            inn["id"], "2026-08-01", "2026-08-31", label="Aug Peak",
            rate_multiplier_bps=13333, min_nights=1), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Cy2 G", email="cy2@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-08-10",
                               "2026-08-13", channel="DIRECT", guest_count=1),
        make_guest_headers(guest["id"]),
    ))
    sum_then_round = round(10001 * 13333 / 10000 * 3)  # = 40003
    assert bk["room_charge_cents"] != sum_then_round
    assert bk["room_charge_cents"] == 40002


# ─── combinatorial_formula: deposit nested max + branch ──────────────────────
def test_deposit_first_night_floor_overrides_percentage(api):
    """PRD §3.3: "A first-night floor then applies after rounding: the deposit is
    never less than the nightly charge of the first occupied night (the same
    floored per-night figure that opened the room-charge sum), so
    `deposit_due_cents` is the larger of the channel-policy amount and that
    first-night charge."

    Design: Difficulty/combinatorial_formula/deposit_due_nested_max_and_branch
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Pine Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Holly", "base_rate_cents": 10000, "max_occupancy": 2},
    )
    bk = create_booking(
        inn["id"], room["id"], guest["id"], "2026-04-10", "2026-04-12",
        as_guest=True, channel="DIRECT", guest_count=1,
    )
    assert bk["total_cents"] == 22000
    # max(round(22000*0.3)=6600, first-night 10000) -> 10000.
    assert bk["deposit_due_cents"] == 10000


def test_deposit_percentage_branch_when_floor_does_not_bind(api):
    """PRD §3.3: "For a `DIRECT` booking the deposit is 30% of `total_cents`,
    rounded half up to whole cents; for an `OTA` booking the deposit is the
    entire `total_cents`, since OTA stays prepay in full."
    PRD §3.3: "the deposit is never less than the nightly charge of the first
    occupied night (the same floored per-night figure that opened the
    room-charge sum), so `deposit_due_cents` is the larger of the channel-policy
    amount and that first-night charge."

    Design: Difficulty/combinatorial_formula/deposit_due_nested_max_and_branch
    """
    # Long stay so 30% of total exceeds one night's charge and the floor is inert.
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Pine Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Holly", "base_rate_cents": 10000, "max_occupancy": 2},
    )
    bk = create_booking(
        inn["id"], room["id"], guest["id"], "2026-04-10", "2026-04-20",
        as_guest=True, channel="DIRECT", guest_count=1,
    )
    # 10 nights * 10000 = 100000 total (tax 0); 30% = 30000 > first-night 10000.
    assert bk["total_cents"] == 100000
    assert bk["deposit_due_cents"] == 30000


# ─── queue B: package charge ─────────────────────────────────────────────────
def test_package_charge_flat_plus_per_night(api):
    """PRD §3.2: "The `package_charge_cents` is 0 when no package was selected;
    otherwise it is the package's `flat_add_cents` plus its `per_night_add_cents`
    multiplied by `nights`."

    Design: Corner/calculations/package_charge_flat_plus_per_night
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="S Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    pkg = get_success_data(api.create_package(
        inn["id"], create_package_payload(inn["id"], name="Romance",
                                          flat_add_cents=5000, per_night_add_cents=2000), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Gg G", email="ggg@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                               "2026-05-13", package_id=pkg["id"], channel="DIRECT", guest_count=1),
        INNKEEPER,
    ))
    assert bk["package_charge_cents"] == 11000, "5000 + 2000*3"
    assert bk["total_cents"] == 41000, "room 30000 + pkg 11000 + tax 0"


# ─── queue B: lodging tax excludes non-taxable package ───────────────────────
def test_lodging_tax_excludes_nontaxable_package(api):
    """PRD §3.2: "The `taxable_base_cents` accumulates only the revenue lines
    whose taxability is switched on: the room charge counts toward it only when
    the room's `is_taxable` is true, and the package charge counts toward it
    only when a package was selected and that package's `is_taxable` is true."
    PRD §3.2: "The `lodging_tax_cents` is the `taxable_base_cents` multiplied by
    the inn's `lodging_tax_rate_bps` divided by 10000, rounded half up to whole
    cents."

    Design: Corner/calculations/lodging_tax_excludes_nontaxable_package
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="T Inn", lodging_tax_rate_bps=1450), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=30000,
                                       max_occupancy=2), INNKEEPER))
    pkg = get_success_data(api.create_package(
        inn["id"], create_package_payload(inn["id"], name="Spa", flat_add_cents=10000,
                                          is_taxable=False), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Hh G", email="hhg@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                               "2026-05-13", package_id=pkg["id"], channel="DIRECT", guest_count=1),
        INNKEEPER,
    ))
    assert bk["taxable_base_cents"] == 90000, "room only (3*30000)"
    assert bk["lodging_tax_cents"] == 13050, "90000*1450/10000"


# ─── queue B: computed money fields immediate on create ──────────────────────
def test_computed_fields_present_on_create_response(api):
    """PRD §3.2: "The `total_cents` is the sum of `room_charge_cents`,
    `package_charge_cents`, and `lodging_tax_cents`."
    PRD §3.2: "The `lodging_tax_cents` is the `taxable_base_cents` multiplied by
    the inn's `lodging_tax_rate_bps` divided by 10000, rounded half up to whole
    cents."

    Design: Corner/consistency_model/immediate_visibility_of_computed_fields_on_create
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Mm Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Xx G", email="xxg@x.com"), INNKEEPER))
    res = api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                               "2026-05-12", channel="DIRECT", guest_count=1),
        INNKEEPER,
    )
    bk = validate_success(res, 201)
    assert bk["lodging_tax_cents"] == 2000, "20000*1000/10000"
    assert bk["total_cents"] == 22000


def test_booking_computed_fields_ignore_client_input(api):
    """PRD §3.2: "The night count, `nights`, is the number of whole days from
    `checkin_date` to `checkout_date`; the occupied nights are the half-open span
    running from the check-in night up to but not including the checkout date, so
    the checkout date itself is never charged."

    Design: Corner/entities/booking_computed_fields_ignore_client_input
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="F Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="T G", email="tg@x.com"), INNKEEPER))
    payload = create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                                     "2026-05-13", channel="DIRECT", guest_count=1)
    # Attempt to inject server-computed values; they must be recomputed.
    payload["nights"] = 99
    payload["room_charge_cents"] = 1
    payload["total_cents"] = 1
    bk = validate_success(api.create_booking(inn["id"], payload, INNKEEPER), 201)
    assert bk["nights"] == 3
    assert bk["room_charge_cents"] == 30000
    assert bk["total_cents"] == 30000
    assert_booking(bk)
