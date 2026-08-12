"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_brand_compliance_audit_payload,
    create_dealer_station_payload,
    create_eft_draft_payload,
    create_inventory_reconciliation_payload,
    create_loss_event_payload,
    create_meter_reading_payload,
    create_product_payload,
    create_rack_price_posting_payload,
    create_set_clock_payload,
    create_storage_tank_payload,
    create_supply_agreement_payload,
    create_tax_remittance_payload,
    create_transport_drop_payload,
    create_truck_payload,
)
from .test_users import TEST_USERS, make_dealer_operator_headers

ADMIN = TEST_USERS["admin_headers"]
PRICING = TEST_USERS["pricing_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CREDIT = TEST_USERS["credit_headers"]
TAX = TEST_USERS["tax_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation
# ---------------------------------------------------------------------------


def create_gasoline_product(product_code="REGULAR_87"):
    return get_success_data(api_client.create_product(
        create_product_payload(product_code=product_code), ADMIN
    ))


def create_diesel_product(product_code="DIESEL_ULSD"):
    return get_success_data(api_client.create_product(
        create_product_payload(
            product_code=product_code,
            display_name="ULSD Diesel",
            category="DIESEL",
            federal_excise_tc_per_gal=244,
            temp_coeff=0.00040,
        ),
        ADMIN,
    ))


def create_station(state_code="TX", state_excise_tc_per_gal=200,
                   credit_limit_cents=100_000_000, activate=True,
                   local_option_tc_per_gal=None, credit_terms_days=None,
                   station_name="Test Station"):
    overrides = {}
    if local_option_tc_per_gal is not None:
        overrides["local_option_tc_per_gal"] = local_option_tc_per_gal
    if credit_terms_days is not None:
        overrides["credit_terms_days"] = credit_terms_days
    station = get_success_data(api_client.create_dealer_station(
        create_dealer_station_payload(
            station_name=station_name,
            state_code=state_code,
            state_excise_tc_per_gal=state_excise_tc_per_gal,
            credit_limit_cents=credit_limit_cents,
            **overrides,
        ),
        ADMIN,
    ))
    if activate:
        station = get_success_data(api_client.activate_dealer_station(station["id"], ADMIN))
    return station


def create_active_agreement(station_id, **overrides):
    agreement = get_success_data(api_client.create_supply_agreement(
        create_supply_agreement_payload(station_id=station_id, **overrides),
        ADMIN,
    ))
    agreement = get_success_data(api_client.activate_supply_agreement(agreement["id"], ADMIN))
    return agreement


def create_draft_agreement(station_id, **overrides):
    return get_success_data(api_client.create_supply_agreement(
        create_supply_agreement_payload(station_id=station_id, **overrides),
        ADMIN,
    ))


def create_posted_price(product_id, terminal_code="TX-NORTH",
                        effective_date="2026-05-01", price_tc_per_gal=2000):
    posting = get_success_data(api_client.create_rack_price_posting(
        create_rack_price_posting_payload(
            product_id=product_id,
            terminal_code=terminal_code,
            effective_date=effective_date,
            price_tc_per_gal=price_tc_per_gal,
        ),
        PRICING,
    ))
    posting = get_success_data(api_client.post_rack_price_posting(posting["id"], PRICING))
    return posting


def create_tank(station_id, product_id, capacity_gallons=20_000,
                opening_physical_gallons=0, safe_fill_pct=None):
    overrides = {}
    if safe_fill_pct is not None:
        overrides["safe_fill_pct"] = safe_fill_pct
    return get_success_data(api_client.create_storage_tank(
        create_storage_tank_payload(
            station_id=station_id,
            product_id=product_id,
            capacity_gallons=capacity_gallons,
            opening_physical_gallons=opening_physical_gallons,
            **overrides,
        ),
        ADMIN,
    ))


def create_truck(truck_code="TRK-1", capacity_gallons=12_000):
    return get_success_data(api_client.create_truck(
        create_truck_payload(truck_code=truck_code, capacity_gallons=capacity_gallons),
        ADMIN,
    ))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(
        create_set_clock_payload(to_iso8601), ADMIN
    ))


# ---------------------------------------------------------------------------
# Tier 2: full drop pipeline fixture
# ---------------------------------------------------------------------------


def setup_full_drop_fixture(
    state_code="TX",
    state_excise_tc_per_gal=200,
    credit_limit_cents=100_000_000,
    price_tc_per_gal=2000,
    price_effective_date="2026-05-01",
    tank_capacity=20_000,
    opening_physical=0,
    safe_fill_pct=None,
    truck_capacity=12_000,
    category="GASOLINE",
    product_code=None,
    committed_gallons=100_000,
    imaging_allowance_cents=100_000,
    margin_tc_per_gal=25,
    shortfall_penalty_tc_per_gal=20,
    buyout_method="LOST_MARGIN",
    term_start_date="2026-01-01",
    term_end_date="2026-12-31",
    local_option_tc_per_gal=None,
    credit_terms_days=None,
):
    """Product + ACTIVE station + ACTIVE agreement + POSTED price + tank + truck.

    Returns dict with keys: product, station, agreement, posting, tank, truck,
    and the matching dealer_operator headers for ownership-gated calls.
    """
    if product_code is None:
        product_code = "REGULAR_87" if category == "GASOLINE" else "DIESEL_ULSD"
    if category == "GASOLINE":
        product = create_gasoline_product(product_code=product_code)
    else:
        product = create_diesel_product(product_code=product_code)
    station = create_station(
        state_code=state_code,
        state_excise_tc_per_gal=state_excise_tc_per_gal,
        credit_limit_cents=credit_limit_cents,
        local_option_tc_per_gal=local_option_tc_per_gal,
        credit_terms_days=credit_terms_days,
    )
    agreement = create_active_agreement(
        station["id"],
        committed_gallons=committed_gallons,
        imaging_allowance_cents=imaging_allowance_cents,
        margin_tc_per_gal=margin_tc_per_gal,
        shortfall_penalty_tc_per_gal=shortfall_penalty_tc_per_gal,
        buyout_method=buyout_method,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
    )
    posting = create_posted_price(
        product["id"],
        terminal_code=station["home_terminal_code"],
        effective_date=price_effective_date,
        price_tc_per_gal=price_tc_per_gal,
    )
    tank = create_tank(
        station["id"], product["id"],
        capacity_gallons=tank_capacity,
        opening_physical_gallons=opening_physical,
        safe_fill_pct=safe_fill_pct,
    )
    truck = create_truck(capacity_gallons=truck_capacity)
    return {
        "product": product,
        "station": station,
        "agreement": agreement,
        "posting": posting,
        "tank": tank,
        "truck": truck,
        "dealer_headers": make_dealer_operator_headers(station["id"]),
    }


def create_drop(fixture, planned_gallons=1000,
                window_start="2026-05-02T08:00:00Z",
                window_end="2026-05-02T12:00:00Z",
                truck_id=None, tank_id=None):
    """Create a PLANNED drop against a full fixture."""
    return get_success_data(api_client.create_transport_drop(
        create_transport_drop_payload(
            station_id=fixture["station"]["id"],
            tank_id=tank_id or fixture["tank"]["id"],
            truck_id=truck_id or fixture["truck"]["id"],
            product_id=fixture["product"]["id"],
            planned_gallons=planned_gallons,
            window_start=window_start,
            window_end=window_end,
        ),
        DISPATCH,
    ))


def schedule_drop(drop_id):
    return get_success_data(api_client.schedule_transport_drop(drop_id, DISPATCH))


def dispatch_drop(drop_id):
    return get_success_data(api_client.dispatch_transport_drop(drop_id, DISPATCH))


def deliver_drop(drop_id, delivered_gallons):
    return get_success_data(api_client.deliver_transport_drop(
        drop_id, {"delivered_gallons": delivered_gallons}, DISPATCH
    ))


def reconcile_drop(drop_id):
    return get_success_data(api_client.reconcile_transport_drop(drop_id, DISPATCH))


def create_and_deliver_drop(fixture, planned_gallons=1000,
                            delivered_gallons=None,
                            window_start="2026-05-02T08:00:00Z",
                            window_end="2026-05-02T12:00:00Z"):
    """Create → schedule → dispatch → deliver. Returns delivered drop dict."""
    if delivered_gallons is None:
        delivered_gallons = planned_gallons
    drop = create_drop(fixture, planned_gallons=planned_gallons,
                       window_start=window_start, window_end=window_end)
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    return deliver_drop(drop["id"], delivered_gallons)


def create_and_reconcile_drop(fixture, planned_gallons=1000,
                              delivered_gallons=None,
                              window_start="2026-05-02T08:00:00Z",
                              window_end="2026-05-02T12:00:00Z"):
    """Create → schedule → dispatch → deliver → reconcile."""
    delivered = create_and_deliver_drop(
        fixture,
        planned_gallons=planned_gallons,
        delivered_gallons=delivered_gallons,
        window_start=window_start,
        window_end=window_end,
    )
    return reconcile_drop(delivered["id"])


# ---------------------------------------------------------------------------
# Tier 3: gauge / meter / loss / reconciliation helpers
# ---------------------------------------------------------------------------


def gauge_tank(fixture, tank_id, reading_gallons, observed_temp_f):
    return get_success_data(api_client.gauge_storage_tank(
        tank_id,
        {"reading_gallons": reading_gallons, "observed_temp_f": observed_temp_f},
        fixture["dealer_headers"],
    ))


def submit_meter_reading(fixture, tank_id, reading_at, totalizer_gallons):
    return get_success_data(api_client.create_meter_reading(
        create_meter_reading_payload(
            tank_id=tank_id, reading_at=reading_at, totalizer_gallons=totalizer_gallons
        ),
        fixture["dealer_headers"],
    ))


def report_loss(fixture, gallons, loss_type="SPILL", tank_id=None,
                occurred_at="2026-05-03T09:00:00Z"):
    payload = create_loss_event_payload(
        station_id=fixture["station"]["id"],
        loss_type=loss_type,
        gallons=gallons,
        occurred_at=occurred_at,
    )
    if tank_id is not None:
        payload["tank_id"] = tank_id
    return get_success_data(api_client.create_loss_event(payload, fixture["dealer_headers"]))


def open_reconciliation(station_id, period_start="2026-05-01", period_end="2026-05-31",
                        threshold_gallons=None, opener_headers=None):
    payload = create_inventory_reconciliation_payload(
        station_id=station_id, period_start=period_start, period_end=period_end
    )
    if threshold_gallons is not None:
        payload["threshold_gallons"] = threshold_gallons
    return get_success_data(api_client.create_inventory_reconciliation(
        payload, opener_headers or ADMIN
    ))


# ---------------------------------------------------------------------------
# Tier 4: invoice / draft helpers
# ---------------------------------------------------------------------------


def schedule_eft_draft(invoice_id, scheduled_date):
    return get_success_data(api_client.create_eft_draft(
        create_eft_draft_payload(invoice_id=invoice_id, scheduled_date=scheduled_date),
        CREDIT,
    ))


def execute_draft(draft_id, outcome="SUCCEEDED"):
    return get_success_data(api_client.execute_eft_draft(
        draft_id, {"outcome": outcome}, CREDIT
    ))


def void_invoice(invoice_id):
    return get_success_data(api_client.void_invoice(invoice_id, CREDIT))


# ---------------------------------------------------------------------------
# Tier 5: tax / audit helpers
# ---------------------------------------------------------------------------


def open_tax_remittance(state_code="TX", period_start="2026-05-01",
                        period_end="2026-05-31"):
    return get_success_data(api_client.create_tax_remittance(
        create_tax_remittance_payload(
            state_code=state_code, period_start=period_start, period_end=period_end
        ),
        TAX,
    ))


def record_audit(station_id, score, audit_date="2026-05-10", deficiencies=None):
    payload = create_brand_compliance_audit_payload(
        station_id=station_id, audit_date=audit_date, score=score
    )
    if deficiencies is not None:
        payload["deficiencies"] = deficiencies
    return get_success_data(api_client.create_brand_compliance_audit(payload, INSPECTOR))
