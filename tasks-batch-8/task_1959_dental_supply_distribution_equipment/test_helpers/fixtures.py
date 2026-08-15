"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test). They use get_success_data()
(lenient) so setup failures surface as clear errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_practice_payload,
    create_product_payload,
    create_usage_profile_payload,
    create_order_payload,
    create_equipment_sale_payload,
    create_technician_payload,
    create_van_stock_payload,
    create_service_ticket_payload,
    create_dispatch_payload,
    create_resolve_payload,
    create_coverage_agreement_payload,
    create_bundle_promotion_payload,
    create_rebate_promotion_payload,
    create_rebate_claim_payload,
    create_trade_in_payload,
)
from .test_users import TEST_USERS, make_practice_manager_headers, make_field_technician_headers

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
MANUFACTURER = TEST_USERS["manufacturer_agent_headers"]


# ─── Tier 0: single-entity creators ───────────────────────────

def create_practice(**overrides):
    """Onboard a practice. Returns the Practice resource."""
    return get_success_data(api_client.create_practice(create_practice_payload(**overrides), ADMIN))


def create_product(**overrides):
    """Create a catalog product. Returns the Product resource."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def create_technician(**overrides):
    """Onboard a technician. Returns the Technician resource."""
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), ADMIN))


def get_practice_version(practice_id):
    """Read the practice and return its current version (for OCC-guarded upserts)."""
    return get_success_data(api_client.get_practice(practice_id, ADMIN))["version"]


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def upsert_profile(practice_id, product_id, **overrides):
    """Create-or-supersede a usage profile with a fresh OCC version. Returns the profile."""
    version = get_practice_version(practice_id)
    payload = create_usage_profile_payload(
        practice_id, product_id, expected_practice_version=version, **overrides
    )
    return get_success_data(
        api_client.upsert_usage_profile(payload, make_practice_manager_headers(practice_id))
    )


def create_and_submit_order(practice_id, lines, **overrides):
    """Create an order and submit it. Returns the SUBMITTED order."""
    order = get_success_data(
        api_client.create_order(create_order_payload(practice_id, lines, **overrides), SALES)
    )
    return get_success_data(api_client.submit_order(order["id"], SALES))


def create_and_deliver_order(practice_id, lines, **overrides):
    """Create an order, submit it, and mark it delivered. Returns the DELIVERED order."""
    order = create_and_submit_order(practice_id, lines, **overrides)
    return get_success_data(api_client.deliver_order(order["id"], ADMIN))


# ─── Tier 3: equipment-sale lifecycle ─────────────────────────

def setup_accepted_sale(
    region="R1",
    warranty_months=12,
    sale_price_cents=900_000,
    technician_certifications=("INSTALL", "REPAIR"),
    install_window=("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"),
    training_minutes=30,
    practice_overrides=None,
    product_overrides=None,
):
    """Practice + EQUIPMENT product + technician, sale walked QUOTE -> ACCEPTED.

    Returns dict(practice, product, technician, sale, warranty_agreement_id).
    """
    practice_kwargs = {"region": region}
    practice_kwargs.update(practice_overrides or {})
    practice = create_practice(**practice_kwargs)
    product = create_product(
        kind="EQUIPMENT", warranty_months=warranty_months, **(product_overrides or {})
    )
    technician = create_technician(
        region=region, certifications=list(technician_certifications)
    )
    sale = get_success_data(
        api_client.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"],
                                          sale_price_cents=sale_price_cents),
            SALES,
        )
    )
    get_success_data(api_client.confirm_equipment_sale(sale["id"], SALES))
    get_success_data(
        api_client.schedule_install(
            sale["id"],
            {"technician_id": technician["id"],
             "window_start": install_window[0],
             "window_end": install_window[1]},
            SALES,
        )
    )
    tech_headers = make_field_technician_headers(technician["id"])
    get_success_data(api_client.complete_install(sale["id"], tech_headers))
    get_success_data(
        api_client.complete_training(sale["id"], {"training_minutes": training_minutes}, tech_headers)
    )
    sale = get_success_data(
        api_client.accept_equipment_sale(sale["id"], make_practice_manager_headers(practice["id"]))
    )
    return {
        "practice": practice,
        "product": product,
        "technician": technician,
        "sale": sale,
        "warranty_agreement_id": sale.get("warranty_agreement_id"),
    }


def setup_confirmed_sale(
    region="R1",
    sale_price_cents=900_000,
    practice=None,
    product=None,
    practice_overrides=None,
):
    """Practice + EQUIPMENT product + sale in CONFIRMED. Returns dict(practice, product, sale)."""
    if practice is None:
        practice_kwargs = {"region": region}
        practice_kwargs.update(practice_overrides or {})
        practice = create_practice(**practice_kwargs)
    product = product or create_product(kind="EQUIPMENT", warranty_months=12)
    sale = get_success_data(
        api_client.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"],
                                          sale_price_cents=sale_price_cents),
            SALES,
        )
    )
    sale = get_success_data(api_client.confirm_equipment_sale(sale["id"], SALES))
    return {"practice": practice, "product": product, "sale": sale}


def drive_sale_to_accepted(
    practice,
    product,
    technician,
    sale_price_cents=900_000,
    install_window=("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"),
    training_minutes=30,
):
    """Walk a new equipment sale QUOTE -> ACCEPTED against existing practice/product/technician.

    Returns the ACCEPTED sale (warranty_agreement_id set per PRD §3.5).
    """
    sale = get_success_data(
        api_client.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"],
                                          sale_price_cents=sale_price_cents),
            SALES,
        )
    )
    get_success_data(api_client.confirm_equipment_sale(sale["id"], SALES))
    get_success_data(
        api_client.schedule_install(
            sale["id"],
            {"technician_id": technician["id"],
             "window_start": install_window[0],
             "window_end": install_window[1]},
            SALES,
        )
    )
    tech_headers = make_field_technician_headers(technician["id"])
    get_success_data(api_client.complete_install(sale["id"], tech_headers))
    get_success_data(
        api_client.complete_training(sale["id"], {"training_minutes": training_minutes}, tech_headers)
    )
    return get_success_data(
        api_client.accept_equipment_sale(sale["id"], make_practice_manager_headers(practice["id"]))
    )


def load_van_stock(technician_id, product_id, quantity_on_van=10, min_quantity=1):
    """Load/adjust one part line on a technician's van. Returns the Technician."""
    return get_success_data(
        api_client.load_van_stock(
            technician_id,
            create_van_stock_payload(
                product_id, quantity_on_van=quantity_on_van, min_quantity=min_quantity
            ),
            ADMIN,
        )
    )


def create_service_plan(
    practice_id,
    equipment_sale_id,
    deductible_cents=5000,
    coverage_cap_cents=100_000,
    start_date="2026-08-01T00:00:00Z",
    end_date="2028-08-01T00:00:00Z",
):
    """Register a SERVICE_PLAN coverage agreement (PRD §3.7). Returns the agreement."""
    return get_success_data(
        api_client.create_coverage_agreement(
            create_coverage_agreement_payload(
                practice_id,
                equipment_sale_id,
                deductible_cents=deductible_cents,
                coverage_cap_cents=coverage_cap_cents,
                start_date=start_date,
                end_date=end_date,
            ),
            SALES,
        )
    )


def open_and_assess_ticket(practice_id, equipment_sale_id, issue_description="malfunction"):
    """Create a service ticket and run assess-coverage. Returns the assessed ticket."""
    ticket = get_success_data(
        api_client.create_service_ticket(
            create_service_ticket_payload(
                practice_id, equipment_sale_id, issue_description=issue_description
            ),
            DISPATCH,
        )
    )
    return get_success_data(api_client.assess_coverage(ticket["id"], DISPATCH))


# ─── Tier 3: service-ticket lifecycle ─────────────────────────

def setup_ticket_assessed(accepted=None, **accepted_kwargs):
    """Accepted sale + OPEN ticket moved through assess-coverage.

    Returns dict(ctx..., ticket) where ctx is the setup_accepted_sale dict.
    """
    ctx = accepted or setup_accepted_sale(**accepted_kwargs)
    ticket = get_success_data(
        api_client.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"]),
            DISPATCH,
        )
    )
    ticket = get_success_data(api_client.assess_coverage(ticket["id"], DISPATCH))
    ctx["ticket"] = ticket
    return ctx


def setup_ticket_dispatched(
    dispatch_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
    accepted=None,
    **accepted_kwargs,
):
    """Ticket in DISPATCHED with a SCHEDULED DispatchJob.

    Returns dict(ctx..., ticket, job, job_technician_id).
    """
    ctx = setup_ticket_assessed(accepted=accepted, **accepted_kwargs)
    job = get_success_data(
        api_client.dispatch_ticket(
            ctx["ticket"]["id"],
            create_dispatch_payload(
                scheduled_start=dispatch_window[0], scheduled_end=dispatch_window[1]
            ),
            DISPATCH,
        )
    )
    ctx["job"] = job
    ctx["job_technician_id"] = job["technician_id"]
    ctx["ticket"] = get_success_data(api_client.get_service_ticket(ctx["ticket"]["id"], DISPATCH))
    return ctx


def setup_ticket_resolved(parts_used=None, labor_minutes=30, **dispatch_kwargs):
    """Ticket resolved by the assigned technician. Returns ctx with resolved ticket."""
    ctx = setup_ticket_dispatched(**dispatch_kwargs)
    payload = create_resolve_payload(parts_used=parts_used or [], labor_minutes=labor_minutes)
    ctx["ticket"] = get_success_data(
        api_client.resolve_ticket(
            ctx["ticket"]["id"], payload, make_field_technician_headers(ctx["job_technician_id"])
        )
    )
    return ctx


# ─── Tier 3: rebate-claim lifecycle ───────────────────────────

def setup_rebate_claim(
    practice_tier="STANDARD",
    rebate_per_unit_cents=50,
    fund_total_cents=10_000,
    order_quantities=(1,),
    num_products=None,
    submit=False,
):
    """Practice + rebate-eligible products + promotion + delivered order + DRAFT claim.

    order_quantities holds one quantity per product; num_products defaults to
    len(order_quantities). Returns dict(practice, products, promotion, order, claim).
    """
    quantities = list(order_quantities)
    n = num_products or len(quantities)
    if len(quantities) < n:
        quantities = quantities + [1] * (n - len(quantities))
    practice = create_practice(practice_tier=practice_tier)
    products = [create_product() for _ in range(n)]
    promotion = get_success_data(
        api_client.create_promotion(
            create_rebate_promotion_payload(
                [p["id"] for p in products],
                rebate_per_unit_cents=rebate_per_unit_cents,
                fund_total_cents=fund_total_cents,
            ),
            ADMIN,
        )
    )
    pm = make_practice_manager_headers(practice["id"])
    lines = [{"product_id": p["id"], "quantity": q} for p, q in zip(products, quantities)]
    order = get_success_data(api_client.create_order(create_order_payload(practice["id"], lines), pm))
    get_success_data(api_client.submit_order(order["id"], pm))
    order = get_success_data(api_client.deliver_order(order["id"], ADMIN))
    claim = get_success_data(
        api_client.create_rebate_claim(
            create_rebate_claim_payload(practice["id"], order["id"], promotion["id"]), pm
        )
    )
    if submit:
        claim = get_success_data(api_client.submit_rebate_claim(claim["id"], pm))
    return {
        "practice": practice,
        "products": products,
        "promotion": promotion,
        "order": order,
        "claim": claim,
    }


# ─── Tier 3: trade-in lifecycle ───────────────────────────────

def create_accepted_trade_in(practice_id, valuation_method="SCRAP_VALUE", **trade_in_overrides):
    """Trade-in walked REQUESTED -> APPRAISED -> ACCEPTED. Returns the TradeIn."""
    trade_in = get_success_data(
        api_client.create_trade_in(create_trade_in_payload(practice_id, **trade_in_overrides), SALES)
    )
    trade_in = get_success_data(
        api_client.appraise_trade_in(trade_in["id"], {"valuation_method": valuation_method}, SALES)
    )
    return get_success_data(
        api_client.accept_trade_in(trade_in["id"], make_practice_manager_headers(practice_id))
    )
