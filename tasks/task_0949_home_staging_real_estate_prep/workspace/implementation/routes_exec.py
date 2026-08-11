"""Installs (Pipeline V), visits (Pipeline O), leases and extensions."""
import calc
import cascades
import consts as C
import lookup
import serializers as S
import store
from envelope import ok, paginate, pagination, qs
from errors import ApiError
from gates import (body, endpoint, enums, occ, path_row, require, rung14_project_closed,
                   rung15_listing_terminated, rung16_listing_closed, rung34_not_too_early,
                   rung71_fiscal_hold, types)
from store import D, add_days, money


def _consumed_orders(project):
    return [o for o in lookup.project_orders(project) if o["state"] in ("PLACED", "CONFIRMED")]


def _crew_load(day, exclude_id=None):
    count = 0
    for install in store.all_rows("installs"):
        if exclude_id is not None and install["id"] == exclude_id:
            continue
        if install["state"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if install["scheduled_at"].date() == day:
            count += 1
    return count


def register(app):
    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------
    @app.post("/staging/projects/<project_id>/installs")
    @endpoint("StagingCoordinator")
    def schedule_install(project_id):
        project = path_row("projects", project_id)
        payload = body()
        require(payload, ["scheduled_at", "crew_size", "initial_cycles"])
        types(payload, {"scheduled_at": ("dt",), "crew_size": ("int", 1, 8),
                        "initial_cycles": ("int", 0, 24)})
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        if project["workflow_state"] != "PULL_OPEN":
            raise ApiError("ERR_PROJECT_INVALID_STATE")                 # rung 19
        if project["pipeline"] != "VACANT_STAGING":
            raise ApiError("ERR_PIPELINE_MISMATCH")                     # rung 20
        pull = lookup.active_pull(project)
        if pull is None or pull["state"] != "COMMITTED":
            raise ApiError("ERR_PULL_INVALID_STATE")                    # rung 21

        scheduled_at = store.parse_dt(payload["scheduled_at"])
        initial_cycles = int(payload["initial_cycles"])
        orders = _consumed_orders(project)
        for order in orders:                                            # rung 42
            edd = order.get("earliest_delivery_date")
            if edd is not None and scheduled_at < edd:
                raise ApiError("ERR_VENDOR_LEAD_TIME_VIOLATION")
        if initial_cycles < C.MIN_LEASE_CYCLES:                         # rung 43
            raise ApiError("ERR_BELOW_MIN_LEASE_TERM")
        for order in orders:                                            # rung 44
            term = order.get("effective_term_cycles")
            if term is not None and int(term) > initial_cycles + C.MAX_EXTENSION_CYCLES_TOTAL:
                raise ApiError("ERR_VENDOR_MIN_TERM_VIOLATION")
        if _crew_load(scheduled_at.date()) >= C.CREW_DAY_CAPACITY:      # rung 61
            raise ApiError("ERR_CREW_DOUBLE_BOOKED")
        deposit = lookup.project_deposit(project)                       # rung 66
        if deposit is None or deposit["state"] != "HELD":
            raise ApiError("ERR_DEPOSIT_NOT_HELD")
        rung71_fiscal_hold(project)

        row = store.new_row("installs", {
            "project_id": project["id"],
            "scheduled_at": scheduled_at,
            "crew_size": int(payload["crew_size"]),
            "state": "SCHEDULED",
            "completed_at": None,
            "attempt_count": 0,
        })
        store.new_row("leases", {
            "project_id": project["id"],
            "initial_cycles": initial_cycles,
            "extension_cycles": 0,
            "billed_cycles": 0,
            "state": "PENDING",
            "start_date": None,
            "end_date": None,
            "pickup_window_start": None,
            "pickup_window_end": None,
            "monthly_rent": money(0),
            "holdover_days": 0,
            "holdover_charge": money(0),
            "holdover_cap_period_start": None,
        })
        project["workflow_state"] = "INSTALL_SCHEDULED"
        store.touch(project)
        return ok(S.install(row), 201)

    @app.get("/staging/installs")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager")
    def list_installs():
        limit, offset = pagination()
        rows = store.where("installs", project_id=qs("project_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.install, limit, offset)

    @app.get("/staging/installs/<install_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager")
    def read_install(install_id):
        return ok(S.install(path_row("installs", install_id)), 200)

    @app.post("/staging/installs/<install_id>/start")
    @endpoint("StagingCoordinator")
    def start_install(install_id):
        install = path_row("installs", install_id)
        project = store.get("projects", install["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        pull = lookup.active_pull(project)
        if pull is None or pull["state"] != "COMMITTED":
            raise ApiError("ERR_PULL_INVALID_STATE")                    # rung 21
        if install["state"] != "SCHEDULED":
            raise ApiError("ERR_INSTALL_INVALID_STATE")                 # rung 24
        rung34_not_too_early(install["scheduled_at"])                   # rung 34
        install["state"] = "IN_PROGRESS"
        store.touch(install)
        return ok(S.install(install), 200)

    @app.post("/staging/installs/<install_id>/complete")
    @endpoint("StagingCoordinator")
    def complete_install(install_id):
        install = path_row("installs", install_id)
        project = store.get("projects", install["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if install["state"] != "IN_PROGRESS":
            raise ApiError("ERR_INSTALL_INVALID_STATE")
        deposit = lookup.project_deposit(project)
        if deposit is None or deposit["state"] != "HELD":
            raise ApiError("ERR_DEPOSIT_NOT_HELD")                      # rung 66
        cascades.install_complete(install, project)
        return ok(S.install(install), 200)

    @app.post("/staging/installs/<install_id>/no-access")
    @endpoint("StagingCoordinator")
    def no_access_install(install_id):
        install = path_row("installs", install_id)
        project = store.get("projects", install["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        state = install["state"]
        if state == "SCHEDULED":
            rung34_not_too_early(install["scheduled_at"])
            install["state"] = "NO_ACCESS"
        elif state == "NO_ACCESS" and \
                int(install["attempt_count"]) >= C.MAX_INSTALL_REATTEMPTS:
            rung34_not_too_early(install["scheduled_at"])
            install["state"] = "CANCELLED"
            pull = lookup.active_pull(project)
            for line in lookup.pull_lines(pull):
                item = store.get("items", line.get("inventory_item_id"))
                if item is not None and item["status"] == "RESERVED":
                    item["status"] = "AVAILABLE"
                    store.touch(item)
            lease = lookup.active_lease(project)
            if lease is not None and lease["state"] == "PENDING":
                lease["state"] = "CANCELLED"
                store.touch(lease)
        else:
            raise ApiError("ERR_INSTALL_INVALID_STATE")
        store.touch(install)
        return ok(S.install(install), 200)

    @app.post("/staging/installs/<install_id>/reschedule")
    @endpoint("StagingCoordinator")
    def reschedule_install(install_id):
        install = path_row("installs", install_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",)})
        project = store.get("projects", install["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if install["state"] != "NO_ACCESS":
            raise ApiError("ERR_INSTALL_INVALID_STATE")
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        for order in _consumed_orders(project):                         # rung 42
            edd = order.get("earliest_delivery_date")
            if edd is not None and scheduled_at < edd:
                raise ApiError("ERR_VENDOR_LEAD_TIME_VIOLATION")
        if int(install["attempt_count"]) >= C.MAX_INSTALL_REATTEMPTS:   # rung 56
            raise ApiError("ERR_INSTALL_ATTEMPT_LIMIT")
        if _crew_load(scheduled_at.date(), exclude_id=install["id"]) >= C.CREW_DAY_CAPACITY:
            raise ApiError("ERR_CREW_DOUBLE_BOOKED")                    # rung 61
        install["state"] = "SCHEDULED"
        install["scheduled_at"] = scheduled_at
        install["attempt_count"] = int(install["attempt_count"]) + 1
        store.touch(install)
        return ok(S.install(install), 200)

    # ------------------------------------------------------------------
    # Visit
    # ------------------------------------------------------------------
    @app.post("/staging/projects/<project_id>/visits")
    @endpoint("StagingCoordinator")
    def schedule_visit(project_id):
        project = path_row("projects", project_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",)})
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        if project["workflow_state"] not in ("AUTHORIZED", "VISITS_OPEN"):
            raise ApiError("ERR_PROJECT_INVALID_STATE")                 # rung 19
        if project["pipeline"] != "OCCUPIED_PREP":
            raise ApiError("ERR_PIPELINE_MISMATCH")                     # rung 20
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        window_end = project.get("service_window_end_date")
        if window_end is not None and scheduled_at > window_end:        # rung 63
            raise ApiError("ERR_SERVICE_WINDOW_EXPIRED")
        deposit = lookup.project_deposit(project)                       # rung 66
        if deposit is None or deposit["state"] != "HELD":
            raise ApiError("ERR_DEPOSIT_NOT_HELD")
        rung71_fiscal_hold(project)
        index = len(lookup.project_visits(project)) + 1
        row = store.new_row("visits", {
            "project_id": project["id"],
            "scheduled_at": scheduled_at,
            "visit_index": index,
            "hours_logged": D(0),
            "billable_hours": money(0),
            "state": "SCHEDULED",
            "attempt_count": 0,
        })
        if project["workflow_state"] == "AUTHORIZED":
            project["workflow_state"] = "VISITS_OPEN"
            store.touch(project)
        return ok(S.visit(row), 201)

    @app.get("/staging/visits")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk")
    def list_visits():
        limit, offset = pagination()
        rows = store.where("visits", project_id=qs("project_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.visit, limit, offset)

    @app.get("/staging/visits/<visit_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "BillingClerk")
    def read_visit(visit_id):
        return ok(S.visit(path_row("visits", visit_id)), 200)

    def _settle_visits(project):
        """"The project moves VISITS_OPEN -> STAGED once every visit on it is terminal --
        that is, every visit is either COMPLETED or CANCELLED -- and at least one is
        COMPLETED. That same moment carries the property IN_PREP -> STAGED."

        The transition is stated as a condition over the visit set, not as a side effect
        of one particular endpoint, so every arc that can make a visit terminal has to
        re-evaluate it: cancelling the last open visit settles the project exactly as
        completing the last open visit does.
        """
        if project is None or project["workflow_state"] != "VISITS_OPEN":
            return
        siblings = lookup.project_visits(project)
        if all(v["state"] in ("COMPLETED", "CANCELLED") for v in siblings) and \
                any(v["state"] == "COMPLETED" for v in siblings):
            project["workflow_state"] = "STAGED"
            store.touch(project)
            cascades.property_hop(lookup.property_of(project), "IN_PREP", "STAGED")

    @app.post("/staging/visits/<visit_id>/complete")
    @endpoint("StagingCoordinator")
    def complete_visit(visit_id):
        visit = path_row("visits", visit_id)
        payload = body()
        require(payload, ["hours_logged"])
        types(payload, {"hours_logged": ("num", 0, None)})
        project = store.get("projects", visit["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if visit["state"] != "SCHEDULED":
            raise ApiError("ERR_VISIT_INVALID_STATE")
        rung34_not_too_early(visit["scheduled_at"])
        window_end = project.get("service_window_end_date")
        if window_end is not None and store.now() > window_end:         # rung 63
            raise ApiError("ERR_SERVICE_WINDOW_EXPIRED")
        visit["state"] = "COMPLETED"
        visit["hours_logged"] = D(payload["hours_logged"])
        visit["billable_hours"] = calc.visit_billable_hours(visit)
        store.touch(visit)
        _settle_visits(project)
        return ok(S.visit(visit), 200)

    @app.post("/staging/visits/<visit_id>/no-access")
    @endpoint("StagingCoordinator")
    def no_access_visit(visit_id):
        visit = path_row("visits", visit_id)
        project = store.get("projects", visit["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if visit["state"] != "SCHEDULED":
            raise ApiError("ERR_VISIT_INVALID_STATE")
        rung34_not_too_early(visit["scheduled_at"])
        visit["state"] = "NO_ACCESS"
        store.touch(visit)
        return ok(S.visit(visit), 200)

    @app.post("/staging/visits/<visit_id>/reschedule")
    @endpoint("StagingCoordinator")
    def reschedule_visit(visit_id):
        visit = path_row("visits", visit_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",)})
        project = store.get("projects", visit["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if visit["state"] != "NO_ACCESS":
            raise ApiError("ERR_VISIT_INVALID_STATE")
        if int(visit["attempt_count"]) >= C.MAX_VISIT_REATTEMPTS:       # rung 57
            raise ApiError("ERR_VISIT_ATTEMPT_LIMIT")
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        window_end = project.get("service_window_end_date")
        if window_end is not None and scheduled_at > window_end:        # rung 63
            raise ApiError("ERR_SERVICE_WINDOW_EXPIRED")
        visit["state"] = "SCHEDULED"
        visit["scheduled_at"] = scheduled_at
        visit["attempt_count"] = int(visit["attempt_count"]) + 1
        store.touch(visit)
        return ok(S.visit(visit), 200)

    @app.post("/staging/visits/<visit_id>/cancel")
    @endpoint("StagingCoordinator")
    def cancel_visit(visit_id):
        visit = path_row("visits", visit_id)
        project = store.get("projects", visit["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if visit["state"] not in ("SCHEDULED", "NO_ACCESS"):
            raise ApiError("ERR_VISIT_INVALID_STATE")
        visit["state"] = "CANCELLED"
        store.touch(visit)
        _settle_visits(project)
        return ok(S.visit(visit), 200)

    # ------------------------------------------------------------------
    # Lease
    # ------------------------------------------------------------------
    @app.get("/staging/leases")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def list_leases():
        limit, offset = pagination()
        rows = store.where("leases", project_id=qs("project_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.lease, limit, offset)

    @app.get("/staging/leases/<lease_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller")
    def read_lease(lease_id):
        return ok(S.lease(path_row("leases", lease_id)), 200)

    @app.post("/staging/leases/<lease_id>/mark-term-complete")
    @endpoint("StagingCoordinator", "BillingClerk")
    def mark_term_complete(lease_id):
        lease = path_row("leases", lease_id)
        project = store.get("projects", lease["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if lease["state"] not in ("ACTIVE", "EXTENDED"):
            raise ApiError("ERR_LEASE_INVALID_STATE")
        cascades.begin_destage(project, lease)
        return ok(S.lease(lease), 200)

    @app.post("/staging/leases/<lease_id>/accrue-holdover")
    @endpoint("BillingClerk")
    def accrue_holdover(lease_id):
        lease = path_row("leases", lease_id)
        project = store.get("projects", lease["project_id"])
        if lease["state"] == "ENDING":
            window_end = lease.get("pickup_window_end")
            if window_end is None:
                raise ApiError("ERR_LEASE_INVALID_STATE")
            if store.now() <= add_days(window_end, C.HOLDOVER_GRACE_DAYS):
                raise ApiError("ERR_LEASE_INVALID_STATE")
            if any(p["state"] == "COMPLETED" for p in lookup.project_pickups(project)):
                raise ApiError("ERR_LEASE_INVALID_STATE")
            lease["state"] = "HOLDOVER"
            lease["holdover_cap_period_start"] = window_end
        elif lease["state"] != "HOLDOVER":
            raise ApiError("ERR_LEASE_INVALID_STATE")
        start = lease.get("holdover_cap_period_start")
        if start is not None:
            while store.now() >= add_days(start, C.HOLDOVER_CAP_PERIOD_DAYS):
                start = add_days(start, C.HOLDOVER_CAP_PERIOD_DAYS)
            lease["holdover_cap_period_start"] = start
        lease["holdover_days"] = calc.holdover_days(lease, project)
        lease["holdover_charge"] = calc.holdover_charge(lease["holdover_days"])
        store.touch(lease)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.lease(lease), 200)

    # ------------------------------------------------------------------
    # Extension
    # ------------------------------------------------------------------
    @app.post("/staging/leases/<lease_id>/extensions")
    @endpoint("StagingCoordinator", "ListingAgent")
    def request_extension(lease_id):
        lease = path_row("leases", lease_id)
        payload = body()
        require(payload, ["requested_cycles", "expected_lease_version"])
        types(payload, {"requested_cycles": ("int", 0, 12),
                        "expected_lease_version": ("int", 0, None)})
        project = store.get("projects", lease["project_id"])
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        if lease["state"] not in ("ACTIVE", "EXTENDED", "ENDING"):
            raise ApiError("ERR_LEASE_INVALID_STATE")                   # rung 26
        occ(payload, "expected_lease_version", lease, "ERR_STALE_LEASE_VERSION")
        requested = int(payload["requested_cycles"])
        if requested <= 0 or requested % C.EXTENSION_INCREMENT_CYCLES != 0:
            raise ApiError("ERR_PARTIAL_CYCLE_EXTENSION")               # rung 45
        if int(lease["extension_cycles"]) + requested > C.MAX_EXTENSION_CYCLES_TOTAL:
            raise ApiError("ERR_EXTENSION_LIMIT_REACHED")               # rung 46
        rung71_fiscal_hold(project)                                     # rung 71
        row = store.new_row("extensions", {
            "lease_id": lease["id"],
            "requested_cycles": requested,
            "state": "REQUESTED",
            "granted_cycles": 0,
            "extended_line_count": 0,
            "returned_line_count": 0,
            "extension_charge": money(0),
            "swap_credit": money(0),
        })
        store.touch(lease)
        return ok(S.extension(row), 201)

    @app.get("/staging/extensions")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "ListingAgent")
    def list_extensions():
        limit, offset = pagination()
        rows = store.where("extensions", lease_id=qs("lease_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.extension, limit, offset)

    @app.get("/staging/extensions/<extension_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "ListingAgent")
    def read_extension(extension_id):
        return ok(S.extension(path_row("extensions", extension_id)), 200)

    @app.post("/staging/extensions/<extension_id>/adjudicate")
    @endpoint("WarehouseManager")
    def adjudicate_extension(extension_id):
        extension = path_row("extensions", extension_id)
        payload = body()
        require(payload, ["decision"])
        enums(payload, {"decision": C.EXT_DECISIONS})
        lease = store.get("leases", extension["lease_id"])
        project = store.get("projects", lease["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if extension["state"] != "REQUESTED":
            raise ApiError("ERR_EXTENSION_INVALID_STATE")
        if payload["decision"] == "DENY":
            extension["state"] = "DENIED"
            extension["granted_cycles"] = 0
            store.touch(extension)
            return ok(S.extension(extension), 200)

        deployed = [l for l in lookup.project_lines(project) if l["state"] == "DEPLOYED"]
        requested = int(extension["requested_cycles"])
        surviving = [l for l in deployed if calc.line_survives(l, lease, requested)]
        returned = [l for l in deployed if l not in surviving]
        extension["granted_cycles"] = requested
        if not returned:
            extension["state"] = "APPROVED_FULL"
            extension["extended_line_count"] = len(deployed)
            extension["returned_line_count"] = 0
            extension["extension_charge"] = calc.extension_charge(deployed, requested)
            extension["swap_credit"] = money(0)
        else:
            extension["state"] = "APPROVED_PARTIAL"
            extension["extended_line_count"] = len(surviving)
            extension["returned_line_count"] = len(returned)
            extension["extension_charge"] = calc.extension_charge(surviving, requested)
            extension["swap_credit"] = calc.partial_extension_swap_credit(returned)
        extension["_returned_line_ids"] = [l["id"] for l in returned]
        store.touch(extension)
        return ok(S.extension(extension), 200)

    @app.post("/staging/extensions/<extension_id>/apply")
    @endpoint("StagingCoordinator")
    def apply_extension(extension_id):
        extension = path_row("extensions", extension_id)
        lease = store.get("leases", extension["lease_id"])
        project = store.get("projects", lease["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if extension["state"] not in ("APPROVED_FULL", "APPROVED_PARTIAL"):
            raise ApiError("ERR_EXTENSION_INVALID_STATE")               # rung 27
        if lease["state"] not in ("ACTIVE", "EXTENDED", "ENDING"):
            raise ApiError("ERR_LEASE_INVALID_STATE")
        granted = int(extension["granted_cycles"])
        if int(lease["extension_cycles"]) + granted > C.MAX_EXTENSION_CYCLES_TOTAL:
            raise ApiError("ERR_EXTENSION_LIMIT_REACHED")               # rung 46

        for line_id in extension.get("_returned_line_ids", []):
            line = store.get("pull_lines", line_id)
            if line is None or line["state"] != "DEPLOYED":
                continue
            line["state"] = "SWAPPED"
            store.touch(line)
            item = store.get("items", line.get("inventory_item_id"))
            if item is not None and item["status"] == "DEPLOYED":
                item["status"] = "AVAILABLE"
                store.touch(item)

        extension["state"] = "APPLIED"
        store.touch(extension)

        lease["state"] = "EXTENDED"
        lease["extension_cycles"] = int(lease["extension_cycles"]) + granted
        lease["billed_cycles"] = int(lease["initial_cycles"]) + int(lease["extension_cycles"])
        lease["end_date"] = calc.lease_end_date(lease)
        calc.derive_pickup_window(lease)
        lease["monthly_rent"] = calc.lease_monthly_rent(lease)
        store.touch(lease)
        lease["state"] = "ACTIVE"                     # the automatic system return
        calc.derive_pickup_window(lease)
        store.touch(lease)

        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.extension(extension), 200)
