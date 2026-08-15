"""Supply inventory + distribution record endpoints."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, optional_field, as_string, as_int, as_enum,
    logical_now, format_iso,
)
from services.core import (
    make_record, touch, paginate, sort_by_created,
    serialize_inventory, serialize_distribution, inventory_issued_count,
    get_event_or_404, get_inventory_or_404, get_signup_or_404, get_distribution_or_404,
)

bp = Blueprint("supplies", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")

KINDS = {"CREDENTIAL", "SUPPLY_ITEM"}


# ---------------- SupplyInventory ----------------

@bp.post("/volunteer-ops/supply-inventories")
def create_inventory():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    item_code = as_string(require_field(body, "item_code"), "item_code")
    description = optional_field(body, "description", None)
    if description is not None:
        description = as_string(description, "description")
    quantity_total = as_int(require_field(body, "quantity_total"), "quantity_total")
    if quantity_total < 0:
        raise errors.invalid_request("quantity_total must be >= 0.")
    for inv in store.supply_inventories.values():
        if inv["event_id"] == event_id and inv["item_code"] == item_code:
            raise errors.invalid_request("item_code must be unique within the event.")
    rec = make_record({
        "event_id": event_id,
        "item_code": item_code,
        "description": description,
        "quantity_total": quantity_total,
    })
    store.supply_inventories[rec["id"]] = rec
    return success_object(serialize_inventory(rec), status=201)


@bp.get("/volunteer-ops/supply-inventories")
def list_inventories():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    items = [i for i in store.supply_inventories.values()
             if event_id is None or i["event_id"] == event_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_inventory(i) for i in page], limit, offset, total)


@bp.get("/volunteer-ops/supply-inventories/<inventoryId>")
def get_inventory(inventoryId):
    require_roles(*ANY)
    inv = get_inventory_or_404(inventoryId)
    return success_object(serialize_inventory(inv))


# ---------------- DistributionRecord ----------------

@bp.post("/volunteer-ops/distribution-records")
def create_distribution():
    require_roles("VolunteerCoordinator")
    body = get_body()
    signup_id = as_string(require_field(body, "signup_id"), "signup_id")
    su = get_signup_or_404(signup_id)
    kind = as_enum(require_field(body, "kind"), "kind", KINDS)
    inventory_id = optional_field(body, "inventory_id", None)

    # state gate: signup must be CHECKED_IN
    if su["status"] != "CHECKED_IN":
        raise errors.signup_not_checked_in()

    inv = None
    # kind vs inventory_id constraint (priority 9)
    if kind == "CREDENTIAL":
        if inventory_id is not None:
            raise errors.invalid_request("inventory_id must be null when kind is CREDENTIAL.")
        # one ISSUED credential per signup
        for dr in store.distribution_records.values():
            if (
                dr["signup_id"] == su["id"]
                and dr["kind"] == "CREDENTIAL"
                and dr["status"] == "ISSUED"
            ):
                raise errors.credential_already_issued()
    else:  # SUPPLY_ITEM
        if inventory_id is None:
            raise errors.invalid_request("inventory_id is required when kind is SUPPLY_ITEM.")
        inventory_id = as_string(inventory_id, "inventory_id")
        inv = get_inventory_or_404(inventory_id)
        # stock check (priority 12)
        if inventory_issued_count(inv["id"]) >= inv["quantity_total"]:
            raise errors.out_of_stock()

    now = logical_now()
    rec = make_record({
        "event_id": su["event_id"],
        "signup_id": su["id"],
        "inventory_id": inventory_id if kind == "SUPPLY_ITEM" else None,
        "kind": kind,
        "status": "ISSUED",
        "issued_at": format_iso(now),
        "returned_at": None,
    })
    store.distribution_records[rec["id"]] = rec
    if inv is not None:
        touch(inv)
    return success_object(serialize_distribution(rec), status=201)


@bp.get("/volunteer-ops/distribution-records")
def list_distributions():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    signup_id = request.args.get("signup_id")
    inventory_id = request.args.get("inventory_id")
    kind = request.args.get("kind")
    items = [
        d for d in store.distribution_records.values()
        if (event_id is None or d["event_id"] == event_id)
        and (signup_id is None or d["signup_id"] == signup_id)
        and (inventory_id is None or d.get("inventory_id") == inventory_id)
        and (kind is None or d["kind"] == kind)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_distribution(d) for d in page], limit, offset, total)


@bp.get("/volunteer-ops/distribution-records/<distributionId>")
def get_distribution(distributionId):
    require_roles(*ANY)
    dr = get_distribution_or_404(distributionId)
    return success_object(serialize_distribution(dr))


@bp.post("/volunteer-ops/distribution-records/<distributionId>/return")
def return_distribution(distributionId):
    require_roles("VolunteerCoordinator")
    dr = get_distribution_or_404(distributionId)
    if dr["status"] != "ISSUED" or dr["kind"] != "SUPPLY_ITEM":
        raise errors.distribution_invalid_state()
    now = logical_now()
    dr["status"] = "RETURNED"
    dr["returned_at"] = format_iso(now)
    touch(dr)
    if dr.get("inventory_id"):
        inv = store.supply_inventories.get(dr["inventory_id"])
        if inv is not None:
            touch(inv)
    return success_object(serialize_distribution(dr))


@bp.post("/volunteer-ops/distribution-records/<distributionId>/revoke")
def revoke_distribution(distributionId):
    require_roles("VolunteerCoordinator")
    dr = get_distribution_or_404(distributionId)
    if dr["status"] != "ISSUED":
        raise errors.distribution_invalid_state()
    dr["status"] = "REVOKED"
    touch(dr)
    if dr["kind"] == "SUPPLY_ITEM" and dr.get("inventory_id"):
        inv = store.supply_inventories.get(dr["inventory_id"])
        if inv is not None:
            touch(inv)
    return success_object(serialize_distribution(dr))
