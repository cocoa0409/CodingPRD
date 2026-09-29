"""PRD 3.7 - plate ordering, the plate budget and compensating cancellation."""
from flask import Blueprint, request

import calc
from core import db, new_row, now_iso, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    load,
    need_bool,
    need_int,
    need_nonempty,
    ok,
    paginate,
    query_bool,
    raw_body,
)
from serialize import committed_plate_cost, plate_order_json

bp = Blueprint("plates", __name__)


@bp.route("/plate-orders", methods=["POST"])
def create_plate_order():
    auth(["PackagingCoordinator"])
    raw = raw_body()
    for collection, key in (
        ("versions", "artwork_version_id"),
        ("printers", "printer_id"),
        ("proofs", "printer_proof_id"),
    ):
        reference = raw.get(key)
        if isinstance(reference, str) and reference:
            load(collection, reference)

    body = body_fields(
        ["artwork_version_id", "printer_id", "printer_proof_id", "plate_set_count"], ["expedite"]
    )
    need_nonempty(body, "artwork_version_id")
    need_nonempty(body, "printer_id")
    need_nonempty(body, "printer_proof_id")
    plate_set_count = need_int(body, "plate_set_count", 1, 24)
    expedite = need_bool(body, "expedite", default=False)

    version = load("versions", body["artwork_version_id"])
    printer = load("printers", body["printer_id"])
    proof = load("proofs", body["printer_proof_id"])
    asset = db.assets[version["artwork_asset_id"]]

    if version["state"] not in ("APPROVED", "RELEASED_TO_PRINT"):
        fail(
            "ERR_VERSION_STATE_INVALID",
            "plates may only be ordered for an APPROVED or RELEASED_TO_PRINT version",
        )
    if proof["artwork_version_id"] != version["id"] or proof["printer_id"] != printer["id"]:
        fail(
            "ERR_PROOF_VERSION_MISMATCH",
            "the named proof does not belong to this version and vendor",
        )
    if printer["certification_status"] != "CERTIFIED":
        fail("ERR_PRINTER_ON_PROBATION", "a vendor on PROBATION may not accept plate orders")
    if proof["proof_state"] != "PROOF_APPROVED":
        fail("ERR_PROOF_NOT_APPROVED", "the authorising proof is not PROOF_APPROVED")

    subtotal, setup, expedite_fee, cost = calc.plate_cost(plate_set_count, expedite)
    committed = committed_plate_cost(asset["id"])
    if committed + cost > asset["plate_budget_cents"]:
        fail(
            "ERR_PLATE_BUDGET_EXCEEDED",
            "the order would take committed plate cost past the asset budget",
        )

    row = new_row(
        "plate_orders",
        {
            "artwork_version_id": version["id"],
            "printer_id": printer["id"],
            "printer_proof_id": proof["id"],
            "plate_set_count": plate_set_count,
            "expedite": expedite,
            "plate_subtotal_cents": subtotal,
            "setup_fee_cents": setup,
            "expedite_fee_cents": expedite_fee,
            "cost_cents": cost,
            "status": "ORDERED",
            "auto_cancelled": False,
            "cancel_reason": None,
            "cancelled_at": None,
        },
    )
    touch(asset)
    return created(plate_order_json(row))


@bp.route("/plate-orders/<order_id>", methods=["GET"])
def get_plate_order(order_id):
    auth(ALL_ROLES)
    return ok(plate_order_json(load("plate_orders", order_id)))


@bp.route("/plate-orders", methods=["GET"])
def list_plate_orders():
    auth(ALL_ROLES)
    version_id = filter_exists("versions", "artwork_version_id")
    printer_id = filter_exists("printers", "printer_id")
    proof_id = filter_exists("proofs", "printer_proof_id")
    items = rows("plate_orders")
    if version_id:
        items = [o for o in items if o["artwork_version_id"] == version_id]
    if printer_id:
        items = [o for o in items if o["printer_id"] == printer_id]
    if proof_id:
        items = [o for o in items if o["printer_proof_id"] == proof_id]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    auto_cancelled = query_bool("auto_cancelled")
    if auto_cancelled is not None:
        items = [o for o in items if o["auto_cancelled"] == auto_cancelled]
    items = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    return paginate(items, plate_order_json)


@bp.route("/plate-orders/<order_id>/cancel", methods=["POST"])
def cancel_plate_order(order_id):
    auth(["PackagingCoordinator"])
    order = load("plate_orders", order_id)
    body = body_fields(["cancel_reason"])
    reason = body.get("cancel_reason")
    if not isinstance(reason, str) or not reason.strip():
        invalid("cancel_reason is required and must be non-empty")

    if order["status"] != "ORDERED":
        fail("ERR_PLATE_ORDER_NOT_CANCELLABLE", "the order is already CANCELLED")

    # Compensating action: cost_cents is never rewritten (PRD 2.9).
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    order["cancelled_at"] = now_iso()
    order["auto_cancelled"] = False
    touch(order)

    version = db.versions[order["artwork_version_id"]]
    asset = db.assets[version["artwork_asset_id"]]
    touch(asset)
    return ok(plate_order_json(order))
