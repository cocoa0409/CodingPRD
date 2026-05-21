"""Customer endpoints."""

from __future__ import annotations

from auth import require_role
from envelope import success
from errors import APIError
from resources import make_versioned
from store import STORE
from validation import get_body, require_number, require_str


def _serialize(c: dict) -> dict:
    return {
        "id": c["id"],
        "name": c["name"],
        "phone": c["phone"],
        "address": c["address"],
        "lat": c["lat"],
        "lng": c["lng"],
        "credit_balance_cents": c["credit_balance_cents"],
        "trust_score": c["trust_score"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def register(app):
    @app.post("/api/customers")
    def register_customer():
        require_role({"PlatformAdmin", "CustomerService"})
        body = get_body()
        name = require_str(body, "name", min_length=1, max_length=200)
        phone = require_str(body, "phone", min_length=1, max_length=40)
        address = require_str(body, "address", min_length=1)
        lat = require_number(body, "lat")
        lng = require_number(body, "lng")
        if lat < -90 or lat > 90 or lng < -180 or lng > 180:
            raise APIError("ERR_VALIDATION", "lat/lng out of range.")
        with STORE.lock:
            if phone in STORE.customer_phones:
                raise APIError("ERR_VALIDATION", "Customer phone already registered.")
            customer = make_versioned({
                "name": name,
                "phone": phone,
                "address": address,
                "lat": lat,
                "lng": lng,
                "credit_balance_cents": 0,
                "trust_score": 1.0,
            })
            STORE.customers[customer["id"]] = customer
            STORE.customer_phones.add(phone)
            return success(_serialize(customer), status=201)

    @app.get("/api/customers/<cid>")
    def read_customer(cid: str):
        user_id, role = require_role({"PlatformAdmin", "Customer", "CustomerService"})
        with STORE.lock:
            c = STORE.customers.get(cid)
            if c is None:
                raise APIError("ERR_NOT_FOUND", "No such customer.")
            if role == "Customer" and user_id != c["id"]:
                raise APIError("ERR_FORBIDDEN")
            return success(_serialize(c))
