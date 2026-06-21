"""AuditFinding lifecycle, self-disclosure, and per-finding repayment creation."""
from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import require_string, require_int, parse_pagination, paginate
from filters import filter_eq
from services.compliance import recompute_ce_posture
from services.repayment import assess_finding_repayment

bp = Blueprint("audit_findings", __name__)

FINDING_TYPES = {"DIVERSION", "DUPLICATE_DISCOUNT", "GPO_VIOLATION", "INELIGIBLE_PATIENT"}


# --------------------------------------------------------------------------
# Create (HRSA finding) / self-disclosure
# --------------------------------------------------------------------------
@bp.route("/audit-findings", methods=["POST"])
def create_audit_finding():
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    body = get_json_body()

    covered_entity_id = require_string(body, "covered_entity_id")
    prescription_dispense_id = require_string(body, "prescription_dispense_id")
    from validation import require_enum

    finding_type = require_enum(body, "finding_type", FINDING_TYPES)
    assessed_units = require_int(body, "assessed_units", minimum=1)

    ce = lookup.covered_entity(covered_entity_id)
    dispense = lookup.dispense(prescription_dispense_id)

    if assessed_units > dispense["quantity_units"]:
        raise err("ERR_ASSESSED_UNITS_EXCEED", "assessed_units exceeds dispense quantity")

    user_id, _ = get_identity()
    rec = _make_finding(ce, dispense, finding_type, assessed_units, "HRSA_AUDIT", user_id)
    recompute_ce_posture(ce)
    return success(serialize(rec), status=201)


@bp.route("/covered-entities/<ce_id>/self-disclosures", methods=["POST"])
def create_self_disclosure(ce_id):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    prescription_dispense_id = require_string(body, "prescription_dispense_id")
    from validation import require_enum

    finding_type = require_enum(body, "finding_type", FINDING_TYPES)
    assessed_units = require_int(body, "assessed_units", minimum=1)

    dispense = lookup.dispense(prescription_dispense_id)
    if assessed_units > dispense["quantity_units"]:
        raise err("ERR_ASSESSED_UNITS_EXCEED", "assessed_units exceeds dispense quantity")

    rec = _make_finding(ce, dispense, finding_type, assessed_units, "SELF_DISCLOSURE", user_id)
    # Self-disclosure drives the dispense DISPENSED -> DISCLOSED.
    if dispense["dispense_status"] == "DISPENSED":
        dispense["dispense_status"] = "DISCLOSED"
        touch(dispense)
    recompute_ce_posture(ce)
    return success(serialize(rec), status=201)


def _make_finding(ce, dispense, finding_type, assessed_units, origin, creator_user_id):
    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "prescription_dispense_id": dispense["id"],
            "finding_type": finding_type,
            "origin": origin,
            "finding_status": "OPEN",
            "assessed_units": assessed_units,
            "_creator_user_id": creator_user_id,  # internal, for SoD on dispute
        }
    )
    db.audit_findings.put(rec)
    return rec


# --------------------------------------------------------------------------
# Fetch / list
# --------------------------------------------------------------------------
@bp.route("/audit-findings/<f_id>", methods=["GET"])
def get_audit_finding(f_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    f = lookup.audit_finding(f_id)
    return success(_serialize_finding(f))


@bp.route("/audit-findings", methods=["GET"])
def list_audit_findings():
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.audit_findings.all())
    items = filter_eq(items, "prescription_dispense_id")
    items = filter_eq(items, "finding_status")
    page, total = paginate(items, limit, offset)
    return list_success([_serialize_finding(r) for r in page], limit, offset, total)


def _serialize_finding(f):
    out = serialize(f)
    out.pop("_creator_user_id", None)
    return out


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------
@bp.route("/audit-findings/<f_id>/start-review", methods=["POST"])
def start_review(f_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    f = lookup.audit_finding(f_id)
    if f["finding_status"] not in ("OPEN", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "start-review requires OPEN or DISPUTED")
    f["finding_status"] = "UNDER_REVIEW"
    touch(f)
    ce = db.covered_entities.get(f["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(_serialize_finding(f))


@bp.route("/audit-findings/<f_id>/dispute", methods=["POST"])
def dispute(f_id):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    f = lookup.audit_finding(f_id)
    if f["finding_status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "dispute requires UNDER_REVIEW")
    # Segregation of duties: a self-disclosed finding may not be disputed by its
    # discloser (same X-User-ID).
    if f["origin"] == "SELF_DISCLOSURE" and f.get("_creator_user_id") == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Discloser may not dispute their own finding")
    f["finding_status"] = "DISPUTED"
    touch(f)
    return success(_serialize_finding(f))


@bp.route("/audit-findings/<f_id>/resolve", methods=["POST"])
def resolve(f_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    f = lookup.audit_finding(f_id)
    if f["finding_status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "resolve requires UNDER_REVIEW")
    # Requires a repayment obligation referencing this finding.
    has_repayment = any(
        r["source_kind"] == "AUDIT_FINDING" and r["source_ref_id"] == f["id"]
        for r in db.repayment_obligations.all()
    )
    if not has_repayment:
        raise err("ERR_REPAYMENT_REQUIRED", "A repayment obligation must exist to resolve")
    f["finding_status"] = "RESOLVED"
    touch(f)
    # Drive the referenced dispense to DISCLOSED if not already terminal.
    dispense = db.dispenses.get(f["prescription_dispense_id"])
    if dispense is not None and dispense["dispense_status"] != "DISCLOSED":
        dispense["dispense_status"] = "DISCLOSED"
        touch(dispense)
    ce = db.covered_entities.get(f["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(_serialize_finding(f))


@bp.route("/audit-findings/<f_id>/dismiss", methods=["POST"])
def dismiss(f_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    f = lookup.audit_finding(f_id)
    if f["finding_status"] not in ("OPEN", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "dismiss requires OPEN or DISPUTED")
    f["finding_status"] = "DISMISSED"
    touch(f)
    ce = db.covered_entities.get(f["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(_serialize_finding(f))


# --------------------------------------------------------------------------
# Per-finding repayment creation
# --------------------------------------------------------------------------
@bp.route("/audit-findings/<f_id>/repayments", methods=["POST"])
def create_repayment(f_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor", "ComplianceOfficer"})
    f = lookup.audit_finding(f_id)

    assessed = assess_finding_repayment(f)

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": f["covered_entity_id"],
            "source_kind": "AUDIT_FINDING",
            "source_ref_id": f["id"],
            "assessed_cents": assessed,
            "paid_cents": 0,
            "remaining_balance_cents": assessed,
            "status": "OWED",
        }
    )
    db.repayment_obligations.put(rec)
    ce = db.covered_entities.get(f["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(serialize(rec), status=201)
