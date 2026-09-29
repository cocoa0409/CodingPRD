"""Structural analyses, modification projects and cost shares."""
from decimal import Decimal

import calc
import find
import serializers
import services
from db import bump, db, new_record, order_key, sorted_records
from errors import ApiError
from middleware import (
    Body,
    auth,
    paginate,
    pagination,
    query_enum,
    query_value,
    require_tenant_scope,
    resolve_identity,
)
from response import array_response, object_response
from util import dec, rhu3

VARIANTS = ("PRELIMINARY", "DETAILED")
ANALYSIS_STATUSES = ("ISSUED", "QUOTED", "SUPERSEDED")
PROJECT_STATUSES = ("PROPOSED", "COST_ALLOCATED", "FUNDED", "STALLED",
                    "IN_CONSTRUCTION", "CERTIFIED", "CANCELLED")
SHARE_STATUSES = ("PENDING", "ACCEPTED", "DECLINED", "BILLED", "VOIDED")
ALLOCATION_BASES = ("PRO_RATA_LOAD", "EQUAL_SHARE")
WINDOW_BLOCKING_STATUSES = ("PROPOSED", "COST_ALLOCATED", "FUNDED", "IN_CONSTRUCTION")


def _pipeline_load(tower, application):
    total = Decimal(0)
    for other in services.tower_applications(tower["id"]):
        if other["id"] == application["id"]:
            continue
        if other["status"] in ("APPROVED", "MODIFICATION_REQUIRED"):
            total += dec(other["total_load_units"])
        elif other["status"] == "AMENDMENT_ISSUED":
            amendment = services.amendment_for_application(other["id"])
            if amendment is not None \
                    and amendment["execution_status"] in ("DRAFT", "PENDING_SIGNATURE"):
                total += dec(other["total_load_units"])
    return rhu3(total)


def _windows_conflict(project, start, end):
    return not (project["construction_window_end_date"].date() < start.date()
                or project["construction_window_start_date"].date() > end.date())


def _require_free_window(tower_id, start, end, exclude_project_id=None):
    for other in services.tower_projects(tower_id):
        if other["id"] == exclude_project_id:
            continue
        if other["status"] not in WINDOW_BLOCKING_STATUSES:
            continue
        if _windows_conflict(other, start, end):
            raise ApiError("ERR_CONSTRUCTION_WINDOW_CONFLICT",
                           "Another project already reserves this construction window.")


def _resolve_beneficiaries(project):
    analysis = db.analyses.get(project["originating_analysis_id"])
    entries = []
    for amendment in services.tower_amendments(project["tower_id"]):
        if amendment["execution_status"] != "EXECUTED":
            continue
        mla = db.mlas.get(amendment["master_lease_agreement_id"])
        if mla is None:
            continue
        entries.append({
            "tenant_id": mla["tenant_id"],
            "site_amendment_id": amendment["id"],
            "basis_load_units": dec(amendment["reserved_load_units"]),
            "basis_created_at": amendment["created_at"],
            "basis_seq": amendment["_seq"],
        })
    if analysis is not None:
        application = db.applications.get(analysis["colocation_application_id"])
        if application is not None and application["status"] in (
                "SUBMITTED", "UNDER_STRUCTURAL_REVIEW", "CAPACITY_HOLD",
                "MODIFICATION_REQUIRED", "APPROVED"):
            mla = db.mlas.get(application["master_lease_agreement_id"])
            if mla is not None:
                entries.append({
                    "tenant_id": mla["tenant_id"],
                    "site_amendment_id": None,
                    "basis_load_units": dec(application["total_load_units"]),
                    "basis_created_at": application["created_at"],
                    "basis_seq": application["_seq"],
                })
    for entry in entries:
        tenant = db.tenants.get(entry["tenant_id"])
        entry["tenant_created_at"] = tenant["created_at"] if tenant else None
        entry["tenant_seq"] = tenant["_seq"] if tenant else 0
    return entries


def _mint_shares(project, beneficiaries):
    costs = calc.project_total_cost(project["base_construction_cost_cents"])
    project["volume_discount_pct"] = costs["volume_discount_pct"]
    project["engineering_fee_cents"] = costs["engineering_fee_cents"]
    project["total_cost_cents"] = costs["total_cost_cents"]
    shares = calc.allocate_shares(costs["total_cost_cents"], beneficiaries,
                                  project["allocation_basis"])
    minted = []
    for entry, amount in zip(beneficiaries, shares):
        record = new_record(
            modification_project_id=project["id"],
            tenant_id=entry["tenant_id"],
            site_amendment_id=entry["site_amendment_id"],
            basis_load_units=entry["basis_load_units"],
            basis_created_at=entry["basis_created_at"],
            share_cents=amount,
            allocation_basis=project["allocation_basis"],
            status="PENDING",
            accepted_at=None,
            decline_reason=None,
        )
        db.cost_shares[record["id"]] = record
        minted.append(record)
    return minted


def register(app):

    # -----------------------------------------------------------------------
    # Structural analyses
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/structural-analyses", methods=["POST"])
    def create_analysis():
        user_id, _role = auth("StructuralEngineer")
        body = Body()
        application_id = body.ident("colocation_application_id")
        variant = body.enum("variant", VARIANTS)
        expected_version = body.integer("expected_tower_version")
        application = find.application(application_id)
        tower = find.tower(application["tower_id"])
        if expected_version != tower["version"]:
            raise ApiError("ERR_STALE_TOWER_VERSION",
                           "The tower version has moved since it was read.")
        if application["status"] != "UNDER_STRUCTURAL_REVIEW":
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "Only an application under structural review may be analysed.")
        if services.tower_capacity_posture(tower) == "FROZEN":
            raise ApiError("ERR_TOWER_POSTURE_FROZEN", "The tower posture is FROZEN.")

        base = services.tower_reserved_load_units(tower)
        subject = dec(application["total_load_units"])
        pipeline = Decimal(0) if variant == "PRELIMINARY" else _pipeline_load(tower, application)
        included = rhu3(base + subject + pipeline)
        pct = calc.loading_pct(included, tower["rated_capacity_load_units"])
        result = calc.analysis_result(pct)

        services.supersede_live_analyses(application)
        record = new_record(
            colocation_application_id=application["id"],
            variant=variant,
            base_load_units=base,
            subject_load_units=subject,
            pipeline_load_units=rhu3(pipeline),
            included_load_units=included,
            projected_loading_pct=pct,
            result=result,
            status="ISSUED",
            modification_construction_cost_cents=None,
            quoted_at=None,
            engineer_user_id=user_id,
            issued_at=db.clock,
        )
        db.analyses[record["id"]] = record

        # Service-level commitment: only the first analysis after the latest
        # review entry can fire the once-per-application latch.
        first_since_entry = not application.get("_analysis_since_entry")
        application["_analysis_since_entry"] = True
        deadline = application.get("review_deadline_at")
        if (first_since_entry and deadline is not None and record["issued_at"] > deadline
                and not application["sla_breached"]):
            application["sla_breached"] = True
            mla = db.mlas.get(application["master_lease_agreement_id"])
            tenant = db.tenants.get(mla["tenant_id"]) if mla else None
            if tenant is not None:
                credit = calc.sla_credit_cents(mla["base_monthly_rent_cents"])
                services.adjust_tenant_balance(tenant, -credit)

        if result == "MODIFICATION_REQUIRED":
            application["status"] = "MODIFICATION_REQUIRED"
        elif result == "CAPACITY_EXCEEDED":
            application["status"] = "REJECTED"
        bump(application)
        bump(tower)
        return object_response(serializers.analysis(record), 201)

    @app.route("/tower-colo/structural-analyses/<analysis_id>/quotation", methods=["POST"])
    def issue_quotation(analysis_id):
        auth("StructuralEngineer")
        body = Body()
        cost = body.integer("modification_construction_cost_cents", exclusive_min=0)
        analysis = find.analysis(analysis_id)
        if analysis["status"] != "ISSUED" or analysis["result"] == "PASS":
            raise ApiError("ERR_INVALID_ANALYSIS_STATE",
                           "A quotation is only accepted on an ISSUED analysis that "
                           "requires modification.")
        analysis["modification_construction_cost_cents"] = cost
        analysis["status"] = "QUOTED"
        analysis["quoted_at"] = db.clock
        bump(analysis)
        return object_response(serializers.analysis(analysis))

    @app.route("/tower-colo/colocation-applications/<application_id>/structural-analyses",
               methods=["GET"])
    def list_application_analyses(application_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Tenant")
        status = query_enum("status", ANALYSIS_STATUSES)
        limit, offset = pagination()
        application = find.application(application_id)
        resolve_identity(user_id, role)
        items = services.application_analyses(application["id"])
        items = sorted(items, key=order_key, reverse=True)
        if status is not None:
            items = [a for a in items if a["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.analysis(a) for a in page], meta)

    # -----------------------------------------------------------------------
    # Modification projects
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/modification-projects", methods=["POST"])
    def create_project():
        user_id, _role = auth("StructuralEngineer")
        body = Body()
        tower_id = body.ident("tower_id")
        analysis_id = body.ident("originating_analysis_id")
        window_start = body.moment("construction_window_start_date")
        window_end = body.moment("construction_window_end_date")
        if window_end.date() < window_start.date():
            raise ApiError("ERR_INVALID_REQUEST",
                           "construction_window_end_date must not precede the start date.")
        basis = body.enum("allocation_basis", ALLOCATION_BASES, required=False,
                          default="PRO_RATA_LOAD")
        find.tower(tower_id)
        analysis = find.analysis(analysis_id)

        _require_free_window(tower_id, window_start, window_end)
        if analysis["status"] != "QUOTED" \
                or not analysis["modification_construction_cost_cents"] \
                or analysis["modification_construction_cost_cents"] <= 0:
            raise ApiError("ERR_QUOTATION_MISSING",
                           "The originating analysis carries no modification quotation.")

        record = new_record(
            tower_id=tower_id,
            originating_analysis_id=analysis_id,
            construction_window_start_date=window_start,
            construction_window_end_date=window_end,
            status="PROPOSED",
            base_construction_cost_cents=analysis["modification_construction_cost_cents"],
            volume_discount_pct=None,
            engineering_fee_cents=None,
            total_cost_cents=None,
            allocation_basis=basis,
            proposing_engineer_user_id=user_id,
            certified_by_user_id=None,
            funded_at=None,
            added_capacity_load_units=None,
            cancellation_reason=None,
            _date_raw=body.raw_dates(),
        )
        db.projects[record["id"]] = record
        return object_response(serializers.project(record), 201)

    @app.route("/tower-colo/modification-projects", methods=["GET"])
    def list_projects():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Tenant")
        status = query_enum("status", PROJECT_STATUSES)
        tower_id = query_value("tower_id")
        analysis_id = query_value("originating_analysis_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.projects.values())
        if tower_id is not None:
            items = [p for p in items if p["tower_id"] == tower_id]
        if analysis_id is not None:
            items = [p for p in items if p["originating_analysis_id"] == analysis_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.project(p) for p in page], meta)

    @app.route("/tower-colo/modification-projects/<project_id>", methods=["GET"])
    def read_project(project_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Tenant")
        project = find.project(project_id)
        resolve_identity(user_id, role)
        return object_response(serializers.project(project))

    @app.route("/tower-colo/modification-projects/<project_id>/allocate-cost-shares",
               methods=["POST"])
    def allocate_cost_shares(project_id):
        auth("StructuralEngineer")
        Body()
        project = find.project(project_id)
        if project["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "Only a PROPOSED project may have its cost shares allocated.")
        _require_free_window(project["tower_id"],
                             project["construction_window_start_date"],
                             project["construction_window_end_date"],
                             exclude_project_id=project["id"])
        beneficiaries = _resolve_beneficiaries(project)
        total_basis = sum((dec(b["basis_load_units"]) for b in beneficiaries), Decimal(0))
        if not beneficiaries or total_basis <= 0:
            raise ApiError("ERR_COST_SHARE_BENEFICIARY_INVALID",
                           "No usable cost-share beneficiary set resolves for this project.")
        analysis = db.analyses.get(project["originating_analysis_id"])
        if analysis is None or analysis["status"] != "QUOTED" \
                or not analysis["modification_construction_cost_cents"]:
            raise ApiError("ERR_QUOTATION_MISSING",
                           "The originating analysis carries no modification quotation.")
        _mint_shares(project, beneficiaries)
        project["status"] = "COST_ALLOCATED"
        bump(project)
        return object_response(serializers.project(project))

    @app.route("/tower-colo/modification-projects/<project_id>/reallocate-cost-shares",
               methods=["POST"])
    def reallocate_cost_shares(project_id):
        auth("StructuralEngineer")
        body = Body()
        expected_version = body.integer("expected_modification_project_version")
        basis = body.enum("allocation_basis", ALLOCATION_BASES, required=False, default=None)
        project = find.project(project_id)
        if expected_version != project["version"]:
            raise ApiError("ERR_STALE_PROJECT_VERSION",
                           "The project version has moved since it was read.")
        if project["status"] != "COST_ALLOCATED":
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "Only a COST_ALLOCATED project may be reallocated.")
        existing = services.project_shares(project["id"])
        if any(share["status"] == "BILLED" for share in existing):
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "A billed cost share blocks reallocation.")
        beneficiaries = _resolve_beneficiaries(project)
        total_basis = sum((dec(b["basis_load_units"]) for b in beneficiaries), Decimal(0))
        if not beneficiaries or total_basis <= 0:
            raise ApiError("ERR_COST_SHARE_BENEFICIARY_INVALID",
                           "No usable cost-share beneficiary set resolves for this project.")
        for share in existing:
            if share["status"] in ("PENDING", "ACCEPTED"):
                share["status"] = "VOIDED"
                bump(share)
        if basis is not None:
            project["allocation_basis"] = basis
        _mint_shares(project, beneficiaries)
        bump(project)
        return object_response(serializers.project(project))

    @app.route("/tower-colo/modification-projects/<project_id>/start-construction",
               methods=["POST"])
    def start_construction(project_id):
        auth("StructuralEngineer")
        Body()
        project = find.project(project_id)
        if project["status"] != "FUNDED":
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "Only a FUNDED project may start construction.")
        if db.clock.date() < project["construction_window_start_date"].date():
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "The construction window has not opened yet.")
        project["status"] = "IN_CONSTRUCTION"
        bump(project)
        return object_response(serializers.project(project))

    @app.route("/tower-colo/modification-projects/<project_id>/certify-completion",
               methods=["POST"])
    def certify_completion(project_id):
        user_id, _role = auth("StructuralEngineer")
        body = Body()
        added = body.number("added_capacity_load_units", exclusive_min=0)
        project = find.project(project_id)
        if project["status"] != "IN_CONSTRUCTION":
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "Only a project in construction may be certified.")
        analysis = db.analyses.get(project["originating_analysis_id"])
        if user_id == project["proposing_engineer_user_id"] \
                or (analysis is not None and user_id == analysis["engineer_user_id"]):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The proposing or analysing engineer may not certify completion.")
        for share in services.project_shares(project["id"]):
            if share["status"] != "VOIDED" and share["status"] != "BILLED":
                raise ApiError("ERR_INVALID_PROJECT_STATE",
                               "Every outstanding cost share must be billed before "
                               "certification.")
        project["status"] = "CERTIFIED"
        project["certified_by_user_id"] = user_id
        project["added_capacity_load_units"] = added
        bump(project)
        tower = find.tower(project["tower_id"])
        tower["rated_capacity_load_units"] = dec(tower["rated_capacity_load_units"]) + added
        services.promote_if_open(tower)
        bump(tower)
        return object_response(serializers.project(project))

    @app.route("/tower-colo/modification-projects/<project_id>/cancel", methods=["POST"])
    def cancel_project(project_id):
        auth("PortfolioAdmin")
        body = Body()
        reason = body.string("cancellation_reason", required=False, max_len=500, default=None)
        project = find.project(project_id)
        status = project["status"]
        if status not in ("PROPOSED", "COST_ALLOCATED", "STALLED", "FUNDED"):
            raise ApiError("ERR_INVALID_PROJECT_STATE",
                           "The project is not in a cancellable state.")
        if reason is not None:
            project["cancellation_reason"] = reason
        if status in ("COST_ALLOCATED", "STALLED"):
            for share in services.project_shares(project["id"]):
                if share["status"] in ("PENDING", "ACCEPTED"):
                    share["status"] = "VOIDED"
                    bump(share)
        elif status == "FUNDED":
            for share in services.project_shares(project["id"]):
                if share["status"] == "BILLED":
                    share["status"] = "VOIDED"
                    bump(share)
                    tenant = db.tenants.get(share["tenant_id"])
                    if tenant is not None:
                        services.adjust_tenant_balance(tenant, -share["share_cents"])
                elif share["status"] in ("PENDING", "ACCEPTED"):
                    share["status"] = "VOIDED"
                    bump(share)
        project["status"] = "CANCELLED"
        bump(project)
        if status == "FUNDED":
            tower = find.tower(project["tower_id"])
            services.promote_if_open(tower)
            bump(tower)
        return object_response(serializers.project(project))

    # -----------------------------------------------------------------------
    # Cost shares
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/cost-shares", methods=["GET"])
    def list_cost_shares():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Tenant")
        status = query_enum("status", SHARE_STATUSES)
        project_id = query_value("modification_project_id")
        tenant_id = query_value("tenant_id")
        amendment_id = query_value("site_amendment_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.cost_shares.values())
        if project_id is not None:
            items = [s for s in items if s["modification_project_id"] == project_id]
        if tenant_id is not None:
            items = [s for s in items if s["tenant_id"] == tenant_id]
        if amendment_id is not None:
            items = [s for s in items if s["site_amendment_id"] == amendment_id]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.cost_share(s) for s in page], meta)

    @app.route("/tower-colo/cost-shares/<share_id>", methods=["GET"])
    def read_cost_share(share_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Tenant")
        share = find.cost_share(share_id)
        resolve_identity(user_id, role)
        return object_response(serializers.cost_share(share))

    @app.route("/tower-colo/cost-shares/<share_id>/accept", methods=["POST"])
    def accept_cost_share(share_id):
        user_id, role = auth("Tenant")
        Body()
        share = find.cost_share(share_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, share["tenant_id"])
        project = db.projects.get(share["modification_project_id"])
        if share["status"] != "PENDING" or project is None \
                or project["status"] != "COST_ALLOCATED":
            raise ApiError("ERR_INVALID_COST_SHARE_STATE",
                           "Only a PENDING share on a COST_ALLOCATED project may be accepted.")
        share["status"] = "ACCEPTED"
        share["accepted_at"] = db.clock
        bump(share)

        siblings = services.project_shares(project["id"])
        outstanding = [s for s in siblings
                       if s["status"] not in ("VOIDED",) and s["status"] == "PENDING"]
        if not outstanding:
            project["status"] = "FUNDED"
            project["funded_at"] = db.clock
            for sibling in siblings:
                if sibling["status"] == "ACCEPTED":
                    sibling["status"] = "BILLED"
                    bump(sibling)
                    tenant = db.tenants.get(sibling["tenant_id"])
                    if tenant is not None:
                        services.adjust_tenant_balance(tenant, sibling["share_cents"])
            bump(project)
            tower = find.tower(project["tower_id"])
            services.freeze_pushback(tower)
            bump(tower)
        return object_response(serializers.cost_share(share))

    @app.route("/tower-colo/cost-shares/<share_id>/decline", methods=["POST"])
    def decline_cost_share(share_id):
        user_id, role = auth("Tenant")
        body = Body()
        reason = body.string("decline_reason", required=False, max_len=500, default=None)
        share = find.cost_share(share_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, share["tenant_id"])
        project = db.projects.get(share["modification_project_id"])
        if share["status"] != "PENDING" or project is None \
                or project["status"] != "COST_ALLOCATED":
            raise ApiError("ERR_INVALID_COST_SHARE_STATE",
                           "Only a PENDING share on a COST_ALLOCATED project may be declined.")
        share["status"] = "DECLINED"
        if reason is not None:
            share["decline_reason"] = reason
        bump(share)
        for sibling in services.project_shares(project["id"]):
            if sibling["status"] == "PENDING":
                sibling["status"] = "VOIDED"
                bump(sibling)
        project["status"] = "STALLED"
        bump(project)
        return object_response(serializers.cost_share(share))
