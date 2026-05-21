"""Rider endpoints."""

from __future__ import annotations

from auth import require_role
from envelope import success
from errors import APIError
from resources import make_versioned, touch
from rider_metrics import recompute_acceptance_rate, recompute_bonus_tier, recompute_on_time_rate
from store import STORE
from validation import get_body, require_str


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "status": r["status"],
        "on_time_rate": r["on_time_rate"],
        "acceptance_rate": r["acceptance_rate"],
        "rating": r["rating"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "bonus_tier": r["bonus_tier"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _has_active_assignment(rider_id: str) -> bool:
    for a in STORE.assignments.values():
        if a["rider_id"] == rider_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return True
    return False


def register(app):
    @app.post("/api/riders")
    def register_rider():
        require_role({"PlatformAdmin"})
        body = get_body()
        name = require_str(body, "name", min_length=1, max_length=200)
        phone = require_str(body, "phone", min_length=1, max_length=40)
        with STORE.lock:
            if phone in STORE.rider_phones:
                raise APIError("ERR_VALIDATION", "Rider phone already registered.")
            rider = make_versioned({
                "name": name,
                "phone": phone,
                "status": "OFFLINE",
                "on_time_rate": 1.0,
                "acceptance_rate": 1.0,
                "rating": 5.0,
                "wallet_balance_cents": 0,
                "bonus_tier": "BRONZE",
            })
            recompute_bonus_tier(rider)
            STORE.riders[rider["id"]] = rider
            STORE.rider_phones.add(phone)
            return success(_serialize(rider), status=201)

    @app.get("/api/riders/<rider_id>")
    def read_rider(rider_id: str):
        user_id, role = require_role({"PlatformAdmin", "Rider", "CustomerService"})
        with STORE.lock:
            r = STORE.riders.get(rider_id)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such rider.")
            if role == "Rider" and user_id != r["id"]:
                raise APIError("ERR_FORBIDDEN")
            return success(_serialize(r))

    @app.post("/api/riders/<rider_id>/go-online")
    def go_online(rider_id: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            r = STORE.riders.get(rider_id)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such rider.")
            if user_id != r["id"]:
                raise APIError("ERR_FORBIDDEN")
            if r["status"] != "OFFLINE":
                raise APIError("ERR_INVALID_STATE", "Rider must be OFFLINE to go online.")
            r["status"] = "AVAILABLE"
            touch(r)
            return success(_serialize(r))

    @app.post("/api/riders/<rider_id>/go-offline")
    def go_offline(rider_id: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            r = STORE.riders.get(rider_id)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such rider.")
            if user_id != r["id"]:
                raise APIError("ERR_FORBIDDEN")
            if r["status"] != "AVAILABLE":
                raise APIError("ERR_INVALID_STATE", "Rider must be AVAILABLE to go offline.")
            if _has_active_assignment(r["id"]):
                raise APIError("ERR_INVALID_STATE", "Rider has active assignment(s).")
            r["status"] = "OFFLINE"
            touch(r)
            return success(_serialize(r))

    @app.post("/api/riders/<rider_id>/suspend")
    def suspend_rider(rider_id: str):
        require_role({"PlatformAdmin"})
        with STORE.lock:
            r = STORE.riders.get(rider_id)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such rider.")
            if r["status"] != "AVAILABLE":
                raise APIError("ERR_INVALID_STATE", "Only AVAILABLE riders can be suspended.")
            if not (r["on_time_rate"] < 0.70 or r["acceptance_rate"] < 0.50):
                raise APIError("ERR_SUSPEND_CRITERIA_NOT_MET")
            r["status"] = "SUSPENDED"
            touch(r)
            return success(_serialize(r))
