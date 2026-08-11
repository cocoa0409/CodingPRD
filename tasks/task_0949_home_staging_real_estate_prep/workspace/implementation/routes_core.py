"""Clock, brokerages, clients, properties, listings, tiers, vendors, inventory."""
import calc
import cascades
import consts as C
import gates
import lookup
import serializers as S
import store
from envelope import ok, paginate, pagination, qs
from errors import ApiError
from gates import (body, endpoint, enums, fks, path_row, require, rung10_listing_agent,
                   rung15_listing_terminated, types)
from store import D, add_days, money


def unique_or_400(collection, field, value):
    for row in store.all_rows(collection):
        if row.get(field) == value:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be unique." % field)


def register(app):
    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    @app.post("/staging/_clock/set_current_utc")
    @endpoint("PlatformAdmin")
    def set_clock():
        payload = body()
        require(payload, ["to_iso8601"])
        types(payload, {"to_iso8601": ("dt",)})
        store.set_clock(store.parse_dt(payload["to_iso8601"]))
        return ok({"current_utc": store.iso(store.now())}, 200)

    # ------------------------------------------------------------------
    # Brokerage
    # ------------------------------------------------------------------
    @app.post("/staging/brokerages")
    @endpoint("PlatformAdmin")
    def create_brokerage():
        payload = body()
        require(payload, ["name", "license_code"])
        types(payload, {"name": ("str",), "license_code": ("str",),
                        "authorization_cap": ("num", 0, 15000),
                        "tax_exempt": ("bool",), "billing_email": ("str",)})
        unique_or_400("brokerages", "license_code", payload["license_code"])
        row = store.new_row("brokerages", {
            "name": payload["name"],
            "license_code": payload["license_code"],
            "authorization_cap": money(payload.get("authorization_cap")
                                       if payload.get("authorization_cap") is not None
                                       else C.AGENT_AUTHORIZATION_DEFAULT_CAP),
            "tax_exempt": bool(payload.get("tax_exempt", False)),
            "billing_email": payload.get("billing_email"),
            "open_project_count": 0,
        })
        return ok(S.brokerage(row), 201)

    @app.get("/staging/brokerages/<brokerage_id>")
    @endpoint("PlatformAdmin", "BillingClerk", "BrokerageAdmin")
    def read_brokerage(brokerage_id):
        return ok(S.brokerage(path_row("brokerages", brokerage_id)), 200)

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------
    @app.post("/staging/clients")
    @endpoint("PlatformAdmin", "StagingCoordinator")
    def create_client():
        payload = body()
        require(payload, ["client_type", "full_name", "email"])
        if payload.get("client_type") in ("LISTING_AGENT", "BROKERAGE_ADMIN"):
            require(payload, ["brokerage_id"])
        enums(payload, {"client_type": C.CLIENT_TYPES})
        types(payload, {"full_name": ("str",), "email": ("str",),
                        "brokerage_id": ("str",),
                        "personal_authorization_cap": ("num", 0, None)})
        fks(payload, {"brokerage_id": "brokerages"})
        unique_or_400("clients", "email", payload["email"])
        brokerage_id = payload.get("brokerage_id")
        if payload["client_type"] == "SELLER":
            brokerage_id = None
        row = store.new_row("clients", {
            "brokerage_id": brokerage_id,
            "client_type": payload["client_type"],
            "full_name": payload["full_name"],
            "email": payload["email"],
            "personal_authorization_cap": money(
                payload.get("personal_authorization_cap")
                if payload.get("personal_authorization_cap") is not None
                else C.AGENT_AUTHORIZATION_DEFAULT_CAP),
            "consent_on_file": False,
        })
        row["effective_authorization_cap"] = calc.effective_authorization_cap(row)
        return ok(S.client(row), 201)

    @app.get("/staging/clients")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk", "BrokerageAdmin")
    def list_clients():
        limit, offset = pagination()
        rows = store.where("clients", brokerage_id=qs("brokerage_id"),
                           client_type=qs("client_type"), email=qs("email"))
        return paginate(store.sort_default(rows), S.client, limit, offset)

    @app.get("/staging/clients/<client_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk", "ListingAgent",
              "Seller", "BrokerageAdmin")
    def read_client(client_id):
        return ok(S.client(path_row("clients", client_id)), 200)

    @app.post("/staging/clients/<client_id>/seller-consent")
    @endpoint("Seller", "PlatformAdmin")
    def seller_consent(client_id):
        row = path_row("clients", client_id)
        if gates.role() == "Seller" and gates.actor() != row["id"]:
            raise ApiError("ERR_NOT_PROPERTY_OWNER")
        row["consent_on_file"] = True
        store.touch(row)
        return ok(S.client(row), 200)

    # ------------------------------------------------------------------
    # Property
    # ------------------------------------------------------------------
    @app.post("/staging/properties")
    @endpoint("PlatformAdmin", "StagingCoordinator")
    def create_property():
        payload = body()
        require(payload, ["owner_client_id", "address_line", "city", "state_code",
                          "distance_miles", "occupancy", "room_count"])
        enums(payload, {"occupancy": C.OCCUPANCIES})
        types(payload, {"owner_client_id": ("str",), "address_line": ("str",),
                        "city": ("str",), "state_code": ("str",),
                        "distance_miles": ("num", 0, 500), "room_count": ("int", 1, 40)})
        fks(payload, {"owner_client_id": "clients"})
        owner = store.get("clients", payload["owner_client_id"])
        if owner["client_type"] != "SELLER":
            raise ApiError("ERR_INVALID_REQUEST", "owner_client_id must reference a SELLER.")
        row = store.new_row("properties", {
            "owner_client_id": payload["owner_client_id"],
            "address_line": payload["address_line"],
            "city": payload["city"],
            "state_code": payload["state_code"],
            "distance_miles": D(payload["distance_miles"]),
            "occupancy": payload["occupancy"],
            "room_count": payload["room_count"],
            "prep_state": "NEW",
        })
        return ok(S.property_(row), 201)

    @app.get("/staging/properties")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def list_properties():
        limit, offset = pagination()
        rows = store.where("properties", owner_client_id=qs("owner_client_id"),
                           occupancy=qs("occupancy"), prep_state=qs("prep_state"))
        return paginate(store.sort_default(rows), S.property_, limit, offset)

    @app.get("/staging/properties/<property_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def read_property(property_id):
        return ok(S.property_(path_row("properties", property_id)), 200)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    @app.post("/staging/listings")
    @endpoint("PlatformAdmin", "StagingCoordinator", "ListingAgent")
    def create_listing():
        payload = body()
        require(payload, ["property_id", "listing_agent_client_id", "mls_number", "list_price"])
        types(payload, {"property_id": ("str",), "listing_agent_client_id": ("str",),
                        "mls_number": ("str",), "list_price": ("num_ex", 0, None)})
        fks(payload, {"property_id": "properties", "listing_agent_client_id": "clients"})
        agent = store.get("clients", payload["listing_agent_client_id"])
        if agent["client_type"] != "LISTING_AGENT":
            raise ApiError("ERR_INVALID_REQUEST",
                           "listing_agent_client_id must reference a LISTING_AGENT.")
        unique_or_400("listings", "mls_number", payload["mls_number"])
        row = store.new_row("listings", {
            "property_id": payload["property_id"],
            "listing_agent_client_id": payload["listing_agent_client_id"],
            "mls_number": payload["mls_number"],
            "list_price": money(payload["list_price"]),
            "listing_state": "ACTIVE",
            "under_contract_at": None,
            "closed_at": None,
            "fallout_count": 0,
        })
        return ok(S.listing(row), 201)

    @app.get("/staging/listings")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk", "ListingAgent", "Seller")
    def list_listings():
        limit, offset = pagination()
        rows = store.where("listings", property_id=qs("property_id"),
                           listing_agent_client_id=qs("listing_agent_client_id"),
                           listing_state=qs("listing_state"))
        return paginate(store.sort_default(rows), S.listing, limit, offset)

    @app.get("/staging/listings/<listing_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk", "ListingAgent", "Seller")
    def read_listing(listing_id):
        return ok(S.listing(path_row("listings", listing_id)), 200)

    def _listing_origin(listing, legal):
        state = listing["listing_state"]
        if state in legal:
            return
        if state == "TERMINATED":
            raise ApiError("ERR_LISTING_TERMINATED")
        if state == "CLOSED_SOLD":
            raise ApiError("ERR_LISTING_CLOSED")
        raise ApiError("ERR_LISTING_NOT_UNDER_CONTRACT")

    @app.post("/staging/listings/<listing_id>/under-contract")
    @endpoint("ListingAgent", "PlatformAdmin")
    def listing_under_contract(listing_id):
        listing = path_row("listings", listing_id)
        rung10_listing_agent(listing)
        rung15_listing_terminated(listing)
        _listing_origin(listing, {"ACTIVE", "BACK_ON_MARKET"})
        listing["listing_state"] = "UNDER_CONTRACT"
        cascades.listing_under_contract(listing)
        return ok(S.listing(listing), 200)

    @app.post("/staging/listings/<listing_id>/fall-out-of-escrow")
    @endpoint("ListingAgent", "PlatformAdmin")
    def listing_fall_out(listing_id):
        listing = path_row("listings", listing_id)
        rung10_listing_agent(listing)
        rung15_listing_terminated(listing)
        _listing_origin(listing, {"UNDER_CONTRACT"})
        listing["listing_state"] = "BACK_ON_MARKET"
        cascades.listing_fall_out(listing)
        for project in store.where("projects", listing_id=listing["id"]):
            cascades.property_hop(lookup.property_of(project), "DESTAGED", "IN_PREP")
        return ok(S.listing(listing), 200)

    @app.post("/staging/listings/<listing_id>/close")
    @endpoint("ListingAgent", "PlatformAdmin")
    def listing_close(listing_id):
        listing = path_row("listings", listing_id)
        rung10_listing_agent(listing)
        _listing_origin(listing, {"UNDER_CONTRACT"})
        # rung 70 - the deferral must not have run out
        for project in store.where("projects", listing_id=listing["id"]):
            for invoice in store.where("invoices", project_id=project["id"]):
                if invoice["state"] != "DEFERRED_CLOSING":
                    continue
                issued = invoice.get("issued_at")
                if issued is not None and store.now() > add_days(issued,
                                                                 C.CLOSING_DEFERRAL_MAX_DAYS):
                    raise ApiError("ERR_CLOSING_DEFERRAL_EXPIRED")
        listing["listing_state"] = "CLOSED_SOLD"
        cascades.listing_close(listing)
        return ok(S.listing(listing), 200)

    @app.post("/staging/listings/<listing_id>/terminate")
    @endpoint("ListingAgent", "PlatformAdmin")
    def listing_terminate(listing_id):
        listing = path_row("listings", listing_id)
        payload = body()
        require(payload, ["termination_reason"])
        types(payload, {"termination_reason": ("str",)})
        rung10_listing_agent(listing)
        rung15_listing_terminated(listing)
        _listing_origin(listing, {"ACTIVE", "BACK_ON_MARKET"})
        listing["listing_state"] = "TERMINATED"
        listing["termination_reason"] = payload["termination_reason"]
        cascades.listing_terminate(listing)
        return ok(S.listing(listing), 200)

    # ------------------------------------------------------------------
    # PackageTier
    # ------------------------------------------------------------------
    @app.post("/staging/package-tiers")
    @endpoint("PlatformAdmin")
    def create_tier():
        payload = body()
        require(payload, ["tier_code", "tier_rank", "room_cap", "included_accessory_sets",
                          "included_photo_sessions", "base_price", "monthly_rent_rate"])
        enums(payload, {"tier_code": C.TIER_CODES})
        types(payload, {"tier_rank": ("int", 1, 3), "room_cap": ("int", 0, None),
                        "included_accessory_sets": ("int", 0, None),
                        "included_photo_sessions": ("int", 0, None),
                        "base_price": ("num", 0, None), "monthly_rent_rate": ("num", 0, None)})
        unique_or_400("tiers", "tier_code", payload["tier_code"])
        row = store.new_row("tiers", {
            "tier_code": payload["tier_code"],
            "tier_rank": payload["tier_rank"],
            "room_cap": payload["room_cap"],
            "included_accessory_sets": payload["included_accessory_sets"],
            "included_photo_sessions": payload["included_photo_sessions"],
            "base_price": money(payload["base_price"]),
            "monthly_rent_rate": money(payload["monthly_rent_rate"]),
        }, common=False)
        return ok(S.tier(row), 201)

    @app.get("/staging/package-tiers")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def list_tiers():
        limit, offset = pagination()
        rows = store.where("tiers", tier_code=qs("tier_code"))
        return paginate(store.sort_default(rows), S.tier, limit, offset)

    @app.get("/staging/package-tiers/<tier_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def read_tier(tier_id):
        return ok(S.tier(path_row("tiers", tier_id)), 200)

    # ------------------------------------------------------------------
    # VendorPartner
    # ------------------------------------------------------------------
    @app.post("/staging/vendors")
    @endpoint("PlatformAdmin", "WarehouseManager")
    def create_vendor():
        payload = body()
        require(payload, ["name"])
        types(payload, {"name": ("str",), "lead_time_days": ("int", 0, None),
                        "min_lease_cycles": ("int", 0, None),
                        "cancel_cutoff_days": ("int", 0, None),
                        "rate_multiplier": ("num", 0, None)})
        row = store.new_row("vendors", {
            "name": payload["name"],
            "lead_time_days": payload.get("lead_time_days", C.VENDOR_DEFAULT_LEAD_TIME_DAYS),
            "min_lease_cycles": payload.get("min_lease_cycles",
                                            C.VENDOR_DEFAULT_MIN_LEASE_CYCLES),
            "cancel_cutoff_days": payload.get("cancel_cutoff_days",
                                              C.VENDOR_DEFAULT_CANCEL_CUTOFF_DAYS),
            "rate_multiplier": D(payload.get("rate_multiplier",
                                             C.VENDOR_RATE_MULTIPLIER_DEFAULT)),
            "status": "ACTIVE",
        })
        return ok(S.vendor(row), 201)

    @app.get("/staging/vendors")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "VendorRep")
    def list_vendors():
        limit, offset = pagination()
        rows = store.where("vendors", status=qs("status"))
        return paginate(store.sort_default(rows), S.vendor, limit, offset)

    @app.get("/staging/vendors/<vendor_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "VendorRep")
    def read_vendor(vendor_id):
        return ok(S.vendor(path_row("vendors", vendor_id)), 200)

    @app.patch("/staging/vendors/<vendor_id>")
    @endpoint("PlatformAdmin", "WarehouseManager")
    def update_vendor(vendor_id):
        row = path_row("vendors", vendor_id)
        payload = body()
        require(payload, [])
        enums(payload, {"status": C.VENDOR_STATUSES})
        types(payload, {"lead_time_days": ("int", 0, None),
                        "min_lease_cycles": ("int", 0, None),
                        "cancel_cutoff_days": ("int", 0, None),
                        "rate_multiplier": ("num", 0, None)})
        for field in ("status", "lead_time_days", "min_lease_cycles", "cancel_cutoff_days"):
            if payload.get(field) is not None:
                row[field] = payload[field]
        if payload.get("rate_multiplier") is not None:
            row["rate_multiplier"] = D(payload["rate_multiplier"])
        store.touch(row)
        return ok(S.vendor(row), 200)

    # ------------------------------------------------------------------
    # InventoryItem
    # ------------------------------------------------------------------
    @app.post("/staging/inventory-items")
    @endpoint("PlatformAdmin", "WarehouseManager")
    def create_item():
        payload = body()
        require(payload, ["sku", "category", "acquired_at", "replacement_value", "monthly_rate"])
        enums(payload, {"category": C.ITEM_CATEGORIES})
        types(payload, {"sku": ("str",), "acquired_at": ("dt",),
                        "replacement_value": ("num", 0, None), "monthly_rate": ("num", 0, None)})
        unique_or_400("items", "sku", payload["sku"])
        row = store.new_row("items", {
            "sku": payload["sku"],
            "category": payload["category"],
            "acquired_at": store.parse_dt(payload["acquired_at"]),
            "replacement_value": money(payload["replacement_value"]),
            "monthly_rate": money(payload["monthly_rate"]),
            "condition_grade": "A",
            "status": "AVAILABLE",
            "times_deployed": 0,
        })
        return ok(S.item(row), 201)

    @app.get("/staging/inventory-items")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def list_items():
        limit, offset = pagination()
        rows = store.where("items", category=qs("category"), status=qs("status"),
                           sku=qs("sku"))
        return paginate(store.sort_default(rows), S.item, limit, offset)

    @app.get("/staging/inventory-items/summary")
    @endpoint("PlatformAdmin", "WarehouseManager")
    def item_summary():
        category = qs("category")
        rows = [r for r in store.all_rows("items")
                if category is None or r["category"] == category]
        counts = {"AVAILABLE": 0, "RESERVED": 0, "DEPLOYED": 0, "IN_REPAIR": 0, "WRITTEN_OFF": 0}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return ok({
            "on_hand_total": len(rows),
            "available": counts["AVAILABLE"],
            "reserved": counts["RESERVED"],
            "deployed": counts["DEPLOYED"],
            "in_repair": counts["IN_REPAIR"],
            "written_off": counts["WRITTEN_OFF"],
        }, 200)

    @app.get("/staging/inventory-items/<item_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def read_item(item_id):
        return ok(S.item(path_row("items", item_id)), 200)

    @app.post("/staging/inventory-items/<item_id>/repair-in")
    @endpoint("WarehouseManager", "PlatformAdmin")
    def item_repair_in(item_id):
        row = path_row("items", item_id)
        if row["status"] != "AVAILABLE":
            raise ApiError("ERR_ITEM_INVALID_STATE")
        row["status"] = "IN_REPAIR"
        store.touch(row)
        return ok(S.item(row), 200)

    @app.post("/staging/inventory-items/<item_id>/repair-out")
    @endpoint("WarehouseManager", "PlatformAdmin")
    def item_repair_out(item_id):
        row = path_row("items", item_id)
        if row["status"] != "IN_REPAIR":
            raise ApiError("ERR_ITEM_INVALID_STATE")
        row["status"] = "AVAILABLE"
        store.touch(row)
        return ok(S.item(row), 200)

    @app.post("/staging/inventory-items/<item_id>/write-off")
    @endpoint("WarehouseManager", "PlatformAdmin")
    def item_write_off(item_id):
        row = path_row("items", item_id)
        payload = body()
        require(payload, ["reason"])
        types(payload, {"reason": ("str",)})
        if row["status"] not in ("AVAILABLE", "IN_REPAIR"):
            raise ApiError("ERR_ITEM_INVALID_STATE")
        row["status"] = "WRITTEN_OFF"
        store.touch(row)
        return ok(S.item(row), 200)
