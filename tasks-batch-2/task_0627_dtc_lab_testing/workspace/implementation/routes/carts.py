"""Carts and cart lines (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str,
    require_enum, paginate,
)
from services.carts import recompute_cart

bp = Blueprint("carts", __name__)

FUND_SOURCES = {"CARD", "HSA_FSA"}
REPEAT_LOOKBACK_DAYS = 365


def _owns(role, user_id, patient_id):
    return not (role == "Patient" and user_id != patient_id)


@bp.route("/catalog/carts", methods=["POST"])
def create_cart():
    user_id, role = require_role(["Patient"])
    body = get_json()
    patient_id = require_str(body, "patient_id")
    fund_source = body.get("fund_source", "CARD")
    require_enum(fund_source, FUND_SOURCES, "fund_source")
    # Ownership: a Patient must create a cart for itself.
    if not _owns(role, user_id, patient_id):
        raise err("ERR_NOT_RESOURCE_OWNER", "Cannot open a cart for another patient")
    require_found("patients", patient_id)

    rec = db.new_record({
        "patient_id": patient_id,
        "fund_source": fund_source,
        "line_count": 0,
        "subtotal_cents": 0,
        "estimated_total_cents": 0,
        "estimated_hsa_applied_cents": 0,
        "estimated_patient_due_cents": 0,
        "status": "OPEN",
    })
    db.insert("carts", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/carts", methods=["GET"])
def list_carts():
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("carts"))
    patient_id = request.args.get("patient_id")
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if role == "Patient":
        rows = [r for r in rows if r["patient_id"] == user_id]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/carts/<rid>", methods=["GET"])
def get_cart(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rec = require_found("carts", rid)
    if not _owns(role, user_id, rec["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    # Recompute estimated totals on read (PRD §3.3) without bumping version.
    recompute_cart(rec)
    return success(serialize(rec))


@bp.route("/catalog/carts/<rid>", methods=["PATCH"])
def update_cart(rid):
    user_id, role = require_role(["Patient"])
    rec = require_found("carts", rid)
    if not _owns(role, user_id, rec["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    body = get_json()
    fund_source = body.get("fund_source")
    require_enum(fund_source, FUND_SOURCES, "fund_source")
    rec["fund_source"] = fund_source
    recompute_cart(rec)
    db.touch(rec)
    return success(serialize(rec))


# ---------------------------------------------------------------------------
# Cart lines
# ---------------------------------------------------------------------------
def _repeat_eligible(patient_id, test_code, cart_created_at):
    """True when a RELEASED result for this test_code falls within the 365-day
    window immediately before the cart was created (PRD §3.2)."""
    cart_dt = clock.parse_iso(cart_created_at)
    window_start = cart_dt.timestamp() - REPEAT_LOOKBACK_DAYS * 86400
    for r in db.all_rows("lab_results"):
        if r["patient_id"] != patient_id or r["test_code"] != test_code:
            continue
        if r["status"] != "RELEASED":
            continue
        released_dt = clock.parse_iso(r["updated_at"])
        rel_ts = released_dt.timestamp()
        if window_start <= rel_ts <= cart_dt.timestamp():
            return True
    return False


@bp.route("/catalog/cart-lines", methods=["POST"])
def add_cart_line():
    user_id, role = require_role(["Patient"])
    body = get_json()
    cart_id = require_str(body, "cart_id")
    offering_id = require_str(body, "test_offering_id")
    cart = require_found("carts", cart_id)
    offering = require_found("test_offerings", offering_id)
    if not _owns(role, user_id, cart["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")

    # Offering must be ACTIVE and cart OPEN.
    if offering["status"] != "ACTIVE" or cart["status"] != "OPEN":
        raise err("ERR_OFFERING_NOT_ADDABLE", "Offering archived or cart not OPEN")

    repeat = _repeat_eligible(cart["patient_id"], offering["test_code"], cart["created_at"])
    line = db.new_record({
        "cart_id": cart_id,
        "test_offering_id": offering_id,
        "test_code": offering["test_code"],
        "unit_list_price_cents": offering["list_price_cents"],
        "repeat_discount_applied": repeat,
    })
    db.insert("cart_lines", line)

    recompute_cart(cart)
    db.touch(cart)
    return success(serialize(line), status=201)


@bp.route("/catalog/cart-lines", methods=["GET"])
def list_cart_lines():
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("cart_lines"))
    cart_id = request.args.get("cart_id")
    offering_id = request.args.get("test_offering_id")
    if cart_id:
        rows = [r for r in rows if r["cart_id"] == cart_id]
    if offering_id:
        rows = [r for r in rows if r["test_offering_id"] == offering_id]
    if role == "Patient":
        owned = {c["id"] for c in db.all_rows("carts") if c["patient_id"] == user_id}
        rows = [r for r in rows if r["cart_id"] in owned]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/cart-lines/<rid>", methods=["GET"])
def get_cart_line(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    line = require_found("cart_lines", rid)
    cart = db.get("carts", line["cart_id"])
    if role == "Patient" and cart and user_id != cart["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(line))


@bp.route("/catalog/cart-lines/<rid>", methods=["DELETE"])
def delete_cart_line(rid):
    user_id, role = require_role(["Patient"])
    line = require_found("cart_lines", rid)
    cart = require_found("carts", line["cart_id"])
    if not _owns(role, user_id, cart["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    if cart["status"] != "OPEN":
        raise err("ERR_OFFERING_NOT_ADDABLE", "Cart not OPEN")
    del db.store["cart_lines"][rid]
    recompute_cart(cart)
    db.touch(cart)
    return success(serialize(cart))
