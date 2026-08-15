"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Cashier, Driver and Volunteer are entity-backed by Worker
(PRD 2.1). Every helper that performs an ownership-gated call builds its
headers from the real worker id via make_cashier_headers / make_driver_headers
/ make_volunteer_headers; opaque roles use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    count_session_payload,
    create_assignment_payload,
    create_batch_payload,
    create_donor_payload,
    create_guideline_payload,
    create_item_payload,
    create_route_payload,
    create_sale_payload,
    create_shift_payload,
    create_stop_payload,
    create_till_session_payload,
    create_transfer_payload,
    create_vendor_payload,
    create_worker_payload,
    seal_bale_payload,
    settle_bale_payload,
    shrink_payload,
    triage_payload,
)
from .test_users import (
    TEST_USERS,
    make_cashier_headers,
    make_driver_headers,
    make_finance_clerk_headers,
    make_store_manager_headers,
)

MGR = TEST_USERS["store_manager_headers"]
INTAKE = TEST_USERS["intake_attendant_headers"]
PRICER = TEST_USERS["pricer_headers"]
COORD = TEST_USERS["volunteer_coordinator_headers"]
FIN = TEST_USERS["finance_clerk_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock. Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, MGR))


# ---------------------------------------------------------------------------
# Donors / batches / items (intake pipeline)
# ---------------------------------------------------------------------------

def create_donor(full_name="Test Donor", **overrides):
    """Register a donor (born ACTIVE, STANDARD, count 0)."""
    return get_success_data(
        api_client.create_donor(create_donor_payload(full_name, **overrides), INTAKE)
    )


def deactivate_donor(donor_id):
    return get_success_data(api_client.update_donor(donor_id, {"status": "INACTIVE"}, INTAKE))


def create_batch(donor_id, source="WALK_IN", receipt_requested=None):
    return get_success_data(
        api_client.create_batch(create_batch_payload(donor_id, source, receipt_requested),
                                INTAKE)
    )


def add_item(batch_id, category="CLOTHING", condition="GOOD", **overrides):
    return get_success_data(
        api_client.add_item(batch_id, create_item_payload(category, condition, **overrides),
                            INTAKE)
    )


def begin_sort(batch_id):
    return get_success_data(api_client.begin_sort(batch_id, INTAKE))


def complete_sort(batch_id):
    return get_success_data(api_client.complete_sort(batch_id, INTAKE))


def triage_item(item_id, decision="SALABLE", **overrides):
    return get_success_data(
        api_client.triage_item(item_id, triage_payload(decision, **overrides), INTAKE)
    )


def create_batch_with_items(item_specs, donor=None, receipt_requested=None,
                            donor_kwargs=None):
    """OPEN batch holding one item per spec. Returns (donor, batch, items)."""
    if donor is None:
        donor = create_donor(**(donor_kwargs or {}))
    batch = create_batch(donor["id"], receipt_requested=receipt_requested)
    items = [add_item(batch["id"], **spec) for spec in item_specs]
    return donor, batch, items


def sort_batch_all(batch_id, items, decision="SALABLE", per_item=None):
    """begin-sort then triage every item. per_item maps item id -> triage kwargs."""
    begin_sort(batch_id)
    out = []
    for item in items:
        kwargs = dict((per_item or {}).get(item["id"], {}))
        kwargs.setdefault("decision", decision)
        out.append(triage_item(item["id"], **kwargs))
    return out


def create_sorted_batch(item_specs, donor_kwargs=None, receipt_requested=None,
                        decision="SALABLE", per_item=None):
    """Batch driven OPEN -> SORTING with every item triaged -> SORTED.

    Returns (donor, batch, items); the batch is the post-complete-sort body.
    """
    donor, batch, items = create_batch_with_items(
        item_specs, receipt_requested=receipt_requested, donor_kwargs=donor_kwargs
    )
    items = sort_batch_all(batch["id"], items, decision=decision, per_item=per_item)
    batch = complete_sort(batch["id"])
    return donor, batch, items


# ---------------------------------------------------------------------------
# Pricing guidelines and the pricing pipeline
# ---------------------------------------------------------------------------

def create_guideline(category, base_cents, demand_multiplier=None):
    return get_success_data(
        api_client.create_guideline(
            create_guideline_payload(category, base_cents, demand_multiplier), MGR)
    )


def price_item(item_id, headers=None):
    return get_success_data(api_client.price_item(item_id, headers or PRICER))


def to_floor_item(item_id):
    return get_success_data(api_client.to_floor_item(item_id, PRICER))


def create_salable_item(category="CLOTHING", condition="GOOD", base_cents=2000,
                        demand_multiplier=None, item_kwargs=None):
    """Guideline + donor + batch + one item triaged SALABLE (batch left SORTING).

    Returns dict(donor, batch, item, guideline).
    """
    guideline = create_guideline(category, base_cents, demand_multiplier)
    donor, batch, items = create_batch_with_items(
        [dict(item_kwargs or {}, category=category, condition=condition)]
    )
    begin_sort(batch["id"])
    item = triage_item(items[0]["id"], "SALABLE")
    return {"donor": donor, "batch": batch, "item": item, "guideline": guideline}


def create_priced_item(category="CLOTHING", condition="GOOD", base_cents=2000,
                       demand_multiplier=None, item_kwargs=None, price_headers=None):
    """create_salable_item + price. Batch is left SORTING."""
    ctx = create_salable_item(category, condition, base_cents, demand_multiplier,
                              item_kwargs)
    ctx["item"] = price_item(ctx["item"]["id"], headers=price_headers)
    return ctx


def create_floored_item(category="CLOTHING", condition="GOOD", base_cents=2000,
                        demand_multiplier=None, item_kwargs=None, cycle=None):
    """Priced item moved ON_FLOOR. Reuses `cycle` if given, else opens one."""
    ctx = create_priced_item(category, condition, base_cents, demand_multiplier,
                             item_kwargs)
    if cycle is None:
        cycle = create_cycle()
    ctx["cycle"] = cycle
    ctx["item"] = to_floor_item(ctx["item"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Weekly cycles
# ---------------------------------------------------------------------------

def create_cycle():
    """Open the (single) weekly cycle."""
    return get_success_data(api_client.create_cycle(MGR))


def get_open_cycle():
    """Find the current OPEN cycle via the status filter."""
    data, _meta = validate_paginated(api_client.list_cycles(MGR, params={"status": "OPEN"}))
    assert len(data) == 1, f"Expected exactly one OPEN cycle, got {len(data)}"
    return data[0]


def run_markdown(cycle_id):
    return get_success_data(api_client.run_markdown(cycle_id, MGR))


def close_cycle(cycle_id):
    """Close the cycle; returns the closed cycle body (with its new version)."""
    return get_success_data(api_client.close_cycle(cycle_id, MGR))


def close_cycle_and_get_next(cycle_id):
    """Close a cycle and return (closed_cycle, next_open_cycle)."""
    closed = close_cycle(cycle_id)
    return closed, get_open_cycle()


# ---------------------------------------------------------------------------
# Salvage vendors and bales
# ---------------------------------------------------------------------------

def create_vendor(name, rates):
    return get_success_data(api_client.create_vendor(create_vendor_payload(name, rates), MGR))


def flat_rate_vendor(category, rate_cents_per_lb, name="Vendor"):
    """Vendor declaring a single unbounded bracket for one category."""
    return create_vendor(name, [{
        "category": category,
        "brackets": [{"up_to_lbs": None, "rate_cents_per_lb": rate_cents_per_lb}],
    }])


def find_accumulating_bale(category=None):
    params = {"status": "ACCUMULATING"}
    if category is not None:
        params["category"] = category
    data, _meta = validate_paginated(api_client.list_bales(MGR, params=params))
    assert len(data) >= 1, "Expected at least one ACCUMULATING bale"
    return data[0]


def create_recycle_bale(salvage_category, item_category, weights, conditions=None):
    """Feed items of the given weights into the category's ACCUMULATING bale
    via RECYCLE triage. Returns (bale, donor, batch, items)."""
    specs = []
    for idx, weight in enumerate(weights):
        spec = {
            "category": item_category,
            "condition": (conditions[idx] if conditions else "GOOD"),
            "weight_lbs": weight,
        }
        specs.append(spec)
    donor, batch, items = create_batch_with_items(specs)
    begin_sort(batch["id"])
    items = [
        triage_item(it["id"], "RECYCLE", salvage_category=salvage_category)
        for it in items
    ]
    bale = find_accumulating_bale(salvage_category)
    return bale, donor, batch, items


def seal_bale(bale_id, vendor_id, headers=None):
    return get_success_data(
        api_client.seal_bale(bale_id, seal_bale_payload(vendor_id), headers or MGR)
    )


def ship_bale(bale_id):
    return get_success_data(api_client.ship_bale(bale_id, MGR))


def settle_bale(bale_id, actual_weight_lbs, headers=None):
    return get_success_data(
        api_client.settle_bale(bale_id, settle_bale_payload(actual_weight_lbs),
                               headers or FIN)
    )


# ---------------------------------------------------------------------------
# Workers / shifts / assignments
# ---------------------------------------------------------------------------

def create_worker(full_name="W Test", employment_type="STAFF", **overrides):
    return get_success_data(
        api_client.create_worker(
            create_worker_payload(full_name, employment_type, **overrides), COORD)
    )


def patch_worker(worker_id, payload, headers=None):
    return get_success_data(api_client.update_worker(worker_id, payload, headers or COORD))


def create_shift(role_type="SORTER", starts_at="2026-08-10T09:00:00Z",
                 ends_at="2026-08-10T12:00:00Z", required_headcount=1):
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(role_type, starts_at, ends_at, required_headcount),
            COORD)
    )


def assign_worker(shift_id, worker_id):
    return get_success_data(
        api_client.assign_worker(shift_id, create_assignment_payload(worker_id), COORD)
    )


def confirm_assignment(assignment_id, headers=None):
    return get_success_data(api_client.confirm_assignment(assignment_id, headers or COORD))


def complete_assignment(assignment_id):
    return get_success_data(api_client.complete_assignment(assignment_id, COORD))


def get_worker(worker_id):
    return get_success_data(api_client.get_worker(worker_id, MGR))


# ---------------------------------------------------------------------------
# Till sessions and sales
# ---------------------------------------------------------------------------

def open_till_session(cashier_worker_id, opening_float_cents=5000):
    """Cashier opens their own drawer; cashier_worker_id comes from X-User-ID."""
    return get_success_data(
        api_client.create_till_session(
            create_till_session_payload(opening_float_cents),
            make_cashier_headers(cashier_worker_id))
    )


def ring_sale(session_id, cashier_worker_id, item_ids, payment_method="CASH"):
    return get_success_data(
        api_client.create_sale(
            create_sale_payload(session_id, item_ids, payment_method),
            make_cashier_headers(cashier_worker_id))
    )


def count_session(session_id, counted_cash_cents, counter_user_id="mgr-counter-1"):
    return get_success_data(
        api_client.count_till_session(
            session_id, count_session_payload(counted_cash_cents),
            make_store_manager_headers(counter_user_id))
    )


def approve_variance(session_id, approver_user_id="fin-approver-1"):
    return get_success_data(
        api_client.approve_variance(session_id,
                                    make_finance_clerk_headers(approver_user_id))
    )


def close_till_session(session_id):
    return get_success_data(api_client.close_till_session(session_id, MGR))


def get_till_session(session_id):
    return get_success_data(api_client.get_till_session(session_id, MGR))


def create_sold_item(base_cents=2000, opening_float_cents=5000, category="CLOTHING",
                     condition="GOOD", item_kwargs=None, payment_method="CASH"):
    """Full pipeline: floored item + cashier worker + OPEN session + sale.

    Returns dict(donor, batch, item, guideline, cycle, cashier, session, sale).
    """
    ctx = create_floored_item(category, condition, base_cents, item_kwargs=item_kwargs)
    cashier = create_worker("W Cash", "STAFF")
    session = open_till_session(cashier["id"], opening_float_cents)
    sale = ring_sale(session["id"], cashier["id"], [ctx["item"]["id"]], payment_method)
    ctx.update({"cashier": cashier, "session": session, "sale": sale})
    return ctx


# ---------------------------------------------------------------------------
# Pickup routes and stops
# ---------------------------------------------------------------------------

def create_driver(full_name="W Drive"):
    return create_worker(full_name, "STAFF")


def create_route(driver_worker_id, route_date="2026-08-10", truck_capacity_cuft=500):
    return get_success_data(
        api_client.create_route(
            create_route_payload(route_date, driver_worker_id, truck_capacity_cuft),
            MGR)
    )


def add_stop(route_id, donor_id, window_start="2026-08-10T09:00:00Z",
             window_end="2026-08-10T10:00:00Z", estimated_volume_cuft=100):
    return get_success_data(
        api_client.add_stop(
            route_id,
            create_stop_payload(donor_id, window_start, window_end,
                                estimated_volume_cuft),
            MGR)
    )


def publish_route(route_id):
    return get_success_data(api_client.publish_route(route_id, MGR))


def unpublish_route(route_id):
    return get_success_data(api_client.unpublish_route(route_id, MGR))


def start_route(route_id):
    return get_success_data(api_client.start_route(route_id, MGR))


def depart_stop(stop_id, driver_worker_id):
    return get_success_data(
        api_client.depart_stop(stop_id, make_driver_headers(driver_worker_id))
    )


def complete_stop(stop_id, driver_worker_id):
    return get_success_data(
        api_client.complete_stop(stop_id, make_driver_headers(driver_worker_id))
    )


def no_show_stop(stop_id, driver_worker_id):
    return get_success_data(
        api_client.no_show_stop(stop_id, make_driver_headers(driver_worker_id))
    )


def create_route_with_stops(stop_specs, driver=None, route_date="2026-08-10",
                            truck_capacity_cuft=500):
    """DRAFT route with one stop per spec. Returns (driver, route, stops).

    Each spec is a dict of add_stop kwargs plus an optional "donor" entry.
    """
    driver = driver or create_driver()
    route = create_route(driver["id"], route_date, truck_capacity_cuft)
    stops = []
    for spec in stop_specs:
        spec = dict(spec)
        donor = spec.pop("donor", None) or create_donor()
        stops.append(add_stop(route["id"], donor["id"], **spec))
    return driver, route, stops


# ---------------------------------------------------------------------------
# Mission transfers
# ---------------------------------------------------------------------------

def create_mission_transfer(cycle_id, expected_cycle_version, allocations,
                            preparer_user_id="fin-preparer-1"):
    return get_success_data(
        api_client.create_mission_transfer(
            cycle_id,
            create_transfer_payload(expected_cycle_version, allocations),
            make_finance_clerk_headers(preparer_user_id))
    )


def approve_transfer(transfer_id, approver_user_id="mgr-approver-1"):
    return get_success_data(
        api_client.approve_transfer(transfer_id,
                                    make_store_manager_headers(approver_user_id))
    )


def disburse_transfer(transfer_id, disburser_user_id="fin-preparer-1"):
    return get_success_data(
        api_client.disburse_transfer(transfer_id,
                                     make_finance_clerk_headers(disburser_user_id))
    )


# ---------------------------------------------------------------------------
# Tier 4/5: closed cycles with a pinned net revenue (mission-pool tests)
# ---------------------------------------------------------------------------

def setup_closed_cycle_with_net_revenue(net_cents, sale_day="2026-08-03T00:00:00Z",
                                        close_day="2026-08-05T00:00:00Z"):
    """Build a CLOSED cycle whose net_revenue_cents == net_cents.

    For a positive amount this prices one FURNITURE/NEW_WITH_TAGS item at
    exactly net_cents (guideline base == net_cents, multiplier 1.0) and rings
    it as a CASH sale inside the cycle window, then reconciles and closes the
    drawer before closing the week. Returns the closed cycle body (its version
    is the value transfer creation must cite).
    """
    if net_cents == 0:
        cycle = create_cycle()
        return close_cycle(cycle["id"])

    guideline = create_guideline("FURNITURE", net_cents, 1.0)
    donor, batch, items = create_batch_with_items(
        [{"category": "FURNITURE", "condition": "NEW_WITH_TAGS"}],
        donor_kwargs={"full_name": "D Pool", "address_line": "9 Oak Ave"},
    )
    begin_sort(batch["id"])
    item = triage_item(items[0]["id"], "SALABLE")
    item = price_item(item["id"])
    cycle = create_cycle()
    item = to_floor_item(item["id"])
    cashier = create_worker("W Cash", "STAFF")
    session = open_till_session(cashier["id"], 0)
    set_clock(sale_day)
    sale = ring_sale(session["id"], cashier["id"], [item["id"]], "CASH")
    assert sale["total_cents"] == net_cents, (
        f"Setup failed: sale total {sale['total_cents']} != {net_cents} "
        f"(guideline {guideline['id']})"
    )
    count_session(session["id"], net_cents)
    close_till_session(session["id"])
    set_clock(close_day)
    return close_cycle(cycle["id"])
