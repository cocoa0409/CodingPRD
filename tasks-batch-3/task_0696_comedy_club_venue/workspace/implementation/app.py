"""Comedy Club & Live-Show Venue API — Flask entry point.

In-memory only. No seeding at startup. Boots clean on every invocation.
"""
import os

from flask import Flask, request

import clock
import errors
import serialize as S
import services as svc
import validate as V
from db import db, new_id
from errors import ApiError
from middleware import get_identity, require_roles
from response import created, ok, list_response, error as err_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return err_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_INTERNAL", str(e), 500)


# ===========================================================================
# List / pagination helper (sort by created_at ASC, PRD §2.3)
# ===========================================================================
def paginate_and_list(records, serializer):
    limit, offset = V.pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)


def auth(allowed_roles):
    """Run priority-1 (auth presence) then priority-2 (RBAC). Returns (uid, role)."""
    user_id, role = get_identity()
    require_roles(role, allowed_roles)
    return user_id, role


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"FloorManager", "Booker", "BoxOffice"})
    data = V.body()
    iso = V.require_iso(data, "to_iso8601")
    clock.set_now(iso)
    return ok({})


# ===========================================================================
# Venues
# ===========================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    auth({"Booker"})
    data = V.body()
    name = V.require_str(data, "name")
    currency = V.require_str(data, "settlement_currency")
    house_fee_pct = V.opt_pct(data, "house_fee_pct", svc.DEFAULT_HOUSE_FEE_PCT)
    rec = {
        "id": new_id(),
        "name": name,
        "settlement_currency": currency,
        "house_fee_pct": house_fee_pct,
        "posture": "OPEN",
        "_closed": False,
    }
    svc.stamp_create(rec)
    db.venues[rec["id"]] = rec
    return created(S.venue(rec))


@app.route("/venues/<venue_id>", methods=["GET"])
def read_venue(venue_id):
    auth({"Booker", "BoxOffice", "FloorManager"})
    rec = svc.get_or_404(db.venues, venue_id)
    return ok(S.venue(rec))


@app.route("/venues/<venue_id>/close", methods=["POST"])
def close_venue(venue_id):
    auth({"Booker"})
    rec = svc.get_or_404(db.venues, venue_id)
    rec["_closed"] = True
    svc.recompute_venue_posture(rec)
    svc.touch(rec)
    return ok(S.venue(rec))


# ===========================================================================
# Shows
# ===========================================================================
@app.route("/venues/<venue_id>/shows", methods=["POST"])
def create_show(venue_id):
    auth({"Booker"})
    venue = svc.get_or_404(db.venues, venue_id)
    data = V.body()
    title = V.require_str(data, "title")
    starts_at = V.require_iso(data, "starts_at")
    ends_at = V.require_iso(data, "ends_at")
    doors_buffer = V.opt_int(data, "doors_buffer_minutes",
                             svc.DEFAULT_DOORS_BUFFER_MINUTES, minimum=0)
    # ends_at strictly after starts_at (PRD §3.1)
    s_dt = clock.parse_iso8601(starts_at)
    e_dt = clock.parse_iso8601(ends_at)
    if not (e_dt > s_dt):
        raise errors.invalid_request("ends_at must be strictly after starts_at")

    # Posture gate (priority 8): venue CLOSED blocks new shows.
    if venue["posture"] == "CLOSED":
        raise ApiError(errors.ERR_POSTURE_BLOCKED, 409, "Venue is closed")

    # Room overlap (priority 12): [starts_at - doors_buffer, ends_at] must not
    # overlap any other non-CANCELLED show at the same venue.
    from datetime import timedelta
    new_start = s_dt - timedelta(minutes=doors_buffer)
    new_end = e_dt
    for other in db.shows.values():
        if other["venue_id"] != venue_id or other["status"] == "CANCELLED":
            continue
        o_start = clock.parse_iso8601(other["starts_at"]) - timedelta(
            minutes=other["doors_buffer_minutes"])
        o_end = clock.parse_iso8601(other["ends_at"])
        if new_start < o_end and o_start < new_end:
            raise ApiError(errors.ERR_SHOW_TIME_CONFLICT, 409,
                           "Show window overlaps another show at this venue")

    rec = {
        "id": new_id(),
        "venue_id": venue_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "doors_buffer_minutes": doors_buffer,
        "status": "DRAFT",
        "is_private": False,
        "ga_sold_count": 0,
    }
    svc.stamp_create(rec)
    db.shows[rec["id"]] = rec
    return created(S.show(rec))


@app.route("/shows/<show_id>", methods=["GET"])
def read_show(show_id):
    auth({"Booker", "BoxOffice", "FloorManager"})
    rec = svc.get_or_404(db.shows, show_id)
    return ok(S.show(rec))


@app.route("/shows", methods=["GET"])
def list_shows():
    auth({"Booker", "BoxOffice", "FloorManager"})
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    recs = [s for s in db.shows.values()
            if (venue_id is None or s["venue_id"] == venue_id)
            and (status is None or s["status"] == status)]
    return paginate_and_list(recs, S.show)


@app.route("/venues/<venue_id>/shows/<show_id>/publish", methods=["POST"])
def publish_show(venue_id, show_id):
    auth({"Booker"})
    venue = svc.get_or_404(db.venues, venue_id)
    show = svc.get_or_404(db.shows, show_id)
    if show["venue_id"] != venue_id:
        raise errors.not_found()
    # State (priority 6): only DRAFT may publish.
    if show["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT show can be published")
    # Preconditions: >=1 section, >=1 tier, no HELD/CONFIRMED private event.
    has_section = any(s["show_id"] == show_id for s in db.sections.values())
    has_tier = any(t["show_id"] == show_id for t in db.tiers.values())
    if not has_section:
        raise errors.invalid_state("Show must have at least one seating section")
    if not has_tier:
        raise errors.invalid_state("Show must have at least one ticket tier")
    has_buyout = any(pe["show_id"] == show_id and pe["status"] in ("HELD", "CONFIRMED")
                     for pe in db.private_events.values())
    if has_buyout:
        raise errors.invalid_state("A held/confirmed private event blocks publishing")
    # Posture gate (priority 8): venue not CLOSED.
    if venue["posture"] == "CLOSED":
        raise ApiError(errors.ERR_POSTURE_BLOCKED, 409, "Venue is closed")
    show["status"] = "ON_SALE"
    svc.touch(show)
    return ok(S.show(show))


@app.route("/venues/<venue_id>/shows/<show_id>/cancel", methods=["POST"])
def cancel_show(venue_id, show_id):
    auth({"Booker"})
    svc.get_or_404(db.venues, venue_id)
    show = svc.get_or_404(db.shows, show_id)
    if show["venue_id"] != venue_id:
        raise errors.not_found()
    # State: not SETTLING or SETTLED.
    if show["status"] in ("SETTLING", "SETTLED"):
        raise errors.invalid_state("A settling/settled show cannot be cancelled")

    # CASCADE 1: active reservations -> CANCELLED with full refund.
    for r in db.reservations.values():
        if r["show_id"] != show_id:
            continue
        if r["booking_status"] in ("BOOKED", "SEATED", "CHECKED_IN"):
            r["refunded_cents"] = svc.compute_refund_show_cancel(r)
            r["booking_status"] = "CANCELLED"
            r["settlement_status"] = "REFUNDED"
            # void tickets
            for tk in db.tickets.values():
                if tk["reservation_id"] == r["id"] and tk["scan_state"] in ("ISSUED", "SCANNED"):
                    tk["scan_state"] = "VOID"
            # release table
            if r.get("table_id"):
                tbl = db.tables.get(r["table_id"])
                if tbl is not None:
                    tbl["status"] = "AVAILABLE"
                    svc.touch(tbl)
                    if tbl.get("assigned_server_id"):
                        srv = db.servers.get(tbl["assigned_server_id"])
                        if srv:
                            svc.recompute_assigned_table_count(srv)
                            svc.touch(srv)
                r["table_id"] = None
            svc.touch(r)

    # CASCADE 2: lineup slots OFFERED/COUNTERED/SIGNED -> DROPPED.
    for ls in db.lineup_slots.values():
        if ls["show_id"] == show_id and ls["contract_status"] in ("OFFERED", "COUNTERED", "SIGNED"):
            ls["contract_status"] = "DROPPED"
            svc.touch(ls)

    # CASCADE 3: HELD/CONFIRMED private events -> CANCELLED (deposit retained).
    for pe in db.private_events.values():
        if pe["show_id"] == show_id and pe["status"] in ("HELD", "CONFIRMED"):
            pe["status"] = "CANCELLED"
            svc.touch(pe)

    show["status"] = "CANCELLED"
    svc.recompute_is_private(show)
    svc.recompute_ga_sold_count(show)
    svc.touch(show)
    return ok(S.show(show))


# ===========================================================================
# Sections
# ===========================================================================
@app.route("/venues/<venue_id>/shows/<show_id>/sections", methods=["POST"])
def create_section(venue_id, show_id):
    auth({"Booker"})
    svc.get_or_404(db.venues, venue_id)
    show = svc.get_or_404(db.shows, show_id)
    if show["venue_id"] != venue_id:
        raise errors.not_found()
    data = V.body()
    kind = V.require_enum(data, "kind", {"GA", "RESERVED", "TABLE"})
    label = V.require_str(data, "label")
    ga_capacity = V.opt_int(data, "ga_capacity", None, minimum=0)
    # ga_capacity required iff kind in {GA, RESERVED}; must be omitted for TABLE.
    if kind in ("GA", "RESERVED"):
        if ga_capacity is None:
            raise errors.invalid_request("ga_capacity is required for GA/RESERVED sections")
    else:  # TABLE
        if ga_capacity is not None:
            raise errors.invalid_request("ga_capacity must be omitted for TABLE sections")
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "kind": kind,
        "label": label,
        "ga_capacity": ga_capacity,
    }
    svc.stamp_create(rec)
    db.sections[rec["id"]] = rec
    return created(S.section(rec))


@app.route("/sections/<section_id>", methods=["GET"])
def read_section(section_id):
    auth({"Booker", "BoxOffice", "FloorManager"})
    rec = svc.get_or_404(db.sections, section_id)
    return ok(S.section(rec))


@app.route("/sections", methods=["GET"])
def list_sections():
    auth({"Booker", "BoxOffice", "FloorManager"})
    show_id = request.args.get("show_id")
    recs = [s for s in db.sections.values()
            if show_id is None or s["show_id"] == show_id]
    return paginate_and_list(recs, S.section)


# ===========================================================================
# Tables
# ===========================================================================
@app.route("/venues/<venue_id>/shows/<show_id>/sections/<section_id>/tables", methods=["POST"])
def create_table(venue_id, show_id, section_id):
    auth({"Booker", "FloorManager"})
    svc.get_or_404(db.venues, venue_id)
    show = svc.get_or_404(db.shows, show_id)
    if show["venue_id"] != venue_id:
        raise errors.not_found()
    section = svc.get_or_404(db.sections, section_id)
    if section["show_id"] != show_id:
        raise errors.not_found()
    data = V.body()
    table_number = V.require_str(data, "table_number")
    seats = V.require_int(data, "seats", minimum=1)
    min_items = V.opt_int(data, "min_items_per_seat",
                          svc.VENUE_DEFAULT_MIN_ITEMS, minimum=0)
    # Section must be kind=TABLE.
    if section["kind"] != "TABLE":
        raise ApiError(errors.ERR_WRONG_SECTION_KIND, 409,
                       "Tables can only be created under a TABLE section")
    # table_number unique within section among non-RETIRED tables.
    for t in db.tables.values():
        if t["section_id"] == section_id and t["status"] != "RETIRED" \
                and t["table_number"] == table_number:
            raise errors.invalid_request("table_number must be unique within the section")
    rec = {
        "id": new_id(),
        "section_id": section_id,
        "table_number": table_number,
        "seats": seats,
        "min_items_per_seat": min_items,
        "assigned_server_id": None,
        "status": "AVAILABLE",
    }
    svc.stamp_create(rec)
    db.tables[rec["id"]] = rec
    return created(S.table(rec))


@app.route("/tables/<table_id>", methods=["GET"])
def read_table(table_id):
    auth({"Booker", "BoxOffice", "FloorManager"})
    rec = svc.get_or_404(db.tables, table_id)
    return ok(S.table(rec))


@app.route("/tables", methods=["GET"])
def list_tables():
    auth({"Booker", "BoxOffice", "FloorManager"})
    section_id = request.args.get("section_id")
    server_id = request.args.get("assigned_server_id")
    recs = [t for t in db.tables.values()
            if (section_id is None or t["section_id"] == section_id)
            and (server_id is None or t.get("assigned_server_id") == server_id)]
    return paginate_and_list(recs, S.table)


@app.route("/tables/<table_id>/assign-server", methods=["POST"])
def assign_server(table_id):
    auth({"FloorManager"})
    table = svc.get_or_404(db.tables, table_id)
    data = V.body()
    server_id = V.require_str(data, "server_id")
    server = db.servers.get(server_id)
    if server is None:
        raise errors.not_found()
    # Server load: assignment must not push assigned_table_count above max_tables.
    # Count the prospective state (this table will point at the server if it
    # isn't already and isn't retired).
    already = (table.get("assigned_server_id") == server_id and table["status"] != "RETIRED")
    prospective = svc.recompute_assigned_table_count(server)
    if not already and table["status"] != "RETIRED":
        prospective += 1
    if prospective > server["max_tables"]:
        raise ApiError(errors.ERR_SERVER_OVERLOADED, 409,
                       "Assignment would exceed the server's max_tables")
    prev_server_id = table.get("assigned_server_id")
    table["assigned_server_id"] = server_id
    svc.touch(table)
    svc.recompute_assigned_table_count(server)
    svc.touch(server)
    if prev_server_id and prev_server_id != server_id:
        prev = db.servers.get(prev_server_id)
        if prev:
            svc.recompute_assigned_table_count(prev)
            svc.touch(prev)
    return ok(S.table(table))


@app.route("/tables/<table_id>/retire", methods=["POST"])
def retire_table(table_id):
    auth({"FloorManager"})
    table = svc.get_or_404(db.tables, table_id)
    # Only AVAILABLE (no active hold).
    if table["status"] != "AVAILABLE":
        raise errors.invalid_state("Only an AVAILABLE table can be retired")
    table["status"] = "RETIRED"
    svc.touch(table)
    if table.get("assigned_server_id"):
        srv = db.servers.get(table["assigned_server_id"])
        if srv:
            svc.recompute_assigned_table_count(srv)
            svc.touch(srv)
    return ok(S.table(table))


# ===========================================================================
# Ticket tiers
# ===========================================================================
@app.route("/venues/<venue_id>/shows/<show_id>/tiers", methods=["POST"])
def create_tier(venue_id, show_id):
    auth({"Booker"})
    svc.get_or_404(db.venues, venue_id)
    show = svc.get_or_404(db.shows, show_id)
    if show["venue_id"] != venue_id:
        raise errors.not_found()
    data = V.body()
    section_id = V.require_str(data, "section_id")
    name = V.require_str(data, "name")
    price_cents = V.require_int(data, "price_cents", minimum=0)
    min_items_override = V.opt_int(data, "min_items_override", None, minimum=0)
    section = db.sections.get(section_id)
    if section is None:
        raise errors.not_found()
    # Section must belong to the same show.
    if section["show_id"] != show_id:
        raise ApiError(errors.ERR_CROSS_SHOW_REFERENCE, 409,
                       "Tier section must belong to the same show")
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "section_id": section_id,
        "name": name,
        "price_cents": price_cents,
        "min_items_override": min_items_override,
    }
    svc.stamp_create(rec)
    db.tiers[rec["id"]] = rec
    return created(S.tier(rec))


@app.route("/tiers/<tier_id>", methods=["GET"])
def read_tier(tier_id):
    auth({"Booker", "BoxOffice", "FloorManager"})
    rec = svc.get_or_404(db.tiers, tier_id)
    return ok(S.tier(rec))


@app.route("/tiers", methods=["GET"])
def list_tiers():
    auth({"Booker", "BoxOffice", "FloorManager"})
    show_id = request.args.get("show_id")
    section_id = request.args.get("section_id")
    recs = [t for t in db.tiers.values()
            if (show_id is None or t["show_id"] == show_id)
            and (section_id is None or t["section_id"] == section_id)]
    return paginate_and_list(recs, S.tier)


# ===========================================================================
# Performers
# ===========================================================================
@app.route("/performers", methods=["POST"])
def create_performer():
    auth({"Booker"})
    data = V.body()
    stage_name = V.require_str(data, "stage_name")
    email = V.require_str(data, "email")
    standard_fee = V.require_int(data, "standard_fee_cents", minimum=0)
    rec = {
        "id": new_id(),
        "stage_name": stage_name,
        "email": email,
        "standard_fee_cents": standard_fee,
    }
    svc.stamp_create(rec)
    db.performers[rec["id"]] = rec
    return created(S.performer(rec))


@app.route("/performers/<performer_id>", methods=["GET"])
def read_performer(performer_id):
    auth({"Booker", "FloorManager", "Performer"})
    rec = svc.get_or_404(db.performers, performer_id)
    return ok(S.performer(rec))


# ===========================================================================
# Lineup slots / contracts
# ===========================================================================
@app.route("/lineup-slots", methods=["POST"])
def create_lineup_slot():
    auth({"Booker"})
    data = V.body()
    show_id = V.require_str(data, "show_id")
    performer_id = V.require_str(data, "performer_id")
    slot_order = V.require_int(data, "slot_order")
    role = V.require_enum(data, "role", {"HOST", "OPENER", "FEATURE", "HEADLINER"})
    offered_fee = V.require_int(data, "offered_fee_cents", minimum=0)
    if show_id not in db.shows:
        raise errors.not_found()
    if performer_id not in db.performers:
        raise errors.not_found()
    # slot_order unique per show among non-DROPPED slots.
    for ls in db.lineup_slots.values():
        if ls["show_id"] == show_id and ls["contract_status"] != "DROPPED" \
                and ls["slot_order"] == slot_order:
            raise errors.invalid_request("slot_order must be unique per show among active slots")
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "performer_id": performer_id,
        "slot_order": slot_order,
        "role": role,
        "offered_fee_cents": offered_fee,
        "agreed_fee_cents": None,
        "contract_status": "OFFERED",
        "counter_rounds": 0,
    }
    svc.stamp_create(rec)
    db.lineup_slots[rec["id"]] = rec
    return created(S.lineup_slot(rec))


@app.route("/lineup-slots/<lineup_slot_id>", methods=["GET"])
def read_lineup_slot(lineup_slot_id):
    auth({"Booker", "FloorManager", "Performer"})
    rec = svc.get_or_404(db.lineup_slots, lineup_slot_id)
    return ok(S.lineup_slot(rec))


@app.route("/lineup-slots", methods=["GET"])
def list_lineup_slots():
    auth({"Booker", "FloorManager", "Performer"})
    show_id = request.args.get("show_id")
    performer_id = request.args.get("performer_id")
    recs = [ls for ls in db.lineup_slots.values()
            if (show_id is None or ls["show_id"] == show_id)
            and (performer_id is None or ls["performer_id"] == performer_id)]
    return paginate_and_list(recs, S.lineup_slot)


@app.route("/lineup-slots/<lineup_slot_id>/counter", methods=["POST"])
def counter_slot(lineup_slot_id):
    uid, role = auth({"Performer"})
    ls = svc.get_or_404(db.lineup_slots, lineup_slot_id)
    # Ownership (priority 4): Performer X-User-ID == performer_id.
    if ls["performer_id"] != uid:
        raise ApiError(errors.ERR_NOT_OWNER, 403, "Not the owner of this lineup slot")
    data = V.body()
    counter_fee = V.require_int(data, "counter_fee_cents", minimum=0)
    # State: must be OFFERED.
    if ls["contract_status"] != "OFFERED":
        raise errors.invalid_state("Counter requires an OFFERED slot")
    # Counter limit (priority 9).
    if ls["counter_rounds"] >= svc.MAX_COUNTER_ROUNDS:
        raise ApiError(errors.ERR_COUNTER_LIMIT_REACHED, 409, "Counter round limit reached")
    ls["contract_status"] = "COUNTERED"
    ls["offered_fee_cents"] = counter_fee
    ls["counter_rounds"] += 1
    svc.touch(ls)
    return ok(S.lineup_slot(ls))


@app.route("/lineup-slots/<lineup_slot_id>/revise-offer", methods=["POST"])
def revise_offer(lineup_slot_id):
    auth({"Booker"})
    ls = svc.get_or_404(db.lineup_slots, lineup_slot_id)
    data = V.body()
    new_offer = V.require_int(data, "new_offered_fee_cents", minimum=0)
    # State: must be COUNTERED.
    if ls["contract_status"] != "COUNTERED":
        raise errors.invalid_state("Revise-offer requires a COUNTERED slot")
    # Counter limit (priority 9).
    if ls["counter_rounds"] >= svc.MAX_COUNTER_ROUNDS:
        raise ApiError(errors.ERR_COUNTER_LIMIT_REACHED, 409, "Counter round limit reached")
    ls["contract_status"] = "OFFERED"
    ls["offered_fee_cents"] = new_offer
    svc.touch(ls)
    return ok(S.lineup_slot(ls))


@app.route("/lineup-slots/<lineup_slot_id>/sign", methods=["POST"])
def sign_slot(lineup_slot_id):
    auth({"Booker", "Performer"})
    ls = svc.get_or_404(db.lineup_slots, lineup_slot_id)
    data = V.body()
    expected_version = V.require_int(data, "expected_lineup_slot_version")
    # State: OFFERED or COUNTERED, show in valid status.
    if ls["contract_status"] not in ("OFFERED", "COUNTERED"):
        raise errors.invalid_state("Only an OFFERED/COUNTERED slot can be signed")
    show = db.shows.get(ls["show_id"])
    if show is None or show["status"] not in ("DRAFT", "ON_SALE", "PRIVATE_HELD", "SOLD_OUT"):
        raise errors.invalid_state("Show is not in a signable status")
    # OCC (priority 17): expected_lineup_slot_version must equal current version.
    if expected_version != ls["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Lineup slot version is stale")
    ls["contract_status"] = "SIGNED"
    ls["agreed_fee_cents"] = ls["offered_fee_cents"]
    svc.touch(ls)
    return ok(S.lineup_slot(ls))


@app.route("/lineup-slots/<lineup_slot_id>/drop", methods=["POST"])
def drop_slot(lineup_slot_id):
    auth({"Booker"})
    ls = svc.get_or_404(db.lineup_slots, lineup_slot_id)
    # State: OFFERED or COUNTERED.
    if ls["contract_status"] not in ("OFFERED", "COUNTERED"):
        raise errors.invalid_state("Only an OFFERED/COUNTERED slot can be dropped")
    ls["contract_status"] = "DROPPED"
    svc.touch(ls)
    return ok(S.lineup_slot(ls))


# ===========================================================================
# Reservations
# ===========================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    uid, role = auth({"BoxOffice", "Patron"})
    data = V.body()
    show_id = V.require_str(data, "show_id")
    section_id = V.require_str(data, "section_id")
    tier_id = V.require_str(data, "tier_id")
    patron_id = V.require_str(data, "patron_id")
    party_size = V.require_int(data, "party_size", minimum=1)
    is_comp = V.opt_bool(data, "is_comp", False)

    # Existence (priority 3): left-to-right on body ids.
    show = db.shows.get(show_id)
    if show is None:
        raise errors.not_found()
    section = db.sections.get(section_id)
    if section is None:
        raise errors.not_found()
    tier = db.tiers.get(tier_id)
    if tier is None:
        raise errors.not_found()

    # State (priority 6): show must be sellable (ON_SALE or SOLD_OUT).
    if show["status"] not in ("ON_SALE", "SOLD_OUT"):
        raise errors.invalid_state("Show is not sellable")

    # Posture gate (priority 8): venue CLOSED blocks new reservations.
    venue = db.venues.get(show["venue_id"])
    if venue is not None and venue["posture"] == "CLOSED":
        raise ApiError(errors.ERR_POSTURE_BLOCKED, 409, "Venue is closed")

    # Cross-show integrity (priority 16): tier & section must belong to show.
    if section["show_id"] != show_id or tier["show_id"] != show_id:
        raise ApiError(errors.ERR_CROSS_SHOW_REFERENCE, 409,
                       "section_id and tier_id must belong to the same show")

    new_res = _build_reservation(show, section, tier, patron_id, party_size, is_comp,
                                 waived=False)

    # Capacity (priority 14) for capacity-tracked sections.
    if section["kind"] in ("GA", "RESERVED"):
        remaining = section["ga_capacity"] - svc.section_sold_count(show_id, section_id)
        if party_size > remaining:
            raise ApiError(errors.ERR_SECTION_SOLD_OUT, 409,
                           "party_size exceeds remaining section capacity")

    db.reservations[new_res["id"]] = new_res
    svc.recompute_ga_sold_count(show)
    svc.maybe_sold_out(show)
    return created(S.reservation(new_res))


def _build_reservation(show, section, tier, patron_id, party_size, is_comp,
                       waived=False):
    res = {
        "id": new_id(),
        "show_id": show["id"],
        "section_id": section["id"],
        "tier_id": tier["id"],
        "table_id": None,
        "patron_id": patron_id,
        "party_size": party_size,
        "is_comp": is_comp,
        "booking_status": "BOOKED",
        "settlement_status": "UNCOLLECTED",
        "items_consumed_cents": 0,
        "refunded_cents": 0,
        "_waived": waived,
    }
    res["ticket_charge_cents"] = svc.compute_ticket_charge(
        is_comp, tier["price_cents"], party_size)
    # Pre-seating estimate of minimum_due (no table yet).
    res["minimum_due_cents"] = svc.compute_minimum_due(res, tier, table=None, waived=waived)
    svc.stamp_create(res)
    return res


@app.route("/reservations/<reservation_id>", methods=["GET"])
def read_reservation(reservation_id):
    auth({"BoxOffice", "FloorManager", "Patron"})
    rec = svc.get_or_404(db.reservations, reservation_id)
    return ok(S.reservation(rec))


@app.route("/reservations", methods=["GET"])
def list_reservations():
    auth({"BoxOffice", "FloorManager", "Patron"})
    show_id = request.args.get("show_id")
    section_id = request.args.get("section_id")
    tier_id = request.args.get("tier_id")
    table_id = request.args.get("table_id")
    patron_id = request.args.get("patron_id")
    recs = [r for r in db.reservations.values()
            if (show_id is None or r["show_id"] == show_id)
            and (section_id is None or r["section_id"] == section_id)
            and (tier_id is None or r["tier_id"] == tier_id)
            and (table_id is None or r.get("table_id") == table_id)
            and (patron_id is None or r["patron_id"] == patron_id)]
    return paginate_and_list(recs, S.reservation)


@app.route("/reservations/<reservation_id>/collect-ticket", methods=["POST"])
def collect_ticket(reservation_id):
    auth({"BoxOffice"})
    res = svc.get_or_404(db.reservations, reservation_id)
    # State: settlement UNCOLLECTED; booking in {BOOKED, SEATED, CHECKED_IN}.
    if res["settlement_status"] != "UNCOLLECTED":
        raise errors.invalid_state("Ticket already collected or refunded")
    if res["booking_status"] not in ("BOOKED", "SEATED", "CHECKED_IN"):
        raise errors.invalid_state("Reservation is not in a collectable booking state")
    res["settlement_status"] = "TICKET_PAID"
    # Issue one Ticket per seat in ISSUED scan_state.
    for i in range(res["party_size"]):
        tk = {
            "id": new_id(),
            "reservation_id": res["id"],
            "seat_label": _seat_label(res, i),
            "scan_state": "ISSUED",
        }
        from db import iso_ms
        tk["created_at"] = iso_ms()
        tk["_seq"] = db.next_seq()
        db.tickets[tk["id"]] = tk
    svc.touch(res)
    return ok(S.reservation(res))


def _seat_label(res, index):
    section = db.sections.get(res["section_id"])
    kind = section["kind"] if section else "GA"
    if kind == "GA":
        return "GA"
    if kind == "RESERVED":
        return "S%d" % (index + 1)
    # TABLE
    tbl = db.tables.get(res.get("table_id")) if res.get("table_id") else None
    num = tbl["table_number"] if tbl else "T"
    return "%s-S%d" % (num, index + 1)


@app.route("/reservations/<reservation_id>/assign-table", methods=["POST"])
def assign_table(reservation_id):
    auth({"FloorManager"})
    res = svc.get_or_404(db.reservations, reservation_id)
    data = V.body()
    table_id = V.require_str(data, "table_id")
    expected_table_version = V.require_int(data, "expected_table_version")
    table = db.tables.get(table_id)
    if table is None:
        raise errors.not_found()
    section = db.sections.get(res["section_id"])
    # Wrong section kind: reservation's section must be TABLE, and the table's
    # section must match the reservation's section.
    if section is None or section["kind"] != "TABLE":
        raise ApiError(errors.ERR_WRONG_SECTION_KIND, 409,
                       "Reservation is not a TABLE-section reservation")
    if table["section_id"] != res["section_id"]:
        raise ApiError(errors.ERR_WRONG_SECTION_KIND, 409,
                       "Table does not belong to the reservation's section")
    # No server assigned.
    if not table.get("assigned_server_id"):
        raise ApiError(errors.ERR_NO_SERVER_ASSIGNED, 409, "Table has no assigned server")
    # Table too small.
    if table["seats"] < res["party_size"]:
        raise ApiError(errors.ERR_TABLE_TOO_SMALL, 409, "Table is too small for the party")
    # Server overloaded: this assignment leans on the table's server (already
    # counted when the server was assigned; re-check the ceiling).
    server = db.servers.get(table["assigned_server_id"])
    if server is not None:
        count = svc.recompute_assigned_table_count(server)
        if count > server["max_tables"]:
            raise ApiError(errors.ERR_SERVER_OVERLOADED, 409,
                           "Server is over its max_tables")
    # Table unavailable (not AVAILABLE).
    if table["status"] != "AVAILABLE":
        raise ApiError(errors.ERR_TABLE_UNAVAILABLE, 409, "Table is not AVAILABLE")
    # OCC (priority 17): expected_table_version must equal table's version.
    if expected_table_version != table["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Table version is stale")

    table["status"] = "HELD"
    res["table_id"] = table_id
    svc.touch(table)
    # Recompute minimum_due in post-seating form (table min_items_per_seat).
    tier = db.tiers.get(res["tier_id"])
    res["minimum_due_cents"] = svc.compute_minimum_due(
        res, tier, table=table, waived=res.get("_waived", False))
    svc.touch(res)
    return ok(S.reservation(res))


@app.route("/reservations/<reservation_id>/seat", methods=["POST"])
def seat_reservation(reservation_id):
    auth({"FloorManager"})
    res = svc.get_or_404(db.reservations, reservation_id)
    section = db.sections.get(res["section_id"])
    # Section must be TABLE and a table assigned.
    if section is None or section["kind"] != "TABLE":
        raise errors.invalid_state("Seating requires a TABLE-section reservation")
    if not res.get("table_id"):
        raise errors.invalid_state("Reservation has no table assigned")
    # From BOOKED only.
    if res["booking_status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED reservation can be seated")
    show = db.shows.get(res["show_id"])
    if show is None or show["status"] not in ("ON_SALE", "SOLD_OUT"):
        raise errors.invalid_state("Show is not in a seatable status")
    res["booking_status"] = "SEATED"
    table = db.tables.get(res["table_id"])
    if table is not None:
        table["status"] = "OCCUPIED"
        svc.touch(table)
    svc.touch(res)
    return ok(S.reservation(res))


@app.route("/reservations/<reservation_id>/check-in", methods=["POST"])
def check_in(reservation_id):
    auth({"BoxOffice"})
    res = svc.get_or_404(db.reservations, reservation_id)
    # From BOOKED or SEATED.
    if res["booking_status"] not in ("BOOKED", "SEATED"):
        raise errors.invalid_state("Only a BOOKED/SEATED reservation can be checked in")
    show = db.shows.get(res["show_id"])
    if show is None or show["status"] not in ("ON_SALE", "SOLD_OUT"):
        raise errors.invalid_state("Show is not in a checkable status")
    # settlement_status TICKET_PAID OR is_comp.
    if not (res["settlement_status"] == "TICKET_PAID" or res["is_comp"]):
        raise errors.invalid_state("Reservation must be TICKET_PAID or a comp to check in")
    res["booking_status"] = "CHECKED_IN"
    # Tickets ISSUED -> SCANNED in created_at ASC order.
    tickets = [tk for tk in db.tickets.values()
               if tk["reservation_id"] == res["id"] and tk["scan_state"] == "ISSUED"]
    tickets.sort(key=lambda t: (t["created_at"], t.get("_seq", 0)))
    for tk in tickets:
        tk["scan_state"] = "SCANNED"
    svc.touch(res)
    return ok(S.reservation(res))


@app.route("/reservations/<reservation_id>/record-consumption", methods=["POST"])
def record_consumption(reservation_id):
    auth({"FloorManager"})
    res = svc.get_or_404(db.reservations, reservation_id)
    data = V.body()
    delta = V.require_int(data, "delta_cents")
    res["items_consumed_cents"] += delta
    # When items_consumed >= minimum_due and currently TICKET_PAID -> MINIMUM_MET.
    if res["settlement_status"] == "TICKET_PAID" \
            and res["items_consumed_cents"] >= res["minimum_due_cents"]:
        res["settlement_status"] = "MINIMUM_MET"
    svc.touch(res)
    return ok(S.reservation(res))


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    uid, role = auth({"BoxOffice", "Patron"})
    res = svc.get_or_404(db.reservations, reservation_id)
    # Ownership (priority 4): Patron may only cancel own reservation.
    if role == "Patron" and res["patron_id"] != uid:
        raise ApiError(errors.ERR_NOT_OWNER, 403, "Not the owner of this reservation")
    # State: from BOOKED/SEATED/CHECKED_IN; show not SETTLED.
    if res["booking_status"] not in ("BOOKED", "SEATED", "CHECKED_IN"):
        raise errors.invalid_state("Reservation cannot be cancelled from its current state")
    show = db.shows.get(res["show_id"])
    if show is None or show["status"] == "SETTLED":
        raise errors.invalid_state("Show is already settled")

    res["refunded_cents"] = svc.compute_refund_cancel(res, show)
    res["booking_status"] = "CANCELLED"
    res["settlement_status"] = "REFUNDED"
    _release_after_exit(res)
    svc.touch(res)
    svc.recompute_ga_sold_count(show)
    svc.maybe_back_on_sale(show)
    return ok(S.reservation(res))


def _release_after_exit(res):
    """Void tickets, release table (recompute server), revert linked guest-list."""
    # Void tickets ISSUED/SCANNED.
    for tk in db.tickets.values():
        if tk["reservation_id"] == res["id"] and tk["scan_state"] in ("ISSUED", "SCANNED"):
            tk["scan_state"] = "VOID"
    # Release table.
    if res.get("table_id"):
        tbl = db.tables.get(res["table_id"])
        if tbl is not None:
            tbl["status"] = "AVAILABLE"
            svc.touch(tbl)
            if tbl.get("assigned_server_id"):
                srv = db.servers.get(tbl["assigned_server_id"])
                if srv:
                    svc.recompute_assigned_table_count(srv)
                    svc.touch(srv)
        res["table_id"] = None
    # Revert any CONVERTED guest-list entry pointing here -> REVOKED.
    for gle in db.guest_list_entries.values():
        if gle.get("reservation_id") == res["id"] and gle["status"] == "CONVERTED":
            gle["status"] = "REVOKED"
            svc.touch(gle)


@app.route("/reservations/<reservation_id>/exchange", methods=["POST"])
def exchange_reservation(reservation_id):
    uid, role = auth({"BoxOffice", "Patron"})
    res = svc.get_or_404(db.reservations, reservation_id)
    # Ownership (priority 4).
    if role == "Patron" and res["patron_id"] != uid:
        raise ApiError(errors.ERR_NOT_OWNER, 403, "Not the owner of this reservation")
    data = V.body()
    target_section_id = V.require_str(data, "target_section_id")
    target_tier_id = V.require_str(data, "target_tier_id")
    target_section = db.sections.get(target_section_id)
    if target_section is None:
        raise errors.not_found()
    target_tier = db.tiers.get(target_tier_id)
    if target_tier is None:
        raise errors.not_found()
    # State: old row must be BOOKED; show ON_SALE/SOLD_OUT.
    if res["booking_status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED reservation can be exchanged")
    show = db.shows.get(res["show_id"])
    if show is None or show["status"] not in ("ON_SALE", "SOLD_OUT"):
        raise errors.invalid_state("Show is not in an exchangeable status")
    # Cross-show integrity: target tier & section must belong to the same show.
    if target_section["show_id"] != res["show_id"] or target_tier["show_id"] != res["show_id"]:
        raise ApiError(errors.ERR_CROSS_SHOW_REFERENCE, 409,
                       "Target section/tier must belong to the same show")
    party_size = res["party_size"]
    # Target section capacity (priority 14).
    if target_section["kind"] in ("GA", "RESERVED"):
        remaining = target_section["ga_capacity"] - svc.section_sold_count(
            res["show_id"], target_section_id)
        if party_size > remaining:
            raise ApiError(errors.ERR_SECTION_SOLD_OUT, 409,
                           "Target section has insufficient capacity")

    # Refund on old row = credit difference (old base - new charge), floored 0.
    new_charge = svc.compute_ticket_charge(False, target_tier["price_cents"], party_size)
    res["refunded_cents"] = svc.compute_refund_exchange(res, new_charge)
    res["booking_status"] = "EXCHANGED"
    res["settlement_status"] = "REFUNDED"
    _release_after_exit(res)
    svc.touch(res)

    # New reservation in BOOKED carrying party_size.
    new_res = _build_reservation(show, target_section, target_tier,
                                 res["patron_id"], party_size, False, waived=False)
    db.reservations[new_res["id"]] = new_res

    # Recompute ga_sold_count for both old & new sections (show-level aggregate).
    svc.recompute_ga_sold_count(show)
    svc.maybe_back_on_sale(show)
    svc.maybe_sold_out(show)
    # The endpoint addresses the old reservation ({reservation_id}); per PRD §2.2
    # the modified (addressed) resource is returned — the old row, now EXCHANGED
    # and REFUNDED with refunded_cents set to the credited difference (PRD §3.7).
    return ok(S.reservation(res))


@app.route("/reservations/<reservation_id>/no-show", methods=["POST"])
def no_show(reservation_id):
    auth({"FloorManager"})
    res = svc.get_or_404(db.reservations, reservation_id)
    # State: from BOOKED/SEATED/CHECKED_IN.
    if res["booking_status"] not in ("BOOKED", "SEATED", "CHECKED_IN"):
        raise errors.invalid_state("Reservation cannot be marked no-show from its state")
    show = db.shows.get(res["show_id"])
    if show is None:
        raise errors.not_found()
    # Timing (priority 7): now >= starts_at + doors_buffer_minutes.
    from datetime import timedelta
    threshold = clock.parse_iso8601(show["starts_at"]) + timedelta(
        minutes=show["doors_buffer_minutes"])
    if clock.now() < threshold:
        raise ApiError(errors.ERR_TIMING_NOT_ALLOWED, 409,
                       "No-show cannot be recorded before doors+buffer")
    res["booking_status"] = "NO_SHOW"
    res["refunded_cents"] = 0  # ticket charge retained, no refund
    # Release any held table (but no settlement_status change to REFUNDED).
    if res.get("table_id"):
        tbl = db.tables.get(res["table_id"])
        if tbl is not None:
            tbl["status"] = "AVAILABLE"
            svc.touch(tbl)
            if tbl.get("assigned_server_id"):
                srv = db.servers.get(tbl["assigned_server_id"])
                if srv:
                    svc.recompute_assigned_table_count(srv)
                    svc.touch(srv)
        res["table_id"] = None
    svc.touch(res)
    svc.recompute_ga_sold_count(show)
    svc.maybe_back_on_sale(show)
    return ok(S.reservation(res))


# ===========================================================================
# Tickets
# ===========================================================================
@app.route("/tickets/<ticket_id>", methods=["GET"])
def read_ticket(ticket_id):
    auth({"BoxOffice", "FloorManager", "Patron"})
    rec = svc.get_or_404(db.tickets, ticket_id)
    return ok(S.ticket(rec))


@app.route("/tickets", methods=["GET"])
def list_tickets():
    auth({"BoxOffice", "FloorManager", "Patron"})
    reservation_id = request.args.get("reservation_id")
    recs = [t for t in db.tickets.values()
            if reservation_id is None or t["reservation_id"] == reservation_id]
    return paginate_and_list(recs, S.ticket)


# ===========================================================================
# Guest list
# ===========================================================================
@app.route("/guest-list-entries", methods=["POST"])
def create_guest_list_entry():
    auth({"Booker", "Performer"})
    data = V.body()
    show_id = V.require_str(data, "show_id")
    host_performer_id = V.require_str(data, "host_performer_id")
    guest_name = V.require_str(data, "guest_name")
    party_size = V.require_int(data, "party_size", minimum=1)
    minimum_waived = V.opt_bool(data, "minimum_waived", False)
    if show_id not in db.shows:
        raise errors.not_found()
    if host_performer_id not in db.performers:
        raise errors.not_found()
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "host_performer_id": host_performer_id,
        "guest_name": guest_name,
        "party_size": party_size,
        "minimum_waived": minimum_waived,
        "status": "LISTED",
        "reservation_id": None,
    }
    svc.stamp_create(rec)
    db.guest_list_entries[rec["id"]] = rec
    return created(S.guest_list_entry(rec))


@app.route("/guest-list-entries/<guest_list_entry_id>", methods=["GET"])
def read_guest_list_entry(guest_list_entry_id):
    auth({"Booker", "FloorManager", "Performer"})
    rec = svc.get_or_404(db.guest_list_entries, guest_list_entry_id)
    return ok(S.guest_list_entry(rec))


@app.route("/guest-list-entries", methods=["GET"])
def list_guest_list_entries():
    auth({"Booker", "FloorManager", "Performer"})
    show_id = request.args.get("show_id")
    host_performer_id = request.args.get("host_performer_id")
    reservation_id = request.args.get("reservation_id")
    recs = [g for g in db.guest_list_entries.values()
            if (show_id is None or g["show_id"] == show_id)
            and (host_performer_id is None or g["host_performer_id"] == host_performer_id)
            and (reservation_id is None or g.get("reservation_id") == reservation_id)]
    return paginate_and_list(recs, S.guest_list_entry)


@app.route("/guest-list-entries/<guest_list_entry_id>/convert", methods=["POST"])
def convert_guest_list_entry(guest_list_entry_id):
    auth({"BoxOffice"})
    gle = svc.get_or_404(db.guest_list_entries, guest_list_entry_id)
    data = V.body()
    section_id = V.require_str(data, "section_id")
    tier_id = V.require_str(data, "tier_id")
    section = db.sections.get(section_id)
    if section is None:
        raise errors.not_found()
    tier = db.tiers.get(tier_id)
    if tier is None:
        raise errors.not_found()
    # State: entry must be LISTED.
    if gle["status"] != "LISTED":
        raise ApiError(errors.ERR_GUEST_LIST_NOT_LISTED, 409,
                       "Guest-list entry is not LISTED")
    show = db.shows.get(gle["show_id"])
    if show is None:
        raise errors.not_found()
    # Show must be ON_SALE or SOLD_OUT.
    if show["status"] not in ("ON_SALE", "SOLD_OUT"):
        raise errors.invalid_state("Show is not sellable")
    # section_id and tier_id must belong to the same show.
    if section["show_id"] != gle["show_id"] or tier["show_id"] != gle["show_id"]:
        raise ApiError(errors.ERR_CROSS_SHOW_REFERENCE, 409,
                       "section and tier must belong to the entry's show")

    new_res = _build_reservation(show, section, tier, gle["host_performer_id"],
                                 gle["party_size"], True,
                                 waived=gle["minimum_waived"])
    db.reservations[new_res["id"]] = new_res
    gle["status"] = "CONVERTED"
    gle["reservation_id"] = new_res["id"]
    svc.touch(gle)
    svc.recompute_ga_sold_count(show)
    svc.maybe_sold_out(show)
    return ok(S.guest_list_entry(gle))


@app.route("/guest-list-entries/<guest_list_entry_id>/revoke", methods=["POST"])
def revoke_guest_list_entry(guest_list_entry_id):
    auth({"Booker", "Performer"})
    gle = svc.get_or_404(db.guest_list_entries, guest_list_entry_id)
    # From LISTED or CONVERTED.
    if gle["status"] not in ("LISTED", "CONVERTED"):
        raise errors.invalid_state("Entry cannot be revoked from its current state")
    # If a comp reservation was linked and still active, cancel it.
    if gle.get("reservation_id"):
        res = db.reservations.get(gle["reservation_id"])
        if res is not None and res["booking_status"] in ("BOOKED", "SEATED", "CHECKED_IN"):
            show = db.shows.get(res["show_id"])
            res["refunded_cents"] = svc.compute_refund_show_cancel(res)
            res["booking_status"] = "CANCELLED"
            res["settlement_status"] = "REFUNDED"
            # Release without re-reverting this same guest-list entry.
            for tk in db.tickets.values():
                if tk["reservation_id"] == res["id"] and tk["scan_state"] in ("ISSUED", "SCANNED"):
                    tk["scan_state"] = "VOID"
            if res.get("table_id"):
                tbl = db.tables.get(res["table_id"])
                if tbl is not None:
                    tbl["status"] = "AVAILABLE"
                    svc.touch(tbl)
                    if tbl.get("assigned_server_id"):
                        srv = db.servers.get(tbl["assigned_server_id"])
                        if srv:
                            svc.recompute_assigned_table_count(srv)
                            svc.touch(srv)
                res["table_id"] = None
            svc.touch(res)
            if show is not None:
                svc.recompute_ga_sold_count(show)
                svc.maybe_back_on_sale(show)
    gle["status"] = "REVOKED"
    svc.touch(gle)
    return ok(S.guest_list_entry(gle))


# ===========================================================================
# Servers
# ===========================================================================
@app.route("/servers", methods=["POST"])
def create_server():
    auth({"FloorManager"})
    data = V.body()
    name = V.require_str(data, "name")
    max_tables = V.opt_int(data, "max_tables", svc.DEFAULT_MAX_TABLES, minimum=1)
    rec = {
        "id": new_id(),
        "name": name,
        "max_tables": max_tables,
        "assigned_table_count": 0,
    }
    svc.stamp_create(rec)
    db.servers[rec["id"]] = rec
    return created(S.server(rec))


@app.route("/servers/<server_id>", methods=["GET"])
def read_server(server_id):
    auth({"FloorManager", "Booker"})
    rec = svc.get_or_404(db.servers, server_id)
    svc.recompute_assigned_table_count(rec)
    return ok(S.server(rec))


# ===========================================================================
# Private events
# ===========================================================================
@app.route("/private-events", methods=["POST"])
def create_private_event():
    auth({"Booker"})
    data = V.body()
    show_id = V.require_str(data, "show_id")
    client_name = V.require_str(data, "client_name")
    buyout_fee = V.require_int(data, "buyout_fee_cents", minimum=0)
    deposit_pct = V.opt_pct(data, "deposit_pct", svc.DEFAULT_DEPOSIT_PCT)
    show = db.shows.get(show_id)
    if show is None:
        raise errors.not_found()
    # State: show must be DRAFT.
    if show["status"] != "DRAFT":
        raise errors.invalid_state("Private event can only be created for a DRAFT show")
    # No reservation in BOOKED/SEATED/CHECKED_IN for the show.
    has_active = any(
        r["show_id"] == show_id and r["booking_status"] in ("BOOKED", "SEATED", "CHECKED_IN")
        for r in db.reservations.values())
    if has_active:
        raise errors.invalid_state("Show has active reservations")
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "client_name": client_name,
        "buyout_fee_cents": buyout_fee,
        "deposit_pct": deposit_pct,
        "status": "HELD",
        "deposit_cents": svc.compute_buyout_deposit(deposit_pct, buyout_fee),
    }
    svc.stamp_create(rec)
    db.private_events[rec["id"]] = rec
    # System consequence: Show DRAFT -> PRIVATE_HELD; is_private true.
    show["status"] = "PRIVATE_HELD"
    svc.recompute_is_private(show)
    svc.touch(show)
    return created(S.private_event(rec))


@app.route("/private-events/<private_event_id>", methods=["GET"])
def read_private_event(private_event_id):
    auth({"Booker", "FloorManager"})
    rec = svc.get_or_404(db.private_events, private_event_id)
    return ok(S.private_event(rec))


@app.route("/private-events", methods=["GET"])
def list_private_events():
    auth({"Booker", "FloorManager"})
    show_id = request.args.get("show_id")
    recs = [pe for pe in db.private_events.values()
            if show_id is None or pe["show_id"] == show_id]
    return paginate_and_list(recs, S.private_event)


@app.route("/private-events/<private_event_id>/confirm", methods=["POST"])
def confirm_private_event(private_event_id):
    auth({"Booker"})
    pe = svc.get_or_404(db.private_events, private_event_id)
    # State: from HELD; underlying show PRIVATE_HELD.
    if pe["status"] != "HELD":
        raise errors.invalid_state("Only a HELD buyout can be confirmed")
    show = db.shows.get(pe["show_id"])
    if show is None or show["status"] != "PRIVATE_HELD":
        raise errors.invalid_state("Underlying show is not PRIVATE_HELD")
    pe["status"] = "CONFIRMED"
    svc.touch(pe)
    svc.recompute_is_private(show)
    return ok(S.private_event(pe))


@app.route("/private-events/<private_event_id>/cancel", methods=["POST"])
def cancel_private_event(private_event_id):
    auth({"Booker"})
    pe = svc.get_or_404(db.private_events, private_event_id)
    # From HELD or CONFIRMED.
    if pe["status"] not in ("HELD", "CONFIRMED"):
        raise errors.invalid_state("Buyout cannot be cancelled from its state")
    pe["status"] = "CANCELLED"  # deposit retained (non-refundable)
    svc.touch(pe)
    show = db.shows.get(pe["show_id"])
    if show is not None:
        # If no other HELD/CONFIRMED buyout, revert PRIVATE_HELD -> ON_SALE.
        other = any(
            p["show_id"] == show["id"] and p["id"] != pe["id"]
            and p["status"] in ("HELD", "CONFIRMED")
            for p in db.private_events.values())
        svc.recompute_is_private(show)
        if not other and show["status"] == "PRIVATE_HELD":
            show["status"] = "ON_SALE"
            svc.touch(show)
    return ok(S.private_event(pe))


# ===========================================================================
# Settlements
# ===========================================================================
@app.route("/settlements", methods=["POST"])
def open_settlement():
    auth({"FloorManager"})
    data = V.body()
    show_id = V.require_str(data, "show_id")
    show = db.shows.get(show_id)
    if show is None:
        raise errors.not_found()
    # Timing: now >= ends_at -> else ERR_SHOW_NOT_ENDED.
    # PRD §3.12 names only two open-settlement guards: ERR_SHOW_NOT_ENDED
    # (timing) and ERR_SETTLEMENT_EXISTS (duplicate). No show-status precondition
    # is stated, so opening a second settlement on an already-SETTLING show must
    # reach the duplicate check rather than a fabricated state rejection.
    if clock.now() < clock.parse_iso8601(show["ends_at"]):
        raise ApiError(errors.ERR_SHOW_NOT_ENDED, 409, "Show has not yet ended")
    # No OPEN settlement already exists.
    for s in db.settlements.values():
        if s["show_id"] == show_id and s["status"] == "OPEN":
            raise ApiError(errors.ERR_SETTLEMENT_EXISTS, 409,
                           "An OPEN settlement already exists for this show")
    rec = {
        "id": new_id(),
        "show_id": show_id,
        "status": "OPEN",
        "gross_ticket_cents": 0,
        "gross_minimum_cents": 0,
        "buyout_cents": 0,
        "performer_payout_cents": 0,
        "house_cut_cents": 0,
        "net_to_venue_cents": 0,
    }
    svc.stamp_create(rec)
    db.settlements[rec["id"]] = rec
    show["status"] = "SETTLING"
    svc.touch(show)
    venue = db.venues.get(show["venue_id"])
    if venue is not None:
        svc.recompute_venue_posture(venue)
        svc.touch(venue)
    return created(S.settlement(rec))


@app.route("/settlements/<settlement_id>", methods=["GET"])
def read_settlement(settlement_id):
    auth({"FloorManager", "Booker"})
    rec = svc.get_or_404(db.settlements, settlement_id)
    return ok(S.settlement(rec))


@app.route("/settlements", methods=["GET"])
def list_settlements():
    auth({"FloorManager", "Booker"})
    show_id = request.args.get("show_id")
    recs = [s for s in db.settlements.values()
            if show_id is None or s["show_id"] == show_id]
    return paginate_and_list(recs, S.settlement)


@app.route("/settlements/<settlement_id>/finalize", methods=["POST"])
def finalize_settlement(settlement_id):
    auth({"FloorManager"})
    st = svc.get_or_404(db.settlements, settlement_id)
    # State: settlement OPEN; show SETTLING.
    if st["status"] != "OPEN":
        raise errors.invalid_state("Settlement is not OPEN")
    show = db.shows.get(st["show_id"])
    if show is None or show["status"] != "SETTLING":
        raise errors.invalid_state("Show is not SETTLING")
    # Minimum-not-met guard: no CHECKED_IN + TICKET_PAID reservation may have
    # items_consumed_cents < minimum_due_cents.
    for r in db.reservations.values():
        if r["show_id"] != st["show_id"]:
            continue
        if r["booking_status"] == "CHECKED_IN" and r["settlement_status"] == "TICKET_PAID" \
                and r["items_consumed_cents"] < r["minimum_due_cents"]:
            raise ApiError(errors.ERR_MINIMUM_NOT_MET, 409,
                           "A checked-in reservation has not met its minimum")

    # compute_settlement (PRD §3.12) — order pinned.
    included = [r for r in db.reservations.values()
                if r["show_id"] == st["show_id"]
                and r["booking_status"] in ("CHECKED_IN", "NO_SHOW")]
    gross_ticket = sum(r["ticket_charge_cents"] for r in included
                       if r["settlement_status"] in ("TICKET_PAID", "MINIMUM_MET"))
    gross_minimum = sum(min(r["items_consumed_cents"], r["minimum_due_cents"])
                        for r in included if r["settlement_status"] == "MINIMUM_MET")
    buyout = 0
    for pe in db.private_events.values():
        if pe["show_id"] == st["show_id"] and pe["status"] == "CONFIRMED":
            buyout = pe["buyout_fee_cents"]
            break
    gross_box_office = gross_ticket + gross_minimum + buyout
    venue = db.venues.get(show["venue_id"])
    house_fee_pct = venue["house_fee_pct"] if venue else 0
    # Single round_half_up on the gross total (never per line) — PRD §3.12.
    house_cut = svc.round_half_up(svc.Decimal(str(house_fee_pct)) * svc.Decimal(str(gross_box_office)))
    performer_payout = sum(
        ls["agreed_fee_cents"] for ls in db.lineup_slots.values()
        if ls["show_id"] == st["show_id"] and ls["contract_status"] == "SIGNED"
        and ls["agreed_fee_cents"] is not None)
    net_to_venue = gross_box_office - house_cut - performer_payout

    st["gross_ticket_cents"] = gross_ticket
    st["gross_minimum_cents"] = gross_minimum
    st["buyout_cents"] = buyout
    st["performer_payout_cents"] = performer_payout
    st["house_cut_cents"] = house_cut
    st["net_to_venue_cents"] = net_to_venue
    st["status"] = "FINALIZED"
    svc.touch(st)

    # CASCADE: Show -> SETTLED; venue posture recomputed.
    show["status"] = "SETTLED"
    svc.touch(show)
    if venue is not None:
        svc.recompute_venue_posture(venue)
        svc.touch(venue)
    return ok(S.settlement(st))


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
