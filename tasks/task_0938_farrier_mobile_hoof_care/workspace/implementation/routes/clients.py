"""Clients, deposits and payments (PRD 3.1, 3.9)."""

from flask import Blueprint

from core.auth import authenticate
from core.errors import ApiError
from core.store import db
from core.validate import body, opt_bool, opt_int, out_of_range, req_int, req_str
from domain.clients import apply_payment, refresh_client_standing
from domain.lookup import guard_client_resource, must

from ._common import listing, single

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    authenticate(("PlatformAdmin",))
    data = body()
    display_name = req_str(data, "display_name")
    home_barn_id = req_str(data, "home_barn_id")
    tax_exempt = opt_bool(data, "tax_exempt", default=False)
    opening = opt_int(data, "opening_completed_visit_count", default=0)
    must("barns", home_barn_id)
    if opening < 0:
        out_of_range("opening_completed_visit_count may not be negative.")
    row = db.mint(
        "clients",
        {
            "display_name": display_name,
            "home_barn_id": home_barn_id,
            "billing_standing": "ACTIVE",
            "deposit_balance_cents": 0,
            "credit_balance_cents": 0,
            "completed_visit_count": opening,
            "no_show_count_rolling": 0,
            "tax_exempt": tax_exempt,
        },
    )
    return single(row, 201)


@bp.get("/clients")
def list_clients():
    return listing(
        "clients",
        {"home_barn_id": "home_barn_id", "billing_standing": "billing_standing"},
        ("PlatformAdmin", "Dispatcher", "BillingClerk"),
    )


@bp.get("/clients/<client_id>")
def read_client(client_id):
    authenticate(("PlatformAdmin", "Dispatcher", "BillingClerk", "ClientUser"))
    guard_client_resource(client_id)
    return single(must("clients", client_id))


@bp.post("/clients/<client_id>/deposits")
def post_deposit(client_id):
    authenticate(("BillingClerk",))
    client = must("clients", client_id)
    data = body()
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        out_of_range("amount_cents must be strictly positive.")
    client["deposit_balance_cents"] += amount
    refresh_client_standing(client)
    db.touch(client)
    return single(client)


@bp.post("/clients/<client_id>/payments")
def post_payment(client_id):
    authenticate(("BillingClerk",))
    client = must("clients", client_id)
    data = body()
    amount = req_int(data, "amount_cents")
    expected = req_int(data, "expected_client_version")
    if amount <= 0:
        out_of_range("amount_cents must be strictly positive.")
    if expected != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION")
    apply_payment(client, amount)
    db.touch(client)
    return single(client)
