"""Tenants, master lease agreements, colocation applications and equipment lines."""
import re
from decimal import Decimal

import calc
import find
import serializers
import services
from db import bump, db, new_record, sorted_records
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

CARRIER_CODE = re.compile(r"^[A-Z0-9]{3,12}$")
MLA_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED")
APPLICATION_STATUSES = (
    "DRAFT", "SUBMITTED", "UNDER_STRUCTURAL_REVIEW", "CAPACITY_HOLD",
    "MODIFICATION_REQUIRED", "ON_HOLD", "APPROVED", "AMENDMENT_ISSUED",
    "REJECTED", "WITHDRAWN",
)
EQUIPMENT_TYPES = ("ANTENNA", "RRU", "TMA", "DISH")
EDITABLE_APPLICATION_STATES = ("DRAFT", "MODIFICATION_REQUIRED")


def _owning_tenant_id(application):
    mla = db.mlas.get(application["master_lease_agreement_id"])
    return mla["tenant_id"] if mla else None


def _recompute_total_load(application):
    application["total_load_units"] = services.application_total_load_units(application)


def register(app):

    # -----------------------------------------------------------------------
    # Tenants
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/tenants", methods=["POST"])
    def create_tenant():
        auth("PortfolioAdmin")
        body = Body()
        legal_name = body.string("legal_name", max_len=160)
        carrier_code = body.string("carrier_code", max_len=12)
        if not CARRIER_CODE.match(carrier_code):
            raise ApiError("ERR_INVALID_REQUEST",
                           "carrier_code must be 3 to 12 uppercase alphanumeric characters.")
        for existing in db.tenants.values():
            if existing["carrier_code"] == carrier_code:
                raise ApiError("ERR_INVALID_REQUEST",
                               "carrier_code must be unique across tenants.")
        record = new_record(
            legal_name=legal_name,
            carrier_code=carrier_code,
            outstanding_balance_cents=0,
        )
        db.tenants[record["id"]] = record
        return object_response(serializers.tenant(record), 201)

    @app.route("/tower-colo/tenants/<tenant_id>", methods=["GET"])
    def read_tenant(tenant_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        tenant = find.tenant(tenant_id)
        resolve_identity(user_id, role)
        return object_response(serializers.tenant(tenant))

    @app.route("/tower-colo/tenants/<tenant_id>/payments", methods=["POST"])
    def create_tenant_payment(tenant_id):
        user_id, role = auth("PortfolioAdmin", "Tenant")
        body = Body()
        amount = body.integer("amount_cents")
        tenant = find.tenant(tenant_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, tenant["id"])
        if amount <= 0:
            raise ApiError("ERR_INVALID_PAYMENT_AMOUNT",
                           "amount_cents must be greater than zero.")
        services.adjust_tenant_balance(tenant, -amount)
        return object_response(serializers.tenant(tenant))

    # -----------------------------------------------------------------------
    # Master lease agreements
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/master-lease-agreements", methods=["POST"])
    def create_mla():
        auth("PortfolioAdmin")
        body = Body()
        tenant_id = body.ident("tenant_id")
        base_rent = body.integer("base_monthly_rent_cents", exclusive_min=0)
        escalator = body.number("escalator_pct", minimum=0, maximum=25)
        initial_term_years = body.integer("initial_term_years", minimum=1)
        renewal_terms_count = body.integer("renewal_terms_count", minimum=0)
        expires_on = body.moment("expires_on")
        expedited = body.integer("expedited_review_days", required=False,
                                 minimum=1, maximum=45, default=None)
        find.tenant(tenant_id)
        record = new_record(
            tenant_id=tenant_id,
            base_monthly_rent_cents=base_rent,
            escalator_pct=escalator,
            initial_term_years=initial_term_years,
            renewal_terms_count=renewal_terms_count,
            expires_on=expires_on,
            expedited_review_days=expedited,
            status="DRAFT",
            _date_raw=body.raw_dates(),
        )
        db.mlas[record["id"]] = record
        return object_response(serializers.mla(record), 201)

    @app.route("/tower-colo/master-lease-agreements/<mla_id>/activate", methods=["POST"])
    def activate_mla(mla_id):
        auth("PortfolioAdmin")
        Body()
        mla = find.mla(mla_id)
        if mla["status"] != "DRAFT":
            raise ApiError("ERR_MLA_NOT_ACTIVE",
                           "Only a DRAFT master lease agreement may be activated.")
        if mla["expires_on"] <= db.clock:
            raise ApiError("ERR_INVALID_REQUEST",
                           "expires_on must be after the current logical clock instant.")
        mla["status"] = "ACTIVE"
        bump(mla)
        return object_response(serializers.mla(mla))

    @app.route("/tower-colo/master-lease-agreements/<mla_id>/reinstate", methods=["POST"])
    def reinstate_mla(mla_id):
        auth("PortfolioAdmin")
        Body()
        mla = find.mla(mla_id)
        if mla["status"] != "ACTIVE":
            raise ApiError("ERR_MLA_NOT_ACTIVE",
                           "Only an ACTIVE master lease agreement may be reinstated.")
        tenant = db.tenants.get(mla["tenant_id"])
        if tenant is not None and services.credit_status_for(tenant) == "DELINQUENT":
            raise ApiError("ERR_TENANT_DELINQUENT",
                           "The tenant is still delinquent.")
        services.unhold_applications(mla)
        bump(mla)
        return object_response(serializers.mla(mla))

    @app.route("/tower-colo/tenants/<tenant_id>/master-lease-agreements", methods=["GET"])
    def list_tenant_mlas(tenant_id):
        user_id, role = auth("PortfolioAdmin", "Tenant")
        status = query_enum("status", MLA_STATUSES)
        limit, offset = pagination()
        tenant = find.tenant(tenant_id)
        resolve_identity(user_id, role)
        items = services.tenant_mlas(tenant["id"])
        if status is not None:
            items = [m for m in items if m["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.mla(m) for m in page], meta)

    # -----------------------------------------------------------------------
    # Colocation applications
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/colocation-applications", methods=["POST"])
    def create_application():
        user_id, role = auth("Tenant")
        body = Body()
        tower_id = body.ident("tower_id")
        mla_id = body.ident("master_lease_agreement_id")
        bottom = body.number("requested_elevation_bottom_ft", minimum=0)
        top = body.number("requested_elevation_top_ft", exclusive_min=bottom)
        ground = body.number("requested_ground_space_sqft", exclusive_min=0)
        expedited = body.boolean("expedited_requested", required=False, default=False)
        find.tower(tower_id)
        mla = find.mla(mla_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, mla["tenant_id"])
        record = new_record(
            tower_id=tower_id,
            master_lease_agreement_id=mla_id,
            requested_elevation_bottom_ft=bottom,
            requested_elevation_top_ft=top,
            requested_ground_space_sqft=ground,
            expedited_requested=expedited,
            status="DRAFT",
            submitted_at=None,
            review_deadline_at=None,
            sla_breached=False,
            total_load_units=Decimal(0),
            revision_count=0,
            rejection_reason=None,
            revision_note=None,
            _analysis_since_entry=False,
        )
        db.applications[record["id"]] = record
        return object_response(serializers.application(record), 201)

    @app.route("/tower-colo/colocation-applications", methods=["GET"])
    def list_applications():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        status = query_enum("status", APPLICATION_STATUSES)
        tower_id = query_value("tower_id")
        mla_id = query_value("master_lease_agreement_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.applications.values())
        if tower_id is not None:
            items = [a for a in items if a["tower_id"] == tower_id]
        if mla_id is not None:
            items = [a for a in items if a["master_lease_agreement_id"] == mla_id]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.application(a) for a in page], meta)

    @app.route("/tower-colo/colocation-applications/<application_id>", methods=["GET"])
    def read_application(application_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        application = find.application(application_id)
        resolve_identity(user_id, role)
        return object_response(serializers.application(application))

    # -----------------------------------------------------------------------
    # Equipment lines
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/colocation-applications/<application_id>/equipment-lines",
               methods=["POST"])
    def create_equipment_line(application_id):
        user_id, role = auth("Tenant")
        body = Body()
        equipment_type = body.enum("equipment_type", EQUIPMENT_TYPES)
        model_code = body.string("model_code", max_len=40)
        quantity = body.integer("quantity", minimum=1)
        unit_weight = body.number("unit_weight_lbs", exclusive_min=0)
        wind_area = body.number("wind_area_sqft", minimum=0)
        mount_elevation = body.number("mount_elevation_ft", minimum=0)
        application = find.application(application_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, _owning_tenant_id(application))
        record = new_record(
            colocation_application_id=application["id"],
            installed_amendment_id=None,
            equipment_type=equipment_type,
            model_code=model_code,
            quantity=quantity,
            unit_weight_lbs=unit_weight,
            wind_area_sqft=wind_area,
            mount_elevation_ft=mount_elevation,
            load_units=calc.equipment_line_load_units(
                unit_weight, wind_area, quantity, mount_elevation),
        )
        db.equipment_lines[record["id"]] = record
        _recompute_total_load(application)
        bump(application)
        return object_response(serializers.equipment_line(record), 201)

    @app.route("/tower-colo/equipment-lines", methods=["GET"])
    def list_equipment_lines():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        application_id = query_value("colocation_application_id")
        amendment_id = query_value("installed_amendment_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.equipment_lines.values())
        if application_id is not None:
            items = [l for l in items if l["colocation_application_id"] == application_id]
        if amendment_id is not None:
            items = [l for l in items if l["installed_amendment_id"] == amendment_id]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.equipment_line(l) for l in page], meta)

    @app.route("/tower-colo/equipment-lines/<line_id>", methods=["GET"])
    def read_equipment_line(line_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        line = find.equipment_line(line_id)
        resolve_identity(user_id, role)
        return object_response(serializers.equipment_line(line))

    @app.route("/tower-colo/equipment-lines/<line_id>", methods=["DELETE"])
    def delete_equipment_line(line_id):
        user_id, role = auth("Tenant")
        line = find.equipment_line(line_id)
        application = db.applications.get(line["colocation_application_id"])
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, _owning_tenant_id(application))
        if application["status"] not in EDITABLE_APPLICATION_STATES:
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "Equipment lines may only be removed while the application "
                           "is DRAFT or MODIFICATION_REQUIRED.")
        del db.equipment_lines[line["id"]]
        _recompute_total_load(application)
        bump(application)
        return "", 204

    # -----------------------------------------------------------------------
    # Application lifecycle
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/colocation-applications/<application_id>/submit",
               methods=["POST"])
    def submit_application(application_id):
        user_id, role = auth("Tenant")
        Body()
        application = find.application(application_id)
        resolve_identity(user_id, role)
        mla = db.mlas.get(application["master_lease_agreement_id"])
        require_tenant_scope(role, user_id, mla["tenant_id"] if mla else None)
        if application["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "Only a DRAFT application may be submitted.")
        if mla["status"] != "ACTIVE":
            raise ApiError("ERR_MLA_NOT_ACTIVE",
                           "The master lease agreement is not ACTIVE.")
        if services.application_privilege_for(mla) != "ENABLED":
            raise ApiError("ERR_MLA_PRIVILEGE_SUSPENDED",
                           "The master lease agreement's application privilege is suspended.")
        tower = find.tower(application["tower_id"])
        if not (tower["min_colocation_elevation_ft"] <= application["requested_elevation_bottom_ft"]
                and application["requested_elevation_top_ft"] <= tower["max_elevation_ft"]):
            raise ApiError("ERR_ELEVATION_OUT_OF_RANGE",
                           "The requested band lies outside the tower's usable range.")
        if not services.application_lines(application["id"]):
            raise ApiError("ERR_NO_EQUIPMENT_LINES",
                           "The application has no equipment lines.")
        tenant = db.tenants.get(mla["tenant_id"])
        if tenant is not None and services.credit_status_for(tenant) == "DELINQUENT":
            raise ApiError("ERR_TENANT_DELINQUENT", "The tenant is delinquent.")

        application["status"] = "SUBMITTED"
        _recompute_total_load(application)
        services.stamp_review_window(application)
        if services.tower_capacity_posture(tower) == "OPEN":
            application["status"] = "UNDER_STRUCTURAL_REVIEW"
        else:
            application["status"] = "CAPACITY_HOLD"
        bump(application)
        return object_response(serializers.application(application))

    @app.route("/tower-colo/colocation-applications/<application_id>/revise",
               methods=["POST"])
    def revise_application(application_id):
        user_id, role = auth("Tenant")
        body = Body()
        note = body.string("revision_note", required=False, max_len=500, default=None)
        application = find.application(application_id)
        resolve_identity(user_id, role)
        mla = db.mlas.get(application["master_lease_agreement_id"])
        require_tenant_scope(role, user_id, mla["tenant_id"] if mla else None)
        if application["status"] != "MODIFICATION_REQUIRED":
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "Only a MODIFICATION_REQUIRED application may be revised.")
        if mla["status"] != "ACTIVE":
            raise ApiError("ERR_MLA_NOT_ACTIVE",
                           "The master lease agreement is not ACTIVE.")
        if services.application_privilege_for(mla) != "ENABLED":
            raise ApiError("ERR_MLA_PRIVILEGE_SUSPENDED",
                           "The master lease agreement's application privilege is suspended.")
        tower = find.tower(application["tower_id"])
        if services.tower_capacity_posture(tower) != "OPEN":
            raise ApiError("ERR_TOWER_POSTURE_FROZEN",
                           "The tower posture does not admit a revision.")
        if not services.application_lines(application["id"]):
            raise ApiError("ERR_NO_EQUIPMENT_LINES",
                           "The application has no equipment lines.")

        application["revision_count"] += 1
        if note is not None:
            application["revision_note"] = note
        _recompute_total_load(application)
        application["status"] = "UNDER_STRUCTURAL_REVIEW"
        services.stamp_review_window(application)
        services.supersede_live_analyses(application)
        bump(application)
        return object_response(serializers.application(application))

    @app.route("/tower-colo/colocation-applications/<application_id>/approve",
               methods=["POST"])
    def approve_application(application_id):
        auth("PortfolioAdmin")
        Body()
        application = find.application(application_id)
        status = application["status"]
        if status not in ("UNDER_STRUCTURAL_REVIEW", "MODIFICATION_REQUIRED"):
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "The application is not in an approvable state.")
        if status == "UNDER_STRUCTURAL_REVIEW":
            newest = services.newest_live_analysis(application["id"])
            if newest is None or newest["result"] != "PASS":
                raise ApiError("ERR_INVALID_APPLICATION_STATE",
                               "The newest live structural analysis is not a PASS.")
        else:
            newest = services.newest_live_analysis(application["id"])
            certified = None
            if newest is not None:
                for project in db.projects.values():
                    if project["status"] == "CERTIFIED" \
                            and project["originating_analysis_id"] == newest["id"]:
                        certified = project
                        break
            if certified is None:
                raise ApiError("ERR_INVALID_APPLICATION_STATE",
                               "No certified reinforcement covers this application.")
        tower = find.tower(application["tower_id"])
        if services.tower_capacity_posture(tower) == "FROZEN":
            raise ApiError("ERR_TOWER_POSTURE_FROZEN", "The tower posture is FROZEN.")
        tenant = services.application_tenant(application)
        if tenant is not None and services.credit_status_for(tenant) == "DELINQUENT":
            raise ApiError("ERR_TENANT_DELINQUENT", "The tenant is delinquent.")
        application["status"] = "APPROVED"
        bump(application)
        return object_response(serializers.application(application))

    @app.route("/tower-colo/colocation-applications/<application_id>/reject",
               methods=["POST"])
    def reject_application(application_id):
        auth("PortfolioAdmin")
        body = Body()
        reason = body.string("rejection_reason", required=False, max_len=500, default=None)
        application = find.application(application_id)
        if application["status"] not in ("UNDER_STRUCTURAL_REVIEW", "MODIFICATION_REQUIRED"):
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "The application is not in a rejectable state.")
        application["status"] = "REJECTED"
        if reason is not None:
            application["rejection_reason"] = reason
        bump(application)
        return object_response(serializers.application(application))

    @app.route("/tower-colo/colocation-applications/<application_id>/withdraw",
               methods=["POST"])
    def withdraw_application(application_id):
        user_id, role = auth("Tenant")
        Body()
        application = find.application(application_id)
        resolve_identity(user_id, role)
        require_tenant_scope(role, user_id, _owning_tenant_id(application))
        status = application["status"]
        if status not in ("DRAFT", "SUBMITTED", "UNDER_STRUCTURAL_REVIEW",
                          "CAPACITY_HOLD", "MODIFICATION_REQUIRED"):
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "The application is not in a withdrawable state.")
        if status in ("UNDER_STRUCTURAL_REVIEW", "MODIFICATION_REQUIRED"):
            services.supersede_live_analyses(application)
        application["status"] = "WITHDRAWN"
        bump(application)
        return object_response(serializers.application(application))
