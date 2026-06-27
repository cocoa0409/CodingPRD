"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so the DB always starts
empty). Fixtures use get_success_data() so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error downstream.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
)
from . import factories as F

BOOKSELLER = TEST_USERS["bookseller_headers"]
INVMGR = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["store_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def make_member(tier=None, is_local_author=None, email=None, full_name="Test Member"):
    """Register a member. Returns the Member dict."""
    payload = F.create_member_payload(full_name=full_name)
    if email is not None:
        payload["email"] = email
    if tier is not None:
        payload["tier"] = tier
    if is_local_author is not None:
        payload["is_local_author"] = is_local_author
    resp = api_client.create_member(payload, ANON)
    return get_success_data(resp)


def make_title(list_price_cents=1000, demand_flag=None, returnable=None,
               pod_eligible=None, category=None, isbn13=None,
               headers=BOOKSELLER, name="Test Title"):
    """Create a title. Returns the Title dict."""
    payload = F.create_title_payload(list_price_cents=list_price_cents, name=name)
    if isbn13 is not None:
        payload["isbn13"] = isbn13
    if demand_flag is not None:
        payload["demand_flag"] = demand_flag
    if returnable is not None:
        payload["returnable"] = returnable
    if pod_eligible is not None:
        payload["pod_eligible"] = pod_eligible
    if category is not None:
        payload["category"] = category
    resp = api_client.create_title(payload, headers)
    return get_success_data(resp)


def receive_stock(title_id, quantity, cost_cents=None, headers=BOOKSELLER):
    """Receive distributor stock for a title."""
    payload = F.create_stock_items_payload(quantity=quantity)
    if cost_cents is not None:
        payload["cost_cents"] = cost_cents
    resp = api_client.create_stock_items(title_id, payload, headers)
    return get_success_data(resp)


def seed_credit(member_id, delta_cents):
    """Seed store credit on a member via an admin adjustment."""
    resp = api_client.create_credit_adjustment(
        member_id, F.credit_adjustment_payload(delta_cents), ADMIN
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Sales order hierarchy
# ---------------------------------------------------------------------------
def setup_order_with_line(list_price_cents=1000, quantity=1, stock_qty=None,
                          member_tier=None, credit_redeemed_cents=None,
                          member_credit=None):
    """Member + Title (optionally stocked) + OPEN/UNPAID order with one line.

    Returns dict: member, title, order, line.
    Set stock_qty to receive AVAILABLE copies; set member_credit to seed credit;
    set credit_redeemed_cents to elect redemption at order creation.
    """
    member = make_member(tier=member_tier)
    if member_credit:
        seed_credit(member["id"], member_credit)
        member = get_success_data(api_client.get_member(member["id"], ADMIN))
    title = make_title(list_price_cents=list_price_cents)
    if stock_qty:
        receive_stock(title["id"], stock_qty)
    so_payload = F.create_sales_order_payload(member["id"])
    if credit_redeemed_cents is not None:
        so_payload["credit_redeemed_cents"] = credit_redeemed_cents
    mh = make_member_headers(member["id"])
    order = get_success_data(api_client.create_sales_order(so_payload, mh))
    line = get_success_data(api_client.create_order_line(
        order["id"], F.create_order_line_payload(title["id"], quantity), mh
    ))
    # refresh order to pick up subtotal
    order = get_success_data(api_client.get_sales_order(order["id"], mh))
    return {"member": member, "title": title, "order": order, "line": line}


def setup_paid_order(list_price_cents=1000, quantity=1, stock_qty=1,
                     member_tier=None, credit_redeemed_cents=None,
                     member_credit=None):
    """As setup_order_with_line, then PAY the order. Returns the same dict with
    `order` refreshed to PAID state (carries version after pay)."""
    ctx = setup_order_with_line(
        list_price_cents=list_price_cents, quantity=quantity, stock_qty=stock_qty,
        member_tier=member_tier, credit_redeemed_cents=credit_redeemed_cents,
        member_credit=member_credit,
    )
    mh = make_member_headers(ctx["member"]["id"])
    paid = get_success_data(api_client.pay_order(ctx["order"]["id"], mh))
    ctx["order"] = paid
    return ctx


def setup_reserved_paid_order(list_price_cents=1000, quantity=1, stock_qty=1,
                              member_tier=None):
    """Paid order, then RESERVE it (Bookseller). Returns dict with order at
    payment PAID / fulfillment RESERVED."""
    ctx = setup_paid_order(
        list_price_cents=list_price_cents, quantity=quantity, stock_qty=stock_qty,
        member_tier=member_tier,
    )
    v = ctx["order"]["version"]
    reserved = get_success_data(api_client.reserve_order(
        ctx["order"]["id"], {"expected_sales_order_version": v}, BOOKSELLER
    ))
    ctx["order"] = reserved
    return ctx


# ---------------------------------------------------------------------------
# Special orders
# ---------------------------------------------------------------------------
def setup_special_order(list_price_cents=2000, fulfillment_method="DISTRIBUTOR",
                        quantity=1, pod_eligible=None):
    """Member + Title + DRAFT SpecialOrder. Returns dict: member, title, special_order."""
    member = make_member()
    title = make_title(list_price_cents=list_price_cents, pod_eligible=pod_eligible)
    mh = make_member_headers(member["id"])
    so = get_success_data(api_client.create_special_order(
        F.create_special_order_payload(member["id"], title["id"], quantity,
                                       fulfillment_method),
        mh,
    ))
    return {"member": member, "title": title, "special_order": so}


def setup_quoted_special_order(list_price_cents=2000,
                               fulfillment_method="DISTRIBUTOR", quantity=1):
    """DRAFT->QUOTED special order. Returns dict with special_order at QUOTED."""
    ctx = setup_special_order(list_price_cents=list_price_cents,
                              fulfillment_method=fulfillment_method, quantity=quantity)
    q = get_success_data(api_client.quote_special_order(ctx["special_order"]["id"],
                                                        BOOKSELLER))
    ctx["special_order"] = q
    return ctx


def setup_special_order_revised_n_times(n, list_price_cents=2000):
    """DISTRIBUTOR special order quoted, then revised `n` times (each revise from
    QUOTED requires a re-quote). Leaves the order QUOTED after a final quote when
    n>0. Returns dict: member, title, special_order, member_headers."""
    ctx = setup_special_order(list_price_cents=list_price_cents,
                              fulfillment_method="DISTRIBUTOR")
    so_id = ctx["special_order"]["id"]
    mh = make_member_headers(ctx["member"]["id"])
    # first quote
    get_success_data(api_client.quote_special_order(so_id, BOOKSELLER))
    for _ in range(n):
        get_success_data(api_client.revise_special_order(so_id, mh))
        get_success_data(api_client.quote_special_order(so_id, BOOKSELLER))
    ctx["special_order"] = get_success_data(api_client.get_special_order(so_id, mh))
    ctx["member_headers"] = mh
    return ctx


def setup_received_special_order(list_price_cents=2000, quantity=1):
    """DISTRIBUTOR special order taken DRAFT->QUOTED->CONFIRMED->RECEIVED.
    Returns dict: member, title, special_order (RECEIVED), member_headers."""
    ctx = setup_special_order(list_price_cents=list_price_cents, quantity=quantity)
    so_id = ctx["special_order"]["id"]
    mh = make_member_headers(ctx["member"]["id"])
    get_success_data(api_client.quote_special_order(so_id, BOOKSELLER))
    get_success_data(api_client.confirm_special_order(so_id, mh))
    get_success_data(api_client.receive_special_order(so_id, BOOKSELLER))
    ctx["special_order"] = get_success_data(api_client.get_special_order(so_id, mh))
    ctx["member_headers"] = mh
    return ctx


def setup_confirmed_special_order(list_price_cents=2000, quantity=1):
    """DISTRIBUTOR special order taken DRAFT->QUOTED->CONFIRMED.
    Returns dict: member, title, special_order (CONFIRMED), member_headers."""
    ctx = setup_special_order(list_price_cents=list_price_cents, quantity=quantity)
    so_id = ctx["special_order"]["id"]
    mh = make_member_headers(ctx["member"]["id"])
    get_success_data(api_client.quote_special_order(so_id, BOOKSELLER))
    get_success_data(api_client.confirm_special_order(so_id, mh))
    ctx["special_order"] = get_success_data(api_client.get_special_order(so_id, mh))
    ctx["member_headers"] = mh
    return ctx


# ---------------------------------------------------------------------------
# Publisher returns
# ---------------------------------------------------------------------------
def setup_draft_return(stock_qty=5, return_qty=2, returnable=True,
                       list_price_cents=1000):
    """Returnable Title with stock + a DRAFT PublisherReturn. Returns dict:
    title, publisher_return."""
    title = make_title(list_price_cents=list_price_cents, returnable=returnable,
                       headers=INVMGR)
    receive_stock(title["id"], stock_qty, headers=INVMGR)
    pr = get_success_data(api_client.create_publisher_return(
        F.create_publisher_return_payload(title["id"], return_qty), INVMGR
    ))
    return {"title": title, "publisher_return": pr}


def setup_submitted_return(stock_qty=5, return_qty=2, list_price_cents=1000):
    """DRAFT->SUBMITTED publisher return (reserves copies, snapshots credit).
    Returns dict: title, publisher_return (SUBMITTED)."""
    ctx = setup_draft_return(stock_qty=stock_qty, return_qty=return_qty,
                             returnable=True, list_price_cents=list_price_cents)
    pr = ctx["publisher_return"]
    submitted = get_success_data(api_client.submit_publisher_return(
        pr["id"], {"expected_publisher_return_version": pr["version"]}, INVMGR
    ))
    ctx["publisher_return"] = submitted
    return ctx


# ---------------------------------------------------------------------------
# Buybacks
# ---------------------------------------------------------------------------
def setup_buyback_with_lines(lines, list_prices=None, demand_flags=None,
                             member_tier=None):
    """Member + Titles + a PENDING buyback with the given lines.

    `lines` is a list of (condition_grade, quantity) tuples. `list_prices` and
    `demand_flags` are parallel lists controlling each line's title; defaults
    1000 / NORMAL. Returns dict: member, titles (list), buyback, member_headers.
    """
    member = make_member(tier=member_tier)
    n = len(lines)
    if list_prices is None:
        list_prices = [1000] * n
    if demand_flags is None:
        demand_flags = [None] * n
    titles = [make_title(list_price_cents=list_prices[i], demand_flag=demand_flags[i])
              for i in range(n)]
    bb = get_success_data(api_client.create_buyback(
        F.create_buyback_payload(member["id"]), BOOKSELLER
    ))
    for i, (grade, qty) in enumerate(lines):
        get_success_data(api_client.create_buyback_line(
            bb["id"], F.create_buyback_line_payload(titles[i]["id"], grade, qty),
            BOOKSELLER,
        ))
    return {"member": member, "titles": titles, "buyback": bb}


def setup_offered_buyback(lines, list_prices=None, demand_flags=None):
    """As setup_buyback_with_lines, then make the OFFER. Returns dict with
    buyback at OFFERED (refreshed, carries offer_total_cents)."""
    ctx = setup_buyback_with_lines(lines, list_prices=list_prices,
                                   demand_flags=demand_flags)
    offered = get_success_data(api_client.offer_buyback(ctx["buyback"]["id"],
                                                        BOOKSELLER))
    ctx["buyback"] = offered
    return ctx


# ---------------------------------------------------------------------------
# Author events + tickets
# ---------------------------------------------------------------------------
def setup_event(starts_at="2026-02-01T18:00:00Z", capacity=10,
                base_price_cents=2000, demand_flag=None, list_price_cents=1000):
    """Title + future AuthorEvent. Returns dict: title, event."""
    title = make_title(list_price_cents=list_price_cents, demand_flag=demand_flag)
    event = get_success_data(api_client.create_author_event(
        F.create_author_event_payload(title["id"], starts_at, capacity,
                                      base_price_cents),
        BOOKSELLER,
    ))
    return {"title": title, "event": event}


def setup_event_with_ticket(starts_at="2026-02-01T18:00:00Z", capacity=5,
                            base_price_cents=2000, demand_flag=None,
                            member_tier=None, list_price_cents=1000):
    """Title + future event + one member holding a BOOKED ticket. Returns dict:
    title, event, member, ticket."""
    ctx = setup_event(starts_at=starts_at, capacity=capacity,
                      base_price_cents=base_price_cents, demand_flag=demand_flag,
                      list_price_cents=list_price_cents)
    member = make_member(tier=member_tier)
    mh = make_member_headers(member["id"])
    ticket = get_success_data(api_client.book_ticket(
        ctx["event"]["id"], F.book_ticket_payload(member["id"]), mh
    ))
    ctx["member"] = member
    ctx["ticket"] = ticket
    return ctx


# ---------------------------------------------------------------------------
# Consignment
# ---------------------------------------------------------------------------
def setup_agreement(list_price_cents=2000):
    """Local-author member + Title + ACTIVE ConsignmentAgreement. Returns dict:
    author, title, agreement."""
    author = make_member(is_local_author=True)
    title = make_title(list_price_cents=list_price_cents, headers=INVMGR)
    agreement = get_success_data(api_client.create_consignment_agreement(
        F.create_consignment_agreement_payload(author["id"], title["id"]), INVMGR
    ))
    return {"author": author, "title": title, "agreement": agreement}


def shelve_copy(agreement_id, sale_price_cents=2000):
    """Shelve one consigned copy. Returns the ConsignmentCopy dict."""
    return get_success_data(api_client.create_consignment_copy(
        agreement_id, F.create_consignment_copy_payload(sale_price_cents), INVMGR
    ))


def setup_agreement_with_copies(num_copies, sale_price_cents=2000,
                                list_price_cents=2000):
    """Agreement + `num_copies` ON_SHELF copies. Returns dict: author, title,
    agreement, copies (list of copy dicts)."""
    ctx = setup_agreement(list_price_cents=list_price_cents)
    copies = [shelve_copy(ctx["agreement"]["id"], sale_price_cents)
              for _ in range(num_copies)]
    ctx["copies"] = copies
    return ctx


def setup_agreement_with_units_sold(units_already_sold, sale_price_cents=2000,
                                    list_price_cents=2000):
    """Agreement where `units_already_sold` copies are already SOLD (via direct
    mark-sold), plus two more ON_SHELF copies left to sell. Returns dict: author,
    title, agreement, next_copy_ids (the two unsold copy ids in shelve order)."""
    ctx = setup_agreement(list_price_cents=list_price_cents)
    ag_id = ctx["agreement"]["id"]
    for _ in range(units_already_sold):
        c = shelve_copy(ag_id, sale_price_cents)
        get_success_data(api_client.mark_copy_sold(c["id"], BOOKSELLER))
    next_copies = [shelve_copy(ag_id, sale_price_cents) for _ in range(2)]
    ctx["next_copy_ids"] = [c["id"] for c in next_copies]
    return ctx


def setup_consignment_sale_via_fulfill(sale_price_cents=2000, list_price_cents=2000):
    """Full chain to drive a fulfill->consignment cascade:
    local author + buyer + title + ACTIVE agreement with one ON_SHELF copy (whose
    backing CONSIGNMENT StockItem is the only AVAILABLE stock), then a paid +
    reserved order for q1 of the title. Returns dict: author, buyer, title,
    agreement, order, member_headers (buyer's). Caller triggers fulfill.
    """
    ag_ctx = setup_agreement(list_price_cents=list_price_cents)
    shelve_copy(ag_ctx["agreement"]["id"], sale_price_cents)  # backing stock AVAILABLE
    buyer = make_member()
    mh = make_member_headers(buyer["id"])
    order = get_success_data(api_client.create_sales_order(
        F.create_sales_order_payload(buyer["id"]), mh
    ))
    get_success_data(api_client.create_order_line(
        order["id"], F.create_order_line_payload(ag_ctx["title"]["id"], 1), mh
    ))
    paid = get_success_data(api_client.pay_order(order["id"], mh))
    reserved = get_success_data(api_client.reserve_order(
        order["id"], {"expected_sales_order_version": paid["version"]}, BOOKSELLER
    ))
    return {
        "author": ag_ctx["author"],
        "buyer": buyer,
        "title": ag_ctx["title"],
        "agreement": ag_ctx["agreement"],
        "order": reserved,
        "member_headers": mh,
    }
