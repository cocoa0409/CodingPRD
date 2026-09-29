"""Loading manifests: issue (and re-issue) plus reads."""

from flask import Blueprint

import clock
import db
import validate
from errors import fail
from middleware import LOAD_MASTER, actor, authenticate
from routes.helpers import guard_scope, one, resolve, simple_list
from services import calc
from timeutil import fmt_ms

bp = Blueprint("manifests", __name__)

MANIFEST_STATUSES = ["DRAFT", "ISSUED", "AMENDED", "VOID"]


@bp.route("/loading-manifests/<manifest_id>/issue", methods=["POST"])
def issue_manifest(manifest_id):
    authenticate(LOAD_MASTER)
    validate.body([])
    manifest = resolve("loading_manifests", manifest_id)

    # band 70 — manifest, then flight, then the carts of the flight
    if manifest["status"] not in ("DRAFT", "AMENDED"):
        fail("ERR_INVALID_RESOURCE_STATE")
    flight = db.get("flights", manifest["flight_id"])
    if flight is None or flight["status"] != "PLANNED":
        fail("ERR_INVALID_FLIGHT_STATE")

    carts = calc.flight_carts(flight["id"])
    for cart in carts:
        if calc.cart_loaded_units(cart["id"]) < 1:
            continue
        if cart["build_status"] != "BUILT":
            fail("ERR_INVALID_CART_STATE")
        if cart["seal_status"] not in ("SEALED", "RESEALED"):
            fail("ERR_INVALID_CART_STATE")

    snapshot_carts = [cart for cart in carts if cart["build_status"] == "BUILT"]

    # band 85 — segregation of duties
    acting = actor().user_id
    for cart in snapshot_carts:
        if cart["sealed_by_user_id"] == acting:
            fail("ERR_SEGREGATION_OF_DUTIES")

    snapshot = []
    total = 0
    for cart in snapshot_carts:
        units = calc.cart_loaded_units(cart["id"])
        snapshot.append({
            "cart_id": cart["id"],
            "seal_number": cart["seal_number"],
            "cart_version": cart["version"],
            "units": units,
        })
        total += units

    manifest["cart_seal_snapshot"] = snapshot
    manifest["total_units"] = total
    manifest["status"] = "ISSUED"
    manifest["issued_at"] = fmt_ms(clock.now())
    manifest["issued_by_user_id"] = acting
    db.touch(manifest)

    flight["status"] = "LOADED"
    db.touch(flight)
    return one("loading_manifests", manifest)


@bp.route("/loading-manifests", methods=["GET"])
def list_manifests():
    authenticate()
    return simple_list("loading_manifests", {
        "flight_id": {"type": "string"},
        "status": {"type": "enum", "values": MANIFEST_STATUSES},
    })


@bp.route("/loading-manifests/<manifest_id>", methods=["GET"])
def read_manifest(manifest_id):
    authenticate()
    manifest = resolve("loading_manifests", manifest_id)
    guard_scope("loading_manifests", manifest)
    return one("loading_manifests", manifest)
