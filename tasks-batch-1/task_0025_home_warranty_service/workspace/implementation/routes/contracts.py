"""Contract routes (PRD §3.2, §3.8).

Lifecycle: PENDING_PAYMENT -> ACTIVE -> EXPIRING_SOON -> {RENEWED, EXPIRED}.
Cancellation possible from PENDING_PAYMENT (unconditionally) or ACTIVE
(only when no open claims exist).
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OPEN_CLAIMS_BLOCK_CANCEL,
    ERR_PACKAGE_RETIRED,
    ERR_STALE_VERSION,
    ERR_NOT_FOUND,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_int,
    require_string,
    lookup_or_404,
    parse_clock_dt,
)
from services.ownership import assert_customer_owns_contract
from services.calculations import compute_renewal_premium_cents


bp = Blueprint("contracts", __name__)


VIEW_ROLES = ["PlatformAdmin", "Customer", "Dispatcher"]
OPEN_CLAIM_STATUSES = {"SUBMITTED", "ASSESSED", "DISPATCHED"}


# ---------- POST /contracts --------------------------------------------------


@bp.post("/contracts")
def create_contract():
    require_auth(["Customer", "PlatformAdmin"])()
    body = get_json_body()
    require_fields(body, ["customer_id", "package_id"])
    customer_id = body["customer_id"]
    package_id = body["package_id"]
    require_string(customer_id, "customer_id")
    require_string(package_id, "package_id")

    # FK existence (priority 4 — ERR_NOT_FOUND).
    customer = lookup_or_404(db.customers, customer_id, "Customer")
    pkg = lookup_or_404(db.contract_packages, package_id, "ContractPackage")

    # Customer ownership: Customer caller may only open contracts as themselves.
    # PRD §1.7 RBAC: 'POST /contracts (as own customer_id)'.
    if current_role() == "Customer" and customer_id != current_user_id():
        from errors import ERR_FORBIDDEN
        raise APIError(ERR_FORBIDDEN, 403, "Customer can only open contracts as self")

    # Retired package blocks new contracts.
    if pkg["status"] != "ACTIVE":
        raise APIError(ERR_PACKAGE_RETIRED, 422, "Package is retired")

    contract = {
        "customer_id": customer_id,
        "package_id": package_id,
        "status": "PENDING_PAYMENT",
        "coverage_start_utc": None,
        "coverage_end_utc": None,
        "renewal_reminder_sent_at": None,
        "claims_in_period_count": 0,
        "total_paid_out_cents": 0,
        "annual_premium_due_cents": 0,
    }
    db.stamp_common(contract)
    db.contracts[contract["id"]] = contract
    return ok_object(contract, 201)


# ---------- GET /contracts/{id} ---------------------------------------------


@bp.get("/contracts/<cid>")
def get_contract(cid: str):
    require_auth(VIEW_ROLES)()
    contract = lookup_or_404(db.contracts, cid, "Contract")
    assert_customer_owns_contract(contract, current_role(), current_user_id())
    return ok_object(contract, 200)


# ---------- GET /contracts ---------------------------------------------------


@bp.get("/contracts")
def list_contracts():
    require_auth(VIEW_ROLES)()
    limit, offset = paginate_params(request.args)
    customer_filter = request.args.get("customer_id")
    package_filter = request.args.get("package_id")
    status_filter = request.args.get("status")

    role = current_role()
    user_id = current_user_id()

    items = list(db.contracts.values())
    # Customer role can only see their own contracts (PRD §1.7).
    if role == "Customer":
        items = [c for c in items if c["customer_id"] == user_id]
    if customer_filter:
        items = [c for c in items if c["customer_id"] == customer_filter]
    if package_filter:
        items = [c for c in items if c["package_id"] == package_filter]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /contracts/{id}/activate -----------------------------------


@bp.post("/contracts/<cid>/activate")
def activate_contract(cid: str):
    require_auth(["PlatformAdmin"])()
    contract = lookup_or_404(db.contracts, cid, "Contract")

    if contract["status"] != "PENDING_PAYMENT":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot activate from status {contract['status']}")

    pkg = db.contract_packages.get(contract["package_id"])
    if pkg is None:
        # Shouldn't happen — packages are not deleted, only retired.
        raise APIError(ERR_NOT_FOUND, 404, "Referenced package not found")
    if pkg["status"] != "ACTIVE":
        # PRD §3.2: 'Activation is only permitted when the contract's referenced
        # package is itself ACTIVE; an activation pointed at a retired package
        # fails state validation.'
        raise APIError(ERR_INVALID_STATE, 409, "Package is not ACTIVE")

    now_dt = parse_clock_dt()
    end_dt = now_dt + timedelta(days=365)
    contract["coverage_start_utc"] = db.iso_format(now_dt)
    contract["coverage_end_utc"] = db.iso_format(end_dt)
    if contract.get("annual_premium_due_cents", 0) == 0:
        contract["annual_premium_due_cents"] = int(pkg["annual_premium_cents"])
    contract["status"] = "ACTIVE"
    db.bump(contract)
    return ok_object(contract, 200)


# ---------- POST /contracts/{id}/cancel -------------------------------------


@bp.post("/contracts/<cid>/cancel")
def cancel_contract(cid: str):
    require_auth(["Customer", "PlatformAdmin"])()
    contract = lookup_or_404(db.contracts, cid, "Contract")
    assert_customer_owns_contract(contract, current_role(), current_user_id())

    status = contract["status"]
    if status not in {"PENDING_PAYMENT", "ACTIVE"}:
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot cancel from status {status}")

    if status == "ACTIVE":
        # Block when any claim on this contract is in {SUBMITTED, ASSESSED, DISPATCHED}.
        for ct in db.claim_tickets.values():
            if ct["contract_id"] == cid and ct["status"] in OPEN_CLAIM_STATUSES:
                raise APIError(
                    ERR_OPEN_CLAIMS_BLOCK_CANCEL,
                    422,
                    "Open claims block contract cancellation",
                )

    contract["status"] = "CANCELLED"
    db.bump(contract)
    return ok_object(contract, 200)


# ---------- POST /contracts/{id}/renew --------------------------------------


@bp.post("/contracts/<cid>/renew")
def renew_contract(cid: str):
    require_auth(["Customer", "PlatformAdmin"])()
    contract = lookup_or_404(db.contracts, cid, "Contract")
    assert_customer_owns_contract(contract, current_role(), current_user_id())

    body = get_json_body()
    # State check is priority 6; OCC is priority 13 (per scaffold §1.4).
    if contract["status"] != "EXPIRING_SOON":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Cannot renew from status {contract['status']}",
        )

    new_package_id = body.get("new_package_id")
    if new_package_id is not None:
        require_string(new_package_id, "new_package_id")
        new_pkg = lookup_or_404(db.contract_packages, new_package_id, "ContractPackage")
        if new_pkg["status"] != "ACTIVE":
            raise APIError(ERR_PACKAGE_RETIRED, 422, "new_package_id refers to a retired package")
        successor_package_id = new_package_id
    else:
        successor_package_id = contract["package_id"]
        new_pkg = db.contract_packages.get(successor_package_id)
        if new_pkg is None:
            raise APIError(ERR_NOT_FOUND, 404, "Original package not found")

    # OCC check (priority 13 in scaffold table).
    require_fields(body, ["expected_contract_version"])
    expected = body["expected_contract_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_contract_version must be an integer")
    if expected != contract.get("version"):
        raise APIError(ERR_STALE_VERSION, 412, "Contract version mismatch")

    # Compute renewal premium.
    now_dt = parse_clock_dt()
    end_dt = db.parse_iso_dt(contract["coverage_end_utc"])
    assert end_dt is not None
    delta_seconds = (end_dt - now_dt).total_seconds()
    # floor((end - now)/86400) — Python int() truncates toward 0; since end >= now
    # in EXPIRING_SOON, delta is non-negative, so int() == floor() here. We use
    # explicit math.floor for safety against edge cases.
    import math
    days_remaining = int(math.floor(delta_seconds / 86400.0))

    item_count = sum(1 for it in db.covered_items.values() if it["contract_id"] == cid)
    renewal_premium = compute_renewal_premium_cents(
        annual_premium_cents=int(new_pkg["annual_premium_cents"]),
        days_remaining=days_remaining,
        covered_item_count=item_count,
    )

    successor = {
        "customer_id": contract["customer_id"],
        "package_id": successor_package_id,
        "status": "PENDING_PAYMENT",
        "coverage_start_utc": None,
        "coverage_end_utc": None,
        "renewal_reminder_sent_at": None,
        "claims_in_period_count": 0,
        "total_paid_out_cents": 0,
        "annual_premium_due_cents": renewal_premium,
    }
    db.stamp_common(successor)
    db.contracts[successor["id"]] = successor

    # Mark original RENEWED and bump.
    contract["status"] = "RENEWED"
    db.bump(contract)

    return ok_object(successor, 201)
