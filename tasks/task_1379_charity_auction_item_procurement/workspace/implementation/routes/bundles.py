"""Bundle and Bid routes (PRD 3.4, 3.5)."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from services import calc
from services import workflows as wf

bp = Blueprint("bundles", __name__)

CM = ["CatalogManager"]
READ = mw.ALL_ROLES


@bp.post("/bundles")
def create_bundle():
    mw.require_auth(CM)
    body = mw.get_json_body()
    gala_event_id = mw.require_string(body, "gala_event_id")
    event = mw.get_or_404("gala_events", gala_event_id)
    title = mw.require_string(body, "title")
    if event["status"] != "CATALOGING":
        raise errors.err_catalog_frozen("Bundle creation requires event CATALOGING")
    rec = mw.new_record()
    rec["gala_event_id"] = gala_event_id
    rec["title"] = title
    rec["status"] = "DRAFT"
    rec["bundle_fmv_cents"] = 0
    rec["min_bid_cents"] = None
    rec["min_bid_overridden"] = False
    rec["current_high_bid_cents"] = None
    rec["published_at"] = None
    stores["bundles"][rec["id"]] = rec
    # Create returns the created resource as stored (PRD 2.2 + 3.4):
    # min_bid_cents is null at start; the DRAFT preview variant (PRD 3.4)
    # is shown on reads (GET), handled by wf.serialize_bundle there.
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/bundles/<rid>")
def get_bundle(rid):
    mw.require_auth(READ)
    return response.success_object(wf.serialize_bundle(mw.get_or_404("bundles", rid)))


@bp.post("/bundles/<rid>/items")
def attach_item(rid):
    mw.require_auth(CM)
    bundle = mw.get_or_404("bundles", rid)
    body = mw.get_json_body()
    item_id = mw.require_string(body, "item_id")
    item = mw.get_or_404("items", item_id)
    if bundle["status"] != "DRAFT":
        raise errors.err_invalid_state("Attach requires a DRAFT bundle")
    event = stores["gala_events"][bundle["gala_event_id"]]
    if event["status"] != "CATALOGING":
        raise errors.err_catalog_frozen()
    if item["bundle_id"] is not None:
        raise errors.err_item_already_bundled()
    if item["status"] != "VALUED":
        raise errors.err_item_not_valued()
    if item["gala_event_id"] != bundle["gala_event_id"]:
        raise errors.err_invalid_request("Item belongs to a different gala event than the bundle")
    item["status"] = "BUNDLED"
    item["bundle_id"] = bundle["id"]
    mw.touch(item)
    wf.recompute_bundle_fmv(bundle)
    return response.success_object(wf.serialize_bundle(bundle))


@bp.delete("/bundles/<rid>/items/<item_id>")
def detach_item(rid, item_id):
    mw.require_auth(CM)
    bundle = mw.get_or_404("bundles", rid)
    item = mw.get_or_404("items", item_id)
    if item["bundle_id"] != bundle["id"]:
        raise errors.err_not_found("Item is not a member of this bundle")
    if bundle["status"] != "DRAFT":
        raise errors.err_invalid_state("Detach requires a DRAFT bundle")
    event = stores["gala_events"][bundle["gala_event_id"]]
    if event["status"] != "CATALOGING":
        raise errors.err_catalog_frozen()
    item["status"] = "VALUED"
    item["bundle_id"] = None
    mw.touch(item)
    wf.recompute_bundle_fmv(bundle)
    return response.success_object(wf.serialize_bundle(bundle))


@bp.post("/bundles/<rid>/publish")
def publish_bundle(rid):
    mw.require_auth(CM)
    bundle = mw.get_or_404("bundles", rid)
    if bundle["status"] != "DRAFT":
        raise errors.err_invalid_state("Publish requires a DRAFT bundle")
    event = stores["gala_events"][bundle["gala_event_id"]]
    if event["status"] != "CATALOGING":
        raise errors.err_catalog_frozen()
    members = wf.member_items(bundle)
    if not members:
        raise errors.err_bundle_empty()
    # Freeze FMV and lock the minimum bid (LOCKED variant, PRD 3.4).
    bundle["bundle_fmv_cents"] = sum(i["current_fmv_cents"] for i in members)
    bundle["min_bid_cents"] = calc.minimum_bid_cents(bundle["bundle_fmv_cents"], event)
    bundle["published_at"] = clock.now()
    bundle["status"] = "PUBLISHED"
    mw.touch(bundle)
    for item in members:
        item["status"] = "CATALOGED"
        mw.touch(item)
    return response.success_object(wf.serialize_bundle(bundle))


@bp.patch("/bundles/<rid>/min-bid")
def patch_min_bid(rid):
    mw.require_auth(CM)
    bundle = mw.get_or_404("bundles", rid)
    body = mw.get_json_body()
    min_bid_cents = mw.require_int(body, "min_bid_cents")
    expected = mw.require_int(body, "expected_bundle_version")
    if expected != bundle["version"]:
        raise errors.err_stale_version()
    if bundle["status"] != "PUBLISHED":
        raise errors.err_invalid_state("Min-bid override requires a PUBLISHED bundle")
    event = stores["gala_events"][bundle["gala_event_id"]]
    if event["status"] != "CATALOGING":
        raise errors.err_catalog_frozen()
    if min_bid_cents < event["min_bid_floor_cents"]:
        raise errors.err_min_bid_below_floor()
    bundle["min_bid_cents"] = min_bid_cents
    bundle["min_bid_overridden"] = True
    mw.touch(bundle)
    return response.success_object(wf.serialize_bundle(bundle))


@bp.post("/bundles/<rid>/bids")
def place_bid(rid):
    user_id, _ = mw.require_auth(["Bidder"])
    bundle = mw.get_or_404("bundles", rid)
    body = mw.get_json_body()
    amount_cents = mw.require_int(body, "amount_cents")
    expected = mw.require_int(body, "expected_bundle_version")
    if expected != bundle["version"]:
        raise errors.err_stale_version()
    if bundle["status"] != "PUBLISHED":
        raise errors.err_invalid_state("Bids require a PUBLISHED bundle")
    event = stores["gala_events"][bundle["gala_event_id"]]
    if event["status"] != "BIDDING_OPEN":
        raise errors.err_event_phase_forbidden("Bids require event BIDDING_OPEN")
    bidder = stores["bidders"].get(user_id)
    if bidder is None or bidder["gala_event_id"] != bundle["gala_event_id"]:
        raise errors.err_bidder_event_mismatch()
    if bidder["status"] != "REGISTERED":
        raise errors.err_bidder_suspended()
    if not bidder["payment_method_on_file"]:
        raise errors.err_payment_method_required()
    active = wf.active_bid(bundle["id"])
    min_next = calc.min_next_bid_cents(bundle, event, active is not None)
    if amount_cents < min_next:
        raise errors.err_bid_below_minimum(f"amount_cents below min_next_bid_cents {min_next}")
    rec = mw.new_record()
    rec["bundle_id"] = bundle["id"]
    rec["bidder_id"] = user_id
    rec["amount_cents"] = amount_cents
    rec["placed_at"] = clock.now()
    rec["status"] = "ACTIVE"
    stores["bids"][rec["id"]] = rec
    if active is not None:
        active["status"] = "OUTBID"
        mw.touch(active)
    bundle["current_high_bid_cents"] = amount_cents
    mw.touch(bundle)
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/bundles/<rid>/bids")
def list_bundle_bids(rid):
    mw.require_auth(READ)
    bundle = mw.get_or_404("bundles", rid)
    limit, offset = mw.parse_pagination()
    items = [b for b in stores["bids"].values() if b["bundle_id"] == bundle["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(b) for b in page], limit, offset, total)
