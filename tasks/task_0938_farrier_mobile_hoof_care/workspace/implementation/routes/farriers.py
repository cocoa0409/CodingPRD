"""Farriers and their certification axis (PRD 3.2)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import CERT_LEVELS, DEACTIVATE_REASONS
from core.errors import ApiError
from core.store import db, order_key
from core.timeutil import clock, parse_iso_date
from core.validate import body, enum, req_date, req_str
from domain.inventory import mint_buckets_for_farrier
from domain.lookup import must
from domain.routeops import cancel_route

from ._common import listing, single

bp = Blueprint("farriers", __name__)


@bp.post("/farriers")
def create_farrier():
    authenticate(("PlatformAdmin",))
    data = body()
    display_name = req_str(data, "display_name")
    level = data.get("certification_level")
    if not isinstance(level, str) or not level:
        from core.validate import bad

        bad("Field certification_level is required.")
    cert_expires_on = req_date(data, "cert_expires_on")
    enum(level, CERT_LEVELS, "certification_level")
    farrier = db.mint(
        "farriers",
        {
            "display_name": display_name,
            "certification_level": level,
            "cert_expires_on": cert_expires_on,
            "status": "ACTIVE",
        },
    )
    mint_buckets_for_farrier(farrier)
    return single(farrier, 201)


@bp.get("/farriers")
def list_farriers():
    return listing(
        "farriers",
        {"certification_level": "certification_level", "status": "status"},
        ("PlatformAdmin", "Dispatcher", "Farrier", "BillingClerk"),
    )


@bp.get("/farriers/<farrier_id>")
def read_farrier(farrier_id):
    authenticate(("PlatformAdmin", "Dispatcher", "Farrier", "BillingClerk"))
    return single(must("farriers", farrier_id))


@bp.post("/farriers/<farrier_id>/deactivate")
def deactivate_farrier(farrier_id):
    authenticate(("PlatformAdmin",))
    farrier = must("farriers", farrier_id)
    data = body()
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason:
        from core.validate import bad

        bad("Field reason is required.")
    enum(reason, DEACTIVATE_REASONS, "reason")
    if farrier["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    farrier["status"] = "INACTIVE" if reason == "VOLUNTARY" else "DECERTIFIED"
    routes = [
        r
        for r in db.routes.values()
        if r["farrier_id"] == farrier["id"] and r["status"] in ("DRAFT", "PLANNED")
    ]
    for route in sorted(routes, key=order_key):
        cancel_route(route)
    db.touch(farrier)
    return single(farrier)


@bp.post("/farriers/<farrier_id>/reactivate")
def reactivate_farrier(farrier_id):
    authenticate(("PlatformAdmin",))
    farrier = must("farriers", farrier_id)
    if farrier["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    farrier["status"] = "ACTIVE"
    db.touch(farrier)
    return single(farrier)


@bp.post("/farriers/<farrier_id>/recertify")
def recertify_farrier(farrier_id):
    authenticate(("PlatformAdmin",))
    farrier = must("farriers", farrier_id)
    data = body()
    level = data.get("certification_level")
    if not isinstance(level, str) or not level:
        from core.validate import bad

        bad("Field certification_level is required.")
    cert_expires_on = req_date(data, "cert_expires_on")
    enum(level, CERT_LEVELS, "certification_level")
    if farrier["status"] != "DECERTIFIED":
        raise ApiError("ERR_INVALID_STATE")
    if parse_iso_date(cert_expires_on) < clock.today:
        raise ApiError("ERR_INVALID_STATE")
    farrier["certification_level"] = level
    farrier["cert_expires_on"] = cert_expires_on
    farrier["status"] = "ACTIVE"
    db.touch(farrier)
    return single(farrier)
