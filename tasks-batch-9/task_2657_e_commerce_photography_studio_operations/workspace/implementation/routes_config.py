"""Reference data (vendors, asset profiles, stations, talent, providers),
styles, usage-rights releases and the logical studio clock."""
from decimal import Decimal

from flask import Blueprint

from core import (
    CATEGORIES, ANGLE_CODES, CONTENT_STATES, DOC_STATES, PRIORITY_TIERS,
    PROVIDER_KINDS, STATION_TYPES, TALENT_TYPES, TERRITORIES, USAGE_SCOPES,
    authorize, by_created, created, db, fail, get_body, iso3, new_row, now, ok,
    ok_list, page_params, paginate, parse_dt, qenum, qstr, touch, vbool, vdt,
    venum, vint, vnum, vstr,
)
from logic import cost_summary, find, refresh_all_releases, refresh_release
from serialize import (
    asset_profile_out, provider_out, release_out, station_out, style_out,
    talent_out, vendor_out,
)

bp = Blueprint("config", __name__)

UPPER_NUM = r"^[A-Z0-9]+\Z"
UPPER_NUM_DASH = r"^[A-Z0-9\-]+\Z"


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("StudioAdmin")
    body = get_body()
    current_utc = vdt(body, "current_utc")
    db.clock = current_utc
    refresh_all_releases()
    return ok({"current_utc": iso3(db.clock)})


# --------------------------------------------------------------------------
# Vendors
# --------------------------------------------------------------------------
@bp.post("/vendors")
def create_vendor():
    authorize("StudioAdmin")
    body = get_body()
    name = vstr(body, "name", minlen=1, maxlen=120)
    if not name.strip():
        fail("ERR_INVALID_REQUEST", "Field 'name' must be non-empty after trimming.")
    vendor_code = vstr(body, "vendor_code", minlen=2, maxlen=12, pattern=UPPER_NUM)
    sample_sla_days = vint(body, "sample_sla_days", required=False, default=14,
                           minimum=1, maximum=120)
    contact_email = vstr(body, "contact_email", required=False, default=None, maxlen=320)

    if any(v["vendor_code"] == vendor_code for v in db.vendors.values()):
        fail("ERR_DUPLICATE_CODE", "vendor_code '%s' already exists." % vendor_code)

    row = new_row({
        "name": name,
        "vendor_code": vendor_code,
        "sample_sla_days": sample_sla_days,
        "contact_email": contact_email,
        "outstanding_sample_count": 0,
        "late_return_count": 0,
        "coordination_hold": False,
    })
    db.vendors[row["id"]] = row
    return created(vendor_out(row))


@bp.get("/vendors/<vendor_id>")
def read_vendor(vendor_id):
    authorize("StudioAdmin", "SampleCoordinator")
    row = find(db.vendors, vendor_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(vendor_out(row))


# --------------------------------------------------------------------------
# Asset profiles (immutable)
# --------------------------------------------------------------------------
@bp.post("/asset-profiles")
def create_asset_profile():
    authorize("StudioAdmin")
    body = get_body()
    category = venum(body, "category", CATEGORIES)
    required_angles = varray_angles(body)
    required_detail_shots = vint(body, "required_detail_shots", minimum=0)
    min_on_model_shots = vint(body, "min_on_model_shots", minimum=0)
    video_required = vbool(body, "video_required")
    naming_pattern = vstr(body, "naming_pattern", minlen=1)
    for token in ("{style_number}", "{angle_code}", "{seq}"):
        if token not in naming_pattern:
            fail("ERR_INVALID_REQUEST",
                 "naming_pattern must contain the token %s." % token)
    required_metadata_keys = _metadata_keys(body)

    if any(p["category"] == category for p in db.asset_profiles.values()):
        fail("ERR_DUPLICATE_CODE",
             "An asset profile for category '%s' already exists." % category)

    row = new_row({
        "category": category,
        "required_angles": required_angles,
        "required_detail_shots": required_detail_shots,
        "min_on_model_shots": min_on_model_shots,
        "video_required": video_required,
        "naming_pattern": naming_pattern,
        "required_metadata_keys": required_metadata_keys,
    })
    db.asset_profiles[row["id"]] = row
    return created(asset_profile_out(row))


def varray_angles(body):
    from core import varray
    return varray(body, "required_angles", non_empty=True, member_enum=ANGLE_CODES)


def _metadata_keys(body):
    from core import varray
    keys = varray(body, "required_metadata_keys", non_empty=True, strings=True)
    for key in keys:
        if not key.strip():
            fail("ERR_INVALID_REQUEST",
                 "required_metadata_keys must not contain empty strings.")
    return keys


@bp.get("/asset-profiles/<profile_id>")
def read_asset_profile(profile_id):
    authorize("StudioAdmin", "Producer", "ContentOps")
    row = find(db.asset_profiles, profile_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(asset_profile_out(row))


# --------------------------------------------------------------------------
# Stations
# --------------------------------------------------------------------------
@bp.post("/stations")
def create_station():
    authorize("StudioAdmin")
    body = get_body()
    station_code = vstr(body, "station_code", minlen=2, maxlen=16, pattern=UPPER_NUM_DASH)
    station_type = venum(body, "station_type", STATION_TYPES)
    daily_capacity_minutes = vint(body, "daily_capacity_minutes", minimum=1, maximum=1440)
    buffer_minutes = vint(body, "buffer_minutes", required=False, default=0,
                          minimum=0, maximum=240)
    max_concurrent_sessions = vint(body, "max_concurrent_sessions", required=False,
                                   default=1, minimum=1, maximum=8)
    calibrated_until = vdt(body, "calibrated_until", required=False, default=None)

    if any(s["station_code"] == station_code for s in db.stations.values()):
        fail("ERR_DUPLICATE_CODE", "station_code '%s' already exists." % station_code)

    row = new_row({
        "station_code": station_code,
        "station_type": station_type,
        "daily_capacity_minutes": daily_capacity_minutes,
        "buffer_minutes": buffer_minutes,
        "max_concurrent_sessions": max_concurrent_sessions,
        "calibrated_until": calibrated_until,
    })
    db.stations[row["id"]] = row
    return created(station_out(row))


@bp.get("/stations/<station_id>")
def read_station(station_id):
    authorize("StudioAdmin", "Producer")
    row = find(db.stations, station_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(station_out(row))


# --------------------------------------------------------------------------
# Talent profiles
# --------------------------------------------------------------------------
@bp.post("/talent-profiles")
def create_talent():
    authorize("StudioAdmin")
    body = get_body()
    full_name = vstr(body, "full_name", minlen=1, maxlen=120)
    talent_type = venum(body, "talent_type", TALENT_TYPES)
    agency_name = vstr(body, "agency_name", required=False, default=None, maxlen=200)
    hourly_rate_cents = vint(body, "hourly_rate_cents", minimum=0)
    day_rate_cents = vint(body, "day_rate_cents", minimum=0)
    minimum_call_hours = vint(body, "minimum_call_hours", required=False, default=4,
                              minimum=0, maximum=12)
    max_daily_minutes = vint(body, "max_daily_minutes", required=False, default=480,
                             minimum=60, maximum=1440)

    row = new_row({
        "full_name": full_name,
        "talent_type": talent_type,
        "agency_name": agency_name,
        "hourly_rate_cents": hourly_rate_cents,
        "day_rate_cents": day_rate_cents,
        "minimum_call_hours": minimum_call_hours,
        "max_daily_minutes": max_daily_minutes,
        "requires_release": talent_type == "MODEL",
    })
    db.talents[row["id"]] = row
    return created(talent_out(row))


@bp.get("/talent-profiles/<talent_id>")
def read_talent(talent_id):
    authorize("StudioAdmin", "Producer")
    row = find(db.talents, talent_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(talent_out(row))


# --------------------------------------------------------------------------
# Studio providers
# --------------------------------------------------------------------------
@bp.post("/studio-providers")
def create_provider():
    authorize("StudioAdmin")
    body = get_body()
    provider_code = vstr(body, "provider_code", minlen=2, maxlen=12, pattern=UPPER_NUM)
    provider_kind = venum(body, "provider_kind", PROVIDER_KINDS)
    station_hour_rate_cents = vint(body, "station_hour_rate_cents", minimum=0)
    retouch_rate_cents_per_asset = vint(body, "retouch_rate_cents_per_asset", minimum=0)
    sla_hours = vint(body, "sla_hours", minimum=1)
    quality_score = vnum(body, "quality_score", minimum=0, maximum=100)
    style_quote_cents = vint(body, "style_quote_cents", required=False, default=0, minimum=0)
    capacity_assets_per_day = vint(body, "capacity_assets_per_day", required=False,
                                   default=40, minimum=1)
    if provider_kind == "IN_HOUSE" and style_quote_cents != 0:
        fail("ERR_INVALID_REQUEST",
             "style_quote_cents must be 0 for an IN_HOUSE provider.")

    if any(p["provider_code"] == provider_code for p in db.providers.values()):
        fail("ERR_DUPLICATE_CODE", "provider_code '%s' already exists." % provider_code)

    row = new_row({
        "provider_code": provider_code,
        "provider_kind": provider_kind,
        "station_hour_rate_cents": station_hour_rate_cents,
        "retouch_rate_cents_per_asset": retouch_rate_cents_per_asset,
        "sla_hours": sla_hours,
        "quality_score": quality_score,
        "style_quote_cents": style_quote_cents,
        "capacity_assets_per_day": capacity_assets_per_day,
    })
    db.providers[row["id"]] = row
    return created(provider_out(row))


@bp.get("/studio-providers/<provider_id>")
def read_provider(provider_id):
    authorize("StudioAdmin", "Producer", "ContentOps")
    row = find(db.providers, provider_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(provider_out(row))


# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------
@bp.post("/styles")
def create_style():
    authorize("StudioAdmin")
    body = get_body()
    style_number = vstr(body, "style_number", minlen=4, maxlen=16,
                        pattern=UPPER_NUM, strip=True)
    category = venum(body, "category", CATEGORIES)
    vendor_id = vstr(body, "vendor_id", minlen=1)
    asset_profile_id = vstr(body, "asset_profile_id", minlen=1)
    base_style_id = vstr(body, "base_style_id", required=False, default=None, minlen=1)
    colorway_code = vstr(body, "colorway_code", required=False, default=None,
                         minlen=2, maxlen=8, pattern=UPPER_NUM)
    priority_tier = venum(body, "priority_tier", PRIORITY_TIERS, required=False,
                          default="C")

    # Body foreign keys (PRD 2.7 step 4).
    vendor = find(db.vendors, vendor_id, "ERR_REFERENCE_NOT_FOUND")
    profile = find(db.asset_profiles, asset_profile_id, "ERR_REFERENCE_NOT_FOUND")
    base_style = None
    if base_style_id is not None:
        base_style = find(db.styles, base_style_id, "ERR_STYLE_NOT_FOUND")

    # Business rules (PRD 2.7 step 8).
    if any(s["style_number"] == style_number for s in db.styles.values()):
        fail("ERR_DUPLICATE_STYLE_NUMBER",
             "style_number '%s' already exists." % style_number)
    if category != profile["category"]:
        fail("ERR_CATEGORY_PROFILE_MISMATCH",
             "The asset profile governs category '%s'." % profile["category"])
    if (base_style_id is None) != (colorway_code is None):
        fail("ERR_INVALID_BASE_STYLE",
             "base_style_id and colorway_code must be supplied together.")
    if base_style is not None:
        if base_style.get("base_style_id"):
            fail("ERR_INVALID_BASE_STYLE",
                 "Colorway parentage is one level deep only.")
        for s in db.styles.values():
            if s.get("base_style_id") == base_style_id and s.get("colorway_code") == colorway_code:
                fail("ERR_INVALID_BASE_STYLE",
                     "That colorway code already exists under this base style.")

    row = new_row({
        "style_number": style_number,
        "category": category,
        "vendor_id": vendor["id"],
        "asset_profile_id": profile["id"],
        "base_style_id": base_style_id,
        "colorway_code": colorway_code,
        "priority_tier": priority_tier,
        "content_state": "NOT_STARTED",
        "allocated_cost_cents": 0,
    })
    db.styles[row["id"]] = row
    return created(style_out(row))


@bp.get("/styles/<style_id>")
def read_style(style_id):
    authorize("StudioAdmin", "SampleCoordinator", "Producer", "ContentOps")
    row = find(db.styles, style_id, "ERR_STYLE_NOT_FOUND")
    return ok(style_out(row))


@bp.get("/styles")
def list_styles():
    authorize("StudioAdmin", "SampleCoordinator", "Producer", "ContentOps")
    limit, offset = page_params()
    vendor_id = qstr("vendor_id")
    asset_profile_id = qstr("asset_profile_id")
    base_style_id = qstr("base_style_id")
    category = qenum("category", CATEGORIES)
    content_state = qenum("content_state", CONTENT_STATES)
    priority_tier = qenum("priority_tier", PRIORITY_TIERS)

    rows = list(db.styles.values())
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if asset_profile_id is not None:
        rows = [r for r in rows if r["asset_profile_id"] == asset_profile_id]
    if base_style_id is not None:
        rows = [r for r in rows if r.get("base_style_id") == base_style_id]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if content_state is not None:
        rows = [r for r in rows if r["content_state"] == content_state]
    if priority_tier is not None:
        rows = [r for r in rows if r["priority_tier"] == priority_tier]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([style_out(r) for r in page], limit, offset, total)


@bp.get("/styles/<style_id>/cost-summary")
def style_cost_summary(style_id):
    authorize("StudioAdmin", "ContentOps")
    style = find(db.styles, style_id, "ERR_STYLE_NOT_FOUND")
    return ok(cost_summary(style))


# --------------------------------------------------------------------------
# Release documents
# --------------------------------------------------------------------------
@bp.post("/release-documents")
def create_release():
    authorize("StudioAdmin")
    body = get_body()
    talent_id = vstr(body, "talent_id", minlen=1)
    scope = venum(body, "scope", USAGE_SCOPES)
    territory = venum(body, "territory", TERRITORIES)
    valid_from = vdt(body, "valid_from")
    valid_until = vdt(body, "valid_until")

    talent = find(db.talents, talent_id, "ERR_REFERENCE_NOT_FOUND")

    if valid_until <= valid_from:
        fail("ERR_INVALID_TIME_WINDOW", "valid_until must be strictly after valid_from.")

    row = new_row({
        "talent_id": talent["id"],
        "scope": scope,
        "territory": territory,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "doc_state": "PENDING",
        "signed_at": None,
    })
    db.releases[row["id"]] = row
    return created(release_out(row))


@bp.post("/release-documents/<release_id>/sign")
def sign_release(release_id):
    authorize("StudioAdmin")
    row = find(db.releases, release_id, "ERR_REFERENCE_NOT_FOUND")
    refresh_release(row)
    if row["doc_state"] != "PENDING" or now() >= row["valid_until"]:
        fail("ERR_RELEASE_INVALID_STATE")
    row["doc_state"] = "SIGNED"
    row["signed_at"] = now()
    touch(row)
    return ok(release_out(row))


@bp.get("/release-documents/<release_id>")
def read_release(release_id):
    authorize("StudioAdmin", "Producer")
    row = find(db.releases, release_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(release_out(row))


@bp.get("/release-documents")
def list_releases():
    authorize("StudioAdmin", "Producer")
    limit, offset = page_params()
    talent_id = qstr("talent_id")
    doc_state = qenum("doc_state", DOC_STATES)
    scope = qenum("scope", USAGE_SCOPES)

    refresh_all_releases()
    rows = list(db.releases.values())
    if talent_id is not None:
        rows = [r for r in rows if r["talent_id"] == talent_id]
    if doc_state is not None:
        rows = [r for r in rows if r["doc_state"] == doc_state]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([release_out(r) for r in page], limit, offset, total)
