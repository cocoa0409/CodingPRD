"""
Three conserved quantities and the round trips that must restore them exactly:
floor area in square feet, collected money in cents, sponsorship units in slots.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    DealStatus,
    FloorPosture,
    SpaceContractStatus,
    assert_cancellation_ledger_untouched,
    assert_deposit_conservation,
    assert_floor_area_partition,
    assert_show_area_ledger,
    factories as f,
    fixtures as fx,
    make_director_headers,
    make_sales_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"
INSIDE_NINETY_DAY_BAND_CLOCK = "2026-09-10T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)


def _held_floor(client: ApiClient) -> dict:
    """A 600 sqft floor with 400 of it held on an unsigned contract."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings",
                             contact_email="sales@nordic.example",
                             consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    env["contract"] = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    return env


# ── Conserved quantity 1: floor area ────────────────────────────────────────
def test_sign_then_cancel_returns_every_square_foot_to_the_floor(client: ApiClient):
    """
    The hold moves to assigned and back to available with no drift in any term.

    "A show's `sellable_booth_sqft` must always equal the sum of its
    `available_net_sqft`, `held_net_sqft` and `assigned_net_sqft`."  "after a sign followed by a cancel, the
    show's three area figures, the exhibitor's provisional standing and tier, and the
    contract's `points_awarded` are all exactly back where they started."

    Design: Difficulty/compensating_invariant/sign_then_cancel_returns_every_square_foot_to_the_floor
    """
    env = _held_floor(client)
    show_id = env["show"]["id"]

    before = fx.read_show(client, show_id)
    assert_show_area_ledger(before, 600, 400, 0, 200, 67)
    assert before["floor_posture"] == FloorPosture.OPEN

    signed = fx.sign_contract(client, env["contract"], 400000)
    after_sign = fx.read_show(client, show_id)
    assert_show_area_ledger(after_sign, 600, 0, 400, 200, 67)
    assert after_sign["floor_posture"] == FloorPosture.OPEN
    assert signed["points_awarded"] == 8
    assert (
        fx.read_booth(client, env["booth_by_number"]["A100"]["id"])["status"]
        == BoothStatus.ASSIGNED
    )

    validate_success(
        client.cancel_space_contract(
            env["contract"]["id"],
            f.cancel_payload("Exhibitor withdrew from the 2027 edition"),
            env["exhibitor_headers"],
        )
    )
    after_cancel = fx.read_show(client, show_id)
    assert_show_area_ledger(after_cancel, 600, 0, 0, 600, 0)
    assert after_cancel["floor_posture"] == FloorPosture.OPEN
    assert_floor_area_partition(after_cancel)


def test_the_cancelled_hold_releases_its_booth_and_unwinds_its_points(
    client: ApiClient,
):
    """
    The compensating legs: the booth is freed, the points are reset, and the
    twenty-five percent band two hundred days out is settled out of the deposit.

    "The first releases inventory: every booth of the contract transitions
    `ASSIGNED → AVAILABLE` with `space_contract_id` cleared."  "The third releases
    points: `points_awarded` is subtracted from the exhibitor's space-point base and
    then reset to zero".  "With the seeded default schedule, a cancellation two
    hundred days before the doors open costs 25 percent of the space fee".

    Design: Difficulty/compensating_invariant/sign_then_cancel_returns_every_square_foot_to_the_floor
    """
    env = _held_floor(client)
    fx.sign_contract(client, env["contract"], 400000)

    cancelled = validate_success(
        client.cancel_space_contract(
            env["contract"]["id"],
            f.cancel_payload("Exhibitor withdrew from the 2027 edition"),
            env["exhibitor_headers"],
        )
    )
    assert cancelled["status"] == SpaceContractStatus.CANCELLED
    assert cancelled["points_awarded"] == 0
    assert cancelled["space_fee_cents"] == 1556280
    assert cancelled["cancellation_fee_cents"] == 389070
    assert cancelled["fee_applied_to_deposit_cents"] == 389070
    assert cancelled["refund_cents"] == 10930
    assert cancelled["balance_due_cents"] == 0
    assert_deposit_conservation(cancelled)

    held_booth = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert held_booth["status"] == BoothStatus.AVAILABLE
    assert held_booth["space_contract_id"] is None

    untouched = fx.read_booth(client, env["booth_by_number"]["C050"]["id"])
    assert untouched["status"] == BoothStatus.AVAILABLE
    assert untouched["space_contract_id"] is None


# ── Conserved quantity 2: money in cents ────────────────────────────────────
def _fully_deposited(client: ApiClient) -> dict:
    """
    The same 400 sqft engagement, signed at the minimum and then topped up to
    400000 cents in two instalments.
    """
    env = _held_floor(client)
    fx.sign_contract(client, env["contract"], 389070)
    env["contract"] = validate_success(
        client.post_deposit(
            env["contract"]["id"], f.deposit_payload(10930),
            env["exhibitor_headers"],
        )
    )
    return env


def test_a_fee_larger_than_the_deposit_fills_from_the_deposit_first(
    client: ApiClient,
):
    """
    Cancelling inside the fifty percent band with 400000 cents on hand against a
    778140 cent liability.

    "`fee_applied_to_deposit_cents` is the smaller of `cancellation_fee_cents` and
    `deposit_paid_cents`. `refund_cents` is `deposit_paid_cents` less
    `fee_applied_to_deposit_cents` — the cash actually returned to the exhibitor.
    `balance_due_cents` is `cancellation_fee_cents` less
    `fee_applied_to_deposit_cents` — the unpaid remainder that is invoiced after the
    fact."  "Note that the basis is the space fee and not `invoice_total_cents`"

    Design: Difficulty/compensating_invariant/cancellation_waterfall_conserves_every_collected_cent
    """
    env = _fully_deposited(client)
    before = fx.read_contract(client, env["contract"]["id"])
    assert before["deposit_paid_cents"] == 400000
    assert_cancellation_ledger_untouched(before)

    fx.set_clock(client, INSIDE_NINETY_DAY_BAND_CLOCK)
    cancelled = validate_success(
        client.cancel_space_contract(
            env["contract"]["id"],
            f.cancel_payload("Budget freeze at the exhibitor's head office"),
            env["exhibitor_headers"],
        )
    )
    assert cancelled["space_fee_cents"] == 1556280
    assert cancelled["cancellation_fee_cents"] == 778140
    assert cancelled["fee_applied_to_deposit_cents"] == 400000
    assert cancelled["refund_cents"] == 0
    assert cancelled["balance_due_cents"] == 378140


def test_the_two_split_identities_hold_across_the_overflow(client: ApiClient):
    """
    Every cent collected is accounted for and the fee is fully split, with only one
    of the two outward legs non-zero.

    "For any space contract, `deposit_paid_cents` must always equal `refund_cents`
    plus `fee_applied_to_deposit_cents`, so every cent collected is accounted for;
    and `cancellation_fee_cents` must always equal `fee_applied_to_deposit_cents`
    plus `balance_due_cents`, so the fee is fully split. At most one of
    `refund_cents` and `balance_due_cents` is ever non-zero."

    Design: Difficulty/compensating_invariant/cancellation_waterfall_conserves_every_collected_cent
    """
    env = _fully_deposited(client)
    fx.set_clock(client, INSIDE_NINETY_DAY_BAND_CLOCK)
    validate_success(
        client.cancel_space_contract(
            env["contract"]["id"],
            f.cancel_payload("Budget freeze at the exhibitor's head office"),
            env["exhibitor_headers"],
        )
    )

    cancelled = fx.read_contract(client, env["contract"]["id"])
    assert_deposit_conservation(cancelled)
    assert cancelled["refund_cents"] == 0
    assert cancelled["balance_due_cents"] != 0

    booth = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert booth["status"] == BoothStatus.AVAILABLE
    show = fx.read_show(client, env["show"]["id"])
    assert show["available_net_sqft"] == 600
    assert_floor_area_partition(show)


# ── Conserved quantity 3: sponsorship units ─────────────────────────────────
REP_1 = make_sales_rep_headers("u_rep_1")
DIRECTOR_1 = make_director_headers("u_dir_1")

SPONSORS = [
    ("Nordic Furnishings", "sales@nordic.example", 6, 850000),
    ("Harbor Ceramics", "sales@harbor.example", 2, 900000),
    ("Alder Textiles", "sales@alder.example", 1, 950000),
]


def _two_unit_package(client: ApiClient) -> dict:
    """A keynote package with two units and three eligible sponsors."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    env["sponsors"] = [
        fx.exhibitor(client, legal_name, fx.SALES_REP_HEADERS,
                     contact_email=email, consecutive_years=years)
        for legal_name, email, years, _ in SPONSORS
    ]
    env["package"] = fx.sponsorship_package(
        client, env["show"]["id"], package_code="GOLD_KEYNOTE",
        list_price_cents=1000000, price_floor_cents=700000, inventory_total=2,
        exclusivity_category="NONE",
        obligation_codes=["SOCIAL_MEDIA_POST", "ONSITE_BANNER"],
        priority_point_value=40,
    )
    return env


def _propose(client: ApiClient, package_id: str, exhibitor_id: str, price: int):
    return client.create_sponsorship_deal(
        package_id, f.sponsorship_deal_payload(exhibitor_id, price), REP_1
    )


def _units(client: ApiClient, show_id: str, package_id: str) -> tuple:
    rows, _ = validate_paginated(
        client.list_sponsorship_packages(show_id, fx.DIRECTOR_HEADERS)
    )
    row = next(r for r in rows if r["id"] == package_id)
    assert row["inventory_total"] == row["inventory_committed"] + row["inventory_available"]
    assert 0 <= row["inventory_available"] <= row["inventory_total"]
    return row["inventory_committed"], row["inventory_available"]


def test_the_slot_is_consumed_at_proposal_and_signing_moves_nothing(
    client: ApiClient,
):
    """
    Two proposals exhaust a two-unit package, a third is refused, and signing one of
    the two leaves the split alone.

    "A proposal consumes a unit **immediately**: `inventory_committed` rises by one
    and `inventory_available` falls by one, because a proposal holds the slot even
    before anyone commits to it."  "The package must have at least one unit left, or
    the request is refused with `ERR_SPONSORSHIP_INVENTORY_EXHAUSTED`."

    Design: Difficulty/compensating_invariant/propose_then_cancel_restores_the_sponsorship_unit_count
    """
    env = _two_unit_package(client)
    show_id, package_id = env["show"]["id"], env["package"]["id"]
    assert _units(client, show_id, package_id) == (0, 2)

    first = validate_success(
        _propose(client, package_id, env["sponsors"][0]["id"], 850000), 201
    )
    assert _units(client, show_id, package_id) == (1, 1)

    validate_success(
        _propose(client, package_id, env["sponsors"][1]["id"], 900000), 201
    )
    assert _units(client, show_id, package_id) == (2, 0)

    validate_error(
        _propose(client, package_id, env["sponsors"][2]["id"], 950000),
        ApiErrorId.SPONSORSHIP_INVENTORY_EXHAUSTED,
        409,
    )
    assert _units(client, show_id, package_id) == (2, 0)

    validate_success(client.sign_sponsorship_deal(first["id"], DIRECTOR_1))
    assert _units(client, show_id, package_id) == (2, 0)


def test_cancelling_a_proposal_restores_the_split_and_reopens_the_slot(
    client: ApiClient,
):
    """
    The proposal that dies gives its unit back exactly, and the sponsor that was
    turned away can now be sold.

    "From `PROPOSED`, the effect is narrow: the reason is stored, the held unit is
    released so `inventory_committed` and `inventory_available` return to their exact
    pre-proposal values, and the deal's `version` is incremented."  "A package's
    `inventory_total` must always equal `inventory_committed` plus
    `inventory_available`"

    Design: Difficulty/compensating_invariant/propose_then_cancel_restores_the_sponsorship_unit_count
    """
    env = _two_unit_package(client)
    show_id, package_id = env["show"]["id"], env["package"]["id"]
    first = validate_success(
        _propose(client, package_id, env["sponsors"][0]["id"], 850000), 201
    )
    second = validate_success(
        _propose(client, package_id, env["sponsors"][1]["id"], 900000), 201
    )
    validate_error(
        _propose(client, package_id, env["sponsors"][2]["id"], 950000),
        ApiErrorId.SPONSORSHIP_INVENTORY_EXHAUSTED,
        409,
    )
    validate_success(client.sign_sponsorship_deal(first["id"], DIRECTOR_1))

    cancelled = validate_success(
        client.cancel_sponsorship_deal(
            second["id"],
            f.cancel_payload("Sponsor could not clear the artwork deadline"),
            DIRECTOR_1,
        )
    )
    assert cancelled["deal_status"] == DealStatus.CANCELLED
    assert cancelled["obligation_count"] == 0
    assert fx.read_obligations(client, second["id"]) == []
    assert _units(client, show_id, package_id) == (1, 1)

    reopened = validate_success(
        _propose(client, package_id, env["sponsors"][2]["id"], 950000), 201
    )
    assert reopened["deal_status"] == DealStatus.PROPOSED
    assert _units(client, show_id, package_id) == (2, 0)
