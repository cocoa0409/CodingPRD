"""Quote endpoints, including issue/revise/accept with cascades and OCC."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state, err_unauthorized, err_stale_version)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import (stamp_new, touch, serialize, audit,
                           recompute_customer_outstanding, parse_iso8601)
from services.calculations import (valid_rail_length_m,
                                   provisional_quote_total,
                                   issued_quote_total)
from services.sweeps import QUOTE_TTL_DAYS

bp = Blueprint("quotes", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "FundingOfficer")


def _load_quote(qid):
    q = db.quotes.get(qid)
    if q is None:
        raise err_not_found("Quote not found")
    return q


@bp.post("/stairlift-ops/customers/<cid>/quotes")
def create_quote(cid):
    require_role("SalesRep")
    customer = db.customers.get(cid)
    if customer is None:
        raise err_not_found("Customer not found")
    body = get_json_body(["home_assessment_id", "model_code", "acquisition_mode"])
    ha_id = body["home_assessment_id"]
    model_code = body["model_code"]
    mode = body["acquisition_mode"]
    if not isinstance(ha_id, str) or not isinstance(model_code, str) \
            or not isinstance(mode, str):
        raise err_invalid_request("home_assessment_id/model_code/acquisition_mode must be strings")
    if mode not in ("RENTAL", "PURCHASE"):
        raise err_invalid_request("acquisition_mode must be RENTAL or PURCHASE")
    assessment = db.home_assessments.get(ha_id)
    if assessment is None:
        raise err_not_found("HomeAssessment not found")
    pm_id = db.product_models_by_code.get(model_code)
    if pm_id is None:
        raise err_not_found("ProductModel not found")
    pm = db.product_models[pm_id]
    quote = {
        "customer_id": cid,
        "home_assessment_id": ha_id,
        "model_code": model_code,
        "acquisition_mode": mode,
        "status": "DRAFT",
        "revision_number": 1,
        "provisional_total_cents": provisional_quote_total(pm, mode),
        "issued_total_cents": 0,
        "issued_at": None,
        "expires_at": None,
        "valid_rail_length_m": valid_rail_length_m(
            assessment["stair_rise_mm"], assessment["stair_run_mm"])
        if assessment.get("stair_rise_mm") is not None else 0.0,
    }
    stamp_new(quote)
    db.quotes[quote["id"]] = quote
    return success_object(serialize(quote), 201)


@bp.get("/stairlift-ops/customers/<cid>/quotes")
def list_customer_quotes(cid):
    user_id, role = require_role("PlatformAdmin", "SalesRep", "FundingOfficer",
                                 "Customer")
    if cid not in db.customers:
        raise err_not_found("Customer not found")
    if role == "Customer" and user_id != cid:
        raise err_unauthorized()
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = sorted(
        (q for q in db.quotes.values() if q["customer_id"] == cid),
        key=lambda q: q["created_at"])
    if status:
        items = [q for q in items if q["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(q) for q in page], limit, offset, total)


@bp.get("/stairlift-ops/quotes")
def list_quotes():
    require_role(*READ_ROLES)
    limit, offset = get_pagination()
    ha = request.args.get("home_assessment_id")
    status = request.args.get("status")
    cid = request.args.get("customer_id")
    items = sorted(db.quotes.values(), key=lambda q: q["created_at"])
    if ha:
        items = [q for q in items if q["home_assessment_id"] == ha]
    if status:
        items = [q for q in items if q["status"] == status]
    if cid:
        items = [q for q in items if q["customer_id"] == cid]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(q) for q in page], limit, offset, total)


@bp.get("/stairlift-ops/quotes/<qid>")
def get_quote(qid):
    user_id, role = require_role("PlatformAdmin", "SalesRep", "FundingOfficer",
                                 "Customer")
    q = _load_quote(qid)
    if role == "Customer" and user_id != q["customer_id"]:
        raise err_unauthorized()
    return success_object(serialize(q))


@bp.get("/stairlift-ops/quotes/<qid>/agreements")
def list_quote_agreements(qid):
    require_role("PlatformAdmin", "SalesRep", "FundingOfficer",
                 "InstallCoordinator")
    _load_quote(qid)
    limit, offset = get_pagination()
    items = sorted(
        (a for a in db.agreements.values() if a["quote_id"] == qid),
        key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.post("/stairlift-ops/quotes/<qid>/issue")
def issue_quote(qid):
    user_id, role = require_role("SalesRep")
    q = _load_quote(qid)
    if q["status"] != "DRAFT":
        raise err_invalid_state("Quote must be DRAFT to issue")
    assessment = db.home_assessments.get(q["home_assessment_id"])
    if assessment is None or assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED", 409,
                       "HomeAssessment must be APPROVED")
    pm = db.product_models[db.product_models_by_code[q["model_code"]]]
    if assessment["staircase_kind"] == "CURVED" and not pm["supports_curved"]:
        raise ApiError("ERR_MODEL_INCOMPATIBLE", 422,
                       "Model does not support curved staircases")
    if assessment.get("has_outdoor_exposure") and not pm["supports_outdoor"]:
        raise ApiError("ERR_MODEL_INCOMPATIBLE", 422,
                       "Model does not support outdoor exposure")
    for other in db.quotes.values():
        if other["customer_id"] == q["customer_id"] and other["id"] != q["id"] \
                and other["status"] == "ISSUED":
            raise ApiError("ERR_ACTIVE_QUOTE_EXISTS", 409,
                           "Another quote on this customer is ISSUED")
    q["issued_total_cents"] = issued_quote_total(q, assessment, pm)
    now = db.get_now()
    q["issued_at"] = db.now_iso()
    q["expires_at"] = db.iso_z(now + timedelta(days=QUOTE_TTL_DAYS))
    q["status"] = "ISSUED"
    touch(q)
    audit("Quote", q["id"], "QUOTE_ISSUED", role, {"to": "ISSUED"})
    return success_object(serialize(q))


@bp.post("/stairlift-ops/quotes/<qid>/revise")
def revise_quote(qid):
    user_id, role = require_role("SalesRep")
    q = _load_quote(qid)
    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to revise")
    exp = parse_iso8601(q["expires_at"])
    if exp is not None and exp <= db.get_now():
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote has expired")
    q["status"] = "DRAFT"
    q["revision_number"] = q["revision_number"] + 1
    q["issued_total_cents"] = 0
    q["issued_at"] = None
    q["expires_at"] = None
    touch(q)
    audit("Quote", q["id"], "QUOTE_REVISED", role,
          {"to": "DRAFT", "revision_number": q["revision_number"]})
    return success_object(serialize(q))


@bp.post("/stairlift-ops/quotes/<qid>/accept")
def accept_quote(qid):
    user_id, role = require_role("Customer", "PlatformAdmin")
    q = _load_quote(qid)
    if role == "Customer" and user_id != q["customer_id"]:
        raise err_unauthorized()
    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to accept")
    body = get_json_body(["equipment_unit_id", "expected_customer_version"])
    equipment_unit_id = body["equipment_unit_id"]
    expected_customer_version = body["expected_customer_version"]
    if not isinstance(equipment_unit_id, str):
        raise err_invalid_request("equipment_unit_id must be a string")
    if isinstance(expected_customer_version, bool) or \
            not isinstance(expected_customer_version, int):
        raise err_invalid_request("expected_customer_version must be an integer")
    liability_waiver_signed = body.get("liability_waiver_signed", False)
    if not isinstance(liability_waiver_signed, bool):
        raise err_invalid_request("liability_waiver_signed must be boolean")
    committed_rental_months = body.get("committed_rental_months")
    if q["acquisition_mode"] == "RENTAL":
        if committed_rental_months is None:
            raise err_invalid_request(
                "committed_rental_months required for RENTAL")
        if isinstance(committed_rental_months, bool) or \
                not isinstance(committed_rental_months, int):
            raise err_invalid_request("committed_rental_months must be an integer")
        if committed_rental_months < 3:
            raise err_invalid_request(
                "committed_rental_months must be >= 3")
    # temporal gate
    exp = parse_iso8601(q["expires_at"])
    if exp is not None and exp <= db.get_now():
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote has expired")
    # unit availability
    unit = db.equipment_units.get(equipment_unit_id)
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409,
                       "EquipmentUnit does not exist")
    if unit["status"] != "IN_STOCK" or unit["model_code"] != q["model_code"]:
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409,
                       "EquipmentUnit not available or model mismatch")
    # OCC on Customer.version
    customer = db.customers.get(q["customer_id"])
    if customer is None:
        raise err_not_found("Customer not found")
    if customer["version"] != expected_customer_version:
        raise err_stale_version()

    # --- commit ---
    q["status"] = "ACCEPTED"
    touch(q)
    unit["status"] = "RESERVED"
    touch(unit)
    pm = db.product_models[db.product_models_by_code[q["model_code"]]]
    if q["acquisition_mode"] == "PURCHASE":
        list_price = q["issued_total_cents"]
    else:
        list_price = pm["monthly_rental_rate_cents"] * committed_rental_months
    agreement = {
        "quote_id": q["id"],
        "customer_id": q["customer_id"],
        "mode": q["acquisition_mode"],
        "status": "PENDING_FUNDING",
        "equipment_unit_id": equipment_unit_id,
        "list_price_cents": list_price,
        "committed_rental_months": committed_rental_months
        if q["acquisition_mode"] == "RENTAL" else None,
        "funding_applied_cents": 0,
        "paid_to_date_cents": 0,
        "liability_waiver_signed": liability_waiver_signed,
        "version_anchor_quote_revision": q["revision_number"],
    }
    stamp_new(agreement)
    db.agreements[agreement["id"]] = agreement
    # acceptance increments customer version by one
    touch(customer)
    recompute_customer_outstanding(customer["id"])
    audit("Quote", q["id"], "QUOTE_ACCEPTED", role, {"to": "ACCEPTED"})
    audit("Agreement", agreement["id"], "AGREEMENT_CREATED", role,
          {"status": "PENDING_FUNDING"})
    return success_object(serialize(agreement), 201)
