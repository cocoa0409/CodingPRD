"""Logical clock, tax jurisdictions, revenue-share tiers."""
from flask import Blueprint

from core import (
    authenticate,
    db,
    fail,
    filter_eq,
    get_body,
    iso,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    parse_iso,
    public,
    req_bool,
    req_int,
    req_str,
)
from services import jurisdiction_for, lookup

bp = Blueprint("config_routes", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 string.")
    parsed = parse_iso(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be a valid ISO 8601 instant.")
    db.clock = parsed
    return ok({"current_utc": iso(db.clock)})


# ---- tax jurisdictions ---------------------------------------------------
@bp.post("/api/tax-jurisdictions")
def create_jurisdiction():
    authenticate({"PlatformAdmin"})
    body = get_body()
    country_code = req_str(body, "country_code")
    vat_rate_bps = req_int(body, "vat_rate_bps", minimum=0)
    if vat_rate_bps > 3000:
        fail("ERR_INVALID_REQUEST", "vat_rate_bps must be between 0 and 3000.")
    marketplace_facilitator = req_bool(body, "marketplace_facilitator")
    if jurisdiction_for(country_code) is not None:
        fail("ERR_JURISDICTION_EXISTS", "A jurisdiction already exists for this country_code.")
    rec = new_record(
        versioned=False,
        country_code=country_code,
        vat_rate_bps=vat_rate_bps,
        marketplace_facilitator=marketplace_facilitator,
    )
    db.tax_jurisdictions[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/tax-jurisdictions")
def list_jurisdictions():
    authenticate({"PlatformAdmin", "FinanceOps", "StorefrontService"})
    limit, offset = pagination()
    rows = filter_eq(ordered(db.tax_jurisdictions), "country_code")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/tax-jurisdictions/<tax_jurisdiction_id>")
def read_jurisdiction(tax_jurisdiction_id):
    authenticate({"PlatformAdmin", "FinanceOps", "StorefrontService"})
    rec = lookup("tax_jurisdictions", tax_jurisdiction_id)
    return ok(public(rec))


# ---- revenue share tiers -------------------------------------------------
@bp.post("/api/revenue-share-tiers")
def create_tier():
    authenticate({"PlatformAdmin"})
    body = get_body()
    label = req_str(body, "label")
    min_cumulative_base_cents = req_int(body, "min_cumulative_base_cents", minimum=0)
    developer_share_bps = req_int(body, "developer_share_bps", minimum=1)
    if developer_share_bps > 10000:
        fail("ERR_INVALID_REQUEST", "developer_share_bps must be <= 10000.")
    rec = new_record(
        versioned=False,
        label=label,
        min_cumulative_base_cents=min_cumulative_base_cents,
        developer_share_bps=developer_share_bps,
    )
    db.revenue_share_tiers[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/revenue-share-tiers")
def list_tiers():
    authenticate({"PlatformAdmin", "FinanceOps", "Developer"})
    limit, offset = pagination()
    items, total = paginate(ordered(db.revenue_share_tiers), limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/revenue-share-tiers/<revenue_share_tier_id>")
def read_tier(revenue_share_tier_id):
    authenticate({"PlatformAdmin", "FinanceOps", "Developer"})
    rec = lookup("revenue_share_tiers", revenue_share_tier_id)
    return ok(public(rec))
