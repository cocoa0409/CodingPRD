"""Art Gallery & Exhibition Sales API — entry point and all routes.

In-memory only; no seeding. Validation order per PRD §2.6:
auth -> forbidden -> existence -> invalid_request -> state -> OCC -> business.
"""
import os

from flask import Flask, request

import clock as clockmod
import errors
import response
import services as svc
from db import DB
from middleware import authenticate, require_role

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error(err)


@app.errorhandler(404)
def handle_404(_e):
    return response.error(errors.not_found("Route not found."))


@app.errorhandler(405)
def handle_405(_e):
    return response.error(errors.forbidden("Method not allowed."))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error(e)
    return response.error(errors.ApiError("ERR_INTERNAL", 500, str(e)))


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Body must be a JSON object.")
        return data
    return {}


def list_filter(rows, args, fields):
    """Apply equality filters for the given field names if present in args."""
    out = list(rows)
    for f in fields:
        val = args.get(f)
        if val is not None:
            out = [r for r in out if str(r.get(f)) == str(val)]
    return out


def artist_scope(user_id, role, rows, artist_id_getter):
    """For Artist role, restrict to rows owned by the acting artist."""
    if role != "Artist":
        return rows
    return [r for r in rows if artist_id_getter(r) == user_id]


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.invalid_request("Missing required field: to_iso8601")
    try:
        DB.clock_utc = clockmod.parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 instant.")
    return response.ok({"clock_utc": clockmod.format_iso_clock(DB.clock_utc)})


# ===========================================================================
# Gallery
# ===========================================================================
@app.route("/galleries", methods=["POST"])
def create_gallery():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    name = svc.as_str(body, "name")
    home = svc.state_code(body, "home_state_code")
    rate = svc.as_int(body, "sales_tax_rate_bps")
    if rate < 0 or rate > 2000:
        raise errors.invalid_request("sales_tax_rate_bps must be 0..2000.")
    resale = svc.as_int(body, "resale_exempt_threshold_cents", required=False, default=0)
    if resale < 0:
        raise errors.invalid_request("resale_exempt_threshold_cents must be >= 0.")
    split = svc.as_int(body, "default_consignment_split_bps", required=False, default=5000)
    if split < 0 or split > 10000:
        raise errors.invalid_request("default_consignment_split_bps must be 0..10000.")
    g = {
        "id": DB.new_id(),
        "name": name,
        "home_state_code": home,
        "sales_tax_rate_bps": rate,
        "resale_exempt_threshold_cents": resale,
        "default_consignment_split_bps": split,
    }
    svc.stamp_new(g)
    DB.galleries[g["id"]] = g
    return response.created(svc.ser_gallery(g))


@app.route("/galleries/<gallery_id>", methods=["GET"])
def get_gallery(gallery_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    g = svc.get_gallery(gallery_id)
    return response.ok(svc.ser_gallery(g))


# ===========================================================================
# Artist
# ===========================================================================
@app.route("/artists", methods=["POST"])
def create_artist():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    gid = svc.as_str(body, "gallery_id")
    full_name = svc.as_str(body, "full_name")
    override = svc.as_int(body, "split_override_bps", required=False, default=None)
    if override is not None and (override < 0 or override > 10000):
        raise errors.invalid_request("split_override_bps must be 0..10000.")
    svc.get_gallery(gid)
    a = {
        "id": DB.new_id(),
        "gallery_id": gid,
        "full_name": full_name,
        "split_override_bps": override,
        "status": "ACTIVE",
    }
    svc.stamp_new(a)
    DB.artists[a["id"]] = a
    return response.created(svc.ser_artist(a))


@app.route("/artists", methods=["GET"])
def list_artists():
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(DB.artists.values(), request.args, ["gallery_id", "status"])
    rows = artist_scope(uid, role, rows, lambda r: r["id"])
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_artist(a) for a in page], limit, offset, total)


@app.route("/artists/<artist_id>", methods=["GET"])
def get_artist(artist_id):
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    a = svc.get_or_404(DB.artists, artist_id, "Artist")
    if role == "Artist" and a["id"] != uid:
        raise errors.forbidden()
    return response.ok(svc.ser_artist(a))


@app.route("/artists/<artist_id>/suspend", methods=["POST"])
def suspend_artist(artist_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    a = svc.get_or_404(DB.artists, artist_id, "Artist")
    if a["status"] != "ACTIVE":
        raise errors.invalid_state("Artist is not ACTIVE.")
    a["status"] = "SUSPENDED"
    svc.touch(a)
    return response.ok(svc.ser_artist(a))


@app.route("/artists/<artist_id>/reinstate", methods=["POST"])
def reinstate_artist(artist_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    a = svc.get_or_404(DB.artists, artist_id, "Artist")
    if a["status"] != "SUSPENDED":
        raise errors.invalid_state("Artist is not SUSPENDED.")
    a["status"] = "ACTIVE"
    svc.touch(a)
    return response.ok(svc.ser_artist(a))


# ===========================================================================
# Artwork
# ===========================================================================
@app.route("/artworks", methods=["POST"])
def create_artwork():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar"})
    body = get_body()
    gid = svc.as_str(body, "gallery_id")
    artist_id = svc.as_str(body, "artist_id")
    title = svc.as_str(body, "title")
    list_price = svc.as_int(body, "list_price_cents")
    insured = svc.as_int(body, "insured_value_cents")
    if list_price <= 0:
        raise errors.invalid_request("list_price_cents must be > 0.")
    if insured <= 0:
        raise errors.invalid_request("insured_value_cents must be > 0.")
    svc.get_gallery(gid)
    artist = svc.get_or_404(DB.artists, artist_id, "Artist")
    if artist["status"] == "SUSPENDED":
        raise errors.artist_suspended()
    aw = {
        "id": DB.new_id(),
        "gallery_id": gid,
        "artist_id": artist_id,
        "title": title,
        "list_price_cents": list_price,
        "insured_value_cents": insured,
        "provenance_count": 0,
        "provenance_log": [],
        "status": "CONSIGNED",
    }
    svc.stamp_new(aw)
    DB.artworks[aw["id"]] = aw
    svc.seed_provenance(aw, "CONSIGNED")
    return response.created(svc.ser_artwork(aw))


@app.route("/artworks", methods=["GET"])
def list_artworks():
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.artworks.values(), request.args, ["gallery_id", "artist_id", "status"]
    )
    rows = artist_scope(uid, role, rows, lambda r: r["artist_id"])
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_artwork(a) for a in page], limit, offset, total)


@app.route("/artworks/<artwork_id>", methods=["GET"])
def get_artwork(artwork_id):
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    aw = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    if role == "Artist" and aw["artist_id"] != uid:
        raise errors.forbidden()
    return response.ok(svc.ser_artwork(aw))


@app.route("/artworks/<artwork_id>/provenance", methods=["POST"])
def append_provenance_route(artwork_id):
    _uid, role = authenticate()
    require_role(role, {"Registrar"})
    aw = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    body = get_body()
    if "event" not in body or body["event"] is None:
        raise errors.invalid_request("Missing required field: event")
    event_text = body["event"]
    if not isinstance(event_text, str):
        raise errors.invalid_request("event must be a string.")
    if event_text.strip() == "":
        raise errors.duplicate_provenance_event()
    svc.append_provenance(aw, event_text)
    return response.created(svc.ser_artwork(aw))


@app.route("/artworks/<artwork_id>/return-to-artist", methods=["POST"])
def return_to_artist(artwork_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    aw = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    if aw["status"] != "CONSIGNED":
        raise errors.invalid_state("Artwork must be CONSIGNED to return to artist.")
    aw["status"] = "RETURNED"
    svc.touch(aw)
    svc.append_provenance(aw, "RETURNED_TO_ARTIST")
    return response.ok(svc.ser_artwork(aw))


# ===========================================================================
# Exhibition + wall map
# ===========================================================================
@app.route("/exhibitions", methods=["POST"])
def create_exhibition():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    gid = svc.as_str(body, "gallery_id")
    title = svc.as_str(body, "title")
    capacity = svc.as_int(body, "wall_capacity")
    if capacity <= 0:
        raise errors.invalid_request("wall_capacity must be > 0.")
    opens = svc.parse_dt_field(body, "opens_utc")
    closes = svc.parse_dt_field(body, "closes_utc")
    if closes <= opens:
        raise errors.invalid_request("closes_utc must be strictly after opens_utc.")
    svc.get_gallery(gid)
    ex = {
        "id": DB.new_id(),
        "gallery_id": gid,
        "title": title,
        "wall_capacity": capacity,
        "opens_utc": opens,
        "closes_utc": closes,
        "status": "PLANNED",
    }
    svc.stamp_new(ex)
    DB.exhibitions[ex["id"]] = ex
    return response.created(svc.ser_exhibition(ex))


@app.route("/exhibitions", methods=["GET"])
def list_exhibitions():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(DB.exhibitions.values(), request.args, ["gallery_id", "status"])
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_exhibition(e) for e in page], limit, offset, total)


@app.route("/exhibitions/<exhibition_id>", methods=["GET"])
def get_exhibition(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    return response.ok(svc.ser_exhibition(ex))


def _windows_overlap_closed(a_open, a_close, b_open, b_close):
    """Closed-interval overlap (shared boundary counts) for exhibitions."""
    return a_open <= b_close and b_open <= a_close


@app.route("/exhibitions/<exhibition_id>/wall-slots", methods=["POST"])
def place_wall_slot(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar"})
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    body = get_body()
    artwork_id = svc.as_str(body, "artwork_id")
    wall_label = svc.as_str(body, "wall_label")
    position_index = svc.as_int(body, "position_index")
    expected_version = svc.as_int(body, "expected_exhibition_version")
    if position_index < 0:
        raise errors.invalid_request("position_index must be >= 0.")
    artwork = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    # OCC (priority 6) before business rules (priority >= 7).
    if expected_version != ex["version"]:
        raise errors.stale_version()
    # Schedule conflict (priority 9): same artwork PLACED in another non-terminal
    # exhibition whose closed run window intersects this one.
    for other in DB.exhibitions.values():
        if other["id"] == exhibition_id:
            continue
        if other["status"] not in ("PLANNED", "OPEN"):
            continue
        placed_here = any(
            ws["exhibition_id"] == other["id"]
            and ws["artwork_id"] == artwork_id
            and ws["status"] == "PLACED"
            for ws in DB.wall_slots.values()
        )
        if not placed_here:
            continue
        if _windows_overlap_closed(
            ex["opens_utc"], ex["closes_utc"], other["opens_utc"], other["closes_utc"]
        ):
            raise errors.schedule_conflict()
    # Capacity & position uniqueness (priority 10).
    occupied, _avail = svc.exhibition_slot_counts(exhibition_id, ex["wall_capacity"])
    if occupied + 1 > ex["wall_capacity"]:
        raise errors.wall_capacity_exceeded()
    for ws in DB.wall_slots.values():
        if (
            ws["exhibition_id"] == exhibition_id
            and ws["status"] == "PLACED"
            and ws["position_index"] == position_index
        ):
            raise errors.wall_capacity_exceeded()
    slot = {
        "id": DB.new_id(),
        "gallery_id": ex["gallery_id"],
        "exhibition_id": exhibition_id,
        "artwork_id": artwork_id,
        "wall_label": wall_label,
        "position_index": position_index,
        "status": "PLACED",
    }
    svc.stamp_new(slot)
    DB.wall_slots[slot["id"]] = slot
    svc.touch(ex)  # bump exhibition version (supersede write)
    return response.created(svc.ser_wall_slot(slot))


@app.route("/exhibitions/<exhibition_id>/wall-slots", methods=["GET"])
def list_exhibition_wall_slots(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    limit, offset = svc.parse_pagination(request.args)
    rows = [
        ws for ws in DB.wall_slots.values() if ws["exhibition_id"] == exhibition_id
    ]
    rows = list_filter(rows, request.args, ["status"])
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_wall_slot(w) for w in page], limit, offset, total)


@app.route("/wall-slots", methods=["GET"])
def list_wall_slots():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.wall_slots.values(),
        request.args,
        ["gallery_id", "artwork_id", "exhibition_id", "status"],
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_wall_slot(w) for w in page], limit, offset, total)


@app.route("/wall-slots/<wall_slot_id>", methods=["GET"])
def get_wall_slot(wall_slot_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"})
    ws = svc.get_or_404(DB.wall_slots, wall_slot_id, "WallSlot")
    return response.ok(svc.ser_wall_slot(ws))


@app.route("/exhibitions/<exhibition_id>/open", methods=["POST"])
def open_exhibition(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    if ex["status"] != "PLANNED":
        raise errors.invalid_state("Exhibition must be PLANNED to open.")
    occupied, _avail = svc.exhibition_slot_counts(exhibition_id, ex["wall_capacity"])
    if occupied < 1:
        raise errors.invalid_state("At least one slot must be occupied to open.")
    if DB.clock_utc < ex["opens_utc"]:
        raise errors.invalid_state("Clock has not reached opens_utc.")
    ex["status"] = "OPEN"
    svc.touch(ex)
    return response.ok(svc.ser_exhibition(ex))


@app.route("/exhibitions/<exhibition_id>/close", methods=["POST"])
def close_exhibition(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    if ex["status"] != "OPEN":
        raise errors.invalid_state("Exhibition must be OPEN to close.")
    if DB.clock_utc < ex["closes_utc"]:
        raise errors.invalid_state("Clock has not reached closes_utc.")
    ex["status"] = "CLOSED"
    for ws in DB.wall_slots.values():
        if ws["exhibition_id"] == exhibition_id and ws["status"] == "PLACED":
            ws["status"] = "RELEASED"
            svc.touch(ws)
    svc.touch(ex)
    return response.ok(svc.ser_exhibition(ex))


@app.route("/exhibitions/<exhibition_id>/cancel", methods=["POST"])
def cancel_exhibition(exhibition_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    if ex["status"] != "PLANNED":
        raise errors.invalid_state("Exhibition must be PLANNED to cancel.")
    ex["status"] = "CANCELLED"
    # Release placed slots.
    for ws in DB.wall_slots.values():
        if ws["exhibition_id"] == exhibition_id and ws["status"] == "PLACED":
            ws["status"] = "RELEASED"
            svc.touch(ws)
    # Cancel scheduled opening events and their confirmed/waitlisted RSVPs.
    for ev in DB.opening_events.values():
        if ev["exhibition_id"] == exhibition_id and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            svc.touch(ev)
            for r in DB.rsvps.values():
                if r["opening_event_id"] == ev["id"] and r["status"] in (
                    "CONFIRMED",
                    "WAITLISTED",
                ):
                    r["status"] = "CANCELLED"
                    svc.touch(r)
    svc.touch(ex)
    return response.ok(svc.ser_exhibition(ex))


# ===========================================================================
# Sale
# ===========================================================================
@app.route("/sales", methods=["POST"])
def create_sale():
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    body = get_body()
    gid = svc.as_str(body, "gallery_id")
    artwork_id = svc.as_str(body, "artwork_id")
    buyer_name = svc.as_str(body, "buyer_name")
    buyer_state = svc.state_code(body, "buyer_state_code")
    gross = svc.as_int(body, "gross_amount_cents")
    if gross <= 0:
        raise errors.invalid_request("gross_amount_cents must be > 0.")
    exhibition_id = svc.as_str(body, "exhibition_id", required=False, default=None)
    discount = svc.as_int(body, "discount_bps", required=False, default=0)
    if discount < 0 or discount > 10000:
        raise errors.invalid_request("discount_bps must be 0..10000.")
    shipping = svc.as_int(body, "shipping_cents", required=False, default=0)
    if shipping < 0:
        raise errors.invalid_request("shipping_cents must be >= 0.")
    gallery = svc.get_gallery(gid)
    artwork = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    if exhibition_id is not None:
        svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    if artwork["status"] != "CONSIGNED":
        raise errors.invalid_state("Artwork must be CONSIGNED to reserve.")
    artist = DB.artists.get(artwork["artist_id"])
    if artist and artist["status"] == "SUSPENDED":
        raise errors.artist_suspended()
    sale = _build_sale(
        gid, artwork, exhibition_id, buyer_name, buyer_state, gross, discount, shipping,
        gallery, artist,
    )
    return response.created(svc.ser_sale(sale))


def _build_sale(
    gid, artwork, exhibition_id, buyer_name, buyer_state, gross, discount, shipping,
    gallery, artist,
):
    sale = {
        "id": DB.new_id(),
        "gallery_id": gid,
        "artwork_id": artwork["id"],
        "exhibition_id": exhibition_id,
        "buyer_name": buyer_name,
        "buyer_state_code": buyer_state,
        "gross_amount_cents": gross,
        "discount_bps": discount,
        "shipping_cents": shipping,
        "net_amount_cents": 0,
        "tax_amount_cents": 0,
        "buyer_total_cents": 0,
        "artist_share_cents": 0,
        "gallery_share_cents": 0,
        "amount_collected_cents": 0,
        "settlement_status": "RESERVED",
        "shipping_status": "PENDING",
    }
    svc.stamp_new(sale)
    svc.compute_sale_money(sale, gallery)
    svc.compute_provisional_split(sale, artist, gallery)
    DB.sales[sale["id"]] = sale
    artwork["status"] = "RESERVED"
    svc.touch(artwork)
    svc.append_provenance(artwork, "RESERVED")
    return sale


@app.route("/sales", methods=["GET"])
def list_sales():
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.sales.values(),
        request.args,
        ["gallery_id", "artwork_id", "exhibition_id", "settlement_status", "shipping_status"],
    )
    if role == "Artist":
        rows = [
            s
            for s in rows
            if DB.artworks.get(s["artwork_id"], {}).get("artist_id") == uid
        ]
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_sale(s) for s in page], limit, offset, total)


@app.route("/sales/<sale_id>", methods=["GET"])
def get_sale(sale_id):
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Artist"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if role == "Artist":
        artwork = DB.artworks.get(s["artwork_id"])
        if not artwork or artwork["artist_id"] != uid:
            raise errors.forbidden()
    return response.ok(svc.ser_sale(s))


@app.route("/sales/<sale_id>/invoice", methods=["POST"])
def invoice_sale(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if s["settlement_status"] != "RESERVED":
        raise errors.invalid_state("Sale must be RESERVED to invoice.")
    s["settlement_status"] = "INVOICED"
    svc.touch(s)
    return response.ok(svc.ser_sale(s))


@app.route("/sales/<sale_id>/payments", methods=["POST"])
def post_payment(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    body = get_body()
    amount = svc.as_int(body, "amount_cents")
    expected_version = svc.as_int(body, "expected_sale_version")
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be > 0.")
    if s["settlement_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Sale must be INVOICED or PARTIALLY_PAID.")
    # OCC (priority 6).
    if expected_version != s["version"]:
        raise errors.stale_version()
    # Overpayment guard (priority 13).
    if s["amount_collected_cents"] + amount > s["buyer_total_cents"]:
        raise errors.overpayment()
    s["amount_collected_cents"] += amount
    if s["amount_collected_cents"] < s["buyer_total_cents"]:
        s["settlement_status"] = "PARTIALLY_PAID"
    svc.touch(s)
    # Advance linked ACTIVE payment plan, auto-complete when fully posted.
    plan = _active_plan_for_sale(sale_id)
    if plan is not None:
        plan["posted_installment_count"] += 1
        if plan["posted_installment_count"] >= plan["installment_count"]:
            plan["status"] = "COMPLETED"
        svc.touch(plan)
    return response.ok(svc.ser_sale(s))


def _active_plan_for_sale(sale_id):
    for p in DB.payment_plans.values():
        if p["sale_id"] == sale_id and p["status"] == "ACTIVE":
            return p
    return None


@app.route("/sales/<sale_id>/settle", methods=["POST"])
def settle_sale(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if s["settlement_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Sale must be INVOICED or PARTIALLY_PAID to settle.")
    if s["amount_collected_cents"] != s["buyer_total_cents"]:
        raise errors.invalid_state("Sale is not fully paid.")
    artwork = DB.artworks.get(s["artwork_id"])
    gallery = DB.galleries.get(s["gallery_id"])
    artist = DB.artists.get(artwork["artist_id"]) if artwork else None
    # hop1: sale SETTLED + final split
    svc.compute_final_split(s, artist, gallery)
    s["settlement_status"] = "SETTLED"
    svc.touch(s)
    # hop2: artwork RESERVED -> SOLD
    if artwork:
        artwork["status"] = "SOLD"
        svc.touch(artwork)
        svc.append_provenance(artwork, "SOLD")
        # hop3: release any PLACED wall slot held by the artwork
        for ws in DB.wall_slots.values():
            if ws["artwork_id"] == artwork["id"] and ws["status"] == "PLACED":
                ws["status"] = "RELEASED"
                svc.touch(ws)
    # ledger accrues live via artist_ledger() at read time.
    return response.ok(svc.ser_sale(s))


@app.route("/sales/<sale_id>/void", methods=["POST"])
def void_sale(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if s["settlement_status"] not in ("RESERVED", "INVOICED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Sale cannot be voided in its current state.")
    s["settlement_status"] = "VOID"
    svc.touch(s)
    artwork = DB.artworks.get(s["artwork_id"])
    if artwork and artwork["status"] == "RESERVED":
        artwork["status"] = "CONSIGNED"
        svc.touch(artwork)
        svc.append_provenance(artwork, "SALE_VOIDED")
    # Release the sale's exhibition wall slot if the artwork was placed there.
    if artwork:
        for ws in DB.wall_slots.values():
            if ws["artwork_id"] == artwork["id"] and ws["status"] == "PLACED":
                ws["status"] = "RELEASED"
                svc.touch(ws)
    # Cancel any ACTIVE payment plan.
    plan = _active_plan_for_sale(sale_id)
    if plan is not None:
        plan["status"] = "CANCELLED"
        svc.touch(plan)
    return response.ok(svc.ser_sale(s))


@app.route("/sales/<sale_id>/ship", methods=["POST"])
def ship_sale(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if s["shipping_status"] != "PENDING":
        raise errors.invalid_state("Sale shipping is not PENDING.")
    if s["settlement_status"] == "VOID":
        raise errors.invalid_state("Cannot ship a voided sale.")
    s["shipping_status"] = "SHIPPED"
    svc.touch(s)
    artwork = DB.artworks.get(s["artwork_id"])
    if artwork:
        svc.append_provenance(artwork, "SHIPPED")
    return response.ok(svc.ser_sale(s))


@app.route("/sales/<sale_id>/deliver", methods=["POST"])
def deliver_sale(sale_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    s = svc.get_or_404(DB.sales, sale_id, "Sale")
    if s["shipping_status"] != "SHIPPED":
        raise errors.invalid_state("Sale shipping must be SHIPPED to deliver.")
    s["shipping_status"] = "DELIVERED"
    svc.touch(s)
    return response.ok(svc.ser_sale(s))


# ===========================================================================
# Payment plans
# ===========================================================================
@app.route("/payment-plans", methods=["POST"])
def create_payment_plan():
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    body = get_body()
    sale_id = svc.as_str(body, "sale_id")
    count = svc.as_int(body, "installment_count")
    cadence = svc.as_int(body, "cadence_days")
    first_due = svc.parse_dt_field(body, "first_due_utc")
    if count < 2 or count > 24:
        raise errors.invalid_request("installment_count must be 2..24.")
    if cadence < 1:
        raise errors.invalid_request("cadence_days must be >= 1.")
    sale = svc.get_or_404(DB.sales, sale_id, "Sale")
    if sale["settlement_status"] != "INVOICED":
        raise errors.plan_sale_not_invoiced()
    plan = {
        "id": DB.new_id(),
        "gallery_id": sale["gallery_id"],
        "sale_id": sale_id,
        "installment_count": count,
        "cadence_days": cadence,
        "first_due_utc": first_due,
        "installment_cents": 0,
        "final_installment_cents": 0,
        "posted_installment_count": 0,
        "status": "ACTIVE",
    }
    svc.stamp_new(plan)
    svc.compute_installment_schedule(plan, sale["buyer_total_cents"])
    DB.payment_plans[plan["id"]] = plan
    return response.created(svc.ser_payment_plan(plan))


@app.route("/payment-plans", methods=["GET"])
def list_payment_plans():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.payment_plans.values(), request.args, ["gallery_id", "sale_id", "status"]
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing(
        [svc.ser_payment_plan(p) for p in page], limit, offset, total
    )


@app.route("/payment-plans/<plan_id>", methods=["GET"])
def get_payment_plan(plan_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate"})
    p = svc.get_or_404(DB.payment_plans, plan_id, "PaymentPlan")
    return response.ok(svc.ser_payment_plan(p))


@app.route("/payment-plans/<plan_id>/sweep-overdue", methods=["POST"])
def sweep_plan(plan_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    p = svc.get_or_404(DB.payment_plans, plan_id, "PaymentPlan")
    if p["status"] != "ACTIVE":
        raise errors.invalid_state("Plan must be ACTIVE to sweep.")
    if svc.plan_missed_count(p) >= svc.MAX_MISSED_INSTALLMENTS:
        p["status"] = "DEFAULTED"
        svc.touch(p)
    return response.ok(svc.ser_payment_plan(p))


# ===========================================================================
# Leases
# ===========================================================================
@app.route("/leases", methods=["POST"])
def create_lease():
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    body = get_body()
    artwork_id = svc.as_str(body, "artwork_id")
    lessee = svc.as_str(body, "lessee_name")
    rate = svc.as_int(body, "monthly_rate_cents")
    term = svc.as_int(body, "term_months")
    starts = svc.parse_dt_field(body, "starts_utc")
    credit = svc.as_int(body, "purchase_credit_bps", required=False, default=0)
    if rate <= 0:
        raise errors.invalid_request("monthly_rate_cents must be > 0.")
    if term < 1:
        raise errors.invalid_request("term_months must be >= 1.")
    if credit < 0 or credit > 10000:
        raise errors.invalid_request("purchase_credit_bps must be 0..10000.")
    artwork = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    if artwork["status"] != "CONSIGNED":
        raise errors.invalid_state("Artwork must be CONSIGNED to lease.")
    lease = {
        "id": DB.new_id(),
        "gallery_id": artwork["gallery_id"],
        "artwork_id": artwork_id,
        "lessee_name": lessee,
        "monthly_rate_cents": rate,
        "term_months": term,
        "starts_utc": starts,
        "purchase_credit_bps": credit,
        "status": "ACTIVE",
    }
    svc.stamp_new(lease)
    DB.leases[lease["id"]] = lease
    artwork["status"] = "ON_LOAN"
    svc.touch(artwork)
    return response.created(svc.ser_lease(lease))


@app.route("/leases", methods=["GET"])
def list_leases():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.leases.values(), request.args, ["gallery_id", "artwork_id", "status"]
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_lease(l) for l in page], limit, offset, total)


@app.route("/leases/<lease_id>", methods=["GET"])
def get_lease(lease_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar"})
    l = svc.get_or_404(DB.leases, lease_id, "LeaseAgreement")
    return response.ok(svc.ser_lease(l))


@app.route("/leases/<lease_id>/convert", methods=["POST"])
def convert_lease(lease_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    lease = svc.get_or_404(DB.leases, lease_id, "LeaseAgreement")
    if lease["status"] != "ACTIVE":
        raise errors.invalid_state("Lease must be ACTIVE to convert.")
    artwork = DB.artworks.get(lease["artwork_id"])
    if not artwork or artwork["status"] != "ON_LOAN":
        raise errors.lease_artwork_not_out()
    _months, _rent, buyout = svc.compute_lease_figures(lease)
    gallery = DB.galleries.get(lease["gallery_id"])
    artist = DB.artists.get(artwork["artist_id"]) if artwork else None
    # Build the sale directly (artwork is ON_LOAN -> RESERVED, not CONSIGNED).
    sale = {
        "id": DB.new_id(),
        "gallery_id": lease["gallery_id"],
        "artwork_id": artwork["id"],
        "exhibition_id": None,
        "buyer_name": lease["lessee_name"],
        "buyer_state_code": gallery["home_state_code"] if gallery else "NA",
        "gross_amount_cents": buyout,
        "discount_bps": 0,
        "shipping_cents": 0,
        "net_amount_cents": 0,
        "tax_amount_cents": 0,
        "buyer_total_cents": 0,
        "artist_share_cents": 0,
        "gallery_share_cents": 0,
        "amount_collected_cents": 0,
        "settlement_status": "RESERVED",
        "shipping_status": "PENDING",
    }
    svc.stamp_new(sale)
    svc.compute_sale_money(sale, gallery)
    svc.compute_provisional_split(sale, artist, gallery)
    DB.sales[sale["id"]] = sale
    artwork["status"] = "RESERVED"
    svc.touch(artwork)
    svc.append_provenance(artwork, "RESERVED")
    lease["status"] = "CONVERTED"
    svc.touch(lease)
    return response.ok(svc.ser_lease(lease))


@app.route("/leases/<lease_id>/return", methods=["POST"])
def return_lease(lease_id):
    _uid, role = authenticate()
    require_role(role, {"SalesAssociate", "GalleryAdmin"})
    lease = svc.get_or_404(DB.leases, lease_id, "LeaseAgreement")
    if lease["status"] != "ACTIVE":
        raise errors.invalid_state("Lease must be ACTIVE to return.")
    artwork = DB.artworks.get(lease["artwork_id"])
    lease["status"] = "RETURNED"
    svc.touch(lease)
    if artwork and artwork["status"] == "ON_LOAN":
        artwork["status"] = "CONSIGNED"
        svc.touch(artwork)
        svc.append_provenance(artwork, "LEASE_RETURNED")
    return response.ok(svc.ser_lease(lease))


@app.route("/leases/<lease_id>/terminate", methods=["POST"])
def terminate_lease(lease_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    lease = svc.get_or_404(DB.leases, lease_id, "LeaseAgreement")
    if lease["status"] != "ACTIVE":
        raise errors.invalid_state("Lease must be ACTIVE to terminate.")
    artwork = DB.artworks.get(lease["artwork_id"])
    lease["status"] = "TERMINATED"
    svc.touch(lease)
    if artwork and artwork["status"] == "ON_LOAN":
        artwork["status"] = "CONSIGNED"
        svc.touch(artwork)
    return response.ok(svc.ser_lease(lease))


# ===========================================================================
# Opening events + RSVP
# ===========================================================================
@app.route("/opening-events", methods=["POST"])
def create_opening_event():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    exhibition_id = svc.as_str(body, "exhibition_id")
    capacity = svc.as_int(body, "capacity")
    starts = svc.parse_dt_field(body, "starts_utc")
    deadline = svc.parse_dt_field(body, "rsvp_deadline_utc")
    if capacity <= 0:
        raise errors.invalid_request("capacity must be > 0.")
    if deadline > starts:
        raise errors.invalid_request("rsvp_deadline_utc must be at or before starts_utc.")
    ex = svc.get_or_404(DB.exhibitions, exhibition_id, "Exhibition")
    ev = {
        "id": DB.new_id(),
        "gallery_id": ex["gallery_id"],
        "exhibition_id": exhibition_id,
        "capacity": capacity,
        "starts_utc": starts,
        "rsvp_deadline_utc": deadline,
        "status": "SCHEDULED",
    }
    svc.stamp_new(ev)
    DB.opening_events[ev["id"]] = ev
    return response.created(svc.ser_opening_event(ev))


@app.route("/opening-events", methods=["GET"])
def list_opening_events():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.opening_events.values(), request.args, ["gallery_id", "exhibition_id", "status"]
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing(
        [svc.ser_opening_event(e) for e in page], limit, offset, total
    )


@app.route("/opening-events/<event_id>", methods=["GET"])
def get_opening_event(event_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar", "Artist"})
    ev = svc.get_or_404(DB.opening_events, event_id, "OpeningEvent")
    return response.ok(svc.ser_opening_event(ev))


@app.route("/opening-events/<event_id>/close", methods=["POST"])
def close_event(event_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    ev = svc.get_or_404(DB.opening_events, event_id, "OpeningEvent")
    if ev["status"] != "SCHEDULED":
        raise errors.invalid_state("Event must be SCHEDULED to close.")
    ev["status"] = "CLOSED"
    svc.touch(ev)
    return response.ok(svc.ser_opening_event(ev))


@app.route("/opening-events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    ev = svc.get_or_404(DB.opening_events, event_id, "OpeningEvent")
    if ev["status"] != "SCHEDULED":
        raise errors.invalid_state("Event must be SCHEDULED to cancel.")
    ev["status"] = "CANCELLED"
    svc.touch(ev)
    for r in DB.rsvps.values():
        if r["opening_event_id"] == event_id and r["status"] in (
            "CONFIRMED",
            "WAITLISTED",
        ):
            r["status"] = "CANCELLED"
            svc.touch(r)
    return response.ok(svc.ser_opening_event(ev))


@app.route("/rsvps", methods=["POST"])
def create_rsvp():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate"})
    body = get_body()
    event_id = svc.as_str(body, "opening_event_id")
    guest = svc.as_str(body, "guest_name")
    party = svc.as_int(body, "party_size", required=False, default=1)
    if party < 1 or party > 10:
        raise errors.invalid_request("party_size must be 1..10.")
    ev = svc.get_or_404(DB.opening_events, event_id, "OpeningEvent")
    # RSVP deadline / event-state guard (priority 11).
    if ev["status"] != "SCHEDULED" or DB.clock_utc > ev["rsvp_deadline_utc"]:
        raise errors.rsvp_closed()
    # party_size must be <= capacity (priority 12).
    if party > ev["capacity"]:
        raise errors.invalid_request("party_size must be <= capacity.")
    seats = svc.confirmed_seats(event_id)
    status = "CONFIRMED" if seats + party <= ev["capacity"] else "WAITLISTED"
    rsvp = {
        "id": DB.new_id(),
        "gallery_id": ev["gallery_id"],
        "opening_event_id": event_id,
        "guest_name": guest,
        "party_size": party,
        "status": status,
    }
    svc.stamp_new(rsvp)
    DB.rsvps[rsvp["id"]] = rsvp
    return response.created(svc.ser_rsvp(rsvp))


@app.route("/rsvps", methods=["GET"])
def list_rsvps():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.rsvps.values(), request.args, ["gallery_id", "opening_event_id", "status"]
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_rsvp(r) for r in page], limit, offset, total)


@app.route("/rsvps/<rsvp_id>", methods=["GET"])
def get_rsvp(rsvp_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate", "Registrar"})
    r = svc.get_or_404(DB.rsvps, rsvp_id, "Rsvp")
    return response.ok(svc.ser_rsvp(r))


@app.route("/rsvps/<rsvp_id>/cancel", methods=["POST"])
def cancel_rsvp(rsvp_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "SalesAssociate"})
    r = svc.get_or_404(DB.rsvps, rsvp_id, "Rsvp")
    if r["status"] == "CONFIRMED":
        ev = DB.opening_events.get(r["opening_event_id"])
        if not ev or ev["status"] != "SCHEDULED":
            raise errors.invalid_state("Event must be SCHEDULED to cancel a confirmed RSVP.")
        r["status"] = "CANCELLED"
        svc.touch(r)
        _promote_waitlist(r["opening_event_id"])
    elif r["status"] == "WAITLISTED":
        r["status"] = "CANCELLED"
        svc.touch(r)
    else:
        raise errors.invalid_state("RSVP cannot be cancelled in its current state.")
    return response.ok(svc.ser_rsvp(r))


def _promote_waitlist(event_id):
    """Promote earliest-created WAITLISTED RSVPs that fit, no skip-ahead."""
    ev = DB.opening_events.get(event_id)
    if not ev:
        return
    waitlisted = sorted(
        [
            r
            for r in DB.rsvps.values()
            if r["opening_event_id"] == event_id and r["status"] == "WAITLISTED"
        ],
        key=lambda r: r["_seq"],
    )
    for r in waitlisted:
        seats_free = ev["capacity"] - svc.confirmed_seats(event_id)
        if r["party_size"] <= seats_free:
            r["status"] = "PROMOTED"
            svc.touch(r)
        else:
            break


# ===========================================================================
# Loans
# ===========================================================================
@app.route("/loans", methods=["POST"])
def create_loan():
    _uid, role = authenticate()
    require_role(role, {"Registrar", "GalleryAdmin"})
    body = get_body()
    artwork_id = svc.as_str(body, "artwork_id")
    borrower = svc.as_str(body, "borrower_name")
    coverage = svc.as_int(body, "coverage_value_cents")
    out_utc = svc.parse_dt_field(body, "out_utc")
    due_utc = svc.parse_dt_field(body, "due_utc")
    if coverage <= 0:
        raise errors.invalid_request("coverage_value_cents must be > 0.")
    if due_utc <= out_utc:
        raise errors.invalid_request("due_utc must be strictly after out_utc.")
    artwork = svc.get_or_404(DB.artworks, artwork_id, "Artwork")
    if artwork["status"] != "CONSIGNED":
        raise errors.invalid_state("Artwork must be CONSIGNED to loan out.")
    # Coverage adequacy (priority 8) BEFORE schedule conflict (priority 9).
    if coverage < artwork["insured_value_cents"]:
        raise errors.insufficient_coverage()
    # Schedule conflict against full loan history (half-open windows).
    for other in DB.loans.values():
        if other["artwork_id"] != artwork_id:
            continue
        if out_utc < other["due_utc"] and other["out_utc"] < due_utc:
            raise errors.schedule_conflict()
    loan = {
        "id": DB.new_id(),
        "gallery_id": artwork["gallery_id"],
        "artwork_id": artwork_id,
        "borrower_name": borrower,
        "coverage_value_cents": coverage,
        "out_utc": out_utc,
        "due_utc": due_utc,
        "returned_utc": None,
        "status": "OUTSTANDING",
    }
    svc.stamp_new(loan)
    DB.loans[loan["id"]] = loan
    artwork["status"] = "ON_LOAN"
    svc.touch(artwork)
    svc.append_provenance(artwork, "LOANED_OUT")
    return response.created(svc.ser_loan(loan))


@app.route("/loans", methods=["GET"])
def list_loans():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.loans.values(), request.args, ["gallery_id", "artwork_id", "status"]
    )
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_loan(l) for l in page], limit, offset, total)


@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Registrar"})
    l = svc.get_or_404(DB.loans, loan_id, "Loan")
    return response.ok(svc.ser_loan(l))


@app.route("/loans/<loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    _uid, role = authenticate()
    require_role(role, {"Registrar", "GalleryAdmin"})
    l = svc.get_or_404(DB.loans, loan_id, "Loan")
    if l["status"] not in ("OUTSTANDING", "OVERDUE"):
        raise errors.invalid_state("Loan must be OUTSTANDING or OVERDUE to return.")
    l["status"] = "RETURNED"
    l["returned_utc"] = DB.clock_utc
    svc.touch(l)
    artwork = DB.artworks.get(l["artwork_id"])
    if artwork and artwork["status"] == "ON_LOAN":
        artwork["status"] = "CONSIGNED"
        svc.touch(artwork)
        svc.append_provenance(artwork, "LOAN_RETURNED")
    return response.ok(svc.ser_loan(l))


@app.route("/loans/<loan_id>/sweep-overdue", methods=["POST"])
def sweep_loan(loan_id):
    _uid, role = authenticate()
    require_role(role, {"Registrar", "GalleryAdmin"})
    l = svc.get_or_404(DB.loans, loan_id, "Loan")
    if l["status"] != "OUTSTANDING":
        raise errors.invalid_state("Loan must be OUTSTANDING to sweep.")
    if DB.clock_utc < l["due_utc"]:
        raise errors.invalid_state("Clock has not reached due_utc.")
    l["status"] = "OVERDUE"
    svc.touch(l)
    return response.ok(svc.ser_loan(l))


# ===========================================================================
# Payouts + reporting
# ===========================================================================
@app.route("/payouts", methods=["POST"])
def create_payout():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    body = get_body()
    artist_id = svc.as_str(body, "artist_id")
    requested = svc.as_int(body, "requested_cents")
    if requested <= 0:
        raise errors.invalid_request("requested_cents must be > 0.")
    artist = svc.get_or_404(DB.artists, artist_id, "Artist")
    if artist["status"] == "SUSPENDED":
        raise errors.artist_suspended()
    _accrued, _paid, payable = svc.artist_ledger(artist_id)
    if payable <= 0:
        raise errors.no_payable_balance()
    approved = min(requested, payable)
    payout = {
        "id": DB.new_id(),
        "gallery_id": artist["gallery_id"],
        "artist_id": artist_id,
        "requested_cents": requested,
        "approved_cents": approved,
        "status": "PENDING",
    }
    svc.stamp_new(payout)
    DB.payouts[payout["id"]] = payout
    return response.created(svc.ser_payout(payout))


@app.route("/payouts", methods=["GET"])
def list_payouts():
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Artist"})
    limit, offset = svc.parse_pagination(request.args)
    rows = list_filter(
        DB.payouts.values(), request.args, ["gallery_id", "artist_id", "status"]
    )
    if role == "Artist":
        rows = [p for p in rows if p["artist_id"] == uid]
    page, total = svc.paginate(rows, limit, offset)
    return response.listing([svc.ser_payout(p) for p in page], limit, offset, total)


@app.route("/payouts/<payout_id>", methods=["GET"])
def get_payout(payout_id):
    uid, role = authenticate()
    require_role(role, {"GalleryAdmin", "Artist"})
    p = svc.get_or_404(DB.payouts, payout_id, "Payout")
    if role == "Artist" and p["artist_id"] != uid:
        raise errors.forbidden()
    return response.ok(svc.ser_payout(p))


@app.route("/payouts/<payout_id>/complete", methods=["POST"])
def complete_payout(payout_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    p = svc.get_or_404(DB.payouts, payout_id, "Payout")
    if p["status"] != "PENDING":
        raise errors.invalid_state("Payout must be PENDING to complete.")
    p["status"] = "COMPLETED"
    svc.touch(p)
    # ledger_paid reflects COMPLETED payouts live via artist_ledger().
    return response.ok(svc.ser_payout(p))


@app.route("/payouts/<payout_id>/reverse", methods=["POST"])
def reverse_payout(payout_id):
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    p = svc.get_or_404(DB.payouts, payout_id, "Payout")
    if p["status"] != "COMPLETED":
        raise errors.invalid_state("Payout must be COMPLETED to reverse.")
    p["status"] = "REVERSED"
    svc.touch(p)
    return response.ok(svc.ser_payout(p))


@app.route("/reports/sales-summary", methods=["GET"])
def sales_summary():
    _uid, role = authenticate()
    require_role(role, {"GalleryAdmin"})
    from_utc = None
    to_utc = None
    if request.args.get("from_utc"):
        try:
            from_utc = clockmod.parse_iso(request.args.get("from_utc"))
        except (ValueError, TypeError):
            raise errors.invalid_request("from_utc must be an ISO 8601 instant.")
    if request.args.get("to_utc"):
        try:
            to_utc = clockmod.parse_iso(request.args.get("to_utc"))
        except (ValueError, TypeError):
            raise errors.invalid_request("to_utc must be an ISO 8601 instant.")

    count = 0
    gross = net = tax = shipping = artist_share = gallery_share = 0
    for s in DB.sales.values():
        if s["settlement_status"] != "SETTLED":
            continue
        when = s["updated_at"]
        if from_utc is not None and when < from_utc:
            continue
        if to_utc is not None and when > to_utc:
            continue
        count += 1
        gross += s["gross_amount_cents"]
        net += s["net_amount_cents"]
        tax += s["tax_amount_cents"]
        shipping += s["shipping_cents"]
        artist_share += s["artist_share_cents"]
        gallery_share += s["gallery_share_cents"]

    return response.ok(
        {
            "settled_sale_count": count,
            "gross_total_cents": gross,
            "net_total_cents": net,
            "tax_total_cents": tax,
            "shipping_total_cents": shipping,
            "artist_share_total_cents": artist_share,
            "gallery_share_total_cents": gallery_share,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
