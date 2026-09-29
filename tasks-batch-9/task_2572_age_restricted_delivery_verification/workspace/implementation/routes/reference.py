"""Clock control, jurisdictions, restriction policies and products."""
import re

from flask import Blueprint

from db import (
    PRODUCT_RESTRICTION_TYPES,
    RESTRICTION_CLASSES,
    DOCUMENT_TYPES,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    COURIER,
    CUSTOMER,
    PARTNER_MANAGER,
    PLATFORM_ADMIN,
    SECRET_SHOPPER_AUDITOR,
    auth,
    fetch,
)
from response import created, listing, ok, pagination, public
from services.sweep import run_sweep
from util import dec, fmt_dt, parse_date, parse_dt, rhu
import validate as v

bp = Blueprint("reference", __name__)

CODE_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{2,6}$")
DRY_STATUSES = ("WET", "DAMP", "DRY")
PERMISSIBILITIES = ("PERMITTED", "PERMIT_REQUIRED", "PROHIBITED")


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(PLATFORM_ADMIN)
    body = v.body()
    instant, raw = v.req_dt(body, "current_utc")
    if instant < db.clock:
        raise ApiError("ERR_CLOCK_REWIND")
    db.clock = instant
    db.clock_raw = raw
    counts = run_sweep()
    data = {"current_utc": raw}
    data.update(counts)
    return ok(data)


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.post("/jurisdictions")
def create_jurisdiction():
    auth(PLATFORM_ADMIN)
    body = v.body()
    code = v.req_str(body, "code")
    if not CODE_RE.match(code):
        raise ApiError("ERR_VALIDATION", "code must match [A-Z]{2}-[A-Z0-9]{2,6}")
    name = v.req_str(body, "name")
    dry_status = v.req_enum(body, "dry_status", DRY_STATUSES)
    offset = v.req_int(body, "utc_offset_minutes", -720, 840)
    for existing in db.jurisdictions.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "jurisdiction code is already in use")
    row = new_row(
        code=code,
        name=name,
        dry_status=dry_status,
        utc_offset_minutes=offset,
        active_policy_count=0,
    )
    db.jurisdictions[row["id"]] = row
    return created(public(row))


@bp.get("/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    auth(*(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER, COURIER,
           SECRET_SHOPPER_AUDITOR))
    return ok(public(fetch("jurisdictions", jurisdiction_id)))


@bp.get("/jurisdictions")
def list_jurisdictions():
    auth(*(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER, COURIER,
           SECRET_SHOPPER_AUDITOR))
    dry_status = v.enum_filter("dry_status", DRY_STATUSES)
    code = v.str_filter("code")
    limit, offset = pagination()
    rows = list(db.jurisdictions.values())
    if dry_status is not None:
        rows = [r for r in rows if r["dry_status"] == dry_status]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# Restriction policies
# ---------------------------------------------------------------------------
@bp.post("/restriction-policies")
def create_policy():
    auth(PLATFORM_ADMIN)
    body = v.body()
    jurisdiction_id = body.get("jurisdiction_id")
    if not isinstance(jurisdiction_id, str) or jurisdiction_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "jurisdiction_id is required")
    jurisdiction = fetch("jurisdictions", jurisdiction_id)

    restriction_type = v.req_enum(body, "restriction_type", RESTRICTION_CLASSES)
    permissibility = v.req_enum(body, "permissibility", PERMISSIBILITIES)
    min_age_years = v.req_int(body, "min_age_years", 18, 25)
    start_minute = v.req_int(body, "delivery_window_start_minute", 0, 1439)
    end_minute = v.req_int(body, "delivery_window_end_minute", 0, 1440)
    unit_scale_factor = v.req_dec(body, "unit_scale_factor", minimum="0.01", maximum="5.00")
    max_units_per_order = v.req_dec(body, "max_units_per_order", exclusive_min="0")
    rolling_window_days = v.req_int(body, "rolling_window_days", 1, 365)
    max_units_per_window = v.req_dec(body, "max_units_per_window", exclusive_min="0")
    acceptable_document_types = body.get("acceptable_document_types")
    if not isinstance(acceptable_document_types, list):
        raise ApiError("ERR_VALIDATION", "acceptable_document_types must be an array")
    for item in acceptable_document_types:
        if not isinstance(item, str) or item not in DOCUMENT_TYPES:
            raise ApiError("ERR_VALIDATION", "acceptable_document_types entries must be document types")
    requires_scan = v.req_bool(body, "requires_scan")
    effective_from = v.req_date(body, "effective_from")
    effective_to = v.req_date(body, "effective_to")

    # tier 8 -- cross-field semantics inside one body
    if effective_to < effective_from:
        raise ApiError("ERR_INCONSISTENT_FIELDS", "effective_to precedes effective_from")
    if start_minute == end_minute:
        raise ApiError("ERR_INCONSISTENT_FIELDS", "the delivery window would be degenerate")

    # tier 18 -- closed-closed interval occupation
    for existing in db.policies.values():
        if existing["jurisdiction_id"] != jurisdiction_id:
            continue
        if existing["restriction_type"] != restriction_type:
            continue
        other_from = parse_date(existing["effective_from"])
        other_to = parse_date(existing["effective_to"])
        if effective_from <= other_to and other_from <= effective_to:
            raise ApiError("ERR_POLICY_PERIOD_OVERLAP")

    row = new_row(
        jurisdiction_id=jurisdiction_id,
        restriction_type=restriction_type,
        permissibility=permissibility,
        min_age_years=min_age_years,
        delivery_window_start_minute=start_minute,
        delivery_window_end_minute=end_minute,
        unit_scale_factor=rhu(unit_scale_factor, 2),
        max_units_per_order=rhu(max_units_per_order, 2),
        rolling_window_days=rolling_window_days,
        max_units_per_window=rhu(max_units_per_window, 2),
        acceptable_document_types=list(acceptable_document_types),
        requires_scan=requires_scan,
        effective_from=effective_from.isoformat(),
        effective_to=effective_to.isoformat(),
    )
    db.policies[row["id"]] = row
    jurisdiction["active_policy_count"] = sum(
        1 for p in db.policies.values() if p["jurisdiction_id"] == jurisdiction_id
    )
    touch(jurisdiction)
    return created(public(row))


@bp.get("/restriction-policies/<policy_id>")
def get_policy(policy_id):
    auth(*(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER, COURIER,
           SECRET_SHOPPER_AUDITOR))
    return ok(public(fetch("policies", policy_id)))


@bp.get("/jurisdictions/<jurisdiction_id>/restriction-policies")
def list_jurisdiction_policies(jurisdiction_id):
    auth(*(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER, COURIER,
           SECRET_SHOPPER_AUDITOR))
    fetch("jurisdictions", jurisdiction_id)
    restriction_type = v.enum_filter("restriction_type", RESTRICTION_CLASSES)
    limit, offset = pagination()
    rows = [p for p in db.policies.values() if p["jurisdiction_id"] == jurisdiction_id]
    if restriction_type is not None:
        rows = [p for p in rows if p["restriction_type"] == restriction_type]
    # The single declared exception to created_at ordering: effective_from ASC first.
    rows.sort(key=lambda p: (p["effective_from"], p["created_at"], p["_seq"]))
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@bp.post("/products")
def create_product():
    auth(PLATFORM_ADMIN)
    body = v.body()
    sku = v.req_str(body, "sku")
    name = v.req_str(body, "name")
    restriction_type = v.req_enum(body, "restriction_type", PRODUCT_RESTRICTION_TYPES)
    units = v.req_dec(body, "restricted_units_per_item", minimum="0")
    list_price_cents = v.req_int(body, "list_price_cents", 1)
    if restriction_type == "NONE" and units != dec("0"):
        raise ApiError("ERR_VALIDATION", "a NONE product must carry restricted_units_per_item of 0")
    for existing in db.products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_CODE", "sku is already in use")
    row = new_row(
        sku=sku,
        name=name,
        restriction_type=restriction_type,
        restricted_units_per_item=rhu(units, 2),
        list_price_cents=list_price_cents,
    )
    db.products[row["id"]] = row
    return created(public(row))


@bp.get("/products/<product_id>")
def get_product(product_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, CUSTOMER)
    return ok(public(fetch("products", product_id)))


@bp.get("/products")
def list_products():
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, CUSTOMER)
    restriction_type = v.enum_filter("restriction_type", PRODUCT_RESTRICTION_TYPES)
    sku = v.str_filter("sku")
    limit, offset = pagination()
    rows = list(db.products.values())
    if restriction_type is not None:
        rows = [r for r in rows if r["restriction_type"] == restriction_type]
    if sku is not None:
        rows = [r for r in rows if r["sku"] == sku]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)
