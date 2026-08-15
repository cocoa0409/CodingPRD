"""Warranty claim endpoints (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_CLAIM_SERIAL_DUPLICATE,
    ERR_NO_AUTHORIZED_CENTER, ERR_CLAIM_NOT_SUBMITTED, ERR_CLAIM_NOT_UNDER_REVIEW,
    ERR_CLAIM_NOT_MORE_INFO, ERR_CLAIM_INFO_CYCLE_EXHAUSTED, ERR_CLAIM_NOT_APPROVED,
    ERR_CLAIM_NOT_RESOLVED, ERR_CENTER_SUSPENDED,
)
from middleware import check_claim_ownership, get_caller, require_roles
from response import success_object
from routes.helpers import get_one, list_response, public
from services import final_credit, new_record, provisional_credit, touch
from validate import (
    get_body, req_date, req_str, require_path_resource, require_ref,
)

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = ["BranchManager", "Account"]
CLAIM_MANAGER_ROLES = ["BranchManager"]
MAX_INFO_CYCLES = 3


def _require_claim(rid):
    return require_path_resource("warranty_claims", rid)


@bp.post("/pool-supply/warranty-claims")
def create_claim():
    caller = get_caller()
    require_roles(caller, ["Account", "BranchManager"])
    body = get_body()
    account_id = req_str(body, "account_id")
    product_id = req_str(body, "product_id")
    serial_number = req_str(body, "serial_number")
    brand = req_str(body, "brand")
    purchase_date = req_date(body, "purchase_date")
    failure_description = req_str(body, "failure_description")
    # existence (priority 4)
    require_ref("accounts", account_id, "account_id")
    product = require_ref("products", product_id, "product_id")
    # priority 16: equipment family + serial unique per product among non-REJECTED
    if product["product_family"] != "EQUIPMENT":
        raise_error(ERR_CLAIM_SERIAL_DUPLICATE, "warranty covers EQUIPMENT products only")
    serial_taken = any(
        c["product_id"] == product_id
        and c["serial_number"] == serial_number
        and c["status"] != "REJECTED"
        for c in db["warranty_claims"].values()
    )
    if serial_taken:
        raise_error(ERR_CLAIM_SERIAL_DUPLICATE, "serial_number already claimed for this product")
    # priority 17: at least one ACTIVE center carries the brand
    candidates = [
        c for c in db["service_centers"].values()
        if c["status"] == "ACTIVE" and brand in c["authorized_brands"]
    ]
    if not candidates:
        raise_error(ERR_NO_AUTHORIZED_CENTER, "no ACTIVE service center carries this brand")
    # Deterministic selector: region match (accounts carry no region field -> no
    # center matches), then labor_rate_cents ASC, then created_at ASC.
    candidates.sort(key=lambda c: (c["labor_rate_cents"], c["_seq"]))
    center = candidates[0]
    rec = new_record("warranty_claims", {
        "account_id": account_id,
        "product_id": product_id,
        "serial_number": serial_number,
        "brand": brand,
        "purchase_date": purchase_date,
        "failure_description": failure_description,
        "assigned_center_id": center["id"],
        "provisional_credit_cents": provisional_credit(center),
        "final_credit_cents": None,
        "actual_labor_hours": None,
        "info_cycles": 0,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/warranty-claims")
def list_claims():
    filters = {
        "account_id": request.args.get("account_id"),
        "status": request.args.get("status"),
        "product_id": request.args.get("product_id"),
        "assigned_center_id": request.args.get("assigned_center_id"),
    }
    return list_response("warranty_claims", CLAIM_READ_ROLES, filters)


@bp.get("/pool-supply/warranty-claims/<rid>")
def get_claim(rid):
    return get_one("warranty_claims", rid, CLAIM_READ_ROLES)


@bp.post("/pool-supply/warranty-claims/<rid>/start-review")
def start_review(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "SUBMITTED":
        raise_error(ERR_CLAIM_NOT_SUBMITTED, "start-review requires SUBMITTED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/request-info")
def request_info(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_CLAIM_NOT_UNDER_REVIEW, "request-info requires UNDER_REVIEW")
    claim["status"] = "MORE_INFO"
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/supply-info")
def supply_info(rid):
    caller = get_caller()
    require_roles(caller, ["Account"])
    claim = _require_claim(rid)
    check_claim_ownership(caller, claim)
    if claim["status"] != "MORE_INFO":
        raise_error(ERR_CLAIM_NOT_MORE_INFO, "supply-info requires MORE_INFO")
    if claim["info_cycles"] >= MAX_INFO_CYCLES:
        raise_error(ERR_CLAIM_INFO_CYCLE_EXHAUSTED, "info cycle limit (3) reached; the claim must be rejected")
    body = get_body()
    req_str(body, "info_note")
    claim["info_cycles"] += 1
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/approve")
def approve_claim(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_CLAIM_NOT_UNDER_REVIEW, "approve requires UNDER_REVIEW")
    center = db["service_centers"].get(claim["assigned_center_id"])
    if center is None or center["status"] != "ACTIVE":
        raise_error(ERR_CENTER_SUSPENDED, "assigned service center is not ACTIVE")
    claim["status"] = "APPROVED"
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/reject")
def reject_claim(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_CLAIM_NOT_UNDER_REVIEW, "reject requires UNDER_REVIEW")
    claim["status"] = "REJECTED"
    claim["provisional_credit_cents"] = 0  # compensation
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/resolve")
def resolve_claim(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "APPROVED":
        raise_error(ERR_CLAIM_NOT_APPROVED, "resolve requires APPROVED")
    body = get_body()
    hours = body.get("actual_labor_hours")
    if hours is None or isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise_error(ERR_INVALID_REQUEST, "actual_labor_hours must be a number > 0")
    center = db["service_centers"][claim["assigned_center_id"]]
    claim["actual_labor_hours"] = hours
    claim["final_credit_cents"] = final_credit(hours, center)
    claim["status"] = "RESOLVED"
    touch(claim)
    return success_object(public(claim))


@bp.post("/pool-supply/warranty-claims/<rid>/close")
def close_claim(rid):
    caller = get_caller()
    require_roles(caller, CLAIM_MANAGER_ROLES)
    claim = _require_claim(rid)
    if claim["status"] != "RESOLVED":
        raise_error(ERR_CLAIM_NOT_RESOLVED, "close requires RESOLVED")
    claim["status"] = "CLOSED"
    touch(claim)
    return success_object(public(claim))
