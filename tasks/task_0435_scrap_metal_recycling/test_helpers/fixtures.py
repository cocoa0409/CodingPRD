"""Composite setup helpers for the scrap-metal yard API.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion mismatch.

All five roles are opaque, so fixtures use the shared TEST_USERS headers except
where a test must control a specific X-User-ID (segregation of duties), in which
case the caller passes explicit headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_weigh_master_headers,
)

WM = TEST_USERS["weigh_master_headers"]
PC = TEST_USERS["payout_clerk_headers"]
YM = TEST_USERS["yard_manager_headers"]
SA = TEST_USERS["settlement_accountant_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------
def publish_price(grade_code="SHRED_STEEL", category="FERROUS",
                  spot=11, mill=14):
    """Publish an ACTIVE CommodityPrice. Returns the price object."""
    resp = api_client.create_commodity_price(
        {
            "grade_code": grade_code,
            "category": category,
            "spot_price_cents_per_lb": spot,
            "mill_price_cents_per_lb": mill,
        },
        YM,
    )
    return get_success_data(resp)


def register_seller(legal_name="Test Seller", id_type="STATE_ID",
                    id_number="SID-1", tin=None):
    """Register an ACTIVE seller. Returns the seller object."""
    payload = {"legal_name": legal_name, "id_type": id_type, "id_number": id_number}
    if tin is not None:
        payload["tin"] = tin
    resp = api_client.create_seller(payload, WM)
    return get_success_data(resp)


def stage_container(category="FERROUS", capacity_lb=5000):
    """Stage a STAGED container. Returns the container object."""
    resp = api_client.create_container(
        {"category": category, "capacity_lb": capacity_lb}, YM
    )
    return get_success_data(resp)


def open_ticket(seller_id, gross_weight_lb=1500):
    """Open a DRAFT ticket. Returns the ticket object."""
    resp = api_client.create_ticket(
        {"seller_id": seller_id, "gross_weight_lb": gross_weight_lb}, WM
    )
    return get_success_data(resp)


def add_line(ticket_id, grade_code="SHRED_STEEL", weight_lb=100):
    """Add a line item to a DRAFT ticket. Returns the line item object."""
    resp = api_client.add_line_item(
        ticket_id, {"grade_code": grade_code, "weight_lb": weight_lb}, WM
    )
    return get_success_data(resp)


def open_hedge(category="FERROUS", hedged_weight_lb=1300, locked_price=90):
    """Open an OPEN hedge position. Returns the hedge object."""
    resp = api_client.create_hedge(
        {
            "category": category,
            "hedged_weight_lb": hedged_weight_lb,
            "locked_price_cents_per_lb": locked_price,
        },
        SA,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: ticket through the weigh-out / release stages
# ---------------------------------------------------------------------------
def create_weighed_ticket(seller_id=None, grade_code="SHRED_STEEL",
                          category="FERROUS", spot=11, mill=14,
                          weight_lb=100, gross_weight_lb=1500,
                          tare_weight_lb=200, lines=None, price_published=True,
                          seller_tin=None):
    """Create a WEIGHED ticket (DRAFT -> add lines -> weigh-out).

    Returns dict {price, seller, ticket, line_items}. If `lines` is given it is a
    list of (grade_code, weight_lb) tuples; otherwise a single line of
    (grade_code, weight_lb) is added. Assumes a single grade/price unless lines
    use grades the caller pre-published.
    """
    price = None
    if price_published:
        price = publish_price(grade_code, category, spot, mill)
    if seller_id is None:
        seller = register_seller(tin=seller_tin)
        seller_id = seller["id"]
    else:
        seller = None
    ticket = open_ticket(seller_id, gross_weight_lb=gross_weight_lb)
    line_items = []
    if lines is None:
        lines = [(grade_code, weight_lb)]
    for g, w in lines:
        line_items.append(add_line(ticket["id"], grade_code=g, weight_lb=w))
    resp = api_client.weigh_out(ticket["id"], {"tare_weight_lb": tare_weight_lb}, WM)
    ticket = get_success_data(resp)
    return {"price": price, "seller": seller, "seller_id": seller_id,
            "ticket": ticket, "line_items": line_items}


def create_released_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                           spot=11, mill=14, weight_lb=100,
                           gross_weight_lb=1500, tare_weight_lb=200,
                           capacity_lb=5000, lines=None, seller_tin=None,
                           seller_id=None, container_id=None):
    """Create a RELEASED ticket loaded into a matching STAGED container.

    Returns dict {price, seller, seller_id, ticket, line_items, container}.
    """
    built = create_weighed_ticket(
        seller_id=seller_id, grade_code=grade_code, category=category,
        spot=spot, mill=mill, weight_lb=weight_lb,
        gross_weight_lb=gross_weight_lb, tare_weight_lb=tare_weight_lb,
        lines=lines, seller_tin=seller_tin,
    )
    if container_id is None:
        container = stage_container(category=category, capacity_lb=capacity_lb)
        container_id = container["id"]
    else:
        container = None
    resp = api_client.release_ticket(built["ticket"]["id"],
                                     {"container_id": container_id}, WM)
    built["ticket"] = get_success_data(resp)
    built["container"] = container
    built["container_id"] = container_id
    return built


# ---------------------------------------------------------------------------
# Tier 3: payout lifecycle
# ---------------------------------------------------------------------------
def create_pending_payout(method="CASH", grade_code="SHRED_STEEL",
                          category="FERROUS", spot=11, weight_lb=100,
                          seller_tin=None, payout_headers=None):
    """Create a RELEASED ticket and a PENDING payout for it.

    Returns dict including 'payout'. `payout_headers` controls the acting
    PayoutClerk's X-User-ID (segregation-of-duties tests); defaults to shared PC.
    """
    built = create_released_ticket(
        grade_code=grade_code, category=category, spot=spot,
        weight_lb=weight_lb, capacity_lb=5000, seller_tin=seller_tin,
    )
    hdr = payout_headers or PC
    resp = api_client.create_payout(
        {"ticket_id": built["ticket"]["id"], "method": method}, hdr
    )
    built["payout"] = get_success_data(resp)
    return built


def create_settled_cash_payout(grade_code="SHRED_STEEL", category="FERROUS",
                               spot=11, weight_lb=100, seller_tin=None):
    """Create a RELEASED ticket, a PENDING CASH payout, and settle it.

    Returns dict including 'payout' (SETTLED) and the seller after the ledger sync.
    """
    built = create_pending_payout(method="CASH", grade_code=grade_code,
                                  category=category, spot=spot,
                                  weight_lb=weight_lb, seller_tin=seller_tin)
    resp = api_client.settle_payout(built["payout"]["id"], PC)
    built["payout"] = get_success_data(resp)
    return built


# ---------------------------------------------------------------------------
# Tier 3/4: container dispatch + mill shipment
# ---------------------------------------------------------------------------
def dispatch_container(container_id):
    """GET current version, then dispatch the container. Returns dispatched container."""
    cont = get_success_data(api_client.get_container(container_id, YM))
    resp = api_client.dispatch_container(
        container_id, {"expected_container_version": cont["version"]}, YM
    )
    return get_success_data(resp)


def create_shipped_shipment(grade_code="SHRED_STEEL", category="FERROUS",
                            spot=11, mill=14, weight_lb=100,
                            gross_weight_lb=1500, tare_weight_lb=200,
                            capacity_lb=5000, lines=None,
                            hedge_id=None, ship_role=None):
    """Create a SHIPPED mill shipment from a dispatched container.

    Flow: released ticket -> dispatch container -> create mill-shipment.
    Returns dict {price, seller, ticket, container, shipment, [hedge_id]}.
    `hedge_id` optionally links an OPEN hedge to the shipment.
    """
    built = create_released_ticket(
        grade_code=grade_code, category=category, spot=spot, mill=mill,
        weight_lb=weight_lb, gross_weight_lb=gross_weight_lb,
        tare_weight_lb=tare_weight_lb, capacity_lb=capacity_lb, lines=lines,
    )
    dispatch_container(built["container_id"])
    payload = {"container_id": built["container_id"]}
    if hedge_id is not None:
        payload["hedge_position_id"] = hedge_id
    hdr = ship_role or YM
    resp = api_client.create_mill_shipment(payload, hdr)
    built["shipment"] = get_success_data(resp)
    built["hedge_id"] = hedge_id
    return built


def create_shipped_shipment_with_hedge(hedged_weight_lb=1300, locked_price=90,
                                       category="FERROUS", weight_lb=100,
                                       gross_weight_lb=1500, tare_weight_lb=200,
                                       spot=11, mill=14,
                                       grade_code="SHRED_STEEL"):
    """Open a hedge and create a SHIPPED shipment linked to it.

    Returns dict including 'shipment', 'hedge', and 'hedge_version' (the version
    observed at hedge creation, for the OCC expected_hedge_version on settle).
    """
    hedge = open_hedge(category=category, hedged_weight_lb=hedged_weight_lb,
                       locked_price=locked_price)
    built = create_shipped_shipment(
        grade_code=grade_code, category=category, spot=spot, mill=mill,
        weight_lb=weight_lb, gross_weight_lb=gross_weight_lb,
        tare_weight_lb=tare_weight_lb, capacity_lb=5000, hedge_id=hedge["id"],
    )
    built["hedge"] = hedge
    built["hedge_version"] = hedge["version"]
    return built


# ---------------------------------------------------------------------------
# Tier 5: segregation-of-duties setup (theft hold cleared, then release)
# ---------------------------------------------------------------------------
def create_released_ticket_with_cleared_hold(clearer_user_id,
                                             grade_code="SHRED_STEEL",
                                             category="FERROUS", spot=11,
                                             weight_lb=100, capacity_lb=5000):
    """Build a RELEASED ticket whose theft_hold_released_by == clearer_user_id.

    Flow: weighed ticket -> theft-hold -> clear-hold (as clearer_user_id) ->
    release. Used by segregation-of-duties payout tests.
    Returns dict {seller, ticket, container, container_id}.
    """
    built = create_weighed_ticket(grade_code=grade_code, category=category,
                                  spot=spot, weight_lb=weight_lb)
    tkt_id = built["ticket"]["id"]
    get_success_data(api_client.theft_hold(tkt_id, WM))
    clearer = make_weigh_master_headers(clearer_user_id)
    built["ticket"] = get_success_data(api_client.clear_hold(tkt_id, clearer))
    container = stage_container(category=category, capacity_lb=capacity_lb)
    built["ticket"] = get_success_data(
        api_client.release_ticket(tkt_id, {"container_id": container["id"]}, WM)
    )
    built["container"] = container
    built["container_id"] = container["id"]
    return built


# ---------------------------------------------------------------------------
# Tier 4: hedge already partly realized (for over-realize / stale-version tests)
# ---------------------------------------------------------------------------
def realize_hedge_once(hedged_weight_lb=1000, locked_price=90,
                       first_leg_weight=100, first_tare=400,
                       first_final=50000):
    """Open a hedge and realize it once via a first settled shipment.

    Returns dict {hedge_id, hedge_version_after, first_shipment}. The hedge has
    realized_weight = (gross-tare) of the first ticket; its version has advanced
    past the value observed at creation.
    """
    hedge = open_hedge(category="FERROUS", hedged_weight_lb=hedged_weight_lb,
                       locked_price=locked_price)
    first = create_shipped_shipment(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=first_leg_weight, gross_weight_lb=1000,
        tare_weight_lb=first_tare, capacity_lb=5000, hedge_id=hedge["id"],
    )
    settle_resp = api_client.settle_mill_shipment(
        first["shipment"]["id"],
        {"final_settlement_cents": first_final,
         "expected_hedge_version": hedge["version"]},
        SA,
    )
    settled = get_success_data(settle_resp)  # noqa: F841 (forces setup to complete)
    hedge_after = get_success_data(api_client.get_hedge(hedge["id"], SA))
    return {
        "hedge_id": hedge["id"],
        "hedge_version_at_open": hedge["version"],
        "hedge_version_after": hedge_after["version"],
        "first_shipment": first["shipment"],
    }
