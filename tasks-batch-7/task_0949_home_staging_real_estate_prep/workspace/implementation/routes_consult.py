"""Consultations, scope items and projects."""
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
                   rung11_property_owner, rung12_project_party, rung14_project_closed,
                   rung15_listing_terminated, rung17_consultation_cancelled,
                   rung34_not_too_early, rung71_fiscal_hold, types)
from store import D, money


def _recount_consultation(consultation):
    items = lookup.consultation_scope_items(consultation)
    consultation["scoped_room_count"] = len([i for i in items if i["action"] != "ACCESSORY_ONLY"])
    consultation["rental_line_count"] = len([i for i in items if i.get("requires_rental")])


def register(app):
    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------
    @app.post("/staging/consultations")
    @endpoint("StagingCoordinator", "ListingAgent", "Seller")
    def create_consultation():
        payload = body()
        require(payload, ["property_id", "requested_by_client_id", "scheduled_at"])
        types(payload, {"property_id": ("str",), "requested_by_client_id": ("str",),
                        "scheduled_at": ("dt",)})
        fks(payload, {"property_id": "properties", "requested_by_client_id": "clients"})
        scheduled_at = store.parse_dt(payload["scheduled_at"])
        if scheduled_at < store.now():
            raise ApiError("ERR_INVALID_REQUEST",
                           "scheduled_at must be at or after the logical clock.")
        prop = store.get("properties", payload["property_id"])
        rung11_property_owner(prop)
        if prop["prep_state"] != "NEW" or lookup.live_consultations(prop):
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        row = store.new_row("consultations", {
            "property_id": prop["id"],
            "requested_by_client_id": payload["requested_by_client_id"],
            "scheduled_at": scheduled_at,
            "held_at": None,
            "pipeline": None,
            "state": "SCHEDULED",
            "revision_count": 0,
            "recommended_tier_code": None,
            "estimated_hours": D(0),
            "scoped_room_count": 0,
            "rental_line_count": 0,
        })
        cascades.property_hop(prop, "NEW", "CONSULT_BOOKED")
        return ok(S.consultation(row), 201)

    @app.get("/staging/consultations")
    @endpoint("PlatformAdmin", "StagingCoordinator", "ListingAgent", "Seller", "BillingClerk")
    def list_consultations():
        limit, offset = pagination()
        rows = store.where("consultations", property_id=qs("property_id"),
                           requested_by_client_id=qs("requested_by_client_id"),
                           state=qs("state"), pipeline=qs("pipeline"))
        return paginate(store.sort_default(rows), S.consultation, limit, offset)

    @app.get("/staging/consultations/<consultation_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "ListingAgent", "Seller", "BillingClerk")
    def read_consultation(consultation_id):
        return ok(S.consultation(path_row("consultations", consultation_id)), 200)

    @app.post("/staging/consultations/<consultation_id>/hold")
    @endpoint("StagingCoordinator")
    def hold_consultation(consultation_id):
        row = path_row("consultations", consultation_id)
        rung17_consultation_cancelled(row)
        if row["state"] != "SCHEDULED":
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        rung34_not_too_early(row["scheduled_at"])
        prop = store.get("properties", row["property_id"])
        row["state"] = "HELD"
        row["held_at"] = store.now()
        row["pipeline"] = ("OCCUPIED_PREP" if prop["occupancy"] == "OCCUPIED"
                           else "VACANT_STAGING")
        store.touch(row)
        return ok(S.consultation(row), 200)

    @app.post("/staging/consultations/<consultation_id>/scope-items")
    @endpoint("StagingCoordinator")
    def add_scope_item(consultation_id):
        consultation = path_row("consultations", consultation_id)
        payload = body()
        require(payload, ["room_label", "action"])
        enums(payload, {"action": C.SCOPE_ACTIONS})
        types(payload, {"room_label": ("str",), "estimated_hours": ("num", 0, None),
                        "requires_rental": ("bool",),
                        "accessory_set_count": ("int", 0, None)})
        rung17_consultation_cancelled(consultation)
        if consultation["state"] not in ("HELD", "SCOPE_DRAFTED", "SCOPE_REJECTED"):
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        pipeline = consultation.get("pipeline")
        action = payload["action"]
        if pipeline == "OCCUPIED_PREP" and action in C.VACANT_ONLY_ACTIONS:
            raise ApiError("ERR_PIPELINE_MISMATCH")
        if pipeline == "VACANT_STAGING" and action in C.OCCUPIED_ONLY_ACTIONS:
            raise ApiError("ERR_PIPELINE_MISMATCH")
        requires_rental = bool(payload.get("requires_rental", False))
        if pipeline == "OCCUPIED_PREP" and requires_rental:
            raise ApiError("ERR_INVALID_REQUEST",
                           "requires_rental must be false on an OCCUPIED_PREP consultation.")
        existing = lookup.consultation_scope_items(consultation)
        if any(i["room_label"] == payload["room_label"] for i in existing):
            raise ApiError("ERR_INVALID_REQUEST", "room_label must be unique per consultation.")
        row = store.new_row("scope_items", {
            "consultation_id": consultation["id"],
            "room_label": payload["room_label"],
            "action": action,
            "estimated_hours": D(payload.get("estimated_hours", 0)),
            "requires_rental": requires_rental,
            "accessory_set_count": int(payload.get("accessory_set_count", 0)),
            "sequence_index": len(existing) + 1,
        })
        if consultation["state"] == "SCOPE_REJECTED":
            consultation["revision_count"] = int(consultation["revision_count"]) + 1
        consultation["state"] = "SCOPE_DRAFTED"
        _recount_consultation(consultation)
        store.touch(consultation)
        return ok(S.scope_item(row), 201)

    @app.get("/staging/scope-items")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "ListingAgent", "Seller")
    def list_scope_items():
        limit, offset = pagination()
        rows = store.where("scope_items", consultation_id=qs("consultation_id"),
                           action=qs("action"), room_label=qs("room_label"))
        return paginate(store.sort_default(rows), S.scope_item, limit, offset)

    @app.get("/staging/scope-items/<scope_item_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "ListingAgent", "Seller")
    def read_scope_item(scope_item_id):
        return ok(S.scope_item(path_row("scope_items", scope_item_id)), 200)

    @app.post("/staging/consultations/<consultation_id>/submit-scope")
    @endpoint("StagingCoordinator")
    def submit_scope(consultation_id):
        consultation = path_row("consultations", consultation_id)
        payload = body()
        require(payload, ["recommended_tier_code"])
        enums(payload, {"recommended_tier_code": C.TIER_CODES})
        types(payload, {"estimated_hours": ("num", 0, None)})
        rung17_consultation_cancelled(consultation)
        if consultation["state"] != "SCOPE_DRAFTED":
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        if int(consultation["scoped_room_count"]) < 1:
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        consultation["state"] = "SCOPE_SUBMITTED"
        consultation["recommended_tier_code"] = payload["recommended_tier_code"]
        if payload.get("estimated_hours") is not None:
            consultation["estimated_hours"] = D(payload["estimated_hours"])
        store.touch(consultation)
        return ok(S.consultation(consultation), 200)

    def _scope_party(consultation):
        prop = store.get("properties", consultation["property_id"])
        if gates.role() == "ListingAgent":
            listings = lookup.property_listings(prop)
            if not any(l["listing_agent_client_id"] == gates.actor() for l in listings):
                raise ApiError("ERR_NOT_LISTING_AGENT")
        rung11_property_owner(prop)

    @app.post("/staging/consultations/<consultation_id>/approve-scope")
    @endpoint("ListingAgent", "Seller")
    def approve_scope(consultation_id):
        consultation = path_row("consultations", consultation_id)
        _scope_party(consultation)
        rung17_consultation_cancelled(consultation)
        if consultation["state"] != "SCOPE_SUBMITTED":
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        consultation["state"] = "SCOPE_APPROVED"
        store.touch(consultation)
        cascades.property_hop(store.get("properties", consultation["property_id"]),
                              "CONSULT_BOOKED", "SCOPED")
        return ok(S.consultation(consultation), 200)

    @app.post("/staging/consultations/<consultation_id>/reject-scope")
    @endpoint("ListingAgent", "Seller")
    def reject_scope(consultation_id):
        consultation = path_row("consultations", consultation_id)
        payload = body()
        require(payload, [])
        types(payload, {"rejection_note": ("str",)})
        _scope_party(consultation)
        rung17_consultation_cancelled(consultation)
        if consultation["state"] != "SCOPE_SUBMITTED":
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        consultation["state"] = "SCOPE_REJECTED"
        consultation["rejection_note"] = payload.get("rejection_note")
        store.touch(consultation)
        return ok(S.consultation(consultation), 200)

    @app.post("/staging/consultations/<consultation_id>/cancel")
    @endpoint("StagingCoordinator", "PlatformAdmin")
    def cancel_consultation(consultation_id):
        consultation = path_row("consultations", consultation_id)
        if consultation["state"] not in ("SCHEDULED", "HELD", "SCOPE_DRAFTED", "SCOPE_REJECTED"):
            raise ApiError("ERR_CONSULTATION_INVALID_STATE")
        consultation["state"] = "CANCELLED"
        store.touch(consultation)
        prop = store.get("properties", consultation["property_id"])
        if not lookup.live_consultations(prop, exclude_id=consultation["id"]):
            if prop["prep_state"] != "NEW":
                prop["prep_state"] = "NEW"
                store.touch(prop)
        return ok(S.consultation(consultation), 200)

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------
    @app.post("/staging/projects")
    @endpoint("StagingCoordinator")
    def create_project():
        payload = body()
        require(payload, ["property_id", "consultation_id", "listing_id", "package_tier_id",
                          "payer_client_id", "payer_type"])
        if payload.get("payer_type") == "BROKERAGE":
            require(payload, ["brokerage_id"])
        enums(payload, {"payer_type": C.PAYER_TYPES})
        types(payload, {"property_id": ("str",), "consultation_id": ("str",),
                        "listing_id": ("str",), "package_tier_id": ("str",),
                        "payer_client_id": ("str",), "brokerage_id": ("str",),
                        "payer_split_agent_pct": ("num_ex", 0, 1)})
        fks(payload, {"property_id": "properties", "consultation_id": "consultations",
                      "listing_id": "listings", "package_tier_id": "tiers",
                      "payer_client_id": "clients", "brokerage_id": "brokerages"})
        consultation = store.get("consultations", payload["consultation_id"])
        rung17_consultation_cancelled(consultation)
        if consultation["state"] != "SCOPE_APPROVED":
            raise ApiError("ERR_SCOPE_NOT_APPROVED")
        prop = store.get("properties", payload["property_id"])
        for other in store.where("projects", property_id=prop["id"]):
            if other["workflow_state"] != "CLOSED":
                raise ApiError("ERR_DUPLICATE_ACTIVE_PROJECT")

        items = lookup.consultation_scope_items(consultation)
        row = store.new_row("projects", {
            "property_id": prop["id"],
            "consultation_id": consultation["id"],
            "listing_id": payload["listing_id"],
            "package_tier_id": payload["package_tier_id"],
            "payer_client_id": payload["payer_client_id"],
            "brokerage_id": payload.get("brokerage_id"),
            "authorized_by_client_id": None,
            "pipeline": consultation["pipeline"],
            "payer_type": payload["payer_type"],
            "payer_split_agent_pct": D(payload.get("payer_split_agent_pct", "0.50")),
            "workflow_state": "DRAFT",
            "payment_state": "UNBILLED",
            "room_count": len([i for i in items if i["action"] != "ACCESSORY_ONLY"]),
            "accessory_set_count": sum(int(i["accessory_set_count"]) for i in items),
            "authorized_amount": None,
            "authorized_at": None,
            "destage_eligible": False,
            "service_window_end_date": None,
            "window_extension_count": 0,
            "restage_count": 0,
            "fiscal_hold": False,
            "package_adjustments": money(0),
            "closing_escalation_booked": money(0),
            "destage_started_at": None,
        })
        row["contract_value"] = calc.contract_value(row)
        return ok(S.project(row), 201)

    @app.get("/staging/projects")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller", "BrokerageAdmin")
    def list_projects():
        limit, offset = pagination()
        rows = store.where("projects", property_id=qs("property_id"),
                           consultation_id=qs("consultation_id"), listing_id=qs("listing_id"),
                           package_tier_id=qs("package_tier_id"),
                           payer_client_id=qs("payer_client_id"),
                           brokerage_id=qs("brokerage_id"),
                           authorized_by_client_id=qs("authorized_by_client_id"),
                           pipeline=qs("pipeline"), workflow_state=qs("workflow_state"),
                           payment_state=qs("payment_state"))
        return paginate(store.sort_default(rows), S.project, limit, offset)

    @app.get("/staging/projects/<project_id>")
    @endpoint("PlatformAdmin", "StagingCoordinator", "WarehouseManager", "BillingClerk",
              "ListingAgent", "Seller", "BrokerageAdmin")
    def read_project(project_id):
        return ok(S.project(path_row("projects", project_id)), 200)

    @app.post("/staging/projects/<project_id>/authorize")
    @endpoint("ListingAgent", "Seller", "BrokerageAdmin")
    def authorize_project(project_id):
        project = path_row("projects", project_id)
        listing = lookup.listing_of(project)
        prop = lookup.property_of(project)
        rung10_listing_agent(listing)
        rung11_property_owner(prop)
        rung12_project_party(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if project["workflow_state"] != "DRAFT":
            raise ApiError("ERR_PROJECT_INVALID_STATE")
        consultation = lookup.consultation_of(project)
        if consultation is None or consultation["state"] != "SCOPE_APPROVED":
            raise ApiError("ERR_SCOPE_NOT_APPROVED")

        payer = store.get("clients", project["payer_client_id"])
        contract_value = D(project["contract_value"])
        if gates.role() == "BrokerageAdmin":
            acting_cap = C.BROKERAGE_AUTHORIZATION_HARD_CAP
        else:
            acting = store.get("clients", gates.actor())
            acting_cap = (D(acting["effective_authorization_cap"]) if acting is not None
                          else D(0))
        headroom = acting_cap - contract_value
        consent = bool(payer.get("consent_on_file")) if payer is not None else False
        payer_is_seller = payer is not None and payer["client_type"] == "SELLER"
        # Rung 39 is the residual cap refusal. "Negative headroom is authorized only
        # when the payer client carries consent_on_file true; otherwise it is refused
        # with ERR_AUTHORIZATION_CAP_EXCEEDED" -- but the two neighbouring sentences
        # take their cases away from it. A seller payer keeps the consent question
        # alive, and that case is "separately refused with ERR_SELLER_CONSENT_REQUIRED"
        # at rung 41; and a contract above the platform ceiling belongs to rung 40,
        # which fires "regardless of who authorizes and regardless of whether seller
        # consent is on file". Rung 39 therefore answers only when neither the seller
        # consent path nor the platform ceiling owns the refusal -- which is exactly
        # the arithmetic that keeps rungs 40 and 41 reachable at all.
        over_platform_ceiling = contract_value > C.BROKERAGE_AUTHORIZATION_HARD_CAP
        if (headroom < 0 and not consent and not payer_is_seller
                and not over_platform_ceiling):
            raise ApiError("ERR_AUTHORIZATION_CAP_EXCEEDED")            # rung 39
        if over_platform_ceiling:
            raise ApiError("ERR_BROKERAGE_CAP_EXCEEDED")                # rung 40
        if gates.role() == "ListingAgent" and headroom < 0:
            if not payer_is_seller or not consent:
                raise ApiError("ERR_SELLER_CONSENT_REQUIRED")           # rung 41

        project["workflow_state"] = "AUTHORIZED"
        project["authorized_by_client_id"] = gates.actor()
        project["authorized_amount"] = money(contract_value)
        project["authorized_at"] = store.now()
        if project["pipeline"] == "OCCUPIED_PREP":
            project["service_window_end_date"] = calc.service_window_end_date(project)
        store.touch(project)
        # "Deposit money is conserved. A deposit's amount always equals the sum of
        # applied_to_damage, applied_to_holdover, applied_to_balance, refunded_amount,
        # forfeited_amount and held_remaining... The identity is observable on any single
        # deposit read." No sentence assigns held_remaining a value before collection, so
        # the residue starts as the whole amount and the REQUIRED row already balances;
        # collection's "sets held_remaining to the full amount" then re-asserts it.
        deposit_amount = calc.deposit_requirement(project)
        store.new_row("deposits", {
            "project_id": project["id"],
            "invoice_id": None,
            "amount": deposit_amount,
            "state": "REQUIRED",
            "applied_to_damage": money(0),
            "applied_to_holdover": money(0),
            "applied_to_balance": money(0),
            "refunded_amount": money(0),
            "forfeited_amount": money(0),
            "held_remaining": deposit_amount,
        })
        cascades.property_hop(prop, "SCOPED", "IN_PREP")
        return ok(S.project(project), 200)

    def _change_package(project_id, upgrade):
        project = path_row("projects", project_id)
        payload = body()
        require(payload, ["package_tier_id"])
        types(payload, {"package_tier_id": ("str",)})
        fks(payload, {"package_tier_id": "tiers"})
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        old_tier = lookup.tier_of(project)
        new_tier = store.get("tiers", payload["package_tier_id"])

        if upgrade:
            probe = dict(project)
            probe["package_tier_id"] = new_tier["id"]
            if calc.contract_value(probe, new_tier) > C.BROKERAGE_AUTHORIZATION_HARD_CAP:
                raise ApiError("ERR_BROKERAGE_CAP_EXCEEDED")            # rung 40
            if int(new_tier["tier_rank"]) <= int(old_tier["tier_rank"]):
                raise ApiError("ERR_INVALID_TIER_CHANGE")               # rung 47
            adjustment = calc.upgrade_adjustment(project, old_tier, new_tier)
            rung71_fiscal_hold(project)                                 # rung 71
        else:
            if int(new_tier["tier_rank"]) >= int(old_tier["tier_rank"]):
                raise ApiError("ERR_INVALID_TIER_CHANGE")               # rung 47
            adjustment = calc.downgrade_adjustment(project, old_tier, new_tier)

        project["package_tier_id"] = new_tier["id"]
        project["package_adjustments"] = money(D(project.get("package_adjustments") or 0)
                                               + adjustment)
        project["contract_value"] = calc.contract_value(project, new_tier)
        store.touch(project)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.project(project), 200)

    @app.post("/staging/projects/<project_id>/upgrade-package")
    @endpoint("StagingCoordinator", "ListingAgent")
    def upgrade_package(project_id):
        return _change_package(project_id, True)

    @app.post("/staging/projects/<project_id>/downgrade-package")
    @endpoint("StagingCoordinator", "ListingAgent")
    def downgrade_package(project_id):
        return _change_package(project_id, False)

    @app.post("/staging/projects/<project_id>/extend-window")
    @endpoint("StagingCoordinator", "ListingAgent")
    def extend_window(project_id):
        project = path_row("projects", project_id)
        listing = lookup.listing_of(project)
        rung14_project_closed(project)
        rung15_listing_terminated(listing)
        if project["pipeline"] != "OCCUPIED_PREP":
            raise ApiError("ERR_PIPELINE_MISMATCH")                     # rung 20
        if int(project.get("window_extension_count") or 0) >= C.MAX_OCCUPIED_WINDOW_EXTENSIONS:
            raise ApiError("ERR_WINDOW_EXTENSION_LIMIT")                # rung 64
        rung71_fiscal_hold(project)                                     # rung 71
        project["window_extension_count"] = int(project["window_extension_count"]) + 1
        project["service_window_end_date"] = calc.service_window_end_date(project)
        project["package_adjustments"] = money(D(project.get("package_adjustments") or 0)
                                               + C.OCCUPIED_WINDOW_EXTENSION_FEE)
        store.touch(project)
        invoice = lookup.project_invoice(project)
        if invoice is not None:
            calc.refresh_invoice(invoice)
        return ok(S.project(project), 200)

    @app.post("/staging/projects/<project_id>/close")
    @endpoint("StagingCoordinator", "PlatformAdmin")
    def close_project(project_id):
        project = path_row("projects", project_id)
        if project["workflow_state"] != "CLOSEOUT":
            raise ApiError("ERR_PROJECT_INVALID_STATE")
        if project["payment_state"] not in ("SETTLED", "WRITTEN_OFF"):
            raise ApiError("ERR_PROJECT_INVALID_STATE")
        for invoice in store.where("invoices", project_id=project["id"]):
            if invoice["state"] not in ("PAID", "VOID"):
                raise ApiError("ERR_PROJECT_INVALID_STATE")
        project["workflow_state"] = "CLOSED"
        store.touch(project)
        prop = lookup.property_of(project)
        cascades.property_hop(prop, "STAGED", "DESTAGED")
        cascades.property_hop(prop, "DESTAGED", "CLOSED")
        return ok(S.project(project), 200)
