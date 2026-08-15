"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the
server before each test), so these helpers build complete precondition
chains out of PRD-declared endpoints only.

Identity threading: PublisherManager is entity-backed by Publisher, so
every ownership-gated call (package/deal/window/node writes and
transitions) uses make_publisher_manager_headers(publisher_id) built from
the real publisher id. Opaque roles use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    BATCH_PERIOD_END,
    BATCH_PERIOD_START,
    DEFAULT_DAILY_CAP_MICROS,
    DEFAULT_MAX_QPS,
    FINANCE_USER_ID,
    FLIGHT_END,
    FLIGHT_START,
    SECOND_ADMIN_USER_ID,
)
from .factories import (
    create_blocklist_entry_payload,
    create_deal_payload,
    create_demand_partner_payload,
    create_package_payload,
    create_payout_batch_payload,
    create_publisher_payload,
    create_reconciliation_report_payload,
    create_seasonal_window_payload,
    create_supply_chain_node_payload,
    execute_auction_payload,
    make_bid,
    resolve_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_exchange_admin_headers,
    make_finance_officer_headers,
    make_publisher_manager_headers,
)

ADMIN = TEST_USERS["exchange_admin_headers"]
DEMAND = TEST_USERS["demand_side_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]

# seat_id must be unique across all demand partners; a process-level counter
# keeps default seats distinct when one test registers several partners.
_seat_counter = iter(range(1, 1_000_000))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_publisher(name="Pub", domain="p.com", payment_terms="GUARANTEED"):
    """Create a publisher (born ACTIVE, counters at zero)."""
    resp = api_client.create_publisher(
        create_publisher_payload(name, domain, payment_terms), ADMIN)
    return get_success_data(resp, 201)


def create_partner(name="DP", seat_id=None, max_qps=DEFAULT_MAX_QPS,
                   daily_cap_micros=DEFAULT_DAILY_CAP_MICROS):
    """Register a demand partner (born ACTIVE, counters at zero)."""
    if seat_id is None:
        seat_id = f"seat-{next(_seat_counter)}"
    resp = api_client.create_demand_partner(
        create_demand_partner_payload(name, seat_id, max_qps, daily_cap_micros),
        ADMIN)
    return get_success_data(resp, 201)


def create_package_for(publisher_id, name="Pkg", ad_format="DISPLAY",
                       category_tags=("IAB1",), base_floor_cpm_micros=500000):
    """Create an ACTIVE package owned by the given publisher."""
    headers = make_publisher_manager_headers(publisher_id)
    resp = api_client.create_package(
        create_package_payload(name, ad_format, category_tags,
                               base_floor_cpm_micros),
        headers)
    return get_success_data(resp, 201)


def create_deal_for(publisher_id, package_id, demand_partner_id,
                    deal_type="PMP_STANDARD", auction_type="FIRST_PRICE",
                    floor_cpm_micros=500000, start_at=FLIGHT_START,
                    end_at=FLIGHT_END, committed_impressions=None):
    """Create a DRAFT deal on an owned package."""
    headers = make_publisher_manager_headers(publisher_id)
    resp = api_client.create_deal(
        create_deal_payload(package_id, demand_partner_id, deal_type,
                            auction_type, floor_cpm_micros, start_at, end_at,
                            committed_impressions),
        headers)
    return get_success_data(resp, 201)


def add_supply_hop(package_id, publisher_id, seller_domain, fee_bps,
                   parent_node_id=None):
    """Append one hop to a package's supply chain."""
    headers = make_publisher_manager_headers(publisher_id)
    resp = api_client.create_supply_chain_node(
        create_supply_chain_node_payload(package_id, seller_domain, fee_bps,
                                         parent_node_id),
        headers)
    return get_success_data(resp, 201)


def create_window(package_id, publisher_id, name="W", start_date="2026-11-20",
                  end_date="2026-11-30", multiplier_bps=15000):
    """Create a seasonal pricing window on an owned package."""
    headers = make_publisher_manager_headers(publisher_id)
    resp = api_client.create_seasonal_window(
        create_seasonal_window_payload(package_id, name, start_date, end_date,
                                       multiplier_bps),
        headers)
    return get_success_data(resp, 201)


def create_blocklist(scope, rule_type, value, publisher_id=None, deal_id=None,
                     as_admin=True):
    """Create an ACTIVE blocklist entry (ExchangeAdmin by default)."""
    if as_admin:
        headers = ADMIN
    else:
        assert publisher_id is not None, "manager-scoped creation needs a publisher id"
        headers = make_publisher_manager_headers(publisher_id)
    resp = api_client.create_blocklist_entry(
        create_blocklist_entry_payload(scope, rule_type, value, publisher_id,
                                       deal_id),
        headers)
    return get_success_data(resp, 201)


def set_clock(to_iso8601):
    """Advance the logical clock (ExchangeAdmin only)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 2: deal lifecycle shortcuts
# ---------------------------------------------------------------------------

def submit_deal(deal_id, publisher_id):
    headers = make_publisher_manager_headers(publisher_id)
    return get_success_data(api_client.submit_deal(deal_id, headers), 200)


def approve_deal(deal_id):
    return get_success_data(api_client.approve_deal(deal_id, ADMIN), 200)


def submit_and_approve_deal(deal_id, publisher_id):
    """DRAFT -> PENDING_REVIEW -> ACTIVE. Returns the ACTIVE deal."""
    submit_deal(deal_id, publisher_id)
    return approve_deal(deal_id)


def setup_active_deal(payment_terms="GUARANTEED", publisher_name="Pub",
                      publisher_domain="p.com", package_floor=500000,
                      deal_floor=500000, deal_type="PMP_STANDARD",
                      auction_type="FIRST_PRICE", committed_impressions=None,
                      category_tags=("IAB1",), ad_format="DISPLAY",
                      max_qps=DEFAULT_MAX_QPS,
                      daily_cap_micros=DEFAULT_DAILY_CAP_MICROS,
                      seat_id=None, start_at=FLIGHT_START,
                      end_at=FLIGHT_END, supply_hops=()):
    """Publisher + partner + package + APPROVED ACTIVE deal.

    ``supply_hops`` is a tuple of (seller_domain, fee_bps) appended in order
    before the deal is created. Returns a dict with pub, partner, pkg, deal
    and the manager headers threaded for the owning publisher.
    """
    pub = create_publisher(publisher_name, publisher_domain, payment_terms)
    partner = create_partner(seat_id=seat_id, max_qps=max_qps,
                             daily_cap_micros=daily_cap_micros)
    pkg = create_package_for(pub["id"], category_tags=category_tags,
                             ad_format=ad_format,
                             base_floor_cpm_micros=package_floor)
    parent = None
    nodes = []
    for i, (domain, fee_bps) in enumerate(supply_hops):
        parent = add_supply_hop(pkg["id"], pub["id"], domain, fee_bps,
                                parent_node_id=parent["id"] if parent else None)
        nodes.append(parent)
    deal = create_deal_for(pub["id"], pkg["id"], partner["id"], deal_type,
                           auction_type, deal_floor, start_at, end_at,
                           committed_impressions)
    deal = submit_and_approve_deal(deal["id"], pub["id"])
    return {
        "pub": pub,
        "partner": partner,
        "pkg": pkg,
        "deal": deal,
        "nodes": nodes,
        "manager_headers": make_publisher_manager_headers(pub["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: auctions and records
# ---------------------------------------------------------------------------

def run_auction(publisher_id, bids):
    """Execute one auction as DemandSide. Returns the response data payload."""
    resp = api_client.execute_auction(
        execute_auction_payload(publisher_id, bids), DEMAND)
    return get_success_data(resp, 200)


def fill_auction(publisher_id, bid_cpm_micros=1_000_000, impression_count=1000,
                 creative_domain="a.com"):
    """Run a single-bid auction expected to fill. Returns the AuctionRecord."""
    data = run_auction(publisher_id,
                       [make_bid(bid_cpm_micros, impression_count,
                                 creative_domain)])
    record = data.get("auction_record")
    assert record, f"Expected the auction to fill, got: {data}"
    return record


def confirm_record(record_id):
    return get_success_data(api_client.confirm_billing(record_id, DEMAND), 200)


def void_record(record_id):
    return get_success_data(api_client.void_auction_record(record_id, ADMIN), 200)


def list_records(headers=None, **params):
    items, meta = validate_paginated(
        api_client.list_auction_records(headers or ADMIN, params=params or None))
    return items, meta


def get_partner(partner_id):
    return get_success_data(api_client.get_demand_partner(partner_id, ADMIN), 200)


def get_publisher(publisher_id):
    return get_success_data(api_client.get_publisher(publisher_id, ADMIN), 200)


def get_deal(deal_id):
    return get_success_data(api_client.get_deal(deal_id, ADMIN), 200)


def get_package(package_id):
    return get_success_data(api_client.get_package(package_id, ADMIN), 200)


# ---------------------------------------------------------------------------
# Tier 4: reconciliation reports
# ---------------------------------------------------------------------------

def create_report(deal_id, period_start="2026-08-01", period_end="2026-08-02"):
    resp = api_client.create_reconciliation_report(
        create_reconciliation_report_payload(deal_id, period_start, period_end),
        make_finance_officer_headers(FINANCE_USER_ID))
    return get_success_data(resp, 201)


def resolve_report(report_id, resolution_type, adjustment_micros=None,
                   as_finance=False):
    headers = (make_finance_officer_headers(FINANCE_USER_ID) if as_finance
               else ADMIN)
    resp = api_client.resolve_report(
        report_id, resolve_report_payload(resolution_type, adjustment_micros),
        headers)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 5: payout batches and lines
# ---------------------------------------------------------------------------

def create_batch(period_start=BATCH_PERIOD_START, period_end=BATCH_PERIOD_END,
                 creator=FINANCE_USER_ID):
    """Create a DRAFT payout batch as a FinanceOfficer."""
    resp = api_client.create_payout_batch(
        create_payout_batch_payload(period_start, period_end),
        make_finance_officer_headers(creator))
    return get_success_data(resp, 201)


def submit_batch(batch_id, creator=FINANCE_USER_ID):
    return get_success_data(
        api_client.submit_payout_batch(
            batch_id, make_finance_officer_headers(creator)), 200)


def approve_batch(batch_id, approver=SECOND_ADMIN_USER_ID):
    """Approve a PENDING_APPROVAL batch as a different ExchangeAdmin operator."""
    return get_success_data(
        api_client.approve_payout_batch(
            batch_id, make_exchange_admin_headers(approver)), 200)


def release_batch(batch_id, releaser=FINANCE_USER_ID):
    return get_success_data(
        api_client.release_payout_batch(
            batch_id, make_finance_officer_headers(releaser)), 200)


def list_lines(batch_id, status=None):
    params = {"status": status} if status else None
    items, _meta = validate_paginated(
        api_client.list_batch_lines(batch_id, FINANCE, params=params))
    return items


def setup_submitted_batch_with_line(payment_terms="GUARANTEED",
                                    confirm=False,
                                    period_start=BATCH_PERIOD_START,
                                    period_end=BATCH_PERIOD_END):
    """One publisher, one filled auction (canonical 850,000 net), one
    submitted batch covering the default period. Returns a dict with the
    scenario objects and the single generated line.
    """
    sc = setup_active_deal(payment_terms=payment_terms)
    record = fill_auction(sc["pub"]["id"])
    if confirm:
        confirm_record(record["id"])
    batch = create_batch(period_start, period_end)
    batch = submit_batch(batch["id"])
    lines = list_lines(batch["id"])
    assert len(lines) == 1, f"Expected exactly one generated line, got {lines}"
    sc.update({"batch": batch, "line": lines[0], "record": record})
    return sc
