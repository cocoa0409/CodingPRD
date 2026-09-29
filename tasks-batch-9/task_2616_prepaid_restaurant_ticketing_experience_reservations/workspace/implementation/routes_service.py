"""Services, ticket classes, release runs and the hold sweep."""
from common import (ApiError, DB, DOW_NAMES, Watch, clock, floor_div, must_get,
                    new_record, ok, ok_list, parse_iso, public, to_iso)
from calc import (apply_settlement, classes_of_service, entries_of_service,
                  minutes, promote_one,
                  reservations_of_service, rescore, restaurant_of_service,
                  return_seats, sync_class, sync_service, ticket_class_of)
from guards import (auth, filtered, opt_bool, opt_enum, opt_int, opt_str,
                    own_restaurant, pagination, req_date, req_dt, req_enum,
                    req_int, req_str, window)
from routes_catalog import CATALOG_READERS, own_body_restaurant

QUOTE_READERS = ("PlatformAdmin", "RestaurantManager", "GuestServices", "Guest")


def register(app):

    # -------------------------------------------------------------- services

    @app.post("/services")
    def create_service():
        ctx = auth("RestaurantManager")
        body = ctx.body
        own_body_restaurant(ctx)
        restaurant_id = req_str(body, "restaurant_id")
        must_get("restaurants", restaurant_id)
        service_date = req_date(body, "service_date")
        meal_period = req_enum(body, "meal_period", ("LUNCH", "DINNER"))
        seating_start = req_dt(body, "seating_start_utc")
        seating_end = req_dt(body, "seating_end_utc")
        if seating_end <= seating_start:
            raise ApiError("ERR_VALIDATION",
                           "seating_end_utc must fall strictly after seating_start_utc")
        turn_time = req_int(body, "turn_time_minutes", 15, 480)
        seats_capacity = req_int(body, "seats_capacity", 1, None)
        demand_tier = opt_enum(body, "demand_tier",
                               ("LOW", "STANDARD", "HIGH", "PEAK"), "STANDARD")
        unsold_release_bp = opt_int(body, "unsold_release_bp", 5000, 0, 10000)
        release_lead = opt_int(body, "release_lead_minutes", 180, 1, 10080)
        policy = opt_enum(body, "waitlist_policy",
                          ("FAIR_QUEUE", "YIELD_WEIGHTED"), "FAIR_QUEUE")
        prep_capacity = opt_int(body, "kitchen_prep_capacity_minutes", 600, 0, None)
        rec = new_record("services", {
            "restaurant_id": restaurant_id,
            "service_date": body["service_date"],
            "day_of_week": DOW_NAMES[service_date.weekday()],
            "meal_period": meal_period,
            "seating_start_utc": to_iso(seating_start),
            "seating_end_utc": to_iso(seating_end),
            "turn_time_minutes": turn_time,
            "demand_tier": demand_tier,
            "seats_capacity": seats_capacity,
            "unsold_release_bp": unsold_release_bp,
            "release_lead_minutes": release_lead,
            "waitlist_policy": policy,
            "kitchen_prep_capacity_minutes": prep_capacity,
            "status": "DRAFT",
            "release_run_count": 0,
            "seats_released_total": 0,
            "last_release_released_count": 0,
            "last_release_promoted_count": 0,
            "covers_confirmed": 0,
            "gross_charged_cents": 0,
            "refunded_cents": 0,
            "forfeited_cents": 0,
            "net_settled_cents": 0,
        })
        return ok(public(rec), 201)

    @app.get("/services/<sid>")
    def read_service(sid):
        ctx = auth(*CATALOG_READERS)
        service = must_get("services", sid)
        own_restaurant(ctx, service["restaurant_id"])
        return ok(public(service))

    @app.get("/services")
    def list_services():
        auth(*CATALOG_READERS)
        pagination()
        items, limit, offset, total = window(filtered("services", {
            "restaurant_id": "restaurant_id",
            "status": "status",
            "service_date": "service_date",
            "demand_tier": "demand_tier",
        }))
        return ok_list(items, limit, offset, total)

    @app.post("/services/<sid>/publish")
    def publish_service(sid):
        ctx = auth("RestaurantManager")
        service = must_get("services", sid)
        own_restaurant(ctx, service["restaurant_id"])
        if service["status"] != "DRAFT":
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "only a DRAFT service may be published")
        classes = classes_of_service(sid)
        if not classes:
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "a service needs at least one ticket class")
        allocated = sum(tc["seats_allocated"] for tc in classes)
        if allocated > service["seats_capacity"]:
            raise ApiError("ERR_SERVICE_CAPACITY_EXCEEDED",
                           "allocated seats exceed the service capacity")
        if parse_iso(service["seating_start_utc"]) <= clock():
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "seating_start_utc must lie after the logical clock")
        w = Watch()
        w.add(service)
        service["status"] = "PUBLISHED"
        for tc in classes:
            sync_class(tc, w)
        w.commit()
        return ok(public(service))

    @app.post("/services/<sid>/demand-tier")
    def retier_service(sid):
        ctx = auth("RestaurantManager")
        service = must_get("services", sid)
        own_restaurant(ctx, service["restaurant_id"])
        tier = req_enum(ctx.body, "demand_tier",
                        ("LOW", "STANDARD", "HIGH", "PEAK"))
        w = Watch()
        w.add(service)
        service["demand_tier"] = tier
        for tc in classes_of_service(sid):
            sync_class(tc, w)
        w.commit()
        return ok(public(service))

    @app.post("/services/<sid>/cancel")
    def cancel_service(sid):
        ctx = auth("RestaurantManager")
        service = must_get("services", sid)
        own_restaurant(ctx, service["restaurant_id"])
        opt_str(ctx.body, "reason_code")
        if service["status"] not in ("DRAFT", "PUBLISHED"):
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "only a DRAFT or PUBLISHED service may be cancelled")
        w = Watch()
        w.add(service)
        if service["status"] == "PUBLISHED":
            for res in reservations_of_service(sid):
                if res["fulfillment_status"] not in ("PENDING", "CONFIRMED"):
                    continue
                previous = res["fulfillment_status"]
                tc = ticket_class_of(res)
                w.add(res, tc)
                if previous == "PENDING":
                    return_seats(tc, res, w)
                else:
                    tc["seats_sold"] -= res["party_size"]
                    tc["seats_available"] += res["party_size"]
                    sync_class(tc, w)
                res["fulfillment_status"] = "CANCELLED"
                apply_settlement(res, "SERVICE_CANCEL", "SERVICE_CANCEL", w)
            for entry in entries_of_service(sid):
                if entry["status"] in ("WAITING", "OFFERED"):
                    w.add(entry)
                    entry["status"] = "WITHDRAWN"
        for tc in classes_of_service(sid):
            w.add(tc)
            tc["status"] = "CLOSED"
        service["status"] = "CANCELLED"
        sync_service(service, w)
        w.commit()
        return ok(public(service))

    @app.post("/services/<sid>/release-run")
    def release_run(sid):
        ctx = auth("RestaurantManager")
        service = must_get("services", sid)
        own_restaurant(ctx, service["restaurant_id"])
        if service["status"] != "PUBLISHED":
            raise ApiError("ERR_SERVICE_NOT_PUBLISHED",
                           "release runs require a PUBLISHED service")
        window_opens = (parse_iso(service["seating_start_utc"])
                        - minutes(service["release_lead_minutes"]))
        if clock() < window_opens:
            raise ApiError("ERR_RELEASE_WINDOW_NOT_OPEN",
                           "the release window has not opened yet")
        w = Watch()
        w.add(service)
        classes = classes_of_service(sid)
        released_total = 0
        for tc in classes:
            if tc["status"] not in ("OPEN", "SOLD_OUT"):
                continue
            count = floor_div(tc["seats_available"] * service["unsold_release_bp"],
                              10000)
            if count <= 0:
                continue
            w.add(tc)
            tc["seats_available"] -= count
            tc["seats_released"] += count
            released_total += count
            sync_class(tc, w)
        promoted_total = 0
        for tc in classes:
            while tc["seats_released"] > 0:
                entry = promote_one(tc, "seats_released", w)
                if entry is None:
                    break
                promoted_total += 1
        service["release_run_count"] += 1
        service["seats_released_total"] += released_total
        service["last_release_released_count"] = released_total
        service["last_release_promoted_count"] = promoted_total
        sync_service(service, w)
        w.commit()
        return ok(public(service))

    @app.post("/services/<sid>/hold-sweep")
    def hold_sweep(sid):
        ctx = auth("PlatformAdmin")
        service = must_get("services", sid)
        close_service = opt_bool(ctx.body, "close_service", False)
        if service["status"] != "PUBLISHED":
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "the hold sweep requires a PUBLISHED service")
        if close_service and clock() < parse_iso(service["seating_end_utc"]):
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "the service may not be closed before seating_end_utc")
        restaurant = restaurant_of_service(service)
        w = Watch()
        w.add(service)
        for res in reservations_of_service(sid):
            if res["fulfillment_status"] != "PENDING":
                continue
            if res["hold_expires_at_utc"] is None:
                continue
            if clock() < parse_iso(res["hold_expires_at_utc"]):
                continue
            tc = ticket_class_of(res)
            w.add(res, tc)
            res["fulfillment_status"] = "EXPIRED"
            return_seats(tc, res, w)
            apply_settlement(res, "HOLD_LAPSE", "HOLD_LAPSE", w)
            for entry in entries_of_service(sid):
                if entry["status"] != "OFFERED":
                    continue
                if entry["offered_reservation_id"] != res["id"]:
                    continue
                w.add(entry)
                entry["offer_round"] += 1
                if entry["offer_round"] < restaurant["max_offer_rounds"]:
                    entry["status"] = "WAITING"
                    entry["offered_reservation_id"] = None
                    entry["offer_expires_at_utc"] = None
                else:
                    entry["status"] = "EXPIRED"
                rescore(entry, w)
        if close_service:
            for res in reservations_of_service(sid):
                if res["fulfillment_status"] == "PENDING":
                    raise ApiError(
                        "ERR_SERVICE_INVALID_STATE",
                        "a reservation is still PENDING on this service")
            for tc in classes_of_service(sid):
                w.add(tc)
                tc["status"] = "CLOSED"
            service["status"] = "CLOSED"
        sync_service(service, w)
        w.commit()
        return ok(public(service))

    # --------------------------------------------------------- ticket classes

    @app.post("/ticket-classes")
    def create_ticket_class():
        ctx = auth("RestaurantManager")
        body = ctx.body
        service_id = body.get("service_id")
        service = None
        if isinstance(service_id, str) and service_id.strip() != "":
            service = must_get("services", service_id)
            own_restaurant(ctx, service["restaurant_id"])
        package_id = body.get("package_id")
        package = None
        if isinstance(package_id, str) and package_id.strip() != "":
            package = must_get("packages", package_id)
        req_str(body, "service_id")
        req_str(body, "package_id")
        seats_allocated = req_int(body, "seats_allocated", 1, None)
        min_party = opt_int(body, "min_party_size", None, 1, 20)
        max_party = opt_int(body, "max_party_size", None, 1, 20)
        if service["status"] != "DRAFT":
            raise ApiError("ERR_SERVICE_INVALID_STATE",
                           "ticket classes may only be added to a DRAFT service")
        if package["restaurant_id"] != service["restaurant_id"]:
            raise ApiError("ERR_PACKAGE_RESTAURANT_MISMATCH",
                           "the package belongs to another restaurant")
        if min_party is None:
            min_party = package["min_party_size"]
        if max_party is None:
            max_party = package["max_party_size"]
        if (min_party > max_party or min_party < package["min_party_size"]
                or max_party > package["max_party_size"]):
            raise ApiError("ERR_PARTY_SIZE_OUT_OF_BAND",
                           "the class band must sit inside the package band")
        allocated = sum(tc["seats_allocated"]
                        for tc in classes_of_service(service["id"]))
        if allocated + seats_allocated > service["seats_capacity"]:
            raise ApiError("ERR_SERVICE_CAPACITY_EXCEEDED",
                           "allocated seats exceed the service capacity")
        rec = new_record("ticket_classes", {
            "service_id": service["id"],
            "package_id": package["id"],
            "seats_allocated": seats_allocated,
            "min_party_size": min_party,
            "max_party_size": max_party,
            "seats_sold": 0,
            "seats_held": 0,
            "seats_released": 0,
            "seats_available": seats_allocated,
            "sell_through_bp": 0,
            "list_price_per_cover_cents": 0,
            "release_price_per_cover_cents": 0,
            "status": "OPEN",
        })
        sync_class(rec)
        return ok(public(rec), 201)

    @app.get("/ticket-classes/<tcid>")
    def read_ticket_class(tcid):
        ctx = auth(*CATALOG_READERS)
        tc = must_get("ticket_classes", tcid)
        own_restaurant(ctx, DB["services"][tc["service_id"]]["restaurant_id"])
        return ok(public(tc))

    @app.get("/ticket-classes")
    def list_ticket_classes():
        auth(*CATALOG_READERS)
        pagination()
        items, limit, offset, total = window(filtered("ticket_classes", {
            "service_id": "service_id",
            "package_id": "package_id",
            "status": "status",
        }))
        return ok_list(items, limit, offset, total)

    @app.get("/ticket-classes/<tcid>/price-quote")
    def price_quote(tcid):
        ctx = auth(*QUOTE_READERS)
        tc = must_get("ticket_classes", tcid)
        own_restaurant(ctx, DB["services"][tc["service_id"]]["restaurant_id"])
        w = Watch()
        sync_class(tc, w)
        w.commit()
        return ok(public(tc))

    @app.post("/ticket-classes/<tcid>/pause")
    def pause_ticket_class(tcid):
        ctx = auth("RestaurantManager")
        tc = must_get("ticket_classes", tcid)
        service = DB["services"][tc["service_id"]]
        own_restaurant(ctx, service["restaurant_id"])
        if tc["status"] != "OPEN":
            raise ApiError("ERR_TICKET_CLASS_INVALID_STATE",
                           "only an OPEN class may be paused")
        w = Watch()
        w.add(tc)
        tc["status"] = "PAUSED"
        w.commit()
        return ok(public(tc))

    @app.post("/ticket-classes/<tcid>/resume")
    def resume_ticket_class(tcid):
        ctx = auth("RestaurantManager")
        tc = must_get("ticket_classes", tcid)
        service = DB["services"][tc["service_id"]]
        own_restaurant(ctx, service["restaurant_id"])
        if service["status"] != "PUBLISHED":
            raise ApiError("ERR_SERVICE_NOT_PUBLISHED",
                           "a class may only be resumed while its service trades")
        if tc["status"] != "PAUSED":
            raise ApiError("ERR_TICKET_CLASS_INVALID_STATE",
                           "only a PAUSED class may be resumed")
        w = Watch()
        w.add(tc)
        tc["status"] = "OPEN"
        sync_class(tc, w)
        w.commit()
        return ok(public(tc))
