"""SupplyItem / SupplyRequest / Dispatch endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..constants import SUPPLY_CATEGORIES
from ..errors import ApiError
from ..services.calculations import compute_priority_score
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/supply-items",
        view_func=require_auth("SupplyManager")(with_lock(create_item)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply-items/<iid>",
        view_func=require_auth("SupplyManager", "CDCSupervisor")(with_lock(get_item)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/supply-requests",
        view_func=require_auth("HospitalReporter", "CDCTracer", "CDCSupervisor")(
            with_lock(create_request)
        ),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply-requests/<rid>",
        view_func=require_auth(
            "SupplyManager", "CDCSupervisor", "HospitalReporter", "CDCTracer"
        )(with_lock(get_request)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/supply-requests/<rid>/allocate",
        view_func=require_auth("SupplyManager")(with_lock(allocate_single)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply/allocate-batch",
        view_func=require_auth("SupplyManager")(with_lock(allocate_batch)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply-requests/<rid>/dispatch",
        view_func=require_auth("SupplyManager")(with_lock(dispatch_request)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/dispatches/<did>/deliver",
        view_func=require_auth("SupplyManager", "HospitalReporter")(with_lock(deliver_dispatch)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply-requests/<rid>/consume",
        view_func=require_auth("HospitalReporter", "CDCTracer")(with_lock(consume_request)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/supply-requests/<rid>/cancel",
        view_func=require_auth("SupplyManager")(with_lock(cancel_request)),
        methods=["POST"],
    )


def _find_item_by_sku(sku: str):
    store = get_store()
    for it in store.supply_items.values():
        if it.get("sku") == sku:
            return it
    return None


def create_item():
    body = get_json_body()
    store = get_store()
    sku = body.get("sku")
    category = body.get("category")
    reserve = body.get("reserve_quantity", 0)
    if not sku or not category:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    if category not in SUPPLY_CATEGORIES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"category must be one of {sorted(SUPPLY_CATEGORIES)}."
        )
    try:
        reserve_int = int(reserve)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "reserve_quantity must be integer.")
    if reserve_int < 0:
        raise ApiError("ERR_INVALID_INPUT", "reserve_quantity must be >= 0.")
    if _find_item_by_sku(sku):
        raise ApiError("ERR_INVALID_INPUT", f"sku {sku!r} already exists.")
    row = {
        **common_fields_create(),
        "sku": sku,
        "category": category,
        "reserve_quantity": reserve_int,
        "allocated_quantity": 0,
    }
    store.supply_items[row["id"]] = row
    return ok(row, status=201)


def get_item(iid: str):
    store = get_store()
    it = store.supply_items.get(iid)
    if not it:
        raise ApiError("ERR_NOT_FOUND", f"SupplyItem {iid} not found.")
    return ok(it)


def create_request():
    body = get_json_body()
    store = get_store()
    sku = body.get("sku")
    inst_id = body.get("requesting_institution_id")
    qty = body.get("requested_quantity")
    if not sku or not inst_id or qty is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    try:
        qty_int = int(qty)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "requested_quantity must be integer.")
    if qty_int <= 0:
        raise ApiError("ERR_INVALID_INPUT", "requested_quantity must be > 0.")
    item = _find_item_by_sku(sku)
    if not item:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"sku {sku} not found.")
    inst = store.institutions.get(inst_id)
    if not inst:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"requesting_institution_id {inst_id} not found.")
    priority = compute_priority_score(inst, item)
    row = {
        **common_fields_create(),
        "sku": sku,
        "sku_item_id": item["id"],
        "requesting_institution_id": inst_id,
        "requested_quantity": qty_int,
        "priority_score": priority,
        "allocated_quantity": 0,
        "dispatched_quantity": 0,
        "consumed_quantity": 0,
        "status": "PENDING",
    }
    store.supply_requests[row["id"]] = row
    return ok(row, status=201)


def get_request(rid: str):
    store = get_store()
    r = store.supply_requests.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", f"SupplyRequest {rid} not found.")
    return ok(r)


def _allocate_one(req: dict) -> int:
    store = get_store()
    item = store.supply_items.get(req.get("sku_item_id")) or _find_item_by_sku(req.get("sku"))
    if not item:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "Linked supply item not found.")
    available = int(item.get("reserve_quantity", 0)) - int(item.get("allocated_quantity", 0))
    if available <= 0:
        raise ApiError("ERR_SUPPLY_INSUFFICIENT", "No reserve available for allocation.")
    requested = int(req.get("requested_quantity", 0))
    grant = min(requested, available)
    if grant <= 0:
        raise ApiError("ERR_SUPPLY_INSUFFICIENT", "No reserve available for allocation.")
    req["allocated_quantity"] = grant
    req["status"] = "ALLOCATED"
    bump_version(req)
    item["allocated_quantity"] = int(item.get("allocated_quantity", 0)) + grant
    bump_version(item)
    return grant


def allocate_single(rid: str):
    body = get_json_body()
    store = get_store()
    req = store.supply_requests.get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", f"SupplyRequest {rid} not found.")
    check_version(req, body)
    if req.get("status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Request must be PENDING to allocate.")
    _allocate_one(req)
    return ok(req)


def allocate_batch():
    body = get_json_body()
    store = get_store()
    sku = body.get("sku")
    if not sku:
        raise ApiError("ERR_INVALID_INPUT", "Missing sku.")
    item = _find_item_by_sku(sku)
    if not item:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"sku {sku} not found.")

    # Eligible PENDING requests, sorted by priority_score DESC, created_at ASC, id ASC
    eligible = [
        r for r in store.supply_requests.values()
        if r.get("sku") == sku and r.get("status") == "PENDING"
    ]
    eligible.sort(
        key=lambda r: (-int(r.get("priority_score", 0)), r.get("created_at", ""), r.get("id", ""))
    )

    allocations: list[dict] = []
    for req in eligible:
        available = int(item.get("reserve_quantity", 0)) - int(item.get("allocated_quantity", 0))
        if available <= 0:
            break
        requested = int(req.get("requested_quantity", 0))
        grant = min(requested, available)
        if grant <= 0:
            break
        req["allocated_quantity"] = grant
        req["status"] = "ALLOCATED"
        bump_version(req)
        item["allocated_quantity"] = int(item.get("allocated_quantity", 0)) + grant
        bump_version(item)
        allocations.append({"request_id": req["id"], "allocated_quantity": grant})
    return ok({"sku": sku, "allocations": allocations})


def dispatch_request(rid: str):
    body = get_json_body()
    store = get_store()
    req = store.supply_requests.get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", f"SupplyRequest {rid} not found.")
    check_version(req, body)
    if req.get("status") != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Request must be ALLOCATED to dispatch.")
    quantity = body.get("quantity")
    if quantity is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing quantity.")
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "quantity must be integer.")
    if qty != int(req.get("allocated_quantity", 0)):
        raise ApiError(
            "ERR_DISPATCH_QUANTITY_MISMATCH",
            "Dispatch quantity must equal allocated_quantity.",
        )

    item = store.supply_items.get(req.get("sku_item_id")) or _find_item_by_sku(req.get("sku"))
    if not item:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "Linked supply item not found.")

    base = common_fields_append_only()
    from ..clock import now_iso_ms
    dispatch = {
        **base,
        "request_id": rid,
        "quantity": qty,
        "dispatched_at": now_iso_ms(),
        "delivered_at": None,
        "status": "IN_TRANSIT",
    }
    store.dispatches[dispatch["id"]] = dispatch

    item["reserve_quantity"] = int(item.get("reserve_quantity", 0)) - qty
    item["allocated_quantity"] = int(item.get("allocated_quantity", 0)) - qty
    bump_version(item)

    req["dispatched_quantity"] = qty
    req["status"] = "DISPATCHED"
    bump_version(req)

    return ok(dispatch, status=201)


def deliver_dispatch(did: str):
    body = get_json_body()
    store = get_store()
    d = store.dispatches.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"Dispatch {did} not found.")
    if d.get("status") != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Dispatch must be IN_TRANSIT to deliver.")
    from ..clock import now_iso_ms
    d["delivered_at"] = now_iso_ms()
    d["status"] = "DELIVERED"
    # Roll parent request DISPATCHED -> DELIVERED
    req = store.supply_requests.get(d.get("request_id"))
    if req and req.get("status") == "DISPATCHED":
        req["status"] = "DELIVERED"
        bump_version(req)
    return ok(d)


def consume_request(rid: str):
    body = get_json_body()
    store = get_store()
    req = store.supply_requests.get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", f"SupplyRequest {rid} not found.")
    check_version(req, body)
    if req.get("status") != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "Request must be DELIVERED to consume.")
    consumed = body.get("consumed_quantity")
    if consumed is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing consumed_quantity.")
    try:
        c_int = int(consumed)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "consumed_quantity must be integer.")
    if c_int < 0:
        raise ApiError("ERR_INVALID_INPUT", "consumed_quantity must be >= 0.")
    if c_int > int(req.get("dispatched_quantity", 0)):
        raise ApiError(
            "ERR_CONSUMPTION_EXCEEDS_DISPATCH",
            "consumed_quantity cannot exceed dispatched_quantity.",
        )
    req["consumed_quantity"] = c_int
    req["status"] = "CONSUMED"
    bump_version(req)
    return ok(req)


def cancel_request(rid: str):
    body = get_json_body()
    store = get_store()
    req = store.supply_requests.get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", f"SupplyRequest {rid} not found.")
    check_version(req, body)
    prev = req.get("status")
    if prev not in ("PENDING", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", "Request must be PENDING or ALLOCATED to cancel.")
    if prev == "ALLOCATED":
        item = store.supply_items.get(req.get("sku_item_id")) or _find_item_by_sku(req.get("sku"))
        if item:
            item["allocated_quantity"] = max(
                0, int(item.get("allocated_quantity", 0)) - int(req.get("allocated_quantity", 0))
            )
            bump_version(item)
    req["status"] = "CANCELLED"
    bump_version(req)
    return ok(req)
