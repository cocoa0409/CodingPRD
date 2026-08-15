"""Composite setup helpers.

The interesting claims in this PRD require the system to be in a state that
takes 5-15 API calls to reach (a graded lot, a confirmed order, a committed
allocation, a published quote series). These helpers build those states from
scratch using only PRD-declared endpoints. Every call uses the lenient
`get_success_data` validator so setup failures surface as "Setup step failed"
rather than confusing assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_LANDING_START,
    DEFAULT_LANDING_END,
    DEFAULT_QUOTE_DATE,
    DEFAULT_DELIVERY_DATE,
)
from .factories import (
    create_vessel_payload,
    create_customer_payload,
    create_catch_area_payload,
    create_species_payload,
    create_market_quote_payload,
    create_dock_ticket_payload,
    create_landing_line_payload,
    create_grade_assessment_payload,
    create_sales_order_payload,
    create_order_line_payload,
    create_allocation_payload,
    create_shipment_payload,
    create_import_document_payload,
    create_inspection_hold_payload,
)
from .test_users import TEST_USERS, make_customer_headers

OM = TEST_USERS["operations_manager_headers"]
DB = TEST_USERS["dock_buyer_headers"]
GI = TEST_USERS["grading_inspector_headers"]
IP = TEST_USERS["inventory_planner_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_vessel(**overrides) -> dict:
    return get_success_data(api_client.create_vessel(create_vessel_payload(**overrides), OM))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), OM))


def create_catch_area(**overrides) -> dict:
    return get_success_data(api_client.create_catch_area(create_catch_area_payload(**overrides), OM))


def create_species(**overrides) -> dict:
    return get_success_data(api_client.create_species(create_species_payload(**overrides), OM))


def create_draft_quote(species_id, grade="GRADE_A", quote_date=DEFAULT_QUOTE_DATE,
                       price_per_kg_cents=1200, headers=None) -> dict:
    payload = create_market_quote_payload(
        species_id=species_id, grade=grade, quote_date=quote_date,
        price_per_kg_cents=price_per_kg_cents,
    )
    return get_success_data(api_client.create_market_quote(payload, headers or OM))


def get_species_version(species_id) -> int:
    return get_success_data(api_client.get_species(species_id, OM))["version"]


def publish_quote(quote_id, headers=None) -> dict:
    """Publish with a freshly-read species version (OCC, PRD §2.7)."""
    quote = get_success_data(api_client.get_market_quote(quote_id, headers or OM))
    version = get_species_version(quote["species_id"])
    return get_success_data(
        api_client.publish_market_quote(quote_id, {"expected_species_version": version}, headers or OM)
    )


def create_and_publish_quote(species_id, grade="GRADE_A", quote_date=DEFAULT_QUOTE_DATE,
                             price_per_kg_cents=1200, headers=None) -> dict:
    quote = create_draft_quote(species_id, grade, quote_date, price_per_kg_cents, headers)
    return publish_quote(quote["id"], headers)


# ---------------------------------------------------------------------------
# Tier 1: dock ticket state progression
# ---------------------------------------------------------------------------

def create_dock_ticket(vessel_id, catch_area_id,
                       landing_start_at=DEFAULT_LANDING_START,
                       landing_end_at=DEFAULT_LANDING_END, headers=None) -> dict:
    payload = create_dock_ticket_payload(
        vessel_id=vessel_id, catch_area_id=catch_area_id,
        landing_start_at=landing_start_at, landing_end_at=landing_end_at,
    )
    return get_success_data(api_client.create_dock_ticket(payload, headers or DB))


def land_ticket(ticket_id, headers=None) -> dict:
    return get_success_data(api_client.land_dock_ticket(ticket_id, headers or DB))


def get_ticket(ticket_id) -> dict:
    return get_success_data(api_client.get_dock_ticket(ticket_id, OM))


def get_ticket_version(ticket_id) -> int:
    return get_ticket(ticket_id)["version"]


def add_landing_line(ticket_id, species_id, declared_grade="GRADE_A",
                     landed_weight_kg=50.00, processing_type=None, headers=None) -> dict:
    """Add a line, threading the current ticket version into the OCC field."""
    payload = create_landing_line_payload(
        dock_ticket_id=ticket_id, species_id=species_id,
        declared_grade=declared_grade, landed_weight_kg=landed_weight_kg,
        expected_dock_ticket_version=get_ticket_version(ticket_id),
    )
    if processing_type is not None:
        payload["processing_type"] = processing_type
    return get_success_data(api_client.create_landing_line(payload, headers or DB))


def create_assessment(line_id, assessed_grade="GRADE_A", yield_pct=1.00,
                      headers=None) -> dict:
    payload = create_grade_assessment_payload(
        landing_line_id=line_id, assessed_grade=assessed_grade, yield_pct=yield_pct,
    )
    return get_success_data(api_client.create_grade_assessment(payload, headers or GI))


def finalize_assessment(assessment_id, headers=None) -> dict:
    return get_success_data(api_client.finalize_grade_assessment(assessment_id, headers or GI))


def create_and_finalize_assessment(line_id, assessed_grade="GRADE_A",
                                   yield_pct=1.00, headers=None) -> dict:
    assessment = create_assessment(line_id, assessed_grade, yield_pct, headers)
    return finalize_assessment(assessment["id"], headers)


def get_lot_for_line(line_id) -> dict:
    """The inventory lot birthed by finalizing this line's assessment (PRD §3.4)."""
    data, meta = validate_paginated(
        api_client.list_inventory_lots(OM, params={"landing_line_id": line_id})
    )
    assert len(data) >= 1, f"Setup failed: no inventory lot for landing line {line_id}"
    return data[0]


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, OM))


# ---------------------------------------------------------------------------
# Tier 2: the standard landing chain — vessel/area/species/quotes through to
# a graded ticket with a live inventory lot.
# ---------------------------------------------------------------------------

def setup_graded_lot(landed_weight_kg=50.00, declared_grade="GRADE_A",
                     assessed_grade="GRADE_A", yield_pct=1.00,
                     processing_type=None, quote_prices=None,
                     species_overrides=None, vessel=None, catch_area=None,
                     quote_date=DEFAULT_QUOTE_DATE,
                     landing_start_at=DEFAULT_LANDING_START,
                     landing_end_at=DEFAULT_LANDING_END) -> dict:
    """Full landing chain: vessel + catch area + species + published quotes
    -> ticket LANDED -> one landing line -> assessment FINAL -> inventory lot.

    `quote_prices` maps grade -> cents/kg; a quote is published for each entry.
    Both the declared grade (provisional settlement, PRD §3.3) and the assessed
    grade (final settlement, PRD §3.4) need a quote dated on the landing day.

    Returns dict(vessel, catch_area, species, quotes, ticket, line, assessment, lot).
    """
    vessel = vessel or create_vessel()
    catch_area = catch_area or create_catch_area()
    species = create_species(**(species_overrides or {}))
    if quote_prices is None:
        quote_prices = {declared_grade: 1200}
        if assessed_grade != declared_grade:
            quote_prices[assessed_grade] = 950
    quotes = {
        grade: create_and_publish_quote(species["id"], grade=grade,
                                        quote_date=quote_date, price_per_kg_cents=price)
        for grade, price in quote_prices.items()
    }
    ticket = create_dock_ticket(vessel["id"], catch_area["id"],
                                landing_start_at=landing_start_at,
                                landing_end_at=landing_end_at)
    land_ticket(ticket["id"])
    line = add_landing_line(ticket["id"], species["id"], declared_grade,
                            landed_weight_kg, processing_type)
    assessment = create_and_finalize_assessment(line["id"], assessed_grade, yield_pct)
    lot = get_lot_for_line(line["id"])
    return {
        "vessel": vessel, "catch_area": catch_area, "species": species,
        "quotes": quotes, "ticket": get_ticket(ticket["id"]),
        "line": get_success_data(api_client.get_landing_line(line["id"], OM)),
        "assessment": assessment, "lot": lot,
    }


# ---------------------------------------------------------------------------
# Tier 2: sales order progression — DRAFT -> SUBMITTED -> CONFIRMED.
# Customer calls are ownership-gated (PRD §2.1), so the customer's own id is
# threaded into X-User-ID.
# ---------------------------------------------------------------------------

def create_order_with_lines(customer_id, lines) -> dict:
    """Create a DRAFT order for the customer with the given line specs.
    Each line spec: dict(species_id, requested_qty_kg, requested_grade="GRADE_A",
    plus optional min_remaining_shelf_life_hours / allow_substitution)."""
    cust_headers = make_customer_headers(customer_id)
    order = get_success_data(api_client.create_sales_order(
        create_sales_order_payload(customer_id=customer_id), cust_headers))
    created = []
    for spec in lines:
        payload = create_order_line_payload(
            sales_order_id=order["id"], species_id=spec["species_id"],
            requested_grade=spec.get("requested_grade", "GRADE_A"),
            requested_qty_kg=spec.get("requested_qty_kg", 10.00),
        )
        if "min_remaining_shelf_life_hours" in spec:
            payload["min_remaining_shelf_life_hours"] = spec["min_remaining_shelf_life_hours"]
        if "allow_substitution" in spec:
            payload["allow_substitution"] = spec["allow_substitution"]
        created.append(get_success_data(api_client.create_order_line(payload, cust_headers)))
    return {"order": order, "lines": created}


def submit_order(order_id, customer_id) -> dict:
    return get_success_data(
        api_client.submit_sales_order(order_id, make_customer_headers(customer_id)))


def confirm_order(order_id) -> dict:
    return get_success_data(api_client.confirm_sales_order(order_id, OM))


def setup_confirmed_order(customer, lines) -> dict:
    """DRAFT -> SUBMITTED -> CONFIRMED. Returns dict(customer, order, lines)."""
    built = create_order_with_lines(customer["id"], lines)
    submit_order(built["order"]["id"], customer["id"])
    order = confirm_order(built["order"]["id"])
    return {"customer": customer, "order": order, "lines": built["lines"]}


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_sales_order(order_id, OM))


def get_order_version(order_id) -> int:
    return get_order(order_id)["version"]


def get_order_line(line_id) -> dict:
    return get_success_data(api_client.get_order_line(line_id, OM))


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, OM))


# ---------------------------------------------------------------------------
# Tier 3: allocations against a confirmed order (OCC on order version).
# ---------------------------------------------------------------------------

def create_allocation(order_id, order_line_id, lot_id, qty_kg=10.00,
                      transit_hours=8, headers=None) -> dict:
    payload = create_allocation_payload(
        order_line_id=order_line_id, inventory_lot_id=lot_id, qty_kg=qty_kg,
        transit_hours=transit_hours,
        expected_sales_order_version=get_order_version(order_id),
    )
    return get_success_data(api_client.create_allocation(payload, headers or IP))


def commit_allocation(allocation_id, headers=None) -> dict:
    return get_success_data(api_client.commit_allocation(allocation_id, headers or IP))


def get_allocation(allocation_id) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, OM))


def list_allocations_for_line(order_line_id):
    data, _ = validate_paginated(
        api_client.list_allocations(OM, params={"order_line_id": order_line_id}))
    return data


def list_allocations_for_lot(lot_id):
    data, _ = validate_paginated(
        api_client.list_allocations(OM, params={"inventory_lot_id": lot_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 4: composite sales scenarios (lot + confirmed order [+ allocation]).
# ---------------------------------------------------------------------------

def setup_lot_and_confirmed_order(line_qty_kg=10.00, lot_landed_weight_kg=50.00,
                                  min_remaining_shelf_life_hours=None,
                                  allow_substitution=None,
                                  lot_kwargs=None, customer_overrides=None) -> dict:
    """A graded lot plus a confirmed one-line order for the same species.
    Returns dict of the landing chain plus customer/order/line."""
    landing = setup_graded_lot(landed_weight_kg=lot_landed_weight_kg, **(lot_kwargs or {}))
    customer = create_customer(**(customer_overrides or {}))
    line_spec = {"species_id": landing["species"]["id"], "requested_qty_kg": line_qty_kg}
    if min_remaining_shelf_life_hours is not None:
        line_spec["min_remaining_shelf_life_hours"] = min_remaining_shelf_life_hours
    if allow_substitution is not None:
        line_spec["allow_substitution"] = allow_substitution
    order_ctx = setup_confirmed_order(customer, [line_spec])
    return {**landing, "customer": customer, "order": order_ctx["order"],
            "line_o": order_ctx["lines"][0]}


def setup_reserved_allocation(line_qty_kg=10.00, alloc_qty_kg=None,
                              lot_landed_weight_kg=50.00, transit_hours=8,
                              **kwargs) -> dict:
    """Lot + confirmed order + one RESERVED allocation."""
    ctx = setup_lot_and_confirmed_order(line_qty_kg=line_qty_kg,
                                        lot_landed_weight_kg=lot_landed_weight_kg,
                                        **kwargs)
    allocation = create_allocation(
        ctx["order"]["id"], ctx["line_o"]["id"], ctx["lot"]["id"],
        qty_kg=alloc_qty_kg if alloc_qty_kg is not None else line_qty_kg,
        transit_hours=transit_hours,
    )
    return {**ctx, "allocation": allocation}


def setup_committed_allocation(line_qty_kg=10.00, alloc_qty_kg=None,
                               lot_landed_weight_kg=50.00, transit_hours=8,
                               **kwargs) -> dict:
    """Lot + confirmed order + one COMMITTED allocation (order FULFILLED when
    the allocation covers the whole line)."""
    ctx = setup_reserved_allocation(line_qty_kg=line_qty_kg, alloc_qty_kg=alloc_qty_kg,
                                    lot_landed_weight_kg=lot_landed_weight_kg,
                                    transit_hours=transit_hours, **kwargs)
    committed = commit_allocation(ctx["allocation"]["id"])
    return {**ctx, "allocation": committed}


# ---------------------------------------------------------------------------
# Tier 3/5: shipments through the cold chain.
# ---------------------------------------------------------------------------

def create_shipment(order_id, mode="TRUCK", booked_weight_kg=10.00,
                    temp_zone="CHILLED", flight_number=None, flight_date=None,
                    headers=None) -> dict:
    payload = create_shipment_payload(
        sales_order_id=order_id, mode=mode, booked_weight_kg=booked_weight_kg,
        temp_zone=temp_zone,
    )
    if flight_number is not None:
        payload["flight_number"] = flight_number
    if flight_date is not None:
        payload["flight_date"] = flight_date
    return get_success_data(api_client.create_shipment(payload, headers or LC))


def get_shipment(shipment_id) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, OM))


def setup_booked_shipment(order_id, mode="TRUCK", booked_weight_kg=10.00,
                          temp_zone="CHILLED", flight_number=None,
                          flight_date=None) -> dict:
    shipment = create_shipment(order_id, mode, booked_weight_kg, temp_zone,
                               flight_number, flight_date)
    return get_success_data(api_client.book_shipment(shipment["id"], LC))


def setup_in_transit_shipment(order_id, mode="TRUCK", booked_weight_kg=10.00,
                              temp_zone="CHILLED", actual_weight_kg=None,
                              volume_m3=0.10) -> dict:
    booked = setup_booked_shipment(order_id, mode, booked_weight_kg, temp_zone)
    tendered = get_success_data(api_client.tender_shipment(
        booked["id"],
        {"actual_weight_kg": actual_weight_kg if actual_weight_kg is not None else booked_weight_kg,
         "volume_m3": volume_m3},
        LC))
    return get_success_data(api_client.depart_shipment(tendered["id"], LC))


# ---------------------------------------------------------------------------
# Tier 1: compliance records (import documents, inspection holds).
# ---------------------------------------------------------------------------

def create_import_document(ticket_id, species_id, doc_type="HEALTH_CERT",
                           reference_number=None, headers=None) -> dict:
    payload = create_import_document_payload(
        dock_ticket_id=ticket_id, species_id=species_id, doc_type=doc_type,
    )
    if reference_number is not None:
        payload["reference_number"] = reference_number
    return get_success_data(api_client.create_import_document(payload, headers or CO))


def clear_document(doc_id, submit_headers, clear_headers) -> dict:
    """Submit then clear, with two distinct officers (PRD §2.10)."""
    get_success_data(api_client.submit_import_document(doc_id, submit_headers))
    return get_success_data(api_client.clear_import_document(doc_id, clear_headers))


def create_inspection_hold(lot_id, reason="spot check", headers=None) -> dict:
    payload = create_inspection_hold_payload(inventory_lot_id=lot_id, reason=reason)
    return get_success_data(api_client.create_inspection_hold(payload, headers or CO))


def get_hold(hold_id) -> dict:
    return get_success_data(api_client.get_inspection_hold(hold_id, OM))


def get_vessel(vessel_id) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, OM))


def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, OM))
