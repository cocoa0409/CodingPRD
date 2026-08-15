"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_delivery_ticket_payload,
    create_field_payload,
    create_grower_payload,
    create_inventory_lot_payload,
    create_order_line_payload,
    create_order_payload,
    create_plot_trial_payload,
    create_program_payload,
    create_recommendation_payload,
    create_replant_claim_payload,
    create_return_payload,
    create_trait_agreement_payload,
    create_trait_package_payload,
    create_treatment_option_payload,
    create_variety_payload,
)
from .test_users import TEST_USERS, make_adjuster_headers, make_salesrep_headers

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation / state progression ──

def create_open_program(**overrides):
    """Create a seed program and open it for selling. Returns the OPEN program
    (opening also creates the program's ACCRUING commission statement)."""
    program = get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))
    return get_success_data(api_client.open_program(program["id"], ADMIN))


def create_grower(**overrides):
    return get_success_data(api_client.create_grower(create_grower_payload(**overrides), SALESREP))


def create_field_for(grower, **overrides):
    return get_success_data(
        api_client.create_field(create_field_payload(grower["id"], **overrides), SALESREP)
    )


def create_trait_package(**overrides):
    return get_success_data(
        api_client.create_trait_package(create_trait_package_payload(**overrides), ADMIN)
    )


def create_variety(**overrides):
    return get_success_data(api_client.create_variety(create_variety_payload(**overrides), ADMIN))


def create_treatment_option(**overrides):
    return get_success_data(
        api_client.create_treatment_option(create_treatment_option_payload(**overrides), ADMIN)
    )


def create_inventory_lot(variety_id, **overrides):
    return get_success_data(
        api_client.create_inventory_lot(create_inventory_lot_payload(variety_id, **overrides), ADMIN)
    )


def create_pending_agreement(grower, trait_package_id, **overrides):
    """Create a PENDING_SIGNATURE agreement, OCC-guarded on the grower's current
    version (PRD §2.7). A successful create increments the grower's version."""
    payload = create_trait_agreement_payload(
        grower["id"], trait_package_id, grower["version"], **overrides
    )
    return get_success_data(api_client.create_trait_agreement(payload, ADMIN))


def create_signed_agreement(grower, trait_package_id, **overrides):
    """Create + sign an agreement, returning the ACTIVE agreement. The startup
    clock (2026-08-01T00:00:00Z) lies inside the default license window."""
    agreement = create_pending_agreement(grower, trait_package_id, **overrides)
    return get_success_data(api_client.sign_trait_agreement(agreement["id"], ADMIN))


def create_draft_order(grower, program, **overrides):
    return get_success_data(
        api_client.create_order(create_order_payload(grower["id"], program["id"], **overrides),
                                SALESREP)
    )


def add_line(order, variety_id, units, **overrides):
    return get_success_data(
        api_client.add_order_line(
            order["id"], create_order_line_payload(variety_id, units, **overrides), SALESREP
        )
    )


def confirm_order(order_id):
    return get_success_data(api_client.confirm_order(order_id, SALESREP))


# ─── Tier 2: entity hierarchy (program + grower + catalog) ──

def setup_market(program_overrides=None, variety_overrides=None, lot_overrides=None,
                 grower_overrides=None, with_lot=True, with_field=False):
    """OPEN program + grower + listed variety (+ optional stocked lot + field).
    Returns a dict with the created entities."""
    program = create_open_program(**(program_overrides or {}))
    grower = create_grower(**(grower_overrides or {}))
    variety = create_variety(**(variety_overrides or {}))
    result = {"program": program, "grower": grower, "variety": variety}
    if with_lot:
        result["lot"] = create_inventory_lot(variety["id"], **(lot_overrides or {}))
    if with_field:
        result["field"] = create_field_for(grower)
    return result


def setup_traited_market(program_overrides=None, sign_agreement=True,
                         agreement_overrides=None):
    """OPEN program + grower + stewardship-gated trait package + traited variety
    + stocked lot + an agreement (signed to ACTIVE by default). Returns a dict."""
    program = create_open_program(**(program_overrides or {}))
    grower = create_grower()
    package = create_trait_package()
    variety = create_variety(
        sku="CORN-V1", crop="CORN", relative_maturity_days=112,
        trait_package_id=package["id"], base_price_cents_per_unit=25000,
        seeds_per_unit=80000, preferred_soils=["LOAM", "SILT"], min_drainage="MODERATE",
    )
    lot = create_inventory_lot(variety["id"])
    if sign_agreement:
        agreement = create_signed_agreement(grower, package["id"], **(agreement_overrides or {}))
    else:
        agreement = create_pending_agreement(grower, package["id"], **(agreement_overrides or {}))
    return {
        "program": program, "grower": grower, "package": package,
        "variety": variety, "lot": lot, "agreement": agreement,
    }


# ─── Tier 3: order lifecycle shortcuts ────────────────

def setup_confirmed_order(units=10, clock="2027-01-10T00:00:00Z", **market_kwargs):
    """OPEN program + grower + variety + lot + a CONFIRMED order of `units`.
    Returns dict(program, grower, variety, lot, order, line)."""
    market = setup_market(**market_kwargs)
    set_clock(clock)
    order = create_draft_order(market["grower"], market["program"])
    line = add_line(order, market["variety"]["id"], units)
    order = confirm_order(order["id"])
    return {**market, "order": order, "line": line}


def schedule_delivery(order, line, units, scheduled_date="2027-04-10T00:00:00Z",
                      ticket_type="DELIVERY"):
    return get_success_data(
        api_client.create_delivery_ticket(
            create_delivery_ticket_payload(
                order["id"], line["id"], units=units,
                scheduled_date=scheduled_date, type=ticket_type,
            ),
            SALESREP,
        )
    )


def complete_ticket(ticket_id, at_clock="2027-04-10T12:00:00Z"):
    set_clock(at_clock)
    return get_success_data(api_client.complete_delivery_ticket(ticket_id, SALESREP))


def setup_delivered_order(units=10, deliver_units=None, clock="2027-01-10T00:00:00Z",
                          delivery_date="2027-04-10T00:00:00Z", **market_kwargs):
    """CONFIRMED order with `deliver_units` (default: all) completed on a
    delivery ticket. Returns dict(..., ticket)."""
    ctx = setup_confirmed_order(units=units, clock=clock, **market_kwargs)
    ticket = schedule_delivery(ctx["order"], ctx["line"], deliver_units or units,
                               scheduled_date=delivery_date)
    complete_ticket(ticket["id"], at_clock=_noon_of(delivery_date))
    ctx["ticket"] = ticket
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], SALESREP))
    return ctx


def _noon_of(iso_date_instant: str) -> str:
    """Same UTC calendar date at noon (completion may not precede the date)."""
    return iso_date_instant.split("T")[0] + "T12:00:00Z"


def create_published_recommendation(program, field, variety, agronomist=AGRONOMIST):
    """Create + publish a recommendation. Returns the PUBLISHED recommendation.
    The create is OCC-guarded on the field's current version (PRD §2.7)."""
    field_now = get_success_data(api_client.get_field(field["id"], agronomist))
    rec = get_success_data(
        api_client.create_recommendation(
            create_recommendation_payload(
                field["id"], variety["id"], program["id"], field_now["version"]
            ),
            agronomist,
        )
    )
    return get_success_data(api_client.publish_recommendation(rec["id"], agronomist))


# ─── Tier 3: replant claim lifecycle ──────────────────

def setup_filed_claim(ctx=None, filer_id="rep-1", acres_affected=10,
                      event_date="2027-05-01T00:00:00Z", event_type="FROST",
                      file_clock="2027-05-02T09:00:00Z", **market_kwargs):
    """A delivered order plus a FILED replant claim. `filer_id` is the opaque
    X-User-ID recorded as filed_by_user_id (segregation-of-duties anchor).
    Returns dict(ctx..., claim)."""
    if ctx is None:
        ctx = setup_delivered_order(with_field=True, **market_kwargs)
    elif "field" not in ctx:
        ctx["field"] = create_field_for(ctx["grower"])
    set_clock(file_clock)
    claim = get_success_data(
        api_client.create_replant_claim(
            create_replant_claim_payload(
                ctx["order"]["id"], ctx["line"]["id"], ctx["field"]["id"],
                event_date=event_date, event_type=event_type, acres_affected=acres_affected,
            ),
            make_salesrep_headers(filer_id),
        )
    )
    return {**ctx, "claim": claim}


def setup_claim_under_review(adjuster_id="adj-1", **kwargs):
    """A FILED claim moved to UNDER_REVIEW by an adjuster who is not the filer."""
    ctx = setup_filed_claim(**kwargs)
    claim = get_success_data(
        api_client.start_claim_review(ctx["claim"]["id"], make_adjuster_headers(adjuster_id))
    )
    ctx["claim"] = claim
    return ctx


# ─── Tier 4: season closeout ──────────────────────────

def close_sales_at(program_id, clock="2027-03-20T00:00:00Z"):
    """Advance the clock to/ past sales_close_at and close the selling season."""
    set_clock(clock)
    return get_success_data(api_client.close_sales(program_id, ADMIN))


def settle_program_at(program_id, clock="2027-07-15T00:00:00Z"):
    """Advance the clock strictly past return_window_end and settle."""
    set_clock(clock)
    return get_success_data(api_client.settle_program(program_id, ADMIN))


def get_program_commission_statement(program_id):
    """The single commission statement created when the program opened."""
    data = get_success_data(
        api_client.list_commission_statements(ADMIN, params={"program_id": program_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one commission statement for program {program_id}"
    )
    return data[0]


# ─── Tier 5: full composite scenarios ─────────────────

def setup_commission_dual_variant_scenario():
    """Program (base 500bps, volume tier 1000 units -> 100bps, no order rebate)
    with a 900-unit delivered order and an approved replant claim whose
    360-unit free replacement order carries net zero. Returns dict with the
    program, grower, order, claim, replacement order id, and statement."""
    program = create_open_program(
        early_order_tiers=[
            {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1200},
            {"cutoff_at": "2026-11-15T23:59:59Z", "discount_bps": 1000},
            {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600},
        ],
        prepay_tiers=[
            {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
            {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
        ],
        commission_volume_tiers=[{"min_net_units": 1000, "bonus_bps": 100}],
    )
    grower = create_grower()
    field = create_field_for(grower)
    variety = create_variety()
    lot = create_inventory_lot(variety["id"], received_units=10000)
    # 900-unit order confirmed past every early-order cutoff (0bps).
    set_clock("2027-02-01T00:00:00Z")
    order = create_draft_order(grower, program)
    line = add_line(order, variety["id"], 900)
    order = confirm_order(order["id"])
    ticket = schedule_delivery(order, line, 900, scheduled_date="2027-04-10T00:00:00Z")
    complete_ticket(ticket["id"])
    # Replant claim on 40 of 100 acres -> ceil(40 x 900 / 100) = 360 units free.
    ctx = {"program": program, "grower": grower, "field": field,
           "variety": variety, "lot": lot, "order": order, "line": line}
    ctx = setup_filed_claim(ctx=ctx, filer_id="rep-1", acres_affected=40)
    claim = get_success_data(
        api_client.start_claim_review(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
    )
    claim = get_success_data(
        api_client.approve_claim(claim["id"], make_adjuster_headers("adj-1"))
    )
    ctx["claim"] = claim
    ctx["replacement_order"] = get_success_data(
        api_client.get_order(claim["replacement_order_id"], SALESREP)
    )
    ctx["statement"] = get_program_commission_statement(program["id"])
    return ctx


def setup_return_repricing_scenario(return_units=200):
    """Program with a 500-unit / 500bps volume rebate tier; a 600-unit order
    confirmed past the early-order cutoffs (0bps), fully delivered, and a
    REQUESTED return of `return_units` inside the return window."""
    program = create_open_program(
        early_order_tiers=[
            {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1200},
            {"cutoff_at": "2026-11-15T23:59:59Z", "discount_bps": 1000},
            {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600},
        ],
        prepay_tiers=[
            {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
            {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
        ],
        volume_rebate_tiers=[{"min_units": 500, "rebate_bps": 500}],
        commission_volume_tiers=[{"min_net_units": 1000, "bonus_bps": 100}],
    )
    grower = create_grower()
    variety = create_variety()
    lot = create_inventory_lot(variety["id"], received_units=10000)
    set_clock("2027-02-01T00:00:00Z")
    order = create_draft_order(grower, program)
    line = add_line(order, variety["id"], 600)
    order = confirm_order(order["id"])
    ticket = schedule_delivery(order, line, 600, scheduled_date="2027-04-10T00:00:00Z")
    complete_ticket(ticket["id"])
    set_clock("2027-06-01T00:00:00Z")
    seed_return = get_success_data(
        api_client.create_return(
            create_return_payload(order["id"], line["id"], units=return_units,
                                  reason="OVERSTOCK"),
            SALESREP,
        )
    )
    return {"program": program, "grower": grower, "variety": variety, "lot": lot,
            "order": order, "line": line, "ticket": ticket, "return": seed_return}
