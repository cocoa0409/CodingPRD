"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server before every test, so each test
starts against an empty database. Setup calls use get_success_data() so a
setup failure surfaces as a clear error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BID_DUE_DATE, CLOCK_START, ORDER_BY_DATE, STANDARD_TIER_TABLE,
    TEST_DEFAULTS, WINDOW_END, WINDOW_START,
)
from .factories import (
    create_award_payload, create_bid_spec_payload, create_coop_agreement_payload,
    create_crew_payload, create_damage_report_payload, create_district_payload,
    create_install_task_payload, create_po_line_payload,
    create_purchase_order_payload, create_school_site_payload,
    create_shipment_payload, create_spec_line_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS, make_crew_lead_headers, make_district_buyer_headers,
)

D = TEST_DEFAULTS
ADMIN = TEST_USERS["admin_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]
COORDINATOR = TEST_USERS["fulfillment_coordinator_headers"]
SERVICE_AGENT = TEST_USERS["service_agent_headers"]


# ---------------------------------------------------------------------------
# Tier 0/1: single-entity creation and state progression primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Drive the logical clock (PRD §2.5). Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_district(name="District D1", annual_cap_cents=None,
                    extended_warranty_enrolled=None) -> dict:
    payload = create_district_payload(
        name=name,
        annual_cap_cents=annual_cap_cents if annual_cap_cents is not None else D["ANNUAL_CAP_CENTS"],
    )
    if extended_warranty_enrolled is not None:
        payload["extended_warranty_enrolled"] = extended_warranty_enrolled
    return get_success_data(api_client.create_district(payload, ADMIN))


def create_site(district_id: str, name="West ES", daily_crew_capacity=None) -> dict:
    payload = create_school_site_payload(
        district_id=district_id, name=name,
        daily_crew_capacity=daily_crew_capacity if daily_crew_capacity is not None else D["SITE_CAPACITY"],
    )
    return get_success_data(api_client.create_school_site(payload, make_district_buyer_headers(district_id)))


def create_crew(name="Crew Alpha") -> dict:
    return get_success_data(api_client.create_crew(create_crew_payload(name=name), ADMIN))


def create_coop(name="Coop C1", contract_year=None, tier_table=None) -> dict:
    payload = create_coop_agreement_payload(
        name=name,
        contract_year=contract_year if contract_year is not None else D["FISCAL_YEAR"],
        tier_table=tier_table if tier_table is not None else STANDARD_TIER_TABLE,
    )
    return get_success_data(api_client.create_coop_agreement(payload, CONTRACT_MANAGER))


def create_spec(district_id: str, title="Spec A", bid_due_date=BID_DUE_DATE,
                window_start=WINDOW_START, window_end=WINDOW_END) -> dict:
    payload = create_bid_spec_payload(
        district_id=district_id, title=title, bid_due_date=bid_due_date,
        delivery_window_start=window_start, delivery_window_end=window_end,
    )
    return get_success_data(api_client.create_bid_spec(payload, make_district_buyer_headers(district_id)))


def add_spec_line(spec_id: str, district_id: str, manufacturer=None, model=None,
                  qty=None, max_unit_price_cents=None) -> dict:
    payload = create_spec_line_payload(
        bid_spec_id=spec_id,
        manufacturer=manufacturer or D["MANUFACTURER"],
        model=model or D["MODEL"],
        qty=qty if qty is not None else D["SPEC_LINE_QTY"],
        max_unit_price_cents=max_unit_price_cents if max_unit_price_cents is not None else D["MAX_UNIT_PRICE_CENTS"],
    )
    return get_success_data(api_client.create_spec_line(payload, make_district_buyer_headers(district_id)))


def publish_spec(spec_id: str, district_id: str) -> dict:
    return get_success_data(api_client.publish_bid_spec(spec_id, make_district_buyer_headers(district_id)))


def issue_addendum(spec_id: str, district_id: str, note="clarification") -> dict:
    return get_success_data(api_client.issue_addendum(
        spec_id, {"addendum_note": note}, make_district_buyer_headers(district_id)))


def close_spec(spec_id: str, district_id: str) -> dict:
    return get_success_data(api_client.close_bid_spec(spec_id, make_district_buyer_headers(district_id)))


def get_spec(spec_id: str, district_id: str) -> dict:
    return get_success_data(api_client.get_bid_spec(spec_id, make_district_buyer_headers(district_id)))


def create_award(spec_id: str, district_id: str, pricing_mode="AWARD_FLAT",
                 coop_agreement_id=None, flat_unit_price_cents=None,
                 install_rate_cents=None, order_by_date=ORDER_BY_DATE,
                 warranty_years=None, extended_years=0) -> dict:
    payload = {
        "bid_spec_id": spec_id,
        "district_id": district_id,
        "pricing_mode": pricing_mode,
        "install_rate_cents": install_rate_cents if install_rate_cents is not None else D["INSTALL_RATE_CENTS"],
        "order_by_date": order_by_date,
        "warranty_years": warranty_years if warranty_years is not None else D["WARRANTY_YEARS"],
        "extended_years": extended_years,
    }
    if pricing_mode == "COOP_TIERED":
        payload["coop_agreement_id"] = coop_agreement_id
    else:
        payload["flat_unit_price_cents"] = (
            flat_unit_price_cents if flat_unit_price_cents is not None else D["FLAT_UNIT_PRICE_CENTS"])
    return get_success_data(api_client.create_award(payload, make_district_buyer_headers(district_id)))


def accept_award(award_id: str) -> dict:
    """ContractManager accepts: ISSUED -> ACCEPTED (PRD §3.3)."""
    return get_success_data(api_client.accept_award(award_id, CONTRACT_MANAGER))


def get_award(award_id: str) -> dict:
    return get_success_data(api_client.get_award(award_id, CONTRACT_MANAGER))


def create_po(award_id: str, district_id: str, po_number="PO-1", fiscal_year=None) -> dict:
    payload = create_purchase_order_payload(
        award_id=award_id, po_number=po_number,
        fiscal_year=fiscal_year if fiscal_year is not None else D["FISCAL_YEAR"],
    )
    return get_success_data(api_client.create_purchase_order(payload, make_district_buyer_headers(district_id)))


def get_po(po_id: str) -> dict:
    return get_success_data(api_client.get_purchase_order(po_id, COORDINATOR))


def add_po_line(po_id: str, spec_line_id: str, district_id: str, ordered_qty=10,
                extra=None) -> dict:
    payload = create_po_line_payload(
        purchase_order_id=po_id, spec_line_id=spec_line_id, ordered_qty=ordered_qty)
    if extra:
        payload.update(extra)
    return get_success_data(api_client.create_po_line(payload, make_district_buyer_headers(district_id)))


def accept_po(po_id: str) -> dict:
    """FulfillmentCoordinator accepts: RECEIVED -> ACCEPTED, lines -> ORDERED (PRD §3.4)."""
    return get_success_data(api_client.accept_purchase_order(po_id, COORDINATOR))


def cancel_po(po_id: str, district_id: str) -> dict:
    return get_success_data(api_client.cancel_purchase_order(po_id, make_district_buyer_headers(district_id)))


def cancel_po_line(line_id: str, district_id: str) -> dict:
    return get_success_data(api_client.cancel_po_line(line_id, make_district_buyer_headers(district_id)))


def get_po_line(line_id: str) -> dict:
    return get_success_data(api_client.get_po_line(line_id, COORDINATOR))


def get_spec_line(line_id: str, district_id: str) -> dict:
    return get_success_data(api_client.get_spec_line(line_id, make_district_buyer_headers(district_id)))


def declare_backorder(line_id: str, initial_eta_date: str) -> dict:
    return get_success_data(api_client.declare_backorder(
        line_id, {"initial_eta_date": initial_eta_date}, COORDINATOR))


def create_shipment(po_id: str, site_id: str, line_entries, scheduled_date="2026-07-01",
                    kind=None) -> dict:
    """line_entries: list of {"po_line_id": ..., "qty": ...}."""
    payload = create_shipment_payload(
        purchase_order_id=po_id, school_site_id=site_id,
        scheduled_date=scheduled_date, lines=line_entries,
    )
    if kind is not None:
        payload["kind"] = kind
    return get_success_data(api_client.create_shipment(payload, COORDINATOR))


def deliver_shipment(shipment_id: str, delivery_entries) -> dict:
    """delivery_entries: list of {po_line_id, delivered_qty, manufacturer, model}."""
    return get_success_data(api_client.mark_delivered(shipment_id, {"lines": delivery_entries}, COORDINATOR))


def create_task(shipment_id: str, crew_id: str, site_id: str, start_date="2026-07-06",
                end_date="2026-07-08", crew_count=1, room_label="W-12") -> dict:
    payload = create_install_task_payload(
        shipment_id=shipment_id, crew_id=crew_id, school_site_id=site_id,
        room_label=room_label, start_date=start_date, end_date=end_date,
        crew_count=crew_count,
    )
    return get_success_data(api_client.create_install_task(payload, COORDINATOR))


def start_task(task_id: str, crew_id: str) -> dict:
    return get_success_data(api_client.start_install_task(task_id, make_crew_lead_headers(crew_id)))


def complete_task(task_id: str, crew_id: str, uncrated=True, debris_removed=True, placed=True) -> dict:
    payload = {"uncrated": uncrated, "debris_removed": debris_removed, "placed": placed}
    return get_success_data(api_client.complete_install_task(task_id, payload, make_crew_lead_headers(crew_id)))


def get_crew(crew_id: str) -> dict:
    return get_success_data(api_client.get_crew(crew_id, COORDINATOR))


def file_damage_report(po_line_id: str, damaged_qty: int, crew_id: str,
                       discovered_during="DELIVERY", fault_type="TRANSIT",
                       shipment_id=None, install_task_id=None) -> dict:
    payload = create_damage_report_payload(
        po_line_id=po_line_id, damaged_qty=damaged_qty,
        discovered_during=discovered_during, fault_type=fault_type,
    )
    if shipment_id is not None:
        payload["shipment_id"] = shipment_id
    if install_task_id is not None:
        payload["install_task_id"] = install_task_id
    return get_success_data(api_client.create_damage_report(payload, make_crew_lead_headers(crew_id)))


def file_warranty_claim(po_line_id: str, district_id: str, parts_cost_cents=5000,
                        description="glide failure") -> dict:
    payload = create_warranty_claim_payload(
        po_line_id=po_line_id, parts_cost_cents=parts_cost_cents, description=description)
    return get_success_data(api_client.create_warranty_claim(payload, make_district_buyer_headers(district_id)))


def list_notices_for_line(po_line_id: str) -> list:
    data, _meta = _list(api_client.list_backorder_notices(COORDINATOR, params={"po_line_id": po_line_id}))
    return data


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — district + spec/line + award (+ site + crew)
# ---------------------------------------------------------------------------

def build_awarded_context(pricing_mode="AWARD_FLAT", flat_unit_price_cents=None,
                          tier_table=None, contract_year=None,
                          district_name="District D1", annual_cap_cents=None,
                          extended_warranty_enrolled=None,
                          line_qty=None, max_unit_price_cents=None,
                          install_rate_cents=None, order_by_date=ORDER_BY_DATE,
                          warranty_years=None, extended_years=0,
                          site_capacity=None, with_site=True, with_crew=True,
                          clock=CLOCK_START) -> dict:
    """District (+site +crew) + spec with one line, published, closed, awarded,
    award ACCEPTED. Returns a ctx dict of the created entities."""
    set_clock(clock)
    district = create_district(
        name=district_name,
        annual_cap_cents=annual_cap_cents,
        extended_warranty_enrolled=extended_warranty_enrolled,
    )
    d_id = district["id"]
    coop = None
    if pricing_mode == "COOP_TIERED":
        coop = create_coop(contract_year=contract_year, tier_table=tier_table)
    site = create_site(d_id, daily_crew_capacity=site_capacity) if with_site else None
    crew = create_crew() if with_crew else None
    spec = create_spec(d_id)
    spec_line = add_spec_line(
        spec["id"], d_id, qty=line_qty, max_unit_price_cents=max_unit_price_cents)
    publish_spec(spec["id"], d_id)
    close_spec(spec["id"], d_id)
    award = create_award(
        spec["id"], d_id, pricing_mode=pricing_mode,
        coop_agreement_id=coop["id"] if coop else None,
        flat_unit_price_cents=flat_unit_price_cents,
        install_rate_cents=install_rate_cents, order_by_date=order_by_date,
        warranty_years=warranty_years, extended_years=extended_years,
    )
    # Re-read the spec: award creation cascades it CLOSED -> AWARDED (PRD §3.3).
    spec = get_spec(spec["id"], d_id)
    return {
        "district": district, "coop": coop, "site": site, "crew": crew,
        "spec": spec, "spec_line": spec_line, "award": award,
    }


def build_accepted_award_context(**kwargs) -> dict:
    """build_awarded_context + award accepted (ISSUED -> ACCEPTED)."""
    ctx = build_awarded_context(**kwargs)
    ctx["award"] = accept_award(ctx["award"]["id"])
    return ctx


def build_awarded_and_accepted(pricing_mode="AWARD_FLAT", **kwargs) -> dict:
    """Alias of build_accepted_award_context for readability at call sites."""
    return build_accepted_award_context(pricing_mode=pricing_mode, **kwargs)


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — PO + lines + acceptance + delivery + install
# ---------------------------------------------------------------------------

def add_accepted_po(ctx: dict, po_number="PO-1", fiscal_year=None, line_qtys=(10,)):
    """Create a PO on ctx's accepted award, add lines against ctx's spec line,
    accept the PO (lines PENDING -> ORDERED). Returns (po, lines)."""
    po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number=po_number,
                   fiscal_year=fiscal_year)
    lines = [add_po_line(po["id"], ctx["spec_line"]["id"], ctx["district"]["id"], q)
             for q in line_qtys]
    po = accept_po(po["id"])
    return po, lines


def ship_and_deliver(ctx: dict, po: dict, lines: list, qtys=None,
                     scheduled_date="2026-07-01") -> dict:
    """Schedule one shipment covering the given lines and mark it delivered with
    the pinned manufacturer/model. Returns the DELIVERED shipment."""
    qtys = qtys if qtys is not None else [l["ordered_qty"] for l in lines]
    entries = [{"po_line_id": l["id"], "qty": q} for l, q in zip(lines, qtys)]
    shipment = create_shipment(po["id"], ctx["site"]["id"], entries,
                               scheduled_date=scheduled_date)
    delivery = [{
        "po_line_id": l["id"],
        "delivered_qty": q,
        "manufacturer": ctx["spec_line"]["manufacturer"],
        "model": ctx["spec_line"]["model"],
    } for l, q in zip(lines, qtys)]
    return deliver_shipment(shipment["id"], delivery)


def install_and_complete(ctx: dict, shipment: dict, start_date="2026-07-06",
                         end_date="2026-07-08", crew_count=1,
                         complete_clock="2026-07-08T10:00:00Z",
                         room_label="W-12") -> dict:
    """Create task on ctx's crew, start it, complete with the full checklist.
    The completion stamps installed_at from the logical clock (PRD §3.6)."""
    task = create_task(shipment["id"], ctx["crew"]["id"], ctx["site"]["id"],
                       start_date=start_date, end_date=end_date,
                       crew_count=crew_count, room_label=room_label)
    start_task(task["id"], ctx["crew"]["id"])
    if complete_clock is not None:
        set_clock(complete_clock)
    return complete_task(task["id"], ctx["crew"]["id"])


def build_verified_line_context(line_qtys=(10,), complete_clock="2026-07-08T10:00:00Z",
                                **ctx_kwargs) -> dict:
    """Full pipeline: awarded+accepted context, PO accepted with the given lines,
    all lines delivered and installed -> lines VERIFIED, PO FULFILLED.
    Returns ctx extended with po/lines/shipment/task."""
    ctx = build_accepted_award_context(**ctx_kwargs)
    po, lines = add_accepted_po(ctx, line_qtys=line_qtys)
    shipment = ship_and_deliver(ctx, po, lines)
    task = install_and_complete(ctx, shipment, complete_clock=complete_clock)
    ctx.update({"po": po, "lines": lines, "shipment": shipment, "task": task})
    return ctx
