"""Vendor registry: registration, approval, suspension, risk scores (PRD §3.3, §3.7)."""

from flask import Blueprint, request

from db import store, touch
from errors import (
    ApiError,
    ERR_VENDOR_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND,
    ERR_VENDOR_INVALID_TRANSITION,
)
from middleware import require_role
from response import ok, ok_list, parse_pagination, paginate
from services.validation import (
    check_frozen,
    get_json_body,
    new_entity,
    not_found,
    req_list,
    req_str,
    run_lazy_effects,
)

bp = Blueprint("vendors", __name__)

DECLARED_PURPOSES_ENUM = ("ANALYTICS", "ADVERTISING", "SALE_SHARE")
SEVERITY_WEIGHTS = {"HIGH": 50, "MEDIUM": 25}
SCORE_CAP = 100


def vendor_risk_scores(vendor_id):
    """vendor_risk_scores calculation (SCAFFOLD Table 3), computed on read:

    strict   = 100 if any finding of the vendor is CONFIRMED_VIOLATION else 0
    weighted = min(100, sum of HIGH=50 / MEDIUM=25 over OPEN + CONFIRMED_VIOLATION)
    REMEDIATED / CLOSED findings contribute nothing to either score.
    """
    strict = 0
    weighted = 0
    for finding in store["tracker_findings"].values():
        if finding.get("vendor_id") != vendor_id:
            continue
        status = finding.get("status")
        if status == "CONFIRMED_VIOLATION":
            strict = SCORE_CAP
        if status in ("OPEN", "CONFIRMED_VIOLATION"):
            weighted += SEVERITY_WEIGHTS.get(finding.get("severity"), 0)
    return strict, min(SCORE_CAP, weighted)


def _with_scores(vendor):
    strict, weighted = vendor_risk_scores(vendor["id"])
    vendor["risk_score_strict"] = strict
    vendor["risk_score_weighted"] = weighted
    return vendor


@bp.post("/v1/vendors")
def create_vendor():
    require_role("VendorManager")
    body = get_json_body()
    property_id = req_str(body, "property_id")
    legal_name = req_str(body, "legal_name")
    declared_purposes = req_list(body, "declared_purposes", item_enum=DECLARED_PURPOSES_ENUM)
    tracker_signatures = req_list(body, "tracker_signatures", item_type=str)
    if property_id not in store["properties"]:
        not_found("properties", ERR_PROPERTY_NOT_FOUND)
    # Rung 5: vendor registration is frozen-gated (PRD §2.6).
    run_lazy_effects()
    check_frozen(property_id)
    vendor = new_entity(
        {
            "property_id": property_id,
            "legal_name": legal_name,
            "declared_purposes": declared_purposes,
            "tracker_signatures": tracker_signatures,
            "status": "PENDING_REVIEW",
            "risk_score_strict": 0,
            "risk_score_weighted": 0,
        }
    )
    store["vendors"][vendor["id"]] = vendor
    return ok(vendor, 201)


@bp.get("/v1/vendors")
def list_vendors():
    require_role("Any")
    limit, offset = parse_pagination(request.args)
    items = list(store["vendors"].values())
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    if property_id is not None:
        items = [v for v in items if v.get("property_id") == property_id]
    if status is not None:
        items = [v for v in items if v.get("status") == status]
    page, total = paginate(items, limit, offset)
    return ok_list([_with_scores(v) for v in page], total, limit, offset)


@bp.get("/v1/vendors/<id>")
def get_vendor(id):
    require_role("Any")
    vendor = store["vendors"].get(id)
    if vendor is None:
        not_found("vendors", ERR_VENDOR_NOT_FOUND)
    return ok(_with_scores(vendor))


@bp.post("/v1/vendors/<id>/approve")
def approve_vendor(id):
    require_role("PrivacyAdmin")
    vendor = store["vendors"].get(id)
    if vendor is None:
        not_found("vendors", ERR_VENDOR_NOT_FOUND)
    run_lazy_effects()
    check_frozen(vendor["property_id"])
    if vendor["status"] != "PENDING_REVIEW":
        raise ApiError(
            ERR_VENDOR_INVALID_TRANSITION,
            f"Approve requires PENDING_REVIEW; vendor is {vendor['status']}",
            409,
        )
    vendor["status"] = "APPROVED"
    touch(vendor)
    return ok(_with_scores(vendor))


@bp.post("/v1/vendors/<id>/suspend")
def suspend_vendor(id):
    require_role("PrivacyAdmin")
    vendor = store["vendors"].get(id)
    if vendor is None:
        not_found("vendors", ERR_VENDOR_NOT_FOUND)
    run_lazy_effects()
    check_frozen(vendor["property_id"])
    if vendor["status"] != "APPROVED":
        raise ApiError(
            ERR_VENDOR_INVALID_TRANSITION,
            f"Suspend requires APPROVED; vendor is {vendor['status']}",
            409,
        )
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    # Cascade: every ENABLED tag rule of this vendor goes dark at once.
    for rule in list(store["tag_rules"].values()):
        if rule.get("vendor_id") == vendor["id"] and rule.get("status") == "ENABLED":
            rule["status"] = "DISABLED"
            touch(rule)
    return ok(_with_scores(vendor))


@bp.get("/v1/vendors/<id>/tracker-findings")
def list_vendor_tracker_findings(id):
    require_role("Any")
    vendor = store["vendors"].get(id)
    if vendor is None:
        not_found("vendors", ERR_VENDOR_NOT_FOUND)
    limit, offset = parse_pagination(request.args)
    items = [
        f for f in store["tracker_findings"].values() if f.get("vendor_id") == id
    ]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f.get("status") == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, total, limit, offset)
