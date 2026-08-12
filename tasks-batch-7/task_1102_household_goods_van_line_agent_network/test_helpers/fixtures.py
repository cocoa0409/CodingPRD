"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test). Setup calls use
get_success_data() so a setup failure surfaces as a clear "Setup failed" error.

The scenario context is a plain dict with keys:
    booking_agent / origin_agent / hauling_agent / destination_agent : Agent
    customer : Customer
    tariff : Tariff
    order : MoveOrder (as of the last step that refreshed it)
    booking_h / origin_h / hauling_h / dest_h / cust_h : header dicts
    assignments : {"ORIGIN": ..., "HAULING": ..., "DESTINATION": ...} (dicts)
    coverage : ValuationCoverage (when elected)
    estimate : Estimate (when issued)
    ticket : WeightTicket (when recorded)
    statement : RevenueStatement (after delivery)
"""
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    CWT_LBS,
    DEDUCTIBLE_FACTOR,
    FVP_RATE_PER_100_CENTS,
    NON_BINDING_CAP_PCT,
    ROLE_BASE_PCT,
    TIER_BONUS,
    VAN_LINE_FLOOR_PCT,
    TEST_DEFAULTS,
)
from .factories import (
    create_agent_assignment_payload,
    create_agent_payload,
    create_claim_payload,
    create_customer_payload,
    create_estimate_payload,
    create_order_payload,
    create_tariff_payload,
    create_valuation_coverage_payload,
    create_warehouse_payload,
    create_weight_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_booking_agent_headers,
    make_customer_headers,
    make_destination_agent_headers,
    make_hauling_agent_headers,
    make_origin_agent_headers,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


# ---------------------------------------------------------------------------
# Pricing math mirrors (PRD sections 2.6, 3.3, 3.7) — used by fixtures to
# pre-compute the lawful delivery collection amount.
# ---------------------------------------------------------------------------
def round_half_up_cents(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def weight_to_cwt(weight_lbs: int) -> int:
    """PRD section 2.6: divide by 100, any nonzero remainder rounds up."""
    return -(-weight_lbs // CWT_LBS)


def select_band(mileage: int, bands: list) -> dict:
    """PRD section 2.8: min-inclusive, max-exclusive; final band inclusive."""
    for i, band in enumerate(bands):
        last = i == len(bands) - 1
        if band["min_miles"] <= mileage < band["max_miles"]:
            return band
        if last and band["min_miles"] <= mileage <= band["max_miles"]:
            return band
    raise ValueError(f"no mileage band covers {mileage}")


def compute_linehaul_cents(weight_lbs: int, mileage: int, tariff: dict) -> int:
    cwt = weight_to_cwt(weight_lbs)
    band = select_band(mileage, tariff["mileage_bands"])
    return round_half_up_cents(cwt * tariff["base_rate_cents_per_cwt"] * band["rate_multiplier"])


def compute_fuel_cents(linehaul_cents: int, tariff: dict) -> int:
    return round_half_up_cents(linehaul_cents * tariff["fuel_surcharge_pct"])


def compute_fvp_premium_cents(declared_value_cents: int, deductible_cents: int) -> int:
    """PRD section 3.3: whole $100 units rounded up, times 85 cents, times the
    deductible factor, rounded half up."""
    units = -(-declared_value_cents // 10000)
    return round_half_up_cents(units * FVP_RATE_PER_100_CENTS * DEDUCTIBLE_FACTOR[deductible_cents])


def compute_estimate_total(weight_lbs: int, mileage: int, tariff: dict,
                           packing_cents: int = 0, valuation_premium_cents: int = 0) -> dict:
    linehaul = compute_linehaul_cents(weight_lbs, mileage, tariff)
    fuel = compute_fuel_cents(linehaul, tariff)
    return {
        "linehaul_cents": linehaul,
        "fuel_surcharge_cents": fuel,
        "valuation_premium_cents": valuation_premium_cents,
        "packing_cents": packing_cents,
        "estimated_charges_cents": linehaul + fuel + valuation_premium_cents + packing_cents,
    }


def compute_delivery_amounts(pricing_mode: str, estimated_total_cents: int,
                             actual_weight_lbs: int, mileage: int, tariff: dict,
                             packing_cents: int = 0,
                             locked_premium_cents: int = 0) -> dict:
    """PRD section 3.7: final charges, the 110% cap, amount due, deferred balance."""
    if pricing_mode == "BINDING":
        final = estimated_total_cents
        due = final
    else:
        linehaul = compute_linehaul_cents(actual_weight_lbs, mileage, tariff)
        fuel = compute_fuel_cents(linehaul, tariff)
        final = linehaul + fuel + locked_premium_cents + packing_cents
        cap = round_half_up_cents(estimated_total_cents * NON_BINDING_CAP_PCT)
        due = min(final, cap)
    return {
        "final_charges_cents": final,
        "delivery_amount_due_cents": due,
        "deferred_balance_cents": final - due,
    }


def compute_split_shares(linehaul_revenue_cents: int, tiers: dict,
                         valuation_premium_cents: int = 0) -> dict:
    """PRD section 3.8 waterfall. tiers maps role -> commission tier."""
    shares = {}
    for role in ("BOOKING", "ORIGIN", "HAULING", "DESTINATION"):
        pct = ROLE_BASE_PCT[role] + TIER_BONUS[tiers[role]]
        shares[role] = round_half_up_cents(linehaul_revenue_cents * pct)
    residual = linehaul_revenue_cents - sum(shares.values())
    floor = round_half_up_cents(linehaul_revenue_cents * VAN_LINE_FLOOR_PCT)
    if residual < floor:
        shares["HAULING"] -= floor - residual
        residual = floor
    shares["VAN_LINE"] = residual + valuation_premium_cents
    return shares


def add_days(iso: str, days: int) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ") + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def set_clock(iso: str = CLOCK_DEFAULT_ISO):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_agent(capabilities=("BOOKING",), commission_tier="STANDARD", **overrides) -> dict:
    payload = create_agent_payload(
        capabilities=list(capabilities), commission_tier=commission_tier, **overrides
    )
    return get_success_data(api_client.create_agent(payload, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_published_tariff(**overrides) -> dict:
    tariff = get_success_data(api_client.create_tariff(create_tariff_payload(**overrides), ADMIN))
    return get_success_data(api_client.publish_tariff(tariff["id"], ADMIN))


def create_draft_tariff(**overrides) -> dict:
    return get_success_data(api_client.create_tariff(create_tariff_payload(**overrides), ADMIN))


def create_warehouse(capacity_cwt=500, **overrides) -> dict:
    return get_success_data(
        api_client.create_warehouse(
            create_warehouse_payload(capacity_cwt=capacity_cwt, **overrides), ADMIN
        )
    )


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_statement_for_order(order_id: str) -> dict:
    data, _meta = _list(api_client.list_revenue_statements(ADMIN, params={"order_id": order_id}))
    assert len(data) == 1, f"expected exactly one statement for order {order_id}"
    return data[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Tier 2: network + registration hierarchy
# ---------------------------------------------------------------------------
def setup_network(booking_tier="STANDARD", origin_tier="STANDARD",
                  hauling_tier="STANDARD", destination_tier="STANDARD",
                  tariff_overrides=None, set_default_clock=True) -> dict:
    """Four role agents + one customer + one published tariff. No order yet."""
    if set_default_clock:
        set_clock()
    ctx = {
        "booking_agent": create_agent(["BOOKING"], booking_tier),
        "origin_agent": create_agent(["ORIGIN"], origin_tier),
        "hauling_agent": create_agent(["HAULING"], hauling_tier),
        "destination_agent": create_agent(["DESTINATION"], destination_tier),
        "customer": create_customer(),
        "tariff": create_published_tariff(**(tariff_overrides or {})),
    }
    ctx["booking_h"] = make_booking_agent_headers(ctx["booking_agent"]["id"])
    ctx["origin_h"] = make_origin_agent_headers(ctx["origin_agent"]["id"])
    ctx["hauling_h"] = make_hauling_agent_headers(ctx["hauling_agent"]["id"])
    ctx["dest_h"] = make_destination_agent_headers(ctx["destination_agent"]["id"])
    ctx["cust_h"] = make_customer_headers(ctx["customer"]["id"])
    return ctx


def register_order(ctx, pricing_mode="NON_BINDING", mileage=None, pickup_date=None) -> dict:
    """Register one order on the ctx network; stores it on ctx["order"] and
    returns the created MoveOrder."""
    payload = create_order_payload(
        ctx["customer"]["id"],
        ctx["tariff"]["id"],
        pricing_mode=pricing_mode,
        mileage=mileage if mileage is not None else TEST_DEFAULTS["MILEAGE"],
        pickup_date=pickup_date or TEST_DEFAULTS["PICKUP_DATE"],
    )
    ctx["order"] = get_success_data(api_client.create_order(payload, ctx["booking_h"]))
    return ctx["order"]


def setup_registered_order(pricing_mode="NON_BINDING", mileage=None, pickup_date=None,
                           **network_kwargs) -> dict:
    """Full network plus one REGISTERED order (auto-created CONFIRMED BOOKING
    assignment per PRD section 3.2)."""
    ctx = setup_network(**network_kwargs)
    register_order(ctx, pricing_mode=pricing_mode, mileage=mileage,
                   pickup_date=pickup_date)
    return ctx


# ---------------------------------------------------------------------------
# Tier 1/3: registration-phase writes, booking, dispatch, delivery
# ---------------------------------------------------------------------------
def elect_coverage(ctx, coverage_type="RELEASED_VALUE", declared_value_cents=0,
                   deductible_cents=0, as_role="booking"):
    """Elect valuation coverage under OCC (PRD section 2.7). Returns the coverage."""
    version = get_order(ctx["order"]["id"])["version"]
    payload = create_valuation_coverage_payload(
        version,
        coverage_type=coverage_type,
        declared_value_cents=declared_value_cents,
        deductible_cents=deductible_cents,
    )
    headers = ctx["booking_h"] if as_role == "booking" else ctx["cust_h"]
    coverage = get_success_data(
        api_client.create_valuation_coverage(ctx["order"]["id"], payload, headers)
    )
    ctx["coverage"] = coverage
    return coverage


def issue_estimate(ctx, estimated_weight_lbs=None, packing_services_cents=0,
                   estimate_kind=None) -> dict:
    version = get_order(ctx["order"]["id"])["version"]
    payload = create_estimate_payload(
        version,
        estimate_kind=estimate_kind or ctx["order"]["pricing_mode"],
        estimated_weight_lbs=estimated_weight_lbs or TEST_DEFAULTS["ESTIMATED_WEIGHT_LBS"],
        packing_services_cents=packing_services_cents,
    )
    estimate = get_success_data(
        api_client.create_estimate(ctx["order"]["id"], payload, ctx["booking_h"])
    )
    ctx["estimate"] = estimate
    return estimate


def accept_estimate(ctx, estimate_id=None) -> dict:
    est_id = estimate_id or ctx["estimate"]["id"]
    return get_success_data(api_client.accept_estimate(est_id, ctx["cust_h"]))


def staff_order(ctx) -> dict:
    """Propose + confirm ORIGIN/HAULING/DESTINATION assignments (PRD 3.2)."""
    order_id = ctx["order"]["id"]
    proposals = {}
    for role, agent in (
        ("ORIGIN", ctx["origin_agent"]),
        ("HAULING", ctx["hauling_agent"]),
        ("DESTINATION", ctx["destination_agent"]),
    ):
        proposals[role] = get_success_data(
            api_client.create_agent_assignment(
                order_id, create_agent_assignment_payload(agent["id"], role), ctx["booking_h"]
            )
        )
    confirmations = {}
    for role, headers in (
        ("ORIGIN", ctx["origin_h"]),
        ("HAULING", ctx["hauling_h"]),
        ("DESTINATION", ctx["dest_h"]),
    ):
        confirmations[role] = get_success_data(
            api_client.confirm_agent_assignment(proposals[role]["id"], headers)
        )
    ctx["assignments"] = confirmations
    return ctx


def book_order(ctx) -> dict:
    ctx["order"] = get_success_data(api_client.book_order(ctx["order"]["id"], ctx["booking_h"]))
    return ctx["order"]


def setup_booked_order(pricing_mode="NON_BINDING", estimated_weight_lbs=None,
                       packing_services_cents=0, coverage_type="RELEASED_VALUE",
                       declared_value_cents=0, deductible_cents=0,
                       mileage=None, pickup_date=None, **network_kwargs) -> dict:
    """REGISTERED -> coverage elected -> estimate accepted -> roles CONFIRMED ->
    BOOKED (PRD section 3.4 book gates satisfied)."""
    ctx = setup_registered_order(pricing_mode=pricing_mode, mileage=mileage,
                                 pickup_date=pickup_date, **network_kwargs)
    elect_coverage(ctx, coverage_type=coverage_type,
                   declared_value_cents=declared_value_cents,
                   deductible_cents=deductible_cents)
    issue_estimate(ctx, estimated_weight_lbs=estimated_weight_lbs,
                   packing_services_cents=packing_services_cents)
    accept_estimate(ctx)
    staff_order(ctx)
    book_order(ctx)
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Additional orders on an EXISTING network. PRD section 2.8 forbids publishing a
# second tariff whose window intersects an already-published one, and PRD 3.2
# requires the backing tariff's window to cover the pickup date — so a test that
# needs several orders over the same pickup date must register them against the
# network's one published tariff instead of building a fresh network per order.
# ---------------------------------------------------------------------------
def _share_network(base_ctx) -> dict:
    keys = ("booking_agent", "origin_agent", "hauling_agent", "destination_agent",
            "customer", "tariff", "booking_h", "origin_h", "hauling_h", "dest_h",
            "cust_h")
    return {k: base_ctx[k] for k in keys}


def book_additional_order(base_ctx, pricing_mode="NON_BINDING",
                          estimated_weight_lbs=None, packing_services_cents=0,
                          coverage_type="RELEASED_VALUE", declared_value_cents=0,
                          deductible_cents=0, mileage=None, pickup_date=None) -> dict:
    """A fresh BOOKED order reusing base_ctx's agents, customer, and tariff."""
    ctx = _share_network(base_ctx)
    register_order(ctx, pricing_mode=pricing_mode, mileage=mileage,
                   pickup_date=pickup_date)
    elect_coverage(ctx, coverage_type=coverage_type,
                   declared_value_cents=declared_value_cents,
                   deductible_cents=deductible_cents)
    issue_estimate(ctx, estimated_weight_lbs=estimated_weight_lbs,
                   packing_services_cents=packing_services_cents)
    accept_estimate(ctx)
    staff_order(ctx)
    book_order(ctx)
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def in_transit_additional_order(base_ctx, actual_weight_lbs=9600,
                                dispatch_clock="2026-06-10T10:00:00Z",
                                **book_kwargs) -> dict:
    """A fresh order on base_ctx's network carried through to IN_TRANSIT."""
    ctx = book_additional_order(base_ctx, **book_kwargs)
    record_original_weighment(ctx, net_weight_lbs=actual_weight_lbs)
    dispatch_order(ctx, at_iso=dispatch_clock)
    return ctx


def delivered_additional_order(base_ctx, collect_clock=None, **transit_kwargs) -> dict:
    """A fresh order on base_ctx's network carried through to DELIVERED."""
    ctx = in_transit_additional_order(base_ctx, **transit_kwargs)
    if collect_clock:
        set_clock(collect_clock)
    deliver_order(ctx)
    ctx["statement"] = get_statement_for_order(ctx["order"]["id"])
    return ctx


def record_original_weighment(ctx, tare_weight_lbs=None, net_weight_lbs=9600,
                              weighed_at="2026-06-10T09:00:00Z",
                              scale_location="SCALE-01") -> dict:
    tare = tare_weight_lbs if tare_weight_lbs is not None else TEST_DEFAULTS["TARE_WEIGHT_LBS"]
    payload = create_weight_ticket_payload(
        scale_location=scale_location,
        weighed_at=weighed_at,
        tare_weight_lbs=tare,
        gross_weight_lbs=tare + net_weight_lbs,
    )
    ticket = get_success_data(
        api_client.create_weight_ticket(ctx["order"]["id"], payload, ctx["hauling_h"])
    )
    ctx["ticket"] = ticket
    ctx["order"] = get_order(ctx["order"]["id"])
    return ticket


def dispatch_order(ctx, at_iso="2026-06-10T10:00:00Z") -> dict:
    if at_iso is not None:
        set_clock(at_iso)
    ctx["order"] = get_success_data(
        api_client.dispatch_order(ctx["order"]["id"], ctx["hauling_h"])
    )
    return ctx["order"]


def setup_in_transit_order(pricing_mode="NON_BINDING", actual_weight_lbs=9600,
                           dispatch_clock="2026-06-10T10:00:00Z", **book_kwargs) -> dict:
    """BOOKED -> original weighment -> clock >= pickup_date -> IN_TRANSIT."""
    ctx = setup_booked_order(pricing_mode=pricing_mode, **book_kwargs)
    record_original_weighment(ctx, net_weight_lbs=actual_weight_lbs)
    dispatch_order(ctx, at_iso=dispatch_clock)
    return ctx


def expected_delivery_amount(ctx) -> dict:
    """Recompute the lawful delivery figures for the scenario per PRD 3.7."""
    order = ctx["order"]
    est = ctx["estimate"]
    premium = ctx["coverage"]["premium_cents"] if ctx.get("coverage") else 0
    return compute_delivery_amounts(
        pricing_mode=order["pricing_mode"],
        estimated_total_cents=est["estimated_charges_cents"],
        actual_weight_lbs=order["actual_weight_lbs"],
        mileage=order["mileage"],
        tariff=ctx["tariff"],
        packing_cents=est["packing_services_cents"],
        locked_premium_cents=premium,
    )


def deliver_order(ctx, collected_at_delivery_cents=None) -> dict:
    if collected_at_delivery_cents is None:
        collected_at_delivery_cents = expected_delivery_amount(ctx)["delivery_amount_due_cents"]
    ctx["order"] = get_success_data(
        api_client.deliver_order(
            ctx["order"]["id"],
            {"collected_at_delivery_cents": collected_at_delivery_cents},
            ctx["dest_h"],
        )
    )
    return ctx["order"]


def setup_delivered_order(collect_clock=None, **transit_kwargs) -> dict:
    """Full lifecycle through DELIVERED with the statement cascade fired."""
    ctx = setup_in_transit_order(**transit_kwargs)
    if collect_clock:
        set_clock(collect_clock)
    deliver_order(ctx)
    ctx["statement"] = get_statement_for_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: crews
# ---------------------------------------------------------------------------
def create_crew(ctx, service_end="ORIGIN", service_date=None, start_hour=8,
                end_hour=12, crew_size=2) -> dict:
    from .factories import create_crew_assignment_payload

    headers = ctx["origin_h"] if service_end == "ORIGIN" else ctx["dest_h"]
    payload = create_crew_assignment_payload(
        service_end=service_end,
        service_date=service_date or ctx["order"]["pickup_date"],
        start_hour=start_hour,
        end_hour=end_hour,
        crew_size=crew_size,
    )
    return get_success_data(
        api_client.create_crew_assignment(ctx["order"]["id"], payload, headers)
    )


def confirm_crew(ctx, crew_id, service_end="ORIGIN") -> dict:
    headers = ctx["origin_h"] if service_end == "ORIGIN" else ctx["dest_h"]
    return get_success_data(api_client.confirm_crew_assignment(crew_id, headers))


def complete_crew(ctx, crew_id, service_end="ORIGIN") -> dict:
    headers = ctx["origin_h"] if service_end == "ORIGIN" else ctx["dest_h"]
    return get_success_data(api_client.complete_crew_assignment(crew_id, headers))


# ---------------------------------------------------------------------------
# Tier 3: SIT
# ---------------------------------------------------------------------------
def setup_sit_order(warehouse_capacity=500, checkin_clock="2026-06-10T10:00:00Z",
                    **transit_kwargs) -> dict:
    """IN_TRANSIT order checked into a warehouse: lot IN_STORAGE, order IN_SIT."""
    ctx = setup_in_transit_order(**transit_kwargs)
    ctx["warehouse"] = create_warehouse(capacity_cwt=warehouse_capacity)
    lot = get_success_data(
        api_client.create_sit_lot(
            ctx["order"]["id"], {"warehouse_id": ctx["warehouse"]["id"]}, ctx["hauling_h"]
        )
    )
    ctx["lot"] = lot
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/5: claims, disputes, arbitration
# ---------------------------------------------------------------------------
def file_claim(ctx, claimed_amount_cents=250000, claimed_item_weight_lbs=200,
               description="Loss/damage claim") -> dict:
    claim = get_success_data(
        api_client.create_claim(
            ctx["order"]["id"],
            create_claim_payload(
                description=description,
                claimed_amount_cents=claimed_amount_cents,
                claimed_item_weight_lbs=claimed_item_weight_lbs,
            ),
            ctx["cust_h"],
        )
    )
    ctx["claim"] = claim
    return claim


def setup_delivered_order_with_claim(claim_kwargs=None, **transit_kwargs) -> dict:
    ctx = setup_delivered_order(**transit_kwargs)
    file_claim(ctx, **(claim_kwargs or {}))
    return ctx


def make_offer(ctx, offer_amount_cents, adjuster_id="adj-1") -> dict:
    from .test_users import make_claims_adjuster_headers

    return get_success_data(
        api_client.offer_claim(
            ctx["claim"]["id"],
            {"offer_amount_cents": offer_amount_cents},
            make_claims_adjuster_headers(adjuster_id),
        )
    )


def setup_disputed_claim(offer_amount_cents=12000, adjuster_id="adj-1",
                         **claim_setup_kwargs) -> dict:
    """Delivered order + claim with one rejected round (DISPUTED, round_count 1)."""
    ctx = setup_delivered_order_with_claim(**claim_setup_kwargs)
    make_offer(ctx, offer_amount_cents, adjuster_id=adjuster_id)
    ctx["claim"] = get_success_data(
        api_client.reject_claim_offer(ctx["claim"]["id"], ctx["cust_h"])
    )
    return ctx


def open_claim_dispute(ctx, subject_amount_cents=12000) -> dict:
    dispute = get_success_data(
        api_client.create_dispute(
            {"claim_id": ctx["claim"]["id"], "subject_amount_cents": subject_amount_cents},
            ctx["cust_h"],
        )
    )
    ctx["dispute"] = dispute
    return dispute


def setup_docketed_dispute(responded_at_clock="2026-06-10T10:00:00Z",
                           escalate_clock="2026-06-24T10:00:00Z",
                           responder_id="vl-admin-9",
                           subject_amount_cents=12000,
                           **disputed_kwargs) -> dict:
    """DISPUTED claim -> dispute OPENED -> RESPONSE_FILED -> (>=14 days) ->
    ARBITRATION_DOCKETED (PRD section 3.9)."""
    from .test_users import make_van_line_admin_headers

    ctx = setup_disputed_claim(**disputed_kwargs)
    open_claim_dispute(ctx, subject_amount_cents=subject_amount_cents)
    set_clock(responded_at_clock)
    get_success_data(
        api_client.respond_dispute(
            ctx["dispute"]["id"], {}, make_van_line_admin_headers(responder_id)
        )
    )
    set_clock(escalate_clock)
    ctx["dispute"] = get_success_data(
        api_client.escalate_dispute(ctx["dispute"]["id"], ctx["cust_h"])
    )
    return ctx
