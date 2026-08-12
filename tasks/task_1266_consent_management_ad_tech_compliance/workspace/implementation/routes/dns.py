"""Do-not-sell/share request and vendor propagation routes."""
from flask import Blueprint, request

from db import store, new_id, now_iso, touch
from errors import ApiError
from response import ok, ok_list
from services.consent import (
    SCOPE_CATEGORIES,
    check_role,
    check_read_role,
    check_ownership,
    pagination_args,
    sort_created,
    get_visitor_or_404,
)
from services.dns import (
    in_scope_vendors,
    has_open_propagation,
    request_children,
    recompute_request_counters,
)

bp = Blueprint("dns", __name__)
blueprint = bp


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _get_request_or_404(request_id):
    req = store["dns_requests"].get(request_id)
    if req is None:
        raise ApiError("ERR_DNS_REQUEST_NOT_FOUND", "DoNotSellRequest not found", 404)
    return req


def _get_propagation_or_404(propagation_id):
    prop = store["vendor_propagations"].get(propagation_id)
    if prop is None:
        raise ApiError("ERR_PROPAGATION_NOT_FOUND", "VendorPropagation not found", 404)
    return prop


# ---------------------------------------------------------------------------
# POST /v1/visitors/{id}/do-not-sell-requests — Visitor, ownership
# ---------------------------------------------------------------------------


@bp.post("/v1/visitors/<visitor_id>/do-not-sell-requests")
def create_dns_request(visitor_id):
    check_role("Visitor")
    check_ownership(visitor_id)
    visitor = get_visitor_or_404(visitor_id)
    body = _body()
    scope = body.get("scope_categories", ["SALE_SHARE"])
    if not isinstance(scope, list) or any(
        (not isinstance(c, str)) or c not in SCOPE_CATEGORIES for c in scope
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scope_categories must be a list of ANALYTICS, ADVERTISING, SALE_SHARE",
            400,
        )
    prop = store["properties"].get(visitor.get("property_id"))
    if prop is not None and prop.get("sale_share_designation") == "NO_SALE_NO_SHARE":
        raise ApiError(
            "ERR_DNS_NOT_APPLICABLE",
            "Property designation NO_SALE_NO_SHARE makes do-not-sell requests inapplicable",
            409,
        )
    now = now_iso()
    req = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "visitor_id": visitor_id,
        "property_id": visitor.get("property_id"),
        "scope_categories": list(scope),
        "verification_status": "UNVERIFIED",
        "propagation_status": "NOT_STARTED",
        "total_propagations": 0,
        "pending_count": 0,
        "confirmed_count": 0,
        "failed_count": 0,
    }
    store["dns_requests"][req["id"]] = req
    return ok(req, status=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@bp.get("/v1/visitors/<visitor_id>/do-not-sell-requests")
def list_visitor_dns_requests(visitor_id):
    check_read_role()
    get_visitor_or_404(visitor_id)
    limit, offset = pagination_args()
    items = [
        r for r in store["dns_requests"].values() if r.get("visitor_id") == visitor_id
    ]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/do-not-sell-requests")
def list_dns_requests():
    check_read_role()
    limit, offset = pagination_args()
    items = list(store["dns_requests"].values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [r for r in items if r.get("property_id") == property_id]
    verification = request.args.get("verification_status")
    if verification is not None:
        items = [r for r in items if r.get("verification_status") == verification]
    propagation = request.args.get("propagation_status")
    if propagation is not None:
        items = [r for r in items if r.get("propagation_status") == propagation]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/do-not-sell-requests/<request_id>")
def get_dns_request(request_id):
    check_read_role()
    return ok(_get_request_or_404(request_id))


# ---------------------------------------------------------------------------
# PUT /v1/do-not-sell-requests/{id} — verify or reject (PrivacyAdmin)
# ---------------------------------------------------------------------------


@bp.put("/v1/do-not-sell-requests/<request_id>")
def settle_dns_request(request_id):
    check_role("PrivacyAdmin")
    req = _get_request_or_404(request_id)
    body = _body()
    verification = body.get("verification_status")
    if verification not in ("VERIFIED", "REJECTED"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "verification_status must be VERIFIED or REJECTED",
            400,
        )
    if req.get("verification_status") != "UNVERIFIED":
        raise ApiError(
            "ERR_DNS_INVALID_STATE",
            "Verify/reject requires the request to be UNVERIFIED",
            409,
        )
    req["verification_status"] = verification
    touch(req)
    return ok(req)


# ---------------------------------------------------------------------------
# POST /v1/do-not-sell-requests/{id}/propagate — dispatch (PrivacyAdmin)
# ---------------------------------------------------------------------------


@bp.post("/v1/do-not-sell-requests/<request_id>/propagate")
def propagate_dns_request(request_id):
    check_role("PrivacyAdmin")
    req = _get_request_or_404(request_id)
    if req.get("verification_status") != "VERIFIED" or req.get(
        "propagation_status"
    ) not in ("NOT_STARTED", "PARTIAL_FAILURE"):
        raise ApiError(
            "ERR_DNS_INVALID_STATE",
            "Propagate requires VERIFIED with propagation NOT_STARTED or PARTIAL_FAILURE",
            409,
        )
    now = now_iso()
    for vendor in in_scope_vendors(req):
        # re-dispatch skips vendors already holding PENDING/CONFIRMED
        if has_open_propagation(req["id"], vendor["id"]):
            continue
        propagation = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "request_id": req["id"],
            "vendor_id": vendor["id"],
            "status": "PENDING",
            "attempts": 1,
            "last_attempt_at": now,
        }
        store["vendor_propagations"][propagation["id"]] = propagation
    # zero in-scope vendors settles straight to ALL_CONFIRMED with total 0
    recompute_request_counters(req)
    touch(req)
    return ok(req)


# ---------------------------------------------------------------------------
# Propagation reads
# ---------------------------------------------------------------------------


@bp.get("/v1/do-not-sell-requests/<request_id>/propagations")
def list_request_propagations(request_id):
    check_read_role()
    _get_request_or_404(request_id)
    limit, offset = pagination_args()
    items = request_children(request_id)
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/vendor-propagations")
def list_vendor_propagations():
    check_read_role()
    limit, offset = pagination_args()
    items = list(store["vendor_propagations"].values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [p for p in items if p.get("vendor_id") == vendor_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/vendor-propagations/<propagation_id>")
def get_vendor_propagation(propagation_id):
    check_read_role()
    return ok(_get_propagation_or_404(propagation_id))


# ---------------------------------------------------------------------------
# PUT /v1/vendor-propagations/{id} — confirm / fail / retry (VendorManager)
# ---------------------------------------------------------------------------


@bp.put("/v1/vendor-propagations/<propagation_id>")
def settle_vendor_propagation(propagation_id):
    check_role("VendorManager")
    propagation = _get_propagation_or_404(propagation_id)
    body = _body()
    new_status = body.get("status")
    if new_status not in ("PENDING", "CONFIRMED", "FAILED"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "status must be one of PENDING, CONFIRMED, FAILED",
            400,
        )
    current = propagation.get("status")
    if current == "PENDING" and new_status in ("CONFIRMED", "FAILED"):
        pass
    elif current == "FAILED" and new_status == "PENDING":
        # retry: attempts += 1, last_attempt_at re-stamped
        propagation["attempts"] = int(propagation.get("attempts", 0)) + 1
    else:
        raise ApiError(
            "ERR_PROPAGATION_INVALID_STATE",
            "CONFIRMED/FAILED require PENDING; retry requires FAILED",
            409,
        )
    propagation["status"] = new_status
    propagation["last_attempt_at"] = now_iso()
    touch(propagation)
    req = store["dns_requests"].get(propagation.get("request_id"))
    if req is not None:
        recompute_request_counters(req)
        touch(req)
    return ok(propagation)
