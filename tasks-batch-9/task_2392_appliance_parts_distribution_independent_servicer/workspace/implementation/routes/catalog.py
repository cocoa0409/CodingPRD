"""Branches, parts, model-part cross-references, pricing tiers, logical clock."""

from db import db, base_row, fmt, now, touch
from errors import ApiError
from flask import Blueprint
from middleware import authenticate
from response import created, ok, ok_list
from services import calc, flows, serialize
from validation import (parse_body, pagination, q_bool, q_int, q_str)

bp = Blueprint("catalog", __name__)

ALL_ROLES = ("PlatformAdmin", "CreditManager", "PricingAdmin", "WarrantyAdmin",
             "BranchCounterRep", "Servicer")
CATALOG_WRITERS = ("PricingAdmin", "PlatformAdmin")

CATEGORIES = {"ELECTRICAL", "MECHANICAL", "COSMETIC", "SEALED_SYSTEM"}
LIFECYCLES = {"ACTIVE", "SUPERSEDED", "OBSOLETE", "NLA"}
BRANCH_STATUSES = {"OPEN", "COUNT_FREEZE", "CLOSED"}
XREF_SOURCES = {"OEM_PUBLICATION", "MANUAL_ENTRY"}


# --------------------------------------------------------------------------
# branches
# --------------------------------------------------------------------------

@bp.post("/branches")
def create_branch():
    authenticate(("PlatformAdmin",))
    body = parse_body([
        ("code", "str", True),
        ("name", "str", True),
        ("region_code", "str", True),
        ("will_call_enabled", "bool", False),
        ("cutoff_hour_utc", "hour", False),
        ("overnight_surcharge_cents", "money", False),
    ])
    row = base_row()
    row.update({
        "code": body["code"],
        "name": body["name"],
        "region_code": body["region_code"],
        "will_call_enabled": body.get("will_call_enabled", True),
        "cutoff_hour_utc": body.get("cutoff_hour_utc", 20),
        "overnight_surcharge_cents": body.get("overnight_surcharge_cents", 0),
        "branch_status": "OPEN",
    })
    db.branches[row["id"]] = row
    return created(serialize.branch(row))


@bp.patch("/branches/<branch_id>")
def patch_branch(branch_id):
    authenticate(("PlatformAdmin",))
    body = parse_body([
        ("name", "str", False),
        ("will_call_enabled", "bool", False),
        ("cutoff_hour_utc", "hour", False),
        ("overnight_surcharge_cents", "money", False),
        ("branch_status", "enum", False, BRANCH_STATUSES),
    ])
    branch = flows.branch_or_404(branch_id)
    for field in ("name", "will_call_enabled", "cutoff_hour_utc",
                  "overnight_surcharge_cents", "branch_status"):
        if field in body:
            branch[field] = body[field]
    touch(branch)
    return ok(serialize.branch(branch))


@bp.get("/branches")
def list_branches():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    region = q_str("region_code")
    status = q_str("branch_status")
    rows = flows.rows_sorted(db.branches)
    rows.reverse()  # newest first
    if region is not None:
        rows = [r for r in rows if r["region_code"] == region]
    if status is not None:
        rows = [r for r in rows if r["branch_status"] == status]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.branch(r) for r in page], limit, offset, total)


@bp.get("/branches/<branch_id>")
def get_branch(branch_id):
    authenticate(ALL_ROLES)
    return ok(serialize.branch(flows.branch_or_404(branch_id)))


# --------------------------------------------------------------------------
# parts
# --------------------------------------------------------------------------

@bp.post("/parts")
def create_part():
    authenticate(CATALOG_WRITERS)
    body = parse_body([
        ("part_number", "str", True),
        ("oem_code", "str", True),
        ("description", "str", True),
        ("category", "enum", True, CATEGORIES),
        ("list_price_cents", "posint", True),
        ("weight_grams", "posint", True),
        ("lifecycle_status", "enum", False, LIFECYCLES),
        ("core_required", "bool", False),
        ("core_deposit_cents", "money", False),
    ])
    for existing in db.parts.values():
        if existing["part_number"] == body["part_number"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "part_number %s already exists" % body["part_number"])
    row = base_row()
    row.update({
        "part_number": body["part_number"],
        "oem_code": body["oem_code"],
        "description": body["description"],
        "category": body["category"],
        "lifecycle_status": body.get("lifecycle_status", "ACTIVE"),
        "superseded_by_part_id": None,
        "list_price_cents": body["list_price_cents"],
        "core_required": body.get("core_required", False),
        "core_deposit_cents": body.get("core_deposit_cents", 0),
        "weight_grams": body["weight_grams"],
    })
    db.parts[row["id"]] = row
    return created(serialize.part(row))


@bp.post("/parts/<part_id>/supersession")
def set_supersession(part_id):
    authenticate(CATALOG_WRITERS)
    body = parse_body([
        ("superseded_by_part_id", "str", True),
        ("expected_part_version", "signed", True),
    ])
    part = flows.part_or_404(part_id)
    target = flows.part_or_404(body["superseded_by_part_id"])
    if part["version"] != body["expected_part_version"]:
        raise ApiError("ERR_STALE_PART_VERSION",
                       "Part version is %d, not %d"
                       % (part["version"], body["expected_part_version"]))
    if target["id"] == part["id"]:
        raise ApiError("ERR_SUPERSESSION_TARGET_INVALID",
                       "A part cannot supersede itself")
    if target.get("superseded_by_part_id") == part["id"]:
        raise ApiError("ERR_SUPERSESSION_TARGET_INVALID",
                       "The target already points back at this part")
    if target["oem_code"] != part["oem_code"]:
        raise ApiError("ERR_SUPERSESSION_TARGET_INVALID",
                       "Supersession target must share the same oem_code")
    part["lifecycle_status"] = "SUPERSEDED"
    part["superseded_by_part_id"] = target["id"]
    touch(part)
    return ok(serialize.part(part))


@bp.get("/parts")
def list_parts():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.parts)
    for field in ("part_number", "oem_code", "category", "lifecycle_status",
                  "superseded_by_part_id"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    core_required = q_bool("core_required")
    if core_required is not None:
        rows = [r for r in rows if r["core_required"] == core_required]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.part(r) for r in page], limit, offset, total)


@bp.get("/parts/<part_id>")
def get_part(part_id):
    authenticate(ALL_ROLES)
    return ok(serialize.part(flows.part_or_404(part_id)))


# --------------------------------------------------------------------------
# model-part cross references
# --------------------------------------------------------------------------

@bp.post("/model-part-xrefs")
def create_xref():
    authenticate(CATALOG_WRITERS)
    body = parse_body([
        ("model_number", "str", True),
        ("part_id", "str", True),
        ("position_code", "str", True),
        ("xref_source", "enum", True, XREF_SOURCES),
    ])
    flows.part_or_404(body["part_id"])
    for existing in db.model_part_xrefs.values():
        if existing["model_number"] == body["model_number"] \
                and existing["part_id"] == body["part_id"] \
                and existing["position_code"] == body["position_code"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "This model/part/position cross-reference already exists")
    row = base_row(versioned=False)
    row.update({
        "model_number": body["model_number"],
        "part_id": body["part_id"],
        "position_code": body["position_code"],
        "xref_source": body["xref_source"],
    })
    db.model_part_xrefs[row["id"]] = row
    return created(serialize.model_part_xref(row))


@bp.get("/model-part-xrefs")
def list_xrefs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.model_part_xrefs)
    for field in ("model_number", "part_id", "xref_source"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.model_part_xref(r) for r in page], limit, offset, total)


@bp.get("/model-part-xrefs/<xref_id>")
def get_xref(xref_id):
    authenticate(ALL_ROLES)
    row = flows.find(db.model_part_xrefs, xref_id, "ERR_MODEL_PART_XREF_NOT_FOUND")
    return ok(serialize.model_part_xref(row))


# --------------------------------------------------------------------------
# pricing tiers
# --------------------------------------------------------------------------

@bp.post("/pricing-tiers")
def create_tier():
    authenticate(CATALOG_WRITERS)
    body = parse_body([
        ("tier_code", "str", True),
        ("name", "str", True),
        ("discount_pct_electrical", "pct45", True),
        ("discount_pct_mechanical", "pct45", True),
        ("discount_pct_cosmetic", "pct45", True),
        ("discount_pct_sealed_system", "pct45", True),
        ("min_annual_volume_cents", "money", True),
    ])
    for existing in db.pricing_tiers.values():
        if existing["tier_code"] == body["tier_code"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "tier_code %s already exists" % body["tier_code"])
    row = base_row()
    row.update({
        "tier_code": body["tier_code"],
        "name": body["name"],
        "discount_pct_electrical": body["discount_pct_electrical"],
        "discount_pct_mechanical": body["discount_pct_mechanical"],
        "discount_pct_cosmetic": body["discount_pct_cosmetic"],
        "discount_pct_sealed_system": body["discount_pct_sealed_system"],
        "min_annual_volume_cents": body["min_annual_volume_cents"],
    })
    db.pricing_tiers[row["id"]] = row
    return created(serialize.pricing_tier(row))


@bp.get("/pricing-tiers")
def list_tiers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted(db.pricing_tiers.values(),
                  key=lambda r: (r["tier_code"], r["_seq"]))
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.pricing_tier(r) for r in page], limit, offset, total)


@bp.get("/pricing-tiers/<tier_id>")
def get_tier(tier_id):
    authenticate(ALL_ROLES)
    return ok(serialize.pricing_tier(flows.tier_or_404(tier_id)))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = parse_body([("current_utc", "dt", True)])
    db.clock = body["current_utc"]
    return ok({"current_utc": fmt(db.clock)})
