"""Site amendments, departure, compliance audits and retroactive billing."""
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
from util import dec, rhu3

EXECUTION_STATUSES = ("DRAFT", "PENDING_SIGNATURE", "EXECUTED", "TERMINATION_NOTICED",
                      "TERMINATED", "VOIDED")
BILLING_STATUSES = ("NOT_BILLING", "BILLING", "SUSPENDED", "CLOSED")
AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "FINALIZED")
AUDIT_BASES = ("INSTALL_DATE_BASIS", "DISCOVERY_LIMITED")
FINDING_STATUSES = ("OPEN", "BILLED")

DECLARED_BILLING_MOVES = (("BILLING", "SUSPENDED"), ("SUSPENDED", "BILLING"),
                          ("BILLING", "CLOSED"))


def _post_execution_pct(tower, amendment, superseded):
    reserved = services.tower_reserved_load_units(tower)
    if superseded is not None:
        reserved -= dec(superseded["reserved_load_units"])
    reserved += dec(amendment["reserved_load_units"])
    return calc.loading_pct(rhu3(reserved), tower["rated_capacity_load_units"])


def _band_conflicts(tower, amendment, superseded):
    buffer_ft = calc.ELEVATION_SEPARATION_BUFFER_FT
    bottom = dec(amendment["elevation_bottom_ft"])
    top = dec(amendment["elevation_top_ft"])
    for neighbour in services.contributing_amendments(tower["id"]):
        if neighbour["id"] == amendment["id"]:
            continue
        if superseded is not None and neighbour["id"] == superseded["id"]:
            continue
        n_bottom = dec(neighbour["elevation_bottom_ft"])
        n_top = dec(neighbour["elevation_top_ft"])
        if top + buffer_ft <= n_bottom or n_top + buffer_ft <= bottom:
            continue
        return True
    return False


def register(app):

    # -----------------------------------------------------------------------
    # Site amendments
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/site-amendments", methods=["POST"])
    def create_amendment():
        auth("PortfolioAdmin")
        body = Body()
        mla_id = body.ident("master_lease_agreement_id")
        tower_id = body.ident("tower_id")
        application_id = body.ident("colocation_application_id")
        effective_date = body.moment("effective_date")
        term_end_date = body.moment("term_end_date")
        if term_end_date <= effective_date:
            raise ApiError("ERR_INVALID_REQUEST",
                           "term_end_date must be after effective_date.")
        base_rent = body.integer("base_monthly_rent_cents", required=False,
                                 exclusive_min=0, default=None)
        escalator = body.number("escalator_pct", required=False, minimum=0, maximum=25,
                                default=None)
        deposit = body.integer("restoration_deposit_cents", required=False, minimum=0,
                               default=0)
        supersedes_id = body.ident("supersedes_amendment_id", required=False, default=None)

        mla = find.mla(mla_id)
        tower = find.tower(tower_id)
        application = find.application(application_id)
        superseded = find.amendment(supersedes_id) if supersedes_id is not None else None

        if application["status"] != "APPROVED" \
                or services.amendment_for_application(application["id"]) is not None:
            raise ApiError("ERR_INVALID_APPLICATION_STATE",
                           "Only an APPROVED application without an amendment may be papered.")
        if superseded is not None:
            if superseded["execution_status"] != "EXECUTED" \
                    or superseded["tower_id"] != tower_id \
                    or superseded["master_lease_agreement_id"] != mla_id:
                raise ApiError("ERR_SUPERSEDE_TARGET_INVALID",
                               "The superseded amendment must be an executed amendment of "
                               "the same tenant on the same tower.")

        record = new_record(
            master_lease_agreement_id=mla_id,
            tower_id=tower_id,
            colocation_application_id=application_id,
            supersedes_amendment_id=supersedes_id,
            execution_status="DRAFT",
            billing_status="NOT_BILLING",
            base_monthly_rent_cents=(base_rent if base_rent is not None
                                     else mla["base_monthly_rent_cents"]),
            escalator_pct=(escalator if escalator is not None else dec(mla["escalator_pct"])),
            effective_date=effective_date,
            term_end_date=term_end_date,
            elevation_bottom_ft=application["requested_elevation_bottom_ft"],
            elevation_top_ft=application["requested_elevation_top_ft"],
            ground_space_sqft=application["requested_ground_space_sqft"],
            reserved_load_units=application["total_load_units"],
            restoration_deposit_cents=deposit,
            restoration_status="NOT_REQUIRED",
            notice_given_at=None,
            terminated_at=None,
            _date_raw=body.raw_dates(),
        )
        db.amendments[record["id"]] = record
        application["status"] = "AMENDMENT_ISSUED"
        bump(application)
        return object_response(serializers.amendment(record), 201)

    @app.route("/tower-colo/site-amendments", methods=["GET"])
    def list_amendments():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        execution_status = query_enum("execution_status", EXECUTION_STATUSES)
        billing_status = query_enum("billing_status", BILLING_STATUSES)
        mla_id = query_value("master_lease_agreement_id")
        tower_id = query_value("tower_id")
        application_id = query_value("colocation_application_id")
        supersedes_id = query_value("supersedes_amendment_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.amendments.values())
        if mla_id is not None:
            items = [a for a in items if a["master_lease_agreement_id"] == mla_id]
        if tower_id is not None:
            items = [a for a in items if a["tower_id"] == tower_id]
        if application_id is not None:
            items = [a for a in items if a["colocation_application_id"] == application_id]
        if supersedes_id is not None:
            items = [a for a in items if a["supersedes_amendment_id"] == supersedes_id]
        if execution_status is not None:
            items = [a for a in items if a["execution_status"] == execution_status]
        if billing_status is not None:
            items = [a for a in items if a["billing_status"] == billing_status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.amendment(a) for a in page], meta)

    @app.route("/tower-colo/site-amendments/<amendment_id>", methods=["GET"])
    def read_amendment(amendment_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        amendment = find.amendment(amendment_id)
        resolve_identity(user_id, role)
        return object_response(serializers.amendment(amendment))

    @app.route("/tower-colo/site-amendments/<amendment_id>/execute", methods=["POST"])
    def execute_amendment(amendment_id):
        auth("PortfolioAdmin")
        body = Body()
        signature_received = body.boolean("signature_received", required=True)
        amendment = find.amendment(amendment_id)
        tower = find.tower(amendment["tower_id"])
        superseded = (db.amendments.get(amendment["supersedes_amendment_id"])
                      if amendment["supersedes_amendment_id"] else None)

        if not signature_received:
            if amendment["execution_status"] != "DRAFT":
                raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                               "Only a DRAFT amendment may park awaiting signature.")
            if services.active_ground_lease(tower["id"]) is None:
                raise ApiError("ERR_GROUND_LEASE_NOT_ACTIVE",
                               "The tower has no ACTIVE ground lease.")
            amendment["execution_status"] = "PENDING_SIGNATURE"
            bump(amendment)
            return object_response(serializers.amendment(amendment))

        if amendment["execution_status"] not in ("DRAFT", "PENDING_SIGNATURE"):
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "Only a DRAFT or PENDING_SIGNATURE amendment may be executed.")
        lease = services.active_ground_lease(tower["id"])
        if lease is None:
            raise ApiError("ERR_GROUND_LEASE_NOT_ACTIVE",
                           "The tower has no ACTIVE ground lease.")
        if services.tower_capacity_posture(tower) == "FROZEN":
            raise ApiError("ERR_TOWER_POSTURE_FROZEN", "The tower posture is FROZEN.")
        if _post_execution_pct(tower, amendment, superseded) >= calc.STRUCTURAL_CAPACITY_LIMIT_PCT:
            raise ApiError("ERR_STRUCTURAL_CAPACITY_EXCEEDED",
                           "Post-execution structural loading reaches the capacity limit.")
        application = db.applications.get(amendment["colocation_application_id"])
        if application is None or not services.has_structural_clearance(application):
            raise ApiError("ERR_STRUCTURAL_CLEARANCE_MISSING",
                           "No passing analysis or certified reinforcement clears this band.")
        if _band_conflicts(tower, amendment, superseded):
            raise ApiError("ERR_ELEVATION_BAND_CONFLICT",
                           "The elevation band does not clear the separation buffer.")
        available = services.tower_available_ground_space(tower)
        if superseded is not None:
            available += dec(superseded["ground_space_sqft"])
        if available < dec(amendment["ground_space_sqft"]):
            raise ApiError("ERR_GROUND_SPACE_UNAVAILABLE",
                           "Insufficient compound ground space remains.")
        if amendment["term_end_date"].date() > lease["term_end_date"].date():
            raise ApiError("ERR_TERM_EXCEEDS_GROUND_LEASE",
                           "The amendment term outlasts the ground lease term.")
        tenant = services.amendment_tenant(amendment)
        if tenant is not None and services.credit_status_for(tenant) == "DELINQUENT":
            raise ApiError("ERR_TENANT_DELINQUENT", "The tenant is delinquent.")

        amendment["execution_status"] = "EXECUTED"
        amendment["billing_status"] = "BILLING"
        amendment["restoration_status"] = ("PENDING" if amendment["restoration_deposit_cents"] > 0
                                          else "NOT_REQUIRED")
        bump(amendment)
        for line in services.application_lines(application["id"]):
            line["installed_amendment_id"] = amendment["id"]
            bump(line)
        if superseded is not None:
            superseded["execution_status"] = "TERMINATED"
            superseded["restoration_status"] = "COMPLETE"
            superseded["billing_status"] = "CLOSED"
            bump(superseded)
        if tenant is not None and amendment["restoration_deposit_cents"]:
            services.adjust_tenant_balance(tenant, amendment["restoration_deposit_cents"])
        bump(tower)
        return object_response(serializers.amendment(amendment))

    @app.route("/tower-colo/site-amendments/<amendment_id>/void", methods=["POST"])
    def void_amendment(amendment_id):
        auth("PortfolioAdmin")
        Body()
        amendment = find.amendment(amendment_id)
        if amendment["execution_status"] not in ("DRAFT", "PENDING_SIGNATURE"):
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "Only an unexecuted amendment may be voided.")
        amendment["execution_status"] = "VOIDED"
        amendment["billing_status"] = "CLOSED"
        bump(amendment)
        return object_response(serializers.amendment(amendment))

    @app.route("/tower-colo/site-amendments/<amendment_id>/billing-status", methods=["POST"])
    def move_billing_status(amendment_id):
        auth("PortfolioAdmin")
        body = Body()
        to_status = body.enum("to_status", BILLING_STATUSES)
        amendment = find.amendment(amendment_id)
        move = (amendment["billing_status"], to_status)
        if move not in DECLARED_BILLING_MOVES:
            raise ApiError("ERR_INVALID_BILLING_STATE",
                           "Billing move %s -> %s is not declared." % move)
        if move == ("BILLING", "CLOSED"):
            if amendment["execution_status"] != "TERMINATION_NOTICED":
                raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                               "Billing may only be closed after termination notice.")
        elif amendment["execution_status"] not in ("EXECUTED", "TERMINATION_NOTICED"):
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "The amendment is not in an executed state.")
        amendment["billing_status"] = to_status
        bump(amendment)
        return object_response(serializers.amendment(amendment))

    @app.route("/tower-colo/site-amendments/<amendment_id>/termination-notice",
               methods=["POST"])
    def termination_notice(amendment_id):
        user_id, role = auth("Tenant")
        Body()
        amendment = find.amendment(amendment_id)
        resolve_identity(user_id, role)
        mla = db.mlas.get(amendment["master_lease_agreement_id"])
        require_tenant_scope(role, user_id, mla["tenant_id"] if mla else None)
        if amendment["execution_status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "Only an EXECUTED amendment may receive termination notice.")
        if amendment["billing_status"] == "CLOSED":
            raise ApiError("ERR_INVALID_BILLING_STATE",
                           "Billing on this amendment is already closed.")
        amendment["execution_status"] = "TERMINATION_NOTICED"
        amendment["notice_given_at"] = db.clock
        amendment["restoration_status"] = "PENDING"
        bump(amendment)
        return object_response(serializers.amendment(amendment))

    @app.route("/tower-colo/site-amendments/<amendment_id>/complete-decommission",
               methods=["POST"])
    def complete_decommission(amendment_id):
        auth("PortfolioAdmin")
        body = Body()
        confirmed = body.boolean("restoration_confirmed", required=True)
        if confirmed is not True:
            raise ApiError("ERR_INVALID_REQUEST", "restoration_confirmed must be true.")
        amendment = find.amendment(amendment_id)
        if amendment["execution_status"] != "TERMINATION_NOTICED":
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "Only an amendment under termination notice may be decommissioned.")
        if amendment["restoration_status"] != "PENDING":
            raise ApiError("ERR_INVALID_AMENDMENT_STATE",
                           "The restoration obligation is not pending.")
        amendment["execution_status"] = "TERMINATED"
        amendment["terminated_at"] = db.clock
        amendment["restoration_status"] = "COMPLETE"
        amendment["billing_status"] = "CLOSED"
        bump(amendment)
        tenant = services.amendment_tenant(amendment)
        if tenant is not None and amendment["restoration_deposit_cents"]:
            services.adjust_tenant_balance(tenant, -amendment["restoration_deposit_cents"])
        tower = find.tower(amendment["tower_id"])
        services.promote_if_open(tower)
        bump(tower)
        return object_response(serializers.amendment(amendment))

    # -----------------------------------------------------------------------
    # Equipment audits
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/equipment-audits", methods=["POST"])
    def create_audit():
        user_id, _role = auth("ComplianceAuditor")
        body = Body()
        tower_id = body.ident("tower_id")
        audit_date = body.moment("audit_date")
        basis = body.enum("basis", AUDIT_BASES)
        find.tower(tower_id)
        if audit_date > db.clock:
            raise ApiError("ERR_AUDIT_DATE_IN_FUTURE",
                           "The audit date must not be in the future.")
        record = new_record(
            tower_id=tower_id,
            audit_date=audit_date,
            basis=basis,
            status="SCHEDULED",
            auditor_user_id=user_id,
            _date_raw=body.raw_dates(),
        )
        db.audits[record["id"]] = record
        return object_response(serializers.audit(record), 201)

    @app.route("/tower-colo/towers/<tower_id>/equipment-audits", methods=["GET"])
    def list_tower_audits(tower_id):
        auth("PortfolioAdmin", "ComplianceAuditor")
        status = query_enum("status", AUDIT_STATUSES)
        limit, offset = pagination()
        tower = find.tower(tower_id)
        items = sorted_records([a for a in db.audits.values()
                                if a["tower_id"] == tower["id"]])
        if status is not None:
            items = [a for a in items if a["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.audit(a) for a in page], meta)

    @app.route("/tower-colo/equipment-audits/<audit_id>/start", methods=["POST"])
    def start_audit(audit_id):
        auth("ComplianceAuditor")
        Body()
        audit = find.audit(audit_id)
        if audit["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_AUDIT_STATE",
                           "Only a SCHEDULED audit may be started.")
        if audit["audit_date"] > db.clock:
            raise ApiError("ERR_AUDIT_DATE_IN_FUTURE",
                           "The audit date has not been reached.")
        audit["status"] = "IN_PROGRESS"
        bump(audit)
        return object_response(serializers.audit(audit))

    @app.route("/tower-colo/equipment-audits/<audit_id>/findings", methods=["POST"])
    def create_finding(audit_id):
        auth("ComplianceAuditor")
        body = Body()
        tenant_id = body.ident("tenant_id")
        description = body.string("description", max_len=240)
        observed = body.number("observed_load_units", exclusive_min=0)
        installed_on = body.moment("installed_on_date")
        mount_elevation = body.number("mount_elevation_ft", minimum=0)
        amendment_id = body.ident("site_amendment_id", required=False, default=None)
        audit = find.audit(audit_id)
        find.tenant(tenant_id)
        if amendment_id is not None:
            find.amendment(amendment_id)
        if audit["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_AUDIT_STATE",
                           "Findings may only be recorded on an audit in progress.")
        if installed_on.date() > audit["audit_date"].date():
            raise ApiError("ERR_FINDING_DATE_AFTER_AUDIT",
                           "The installation date must not be after the audit date.")
        record = new_record(
            equipment_audit_id=audit["id"],
            tenant_id=tenant_id,
            site_amendment_id=amendment_id,
            description=description,
            observed_load_units=observed,
            installed_on_date=installed_on,
            mount_elevation_ft=mount_elevation,
            months_billable=0,
            retroactive_billing_cents=0,
            status="OPEN",
            _date_raw=body.raw_dates(),
        )
        db.findings[record["id"]] = record
        return object_response(serializers.finding(record), 201)

    @app.route("/tower-colo/audit-findings", methods=["GET"])
    def list_findings():
        user_id, role = auth("PortfolioAdmin", "ComplianceAuditor", "Tenant")
        status = query_enum("status", FINDING_STATUSES)
        audit_id = query_value("equipment_audit_id")
        tenant_id = query_value("tenant_id")
        amendment_id = query_value("site_amendment_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.findings.values())
        if audit_id is not None:
            items = [f for f in items if f["equipment_audit_id"] == audit_id]
        if tenant_id is not None:
            items = [f for f in items if f["tenant_id"] == tenant_id]
        if amendment_id is not None:
            items = [f for f in items if f["site_amendment_id"] == amendment_id]
        if status is not None:
            items = [f for f in items if f["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.finding(f) for f in page], meta)

    @app.route("/tower-colo/audit-findings/<finding_id>", methods=["GET"])
    def read_finding(finding_id):
        user_id, role = auth("PortfolioAdmin", "ComplianceAuditor", "Tenant")
        finding = find.finding(finding_id)
        resolve_identity(user_id, role)
        return object_response(serializers.finding(finding))

    @app.route("/tower-colo/equipment-audits/<audit_id>/finalize", methods=["POST"])
    def finalize_audit(audit_id):
        auth("ComplianceAuditor")
        Body()
        audit = find.audit(audit_id)
        if audit["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_AUDIT_STATE",
                           "Only an audit in progress may be finalized.")
        per_tenant = []
        totals = {}
        for finding in services.audit_findings(audit["id"]):
            if finding["status"] != "OPEN":
                continue
            months = calc.retro_months(audit["audit_date"], finding["installed_on_date"],
                                       audit["basis"])
            amount = calc.retro_billing_cents(months, finding["observed_load_units"])
            finding["months_billable"] = months
            finding["retroactive_billing_cents"] = amount
            finding["status"] = "BILLED"
            bump(finding)
            if finding["tenant_id"] not in totals:
                totals[finding["tenant_id"]] = 0
                per_tenant.append(finding["tenant_id"])
            totals[finding["tenant_id"]] += amount
        audit["status"] = "FINALIZED"
        bump(audit)
        for tenant_id in per_tenant:
            tenant = db.tenants.get(tenant_id)
            if tenant is not None and totals[tenant_id]:
                services.adjust_tenant_balance(tenant, totals[tenant_id])
        return object_response(serializers.audit(audit))
