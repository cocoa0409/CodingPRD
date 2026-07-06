"""Storefront endpoints. Handles create/read/list/update-markup and channel link/suspend/resume."""
from flask import Blueprint, request

import db
from clock import clock
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import listing_price_cents
from services.serialize import serialize

bp = Blueprint("storefronts", __name__)


def _get_storefront_or_404(sid):
    row = db.storefronts.get(sid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"storefront {sid} not found")
    return row


def _validate_markup(mv):
    if not isinstance(mv, int) or isinstance(mv, bool):
        raise_error("ERR_INVALID_REQUEST", "markup_bps must be an integer")
    if mv < 0 or mv > 10000:
        raise_error("ERR_MARKUP_OUT_OF_RANGE", "markup_bps out of [0,10000]")


@bp.post("/pod/storefronts")
@require_auth(["Creator"])
def create_storefront():
    body = request.get_json(silent=True) or {}
    for f in ("creator_id", "slug", "markup_bps"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    channel = body.get("integration_channel", "NATIVE")
    if channel not in ("NATIVE", "ETSY", "SHOPIFY"):
        raise_error("ERR_INVALID_REQUEST", "invalid integration_channel")

    # Priority 4 FK: creator_id must resolve.
    creator = db.creators.get(body["creator_id"])
    if not creator:
        raise_error("ERR_FK_NOT_FOUND", f"creator {body['creator_id']} not found")

    _validate_markup(body["markup_bps"])

    slug = body["slug"]
    if not isinstance(slug, str) or not slug:
        raise_error("ERR_INVALID_REQUEST", "slug must be non-empty string")
    # Slug uniqueness.
    for s in db.storefronts.all():
        if s["slug"] == slug:
            raise_error("ERR_INVALID_REQUEST", "slug already in use")

    row = db.new_common_fields()
    row.update(
        {
            "creator_id": body["creator_id"],
            "slug": slug,
            "integration_channel": channel,
            "integration_status": "NONE",
            "markup_bps": body["markup_bps"],
        }
    )
    db.storefronts.insert(row)
    return created(serialize(row))


@bp.get("/pod/storefronts/<sid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_storefront(sid):
    row = _get_storefront_or_404(sid)
    return ok(serialize(row))


@bp.get("/pod/storefronts")
@require_auth(["Creator", "PlatformAdmin"])
def list_storefronts():
    creator_id = request.args.get("creator_id")
    rows = db.storefronts.all()
    if creator_id is not None:
        rows = [r for r in rows if r["creator_id"] == creator_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.put("/pod/storefronts/<sid>")
@require_auth(["Creator"])
def update_storefront(sid):
    row = _get_storefront_or_404(sid)
    body = request.get_json(silent=True) or {}
    if "markup_bps" not in body:
        raise_error("ERR_INVALID_REQUEST", "missing markup_bps")
    _validate_markup(body["markup_bps"])

    row["markup_bps"] = body["markup_bps"]
    db.bump(row)

    # Cascade: recompute listed_price_cents for every listing under this storefront.
    for lst in db.listings.all():
        if lst["storefront_id"] != sid:
            continue
        variant = db.variants.get(lst["variant_id"])
        product = db.products.get(variant["product_id"]) if variant else None
        if variant and product:
            lst["listed_price_cents"] = listing_price_cents(product, variant, row, is_sample=False)
            db.bump(lst)

    return ok(serialize(row))


@bp.post("/pod/storefronts/<sid>/link-channel")
@require_auth(["Creator"])
def link_channel(sid):
    row = _get_storefront_or_404(sid)
    body = request.get_json(silent=True) or {}
    if "expected_storefront_version" not in body:
        raise_error("ERR_INVALID_REQUEST", "expected_storefront_version is required")
    expected_version = body["expected_storefront_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise_error("ERR_INVALID_REQUEST", "expected_storefront_version must be int")

    # Priority 5 (state): channel not yet LINKED / not SUSPENDED.
    if row["integration_status"] == "LINKED":
        raise_error("ERR_STOREFRONT_CHANNEL_ALREADY_LINKED", "already linked")
    if row["integration_status"] != "NONE":
        raise_error("ERR_INVALID_STATE", "integration_status must be NONE to link")

    # Channel must be ETSY or SHOPIFY (not NATIVE) per state machine.
    if row["integration_channel"] not in ("ETSY", "SHOPIFY"):
        raise_error("ERR_INVALID_STATE", "integration_channel must be ETSY or SHOPIFY to link")

    # Creator must be VERIFIED or PENDING.
    creator = db.creators.get(row["creator_id"])
    if not creator or creator["verification_status"] not in ("VERIFIED", "PENDING"):
        raise_error("ERR_INVALID_STATE", "creator must be VERIFIED or PENDING to link channel")

    # Priority 6 (OCC).
    if expected_version != row["version"]:
        raise_error(
            "ERR_STALE_STOREFRONT_VERSION",
            f"expected version {expected_version}, current is {row['version']}",
        )

    # Apply state change.
    row["integration_status"] = "LINKED"
    db.bump(row)

    # Cascade: emit ChannelSyncEvent{LISTING_MIRROR} per PUBLISHED listing.
    for lst in db.sorted_rows(db.listings.all()):
        if lst["storefront_id"] == sid and lst["status"] == "PUBLISHED":
            evt = {
                "id": db.new_id(),
                "created_at": clock.now_iso(),
                "_seq": clock.next_seq(),
                "storefront_id": sid,
                "channel": row["integration_channel"],
                "event_type": "LISTING_MIRROR",
                "external_ref": lst["id"],
            }
            db.channel_sync_events.insert(evt)

    return ok(serialize(row))


@bp.post("/pod/storefronts/<sid>/suspend-channel")
@require_auth(["PlatformAdmin"])
def suspend_channel(sid):
    row = _get_storefront_or_404(sid)
    if row["integration_status"] != "LINKED":
        raise_error("ERR_INVALID_STATE", "channel must be LINKED to suspend")
    row["integration_status"] = "SUSPENDED"
    db.bump(row)
    return ok(serialize(row))


@bp.post("/pod/storefronts/<sid>/resume-channel")
@require_auth(["PlatformAdmin"])
def resume_channel(sid):
    row = _get_storefront_or_404(sid)
    if row["integration_status"] != "SUSPENDED":
        raise_error("ERR_INVALID_STATE", "channel must be SUSPENDED to resume")
    creator = db.creators.get(row["creator_id"])
    if not creator or creator["verification_status"] != "VERIFIED":
        raise_error("ERR_INVALID_STATE", "creator must be VERIFIED to resume channel")
    row["integration_status"] = "LINKED"
    db.bump(row)
    return ok(serialize(row))


@bp.get("/pod/storefronts/<sid>/channel-sync-events")
@require_auth(["Creator", "PlatformAdmin"])
def list_channel_events(sid):
    # Path resolution first.
    _get_storefront_or_404(sid)
    rows = [e for e in db.channel_sync_events.all() if e["storefront_id"] == sid]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.post("/pod/storefronts/<sid>/ingest-channel-order")
@require_auth(["PlatformAdmin"])
def ingest_channel_order(sid):
    storefront = _get_storefront_or_404(sid)
    body = request.get_json(silent=True) or {}
    for f in ("channel", "external_ref", "listing_id", "buyer_email", "ship_country_code", "item_count"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    channel = body["channel"]
    if channel not in ("ETSY", "SHOPIFY"):
        raise_error("ERR_INVALID_REQUEST", "channel must be ETSY or SHOPIFY")

    listing = db.listings.get(body["listing_id"])
    if not listing:
        raise_error("ERR_FK_NOT_FOUND", f"listing {body['listing_id']} not found")

    item_count = body["item_count"]
    if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 1:
        raise_error("ERR_INVALID_REQUEST", "item_count must be a positive integer")

    # Create Order shell.
    order = db.new_common_fields()
    order.update(
        {
            "storefront_id": sid,
            "buyer_email": body["buyer_email"],
            "ship_country_code": body["ship_country_code"],
            "item_count": item_count,
            "listing_id": body["listing_id"],
            "is_sample": False,
            "gross_amount_cents": 0,
            "shipping_cents": 0,
            "payment_status": "DRAFT",
            "fulfillment_status": "PENDING",
            "routed_partner_id": None,
            "creator_net_cents": 0,
            "_initial_partner_charge_cents": None,
            "_delivered_at": None,
        }
    )
    db.orders.insert(order)

    # Emit sync event.
    evt = {
        "id": db.new_id(),
        "created_at": clock.now_iso(),
        "_seq": clock.next_seq(),
        "storefront_id": sid,
        "channel": channel,
        "event_type": "ORDER_INGEST",
        "external_ref": body["external_ref"],
    }
    db.channel_sync_events.insert(evt)

    return created(serialize(order))
