"""CoveredEntity registration root, its state machine, and nested
child-sites / prescribers / patients / contract-pharmacies / accumulators /
audit-findings / repayment-obligations list endpoints."""
from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import (
    require_string,
    require_enum,
    require_bool,
    require_int,
    parse_pagination,
    paginate,
)
from services.compliance import recompute_ce_posture
from filters import filter_eq

bp = Blueprint("covered_entities", __name__)

ENTITY_TYPES = {
    "DSH",
    "CHILDRENS_HOSPITAL",
    "FREESTANDING_CANCER",
    "CRITICAL_ACCESS",
    "RURAL_REFERRAL",
    "FQHC",
    "RYAN_WHITE",
    "STD_CLINIC",
}
GPO_PROHIBITED_TYPES = {"DSH", "CHILDRENS_HOSPITAL", "FREESTANDING_CANCER"}
BILLING_MODES = {"CARVE_IN", "CARVE_OUT"}


# --------------------------------------------------------------------------
# CoveredEntity CRUD
# --------------------------------------------------------------------------
@bp.route("/covered-entities", methods=["POST"])
def create_covered_entity():
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()

    hrsa_id = require_string(body, "hrsa_id")
    legal_name = require_string(body, "legal_name")
    entity_type = require_enum(body, "entity_type", ENTITY_TYPES)
    medicaid_billing_mode = require_enum(
        body, "medicaid_billing_mode", BILLING_MODES, required=False, default="CARVE_OUT"
    )
    medicaid_provider_number = require_string(
        body, "medicaid_provider_number", required=False, allow_empty=True
    )

    # ERR_DUPLICATE_HRSA_ID — unique across all covered entities.
    for ce in db.covered_entities.all():
        if ce["hrsa_id"] == hrsa_id:
            raise err("ERR_DUPLICATE_HRSA_ID", "hrsa_id already in use")

    # CARVE_IN requires a non-null medicaid_provider_number.
    if medicaid_billing_mode == "CARVE_IN" and not medicaid_provider_number:
        raise err("ERR_MEF_NUMBER_REQUIRED", "CARVE_IN requires medicaid_provider_number")

    rec = base_record(full_meta=True)
    rec.update(
        {
            "hrsa_id": hrsa_id,
            "legal_name": legal_name,
            "entity_type": entity_type,
            "gpo_prohibited": entity_type in GPO_PROHIBITED_TYPES,
            "medicaid_billing_mode": medicaid_billing_mode,
            "medicaid_provider_number": medicaid_provider_number,
            "registration_status": "PENDING",
            "recert_period_index": 0,
            "compliance_posture": "GOOD",
            "open_repayment_cents": 0,
        }
    )
    db.covered_entities.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/covered-entities/<ce_id>", methods=["GET"])
def get_covered_entity(ce_id):
    get_identity()  # any authenticated role
    ce = lookup.covered_entity(ce_id)
    return success(serialize(ce))


@bp.route("/covered-entities", methods=["GET"])
def list_covered_entities():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.covered_entities.all())
    items = filter_eq(items, "registration_status")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# CoveredEntity state machine
# --------------------------------------------------------------------------
def _transition_ce(ce_id, allowed_role, expect_status, on_ok):
    _, role = get_identity()
    require_role(role, {allowed_role})
    ce = lookup.covered_entity(ce_id)
    if ce["registration_status"] not in expect_status:
        raise err("ERR_INVALID_STATE", "Transition not allowed from current state")
    on_ok(ce)
    return success(serialize(ce))


@bp.route("/covered-entities/<ce_id>/approve", methods=["POST"])
def approve_ce(ce_id):
    def on_ok(ce):
        # Re-check MEF requirement at approval time.
        if ce["medicaid_billing_mode"] == "CARVE_IN" and not ce.get("medicaid_provider_number"):
            raise err("ERR_MEF_NUMBER_REQUIRED", "CARVE_IN requires medicaid_provider_number")
        ce["registration_status"] = "ACTIVE"
        touch(ce)
        recompute_ce_posture(ce)

    return _transition_ce(ce_id, "HrsaAuditor", {"PENDING"}, on_ok)


@bp.route("/covered-entities/<ce_id>/deny", methods=["POST"])
def deny_ce(ce_id):
    def on_ok(ce):
        ce["registration_status"] = "DENIED"
        touch(ce)

    return _transition_ce(ce_id, "HrsaAuditor", {"PENDING"}, on_ok)


@bp.route("/covered-entities/<ce_id>/flag-recert", methods=["POST"])
def flag_recert_ce(ce_id):
    def on_ok(ce):
        ce["registration_status"] = "RECERT_DUE"
        touch(ce)

    return _transition_ce(ce_id, "HrsaAuditor", {"ACTIVE"}, on_ok)


@bp.route("/covered-entities/<ce_id>/recertify", methods=["POST"])
def recertify_ce(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    ce = lookup.covered_entity(ce_id)
    if ce["registration_status"] != "RECERT_DUE":
        raise err("ERR_INVALID_STATE", "Recertify requires RECERT_DUE")
    # Gated on GOOD posture (no open findings, no outstanding repayment).
    recompute_ce_posture(ce)
    if ce["compliance_posture"] != "GOOD":
        raise err("ERR_INVALID_STATE", "Recertification blocked while FLAGGED")
    ce["registration_status"] = "ACTIVE"
    ce["recert_period_index"] += 1
    touch(ce)
    return success(serialize(ce))


@bp.route("/covered-entities/<ce_id>/terminate", methods=["POST"])
def terminate_ce(ce_id):
    def on_ok(ce):
        ce["registration_status"] = "TERMINATED"
        touch(ce)
        # Cascade: every ACTIVE contract-pharmacy arrangement -> TERMINATED.
        for cp in db.contract_pharmacies.all():
            if cp["covered_entity_id"] == ce["id"] and cp["arrangement_status"] == "ACTIVE":
                cp["arrangement_status"] = "TERMINATED"
                touch(cp)

    return _transition_ce(ce_id, "HrsaAuditor", {"ACTIVE", "RECERT_DUE"}, on_ok)


# --------------------------------------------------------------------------
# Child sites (nested under CE)
# --------------------------------------------------------------------------
@bp.route("/covered-entities/<ce_id>/child-sites", methods=["POST"])
def create_child_site(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    site_name = require_string(body, "site_name")
    service_address = require_string(body, "service_address")
    registered = require_bool(body, "registered", default=False)

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "site_name": site_name,
            "service_address": service_address,
            "registered": registered,
        }
    )
    db.child_sites.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/covered-entities/<ce_id>/child-sites", methods=["GET"])
def list_child_sites(ce_id):
    get_identity()
    ce = lookup.covered_entity(ce_id)
    limit, offset = parse_pagination()
    items = [c for c in db.child_sites.all() if c["covered_entity_id"] == ce["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "registered", bool_field=True)
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Prescribers (nested create under CE; global list)
# --------------------------------------------------------------------------
PRESCRIBER_RELATIONSHIPS = {"EMPLOYED", "CONTRACTED", "REFERRAL_ONLY", "EXTERNAL"}


@bp.route("/covered-entities/<ce_id>/prescribers", methods=["POST"])
def create_prescriber(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    npi = require_string(body, "npi")
    full_name = require_string(body, "full_name")
    relationship_type = require_enum(body, "relationship_type", PRESCRIBER_RELATIONSHIPS)

    for p in db.prescribers.all():
        if p["npi"] == npi:
            raise err("ERR_INVALID_REQUEST", "npi already in use")

    # Prescriber carries only id + created_at (immutable). PRD §2.4.
    rec = base_record(full_meta=False)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "npi": npi,
            "full_name": full_name,
            "relationship_type": relationship_type,
        }
    )
    db.prescribers.put(rec)
    return success(serialize(rec), status=201)


# --------------------------------------------------------------------------
# Patients (nested create under CE; global list)
# --------------------------------------------------------------------------
@bp.route("/covered-entities/<ce_id>/patients", methods=["POST"])
def create_patient(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "PharmacyOperator"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    mrn = require_string(body, "mrn")
    has_ce_care_record = require_bool(body, "has_ce_care_record", default=True)
    ce_retains_responsibility = require_bool(body, "ce_retains_responsibility", default=True)
    medicaid_ffs_enrolled = require_bool(body, "medicaid_ffs_enrolled", default=False)

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "mrn": mrn,
            "has_ce_care_record": has_ce_care_record,
            "ce_retains_responsibility": ce_retains_responsibility,
            "medicaid_ffs_enrolled": medicaid_ffs_enrolled,
        }
    )
    db.patients.put(rec)
    return success(serialize(rec), status=201)


# --------------------------------------------------------------------------
# CE-scoped list endpoints for cross-aggregate children
# --------------------------------------------------------------------------
@bp.route("/covered-entities/<ce_id>/contract-pharmacies", methods=["GET"])
def list_ce_contract_pharmacies(ce_id):
    get_identity()
    ce = lookup.covered_entity(ce_id)
    limit, offset = parse_pagination()
    items = [c for c in db.contract_pharmacies.all() if c["covered_entity_id"] == ce["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "arrangement_status")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/covered-entities/<ce_id>/accumulators", methods=["GET"])
def list_ce_accumulators(ce_id):
    get_identity()
    ce = lookup.covered_entity(ce_id)
    limit, offset = parse_pagination()
    items = [a for a in db.accumulators.all() if a["covered_entity_id"] == ce["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "drug_product_id")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/covered-entities/<ce_id>/audit-findings", methods=["GET"])
def list_ce_audit_findings(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    ce = lookup.covered_entity(ce_id)
    limit, offset = parse_pagination()
    items = [f for f in db.audit_findings.all() if f["covered_entity_id"] == ce["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "finding_status")
    items = filter_eq(items, "origin")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/covered-entities/<ce_id>/repayment-obligations", methods=["GET"])
def list_ce_repayments(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    ce = lookup.covered_entity(ce_id)
    limit, offset = parse_pagination()
    items = [r for r in db.repayment_obligations.all() if r["covered_entity_id"] == ce["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "status")
    items = filter_eq(items, "source_kind")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
