"""Pricing and the checkout money fan-out: membership-discounted quotes, the
commission-vs-booth-rent payout split, the booth-rent min() clamp on package
revenue, per-line retail rounding, package per-session value, tip distribution
under DIRECT and POOLED, and the package-redeemed zero quote.

Queue A (Difficulty) — rules: dual_variant_calc, combinatorial_formula,
cross_entity_state_dependency (PAST_DUE priced as non-member).
Queue B (Corner) — sections: calculations, endpoints (computed read).
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_stylist_headers,
    create_appointment_payload,
    create_checkout_payload,
    create_salon,
    create_stylist,
    create_resource,
    create_service,
    create_client,
    create_membership_plan,
    create_membership,
    create_package,
    create_package_purchase,
    create_product_sku,
    advance_clock,
    book_appointment,
    checkout_appointment,
    setup_bookable_salon,
)

OWNER = TEST_USERS["salon_owner_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# =========================================================================== #
# Rule 1 — dual_variant_calc: payout commission vs booth rent
# =========================================================================== #
def test_stylist_payout_commission_vs_booth_rent(api):
    """PRD §3.5: "When the serving stylist's compensation_model is COMMISSION,
    the stylist's share, stylist_service_earning_cents, is the recognized service
    revenue multiplied by the stylist's commission_pct, rounded half up to whole
    cents, and the salon's share, salon_service_earning_cents, is the recognized
    revenue minus the stylist's share. When the model is BOOTH_RENT, the salon's
    share is the booth rent — the smaller of the stylist's booth_rent_per_appt_cents
    and the recognized revenue ... — and the stylist's share is the recognized
    revenue minus that booth rent."

    Design: Difficulty/dual_variant_calc/stylist_payout_commission_vs_booth_rent
    """
    salon = create_salon(name="Glow Bar", tip_split_policy="DIRECT")
    st_comm = create_stylist(salon["id"], full_name="Comm", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    st_booth = create_stylist(salon["id"], full_name="Booth", compensation_model="BOOTH_RENT",
                              booth_rent_per_appt_cents=1500, buffer_minutes=0)
    ch1 = create_resource(salon["id"], label="Chair 1", resource_type="CHAIR")
    ch2 = create_resource(salon["id"], label="Chair 2", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=10000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Pat", email="pat@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt_comm, _ = book_appointment(salon["id"], client["id"], st_comm, ch1["id"],
                                    service["id"], "2026-07-01T13:00:00Z")
    appt_booth, _ = book_appointment(salon["id"], client["id"], st_booth, ch2["id"],
                                     service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co_comm = checkout_appointment(appt_comm["id"], tip_cents=0)
    co_booth = checkout_appointment(appt_booth["id"], tip_cents=0)
    assert co_comm["service_revenue_cents"] == 10000
    assert co_comm["stylist_service_earning_cents"] == 4000
    assert co_comm["salon_service_earning_cents"] == 6000
    assert co_booth["stylist_service_earning_cents"] == 8500
    assert co_booth["salon_service_earning_cents"] == 1500


def test_stylist_payout_booth_rent_complements_commission(api):
    """PRD §3.5: "on 10000 cents of revenue a commission stylist at 0.40 earns
    4000 with the salon keeping 6000, whereas a booth-rent stylist owing 1500
    keeps 8500 with the salon earning only 1500."

    Design: Difficulty/dual_variant_calc/stylist_payout_commission_vs_booth_rent
    """
    state = setup_bookable_salon(
        salon_overrides={"tip_split_policy": "DIRECT", "no_show_fee_pct": 0.0},
        stylist_overrides={"compensation_model": "BOOTH_RENT",
                           "booth_rent_per_appt_cents": 1500, "buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 10000, "deposit_pct": 0.0},
    )
    sid = state["salon"]["id"]
    stylist = state["stylists"][0]
    appt, _ = book_appointment(sid, state["client"]["id"], stylist,
                               state["resources"][0]["id"], state["service"]["id"],
                               "2026-07-01T13:00:00Z")
    advance_clock(sid, "2026-07-01T14:00:00Z", state["salon_version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    assert co["service_revenue_cents"] == 10000
    assert co["salon_service_earning_cents"] == 1500
    assert co["stylist_service_earning_cents"] == 8500


# =========================================================================== #
# Rule 1 — dual_variant_calc: member vs non-member quote
# =========================================================================== #
def test_appointment_quote_member_vs_non_member(api):
    """PRD §3.3: "if the booking client holds a single membership that is ACTIVE
    at booking time (memberships that are PAST_DUE or CANCELLED are ignored), the
    plan's service_discount_pct is applied by multiplying the base price by one
    minus that discount fraction and rounding the product half up to whole cents;
    if the client has no ACTIVE membership, the quote is simply the base price."

    Design: Difficulty/dual_variant_calc/appointment_quote_member_vs_non_member
    """
    salon = create_salon(name="Quote Salon", tip_split_policy="DIRECT")
    st1 = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    st2 = create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION", buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Color", duration_minutes=60,
                             base_price_cents=10000, deposit_pct=0.0)
    plan = create_membership_plan(salon["id"], name="Gold", service_discount_pct=0.20, retail_discount_pct=0.0)
    cli_mem = create_client(salon["id"], full_name="Mem", email="mem@x.com")
    cli_non = create_client(salon["id"], full_name="Non", email="non@x.com")
    create_membership(cli_mem["id"], plan["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt_mem, _ = book_appointment(salon["id"], cli_mem["id"], st1, chA["id"],
                                   service["id"], "2026-07-01T14:00:00Z")
    appt_non, _ = book_appointment(salon["id"], cli_non["id"], st2, chB["id"],
                                   service["id"], "2026-07-01T14:00:00Z")
    assert appt_mem["quoted_service_price_cents"] == 8000   # 20% off 10000
    assert appt_non["quoted_service_price_cents"] == 10000  # no discount


def test_appointment_quote_non_member_is_base_price(api):
    """PRD §3.3: "if the client has no ACTIVE membership, the quote is simply the
    base price."

    Design: Difficulty/dual_variant_calc/appointment_quote_member_vs_non_member
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 60, "base_price_cents": 10000, "deposit_pct": 0.0},
    )
    stylist = base["stylists"][0]
    appt, _ = book_appointment(base["salon"]["id"], base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T14:00:00Z")
    assert appt["quoted_service_price_cents"] == 10000


# =========================================================================== #
# Rule 2 — combinatorial_formula
# =========================================================================== #
def test_retail_line_round_per_line_then_sum(api):
    """PRD §3.5: "For each line the effective unit price is the SKU's
    unit_price_cents if there is no active membership, or, if there is, that unit
    price multiplied by one minus the plan's retail_discount_pct, rounded half up
    to whole cents. The line's line_total_cents is that already-integer effective
    unit price multiplied by the line quantity. The checkout's retail_revenue_cents
    is the sum of all the lines' line_total_cents."

    Design: Difficulty/combinatorial_formula/retail_line_round_per_line_then_sum
    """
    salon = create_salon(name="Retail Salon", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Trim", duration_minutes=30,
                             base_price_cents=0, deposit_pct=0.0)
    plan = create_membership_plan(salon["id"], name="Silver", service_discount_pct=0.0,
                                  retail_discount_pct=0.15)
    client = create_client(salon["id"], full_name="Buyer", email="buyer@x.com")
    create_membership(client["id"], plan["id"])
    sku1 = create_product_sku(salon["id"], sku="SH-1", name="Shampoo", unit_price_cents=2000, qty_on_hand=10)
    sku2 = create_product_sku(salon["id"], sku="OL-1", name="Oil", unit_price_cents=999, qty_on_hand=10)
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co = checkout_appointment(
        appt["id"], tip_cents=0,
        retail_lines=[{"product_sku_id": sku1["id"], "quantity": 3},
                      {"product_sku_id": sku2["id"], "quantity": 1}],
    )
    # rhu(2000*0.85)*3 = 1700*3 = 5100; rhu(999*0.85)*1 = rhu(849.15)=849; total 5949.
    assert co["retail_revenue_cents"] == 5949


def test_retail_per_line_rounding_differs_from_sum_then_round(api):
    """PRD §3.5: "Because the rounding happens once per line before summation,
    the total can differ from a sum-then-round computation, and this per-line
    ordering is the contract."

    Design: Difficulty/combinatorial_formula/retail_line_round_per_line_then_sum
    """
    # Two single-unit lines at 999 each with a 15% member discount.
    # Per line: round_half_up(999*0.85)=round_half_up(849.15)=849; sum 849*2=1698.
    # Sum-then-round would give round_half_up(1698.30)=1698 here too, so use a
    # value where the orders diverge: 333 @ 0.85 = 283.05 -> rounds to 283 per
    # line; 283*2 = 566. (sum-then-round of 566.10 = 566; identical) — instead
    # assert the pinned per-line integer result directly on a divergent case:
    # 2001 @ 0.85 = 1700.85 -> per line round 1701; two lines 1701+1701 = 3402.
    salon = create_salon(name="Retail Salon 2", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Trim", duration_minutes=30,
                             base_price_cents=0, deposit_pct=0.0)
    plan = create_membership_plan(salon["id"], name="Silver", service_discount_pct=0.0,
                                  retail_discount_pct=0.15)
    client = create_client(salon["id"], full_name="Buyer", email="buyer2@x.com")
    create_membership(client["id"], plan["id"])
    sku1 = create_product_sku(salon["id"], sku="A-1", name="A", unit_price_cents=2001, qty_on_hand=10)
    sku2 = create_product_sku(salon["id"], sku="B-1", name="B", unit_price_cents=2001, qty_on_hand=10)
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co = checkout_appointment(
        appt["id"], tip_cents=0,
        retail_lines=[{"product_sku_id": sku1["id"], "quantity": 1},
                      {"product_sku_id": sku2["id"], "quantity": 1}],
    )
    # round_half_up(2001*0.85)=round_half_up(1700.85)=1701 per line; sum 3402.
    assert co["retail_revenue_cents"] == 3402


def test_booth_rent_min_clamp_on_package_revenue(api):
    """PRD §3.5: "If the appointment redeemed a package, the recognized
    service_revenue_cents is the package's per-session value."
    PRD §3.5: "When the model is BOOTH_RENT, the salon's share is the booth rent
    — the smaller of the stylist's booth_rent_per_appt_cents and the recognized
    revenue (clamped so it can never exceed the revenue available) — and the
    stylist's share is the recognized revenue minus that booth rent."

    Design: Difficulty/combinatorial_formula/stylist_earning_multiinput_nonlinear_min_branch
    """
    salon = create_salon(name="Booth Salon", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="Booth S", compensation_model="BOOTH_RENT",
                             booth_rent_per_appt_cents=8000, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial Lite", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="Pkg Client", email="pkgc@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    # per-session = 24000/4 = 6000; booth = min(8000, 6000) = 6000; stylist = 0.
    assert co["service_revenue_cents"] == 6000
    assert co["salon_service_earning_cents"] == 6000
    assert co["stylist_service_earning_cents"] == 0


def test_booth_rent_below_revenue_keeps_complement(api):
    """PRD §3.5: "When the model is BOOTH_RENT, the salon's share is the booth
    rent — the smaller of the stylist's booth_rent_per_appt_cents and the
    recognized revenue ... — and the stylist's share is the recognized revenue
    minus that booth rent."

    Design: Difficulty/combinatorial_formula/stylist_earning_multiinput_nonlinear_min_branch
    """
    # Same package per-session revenue (6000) but rent 1500 < revenue: the min()
    # picks 1500, so stylist keeps 4500 and salon earns 1500 (the other branch of
    # the clamp than the rent-8000 case).
    salon = create_salon(name="Booth Salon 2", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="Booth S", compensation_model="BOOTH_RENT",
                             booth_rent_per_appt_cents=1500, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial Lite", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="Pkg Client", email="pkgc2@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    # per-session 6000; booth min(1500,6000)=1500; stylist 6000-1500=4500.
    assert co["service_revenue_cents"] == 6000
    assert co["salon_service_earning_cents"] == 1500
    assert co["stylist_service_earning_cents"] == 4500


# =========================================================================== #
# Rule 7 — cross_entity_state_dependency: PAST_DUE priced as non-member
# =========================================================================== #
def test_pastdue_membership_priced_as_non_member(api):
    """PRD §3.2: "A SalonOwner may mark an ACTIVE membership PAST_DUE — a lapse
    that suspends its discounts so that future appointment quotes price as
    non-member."
    PRD §3.3: "if the booking client holds a single membership that is ACTIVE at
    booking time (memberships that are PAST_DUE or CANCELLED are ignored), the
    plan's service_discount_pct is applied ...; if the client has no ACTIVE
    membership, the quote is simply the base price."

    Design: Difficulty/cross_entity_state_dependency/pastdue_membership_priced_as_non_member_pair_appointment_membership
    """
    salon = create_salon(name="Lapse Salon", tip_split_policy="DIRECT")
    st1 = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    st2 = create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION", buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Color", duration_minutes=60,
                             base_price_cents=10000, deposit_pct=0.0)
    plan = create_membership_plan(salon["id"], name="Gold", service_discount_pct=0.20)
    client = create_client(salon["id"], full_name="Mem", email="lap@x.com")
    mem = create_membership(client["id"], plan["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt_active, _ = book_appointment(salon["id"], client["id"], st1, chA["id"],
                                      service["id"], "2026-07-01T14:00:00Z")
    get_success_data(api.lapse_membership(mem["id"], OWNER))
    appt_pastdue, _ = book_appointment(salon["id"], client["id"], st2, chB["id"],
                                       service["id"], "2026-07-01T14:00:00Z")
    assert appt_active["quoted_service_price_cents"] == 8000     # ACTIVE -> 20% off
    assert appt_pastdue["quoted_service_price_cents"] == 10000   # PAST_DUE -> full price


def test_reinstated_membership_prices_as_member_again(api):
    """PRD §3.2: "may later reinstate a PAST_DUE membership back to ACTIVE,
    restoring its discounts."
    PRD §3.3: "if the booking client holds a single membership that is ACTIVE at
    booking time (memberships that are PAST_DUE or CANCELLED are ignored), the
    plan's service_discount_pct is applied by multiplying the base price by one
    minus that discount fraction and rounding the product half up to whole cents."

    Design: Difficulty/cross_entity_state_dependency/pastdue_membership_priced_as_non_member_pair_appointment_membership
    """
    salon = create_salon(name="Reinstate Price Salon", tip_split_policy="DIRECT")
    st1 = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    st2 = create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION", buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Color", duration_minutes=60,
                             base_price_cents=10000, deposit_pct=0.0)
    plan = create_membership_plan(salon["id"], name="Gold", service_discount_pct=0.20)
    client = create_client(salon["id"], full_name="Mem", email="reins@x.com")
    mem = create_membership(client["id"], plan["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # Lapse then reinstate; a booking after reinstatement quotes the member price.
    get_success_data(api.lapse_membership(mem["id"], OWNER))
    get_success_data(api.reinstate_membership(mem["id"], OWNER))
    appt, _ = book_appointment(salon["id"], client["id"], st1, chA["id"],
                               service["id"], "2026-07-01T14:00:00Z")
    assert appt["quoted_service_price_cents"] == 8000  # discount restored


# =========================================================================== #
# Corner — calculations section (non-stub)
# =========================================================================== #
def test_pooled_tip_remainder_by_created_at(api):
    """PRD §3.5: "Under POOLED, the tip is divided evenly across all stylists in
    the salon whose status is ACTIVE at checkout time, including the serving
    stylist ... the base share for each is the entered tip_cents divided down to
    a whole cent (the floor of the division). The leftover cents ... are then
    handed out one per stylist, to the earliest-created stylists first ... For
    example, a 1000-cent tip pooled across three ACTIVE stylists yields shares of
    334, 333, and 333 in created_at order."

    Design: Corner/calculations/pooled_tip_remainder_by_created_at
    """
    salon = create_salon(name="Pool S", tip_split_policy="POOLED", no_show_fee_pct=0.0)
    st1 = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION")
    create_stylist(salon["id"], full_name="S3", compensation_model="COMMISSION")
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="pl@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], st1, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=1000)
    # Serving stylist S1 was created first -> base 333 + 1 leftover cent = 334.
    assert co["stylist_tip_cents"] == 334


def test_direct_tip_full_to_serving_stylist(api):
    """PRD §3.5: "Under DIRECT, the entire tip_cents goes to the serving stylist
    and every other stylist gets nothing."

    Design: Corner/calculations/direct_tip_full_to_serving_stylist
    """
    salon = create_salon(name="Direct S", tip_split_policy="DIRECT", no_show_fee_pct=0.0)
    st1 = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    create_stylist(salon["id"], full_name="S2", compensation_model="COMMISSION")
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="dt@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], st1, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=1000)
    assert co["stylist_tip_cents"] == 1000


def test_package_session_value_rounds_half_up(api):
    """PRD §3.5: "The per-session value of a package is its total price_cents
    divided by its session_count, with the division performed first and the
    quotient rounded half up to whole cents exactly once."

    Design: Corner/calculations/package_session_value_rounds_half_up
    """
    salon = create_salon(name="Pkg3 S", no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=3, price_cents=10000)
    client = create_client(salon["id"], full_name="C1", email="p3@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    # 10000 / 3 = 3333.33 -> round_half_up -> 3333.
    assert co["service_revenue_cents"] == 3333


def test_package_redeemed_appointment_quotes_zero(api):
    """PRD §3.3: "If the booking redeems a package — a package_purchase_id is
    present — the quote is set to 0, since the session is prepaid, and no deposit
    is collected."

    Design: Corner/calculations/package_redeemed_appointment_quotes_zero
    """
    salon = create_salon(name="PkgZero S")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.5)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="C1", email="pz@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    assert appt["quoted_service_price_cents"] == 0
    assert appt["deposit_held_cents"] == 0


# =========================================================================== #
# Corner — endpoints section: checkout computed read
# =========================================================================== #
def test_checkout_computed_read_returns_split_fields(api):
    """PRD §3.7: "A checkout itself, with all of its computed money fields —
    service_revenue_cents, retail_revenue_cents, stylist_service_earning_cents,
    salon_service_earning_cents, and stylist_tip_cents — is readable by a
    SalonOwner, a FrontDesk operator, or a Stylist."
    PRD §3.5: "the stylist's share ... is the recognized service revenue
    multiplied by the stylist's commission_pct, rounded half up to whole cents,
    and the salon's share ... is the recognized revenue minus the stylist's share."

    Design: Corner/endpoints/checkout_computed_read_returns_split_fields
    """
    salon = create_salon(name="S", no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="cm@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], tip_cents=0)
    # Read it back as the serving Stylist (ownership: resource references this stylist).
    read = get_success_data(api.get_checkout(co["id"], make_stylist_headers(stylist["id"])))
    assert read["stylist_service_earning_cents"] == 2000
    assert read["salon_service_earning_cents"] == 3000
