"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server against an empty database before
every test). Setup calls use get_success_data() so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: after creating an Account, all Buyer-scoped (ownership-gated)
calls use make_buyer_headers(account_id), never the shared Buyer constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import ACCOUNT_MANAGER_HEADERS, WAREHOUSE_HEADERS, make_buyer_headers
from . import factories as f


def _d(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #
def create_account(api=None, **overrides):
    api = api or api_client
    return _d(api.create_account(f.account_payload(**overrides), ACCOUNT_MANAGER_HEADERS))


def create_product(api=None, **overrides):
    api = api or api_client
    return _d(api.create_product(f.product_payload(**overrides), WAREHOUSE_HEADERS))


def create_order(api, account_id):
    return _d(api.create_order(f.order_payload(account_id), make_buyer_headers(account_id)))


def add_line(api, order_id, account_id, product_id, quantity):
    return _d(api.add_order_line(order_id, f.order_line_payload(product_id, quantity),
                                 make_buyer_headers(account_id)))


def account_version(api, account_id):
    return _d(api.get_account(account_id, WAREHOUSE_HEADERS))["version"]


def confirm_order(api, order_id, account_id, version=None):
    if version is None:
        version = account_version(api, account_id)
    return _d(api.confirm_order(order_id, {"expected_account_version": version},
                                make_buyer_headers(account_id)))


def create_shipment(api, order_id, carrier="UPS", liftgate_required=None):
    payload = f.shipment_payload(order_id, carrier=carrier)
    if liftgate_required is not None:
        payload["liftgate_required"] = liftgate_required
    return _d(api.create_shipment(payload, WAREHOUSE_HEADERS))


def book_shipment(api, shipment_id):
    return _d(api.book_shipment(shipment_id, WAREHOUSE_HEADERS))


def deliver_shipment(api, shipment_id):
    return _d(api.deliver_shipment(shipment_id, WAREHOUSE_HEADERS))


def open_return(api, order_id, account_id, reason="Return"):
    return _d(api.create_return(order_id, f.return_payload(reason), make_buyer_headers(account_id)))


def add_return_line(api, return_id, account_id, product_id, quantity, condition):
    return _d(api.add_return_line(return_id,
                                  f.return_line_payload(product_id, quantity, condition),
                                  make_buyer_headers(account_id)))


def approve_return(api, return_id):
    return _d(api.approve_return(return_id, WAREHOUSE_HEADERS))


def receive_return(api, return_id):
    return _d(api.receive_return(return_id, WAREHOUSE_HEADERS))


def refund_return(api, return_id):
    return _d(api.refund_return(return_id, WAREHOUSE_HEADERS))


def create_dock(api, name="Dock 1"):
    return _d(api.create_dock(f.dock_payload(name), WAREHOUSE_HEADERS))


def create_crew(api, name="Crew 1"):
    return _d(api.create_crew(f.crew_payload(name), WAREHOUSE_HEADERS))


def set_clock(api, iso):
    return _d(api.set_clock(iso, WAREHOUSE_HEADERS))


# --------------------------------------------------------------------------- #
# Composites
# --------------------------------------------------------------------------- #
def confirmed_order_with_line(api, product_overrides=None, quantity=1, credit_limit_cents=100_000_000,
                              account_overrides=None):
    """Active account + product + a CONFIRMED order carrying one line.

    Returns (account, product, order, line).
    """
    acct = create_account(api, credit_limit_cents=credit_limit_cents, **(account_overrides or {}))
    prod = create_product(api, **(product_overrides or {}))
    order = create_order(api, acct["id"])
    line = add_line(api, order["id"], acct["id"], prod["id"], quantity)
    confirm_order(api, order["id"], acct["id"])
    return acct, prod, order, line


def delivered_order_with_line(api, product_overrides=None, quantity=1, carrier="UPS",
                              credit_limit_cents=100_000_000):
    """Active account + product + an order confirmed, shipped, and DELIVERED
    (lifecycle COMPLETED). Returns (account, product, order, line, shipment).
    """
    acct = create_account(api, credit_limit_cents=credit_limit_cents)
    prod = create_product(api, **(product_overrides or {}))
    order = create_order(api, acct["id"])
    line = add_line(api, order["id"], acct["id"], prod["id"], quantity)
    confirm_order(api, order["id"], acct["id"])
    ship = create_shipment(api, order["id"], carrier=carrier)
    book_shipment(api, ship["id"])
    deliver_shipment(api, ship["id"])
    return acct, prod, order, line, ship


def approved_certificate_account(api, credit_limit_cents=100_000_000):
    """Account whose Buyer-submitted certificate has been APPROVED
    (tax_exempt_status CERTIFIED). Returns (account, cert)."""
    acct = create_account(api, credit_limit_cents=credit_limit_cents)
    cert = _d(api.create_certificate(acct["id"], f.certificate_payload(),
                                     make_buyer_headers(acct["id"])))
    _d(api.approve_certificate(cert["id"], ACCOUNT_MANAGER_HEADERS))
    return acct, cert
