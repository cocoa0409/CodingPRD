"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() validator so a broken precondition surfaces as a
clear setup failure.

Entity-backed identity threading: Servicer calls are made with
make_servicer_headers(servicer["id"]) and FieldCrew calls with
make_field_crew_headers(crew["id"]); the opaque-role shared constants are used
for VendorAdmin / Dispatcher / QualityReviewer actions.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import ORDER_TYPE_TO_ITEM_CODE, PHOTO_MINIMUMS, TEST_DEFAULTS
from .factories import (
    create_code_violation_payload,
    create_crew_payload,
    create_damage_report_payload,
    create_disposition_payload,
    create_expense_line_payload,
    create_inspection_payload,
    create_investor_allowable_payload,
    create_photo_evidence_payload,
    create_property_payload,
    create_recurring_plan_payload,
    create_registration_payload,
    create_servicer_payload,
    create_work_order_payload,
    record_inspection_payload,
)
from .test_users import TEST_USERS, make_field_crew_headers, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
QA = TEST_USERS["quality_reviewer_headers"]


# ---------------------------------------------------------------------------
# Clock / sweep
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock (VendorAdmin-only test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_daily_sweep() -> dict:
    """Run the daily operational sweep; returns the sweep's result payload."""
    return get_success_data(api_client.run_daily_sweep(ADMIN))


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_servicer(**overrides) -> dict:
    resp = api_client.create_servicer(create_servicer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_crew(**overrides) -> dict:
    resp = api_client.create_crew(create_crew_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_allowable(**overrides) -> dict:
    resp = api_client.create_investor_allowable(
        create_investor_allowable_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_property(servicer_id, **overrides) -> dict:
    resp = api_client.create_property(create_property_payload(servicer_id, **overrides), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Portfolio bundle
# ---------------------------------------------------------------------------

def setup_portfolio(item_code="GRASS_CUT", investor_type="FHA",
                    allowable_overrides=None, property_overrides=None,
                    crew_overrides=None, clock=TEST_DEFAULTS["CLOCK"],
                    with_crew=True, with_allowable=True) -> dict:
    """Servicer + crew + allowable row + property. Returns a context dict."""
    if clock is not None:
        set_clock(clock)
    servicer = create_servicer()
    ctx = {"servicer": servicer, "servicer_id": servicer["id"]}
    if with_crew:
        crew = create_crew(**(crew_overrides or {}))
        ctx.update({"crew": crew, "crew_id": crew["id"]})
    if with_allowable:
        allowable = create_allowable(
            investor_type=investor_type, item_code=item_code,
            **(allowable_overrides or {}))
        ctx.update({"allowable": allowable, "allowable_id": allowable["id"]})
    prop = create_property(servicer["id"], investor_type=investor_type,
                           **(property_overrides or {}))
    ctx.update({"property": prop, "property_id": prop["id"]})
    return ctx


# ---------------------------------------------------------------------------
# Work order lifecycle tiers
# ---------------------------------------------------------------------------

def create_work_order(property_id, servicer_id, **overrides) -> dict:
    """Servicer issues a DIRECT work order."""
    resp = api_client.create_work_order(
        create_work_order_payload(property_id, **overrides),
        make_servicer_headers(servicer_id))
    return get_success_data(resp)


def assign_work_order(work_order_id, crew_id, scheduled_date="2026-08-02") -> dict:
    resp = api_client.assign_work_order(
        work_order_id, {"crew_id": crew_id, "scheduled_date": scheduled_date}, DISPATCHER)
    return get_success_data(resp)


def start_work_order(work_order_id, crew_id) -> dict:
    resp = api_client.start_work_order(work_order_id, make_field_crew_headers(crew_id))
    return get_success_data(resp)


def upload_minimum_photos(work_order_id, order_type, crew_id,
                          date="2026-08-02", hash_prefix="ph") -> list:
    """Upload exactly the order type's minimum unflagged photo set."""
    photos = []
    for category, count in PHOTO_MINIMUMS[order_type].items():
        for i in range(count):
            payload = create_photo_evidence_payload(
                work_order_id=work_order_id, category=category,
                taken_at=f"{date}T{9 + i:02d}:00:00Z",
                content_hash=f"{hash_prefix}-{category}-{i}")
            photos.append(get_success_data(
                api_client.create_photo_evidence(payload, make_field_crew_headers(crew_id))))
    return photos


def submit_work_order(work_order_id, crew_id, submitted_cost_cents) -> dict:
    resp = api_client.submit_work_order(
        work_order_id, {"submitted_cost_cents": submitted_cost_cents},
        make_field_crew_headers(crew_id))
    return get_success_data(resp)


def approve_work_order(work_order_id) -> dict:
    return get_success_data(api_client.approve_work_order(work_order_id, QA))


def complete_work_order(work_order_id) -> dict:
    return get_success_data(api_client.complete_work_order(work_order_id, QA))


def get_invoice_for_work_order(work_order_id) -> dict:
    """Fetch the auto-created DRAFT invoice of a completed work order."""
    resp = api_client.list_invoices(ADMIN, params={"work_order_id": work_order_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one invoice for work order {work_order_id}"
    return data[0]


def add_expense_line(invoice_id, **overrides) -> dict:
    resp = api_client.add_expense_line(invoice_id, create_expense_line_payload(**overrides), ADMIN)
    return get_success_data(resp)


def setup_completed_order_with_invoice(order_type="GRASS_CUT", item_code=None,
                                       unit_price_cents=1000,
                                       submitted_cost_cents=1000,
                                       allowable_overrides=None,
                                       property_overrides=None,
                                       crew_overrides=None,
                                       scheduled_date="2026-08-02",
                                       clock=TEST_DEFAULTS["CLOCK"],
                                       add_line=True) -> dict:
    """Full chain: portfolio -> issue -> assign -> start -> minimum photos ->
    submit -> approve -> complete -> fetch auto-created DRAFT invoice.

    Returns a context dict with servicer/crew/property/work_order/invoice and
    their ids. When add_line is true, one expense line of `item_code` at
    `unit_price_cents` (quantity 1) is added to the invoice.
    """
    item_code = item_code or ORDER_TYPE_TO_ITEM_CODE[order_type]
    ctx = setup_portfolio(item_code=item_code,
                          allowable_overrides=allowable_overrides,
                          property_overrides=property_overrides,
                          crew_overrides=crew_overrides, clock=clock)
    wo = create_work_order(ctx["property_id"], ctx["servicer_id"], order_type=order_type)
    assign_work_order(wo["id"], ctx["crew_id"], scheduled_date=scheduled_date)
    start_work_order(wo["id"], ctx["crew_id"])
    upload_minimum_photos(wo["id"], order_type, ctx["crew_id"], date=scheduled_date,
                          hash_prefix=f"ph-{wo['id'][:8]}")
    submit_work_order(wo["id"], ctx["crew_id"], submitted_cost_cents)
    approve_work_order(wo["id"])
    wo_completed = complete_work_order(wo["id"])
    invoice = get_invoice_for_work_order(wo["id"])
    ctx.update({"work_order": wo_completed, "work_order_id": wo["id"],
                "invoice": invoice, "invoice_id": invoice["id"]})
    if add_line:
        line = add_expense_line(invoice["id"], item_code=item_code,
                                unit_price_cents=unit_price_cents)
        ctx.update({"expense_line": line})
        ctx["invoice"] = get_success_data(api_client.get_invoice(invoice["id"], ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Inspections / occupancy
# ---------------------------------------------------------------------------

def create_inspection(property_id, **overrides) -> dict:
    resp = api_client.create_inspection(create_inspection_payload(property_id, **overrides), ADMIN)
    return get_success_data(resp)


def record_inspection(inspection_id, crew_id, **overrides) -> dict:
    resp = api_client.record_inspection(
        inspection_id, record_inspection_payload(**overrides),
        make_field_crew_headers(crew_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Municipal registration / code violations
# ---------------------------------------------------------------------------

def create_registration(property_id, **overrides) -> dict:
    resp = api_client.create_registration(create_registration_payload(property_id, **overrides), ADMIN)
    return get_success_data(resp)


def setup_active_registration(property_id, municipality_code="COL", **overrides) -> dict:
    reg = create_registration(property_id, municipality_code=municipality_code, **overrides)
    return get_success_data(api_client.activate_registration(reg["id"], ADMIN))


def create_code_violation(property_id, **overrides) -> dict:
    resp = api_client.create_code_violation(create_code_violation_payload(property_id, **overrides), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Damage reports / bids
# ---------------------------------------------------------------------------

def create_damage_report(property_id, crew_id, **overrides) -> dict:
    resp = api_client.create_damage_report(
        create_damage_report_payload(property_id, **overrides),
        make_field_crew_headers(crew_id))
    return get_success_data(resp)


def setup_bid_requested_report(property_overrides=None, crew_overrides=None,
                               clock=TEST_DEFAULTS["CLOCK"],
                               damage_overrides=None) -> dict:
    """Portfolio (DAMAGE_REPAIR allowable) + damage report driven to
    BID_REQUESTED. Context includes damage_report and damage_report_version
    (the report's current version, for OCC-guarded bid creation)."""
    ctx = setup_portfolio(item_code="DAMAGE_REPAIR",
                          allowable_overrides={
                              "max_per_occurrence_cents": 250000,
                              "max_occurrences_per_calendar_year": 5,
                              "aggregate_cap_cents_per_property_year": 900000,
                              "requires_bid_over_cents": 99999999,
                          },
                          property_overrides=property_overrides,
                          crew_overrides=crew_overrides, clock=clock)
    dr = create_damage_report(ctx["property_id"], ctx["crew_id"], **(damage_overrides or {}))
    get_success_data(api_client.triage_damage_report(dr["id"], ADMIN))
    dr_requested = get_success_data(api_client.request_bids(dr["id"], ADMIN))
    ctx.update({"damage_report": dr_requested, "damage_report_id": dr["id"],
                "damage_report_version": dr_requested["version"]})
    return ctx


def create_bid(damage_report_id, crew_id, amount_cents, expected_damage_report_version) -> dict:
    resp = api_client.create_bid(
        damage_report_id,
        {"amount_cents": amount_cents,
         "expected_damage_report_version": expected_damage_report_version},
        make_field_crew_headers(crew_id))
    return get_success_data(resp)


def submit_bid(bid_id, crew_id) -> dict:
    return get_success_data(api_client.submit_bid(bid_id, make_field_crew_headers(crew_id)))


# ---------------------------------------------------------------------------
# Personal property dispositions / recurring plans
# ---------------------------------------------------------------------------

def create_disposition(property_id, crew_id=None, **overrides) -> dict:
    headers = make_field_crew_headers(crew_id) if crew_id else ADMIN
    resp = api_client.create_disposition(create_disposition_payload(property_id, **overrides), headers)
    return get_success_data(resp)


def create_recurring_plan(property_id, **overrides) -> dict:
    resp = api_client.create_recurring_plan(create_recurring_plan_payload(property_id, **overrides), ADMIN)
    return get_success_data(resp)
