"""Customer endpoints."""
from flask import Blueprint, request

from db import CUSTOMER_TYPES, stamp_new, store, touch
from errors import (
    ERR_CUSTOMER_HAS_OPEN_ITEMS,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION,
    ApiError,
    bad_request,
)
from middleware import authenticate, body, f_datetime, f_enum, f_str, f_str_opt, f_version, sorted_page
from response import ok, ok_list
from serializers import serialize_customer
from services.audit import main_event

bp = Blueprint("customers", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]
CLOSE_BLOCKING_CTR_STATUSES = ("DRAFT", "VALIDATED", "FILED", "AMENDMENT_REQUIRED")
CLOSE_BLOCKING_ALERT_STATUSES = ("OPEN", "UNDER_REVIEW")


def get_customer_or_404(customer_id):
    c = store.customers.get(customer_id)
    if c is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer not found", 404)
    return c


@bp.post("/customers")
def create_customer():
    authenticate(["BranchManager"])
    b = body()
    legal_name = f_str(b, "legal_name")
    tin = f_str_opt(b, "tin")
    customer_type = f_enum(b, "customer_type", CUSTOMER_TYPES)
    opened_raw, _opened_dt = f_datetime(b, "account_opened_date")
    customer = {
        "legal_name": legal_name,
        "tin": tin,
        "customer_type": customer_type,
        "account_opened_date": opened_raw,
        "status": "ACTIVE",
        "structuring_referral_count": 0,
        "active_exemption_id": None,
    }
    stamp_new(customer)
    store.customers[customer["id"]] = customer
    main_event("POST /customers", "Customer", customer["id"], None, serialize_customer(customer))
    return ok(serialize_customer(customer), status=201)


@bp.get("/customers")
def list_customers():
    authenticate(ALL_ROLES)
    customer_type = request.args.get("customer_type")
    status = request.args.get("status")
    items = list(store.customers.values())
    if customer_type is not None:
        items = [c for c in items if c["customer_type"] == customer_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_customer(c) for c in page], limit, offset, total)


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    authenticate(ALL_ROLES)
    return ok(serialize_customer(get_customer_or_404(customer_id)))


@bp.patch("/customers/<customer_id>")
def patch_customer(customer_id):
    authenticate(["BranchManager"])
    b = body()
    legal_name = b.get("legal_name")
    if legal_name is not None and not isinstance(legal_name, str):
        raise bad_request("Field 'legal_name' must be a string")
    tin = b.get("tin")
    if tin is not None and not isinstance(tin, str):
        raise bad_request("Field 'tin' must be a string or null")
    expected = f_version(b, "expected_customer_version")
    customer = get_customer_or_404(customer_id)
    if expected != customer["version"]:
        raise ApiError(ERR_STALE_VERSION, "Customer version mismatch", 412)
    before = serialize_customer(customer)
    if legal_name is not None:
        customer["legal_name"] = legal_name
    if "tin" in b:
        customer["tin"] = tin
    touch(customer)
    main_event(
        "PATCH /customers/{id}", "Customer", customer["id"], before,
        serialize_customer(customer),
    )
    return ok(serialize_customer(customer))


@bp.post("/customers/<customer_id>/suspend")
def suspend_customer(customer_id):
    authenticate(["BranchManager"])
    customer = get_customer_or_404(customer_id)
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Customer is not ACTIVE", 409)
    before = serialize_customer(customer)
    customer["status"] = "SUSPENDED"
    touch(customer)
    main_event(
        "POST /customers/{id}/suspend", "Customer", customer["id"], before,
        serialize_customer(customer),
    )
    return ok(serialize_customer(customer))


@bp.post("/customers/<customer_id>/reactivate")
def reactivate_customer(customer_id):
    authenticate(["BranchManager"])
    customer = get_customer_or_404(customer_id)
    if customer["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Customer is not SUSPENDED", 409)
    before = serialize_customer(customer)
    customer["status"] = "ACTIVE"
    touch(customer)
    main_event(
        "POST /customers/{id}/reactivate", "Customer", customer["id"], before,
        serialize_customer(customer),
    )
    return ok(serialize_customer(customer))


@bp.post("/customers/<customer_id>/close")
def close_customer(customer_id):
    authenticate(["BranchManager"])
    customer = get_customer_or_404(customer_id)
    if customer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Customer cannot be closed from its current status", 409)
    for ctr in store.ctrs.values():
        if ctr["customer_id"] == customer_id and ctr["status"] in CLOSE_BLOCKING_CTR_STATUSES:
            raise ApiError(
                ERR_CUSTOMER_HAS_OPEN_ITEMS,
                "Customer has an open CTR",
                409,
            )
    for alert in store.alerts.values():
        if alert["customer_id"] == customer_id and alert["status"] in CLOSE_BLOCKING_ALERT_STATUSES:
            raise ApiError(
                ERR_CUSTOMER_HAS_OPEN_ITEMS,
                "Customer has an open structuring alert",
                409,
            )
    before = serialize_customer(customer)
    customer["status"] = "CLOSED"
    touch(customer)
    main_event(
        "POST /customers/{id}/close", "Customer", customer["id"], before,
        serialize_customer(customer),
    )
    return ok(serialize_customer(customer))
