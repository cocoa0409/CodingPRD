"""Harvest batches: OCC-guarded scheduling, completion, cancellation."""
from datetime import time as dtime
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
from auth import require_roles
from db import common_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_BATCH_YIELD_EXCEEDS_AVAILABLE,
                    ERR_FIELD_NOT_HARVESTABLE, ERR_FIELD_QUALITY_GATE,
                    ERR_HARVEST_WINDOW, ERR_INVALID_ENUM, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_STALE_FIELD_VERSION)
from serialize import pub_batch
from util import (D, as_int, as_str, body, hours_between, ok, ok_list, paged,
                  pagination, parse_date, parse_dt, require, sort_created)

bp = Blueprint("harvest", __name__)

GRADES = {"PREMIUM", "STANDARD", "ECONOMY"}


def _get_batch(bid):
    batch = db.store.harvest_batches.get(bid)
    if batch is None:
        raise err(ERR_NOT_FOUND, f"harvest batch {bid} not found")
    return batch


@bp.route("/harvest-batches", methods=["POST"])
def create_batch():
    require_roles("HarvestSupervisor")
    payload = body()
    # tier 3: body FK existence
    field_id = as_str(require(payload, "field_id"), "field_id")
    field = db.store.fields.get(field_id)
    if field is None:
        raise err(ERR_NOT_FOUND, f"field {field_id} not found")
    # tier 4: request shape
    pallet_count = as_int(require(payload, "pallet_count"), "pallet_count", minimum=1)
    shortfall_slabs = as_int(require(payload, "shortfall_slabs"), "shortfall_slabs", minimum=0)
    shortfall_rolls = as_int(require(payload, "shortfall_rolls"), "shortfall_rolls", minimum=0)
    scheduled_date = parse_date(require(payload, "scheduled_date"), "scheduled_date")
    if "expected_field_version" not in payload or payload["expected_field_version"] is None:
        raise err(ERR_INVALID_REQUEST, "expected_field_version is required")
    expected_version = as_int(payload["expected_field_version"], "expected_field_version")
    if scheduled_date < db.today():
        raise err(ERR_INVALID_REQUEST, "scheduled_date must not be before the current date")
    # tier 5: enum membership
    grade = require(payload, "grade")
    if grade not in GRADES:
        raise err(ERR_INVALID_ENUM, f"grade must be one of {sorted(GRADES)}")
    cfg = calc.config_or_defaults(calc.current_config())
    full_sqft, yield_sqft = calc.line_yield_sqft(cfg, pallet_count, grade,
                                                 shortfall_slabs, shortfall_rolls)
    if yield_sqft <= 0:
        raise err(ERR_INVALID_REQUEST, "yield_sqft must be positive")
    # tier 6: terminal guard
    if field["status"] == "ARCHIVED":
        raise err(ERR_ALREADY_TERMINAL, f"field {field_id} is archived")
    # tier 8: optimistic concurrency on Field.version
    if expected_version != field["version"]:
        raise err(ERR_STALE_FIELD_VERSION,
                  f"expected_field_version {expected_version} != current {field['version']}")
    # tier 11: safety gates — maturity then agronomic quality
    _, maturity = calc.compute_maturity(field)
    if maturity not in ("READY", "MATURE"):
        raise err(ERR_FIELD_NOT_HARVESTABLE,
                  f"field maturity is {maturity}; harvest requires READY or MATURE")
    days_since_mow = hours_between(field["last_mowed_at"], db.now()) / Decimal("24")
    if not (field["mow_count"] >= 3
            and days_since_mow < Decimal("3")
            and Decimal("35") <= D(field["soil_moisture_pct"]) <= Decimal("55")
            and D(field["health_score"]) >= Decimal("70")):
        raise err(ERR_FIELD_QUALITY_GATE,
                  "quality gate failed: mow_count >= 3, last mow < 3 days, "
                  "35 <= moisture <= 55, health >= 70")
    # tier 12: availability net of pending reservations
    available = D(field["remaining_sqft"]) - calc.pending_reserved_sqft(field_id)
    if yield_sqft > available:
        raise err(ERR_BATCH_YIELD_EXCEEDS_AVAILABLE,
                  f"sellable_sqft {yield_sqft} exceeds available {available}")
    batch = common_fields()
    batch.update({
        "field_id": field_id,
        "variety_id": field["variety_id"],
        "grade": grade,
        "pallet_count": pallet_count,
        "shortfall_slabs": shortfall_slabs,
        "shortfall_rolls": shortfall_rolls,
        "full_sqft": full_sqft,
        "yield_sqft": yield_sqft,
        "sellable_sqft": yield_sqft,
        "scheduled_date": scheduled_date,
        "actual_harvest_start": None,
        "actual_harvest_end": None,
        "status": "PENDING",
        "order_id": None,
    })
    db.store.harvest_batches[batch["id"]] = batch
    # scheduling a batch is a field-side write watched by the OCC guard
    db.bump(field)
    return ok(pub_batch(batch), 201)


@bp.route("/harvest-batches", methods=["GET"])
def list_batches():
    require_roles("HarvestSupervisor", "FarmManager", "SalesRep")
    limit, offset = pagination()
    field_id = request.args.get("field_id")
    order_id = request.args.get("order_id")
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    items = sort_created(db.store.harvest_batches.values())
    if field_id is not None:
        items = [b for b in items if b["field_id"] == field_id]
    if order_id is not None:
        items = [b for b in items if b["order_id"] == order_id]
    if variety_id is not None:
        items = [b for b in items if b["variety_id"] == variety_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([pub_batch(b) for b in page], total, limit, offset)


@bp.route("/harvest-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles("HarvestSupervisor", "FarmManager")
    return ok(pub_batch(_get_batch(bid)), 200)


@bp.route("/harvest-batches/<bid>/complete", methods=["POST"])
def complete_batch(bid):
    require_roles("HarvestSupervisor")
    batch = _get_batch(bid)
    payload = body()
    # tier 4: shape
    start = parse_dt(require(payload, "actual_harvest_start"), "actual_harvest_start")
    end = parse_dt(require(payload, "actual_harvest_end"), "actual_harvest_end")
    # tier 6: terminal guard
    if batch["status"] in ("COMPLETE", "CANCELLED"):
        raise err(ERR_ALREADY_TERMINAL, f"harvest batch {bid} is {batch['status']}")
    # tier 7: from-state
    if batch["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, f"harvest batch {bid} is not PENDING")
    # tier 9: daylight harvest window (time-of-day bounds, end strictly after start)
    cfg = calc.config_or_defaults(calc.current_config())
    earliest = int(cfg["harvest_earliest_start_hour"])
    latest = int(cfg["harvest_latest_end_hour"])
    start_tod = start.hour * 3600 + start.minute * 60 + start.second + start.microsecond / 1e6
    end_tod = end.hour * 3600 + end.minute * 60 + end.second + end.microsecond / 1e6
    if start_tod < earliest * 3600 or end_tod > latest * 3600 or end <= start:
        raise err(ERR_HARVEST_WINDOW,
                  f"harvest must start at/after {earliest:02d}:00, end at/before "
                  f"{latest:02d}:00, and end strictly after start")
    batch["status"] = "COMPLETE"
    batch["actual_harvest_start"] = start
    batch["actual_harvest_end"] = end
    db.bump(batch)
    # only completion decrements real inventory
    field = db.store.fields.get(batch["field_id"])
    if field is not None:
        field["remaining_sqft"] = D(field["remaining_sqft"]) - D(batch["sellable_sqft"])
        db.bump(field)
    return ok(pub_batch(batch), 200)


@bp.route("/harvest-batches/<bid>/cancel", methods=["POST"])
def cancel_batch(bid):
    require_roles("HarvestSupervisor")
    batch = _get_batch(bid)
    if batch["status"] in ("COMPLETE", "CANCELLED"):
        raise err(ERR_ALREADY_TERMINAL, f"harvest batch {bid} is {batch['status']}")
    if batch["order_id"] is not None:
        raise err(ERR_INVALID_STATE,
                  "linked batches are released only via order cancel/revert cascades")
    batch["status"] = "CANCELLED"
    db.bump(batch)
    return ok(pub_batch(batch), 200)
