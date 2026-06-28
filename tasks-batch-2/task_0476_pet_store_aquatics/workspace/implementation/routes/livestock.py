"""LivestockBatch + livestock-sale endpoints (PRD §3.3, §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_create, touch
from clock import clock, parse_iso
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_enum, as_datetime, round_half_up,
    TIER_DISCOUNT,
)
from services.derive import compute_loyalty_tier
from services.loyalty import whole_dollar_points, accrue
from services.serialize import batch_out

bp = Blueprint("livestock", __name__)

READ_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk", "Customer"]
ANIMAL_CLASSES = {"FISH", "REPTILE", "SMALL_ANIMAL"}
MORTALITY_CONDEMN_RATE = 0.5


@bp.route("/livestock-batches", methods=["POST"])
def intake_batch():
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    body = get_body()
    store_id = as_str(require_present(body, "store_id"), "store_id")
    lookup("stores", store_id)
    species = as_str(require_present(body, "species"), "species")
    animal_class = as_enum(require_present(body, "animal_class"), "animal_class", ANIMAL_CLASSES)
    head_count = as_int(require_present(body, "head_count"), "head_count")
    if head_count <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "head_count must be > 0.")
    unit_price = as_int(require_present(body, "unit_price_cents"), "unit_price_cents")
    if unit_price <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "unit_price_cents must be > 0.")
    intake_at = require_present(body, "intake_at")
    as_datetime(intake_at, "intake_at")
    quarantine_days = as_int(require_present(body, "quarantine_days"), "quarantine_days")
    if quarantine_days <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "quarantine_days must be > 0.")

    record = {
        "store_id": store_id,
        "species": species,
        "animal_class": animal_class,
        "head_count": head_count,
        "unit_price_cents": unit_price,
        "intake_at": intake_at,
        "quarantine_days": quarantine_days,
        "mortality_count": 0,
        "health_state": "QUARANTINE",
        "sale_state": "HELD",
    }
    stamp_create(record)
    db.livestock_batches[record["id"]] = record
    return object_response(batch_out(record), 201)


@bp.route("/livestock-batches", methods=["GET"])
def list_batches():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.livestock_batches.values())
    store_id = request.args.get("store_id")
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    page, total = paginate(records, limit, offset)
    return array_response([batch_out(r) for r in page], limit, offset, total)


@bp.route("/livestock-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("livestock_batches", batch_id)
    return object_response(batch_out(record))


@bp.route("/livestock-batches/<batch_id>/clear-quarantine", methods=["POST"])
def clear_quarantine(batch_id):
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    batch = lookup("livestock_batches", batch_id)

    if batch["health_state"] == "QUARANTINE":
        # Quarantine window must have elapsed (closed lower bound).
        threshold = parse_iso(batch["intake_at"]) + timedelta(days=batch["quarantine_days"])
        if clock.now() < threshold:
            raise err("ERR_QUARANTINE_NOT_ELAPSED")
        if batch["mortality_count"] != 0:
            raise err("ERR_QUARANTINE_MORTALITY_BLOCK")
        batch["health_state"] = "HEALTHY"
        touch(batch)
        return object_response(batch_out(batch))

    if batch["health_state"] == "UNDER_TREATMENT":
        # Recovery path: mortality ratio strictly below condemn rate.
        ratio = batch["mortality_count"] / batch["head_count"]
        if ratio >= MORTALITY_CONDEMN_RATE:
            raise err("ERR_QUARANTINE_MORTALITY_BLOCK")
        batch["health_state"] = "HEALTHY"
        touch(batch)
        return object_response(batch_out(batch))

    raise err("ERR_BATCH_HEALTH_STATE_INVALID")


@bp.route("/livestock-batches/<batch_id>/record-mortality", methods=["POST"])
def record_mortality(batch_id):
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    batch = lookup("livestock_batches", batch_id)
    body = get_body()
    deaths = as_int(require_present(body, "deaths"), "deaths")
    if deaths <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "deaths must be > 0.")

    if batch["health_state"] not in ("QUARANTINE", "HEALTHY", "UNDER_TREATMENT"):
        raise err("ERR_BATCH_HEALTH_STATE_INVALID")

    batch["mortality_count"] += deaths
    ratio = batch["mortality_count"] / batch["head_count"]
    if ratio >= MORTALITY_CONDEMN_RATE:
        batch["health_state"] = "CONDEMNED"
        batch["sale_state"] = "SOLD_OUT"
    else:
        batch["health_state"] = "UNDER_TREATMENT"
    touch(batch)
    return object_response(batch_out(batch))


@bp.route("/livestock-batches/<batch_id>/list-on-floor", methods=["POST"])
def list_on_floor(batch_id):
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    batch = lookup("livestock_batches", batch_id)
    if batch["sale_state"] != "HELD":
        raise err("ERR_BATCH_SALE_STATE_INVALID")
    if batch["health_state"] != "HEALTHY":
        raise err("ERR_BATCH_NOT_HEALTHY")
    batch["sale_state"] = "ON_FLOOR"
    touch(batch)
    return object_response(batch_out(batch))


@bp.route("/livestock-batches/<batch_id>/condemn", methods=["POST"])
def condemn(batch_id):
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    batch = lookup("livestock_batches", batch_id)
    if batch["health_state"] != "UNDER_TREATMENT":
        raise err("ERR_BATCH_HEALTH_STATE_INVALID")
    batch["health_state"] = "CONDEMNED"
    batch["sale_state"] = "SOLD_OUT"
    touch(batch)
    return object_response(batch_out(batch))


@bp.route("/livestock-sales", methods=["POST"])
def livestock_sale():
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    body = get_body()
    batch_id = as_str(require_present(body, "batch_id"), "batch_id")
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    batch = lookup("livestock_batches", batch_id)
    customer = lookup("customers", customer_id)

    if batch["sale_state"] != "ON_FLOOR":
        raise err("ERR_BATCH_SALE_STATE_INVALID")
    if batch["health_state"] != "HEALTHY":
        raise err("ERR_BATCH_NOT_HEALTHY")

    # livestock_sale_total (PRD §3.4): round once.
    live_head = batch["head_count"] - batch["mortality_count"]
    tier = compute_loyalty_tier(customer["lifetime_spend_cents"])
    disc = TIER_DISCOUNT[tier]
    net_cents = round_half_up(live_head * batch["unit_price_cents"] * (1 - disc))
    earned = whole_dollar_points(net_cents)
    accrue(customer, net_cents, earned)
    touch(customer)

    batch["sale_state"] = "SOLD_OUT"
    touch(batch)
    return object_response(batch_out(batch), 201)
