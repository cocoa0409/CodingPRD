"""Pickups, damage assessments and photography."""
import calc
import cascades
import consts as C
import lookup
import serializers as S
import store
from envelope import ok, paginate, pagination, qs, qs_bool
from errors import ApiError
from gates import (body, endpoint, enums, fks, occ, path_row, require,
                   rung14_project_closed, rung15_listing_terminated, rung16_listing_closed,
                   rung34_not_too_early, rung71_fiscal_hold, types)
from store import D, add_minutes, money


def _property_shoots(prop_id):
    out = []
    for shoot in store.all_rows("shoots"):
        project = store.get("projects", shoot["project_id"])
        if project is not None and project["property_id"] == prop_id:
            out.append(shoot)
    return out


def register(app):
    # ------------------------------------------------------------------
    # Pickup
    # ------------------------------------------------------------------
    @app.post("/staging/projects/<project_id>/pickups")
    @endpoint("StagingCoordinator")
    def schedule_pickup(project_id):
        project = path_row("projects", project_id)
        payload = body()
        require(payload, ["lease_id", "scheduled_at"])
        types(payload, {"lease_id": ("str",), "scheduled_at": ("dt",)})
        fks(payload, {"lease_id": "leases"})
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        if project["pipeline"] != "VACANT_STAGING":
            raise ApiError("ERR_PIPELINE_MISMATCH")                     # rung 20
        lease = store.get("leases", payload["lease_id"])
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        start = lease.get("pickup_window_start")
        end = lease.get("pickup_window_end")
        if start is None or end is None or scheduled_at < start or scheduled_at > end:
            raise ApiError("ERR_PICKUP_OUTSIDE_WINDOW")                 # rung 60
        row = store.new_row("pickups", {
            "project_id": project["id"],
            "lease_id": lease["id"],
            "scheduled_at": scheduled_at,
            "state": "SCHEDULED",
            "attempt_count": 0,
            "completed_at": None,
            "assessed_line_count": 0,
            "damage_total": money(0),
        })
        return ok(S.pickup(row), 201)

    @app.get("/staging/pickups")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk")
    def list_pickups():
        limit, offset = pagination()
        rows = store.where("pickups", project_id=qs("project_id"), lease_id=qs("lease_id"),
                           state=qs("state"))
        return paginate(store.sort_default(rows), S.pickup, limit, offset)

    @app.get("/staging/pickups/<pickup_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk")
    def read_pickup(pickup_id):
        return ok(S.pickup(path_row("pickups", pickup_id)), 200)

    @app.post("/staging/pickups/<pickup_id>/start")
    @endpoint("StagingCoordinator")
    def start_pickup(pickup_id):
        pickup = path_row("pickups", pickup_id)
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if pickup["state"] != "SCHEDULED":
            raise ApiError("ERR_PICKUP_INVALID_STATE")
        rung34_not_too_early(pickup["scheduled_at"])
        pickup["state"] = "IN_PROGRESS"
        store.touch(pickup)
        if project.get("destage_started_at") is None:
            project["destage_started_at"] = store.now()
        return ok(S.pickup(pickup), 200)

    @app.post("/staging/pickups/<pickup_id>/complete")
    @endpoint("StagingCoordinator")
    def complete_pickup(pickup_id):
        pickup = path_row("pickups", pickup_id)
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if pickup["state"] != "IN_PROGRESS":
            raise ApiError("ERR_PICKUP_INVALID_STATE")                  # rung 28
        for assessment in lookup.pickup_assessments(pickup):            # rung 29
            if assessment["state"] != "FINAL":
                raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
        cascades.pickup_complete(pickup, project)
        return ok(S.pickup(pickup), 200)

    def _pickup_failure(pickup_id, target):
        pickup = path_row("pickups", pickup_id)
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if pickup["state"] != "SCHEDULED":
            raise ApiError("ERR_PICKUP_INVALID_STATE")
        rung34_not_too_early(pickup["scheduled_at"])
        pickup["state"] = target
        pickup["attempt_count"] = int(pickup["attempt_count"]) + 1
        store.touch(pickup)
        return ok(S.pickup(pickup), 200)

    @app.post("/staging/pickups/<pickup_id>/no-access")
    @endpoint("StagingCoordinator")
    def no_access_pickup(pickup_id):
        return _pickup_failure(pickup_id, "NO_ACCESS")

    @app.post("/staging/pickups/<pickup_id>/refuse")
    @endpoint("StagingCoordinator")
    def refuse_pickup(pickup_id):
        return _pickup_failure(pickup_id, "REFUSED")

    @app.post("/staging/pickups/<pickup_id>/reschedule")
    @endpoint("StagingCoordinator")
    def reschedule_pickup(pickup_id):
        pickup = path_row("pickups", pickup_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",)})
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if pickup["state"] not in ("NO_ACCESS", "REFUSED"):
            raise ApiError("ERR_PICKUP_INVALID_STATE")                  # rung 28
        if int(pickup["attempt_count"]) >= C.MAX_PICKUP_REATTEMPTS:     # rung 58
            raise ApiError("ERR_PICKUP_ATTEMPT_LIMIT")
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        lease = store.get("leases", pickup["lease_id"])
        start = lease.get("pickup_window_start") if lease else None
        end = lease.get("pickup_window_end") if lease else None
        if start is None or end is None or scheduled_at < start or scheduled_at > end:
            raise ApiError("ERR_PICKUP_OUTSIDE_WINDOW")                 # rung 60
        pickup["state"] = "SCHEDULED"
        pickup["scheduled_at"] = scheduled_at
        store.touch(pickup)
        return ok(S.pickup(pickup), 200)

    # ------------------------------------------------------------------
    # DamageAssessment
    # ------------------------------------------------------------------
    @app.post("/staging/pickups/<pickup_id>/damage-assessments")
    @endpoint("WarehouseManager")
    def raise_assessment(pickup_id):
        pickup = path_row("pickups", pickup_id)
        payload = body()
        require(payload, ["pull_line_id", "condition_at_pickup"])
        enums(payload, {"condition_at_pickup": C.CONDITIONS})
        types(payload, {"pull_line_id": ("str",),
                        "repair_cost_estimate": ("num", 0, None)})
        fks(payload, {"pull_line_id": "pull_lines"})
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if pickup["state"] != "IN_PROGRESS":
            raise ApiError("ERR_PICKUP_INVALID_STATE")                  # rung 28
        for existing in lookup.pickup_assessments(pickup):
            if existing["pull_line_id"] == payload["pull_line_id"]:
                raise ApiError("ERR_INVALID_REQUEST",
                               "pull_line_id must be unique per pickup.")
        row = store.new_row("assessments", {
            "pickup_id": pickup["id"],
            "pull_line_id": payload["pull_line_id"],
            "condition_at_pickup": payload["condition_at_pickup"],
            "repair_cost_estimate": money(payload.get("repair_cost_estimate", 0)),
            "state": "DRAFT",
            "depreciated_replacement_value": money(0),
            "charge_amount": money(0),
            "disposition": "NO_CHARGE",
            "appeal_count": 0,
        })
        return ok(S.assessment(row), 201)

    @app.get("/staging/damage-assessments")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "BillingClerk",
              "ListingAgent", "Seller")
    def list_assessments():
        limit, offset = pagination()
        rows = store.where("assessments", pickup_id=qs("pickup_id"),
                           pull_line_id=qs("pull_line_id"), state=qs("state"),
                           disposition=qs("disposition"))
        return paginate(store.sort_default(rows), S.assessment, limit, offset)

    @app.get("/staging/damage-assessments/<assessment_id>")
    @endpoint("PlatformAdmin", "WarehouseManager", "StagingCoordinator", "BillingClerk",
              "ListingAgent", "Seller")
    def read_assessment(assessment_id):
        return ok(S.assessment(path_row("assessments", assessment_id)), 200)

    def _price(assessment):
        line = store.get("pull_lines", assessment["pull_line_id"])
        drv = calc.depreciated_replacement_value(line)
        assessment["depreciated_replacement_value"] = drv
        charge, disposition = calc.damage_charge(assessment, drv)
        assessment["charge_amount"] = charge
        assessment["disposition"] = disposition

    @app.post("/staging/damage-assessments/<assessment_id>/assess")
    @endpoint("WarehouseManager")
    def assess(assessment_id):
        assessment = path_row("assessments", assessment_id)
        pickup = store.get("pickups", assessment["pickup_id"])
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if assessment["state"] not in ("DRAFT", "REVISED"):
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
        if assessment["state"] == "DRAFT" and pickup["state"] != "IN_PROGRESS":
            raise ApiError("ERR_PICKUP_INVALID_STATE")
        assessment["state"] = "ASSESSED"
        _price(assessment)
        store.touch(assessment)
        return ok(S.assessment(assessment), 200)

    @app.post("/staging/damage-assessments/<assessment_id>/dispute")
    @endpoint("ListingAgent", "Seller")
    def dispute(assessment_id):
        assessment = path_row("assessments", assessment_id)
        payload = body()
        require(payload, [])
        types(payload, {"dispute_note": ("str",)})
        pickup = store.get("pickups", assessment["pickup_id"])
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if assessment["state"] != "ASSESSED":
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE")              # rung 29
        if int(assessment["appeal_count"]) >= C.MAX_DAMAGE_APPEALS:     # rung 59
            raise ApiError("ERR_APPEAL_LIMIT_REACHED")
        assessment["state"] = "DISPUTED"
        assessment["appeal_count"] = int(assessment["appeal_count"]) + 1
        assessment["dispute_note"] = payload.get("dispute_note")
        store.touch(assessment)
        return ok(S.assessment(assessment), 200)

    @app.post("/staging/damage-assessments/<assessment_id>/adjudicate")
    @endpoint("PlatformAdmin")
    def adjudicate_damage(assessment_id):
        assessment = path_row("assessments", assessment_id)
        payload = body()
        require(payload, ["decision"])
        enums(payload, {"decision": C.DAMAGE_DECISIONS})
        types(payload, {"revised_repair_cost": ("num", 0, None)})
        if assessment["state"] != "DISPUTED":
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
        if payload["decision"] == "UPHOLD":
            assessment["state"] = "UPHELD"
        else:
            assessment["state"] = "REVISED"
            if payload.get("revised_repair_cost") is not None:
                assessment["repair_cost_estimate"] = money(payload["revised_repair_cost"])
            _price(assessment)
        store.touch(assessment)
        return ok(S.assessment(assessment), 200)

    @app.post("/staging/damage-assessments/<assessment_id>/finalize")
    @endpoint("WarehouseManager")
    def finalize(assessment_id):
        assessment = path_row("assessments", assessment_id)
        payload = body()
        require(payload, ["expected_pickup_version"])
        types(payload, {"expected_pickup_version": ("int", 0, None)})
        pickup = store.get("pickups", assessment["pickup_id"])
        project = store.get("projects", pickup["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if assessment["state"] not in ("ASSESSED", "UPHELD"):
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE")              # rung 29
        occ(payload, "expected_pickup_version", pickup, "ERR_STALE_PICKUP_VERSION")
        assessment["state"] = "FINAL"
        store.touch(assessment)
        pickup["damage_total"] = money(D(pickup["damage_total"])
                                       + D(assessment["charge_amount"]))
        pickup["assessed_line_count"] = int(pickup["assessed_line_count"]) + 1
        store.touch(pickup)
        line = store.get("pull_lines", assessment["pull_line_id"])
        item = store.get("items", line.get("inventory_item_id")) if line else None
        if assessment["disposition"] == "REPAIR":
            if item is not None and item["status"] == "DEPLOYED":
                item["status"] = "IN_REPAIR"
                grade = item.get("condition_grade")
                item["condition_grade"] = {"A": "B", "B": "C", "C": "C"}.get(grade, grade)
                store.touch(item)
        elif assessment["disposition"] == "REPLACE":
            if item is not None and item["status"] == "DEPLOYED":
                item["status"] = "WRITTEN_OFF"
                store.touch(item)
            if line is not None and line["state"] == "DEPLOYED":
                line["state"] = "RETURNED"
                store.touch(line)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.assessment(assessment), 200)

    # ------------------------------------------------------------------
    # PhotoShoot
    # ------------------------------------------------------------------
    def _shoot_temporal(project, instant):
        if project["pipeline"] == "VACANT_STAGING":
            install = lookup.complete_install(project)                  # rung 48
            if install is None or instant < install["completed_at"]:
                raise ApiError("ERR_SHOOT_BEFORE_INSTALL")
        destage = project.get("destage_started_at")                     # rung 50
        if destage is not None and instant >= destage:
            raise ApiError("ERR_SHOOT_AFTER_DESTAGE")

    @app.post("/staging/projects/<project_id>/photo-shoots")
    @endpoint("StagingCoordinator")
    def schedule_shoot(project_id):
        project = path_row("projects", project_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",), "is_reshoot": ("bool",)})
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        rung16_listing_closed(listing)
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        _shoot_temporal(project, scheduled_at)
        block_end = add_minutes(scheduled_at, C.SHOOT_BLOCK_MINUTES)    # rung 62
        for other in _property_shoots(project["property_id"]):
            if other["state"] not in ("SCHEDULED", "COMPLETED"):
                continue
            other_end = add_minutes(other["scheduled_at"],
                                    C.SHOOT_BLOCK_MINUTES + C.SHOOT_BUFFER_MINUTES)
            if scheduled_at < other_end and other["scheduled_at"] < block_end:
                raise ApiError("ERR_SHOOT_TIME_CONFLICT")
        rung71_fiscal_hold(project)                                     # rung 71
        is_reshoot = bool(payload.get("is_reshoot", False))
        index = None
        if not is_reshoot:
            index = len([s for s in lookup.project_shoots(project)
                         if not s.get("is_reshoot")]) + 1
        row = store.new_row("shoots", {
            "project_id": project["id"],
            "scheduled_at": scheduled_at,
            "is_reshoot": is_reshoot,
            "session_index": index,
            "state": "SCHEDULED",
            "overage_fee": money(0),
            "mls_delivery_gated": calc.mls_delivery_gate(project),
            "delivered_at": None,
        })
        return ok(S.shoot(row), 201)

    @app.get("/staging/photo-shoots")
    @endpoint("PlatformAdmin", "StagingCoordinator", "ListingAgent", "Seller", "BillingClerk")
    def list_shoots():
        limit, offset = pagination()
        rows = store.where("shoots", project_id=qs("project_id"), state=qs("state"))
        is_reshoot = qs_bool("is_reshoot")
        if is_reshoot is not None:
            rows = [r for r in rows if bool(r.get("is_reshoot")) == is_reshoot]
        return paginate(store.sort_default(rows), S.shoot, limit, offset)

    @app.get("/staging/photo-shoots/<shoot_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "ListingAgent", "Seller", "BillingClerk")
    def read_shoot(shoot_id):
        return ok(S.shoot(path_row("shoots", shoot_id)), 200)

    @app.post("/staging/photo-shoots/<shoot_id>/complete")
    @endpoint("StagingCoordinator")
    def complete_shoot(shoot_id):
        shoot = path_row("shoots", shoot_id)
        project = store.get("projects", shoot["project_id"])
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        if shoot["state"] != "SCHEDULED":
            raise ApiError("ERR_SHOOT_INVALID_STATE")                   # rung 30
        rung34_not_too_early(shoot["scheduled_at"])                     # rung 34
        if project["pipeline"] == "VACANT_STAGING":
            install = lookup.complete_install(project)                  # rung 48
            if install is None or shoot["scheduled_at"] < install["completed_at"]:
                raise ApiError("ERR_SHOOT_BEFORE_INSTALL")
        else:
            if not any(v["state"] == "COMPLETED" for v in lookup.project_visits(project)):
                raise ApiError("ERR_VISIT_NOT_COMPLETED")               # rung 49
        destage = project.get("destage_started_at")                     # rung 50
        if destage is not None and shoot["scheduled_at"] >= destage:
            raise ApiError("ERR_SHOOT_AFTER_DESTAGE")
        shoot["state"] = "COMPLETED"
        shoot["overage_fee"] = calc.photo_overage_fee(shoot, lookup.tier_of(project))
        store.touch(shoot)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.shoot(shoot), 200)

    @app.post("/staging/photo-shoots/<shoot_id>/deliver")
    @endpoint("StagingCoordinator")
    def deliver_shoot(shoot_id):
        shoot = path_row("shoots", shoot_id)
        project = store.get("projects", shoot["project_id"])
        if shoot["state"] != "COMPLETED":
            raise ApiError("ERR_SHOOT_INVALID_STATE")                   # rung 30
        if calc.mls_delivery_gate(project):                             # rung 72
            invoice = lookup.project_invoice(project)
            if invoice is None or invoice["state"] != "PAID":
                raise ApiError("ERR_MLS_DELIVERY_PAYMENT_GATE")
        shoot["state"] = "DELIVERED"
        shoot["delivered_at"] = store.now()
        store.touch(shoot)
        return ok(S.shoot(shoot), 200)

    @app.post("/staging/photo-shoots/<shoot_id>/cancel")
    @endpoint("StagingCoordinator")
    def cancel_shoot(shoot_id):
        shoot = path_row("shoots", shoot_id)
        if shoot["state"] != "SCHEDULED":
            raise ApiError("ERR_SHOOT_INVALID_STATE")
        shoot["state"] = "CANCELLED"
        store.touch(shoot)
        return ok(S.shoot(shoot), 200)

    @app.post("/staging/photo-shoots/<shoot_id>/request-reshoot")
    @endpoint("ListingAgent", "Seller")
    def request_reshoot(shoot_id):
        shoot = path_row("shoots", shoot_id)
        payload = body()
        require(payload, ["scheduled_at"])
        types(payload, {"scheduled_at": ("dt",)})
        project = store.get("projects", shoot["project_id"])
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if shoot["state"] not in ("COMPLETED", "DELIVERED"):
            raise ApiError("ERR_SHOOT_INVALID_STATE")                   # rung 30
        if calc.reshoot_credits_remaining(project) < 1:                 # rung 51
            raise ApiError("ERR_RESHOOT_ENTITLEMENT_EXHAUSTED")
        rung71_fiscal_hold(project)                                     # rung 71
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        shoot["state"] = "RESHOOT_REQUESTED"
        store.touch(shoot)
        row = store.new_row("shoots", {
            "project_id": project["id"],
            "scheduled_at": scheduled_at,
            "is_reshoot": True,
            "session_index": None,
            "state": "SCHEDULED",
            "overage_fee": money(0),
            "mls_delivery_gated": calc.mls_delivery_gate(project),
            "delivered_at": None,
        })
        return ok(S.shoot(row), 201)
