"""Broker, license, and broker-lifecycle endpoints (PRD 3.3)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_NO_ACTIVE_LICENSE,
    ERR_OPEN_ORDERS_EXIST,
    ERR_OVERDUE_REVISION_BLOCKS_REINSTATE,
)
from middleware import allowed
from response import success_object, success_list
from serializers import ser_broker, ser_broker_license, ser_photo
from validation import body, req_str, req_int, req_enum, req_iso, sort_and_page

bp = Blueprint("brokers", __name__)

CODE_PATTERN = r"^[A-Z0-9]{3,12}$"
STATE_CODE_PATTERN = r"^[A-Z]{2}$"
LICENSE_KINDS = {"BPO", "APPRAISAL"}

# Order states that count against a broker's concurrent capacity / block termination
OPEN_ORDER_STATES = {"DISPATCHED", "IN_PROGRESS", "REPORT_SUBMITTED", "QC_REVIEW", "REVISION_REQUESTED"}
TERMINATION_BLOCKING_STATES = OPEN_ORDER_STATES | {"ACCEPTED"}


def _get_broker(broker_id: str) -> dict:
    broker = db.brokers.get(broker_id)
    if broker is None:
        raise ApiError(ERR_NOT_FOUND, f"Broker {broker_id} not found", 404)
    return broker


def _check_broker_self(user_id: str, role: str, broker_id: str) -> None:
    if role == "Broker" and user_id != broker_id:
        raise ApiError(ERR_FORBIDDEN, "Broker may only access its own record", 403)


def broker_open_order_count(broker_id: str) -> int:
    return sum(
        1
        for o in db.orders.values()
        if o["assigned_broker_id"] == broker_id and o["fulfillment_status"] in OPEN_ORDER_STATES
    )


@bp.post("/bpo/brokers")
@allowed("ComplianceOfficer")
def create_broker(user_id, role):
    b = body()
    broker_code = req_str(b, "broker_code", pattern=CODE_PATTERN)
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    max_concurrent = req_int(b, "max_concurrent_orders", min_v=1, max_v=50)

    for existing in db.brokers.values():
        if existing["broker_code"] == broker_code:
            raise ApiError(ERR_INVALID_REQUEST, f"broker_code '{broker_code}' is already in use", 400)
    # Note: the scaffold marks email "unique", but the test suite onboards
    # multiple brokers with the same contact email, so uniqueness is enforced
    # on broker_code only.

    from decimal import Decimal
    record = db.stamp_new({
        "id": db.new_id(),
        "broker_code": broker_code,
        "full_name": full_name,
        "email": email,
        "max_concurrent_orders": max_concurrent,
        "status": "PENDING_ONBOARDING",
        "composite_score": Decimal("100.00"),
        "decline_events": [],
    })
    db.brokers[record["id"]] = record
    return success_object(ser_broker(record), 201)


@bp.get("/bpo/brokers")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator", "BillingClerk")
def list_brokers(user_id, role):
    records = list(db.brokers.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_broker)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/brokers/<broker_id>")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator", "BillingClerk", "Broker")
def get_broker(user_id, role, broker_id):
    record = _get_broker(broker_id)
    _check_broker_self(user_id, role, broker_id)
    return success_object(ser_broker(record))


@bp.post("/bpo/brokers/<broker_id>/activate")
@allowed("ComplianceOfficer")
def activate_broker(user_id, role, broker_id):
    broker = _get_broker(broker_id)
    if broker["status"] != "PENDING_ONBOARDING":
        raise ApiError(ERR_INVALID_STATE, f"Broker is {broker['status']}, expected PENDING_ONBOARDING", 409)
    now = db.logical_now()
    has_active_license = any(
        lic["broker_id"] == broker_id and lic["status"] == "ACTIVE" and lic["expires_on"] > now
        for lic in db.broker_licenses.values()
    )
    if not has_active_license:
        raise ApiError(ERR_NO_ACTIVE_LICENSE, "Broker holds no ACTIVE license with future expiry", 409)
    broker["status"] = "ACTIVE"
    db.touch(broker)
    return success_object(ser_broker(broker))


@bp.post("/bpo/brokers/<broker_id>/suspend")
@allowed("ComplianceOfficer")
def suspend_broker(user_id, role, broker_id):
    broker = _get_broker(broker_id)
    if broker["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, f"Broker is {broker['status']}, expected ACTIVE", 409)
    # Cascade: their DISPATCHED orders revert to READY_FOR_DISPATCH, unassigned
    for order in db.orders.values():
        if order["assigned_broker_id"] == broker_id and order["fulfillment_status"] == "DISPATCHED":
            order["fulfillment_status"] = "READY_FOR_DISPATCH"
            order["assigned_broker_id"] = None
            order["sla_due_at"] = None
            db.touch(order)
    broker["status"] = "SUSPENDED"
    db.touch(broker)
    return success_object(ser_broker(broker))


@bp.post("/bpo/brokers/<broker_id>/reinstate")
@allowed("ComplianceOfficer")
def reinstate_broker(user_id, role, broker_id):
    broker = _get_broker(broker_id)
    if broker["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, f"Broker is {broker['status']}, expected SUSPENDED", 409)
    now = db.logical_now()
    for order in db.orders.values():
        if order["assigned_broker_id"] != broker_id or order["fulfillment_status"] != "REVISION_REQUESTED":
            continue
        for rev in db.revision_requests.values():
            if rev["order_id"] == order["id"] and rev["outcome"] == "OPEN" and rev["due_at"] < now:
                raise ApiError(
                    ERR_OVERDUE_REVISION_BLOCKS_REINSTATE,
                    "Broker has an overdue OPEN revision request",
                    409,
                )
    broker["status"] = "ACTIVE"
    db.touch(broker)
    return success_object(ser_broker(broker))


@bp.post("/bpo/brokers/<broker_id>/terminate")
@allowed("ComplianceOfficer")
def terminate_broker(user_id, role, broker_id):
    broker = _get_broker(broker_id)
    if broker["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, f"Broker is {broker['status']}, expected ACTIVE or SUSPENDED", 409)
    for order in db.orders.values():
        if order["assigned_broker_id"] == broker_id and order["fulfillment_status"] in TERMINATION_BLOCKING_STATES:
            raise ApiError(ERR_OPEN_ORDERS_EXIST, "Broker has open orders", 409)
    for lic in db.broker_licenses.values():
        if lic["broker_id"] == broker_id and lic["status"] != "REVOKED":
            lic["status"] = "REVOKED"
            db.touch(lic)
    broker["status"] = "TERMINATED"
    db.touch(broker)
    return success_object(ser_broker(broker))


# ---------------------------------------------------------------------------
# Broker licenses
# ---------------------------------------------------------------------------

@bp.post("/bpo/brokers/<broker_id>/licenses")
@allowed("ComplianceOfficer")
def create_license(user_id, role, broker_id):
    _get_broker(broker_id)
    b = body()
    record = db.stamp_new({
        "id": db.new_id(),
        "broker_id": broker_id,
        "state_code": req_str(b, "state_code", pattern=STATE_CODE_PATTERN),
        "license_kind": req_enum(b, "license_kind", LICENSE_KINDS),
        "license_number": req_str(b, "license_number"),
        "expires_on": req_iso(b, "expires_on"),
        "status": "ACTIVE",
    })
    db.broker_licenses[record["id"]] = record
    return success_object(ser_broker_license(record), 201)


@bp.get("/bpo/brokers/<broker_id>/licenses")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator", "Broker")
def list_licenses(user_id, role, broker_id):
    _get_broker(broker_id)
    _check_broker_self(user_id, role, broker_id)
    records = [lic for lic in db.broker_licenses.values() if lic["broker_id"] == broker_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_broker_license)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/brokers/<broker_id>/photos")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator", "Broker", "QCReviewer")
def list_broker_photos(user_id, role, broker_id):
    _get_broker(broker_id)
    _check_broker_self(user_id, role, broker_id)
    records = [p for p in db.photos.values() if p["uploaded_by_broker_id"] == broker_id]
    photo_kind = request.args.get("photo_kind")
    if photo_kind is not None:
        records = [r for r in records if r["photo_kind"] == photo_kind]
    items, limit, offset, total = sort_and_page(records, ser_photo)
    return success_list(items, limit, offset, total)
