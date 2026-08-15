"""AdvisoryAgreement endpoints + fee-statement."""

from decimal import Decimal
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, to_float, req_body, require_fields, req_enum, opt_number,
    pagination_params, page_slice, get_or_404, touch, touch_no_version, parse_date,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_agreement


bp = Blueprint("agreements", __name__)


@bp.route("/advisory/advisory-agreements", methods=["POST"])
def create_agreement():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["operation_id", "fee_type"])
    operation_id = body["operation_id"]
    if not isinstance(operation_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id must be a string", 400)
    fee_type = req_enum(body, "fee_type", {"PER_BUSHEL", "FLAT_ANNUAL"})
    rate = opt_number(body, "rate_per_bushel")
    flat = opt_number(body, "flat_annual_fee")
    cap = opt_number(body, "annual_cap_dollars")
    # PRD 3.10 states only "required for" rules for the conditional fee fields
    # (unlike contracts in 3.7, which explicitly "forbid" the other pricing
    # fields); co-presence of the other field is not a violation.
    if fee_type == "PER_BUSHEL":
        if rate is None:
            raise ApiError("ERR_VALIDATION", "rate_per_bushel required for PER_BUSHEL", 400)
    else:
        if flat is None:
            raise ApiError("ERR_VALIDATION", "flat_annual_fee required for FLAT_ANNUAL", 400)
    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)
    aid = db.new_id()
    now = db.now_iso()
    agreement = {
        "id": aid,
        "operation_id": operation_id,
        "fee_type": fee_type,
        "rate_per_bushel": rate,
        "flat_annual_fee": flat,
        "annual_cap_dollars": cap,
        "billable_bushels_accrued": 0,
        "disclosure_status": "NONE",
        "acknowledged_agreement_version": None,
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "compliance_certified": False,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.agreements[aid] = agreement
    return success_object(ser_agreement(agreement), status=201)


@bp.route("/advisory/advisory-agreements/<agreementId>", methods=["GET"])
def get_agreement(agreementId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    check_grower_ownership(user_id, role, a["operation_id"])
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements", methods=["GET"])
def list_agreements():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    status = request.args.get("status")
    items = list(DB.agreements.values())
    if role == "Grower":
        items = [a for a in items if a["operation_id"] == user_id]
    if operation_id is not None:
        items = [a for a in items if a["operation_id"] == operation_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_agreement(a) for a in slice_], limit, offset, total)


@bp.route("/advisory/advisory-agreements/<agreementId>/submit", methods=["POST"])
def submit_agreement(agreementId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Agreement in state {a['status']} cannot be submitted", 409)
    a["status"] = "PENDING_SIGNATURE"
    a["disclosure_status"] = "REQUIRED"
    a["submitted_by_user_id"] = user_id
    # Submit increments version (PRD 3.10 version discipline)
    touch(a)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>/deliver-disclosure", methods=["POST"])
def deliver_disclosure(agreementId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    if a["disclosure_status"] not in {"REQUIRED", "STALE"}:
        raise ApiError("ERR_INVALID_STATE", f"Disclosure in state {a['disclosure_status']} cannot be delivered", 409)
    a["disclosure_status"] = "DELIVERED"
    touch_no_version(a)  # deliver-disclosure does NOT increment version (PRD 3.10)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>/acknowledge-disclosure", methods=["POST"])
def acknowledge_disclosure(agreementId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    check_grower_ownership(user_id, role, a["operation_id"])
    if a["disclosure_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", f"Disclosure in state {a['disclosure_status']} cannot be acknowledged", 409)
    a["disclosure_status"] = "ACKNOWLEDGED"
    a["acknowledged_agreement_version"] = a["version"]
    touch_no_version(a)  # acknowledge-disclosure does NOT increment version (PRD 3.10)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>/sign", methods=["POST"])
def sign_agreement(agreementId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    check_grower_ownership(user_id, role, a["operation_id"])
    if a["status"] != "PENDING_SIGNATURE":
        raise ApiError("ERR_INVALID_STATE", f"Agreement in state {a['status']} cannot be signed", 409)
    if a["disclosure_status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED", "Disclosure must be ACKNOWLEDGED before signing", 409)
    if a.get("acknowledged_agreement_version") != a["version"]:
        raise ApiError("ERR_DISCLOSURE_STALE", "Disclosure acknowledgment is stale", 409)
    a["status"] = "ACTIVE"
    touch_no_version(a)  # sign does NOT increment version (PRD 3.10)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>", methods=["PUT"])
def amend_agreement(agreementId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    body = req_body()
    status_change = body.get("status_change")
    if status_change is not None and status_change != "TERMINATE":
        raise ApiError("ERR_VALIDATION", "status_change must be TERMINATE when provided", 400)
    rate = opt_number(body, "rate_per_bushel")
    flat = opt_number(body, "flat_annual_fee")
    cap = opt_number(body, "annual_cap_dollars")

    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Agreement in state {a['status']} cannot be amended", 409)

    if status_change == "TERMINATE":
        # No ACTIVE MarketingPlan references this operation
        for p in DB.plans.values():
            if p["operation_id"] == a["operation_id"] and p["status"] == "ACTIVE":
                raise ApiError("ERR_INVALID_STATE", "An ACTIVE MarketingPlan references this operation", 409)
        a["status"] = "TERMINATED"
        touch(a)
        return success_object(ser_agreement(a))

    # Amendment self-loop: increments version, flips ACKNOWLEDGED -> STALE
    if rate is not None:
        a["rate_per_bushel"] = rate
    if flat is not None:
        a["flat_annual_fee"] = flat
    if cap is not None:
        a["annual_cap_dollars"] = cap
    if a["disclosure_status"] == "ACKNOWLEDGED":
        a["disclosure_status"] = "STALE"
    touch(a)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>/certify-compliance", methods=["POST"])
def certify_compliance(agreementId):
    user_id, role = get_auth()
    require_role(role, ["ComplianceOfficer"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    if a.get("submitted_by_user_id") is not None and a["submitted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Certifier must differ from submitting advisor", 403)
    a["compliance_certified"] = True
    a["certified_by_user_id"] = user_id
    touch_no_version(a)  # certify-compliance does NOT increment version (PRD 3.10)
    return success_object(ser_agreement(a))


@bp.route("/advisory/advisory-agreements/<agreementId>/fee-statement", methods=["GET"])
def fee_statement(agreementId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    a = get_or_404(DB.agreements, agreementId, "AdvisoryAgreement")
    check_grower_ownership(user_id, role, a["operation_id"])
    ps = request.args.get("period_start")
    pe = request.args.get("period_end")
    if not ps or not pe:
        raise ApiError("ERR_VALIDATION", "period_start and period_end are required", 400)
    period_start = parse_date(ps)
    period_end = parse_date(pe)

    billable = Decimal("0")
    for t in DB.tickets.values():
        if t["status"] != "CONFIRMED":
            continue
        c = DB.contracts.get(t["contract_id"])
        if c is None or c["operation_id"] != a["operation_id"]:
            continue
        d = parse_date(t["delivery_date"])
        if period_start <= d <= period_end:
            billable += D(t["net_bushels"])

    if a["fee_type"] == "PER_BUSHEL":
        fee = r2(billable * D(a["rate_per_bushel"]))
    else:
        fee = r2(D(a["flat_annual_fee"]))
    capped = False
    if a.get("annual_cap_dollars") is not None:
        cap = D(a["annual_cap_dollars"])
        if fee > cap:
            fee = cap
            capped = True
    # billable_bushels: integer per scaffold output shape — but net_bushels is 3dp.
    # PRD: "billable bushels are the sum of net_bushels" — keep as number.
    result = {
        "billable_bushels": to_float(billable),
        "fee_dollars": to_float(fee),
        "capped": capped,
    }
    return success_object(result)
