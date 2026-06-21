"""Proration arithmetic and the UP_FRONT vs END_OF_MONTH charge-timing variant.

Covers the dual-variant proration calculation (depth) and the calculation
corner instances for upgrade proration and win-back evaluation order.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    create_creator_payload,
    create_tier_payload,
    create_patron_payload,
    create_pledge_payload,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_draft_pledge,
    create_active_pledge,
    first_pledge_charge,
    settle_charge,
    get_pledge,
    setup_active_membership,
    setup_lapsed_pledge_with_offer,
)

ADMIN = make_platform_admin_headers()


def _pledge_charges(pledge_id, **params):
    p = {"pledge_id": pledge_id}
    p.update(params)
    resp = api_client.list_charges(ADMIN, params=p)
    data, meta = validate_paginated(resp)
    return data, meta


def test_up_front_pledge_creates_initial_proration_charge_750(api):
    """PRD §3.4: "The prorated charge is the base multiplied by the remaining
    days, divided by the days in the month, with the result rounded half up to
    whole cents."
    PRD §3.4: "Under `UP_FRONT`, the prorated amount becomes a charge created
    `PENDING` immediately at pledge or upgrade time — kind `INITIAL_PRORATION`
    for a new pledge, kind `UPGRADE_PRORATION` for an upgrade."

    Design: Difficulty/dual_variant_calc/dvc_proration_up_front_vs_end_of_month
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT", billing_mode="MONTHLY")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])

    data, meta = _pledge_charges(pledge["id"])
    assert meta["total_count"] == 1, f"UP_FRONT pledge must create exactly 1 charge, got {meta['total_count']}"
    charge = data[0]
    assert charge["charge_kind"] == "INITIAL_PRORATION", charge["charge_kind"]
    # June has 30 days; anchor day 16 → remaining 15; 1500*15/30 = 750.
    assert charge["gross_amount_cents"] == 750, f"Expected 750, got {charge['gross_amount_cents']}"


def test_end_of_month_pledge_creates_no_immediate_charge(api):
    """PRD §3.4: "Under `END_OF_MONTH`, no charge is created immediately; the
    prorated amount is deferred and rolled into the next billing-cycle sweep for
    this pledge's cycle anchor."

    Design: Difficulty/dual_variant_calc/dvc_proration_up_front_vs_end_of_month
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="END_OF_MONTH", billing_mode="MONTHLY")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])

    _, meta = _pledge_charges(pledge["id"])
    assert meta["total_count"] == 0, (
        f"END_OF_MONTH pledge must create no immediate charge, got {meta['total_count']}"
    )


def test_upgrade_up_front_charges_proration_delta_350(api):
    """PRD §3.4: "When a patron upgrades a pledge to a different tier, the base
    for the delta is the new tier's `monthly_fee_cents` minus the old tier's
    `monthly_fee_cents`, and that delta is prorated over the remaining days of
    the current cycle in exactly the same way."
    PRD §3.4: "Under an `UP_FRONT` creator the upgrade computes the proration
    delta and creates an `UPGRADE_PRORATION` charge `PENDING`, and the
    `active_pledge_count` of both the old tier and the new tier is recomputed on
    this immediate path."

    Design: Corner/calculations/upgrade_up_front_charges_proration_delta
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    basic = create_published_tier(creator["id"], name="BASIC", rank=1, monthly_fee_cents=800)
    plus = create_published_tier(creator["id"], name="PLUS", rank=2, monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_active_pledge(patron["id"], creator["id"], basic["id"])
    v0 = pledge["version"]

    up = api_client.upgrade_pledge(
        pledge["id"], {"new_tier_id": plus["id"], "expected_pledge_version": v0},
        make_patron_headers(patron["id"]),
    )
    validate_success(up, 200)

    data, _ = _pledge_charges(pledge["id"], status="PENDING")
    upg = [c for c in data if c["charge_kind"] == "UPGRADE_PRORATION"]
    assert len(upg) == 1, f"Expected one UPGRADE_PRORATION charge, got {len(upg)}"
    # delta = 1500-800 = 700; 700*15/30 = 350.
    assert upg[0]["gross_amount_cents"] == 350, f"Expected 350, got {upg[0]['gross_amount_cents']}"
    assert get_pledge(pledge["id"])["tier_id"] == plus["id"]


def test_upgrade_end_of_month_schedules_no_charge(api):
    """PRD §3.4: "Under an `END_OF_MONTH` creator the upgrade creates no
    immediate charge; instead it records the target tier in `scheduled_tier_id`
    to take effect at the next cycle anchor."

    Design: Corner/calculations/upgrade_end_of_month_schedules_no_charge
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="END_OF_MONTH")
    basic = create_published_tier(creator["id"], name="BASIC", rank=1, monthly_fee_cents=800)
    plus = create_published_tier(creator["id"], name="PLUS", rank=2, monthly_fee_cents=1500)
    patron = create_patron()
    # END_OF_MONTH pledge has no auto charge; activate via an admin-created
    # initial charge so the pledge is ACTIVE before the upgrade.
    pledge = create_draft_pledge(patron["id"], creator["id"], basic["id"])
    init = get_success_data(api_client.create_charge(
        {"pledge_id": pledge["id"], "charge_kind": "INITIAL_PRORATION", "gross_amount_cents": 400}, ADMIN))
    settle_charge(init["id"], "SUCCEEDED")
    v0 = get_pledge(pledge["id"])["version"]

    up = api_client.upgrade_pledge(
        pledge["id"], {"new_tier_id": plus["id"], "expected_pledge_version": v0},
        make_patron_headers(patron["id"]),
    )
    data = validate_success(up, 200)
    assert data["scheduled_tier_id"] == plus["id"], (
        f"scheduled_tier_id must be the new tier, got {data['scheduled_tier_id']}"
    )

    _, meta = _pledge_charges(pledge["id"], status="PENDING")
    assert meta["total_count"] == 0, (
        f"END_OF_MONTH upgrade must create no immediate charge, got {meta['total_count']}"
    )


def test_win_back_charge_prorate_then_discount_order(api):
    """PRD §3.6: "Begin by prorating the tier's `monthly_fee_cents` over the
    remaining days of the cycle exactly as in §3.4, rounded half up. If a
    redeemable win-back offer exists, take its `discount_pct`; otherwise the
    discount is zero. The charge's `gross_amount_cents` is then the prorated
    amount multiplied by one minus the discount fraction, rounded half up to
    whole cents."

    Design: Corner/calculations/win_back_charge_prorate_then_discount_order
    """
    # Lapse at 2026-06-20 with a 0.25 offer; reactivate at 2026-06-24.
    s = setup_lapsed_pledge_with_offer(
        lapse_clock="2026-06-20T00:00:00Z", monthly_fee_cents=700, discount_pct=0.25,
    )
    set_clock("2026-06-24T00:00:00Z")
    react = api_client.reactivate_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    validate_success(react, 200)

    data, _ = _pledge_charges(s["pledge"]["id"], status="PENDING")
    wb = [c for c in data if c["charge_kind"] == "WIN_BACK"]
    assert len(wb) == 1, f"Expected one WIN_BACK charge, got {len(wb)}"
    # remaining = 30 - (24-1) = 7; prorate = round(700*7/30) = round(163.33) = 163;
    # discount 0.25 → round(163*0.75) = round(122.25) = 122 (NOT 123).
    assert wb[0]["gross_amount_cents"] == 122, f"Expected 122 (prorate-then-discount), got {wb[0]['gross_amount_cents']}"

    pledge = get_pledge(s["pledge"]["id"])
    assert pledge["win_back_applied"] is True, "win_back_applied must be true after redeeming an offer"
    offer = get_success_data(api_client.get_win_back_offer(s["offer"]["id"], ADMIN))
    assert offer["status"] == "REDEEMED", f"offer must be REDEEMED, got {offer['status']}"


def test_immediate_proration_charge_visible_in_same_flow(api):
    """PRD §3.2: "For a `MONTHLY` tier under an `UP_FRONT` creator, the system
    computes the initial proration and creates a `PENDING` charge of kind
    `INITIAL_PRORATION`".
    PRD §3.4: "The prorated charge is the base multiplied by the remaining days,
    divided by the days in the month, with the result rounded half up to whole
    cents."

    Design: Corner/consistency_model/immediate_proration_charge_visible_in_same_flow
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])

    # Immediately queryable in the same flow (no lag).
    data, meta = _pledge_charges(pledge["id"])
    assert meta["total_count"] == 1
    assert data[0]["charge_kind"] == "INITIAL_PRORATION"
    assert data[0]["gross_amount_cents"] == 750, f"Expected 750, got {data[0]['gross_amount_cents']}"
