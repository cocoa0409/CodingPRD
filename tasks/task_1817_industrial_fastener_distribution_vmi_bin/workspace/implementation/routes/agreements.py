"""BinAgreement endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, touch
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_enum,
    pagination_params, paginate,
)
from response import success, success_list
from services import recompute_posture, sizing_recommendation

bp = Blueprint("agreements", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver", "WarehouseOperator"]
PRICING_MODES = ("UNIT_PRICE", "COST_PER_BIN")
SIZING_METHODS = ("TRAILING", "PROJECTED")


def serialize(agr):
    return {
        "id": agr["id"],
        "site_id": agr["site_id"],
        "part_id": agr["part_id"],
        "bin_location": agr["bin_location"],
        "pricing_mode": agr["pricing_mode"],
        "flat_bin_price_cents": agr["flat_bin_price_cents"],
        "min_qty": agr["min_qty"],
        "max_qty": agr["max_qty"],
        "on_hand_qty": agr["on_hand_qty"],
        "open_order_qty": agr["open_order_qty"],
        "status": agr["status"],
        "compliance_flag": agr["compliance_flag"],
        "created_at": agr["created_at"],
        "updated_at": agr["updated_at"],
        "version": agr["version"],
    }


def _check_sizing_bounds(min_qty, max_qty):
    """Stage 12: min_qty >= 0, max_qty >= 1, min_qty < max_qty."""
    if min_qty < 0 or max_qty < 1 or min_qty >= max_qty:
        raise errors.quantity_bounds(
            "min_qty must be >= 0 and strictly below max_qty; max_qty must be >= 1"
        )


@bp.post("/vmi/bin-agreements")
def create_agreement():
    role = authenticate()
    body = json_body()
    site_id = as_str(need(body, "site_id"), "site_id")
    part_id = as_str(need(body, "part_id"), "part_id")
    bin_location = as_str(need(body, "bin_location"), "bin_location")
    pricing_mode = as_enum(need(body, "pricing_mode"), "pricing_mode", PRICING_MODES)
    # flat_bin_price_cents present exactly when pricing_mode == COST_PER_BIN
    if pricing_mode == "COST_PER_BIN":
        flat_bin_price_cents = as_int(
            need(body, "flat_bin_price_cents"), "flat_bin_price_cents"
        )
        if flat_bin_price_cents < 0:
            raise errors.invalid_request("flat_bin_price_cents must be >= 0")
    else:
        if "flat_bin_price_cents" in body:
            raise errors.invalid_request(
                "flat_bin_price_cents must be omitted under UNIT_PRICE pricing"
            )
        flat_bin_price_cents = 0
    min_qty = as_int(need(body, "min_qty"), "min_qty")
    max_qty = as_int(need(body, "max_qty"), "max_qty")
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        # existence, left-to-right: site before part
        site = store.sites.get(site_id)
        if site is None:
            raise errors.not_found("site not found")
        part = store.parts.get(part_id)
        if part is None:
            raise errors.not_found("part not found")
        # live-parent gate
        if site["status"] == "RETIRED":
            raise errors.retired("site is RETIRED")
        if part["status"] == "OBSOLETE":
            raise errors.retired("part is OBSOLETE")
        # uniqueness of the live (site, part, bin_location) triple
        if any(
            a["site_id"] == site_id
            and a["part_id"] == part_id
            and a["bin_location"] == bin_location
            and a["status"] != "RETIRED"
            for a in store.agreements.values()
        ):
            raise errors.duplicate(
                "a live agreement already exists for this (site, part, bin_location)"
            )
        _check_sizing_bounds(min_qty, max_qty)
        ts = now_iso()
        agr = {
            "id": new_id(),
            "site_id": site_id,
            "part_id": part_id,
            "bin_location": bin_location,
            "pricing_mode": pricing_mode,
            "flat_bin_price_cents": flat_bin_price_cents,
            "min_qty": min_qty,
            "max_qty": max_qty,
            "on_hand_qty": 0,
            "open_order_qty": 0,
            "status": "ACTIVE",
            "compliance_flag": "CLEAR",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.agreements[agr["id"]] = agr
        return success(serialize(agr), 201)


@bp.get("/vmi/bin-agreements/<aid>")
def get_agreement(aid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    agr = store.agreements.get(aid)
    if agr is None:
        raise errors.not_found("bin agreement not found")
    return success(serialize(agr), 200)


@bp.get("/vmi/bin-agreements")
def list_agreements():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    site_id = request.args.get("site_id")
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = sorted(store.agreements.values(), key=lambda a: a["_seq"])
    if site_id is not None:
        items = [a for a in items if a["site_id"] == site_id]
    if part_id is not None:
        items = [a for a in items if a["part_id"] == part_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(a) for a in page], total, limit, offset)


@bp.put("/vmi/bin-agreements/<aid>")
def update_agreement(aid):
    role = authenticate()
    body = json_body()
    expected_version = as_int(
        need(body, "expected_bin_agreement_version"),
        "expected_bin_agreement_version",
    )
    updates = {}
    if "min_qty" in body:
        updates["min_qty"] = as_int(body["min_qty"], "min_qty")
    if "max_qty" in body:
        updates["max_qty"] = as_int(body["max_qty"], "max_qty")
    if "bin_location" in body:
        updates["bin_location"] = as_str(body["bin_location"], "bin_location")
    if "pricing_mode" in body:
        updates["pricing_mode"] = as_enum(
            body["pricing_mode"], "pricing_mode", PRICING_MODES
        )
    if "flat_bin_price_cents" in body:
        updates["flat_bin_price_cents"] = as_int(
            body["flat_bin_price_cents"], "flat_bin_price_cents"
        )
        if updates["flat_bin_price_cents"] < 0:
            raise errors.invalid_request("flat_bin_price_cents must be >= 0")
    # body-only interplay between pricing_mode and flat_bin_price_cents
    if "pricing_mode" in updates:
        if updates["pricing_mode"] == "COST_PER_BIN":
            if "flat_bin_price_cents" not in updates:
                raise errors.invalid_request(
                    "flat_bin_price_cents required when setting COST_PER_BIN"
                )
        else:  # switching to UNIT_PRICE
            if "flat_bin_price_cents" in updates:
                raise errors.invalid_request(
                    "flat_bin_price_cents must be omitted under UNIT_PRICE pricing"
                )
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        agr = store.agreements.get(aid)
        if agr is None:
            raise errors.not_found("bin agreement not found")
        if agr["status"] == "RETIRED":
            raise errors.invalid_state("cannot update a RETIRED bin agreement")
        # entity-dependent interplay: flat price only under COST_PER_BIN
        if (
            "pricing_mode" not in updates
            and "flat_bin_price_cents" in updates
            and agr["pricing_mode"] != "COST_PER_BIN"
        ):
            raise errors.invalid_request(
                "flat_bin_price_cents carries no effect under UNIT_PRICE pricing"
            )
        # stage 12: sizing bounds on the merged values
        new_min = updates.get("min_qty", agr["min_qty"])
        new_max = updates.get("max_qty", agr["max_qty"])
        _check_sizing_bounds(new_min, new_max)
        # stage 15: OCC staleness (last stage of the pipeline)
        if agr["version"] != expected_version:
            raise errors.stale_version(
                "expected_bin_agreement_version does not match the current version"
            )
        agr.update(updates)
        if agr["pricing_mode"] == "UNIT_PRICE":
            agr["flat_bin_price_cents"] = 0
        touch(agr)
        # posture recompute against the new max_qty
        recompute_posture(agr)
        return success(serialize(agr), 200)


@bp.post("/vmi/bin-agreements/<aid>/retire")
def retire_agreement(aid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        agr = store.agreements.get(aid)
        if agr is None:
            raise errors.not_found("bin agreement not found")
        if agr["status"] not in ("ACTIVE", "AT_CAPACITY"):
            raise errors.invalid_state("bin agreement is not in a retirable state")
        if any(
            o["bin_agreement_id"] == aid
            and o["status"] in ("DRAFT", "CONFIRMED", "ON_HOLD", "IN_TRANSIT")
            for o in store.orders.values()
        ):
            raise errors.invalid_state("bin agreement still has open orders")
        agr["status"] = "RETIRED"
        touch(agr)
        return success(serialize(agr), 200)


@bp.post("/vmi/bin-agreements/<aid>/substitute")
def substitute_agreement(aid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        agr = store.agreements.get(aid)
        if agr is None:
            raise errors.not_found("bin agreement not found")
        if agr["status"] == "RETIRED":
            raise errors.invalid_state("cannot substitute on a RETIRED bin agreement")
        candidates = [
            x for x in store.xrefs.values()
            if x["from_part_id"] == agr["part_id"]
            and x["is_active"]
            and store.parts.get(x["to_part_id"]) is not None
            and store.parts[x["to_part_id"]]["status"] == "ACTIVE"
        ]
        candidates.sort(key=lambda x: (x["priority_rank"], x["_seq"]))
        if not candidates:
            raise errors.no_substitute(
                "no active cross-reference leads to an ACTIVE part"
            )
        agr["part_id"] = candidates[0]["to_part_id"]
        touch(agr)
        return success(serialize(agr), 200)


@bp.get("/vmi/bin-agreements/<aid>/sizing-recommendation")
def get_sizing_recommendation(aid):
    role = authenticate()
    method = request.args.get("method", "TRAILING")
    if method not in SIZING_METHODS:
        raise errors.invalid_request("method must be TRAILING or PROJECTED")
    require_roles(role, ["DistributorAdmin", "RouteDriver"])
    agr = store.agreements.get(aid)
    if agr is None:
        raise errors.not_found("bin agreement not found")
    recommended_min, recommended_max = sizing_recommendation(agr, method)
    return success(
        {
            "recommended_min": recommended_min,
            "recommended_max": recommended_max,
            "method": method,
        },
        200,
    )
