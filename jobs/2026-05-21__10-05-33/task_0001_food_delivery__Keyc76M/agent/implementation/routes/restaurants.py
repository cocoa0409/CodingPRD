"""Restaurant resource endpoints and lifecycle actions."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import restaurants as svc


bp = Blueprint("restaurants", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def _valid_name(v):
    return isinstance(v, str) and 1 <= len(v) <= 120


def _valid_lat(v):
    return validators.is_number(v) and -90 <= float(v) <= 90


def _valid_lng(v):
    return validators.is_number(v) and -180 <= float(v) <= 180


def _valid_rate(v):
    if v is None:
        return True
    if not validators.is_number(v):
        return False
    return 0.05 <= float(v) <= 0.35


@bp.route("/api/restaurants", methods=["POST"])
def register_restaurant():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "PlatformAdmin":
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    for field in ("name", "address", "lat", "lng"):
        if field not in payload:
            return envelope.validation(f"Missing required field '{field}'.")

    name = payload["name"]
    if not _valid_name(name):
        return envelope.validation("name must be a 1-120 character string.")

    address = payload["address"]
    if not isinstance(address, str) or not address:
        return envelope.validation("address must be a non-empty string.")

    lat = payload["lat"]
    lng = payload["lng"]
    if not _valid_lat(lat):
        return envelope.validation("lat must be a number in [-90, 90].")
    if not _valid_lng(lng):
        return envelope.validation("lng must be a number in [-180, 180].")

    rate = payload.get("commission_rate_override")
    if not _valid_rate(rate):
        return envelope.validation(
            "commission_rate_override must be a number in [0.05, 0.35]."
        )

    with state.lock():
        # Name must be unique among active restaurants.
        if svc.is_name_taken_among_active(name):
            return envelope.error(
                409, "ERR_INVALID_STATE",
                "Restaurant name already in use by an active restaurant.",
            )
        rec = svc.new_restaurant(name, address, float(lat), float(lng), rate)
        return envelope.created(projection.render(rec))


@bp.route("/api/restaurants/<rid>", methods=["GET"])
def get_restaurant(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    allowed = {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}
    if role not in allowed:
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        return envelope.success(projection.render(rec))


@bp.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    allowed = {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}
    if role not in allowed:
        return envelope.forbidden()

    page, perr = validators.pagination_params(request.args)
    if perr:
        return perr
    limit, offset = page

    status_filter = request.args.get("status")
    with state.lock():
        all_recs = list(state.STORE.restaurants.values())
        if status_filter:
            all_recs = [r for r in all_recs if r["status"] == status_filter]
        all_recs.sort(key=lambda r: r["created_at"])
        total = len(all_recs)
        window = all_recs[offset : offset + limit]
        return envelope.list_response(
            [projection.render(r) for r in window], limit, offset, total
        )


@bp.route("/api/restaurants/<rid>", methods=["PATCH"])
def patch_restaurant(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "Restaurant"):
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        if role == "Restaurant" and user_id != rec["id"]:
            return envelope.forbidden()

        # Allowed mutable fields
        allowed_keys = {"address", "lat", "lng", "commission_rate_override", "version"}
        bad_keys = set(payload.keys()) - allowed_keys
        if "name" in bad_keys:
            return envelope.validation("name is immutable after creation.")
        if bad_keys:
            return envelope.validation(
                f"Field(s) not editable: {', '.join(sorted(bad_keys))}."
            )

        if "address" in payload:
            if not isinstance(payload["address"], str) or not payload["address"]:
                return envelope.validation("address must be a non-empty string.")
        if "lat" in payload and not _valid_lat(payload["lat"]):
            return envelope.validation("lat must be a number in [-90, 90].")
        if "lng" in payload and not _valid_lng(payload["lng"]):
            return envelope.validation("lng must be a number in [-180, 180].")
        if "commission_rate_override" in payload and not _valid_rate(
            payload["commission_rate_override"]
        ):
            return envelope.validation(
                "commission_rate_override must be a number in [0.05, 0.35] or null."
            )

        # OCC
        if "version" in payload:
            if payload["version"] != rec["version"]:
                return envelope.version_conflict()

        # Apply
        for k in ("address", "lat", "lng", "commission_rate_override"):
            if k in payload:
                rec[k] = payload[k]
        svc.bump(rec)
        return envelope.success(projection.render(rec))


# --- Lifecycle action helpers ---

def _admin_only():
    user_id, role = auth.headers()
    if not user_id:
        return None, envelope.auth_required()
    if role != "PlatformAdmin":
        return None, envelope.forbidden()
    return (user_id, role), None


@bp.route("/api/restaurants/<rid>/approve", methods=["POST"])
def approve_restaurant(rid):
    _, err = _admin_only()
    if err:
        return err
    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        if rec["status"] != "PENDING_APPROVAL":
            return envelope.invalid_state(
                "Only PENDING_APPROVAL restaurants can be approved."
            )
        # Re-claim name uniqueness on becoming active
        if svc.is_name_taken_among_active(rec["name"], except_id=rec["id"]):
            return envelope.invalid_state(
                "Restaurant name conflicts with an active restaurant."
            )
        rec["status"] = "ACTIVE"
        svc.claim_name(rec["name"], rec["id"])
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/restaurants/<rid>/suspend", methods=["POST"])
def suspend_restaurant(rid):
    _, err = _admin_only()
    if err:
        return err
    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        if rec["status"] != "ACTIVE":
            return envelope.invalid_state(
                "Only ACTIVE restaurants can be suspended."
            )
        rec["status"] = "SUSPENDED"
        svc.release_name(rec["name"], rec["id"])
        svc.bump(rec)
        # Fan-out: cancel each PLACED order for this restaurant.
        for o in state.STORE.orders.values():
            if o["restaurant_id"] == rec["id"] and o["status"] == "PLACED":
                o["status"] = "CANCELLED"
                if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
                    o["payment_status"] = "VOIDED"
                o["updated_at"] = state.now()
                o["version"] = o["version"] + 1
        return envelope.success(projection.render(rec))


@bp.route("/api/restaurants/<rid>/reinstate", methods=["POST"])
def reinstate_restaurant(rid):
    _, err = _admin_only()
    if err:
        return err
    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        if rec["status"] != "SUSPENDED":
            return envelope.invalid_state(
                "Only SUSPENDED restaurants can be reinstated."
            )
        if svc.is_name_taken_among_active(rec["name"], except_id=rec["id"]):
            return envelope.invalid_state(
                "Restaurant name conflicts with an active restaurant."
            )
        rec["status"] = "ACTIVE"
        svc.claim_name(rec["name"], rec["id"])
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/restaurants/<rid>/settle", methods=["POST"])
def settle_restaurant(rid):
    _, err = _admin_only()
    if err:
        return err
    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        rec["pending_settlement_cents"] = 0
        svc.bump(rec)
        return envelope.success(projection.render(rec))
