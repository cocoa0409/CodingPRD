"""Restaurants, guests, tables, experience packages and add-ons."""
from common import (ApiError, DB, must_get, new_record, ok, ok_list, public,
                    rows)
from guards import (auth, filtered, opt_bool, opt_enum, opt_int,
                    own_restaurant, pagination, req_enum, req_int, req_str,
                    window)

CATALOG_READERS = ("PlatformAdmin", "RestaurantManager", "KitchenLead",
                   "GuestServices", "Guest")
FLOOR_READERS = ("PlatformAdmin", "RestaurantManager", "KitchenLead")
GUEST_READERS = ("PlatformAdmin", "RestaurantManager", "GuestServices", "Guest")


def own_body_restaurant(ctx):
    raw = ctx.body.get("restaurant_id")
    if isinstance(raw, str) and raw.strip() != "":
        own_restaurant(ctx, raw)


def unique_in(table, field, value, scope_field=None, scope_value=None):
    for rec in DB[table].values():
        if rec[field] != value:
            continue
        if scope_field is not None and rec[scope_field] != scope_value:
            continue
        raise ApiError("ERR_VALIDATION", "%s must be unique" % field)


def register(app):

    # ----------------------------------------------------------- restaurants

    @app.post("/restaurants")
    def create_restaurant():
        ctx = auth("PlatformAdmin")
        body = ctx.body
        name = req_str(body, "name", max_len=120)
        service_charge_bp = opt_int(body, "service_charge_bp", 725, 0, 3000)
        hold_ttl = opt_int(body, "hold_ttl_minutes", 20, 1, 1440)
        offer_ttl = opt_int(body, "offer_ttl_minutes", 15, 1, 1440)
        if offer_ttl > hold_ttl:
            raise ApiError("ERR_VALIDATION",
                           "offer_ttl_minutes may not exceed hold_ttl_minutes")
        max_offer_rounds = opt_int(body, "max_offer_rounds", 2, 1, 5)
        max_name_changes = opt_int(body, "max_name_changes", 1, 0, 5)
        name_cutoff = opt_int(body, "name_change_cutoff_minutes", 240, 0, 20160)
        transfer_cutoff = opt_int(body, "transfer_cutoff_minutes", 1440, 0, 20160)
        max_transfers = opt_int(body, "max_transfers_per_guest", 2, 0, 20)
        grace = opt_int(body, "no_show_grace_minutes", 30, 0, 240)
        cap = opt_int(body, "goodwill_credit_cap_cents", 20000, 0, None)
        prep_lead = opt_int(body, "prep_lead_minutes", 45, 1, 240)
        scrutiny = opt_int(body, "refund_scrutiny_threshold_cents", 30000, 0, None)
        unique_in("restaurants", "name", name)
        rec = new_record("restaurants", {
            "name": name,
            "service_charge_bp": service_charge_bp,
            "hold_ttl_minutes": hold_ttl,
            "offer_ttl_minutes": offer_ttl,
            "max_offer_rounds": max_offer_rounds,
            "max_name_changes": max_name_changes,
            "name_change_cutoff_minutes": name_cutoff,
            "transfer_cutoff_minutes": transfer_cutoff,
            "max_transfers_per_guest": max_transfers,
            "no_show_grace_minutes": grace,
            "goodwill_credit_cap_cents": cap,
            "prep_lead_minutes": prep_lead,
            "refund_scrutiny_threshold_cents": scrutiny,
        })
        return ok(public(rec), 201)

    @app.get("/restaurants/<rid>")
    def read_restaurant(rid):
        ctx = auth(*CATALOG_READERS)
        own_restaurant(ctx, rid)
        return ok(public(must_get("restaurants", rid)))

    @app.get("/restaurants")
    def list_restaurants():
        auth(*CATALOG_READERS)
        pagination()
        items, limit, offset, total = window(
            filtered("restaurants", {"name": "name"}))
        return ok_list(items, limit, offset, total)

    @app.get("/restaurants/<rid>/tables")
    def list_restaurant_tables(rid):
        ctx = auth(*FLOOR_READERS)
        own_restaurant(ctx, rid)
        must_get("restaurants", rid)
        pagination()
        items, limit, offset, total = window(
            [t for t in rows("tables") if t["restaurant_id"] == rid])
        return ok_list(items, limit, offset, total)

    @app.get("/restaurants/<rid>/experience-packages")
    def list_restaurant_packages(rid):
        ctx = auth(*CATALOG_READERS)
        own_restaurant(ctx, rid)
        must_get("restaurants", rid)
        pagination()
        items, limit, offset, total = window(
            [p for p in rows("packages") if p["restaurant_id"] == rid])
        return ok_list(items, limit, offset, total)

    @app.get("/restaurants/<rid>/add-ons")
    def list_restaurant_add_ons(rid):
        ctx = auth(*CATALOG_READERS)
        own_restaurant(ctx, rid)
        must_get("restaurants", rid)
        pagination()
        items, limit, offset, total = window(
            [a for a in rows("add_ons") if a["restaurant_id"] == rid])
        return ok_list(items, limit, offset, total)

    @app.get("/restaurants/<rid>/services")
    def list_restaurant_services(rid):
        ctx = auth(*CATALOG_READERS)
        own_restaurant(ctx, rid)
        must_get("restaurants", rid)
        pagination()
        items, limit, offset, total = window(
            filtered("services", {"status": "status"},
                     extra=lambda s: s["restaurant_id"] == rid))
        return ok_list(items, limit, offset, total)

    # ---------------------------------------------------------------- tables

    @app.post("/tables")
    def create_table():
        ctx = auth("RestaurantManager")
        body = ctx.body
        own_body_restaurant(ctx)
        restaurant_id = req_str(body, "restaurant_id")
        must_get("restaurants", restaurant_id)
        table_code = req_str(body, "table_code")
        seats_min = req_int(body, "seats_min", 1, 20)
        seats_max = req_int(body, "seats_max", 1, 20)
        if seats_min > seats_max:
            raise ApiError("ERR_VALIDATION",
                           "seats_min may not exceed seats_max")
        buffer_minutes = opt_int(body, "turn_buffer_minutes", 15, 0, 120)
        unique_in("tables", "table_code", table_code, "restaurant_id",
                  restaurant_id)
        rec = new_record("tables", {
            "restaurant_id": restaurant_id,
            "table_code": table_code,
            "seats_min": seats_min,
            "seats_max": seats_max,
            "turn_buffer_minutes": buffer_minutes,
        })
        return ok(public(rec), 201)

    @app.get("/tables/<tid>")
    def read_table(tid):
        ctx = auth(*FLOOR_READERS)
        table = must_get("tables", tid)
        own_restaurant(ctx, table["restaurant_id"])
        return ok(public(table))

    # --------------------------------------------------- experience packages

    @app.post("/experience-packages")
    def create_package():
        ctx = auth("RestaurantManager")
        body = ctx.body
        own_body_restaurant(ctx)
        restaurant_id = req_str(body, "restaurant_id")
        must_get("restaurants", restaurant_id)
        name = req_str(body, "name")
        course_count = req_int(body, "course_count", 1, 30)
        base_price = req_int(body, "base_price_cents", 1, None)
        mode = req_enum(body, "prepayment_mode", ("DEPOSIT", "FULL"))
        deposit_bp = opt_int(body, "deposit_bp", 3000, 1, 10000)
        schedule = opt_enum(body, "forfeiture_schedule_code",
                            ("STANDARD", "STRICT"), "STANDARD")
        basis = opt_enum(body, "forfeiture_basis",
                         ("DEPOSIT_BASIS", "FULL_TICKET_BASIS"), "DEPOSIT_BASIS")
        release_discount_bp = opt_int(body, "release_discount_bp", 1500, 0, 5000)
        prep_per_cover = opt_int(body, "kitchen_prep_minutes_per_cover", 10, 0, 240)
        min_party = req_int(body, "min_party_size", 1, 20)
        max_party = req_int(body, "max_party_size", 1, 20)
        if min_party > max_party:
            raise ApiError("ERR_VALIDATION",
                           "min_party_size may not exceed max_party_size")
        unique_in("packages", "name", name, "restaurant_id", restaurant_id)
        rec = new_record("packages", {
            "restaurant_id": restaurant_id,
            "name": name,
            "course_count": course_count,
            "base_price_cents": base_price,
            "prepayment_mode": mode,
            "deposit_bp": deposit_bp,
            "forfeiture_schedule_code": schedule,
            "forfeiture_basis": basis,
            "release_discount_bp": release_discount_bp,
            "kitchen_prep_minutes_per_cover": prep_per_cover,
            "min_party_size": min_party,
            "max_party_size": max_party,
        })
        return ok(public(rec), 201)

    @app.get("/experience-packages/<pid>")
    def read_package(pid):
        ctx = auth(*CATALOG_READERS)
        package = must_get("packages", pid)
        own_restaurant(ctx, package["restaurant_id"])
        return ok(public(package))

    # --------------------------------------------------------------- add-ons

    @app.post("/add-ons")
    def create_add_on():
        ctx = auth("RestaurantManager")
        body = ctx.body
        own_body_restaurant(ctx)
        restaurant_id = req_str(body, "restaurant_id")
        must_get("restaurants", restaurant_id)
        name = req_str(body, "name")
        price = req_int(body, "price_cents", 1, None)
        prep_per_unit = opt_int(body, "prep_minutes_per_unit", 0, 0, 120)
        max_qty = opt_int(body, "max_qty_per_cover", 1, 1, 20)
        cutoff = opt_int(body, "order_cutoff_minutes", 1440, 0, 20160)
        requires_ack = opt_bool(body, "requires_kitchen_ack", False)
        unique_in("add_ons", "name", name, "restaurant_id", restaurant_id)
        rec = new_record("add_ons", {
            "restaurant_id": restaurant_id,
            "name": name,
            "price_cents": price,
            "prep_minutes_per_unit": prep_per_unit,
            "max_qty_per_cover": max_qty,
            "order_cutoff_minutes": cutoff,
            "requires_kitchen_ack": requires_ack,
        })
        return ok(public(rec), 201)

    @app.get("/add-ons/<aid>")
    def read_add_on(aid):
        ctx = auth(*CATALOG_READERS)
        add_on = must_get("add_ons", aid)
        own_restaurant(ctx, add_on["restaurant_id"])
        return ok(public(add_on))

    # ---------------------------------------------------------------- guests

    @app.post("/guests")
    def create_guest():
        ctx = auth("PlatformAdmin")
        body = ctx.body
        email = req_str(body, "email", max_len=160)
        display_name = req_str(body, "display_name", max_len=120)
        is_broker_flagged = opt_bool(body, "is_broker_flagged", False)
        unique_in("guests", "email", email)
        rec = new_record("guests", {
            "email": email,
            "display_name": display_name,
            "is_broker_flagged": is_broker_flagged,
            "no_show_strikes": 0,
            "completed_reservations_count": 0,
            "transfers_initiated_count": 0,
            "lifetime_refunded_cents": 0,
            "refund_scrutiny_flag": False,
        })
        return ok(public(rec), 201)

    @app.get("/guests/<gid>")
    def read_guest(gid):
        ctx = auth(*GUEST_READERS)
        if ctx.role == "Guest" and ctx.user_id != gid:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER",
                           "acting guest does not own this resource")
        return ok(public(must_get("guests", gid)))

    @app.get("/guests")
    def list_guests():
        auth("PlatformAdmin", "RestaurantManager", "GuestServices")
        pagination()
        items, limit, offset, total = window(filtered("guests", {
            "email": "email",
            "is_broker_flagged": "is_broker_flagged",
            "refund_scrutiny_flag": "refund_scrutiny_flag",
        }))
        return ok_list(items, limit, offset, total)
