"""Markdown schedules: dual-variant pricing engine with OCC create-supersede,
activation cascade onto holds and lookbooks (PRD §3.5, §2.7)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, require_enum,
    parse_pagination, paginate, serialize, serialize_list,
)
from services.pricing import markdown_price

bp = Blueprint("markdowns", __name__)

PHASES = {"SEASONAL", "CLEARANCE"}


def _refresh_dependents(style):
    """After current_price_cents changes: refresh ACTIVE/EXTENDED hold prices on
    this style's variants and recompute featured_count of containing lookbooks."""
    variant_ids = {v["id"] for v in db.sku_variants.values() if v["style_id"] == style["id"]}
    for hold in db.fitting_room_holds.values():
        if hold["status"] in ("ACTIVE", "EXTENDED") and hold["sku_variant_id"] in variant_ids:
            hold["held_price_cents"] = style["current_price_cents"]
            touch(hold)
    for lb in db.lookbooks.values():
        if style["id"] in lb["style_ids"]:
            _recompute_featured_count(lb)


def _recompute_featured_count(lookbook):
    count = 0
    for sid in lookbook["style_ids"]:
        st = db.styles.get(sid)
        if st is not None and not st["clearance"]:
            count += 1
    lookbook["featured_count"] = count
    touch(lookbook)


@bp.post("/markdown-schedules")
def create_markdown():
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    body = get_json_body()

    # Existence (priority 3) before body validation? Path has no ids; style_id is
    # a body resource id validated left-to-right. Per §2.8 existence (3) precedes
    # well-formedness (5) only for *resource ids*; we resolve style_id first, then
    # validate the rest of the body, then OCC (7).
    style_id = require_str(body, "style_id")
    style = get_or_404("style", style_id)

    phase = require_enum(body, "phase", PHASES)
    markdown_pct = require_int(body, "markdown_pct")
    if markdown_pct < 1 or markdown_pct > 90:
        raise err(errors.ERR_INVALID_REQUEST, "markdown_pct must be in [1,90]")
    effective_date = require_int(body, "effective_date")
    if effective_date < 0:
        raise err(errors.ERR_INVALID_REQUEST, "effective_date must be >= 0")
    expected_style_version = require_int(body, "expected_style_version")

    # OCC (priority 7).
    if expected_style_version != style["version"]:
        raise err(errors.ERR_STALE_STYLE_VERSION, "expected_style_version is stale")

    # Create-supersede: retire any prior DRAFT/SCHEDULED schedule of this style.
    for ms in db.markdown_schedules.values():
        if ms["style_id"] == style_id and ms["status"] in ("DRAFT", "SCHEDULED"):
            ms["status"] = "SUPERSEDED"
            ms["projected_price_cents"] = None
            touch(ms)

    rec = stamp_new({
        "style_id": style_id,
        "phase": phase,
        "markdown_pct": markdown_pct,
        "effective_date": effective_date,
        "status": "DRAFT",
        "projected_price_cents": None,
        "applied_price_cents": None,
    })
    db.markdown_schedules[rec["id"]] = rec

    # Creation increments the style's version by one.
    touch(style)
    return success(serialize(rec), 201)


@bp.get("/markdown-schedules/<rid>")
def get_markdown(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "Merchandiser"})
    rec = get_or_404("markdown_schedule", rid)
    return success(serialize(rec))


@bp.get("/markdown-schedules")
def list_markdowns():
    _, role = authenticate()
    require_role(role, {"StoreManager", "Merchandiser"})
    limit, offset = parse_pagination()
    items = list(db.markdown_schedules.values())
    style_id = request.args.get("style_id")
    status = request.args.get("status")
    if style_id is not None:
        items = [m for m in items if m["style_id"] == style_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/markdown-schedules/<rid>/schedule")
def schedule_markdown(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    ms = get_or_404("markdown_schedule", rid)
    if ms["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "schedule requires DRAFT")
    style = db.styles[ms["style_id"]]
    # projected: provisional preview against current style price.
    ms["projected_price_cents"] = markdown_price(style, ms["phase"], ms["markdown_pct"])
    ms["status"] = "SCHEDULED"
    touch(ms)
    return success(serialize(ms))


@bp.post("/markdown-schedules/<rid>/unschedule")
def unschedule_markdown(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    ms = get_or_404("markdown_schedule", rid)
    if ms["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "unschedule requires SCHEDULED")
    ms["projected_price_cents"] = None
    ms["status"] = "DRAFT"
    touch(ms)
    return success(serialize(ms))


@bp.post("/markdown-schedules/<rid>/activate")
def activate_markdown(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    ms = get_or_404("markdown_schedule", rid)
    if ms["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "activate requires SCHEDULED")
    style = db.styles[ms["style_id"]]
    boutique = db.boutiques[style["boutique_id"]]
    if boutique["current_business_date"] < ms["effective_date"]:
        raise err(errors.ERR_MARKDOWN_NOT_EFFECTIVE, "current_business_date below effective_date")

    # Supersede the prior ACTIVE schedule of this style before writing the price.
    for other in db.markdown_schedules.values():
        if other["id"] != ms["id"] and other["style_id"] == style["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)

    # final variant: re-read current_price_cents at activation.
    applied = markdown_price(style, ms["phase"], ms["markdown_pct"])
    ms["applied_price_cents"] = applied
    ms["status"] = "ACTIVE"
    touch(ms)

    style["current_price_cents"] = applied
    if ms["phase"] == "CLEARANCE":
        style["clearance"] = True
    touch(style)

    _refresh_dependents(style)
    return success(serialize(ms))


@bp.post("/markdown-schedules/<rid>/end")
def end_markdown(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    ms = get_or_404("markdown_schedule", rid)
    if ms["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "end requires ACTIVE")
    style = db.styles[ms["style_id"]]
    ms["status"] = "ENDED"
    touch(ms)

    style["current_price_cents"] = style["list_price_cents"]
    style["clearance"] = False
    touch(style)
    _refresh_dependents(style)
    return success(serialize(ms))
