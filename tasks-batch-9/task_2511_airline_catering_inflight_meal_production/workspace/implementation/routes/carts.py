"""Equipment carts: registration, loading, voiding, build sign-off, sealing."""

from flask import Blueprint

import clock
import db
import validate
from errors import fail
from middleware import LOAD_MASTER, actor, authenticate
from routes.helpers import created, guard_scope, listing, one, resolve, simple_list
from services import calc, cascade

bp = Blueprint("carts", __name__)

CART_TYPES = ["STD_HALF", "STD_FULL", "OVEN_RACK", "DRY_BOX"]
STORAGE_CLASSES = ["CHILL", "HOT", "DRY"]
BUILD_STATUSES = ["EMPTY", "BUILDING", "BUILT", "LOADED", "RETURNED"]
SEAL_STATUSES = ["UNSEALED", "SEALED", "BROKEN", "RESEALED"]
FLIGHT_TERMINAL = ("DEPARTED", "RECONCILED", "CANCELLED")


def cart_or_404(cart_id):
    return resolve("carts", cart_id, "ERR_CART_NOT_FOUND")


# ---------------------------------------------------------------------------
# registration


@bp.route("/carts", methods=["POST"])
def create_cart():
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("flight_id", {"type": "id", "required": True}),
        ("cart_code", {"type": "string", "required": True, "non_empty": True}),
        ("cart_type", {"type": "enum", "required": True, "values": CART_TYPES}),
        ("storage_class", {"type": "enum", "required": True, "values": STORAGE_CLASSES}),
        ("capacity_units", {"type": "int", "required": True, "min": 1, "max": 400}),
        ("galley_position", {"type": "string", "nullable": True}),
    ])
    flight = resolve("flights", data["flight_id"], "ERR_FLIGHT_NOT_FOUND")
    if flight["status"] in FLIGHT_TERMINAL:
        fail("ERR_INVALID_FLIGHT_STATE")

    row = dict(data)
    row.setdefault("galley_position", None)
    row["build_status"] = "EMPTY"
    row["seal_status"] = "UNSEALED"
    row["seal_number"] = None
    row["seal_count"] = 0
    row["sealed_by_user_id"] = None
    return created("carts", db.insert("carts", row))


# ---------------------------------------------------------------------------
# loading


@bp.route("/carts/<cart_id>/items", methods=["POST"])
def load_item(cart_id):
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("production_batch_id", {"type": "id", "required": True}),
        ("qty_units", {"type": "int", "required": True, "min": 1}),
    ])
    cart = cart_or_404(cart_id)
    batch = resolve("production_batches", data["production_batch_id"])

    # band 70 — cart build axis, then the batch release gate
    if cart["build_status"] not in ("EMPTY", "BUILDING"):
        fail("ERR_INVALID_CART_STATE")
    if batch["production_status"] != "RELEASED":
        fail("ERR_BATCH_NOT_RELEASED")

    # band 80 — food safety
    if clock.now() >= batch["_deadline"]:
        fail("ERR_RELEASE_DEADLINE_PASSED")

    # band 90 — cross-row coherence
    if batch["store_zone"] != cart["storage_class"]:
        fail("ERR_STORAGE_CLASS_MISMATCH")
    if batch["flight_id"] != cart["flight_id"]:
        fail("ERR_CART_FLIGHT_MISMATCH")

    # band 100 — cart capacity
    qty = data["qty_units"]
    if calc.cart_loaded_units(cart["id"]) + qty > cart["capacity_units"]:
        fail("ERR_CART_CAPACITY_EXCEEDED")

    # band 120 — the contractual money ceiling
    spec = calc.spec_of_batch(batch)
    flight = db.get("flights", cart["flight_id"])
    airline = calc.airline_of_flight(flight) if flight else None
    if spec is not None and flight is not None and airline is not None:
        projected = calc.cost_per_pax_cents(flight, extra=(spec, qty))
        if projected > airline["cost_cap_per_pax_cents"]:
            fail("ERR_COST_CAP_EXCEEDED")

    item = db.insert("cart_items", {
        "cart_id": cart["id"],
        "production_batch_id": batch["id"],
        "qty_units": qty,
        "meal_code": spec["meal_code"] if spec else None,
        "status": "ACTIVE",
        "voided_at": None,
    })
    if cart["build_status"] == "EMPTY":
        cart["build_status"] = "BUILDING"
    db.touch(cart)
    # PRD 3.6: the load also recomputes the flight's units_loaded, unit_balance
    # and cost_per_pax_cents, so by PRD 2.5/2.9 the flight row is mutated too.
    if flight is not None:
        db.touch(flight)
    return created("cart_items", item)


@bp.route("/carts/<cart_id>/items/<item_id>", methods=["DELETE"])
def void_item(cart_id, item_id):
    authenticate(LOAD_MASTER)
    validate.body([])
    cart = cart_or_404(cart_id)
    item = resolve("cart_items", item_id)
    if item["cart_id"] != cart["id"]:
        fail("ERR_RESOURCE_NOT_FOUND")
    if item["status"] != "ACTIVE":
        fail("ERR_INVALID_RESOURCE_STATE")
    cascade.void_item(item)
    return one("cart_items", item)


# ---------------------------------------------------------------------------
# build sign-off


@bp.route("/carts/<cart_id>/build-completion", methods=["POST"])
def complete_build(cart_id):
    authenticate(LOAD_MASTER)
    validate.body([])
    cart = cart_or_404(cart_id)
    if cart["build_status"] != "BUILDING" or calc.cart_loaded_units(cart["id"]) < 1:
        fail("ERR_INVALID_CART_STATE")
    cart["build_status"] = "BUILT"
    db.touch(cart)
    return one("carts", cart)


# ---------------------------------------------------------------------------
# sealing


def _seal_taken(seal_number, cart_id):
    for other in db.rows("carts"):
        if other["id"] != cart_id and other["seal_number"] == seal_number:
            return True
    for waste in db.rows("waste_manifests"):
        if waste["status"] != "REJECTED" and waste["seal_number"] == seal_number:
            return True
    return False


@bp.route("/carts/<cart_id>/seals", methods=["POST"])
def fit_seal(cart_id):
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("expected_cart_version", {"type": "int", "required": True, "min": 0}),
        ("seal_number", {"type": "string", "required": True, "non_empty": True}),
    ])
    cart = cart_or_404(cart_id)

    # band 65 — optimistic concurrency
    if data["expected_cart_version"] != cart["version"]:
        fail("ERR_STALE_CART_VERSION")

    # band 70 — build axis, then the released-batch gate
    if cart["build_status"] != "BUILT":
        fail("ERR_INVALID_CART_STATE")
    if cart["seal_status"] not in ("UNSEALED", "SEALED", "BROKEN"):
        fail("ERR_INVALID_CART_STATE")
    for item in calc.cart_active_items(cart["id"]):
        batch = db.get("production_batches", item["production_batch_id"])
        if batch is None or batch["production_status"] != "RELEASED":
            fail("ERR_BATCH_NOT_RELEASED")

    # band 100 — seal uniqueness across carts and live waste manifests
    if _seal_taken(data["seal_number"], cart["id"]):
        fail("ERR_SEAL_NUMBER_DUPLICATE")

    superseding = cart["seal_status"] in ("SEALED", "RESEALED")
    if cart["seal_status"] == "UNSEALED":
        cart["seal_status"] = "SEALED"
        cart["seal_count"] = 1
    else:
        cart["seal_status"] = "RESEALED"
        cart["seal_count"] = cart["seal_count"] + 1
    cart["seal_number"] = data["seal_number"]
    cart["sealed_by_user_id"] = actor().user_id
    db.touch(cart)

    if superseding:
        cascade.amend_for_cart(cart)
    return one("carts", cart)


# ---------------------------------------------------------------------------
# reads


@bp.route("/carts", methods=["GET"])
def list_carts():
    authenticate()
    return simple_list("carts", {
        "flight_id": {"type": "string"},
        "storage_class": {"type": "enum", "values": STORAGE_CLASSES},
        "cart_type": {"type": "enum", "values": CART_TYPES},
        "build_status": {"type": "enum", "values": BUILD_STATUSES},
        "seal_status": {"type": "enum", "values": SEAL_STATUSES},
    })


@bp.route("/carts/<cart_id>", methods=["GET"])
def read_cart(cart_id):
    authenticate()
    cart = cart_or_404(cart_id)
    guard_scope("carts", cart)
    return one("carts", cart)


@bp.route("/cart-items", methods=["GET"])
def list_items():
    authenticate()
    filters, limit, offset = validate.pagination({
        "cart_id": {"type": "string"},
        "production_batch_id": {"type": "string"},
        "status": {"type": "enum", "values": ["ACTIVE", "VOID"]},
    })
    rows = db.rows("cart_items")
    if "status" not in filters:
        rows = [row for row in rows if row["status"] == "ACTIVE"]
    return listing("cart_items", rows, filters, limit, offset)


@bp.route("/cart-items/<item_id>", methods=["GET"])
def read_item(item_id):
    authenticate()
    return one("cart_items", resolve("cart_items", item_id))
