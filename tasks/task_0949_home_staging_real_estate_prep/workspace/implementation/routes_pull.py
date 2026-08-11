"""Inventory pulls, pull lines and vendor rental orders (Pipeline V)."""
import calc
import consts as C
import lookup
import serializers as S
import store
from envelope import ok, paginate, pagination, qs
from errors import ApiError
from gates import (body, endpoint, enums, fks, occ, path_row, require,
                   rung13_order_vendor, rung14_project_closed, rung15_listing_terminated,
                   rung16_listing_closed, rung71_fiscal_hold, types)
from store import D, add_days, money


def _candidates(category, taken):
    rows = [i for i in store.all_rows("items")
            if i["status"] == "AVAILABLE" and i["category"] == category
            and i["id"] not in taken]
    return sorted(rows, key=lambda i: (i["acquired_at"], i["created_at"], i["_seq"]))


def _order_used(project, order_id, extra):
    used = 0
    for line in lookup.project_lines(project):
        if line.get("rental_order_id") == order_id and \
                line["state"] in ("ALLOCATED", "DEPLOYED", "RETURNED", "SWAPPED"):
            used += int(line["quantity"])
    return used + extra.get(order_id, 0)


def _plan_allocation(pull, project):
    """Walk the REQUESTED / UNFILLED lines in creation order and decide each one."""
    taken = set()
    extra = {}
    filled_delta = 0
    plan = []
    for line in lookup.pull_lines(pull):
        if line["state"] not in ("REQUESTED", "UNFILLED"):
            continue
        if line["source"] == "OWNED":
            cands = _candidates(line["category"], taken)
            if cands:
                item = cands[0]
                taken.add(item["id"])
                plan.append((line, "ALLOCATED", item, None))
                filled_delta += int(line["quantity"])
            else:
                plan.append((line, "UNFILLED", None, None))
        else:
            order = store.get("orders", line.get("rental_order_id"))
            spare = 0
            if order is not None and order["state"] in ("PLACED", "CONFIRMED"):
                spare = int(order["unit_count"]) - _order_used(project, order["id"], extra)
            if order is not None and order["state"] in ("PLACED", "CONFIRMED") \
                    and spare >= int(line["quantity"]):
                extra[order["id"]] = extra.get(order["id"], 0) + int(line["quantity"])
                plan.append((line, "ALLOCATED", None, order))
                filled_delta += int(line["quantity"])
            else:
                plan.append((line, "UNFILLED", None, None))
    return filled_delta, plan


def register(app):
    # ------------------------------------------------------------------
    # InventoryPull
    # ------------------------------------------------------------------
    @app.post("/staging/projects/<project_id>/pulls")
    @endpoint("WarehouseManager")
    def open_pull(project_id):
        project = path_row("projects", project_id)
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        if project["workflow_state"] != "AUTHORIZED":
            raise ApiError("ERR_PROJECT_INVALID_STATE")
        if project["pipeline"] != "VACANT_STAGING":
            raise ApiError("ERR_PIPELINE_MISMATCH")
        for existing in lookup.project_pulls(project):
            if existing["state"] in ("DRAFT", "SUBMITTED", "PARTIAL", "COMMITTED"):
                raise ApiError("ERR_PROJECT_INVALID_STATE")
        rung71_fiscal_hold(project)
        row = store.new_row("pulls", {
            "project_id": project["id"],
            "state": "DRAFT",
            "requested_unit_count": 0,
            "filled_unit_count": 0,
            "fill_rate": store.rate4(0),
            "resubmit_count": 0,
            "committed_at": None,
        })
        project["workflow_state"] = "PULL_OPEN"
        store.touch(project)
        return ok(S.pull(row), 201)

    @app.get("/staging/pulls")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def list_pulls():
        limit, offset = pagination()
        rows = store.where("pulls", project_id=qs("project_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.pull, limit, offset)

    @app.get("/staging/pulls/<pull_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def read_pull(pull_id):
        return ok(S.pull(path_row("pulls", pull_id)), 200)

    @app.post("/staging/pulls/<pull_id>/lines")
    @endpoint("WarehouseManager")
    def add_line(pull_id):
        pull = path_row("pulls", pull_id)
        payload = body()
        require(payload, ["source", "category", "room_label", "quantity"])
        if payload.get("source") == "VENDOR":
            require(payload, ["rental_order_id"])
        enums(payload, {"source": C.PULL_SOURCES, "category": C.ITEM_CATEGORIES})
        if payload.get("source") == "OWNED":
            types(payload, {"room_label": ("str",), "quantity": ("int", 1, 1),
                            "rental_order_id": ("str",)})
        else:
            types(payload, {"room_label": ("str",), "quantity": ("int", 1, 20),
                            "rental_order_id": ("str",)})
        fks(payload, {"rental_order_id": "orders"})
        project = lookup.project_of_pull(pull)
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if pull["state"] not in ("DRAFT", "PARTIAL"):
            raise ApiError("ERR_PULL_INVALID_STATE")
        consultation = lookup.consultation_of(project)
        labels = {i["room_label"] for i in lookup.consultation_scope_items(consultation)} \
            if consultation else set()
        if payload["room_label"] not in labels:
            raise ApiError("ERR_SCOPE_ITEM_NOT_FOUND")                  # rung 52
        row = store.new_row("pull_lines", {
            "pull_id": pull["id"],
            "inventory_item_id": None,
            "rental_order_id": (payload.get("rental_order_id")
                                if payload["source"] == "VENDOR" else None),
            "source": payload["source"],
            "category": payload["category"],
            "room_label": payload["room_label"],
            "quantity": int(payload["quantity"]),
            "monthly_rate": money(0),
            "state": "REQUESTED",
        })
        calc.recompute_pull(pull)
        store.touch(pull)
        return ok(S.pull_line(row), 201)

    @app.get("/staging/pull-lines")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def list_lines():
        limit, offset = pagination()
        rows = store.where("pull_lines", pull_id=qs("pull_id"),
                           inventory_item_id=qs("inventory_item_id"),
                           rental_order_id=qs("rental_order_id"), source=qs("source"),
                           state=qs("state"))
        return paginate(store.sort_default(rows), S.pull_line, limit, offset)

    @app.get("/staging/pull-lines/<pull_line_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator")
    def read_line(pull_line_id):
        return ok(S.pull_line(path_row("pull_lines", pull_line_id)), 200)

    @app.post("/staging/pulls/<pull_id>/submit")
    @endpoint("WarehouseManager")
    def submit_pull(pull_id):
        pull = path_row("pulls", pull_id)
        project = lookup.project_of_pull(pull)
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if pull["state"] not in ("DRAFT", "PARTIAL"):
            raise ApiError("ERR_PULL_INVALID_STATE")                    # rung 21
        requested, filled_now = calc.pull_counts(pull)
        if pull["state"] == "DRAFT" and requested < 1:
            raise ApiError("ERR_PULL_INVALID_STATE")
        filled_delta, plan = _plan_allocation(pull, project)
        if requested > 0 and (filled_now + filled_delta) == 0:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")                # rung 53
        resubmitting = pull["state"] == "PARTIAL"
        if resubmitting and int(pull["resubmit_count"]) >= C.MAX_PULL_RESUBMITS:
            raise ApiError("ERR_PULL_RESUBMIT_LIMIT")                   # rung 55

        for line, outcome, item, order in plan:
            if outcome == "ALLOCATED":
                line["state"] = "ALLOCATED"
                if item is not None:
                    line["inventory_item_id"] = item["id"]
                    item["status"] = "RESERVED"
                    store.touch(item)
                    line["monthly_rate"] = calc.line_monthly_rate(line, item=item)
                else:
                    vendor = store.get("vendors", order["vendor_id"])
                    line["monthly_rate"] = calc.line_monthly_rate(line, vendor=vendor)
            else:
                line["state"] = "UNFILLED"
            store.touch(line)

        if resubmitting:
            pull["resubmit_count"] = int(pull["resubmit_count"]) + 1
        calc.recompute_pull(pull)
        pull["state"] = "SUBMITTED"
        if int(pull["filled_unit_count"]) < int(pull["requested_unit_count"]):
            pull["state"] = "PARTIAL"
        store.touch(pull)
        return ok(S.pull(pull), 200)

    @app.post("/staging/pulls/<pull_id>/commit")
    @endpoint("WarehouseManager")
    def commit_pull(pull_id):
        pull = path_row("pulls", pull_id)
        payload = body()
        require(payload, ["expected_project_version"])
        types(payload, {"expected_project_version": ("int", 0, None)})
        project = lookup.project_of_pull(pull)
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if pull["state"] not in ("SUBMITTED", "PARTIAL"):
            raise ApiError("ERR_PULL_INVALID_STATE")                    # rung 21
        occ(payload, "expected_project_version", project, "ERR_STALE_PROJECT_VERSION")
        if D(pull["fill_rate"]) < C.PULL_PARTIAL_FILL_MIN_PCT:
            raise ApiError("ERR_FILL_RATE_BELOW_MINIMUM")               # rung 54
        pull["state"] = "COMMITTED"
        pull["committed_at"] = store.now()
        for line in lookup.pull_lines(pull):
            if line["state"] == "UNFILLED":
                line["state"] = "DROPPED"
                store.touch(line)
        store.touch(pull)
        if project["workflow_state"] == "RESTAGE_REQUIRED":
            project["workflow_state"] = "STAGED"
        store.touch(project)
        return ok(S.pull(pull), 200)

    @app.post("/staging/pulls/<pull_id>/release")
    @endpoint("WarehouseManager")
    def release_pull(pull_id):
        pull = path_row("pulls", pull_id)
        if pull["state"] != "COMMITTED":
            raise ApiError("ERR_PULL_INVALID_STATE")
        project = lookup.project_of_pull(pull)
        pull["state"] = "RELEASED"
        for line in lookup.pull_lines(pull):
            if line["state"] == "DEPLOYED":
                line["state"] = "RETURNED"
                store.touch(line)
        for order in lookup.project_orders(project):
            if order["state"] == "DELIVERED":
                order["state"] = "RETURNED"
                store.touch(order)
        store.touch(pull)
        return ok(S.pull(pull), 200)

    @app.post("/staging/pulls/<pull_id>/cancel")
    @endpoint("WarehouseManager")
    def cancel_pull(pull_id):
        pull = path_row("pulls", pull_id)
        if pull["state"] not in ("DRAFT", "SUBMITTED", "PARTIAL"):
            raise ApiError("ERR_PULL_INVALID_STATE")
        for line in lookup.pull_lines(pull):
            if line["state"] == "ALLOCATED":
                item = store.get("items", line.get("inventory_item_id"))
                if item is not None and item["status"] == "RESERVED":
                    item["status"] = "AVAILABLE"
                    store.touch(item)
                line["inventory_item_id"] = None
            if line["state"] != "DROPPED":
                line["state"] = "DROPPED"
                store.touch(line)
        pull["state"] = "CANCELLED"
        calc.recompute_pull(pull)
        store.touch(pull)
        return ok(S.pull(pull), 200)

    # ------------------------------------------------------------------
    # RentalOrder
    # ------------------------------------------------------------------
    @app.post("/staging/rental-orders")
    @endpoint("WarehouseManager")
    def create_order():
        payload = body()
        require(payload, ["project_id", "vendor_id", "unit_count"])
        types(payload, {"project_id": ("str",), "vendor_id": ("str",),
                        "unit_count": ("int", 1, 60)})
        fks(payload, {"project_id": "projects", "vendor_id": "vendors"})
        project = store.get("projects", payload["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        row = store.new_row("orders", {
            "project_id": project["id"],
            "vendor_id": payload["vendor_id"],
            "state": "DRAFT",
            "unit_count": int(payload["unit_count"]),
            "placed_at": None,
            "earliest_delivery_date": None,
            "cancel_cutoff_date": None,
            "effective_term_cycles": None,
            "monthly_rate_total": None,
            "cancellation_fee": money(0),
        })
        return ok(S.order(row), 201)

    @app.get("/staging/rental-orders")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "VendorRep")
    def list_orders():
        limit, offset = pagination()
        rows = store.where("orders", project_id=qs("project_id"), vendor_id=qs("vendor_id"),
                           state=qs("state"))
        return paginate(store.sort_default(rows), S.order, limit, offset)

    @app.get("/staging/rental-orders/<rental_order_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "VendorRep")
    def read_order(rental_order_id):
        return ok(S.order(path_row("orders", rental_order_id)), 200)

    @app.post("/staging/rental-orders/<rental_order_id>/place")
    @endpoint("WarehouseManager")
    def place_order(rental_order_id):
        order = path_row("orders", rental_order_id)
        project = store.get("projects", order["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        vendor = store.get("vendors", order["vendor_id"])
        if order["state"] != "DRAFT" or vendor["status"] != "ACTIVE":
            raise ApiError("ERR_ORDER_INVALID_STATE")
        order["state"] = "PLACED"
        order["placed_at"] = store.now()
        order["earliest_delivery_date"] = add_days(order["placed_at"],
                                                   int(vendor["lead_time_days"]))
        order["cancel_cutoff_date"] = add_days(order["earliest_delivery_date"],
                                               -int(vendor["cancel_cutoff_days"]))
        order["effective_term_cycles"] = calc.vendor_effective_term_cycles(order, vendor)
        order["monthly_rate_total"] = calc.vendor_order_monthly_rate(order, vendor)
        store.touch(order)
        return ok(S.order(order), 200)

    @app.post("/staging/rental-orders/<rental_order_id>/confirm")
    @endpoint("VendorRep")
    def confirm_order(rental_order_id):
        order = path_row("orders", rental_order_id)
        rung13_order_vendor(order)
        if order["state"] != "PLACED":
            raise ApiError("ERR_ORDER_INVALID_STATE")
        order["state"] = "CONFIRMED"
        store.touch(order)
        return ok(S.order(order), 200)

    @app.post("/staging/rental-orders/<rental_order_id>/cancel")
    @endpoint("WarehouseManager")
    def cancel_order(rental_order_id):
        order = path_row("orders", rental_order_id)
        cutoff = order.get("cancel_cutoff_date")
        late = cutoff is not None and store.now() >= cutoff
        if late:
            if order["state"] not in ("PLACED", "CONFIRMED"):
                raise ApiError("ERR_ORDER_INVALID_STATE")
            order["state"] = "CANCELLED_LATE"
        else:
            if order["state"] not in ("DRAFT", "PLACED"):
                raise ApiError("ERR_ORDER_INVALID_STATE")
            order["state"] = "CANCELLED"
        order["cancellation_fee"] = calc.vendor_cancellation_fee(order, late)
        project = store.get("projects", order["project_id"])
        for line in lookup.project_lines(project):
            if line["source"] == "VENDOR" and line.get("rental_order_id") == order["id"] \
                    and line["state"] != "DROPPED":
                line["state"] = "DROPPED"
                store.touch(line)
        store.touch(order)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.order(order), 200)
