"""WarrantyClaim endpoints: filing (term window + duplicate + coverage cap),
get/list, review, approve (coverage variant computation), deny, appeal,
order-parts."""
import uuid

from flask import Blueprint, request

from db import clock_date, new_record, public, store, touch
from errors import (
    ERR_CLAIM_EXCEEDS_COVERAGE,
    ERR_DUPLICATE_CLAIM,
    ERR_INVALID_STATE,
    ERR_LINE_NOT_VERIFIED,
    ERR_WARRANTY_EXPIRED,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from services.cascade import award_of_line, district_id_of_line, po_of_line
from services.pricing import warranty_coverage, warranty_term_end
from validation import (
    body,
    get_or_404,
    paginate,
    parse_pagination,
    pdate,
    req_int,
    req_str,
)

bp = Blueprint("warranty_claims", __name__)

ACTIVE_CLAIM_STATUSES = ("FILED", "UNDER_REVIEW", "APPEALED", "APPROVED")


@bp.route("/v1/warranty-claims", methods=["POST"])
def create_warranty_claim():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    po_line_id = data.get("po_line_id")
    line = store.po_lines.get(po_line_id) if isinstance(po_line_id, str) else None
    # priority 3: ownership scope via the line's district chain
    if line is not None:
        scope_district(caller, district_id_of_line(line))
    # priority 4: body FK existence
    if isinstance(po_line_id, str):
        get_or_404(store.po_lines, po_line_id, "PO line")

    # priority 5: shape
    po_line_id = req_str(data, "po_line_id")
    parts_cost_cents = req_int(data, "parts_cost_cents", minimum=1)
    description = req_str(data, "description")

    # priority 7: warranty filing requires a VERIFIED line
    if line["status"] != "VERIFIED":
        raise_err(ERR_LINE_NOT_VERIFIED, "Warranty claim requires the PO line to be VERIFIED")

    award = award_of_line(line)
    district = store.districts.get(district_id_of_line(line))
    installed_date = pdate(line["installed_at"][:10])

    # priority 8: filing must fall within the applicable term (inclusive)
    term_end = warranty_term_end(award, district, installed_date)
    if clock_date() > term_end:
        raise_err(ERR_WARRANTY_EXPIRED, "Claim filing date is beyond the applicable warranty term")

    # priority 14: no second claim while one is active
    for other in store.warranty_claims.values():
        if other["po_line_id"] == po_line_id and other["status"] in ACTIVE_CLAIM_STATUSES:
            raise_err(ERR_DUPLICATE_CLAIM, "The line already has an active warranty claim")

    # priority 14: claimed cost may not exceed the installed value of the line
    installed_qty = line.get("_installed_qty") or line["delivered_qty"]
    if parts_cost_cents > installed_qty * line["computed_unit_price_cents"]:
        raise_err(ERR_CLAIM_EXCEEDS_COVERAGE, "parts_cost_cents exceeds installed_qty * computed_unit_price_cents")

    rec = new_record({
        "po_line_id": po_line_id,
        "parts_cost_cents": parts_cost_cents,
        "description": description,
        "status": "FILED",
        "filed_date": clock_date().isoformat(),
        "coverage_cents": None,
        "appeal_count": 0,
        "denial_reason": None,
        "parts_order_ref": None,
    })
    store.warranty_claims[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/warranty-claims/<rid>", methods=["GET"])
def get_warranty_claim(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.warranty_claims, rid, "warranty claim")
    return success(public(rec), code=200)


@bp.route("/v1/warranty-claims", methods=["GET"])
def list_warranty_claims():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.warranty_claims.values())
    po_line_id = request.args.get("po_line_id")
    status = request.args.get("status")
    if po_line_id is not None:
        records = [r for r in records if r["po_line_id"] == po_line_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/warranty-claims/<rid>/review", methods=["POST"])
def review_claim(rid):
    caller = authenticate()
    require_roles(caller, ["ServiceAgent"])
    claim = get_or_404(store.warranty_claims, rid, "warranty claim")
    body()

    if claim["status"] not in ("FILED", "APPEALED"):
        raise_err(ERR_INVALID_STATE, f"Cannot review a claim in status {claim['status']}")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success(public(claim), code=200)


@bp.route("/v1/warranty-claims/<rid>/approve", methods=["POST"])
def approve_claim(rid):
    caller = authenticate()
    require_roles(caller, ["ServiceAgent"])
    claim = get_or_404(store.warranty_claims, rid, "warranty claim")
    body()

    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Cannot approve a claim in status {claim['status']}")

    line = store.po_lines.get(claim["po_line_id"])
    award = award_of_line(line)
    district = store.districts.get(district_id_of_line(line))
    claim["coverage_cents"] = warranty_coverage(claim, line, award, district)
    claim["status"] = "APPROVED"
    touch(claim)
    return success(public(claim), code=200)


@bp.route("/v1/warranty-claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    caller = authenticate()
    require_roles(caller, ["ServiceAgent"])
    claim = get_or_404(store.warranty_claims, rid, "warranty claim")
    data = body()
    denial_reason = req_str(data, "denial_reason")

    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Cannot deny a claim in status {claim['status']}")
    claim["denial_reason"] = denial_reason
    claim["status"] = "DENIED"
    touch(claim)
    return success(public(claim), code=200)


@bp.route("/v1/warranty-claims/<rid>/appeal", methods=["POST"])
def appeal_claim(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    claim = store.warranty_claims.get(rid)
    if claim is not None:
        line = store.po_lines.get(claim["po_line_id"])
        if line is not None:
            scope_district(caller, district_id_of_line(line))  # priority 3
    claim = get_or_404(store.warranty_claims, rid, "warranty claim")  # priority 4
    data = body()
    req_str(data, "appeal_note")

    if claim["status"] != "DENIED":
        raise_err(ERR_INVALID_STATE, f"Cannot appeal a claim in status {claim['status']}")
    if claim["appeal_count"] != 0:
        raise_err(ERR_INVALID_STATE, "At most one appeal is permitted per claim")

    claim["status"] = "APPEALED"
    claim["appeal_count"] = 1
    touch(claim)
    return success(public(claim), code=200)


@bp.route("/v1/warranty-claims/<rid>/order-parts", methods=["POST"])
def order_parts(rid):
    caller = authenticate()
    require_roles(caller, ["ServiceAgent"])
    claim = get_or_404(store.warranty_claims, rid, "warranty claim")
    body()

    if claim["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, f"Cannot order parts for a claim in status {claim['status']}")
    claim["status"] = "CLOSED"
    claim["parts_order_ref"] = "parts_" + uuid.uuid4().hex[:16]
    touch(claim)
    return success(public(claim), code=200)
