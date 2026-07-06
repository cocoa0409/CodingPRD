"""Composite setup helpers for the Comic Book & Graphic-Novel Shop platform.

Most interesting claims require the system to reach a multi-step state: an
ON_SALE issue with allocated reservations, a customer carrying store credit, a
consignment that has been listed then sold, an OPEN event with registrations, a
grading submission cycled to RETURNED, and so on. These helpers encapsulate
those preambles so tests focus on assertions.

The harness restarts the server and clears the database before every test, so
every helper builds its preconditions from scratch using only PRD endpoints.
Setup calls use get_success_data() (lenient) so a setup failure reads as
"Setup failed" rather than a confusing assertion error.

Identity threading: the only entity-backed role is Customer. After creating a
Customer, ownership-gated customer actions (release own reservation, cancel own
pre-order, dispute own grading submission, cancel own registration) use
make_customer_headers(customer["id"]). Store-staff operations use the opaque
Clerk / Manager constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_customer_payload,
    create_credit_adjustment_payload,
    create_comic_series_payload,
    create_comic_issue_payload,
    create_pull_subscription_payload,
    create_reservation_payload,
    create_pre_order_payload,
    create_grading_submission_payload,
    create_event_payload,
    create_event_registration_payload,
    create_consignment_payload,
    create_checkout_payload,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=CLERK):
    """Advance the server's logical clock to a supplied instant."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def create_customer(**overrides):
    """Create a customer (defaults to BRONZE, zero balances). Returns customer."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CLERK)
    )


def create_series(**overrides):
    """Create an ACTIVE comic series. Returns series."""
    return get_success_data(
        api_client.create_comic_series(create_comic_series_payload(**overrides), CLERK)
    )


def create_issue(series_id: str, **overrides):
    """Create a SOLICITED comic issue under a series. Returns issue."""
    return get_success_data(
        api_client.create_comic_issue(
            create_comic_issue_payload(series_id, **overrides), CLERK
        )
    )


def advance_issue(issue_id: str, to_status: str):
    """Advance an issue by one transition. Returns updated issue."""
    return get_success_data(
        api_client.transition_comic_issue(issue_id, {"to_status": to_status}, CLERK)
    )


def get_issue(issue_id: str):
    """Read the current issue (used to observe the latest version)."""
    return get_success_data(api_client.get_comic_issue(issue_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 1 / 2: issue-lifecycle composites
# ---------------------------------------------------------------------------
def create_on_sale_issue(copies_ordered: int = 5, cover_price_cents: int = 400,
                         **issue_overrides):
    """Series + issue walked SOLICITED -> ORDERED -> ON_SALE.

    Returns (series, issue) where issue reflects the ON_SALE read (current
    version included).
    """
    series = create_series()
    issue = create_issue(series["id"], copies_ordered=copies_ordered,
                         cover_price_cents=cover_price_cents, **issue_overrides)
    advance_issue(issue["id"], "ORDERED")
    issue = advance_issue(issue["id"], "ON_SALE")
    return series, issue


def create_reservation(customer_id: str, issue_id: str, requested_qty: int = 1,
                       subscription_id=None, headers=CLERK):
    """Create a reservation, threading the issue's current version for OCC.

    Re-reads the issue immediately before the create so
    expected_comic_issue_version is fresh. Returns the created reservation.
    """
    issue = get_issue(issue_id)
    overrides = {"requested_qty": requested_qty}
    if subscription_id is not None:
        overrides["subscription_id"] = subscription_id
    payload = create_reservation_payload(
        customer_id, issue_id, issue["version"], **overrides
    )
    return get_success_data(api_client.create_reservation(payload, headers))


def setup_reserved_issue(copies_ordered: int = 5, requested_qty: int = 1,
                         cover_price_cents: int = 400):
    """ON_SALE issue + one RESERVED reservation (allocation not yet run).

    Returns (customer, series, issue, reservation).
    """
    series, issue = create_on_sale_issue(copies_ordered=copies_ordered,
                                         cover_price_cents=cover_price_cents)
    customer = create_customer()
    reservation = create_reservation(customer["id"], issue["id"], requested_qty)
    return customer, series, issue, reservation


def setup_allocated_reservation(copies_ordered: int = 3, requested_qty: int = 1,
                                cover_price_cents: int = 400):
    """ON_SALE issue + one reservation ALLOCATED via run-allocation.

    Returns (customer, series, issue, reservation) with reservation re-read
    after allocation.
    """
    customer, series, issue, reservation = setup_reserved_issue(
        copies_ordered=copies_ordered, requested_qty=requested_qty,
        cover_price_cents=cover_price_cents,
    )
    get_success_data(api_client.run_allocation(issue["id"], CLERK))
    reservation = get_success_data(
        api_client.get_reservation(reservation["id"], CLERK)
    )
    return customer, series, issue, reservation


def setup_allocated_plus_waitlisted(cover_price_cents: int = 400):
    """ON_SALE issue with copies_ordered=1; customer A ALLOCATED, customer B
    WAITLISTED, after a single run-allocation.

    Reservation A is created first (earlier created_at). Both customers are
    BRONZE. Returns (issue, cust_a, res_a, cust_b, res_b).
    """
    series, issue = create_on_sale_issue(copies_ordered=1,
                                         cover_price_cents=cover_price_cents)
    cust_a = create_customer()
    cust_b = create_customer()
    res_a = create_reservation(cust_a["id"], issue["id"], requested_qty=1)
    res_b = create_reservation(cust_b["id"], issue["id"], requested_qty=1)
    get_success_data(api_client.run_allocation(issue["id"], CLERK))
    res_a = get_success_data(api_client.get_reservation(res_a["id"], CLERK))
    res_b = get_success_data(api_client.get_reservation(res_b["id"], CLERK))
    return issue, cust_a, res_a, cust_b, res_b


def setup_subscription_allocated_plus_waitlisted():
    """copies_ordered=1 ON_SALE issue; customer A has an ACTIVE subscription and
    a subscription-linked ALLOCATED reservation; customer B has a WAITLISTED
    reservation. For the depth-3 subscription-cancel cascade.

    Returns (issue, sub_a, cust_a, res_a, cust_b, res_b).
    """
    series, issue = create_on_sale_issue(copies_ordered=1)
    cust_a = create_customer()
    cust_b = create_customer()
    sub_a = get_success_data(
        api_client.create_pull_subscription(
            create_pull_subscription_payload(cust_a["id"], series["id"]), CLERK
        )
    )
    res_a = create_reservation(cust_a["id"], issue["id"], requested_qty=1,
                               subscription_id=sub_a["id"])
    res_b = create_reservation(cust_b["id"], issue["id"], requested_qty=1)
    get_success_data(api_client.run_allocation(issue["id"], CLERK))
    res_a = get_success_data(api_client.get_reservation(res_a["id"], CLERK))
    res_b = get_success_data(api_client.get_reservation(res_b["id"], CLERK))
    return issue, sub_a, cust_a, res_a, cust_b, res_b


# ---------------------------------------------------------------------------
# Customer wallet / loyalty
# ---------------------------------------------------------------------------
def customer_with_store_credit(amount_cents: int, reason: str = "ADJUSTMENT"):
    """Create a customer and credit their wallet via a Manager adjustment.

    Returns (customer_read, txn) with the customer re-read after the
    adjustment so store_credit_cents reflects the credit.
    """
    customer = create_customer()
    txn = get_success_data(
        api_client.create_credit_adjustment(
            customer["id"], create_credit_adjustment_payload(amount_cents, reason),
            MANAGER,
        )
    )
    customer = get_success_data(api_client.get_customer(customer["id"], CLERK))
    return customer, txn


def checkout(customer_id: str, line_items, headers=CLERK, **overrides):
    """Run a checkout. Returns the checkout response data."""
    return get_success_data(
        api_client.checkout(
            create_checkout_payload(customer_id, line_items, **overrides), headers
        )
    )


def customer_with_confirmed_preorder(cover_price_cents: int, quantity: int = 1,
                                     lifetime_checkout_cents: int = 0):
    """Customer with one CONFIRMED pre-order (estimated_total = quantity *
    cover_price_cents), optionally after a checkout that sets lifetime spend.

    The pre-order is confirmed while the clock is at its 2026-03-01 default,
    which is strictly before the 2026-03-15 default cutoff. Returns
    (customer_read, issue, pre_order).
    """
    customer = create_customer()
    if lifetime_checkout_cents > 0:
        checkout(customer["id"],
                 [{"unit_price_cents": lifetime_checkout_cents, "quantity": 1}])
    series = create_series()
    issue = create_issue(series["id"], cover_price_cents=cover_price_cents)
    pre_order = get_success_data(
        api_client.create_pre_order(
            create_pre_order_payload(customer["id"], issue["id"], quantity=quantity),
            CLERK,
        )
    )
    pre_order = get_success_data(
        api_client.transition_pre_order(
            pre_order["id"], {"to_status": "CONFIRMED"}, CLERK
        )
    )
    customer = get_success_data(api_client.get_customer(customer["id"], CLERK))
    return customer, issue, pre_order


# ---------------------------------------------------------------------------
# Consignment
# ---------------------------------------------------------------------------
def create_listed_consignment(asking_price_cents: int = 10000,
                              commission_pct: float = 0.30):
    """Customer (consignor) + consignment walked RECEIVED -> LISTED.

    Returns (customer, consignment) with the consignment re-read after LISTED.
    """
    customer = create_customer()
    overrides = {"asking_price_cents": asking_price_cents}
    if commission_pct is not None:
        overrides["commission_pct"] = commission_pct
    consignment = get_success_data(
        api_client.create_consignment(
            create_consignment_payload(customer["id"], **overrides), CLERK
        )
    )
    consignment = get_success_data(
        api_client.transition_consignment(
            consignment["id"], {"to_status": "LISTED"}, CLERK
        )
    )
    return customer, consignment


def create_sold_consignment(asking_price_cents: int = 10000,
                            sale_price_cents: int = 10000,
                            commission_pct: float = 0.30):
    """Consignment walked RECEIVED -> LISTED -> SOLD at sale_price_cents.

    Returns (customer, consignment) with the consignment re-read after SOLD.
    """
    customer, consignment = create_listed_consignment(
        asking_price_cents=asking_price_cents, commission_pct=commission_pct
    )
    consignment = get_success_data(
        api_client.transition_consignment(
            consignment["id"],
            {"to_status": "SOLD", "sale_price_cents": sale_price_cents},
            CLERK,
        )
    )
    return customer, consignment


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def create_open_event(capacity: int = 5, store_location: str = "LOC1",
                      starts_at: str = "2026-05-01T10:00:00Z",
                      ends_at: str = "2026-05-01T12:00:00Z", name: str = "Signing"):
    """Create an event and open it (DRAFT -> OPEN). Returns the OPEN event."""
    event = get_success_data(
        api_client.create_event(
            create_event_payload(capacity=capacity, store_location=store_location,
                                 starts_at=starts_at, ends_at=ends_at, name=name),
            CLERK,
        )
    )
    event = get_success_data(
        api_client.transition_event(event["id"], {"to_status": "OPEN"}, CLERK)
    )
    return event


def register_customer(customer_id: str, event_id: str):
    """Register a customer for an event. Returns the registration."""
    return get_success_data(
        api_client.create_event_registration(
            create_event_registration_payload(customer_id, event_id), CLERK
        )
    )


# ---------------------------------------------------------------------------
# Grading submissions
# ---------------------------------------------------------------------------
def grading_submission_returned(grade_result: float = 9.0, declared_value_cents: int = 50000):
    """Grading submission advanced INTAKE -> SUBMITTED -> AT_GRADER -> RETURNED.

    Returns (customer, submission) with the submission re-read after RETURNED.
    """
    customer = create_customer()
    gs = get_success_data(
        api_client.create_grading_submission(
            create_grading_submission_payload(
                customer["id"], declared_value_cents=declared_value_cents
            ),
            CLERK,
        )
    )
    api_client.transition_grading_submission(gs["id"], {"to_status": "SUBMITTED"}, CLERK)
    api_client.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, CLERK)
    gs = get_success_data(
        api_client.transition_grading_submission(
            gs["id"], {"to_status": "RETURNED", "grade_result": grade_result}, CLERK
        )
    )
    return customer, gs


def grading_submission_at_dispute_limit():
    """Grading submission cycled through 3 disputes (dispute_count == 3),
    currently RETURNED. Each dispute is issued by the owning customer (its own
    resource); each regrade RETURN is done by the Clerk.

    Returns (customer, submission) with the submission re-read (dispute_count 3).
    """
    customer, gs = grading_submission_returned(grade_result=8.0)
    owner = make_customer_headers(customer["id"])
    grades = [8.1, 8.2, 8.3]
    for g in grades:
        api_client.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, owner)
        gs = get_success_data(
            api_client.transition_grading_submission(
                gs["id"], {"to_status": "RETURNED", "grade_result": g}, CLERK
            )
        )
    return customer, gs
