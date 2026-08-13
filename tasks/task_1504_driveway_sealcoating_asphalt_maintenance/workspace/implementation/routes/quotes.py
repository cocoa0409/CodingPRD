"""Quote endpoints: create (OCC + supersede), PATCH, send, accept, decline, request-revision."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

from clock import now_iso_ms, format_iso_ms, now, today_date
from db import DB
from middleware import (
    require_role, get_json_body, check_unknown_fields, require_fields,
    require_enum, require_number, require_bool, base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_QUOTE_NOT_FOUND, ERR_PROPERTY_NOT_FOUND, ERR_ASSESSMENT_NOT_FOUND,
    ERR_MATERIAL_NOT_FOUND, ERR_ASSESSMENT_PROPERTY_MISMATCH,
    ERR_STRIPING_COMMERCIAL_ONLY, ERR_INVALID_REQUEST,
    ERR_QUOTE_NOT_EDITABLE, ERR_QUOTE_NOT_SENDABLE, ERR_QUOTE_NOT_ACCEPTABLE,
    ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION, ERR_QUOTE_EXPIRED,
)
from services import (
    quote_pricing, check_assessment_usable_for_quote, check_quote_not_expired,
    find_open_quote_for_property, lazy_quote_expiry,
)

bp = Blueprint("quotes", __name__)


def serialize_quote(q):
    return {
        "id": q["id"],
        "property_id": q["property_id"],
        "assessment_id": q["assessment_id"],
        "material_id": q["material_id"],
        "include_crack_fill": q["include_crack_fill"],
        "include_patch": q["include_patch"],
        "include_seal": q["include_seal"],
        "include_striping": q["include_striping"],
        "coats": q["coats"],
        "stripe_linear_ft": q["stripe_linear_ft"],
        "discount_pct": q["discount_pct"],
        "area_sqft_snapshot": q["area_sqft_snapshot"],
        "crack_ft_snapshot": q["crack_ft_snapshot"],
        "pothole_area_snapshot": q["pothole_area_snapshot"],
        "seal_line_cents": q["seal_line_cents"],
        "crack_line_cents": q["crack_line_cents"],
        "patch_line_cents": q["patch_line_cents"],
        "striping_line_cents": q["striping_line_cents"],
        "subtotal_cents": q["subtotal_cents"],
        "discount_cents": q["discount_cents"],
        "mobilization_fee_cents": q["mobilization_fee_cents"],
        "total_cents": q["total_cents"],
        "sent_at": q["sent_at"],
        "expires_on": q["expires_on"],
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def _validate_discount(body):
    d = body.get("discount_pct", 0)
    if d is None:
        d = 0
    if not isinstance(d, (int, float)) or isinstance(d, bool):
        raise err(ERR_INVALID_REQUEST, 400, "discount_pct must be a number")
    if d < 0 or d > 0.30:
        raise err(ERR_INVALID_REQUEST, 400, "discount_pct must be within 0..0.30")
    return d


def _compute_and_apply_pricing(q, material):
    """Compute pricing fields from q's current scope + snapshot fields."""
    result = quote_pricing(
        area=q["area_sqft_snapshot"],
        crack_ft=q["crack_ft_snapshot"],
        pothole_area=q["pothole_area_snapshot"],
        stripe_ft=q["stripe_linear_ft"] if q["stripe_linear_ft"] is not None else 0,
        include_seal=q["include_seal"],
        include_crack_fill=q["include_crack_fill"],
        include_patch=q["include_patch"],
        include_striping=q["include_striping"],
        coats=q["coats"],
        grade=material["grade"],
        discount_pct=q["discount_pct"],
        material_coverage=material["coverage_sqft_per_gallon"],
        material_price_per_gallon_cents=material["price_per_gallon_cents"],
    )
    q.update(result)


@bp.post("/api/quotes")
def create_quote():
    require_role("Estimator")
    body = get_json_body()
    allowed = {"property_id", "assessment_id", "material_id", "include_crack_fill",
               "include_patch", "include_seal", "include_striping", "coats",
               "stripe_linear_ft", "discount_pct", "expected_property_version"}
    check_unknown_fields(body, allowed)
    require_fields(body, ["property_id", "assessment_id", "material_id",
                          "include_crack_fill", "include_patch", "include_seal",
                          "include_striping", "expected_property_version"])

    prop = DB.properties.get(body["property_id"])
    if prop is None:
        raise err(ERR_PROPERTY_NOT_FOUND, 404, "Property id does not exist")
    assessment = DB.assessments.get(body["assessment_id"])
    if assessment is None:
        raise err(ERR_ASSESSMENT_NOT_FOUND, 404, "Assessment id does not exist")
    material = DB.materials.get(body["material_id"])
    if material is None:
        raise err(ERR_MATERIAL_NOT_FOUND, 404, "Material id does not exist")

    # State: assessment must belong to same property
    if assessment["property_id"] != body["property_id"]:
        raise err(ERR_ASSESSMENT_PROPERTY_MISMATCH, 422,
                  "assessment_id belongs to a different property than property_id")

    # Assessment usability (SUBMITTED, not EXPIRED)
    check_assessment_usable_for_quote(assessment)

    # Scope flags
    include_crack_fill = require_bool(body, "include_crack_fill")
    include_patch = require_bool(body, "include_patch")
    include_seal = require_bool(body, "include_seal")
    include_striping = require_bool(body, "include_striping")
    coats = body.get("coats", 1)
    if not isinstance(coats, int) or isinstance(coats, bool) or coats not in (1, 2):
        raise err(ERR_INVALID_REQUEST, 400, "coats must be 1 or 2")
    stripe_linear_ft = body.get("stripe_linear_ft")
    if include_striping:
        if prop["lot_kind"] != "COMMERCIAL_LOT":
            raise err(ERR_STRIPING_COMMERCIAL_ONLY, 422,
                      "Striping scope or striping plan on a RESIDENTIAL_DRIVEWAY property")
        if stripe_linear_ft is None:
            raise err(ERR_INVALID_REQUEST, 400, "stripe_linear_ft is required when include_striping is true")
        if not isinstance(stripe_linear_ft, (int, float)) or isinstance(stripe_linear_ft, bool):
            raise err(ERR_INVALID_REQUEST, 400, "stripe_linear_ft must be a number")
    discount_pct = _validate_discount(body)

    # OCC check
    expected_prop_version = body["expected_property_version"]
    if not isinstance(expected_prop_version, int) or isinstance(expected_prop_version, bool):
        raise err(ERR_INVALID_REQUEST, 400, "expected_property_version must be an integer")
    if expected_prop_version != prop["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_property_version does not match the property's current version")

    q = base_fields()
    q.update({
        "property_id": body["property_id"],
        "assessment_id": body["assessment_id"],
        "material_id": body["material_id"],
        "include_crack_fill": include_crack_fill,
        "include_patch": include_patch,
        "include_seal": include_seal,
        "include_striping": include_striping,
        "coats": coats,
        "stripe_linear_ft": stripe_linear_ft,
        "discount_pct": discount_pct,
        "area_sqft_snapshot": assessment["measured_area_sqft"],
        "crack_ft_snapshot": assessment["crack_linear_ft"],
        "pothole_area_snapshot": assessment["pothole_area_sqft"],
        "sent_at": None,
        "expires_on": None,
        "status": "DRAFT",
    })
    _compute_and_apply_pricing(q, material)

    # Supersede prior open quote
    prior = find_open_quote_for_property(prop["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    DB.quotes[q["id"]] = q
    prop["open_quote_id"] = q["id"]
    touch(prop)
    return success_object(serialize_quote(q), status=201)


@bp.get("/api/quotes")
def list_quotes():
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "Customer")
    items = list(DB.quotes.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        items = [q for q in items if q["property_id"] in own_props]
    for f, key in [("property_id", "property_id"), ("assessment_id", "assessment_id"),
                   ("material_id", "material_id"), ("status", "status")]:
        v = request.args.get(f)
        if v:
            items = [q for q in items if q[key] == v]
    items.sort(key=lambda q: q["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_quote(q) for q in page], limit, offset, total)


@bp.get("/api/quotes/<quoteId>")
def get_quote(quoteId):
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "Customer")
    q = DB.quotes.get(quoteId)
    if q is None:
        raise err(ERR_QUOTE_NOT_FOUND, 404, "Quote id does not exist")
    lazy_quote_expiry(q)
    if role == "Customer":
        prop = DB.properties.get(q["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_quote(q))


@bp.patch("/api/quotes/<quoteId>")
def patch_quote(quoteId):
    require_role("Estimator")
    q = DB.quotes.get(quoteId)
    if q is None:
        raise err(ERR_QUOTE_NOT_FOUND, 404, "Quote id does not exist")
    if q["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise err(ERR_QUOTE_NOT_EDITABLE, 409, "PATCH requires quote in DRAFT or REVISION_REQUESTED")
    body = get_json_body()
    allowed = {"include_crack_fill", "include_patch", "include_seal", "include_striping",
               "coats", "material_id", "stripe_linear_ft", "discount_pct"}
    check_unknown_fields(body, allowed)

    # Apply updates
    if "include_crack_fill" in body:
        q["include_crack_fill"] = require_bool(body, "include_crack_fill")
    if "include_patch" in body:
        q["include_patch"] = require_bool(body, "include_patch")
    if "include_seal" in body:
        q["include_seal"] = require_bool(body, "include_seal")
    if "include_striping" in body:
        q["include_striping"] = require_bool(body, "include_striping")
    if "coats" in body:
        coats = body["coats"]
        if not isinstance(coats, int) or isinstance(coats, bool) or coats not in (1, 2):
            raise err(ERR_INVALID_REQUEST, 400, "coats must be 1 or 2")
        q["coats"] = coats
    if "material_id" in body:
        material = DB.materials.get(body["material_id"])
        if material is None:
            raise err(ERR_MATERIAL_NOT_FOUND, 404, "Material id does not exist")
        q["material_id"] = body["material_id"]
    if "stripe_linear_ft" in body:
        slf = body["stripe_linear_ft"]
        if slf is not None and (not isinstance(slf, (int, float)) or isinstance(slf, bool)):
            raise err(ERR_INVALID_REQUEST, 400, "stripe_linear_ft must be a number")
        q["stripe_linear_ft"] = slf
    if "discount_pct" in body:
        q["discount_pct"] = _validate_discount(body)

    # Validate striping rules
    prop = DB.properties.get(q["property_id"])
    if q["include_striping"]:
        if prop["lot_kind"] != "COMMERCIAL_LOT":
            raise err(ERR_STRIPING_COMMERCIAL_ONLY, 422,
                      "Striping scope or striping plan on a RESIDENTIAL_DRIVEWAY property")
        if q["stripe_linear_ft"] is None:
            raise err(ERR_INVALID_REQUEST, 400,
                      "stripe_linear_ft is required when include_striping is true")

    # Recompute pricing with (possibly new) material
    material = DB.materials.get(q["material_id"])
    _compute_and_apply_pricing(q, material)
    # REVISION_REQUESTED -> DRAFT, clear sent/expires
    q["sent_at"] = None
    q["expires_on"] = None
    if q["status"] == "REVISION_REQUESTED":
        q["status"] = "DRAFT"
    touch(q)
    return success_object(serialize_quote(q))


@bp.post("/api/quotes/<quoteId>/send")
def send_quote(quoteId):
    require_role("Estimator")
    q = DB.quotes.get(quoteId)
    if q is None:
        raise err(ERR_QUOTE_NOT_FOUND, 404, "Quote id does not exist")
    if q["status"] != "DRAFT":
        raise err(ERR_QUOTE_NOT_SENDABLE, 409, "send requires quote in DRAFT")
    assessment = DB.assessments.get(q["assessment_id"])
    if assessment is None:
        raise err(ERR_ASSESSMENT_NOT_FOUND, 404, "Assessment id does not exist")
    check_assessment_usable_for_quote(assessment)
    q["status"] = "SENT"
    sent_at = now()
    q["sent_at"] = format_iso_ms(sent_at)
    q["expires_on"] = (sent_at.date() + timedelta(days=14)).strftime("%Y-%m-%d")
    touch(q)
    return success_object(serialize_quote(q))


def _customer_quote_action(quoteId, action):
    """Common path for accept/decline/request-revision."""
    user_id, role = require_role("Customer")
    q = DB.quotes.get(quoteId)
    if q is None:
        raise err(ERR_QUOTE_NOT_FOUND, 404, "Quote id does not exist")
    prop = DB.properties.get(q["property_id"])
    if prop is None or prop["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, 403,
                  "Customer acting on a resource owned by a different customer")
    # State check + lazy expiry
    if q["status"] != "SENT":
        # Check expiry first only if it could be SENT-expired — but the quote is not SENT,
        # so we return NOT_ACCEPTABLE. Per priority ordering, state check fires.
        raise err(ERR_QUOTE_NOT_ACCEPTABLE, 409,
                  "accept/decline/request-revision requires quote in SENT")
    check_quote_not_expired(q)
    return q, prop


@bp.post("/api/quotes/<quoteId>/accept")
def accept_quote(quoteId):
    q, prop = _customer_quote_action(quoteId, "accept")
    # Create WorkOrder
    material = DB.materials.get(q["material_id"])
    wo = base_fields()
    wo.update({
        "property_id": q["property_id"],
        "quote_id": q["id"],
        "warranty_claim_id": None,
        "route_sheet_id": None,
        "material_lot_id": None,
        "include_crack_fill": q["include_crack_fill"],
        "include_patch": q["include_patch"],
        "include_seal": q["include_seal"],
        "include_striping": q["include_striping"],
        "coats": q["coats"],
        "material_grade": material["grade"],
        "quoted_area_sqft": q["area_sqft_snapshot"],
        "quoted_total_cents": q["total_cents"],
        "scheduled_date": None,
        "window_start_hour": None,
        "window_end_hour": None,
        "drive_minutes_est": None,
        "vehicles_to_move": None,
        "reserved_gallons": 0,
        "execution_status": "PENDING",
        "billing_status": "UNINVOICED",
        "striping_status": "PLANNING" if q["include_striping"] else "NOT_REQUIRED",
        "stall_count": None,
        "ada_stalls_required": None,
        "stripe_linear_ft_computed": None,
        "actual_area_sqft": None,
        "actual_crack_ft": None,
        "actual_pothole_area_sqft": None,
        "actual_stripe_ft": None,
        "gallons_used": None,
        "started_at": None,
        "finished_at": None,
        "cure_until": None,
        "completed_at": None,
    })
    DB.work_orders[wo["id"]] = wo

    # Supersede other open quotes on the property
    for other in DB.quotes.values():
        if other["id"] != q["id"] and other["property_id"] == q["property_id"] \
           and other["status"] in ("DRAFT", "SENT", "REVISION_REQUESTED"):
            other["status"] = "SUPERSEDED"
            touch(other)

    q["status"] = "ACCEPTED"
    touch(q)
    prop["open_quote_id"] = None
    touch(prop)
    return success_object(serialize_quote(q))


@bp.post("/api/quotes/<quoteId>/decline")
def decline_quote(quoteId):
    q, prop = _customer_quote_action(quoteId, "decline")
    q["status"] = "DECLINED"
    touch(q)
    prop["open_quote_id"] = None
    touch(prop)
    return success_object(serialize_quote(q))


@bp.post("/api/quotes/<quoteId>/request-revision")
def request_revision_quote(quoteId):
    q, prop = _customer_quote_action(quoteId, "request-revision")
    q["status"] = "REVISION_REQUESTED"
    touch(q)
    return success_object(serialize_quote(q))
