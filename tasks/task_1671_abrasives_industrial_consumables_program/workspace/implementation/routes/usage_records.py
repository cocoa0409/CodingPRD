"""Usage record endpoints (PRD 3.4): VMI consumption audits. Append-only events."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_LOT_NOT_AVAILABLE, ERR_LOT_QTY_EXCEEDED,
    ERR_MACHINE_NOT_ACTIVE, ERR_NO_COVERING_STANDARD, ERR_SPEED_RATING_EXCEEDED,
    ERR_GUARD_REQUIRED, ERR_USAGE_DATE_IN_FUTURE,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import (
    compute_usage_metrics, covering_standard, recompute_consumption_flag,
    update_needs_review,
)
from services.core import new_record, serialize, touch
from util import CLOCK, parse_date
from validate import (
    get_body, req_date, req_int, req_str, require_fk, require_path_resource,
)

bp = Blueprint("usage_records", __name__)


def safety_gates(product: dict, machine: dict):
    """Priority 7, speed before guard (PRD 3.2)."""
    if product["max_operating_speed_rpm"] < machine["spindle_max_rpm"]:
        raise_error(
            ERR_SPEED_RATING_EXCEEDED,
            "product max_operating_speed_rpm is below the machine spindle_max_rpm",
        )
    if product["product_form"] == "BONDED" and machine["guard_type"] == "NONE":
        raise_error(ERR_GUARD_REQUIRED, "BONDED product requires a FIXED or ADJUSTABLE guard")


@bp.post("/api/usage-records")
def create_usage_record():
    authorized(["AccountManager"])
    # Priority 3: request shape.
    body = get_body()
    machine_id = req_str(body, "machine_id")
    product_id = req_str(body, "product_id")
    lot_id = req_str(body, "lot_id")
    usage_date = req_date(body, "usage_date")
    qty_used = req_int(body, "qty_used", min_value=1)
    parts_produced = req_int(body, "parts_produced", min_value=1)
    # Priority 4: body FK existence in canonical order (machine, product, lot).
    machine = require_fk("machines", machine_id, "machine")
    product = require_fk("products", product_id, "product")
    lot = require_fk("lots", lot_id, "lot")
    # A supplied lot must belong to the referenced product (mismatch is 400, not 404).
    if lot["product_id"] != product_id:
        raise_error(ERR_INVALID_REQUEST, "lot does not belong to the referenced product")
    # Priority 6: cross-entity states — machine ACTIVE, then lot AVAILABLE.
    if machine["status"] != "ACTIVE":
        raise_error(ERR_MACHINE_NOT_ACTIVE, "machine is not ACTIVE")
    if lot["status"] != "AVAILABLE":
        raise_error(ERR_LOT_NOT_AVAILABLE, "lot is not AVAILABLE")
    # Priority 7: safety gates (speed, then guard).
    safety_gates(product, machine)
    # Priority 8: covering ACTIVE standard for (machine, product) at usage_date.
    usage_d = parse_date(usage_date)
    standard = covering_standard(machine_id, product_id, usage_d)
    if standard is None:
        raise_error(ERR_NO_COVERING_STANDARD, "no ACTIVE standard window covers usage_date")
    # Priority 9: usage_date must not be after the current logical-clock date.
    if usage_d > CLOCK.today():
        raise_error(ERR_USAGE_DATE_IN_FUTURE, "usage_date is after the current logical-clock date")
    # Priority 10: qty_used must not exceed the lot's on-hand quantity (== allowed).
    if qty_used > lot["qty_on_hand"]:
        raise_error(ERR_LOT_QTY_EXCEEDED, "qty_used exceeds lot qty_on_hand")

    # Effects: decrement the lot (DEPLETED at exactly 0).
    lot["qty_on_hand"] -= qty_used
    if lot["qty_on_hand"] == 0:
        lot["status"] = "DEPLETED"
    touch(lot)

    actual, variance, band = compute_usage_metrics(qty_used, parts_produced, standard)
    rec = new_record("usage_records", {
        "machine_id": machine_id,
        "product_id": product_id,
        "lot_id": lot_id,
        "usage_date": usage_date,
        "qty_used": qty_used,
        "parts_produced": parts_produced,
        "actual_qty_per_part": actual,
        "variance_pct": variance,
        "variance_band": band,
    }, common_fields=False)  # append-only event: id + created_at only

    # Rolling-window surveillance on the covering standard, then the machine flag.
    if update_needs_review(standard):
        touch(standard)
    if recompute_consumption_flag(machine):
        touch(machine)
    return success_object(serialize(rec), status=201)


@bp.get("/api/usage-records/<rid>")
def get_usage_record(rid):
    return get_one("usage_records", rid, "usage record")


@bp.get("/api/usage-records")
def list_usage_records():
    return list_response("usage_records", {
        "machine_id": arg("machine_id"),
        "product_id": arg("product_id"),
        "lot_id": arg("lot_id"),
    })
