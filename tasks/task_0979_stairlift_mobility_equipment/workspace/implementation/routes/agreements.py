"""Agreement endpoints: list/get, skip-funding, payments, activate, cancel, close."""

from flask import Blueprint, request

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state, err_unauthorized, err_stale_version)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import (touch, serialize, audit,
                           recompute_customer_outstanding)

bp = Blueprint("agreements", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "FundingOfficer",
              "InstallCoordinator", "ClaimsAdjuster")
OPEN_STATES = ("PENDING_FUNDING", "FUNDED", "SCHEDULED", "INSTALLED",
               "ACTIVE", "REMOVAL_REQUESTED")


def _load_agreement(aid):
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    return ag


def _customer_owns(user_id, role, agreement):
    if role == "Customer" and user_id != agreement["customer_id"]:
        raise err_unauthorized()


@bp.get("/stairlift-ops/agreements")
def list_agreements():
    require_role(*READ_ROLES)
    limit, offset = get_pagination()
    status = request.args.get("status")
    cid = request.args.get("customer_id")
    mode = request.args.get("mode")
    items = sorted(db.agreements.values(), key=lambda a: a["created_at"])
    if status:
        items = [a for a in items if a["status"] == status]
    if cid:
        items = [a for a in items if a["customer_id"] == cid]
    if mode:
        items = [a for a in items if a["mode"] == mode]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.get("/stairlift-ops/agreements/<aid>")
def get_agreement(aid):
    user_id, role = require_role(*READ_ROLES, "Customer")
    ag = _load_agreement(aid)
    _customer_owns(user_id, role, ag)
    return success_object(serialize(ag))


@bp.post("/stairlift-ops/agreements/<aid>/skip-funding")
def skip_funding(aid):
    user_id, role = require_role("FundingOfficer")
    ag = _load_agreement(aid)
    if ag["status"] != "PENDING_FUNDING":
        raise err_invalid_state("Agreement must be PENDING_FUNDING")
    # waiver signed OR all funding apps DENIED/WITHDRAWN
    if not ag.get("liability_waiver_signed"):
        apps = [f for f in db.funding_applications.values()
                if f["quote_id"] == ag["quote_id"]]
        if any(f["status"] not in ("DENIED", "WITHDRAWN") for f in apps):
            raise ApiError("ERR_PENDING_FUNDING_APPS", 402,
                           "Cannot skip funding while applications are pending")
    ag["status"] = "SCHEDULED"
    touch(ag)
    audit("Agreement", ag["id"], "AGREEMENT_SKIP_FUNDING", role,
          {"to": "SCHEDULED"})
    recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(ag))


@bp.post("/stairlift-ops/agreements/<aid>/payments")
def record_payment(aid):
    user_id, role = require_role("Customer", "FundingOfficer", "PlatformAdmin")
    ag = _load_agreement(aid)
    _customer_owns(user_id, role, ag)
    body = get_json_body(["amount_cents", "expected_agreement_version"])
    amount = body["amount_cents"]
    expected = body["expected_agreement_version"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise err_invalid_request("amount_cents must be an integer")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_agreement_version must be an integer")
    if ag["version"] != expected:
        raise err_stale_version()
    ag["paid_to_date_cents"] = ag.get("paid_to_date_cents", 0) + amount
    touch(ag)
    audit("Agreement", ag["id"], "AGREEMENT_PAYMENT", role,
          {"amount_cents": amount})
    recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(ag))


@bp.post("/stairlift-ops/agreements/<aid>/activate")
def activate_agreement(aid):
    user_id, role = require_role("InstallCoordinator")
    ag = _load_agreement(aid)
    if ag["status"] != "INSTALLED":
        raise err_invalid_state("Agreement must be INSTALLED to activate")
    plan = next(
        (sp for sp in db.service_plans.values()
         if sp["agreement_id"] == aid and sp["status"] == "ACTIVE"),
        None)
    if plan is None:
        raise ApiError("ERR_SERVICE_PLAN_REQUIRED", 402,
                       "Activation requires an ACTIVE ServicePlan")
    ag["status"] = "ACTIVE"
    ag["_activated_at"] = db.now_iso()
    ag["_rental_months_accrued"] = 0
    touch(ag)
    unit = db.equipment_units.get(ag.get("equipment_unit_id"))
    if unit is not None and unit["status"] == "INSTALLED":
        unit["status"] = "IN_SERVICE"
        touch(unit)
    audit("Agreement", ag["id"], "AGREEMENT_ACTIVATED", role, {"to": "ACTIVE"})
    recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(ag))


@bp.post("/stairlift-ops/agreements/<aid>/cancel")
def cancel_agreement(aid):
    user_id, role = require_role("FundingOfficer")
    ag = _load_agreement(aid)
    if ag["status"] not in ("PENDING_FUNDING", "FUNDED", "SCHEDULED"):
        raise err_invalid_state(
            "Agreement must be PENDING_FUNDING, FUNDED, or SCHEDULED to cancel")
    # cancel any SCHEDULED install job
    for j in db.install_jobs.values():
        if j["agreement_id"] == aid and j["status"] == "SCHEDULED":
            j["status"] = "CANCELLED"
            touch(j)
            audit("InstallJob", j["id"], "INSTALL_CANCELLED", "system",
                  {"to": "CANCELLED", "reason": "agreement cancelled"})
    unit = db.equipment_units.get(ag.get("equipment_unit_id"))
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "IN_STOCK"
        touch(unit)
    # PRD §3.4: "every funding application on the quote moves to WITHDRAWN"
    for f in db.funding_applications.values():
        if f["quote_id"] == ag["quote_id"] and f["status"] != "WITHDRAWN":
            f["status"] = "WITHDRAWN"
            touch(f)
    ag["status"] = "CANCELLED"
    touch(ag)
    audit("Agreement", ag["id"], "AGREEMENT_CANCELLED", role,
          {"to": "CANCELLED"})
    recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(ag))


@bp.post("/stairlift-ops/agreements/<aid>/close")
def close_agreement(aid):
    user_id, role = require_role("InstallCoordinator")
    ag = _load_agreement(aid)
    if ag["status"] != "REMOVED":
        raise err_invalid_state("Agreement must be REMOVED to close")
    for wc in db.warranty_claims.values():
        if wc["agreement_id"] == aid and wc["status"] not in ("DENIED", "PAID"):
            raise err_invalid_state(
                "All WarrantyClaims must be terminal before close")
    ag["status"] = "CLOSED"
    touch(ag)
    audit("Agreement", ag["id"], "AGREEMENT_CLOSED", role, {"to": "CLOSED"})
    # Customer -> FORMER when no other open agreement
    customer = db.customers.get(ag["customer_id"])
    if customer is not None:
        has_open = any(
            o["id"] != aid and o["customer_id"] == ag["customer_id"]
            and o["status"] in OPEN_STATES
            for o in db.agreements.values())
        if not has_open and customer["status"] == "ACTIVE":
            customer["status"] = "FORMER"
            touch(customer)
            audit("Customer", customer["id"], "CUSTOMER_FORMER", "system",
                  {"to": "FORMER"})
    return success_object(serialize(ag))
