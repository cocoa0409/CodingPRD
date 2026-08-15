"""CustomerSite endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, touch
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_enum,
    pagination_params, paginate,
)
from response import success, success_list

bp = Blueprint("sites", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver", "WarehouseOperator"]
DELIVERY_MODES = ("DOCK_TO_STOCK", "LINE_SIDE")
SITE_STATUSES = ("ACTIVE", "RETIRED")


def serialize(site):
    return {
        "id": site["id"],
        "name": site["name"],
        "ship_to_code": site["ship_to_code"],
        "status": site["status"],
        "credit_limit_cents": site["credit_limit_cents"],
        "outstanding_balance_cents": site["outstanding_balance_cents"],
        "delivery_mode": site["delivery_mode"],
        "created_at": site["created_at"],
        "updated_at": site["updated_at"],
        "version": site["version"],
    }


@bp.post("/vmi/sites")
def create_site():
    role = authenticate()
    body = json_body()
    name = as_str(need(body, "name"), "name")
    ship_to_code = as_str(need(body, "ship_to_code"), "ship_to_code")
    credit_limit_cents = as_int(need(body, "credit_limit_cents"), "credit_limit_cents")
    if credit_limit_cents < 0:
        raise errors.invalid_request("credit_limit_cents must be >= 0")
    delivery_mode = as_enum(need(body, "delivery_mode"), "delivery_mode", DELIVERY_MODES)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        if any(s["ship_to_code"] == ship_to_code for s in store.sites.values()):
            raise errors.duplicate("ship_to_code already in use")
        ts = now_iso()
        site = {
            "id": new_id(),
            "name": name,
            "ship_to_code": ship_to_code,
            "status": "ACTIVE",
            "credit_limit_cents": credit_limit_cents,
            "outstanding_balance_cents": 0,
            "delivery_mode": delivery_mode,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.sites[site["id"]] = site
        return success(serialize(site), 201)


@bp.get("/vmi/sites/<sid>")
def get_site(sid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    site = store.sites.get(sid)
    if site is None:
        raise errors.not_found("site not found")
    return success(serialize(site), 200)


@bp.get("/vmi/sites")
def list_sites():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = sorted(store.sites.values(), key=lambda s: s["_seq"])
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s) for s in page], total, limit, offset)


@bp.post("/vmi/sites/<sid>/retire")
def retire_site(sid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        site = store.sites.get(sid)
        if site is None:
            raise errors.not_found("site not found")
        if site["status"] != "ACTIVE":
            raise errors.invalid_state("site is not ACTIVE")
        if any(
            a["site_id"] == sid and a["status"] in ("ACTIVE", "AT_CAPACITY")
            for a in store.agreements.values()
        ):
            raise errors.invalid_state("site still has live bin agreements")
        if any(
            r["site_id"] == sid and r["status"] in ("SCHEDULED", "IN_PROGRESS")
            for r in store.routes.values()
        ):
            raise errors.invalid_state("site still has live routes")
        site["status"] = "RETIRED"
        touch(site)
        return success(serialize(site), 200)

