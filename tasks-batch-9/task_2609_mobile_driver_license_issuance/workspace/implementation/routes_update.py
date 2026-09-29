"""Update-propagation orders and their per-credential deliveries."""

from flask import Blueprint

import calc
import cascade
import derive
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db, now, sort_rows, touch

bp = Blueprint("update", __name__, url_prefix="/mdl")

ORDER_REASONS = ("ADDRESS_CHANGE", "RENEWAL", "RESTRICTION_CHANGE", "REVOCATION")
ORDER_STATUSES = ("OPEN", "PARTIALLY_DELIVERED", "COMPLETED", "FAILED_CLOSED")
DELIVERY_STATUSES = ("PENDING", "DELIVERED", "FAILED", "SUPERSEDED")
FAILURE_CODES = ("DEVICE_UNREACHABLE", "ATTESTATION_STALE", "USER_DECLINED")


@endpoint(bp, "/update-orders/<order_id>", ["GET"], ["SystemAdmin", "Holder"])
def read_update_order(order_id):
    order = lookup.update_order(order_id)
    return ok(serialize.dump(order))


@endpoint(bp, "/update-orders", ["GET"], ["SystemAdmin", "Holder"])
def list_update_orders():
    limit, offset = v.pagination()
    holder_id = v.q_str("holder_id")
    reason = v.q_enum("reason", ORDER_REASONS)
    status = v.q_enum("status", ORDER_STATUSES)

    rows = list(db.update_orders.values())
    if holder_id is not None:
        rows = [o for o in rows if o["holder_id"] == holder_id]
    if reason is not None:
        rows = [o for o in rows if o["reason"] == reason]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/update-orders/<order_id>/deliveries", ["GET"],
          ["SystemAdmin", "Holder"])
def list_order_deliveries(order_id):
    limit, offset = v.pagination()
    status = v.q_enum("status", DELIVERY_STATUSES)
    order = lookup.update_order(order_id)
    rows = derive.deliveries_of_order(order["id"])
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/update-deliveries/<delivery_id>/deliver", ["POST"], ["SystemAdmin"])
def deliver_update(delivery_id):
    body = v.body()
    receipt_token = v.req_str(body, "device_receipt_token")

    delivery = lookup.update_delivery(delivery_id)

    # step 8: the delivery must still be awaiting a result
    if delivery["status"] != "PENDING":
        raise ApiError("ERR_DELIVERY_NOT_PENDING")

    credential = db.credentials.get(delivery["credential_id"])
    device = db.devices.get(credential["device_id"]) if credential else None
    order = db.update_orders.get(delivery["update_order_id"])
    holder = db.holders.get(credential["holder_id"]) if credential else None

    # step 17: the handset must be bound to receive a push
    if device is None or device["state"] != "BOUND":
        raise ApiError("ERR_DEVICE_NOT_BOUND")

    # step 7: the credential must still be a live carrier
    if credential["lifecycle_state"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")

    # step 29: the near-real-time revocation pointer must read valid and fresh
    projection = calc.revocation_status(credential)
    if projection["status"] != "VALID" or not projection["is_fresh"]:
        raise ApiError("ERR_REVOCATION_STATUS_STALE")

    outstanding_before = derive.pending_update_count(credential["id"])

    delivery["status"] = "DELIVERED"
    delivery["attempt_count"] += 1
    delivery["delivered_at"] = now()
    delivery["device_receipt_token"] = receipt_token

    if outstanding_before == 1:
        credential["sync_state"] = "IN_SYNC"
        credential["doc_version"] += 1
        credential["address_version_synced"] = order["target_address_version"]
        credential["restriction_codes"] = list(holder.get("restriction_codes") or [])
        touch(credential)

    delivery["resulting_doc_version"] = credential["doc_version"]
    touch(delivery)

    calc.rollup(order)
    return ok(serialize.dump(delivery))


@endpoint(bp, "/update-deliveries/<delivery_id>/fail", ["POST"], ["SystemAdmin"])
def fail_update(delivery_id):
    body = v.body()
    failure_code = v.req_enum(body, "failure_code", FAILURE_CODES)

    delivery = lookup.update_delivery(delivery_id)

    # step 8: the delivery must still be awaiting a result
    if delivery["status"] != "PENDING":
        raise ApiError("ERR_DELIVERY_NOT_PENDING")

    credential = db.credentials.get(delivery["credential_id"])
    order = db.update_orders.get(delivery["update_order_id"])

    failures_before = derive.failed_delivery_count(credential["id"])

    delivery["status"] = "FAILED"
    delivery["attempt_count"] += 1
    delivery["failure_code"] = failure_code
    touch(delivery)

    if failures_before == 0:
        # first failure: only the payload is behind, the credential still works
        credential["sync_state"] = "UPDATE_FAILED"
        touch(credential)
    else:
        # second failure: the one cross-axis coupling of the model fires
        credential["sync_state"] = "STALE"
        touch(credential)
        if credential["lifecycle_state"] == "ACTIVE":
            cascade.suspend_credential(
                credential, "UPDATE_FAILED", "SUSPENDED", "UPDATE_FAILED"
            )

    calc.rollup(order)
    return ok(serialize.dump(delivery))
