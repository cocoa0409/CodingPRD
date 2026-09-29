from decimal import Decimal

from flask import Blueprint

import config
from db import db
from errors import fail
from middleware import endpoint, body
from numeric import D, q
from response import created, ok
from routes.common import get_audit, get_pathway, paged_list, resolve_refs
from services import calc, cascade, derive

bp = Blueprint("audits", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "ProgramAdministrator",
              "CreditVerifier", "FinanceController"]

ACTUAL_FIELDS = (
    ("actual_pipeline_mmbtu", 3),
    ("actual_vs_tonnes_lagoon", 3),
    ("actual_vs_tonnes_solid_storage", 3),
    ("actual_vs_tonnes_daily_spread", 3),
    ("actual_haul_tonne_km", 2),
    ("actual_process_g_per_mj", 2),
)


@bp.post("/verification-audits")
@endpoint(["CreditVerifier"])
def create_audit():
    b = body()
    (pathway,) = resolve_refs(b, (("pathway_id", get_pathway),))
    row = db.new_row({
        "pathway_id": pathway["id"],
        "audit_year": b.integer("audit_year", gt=0),
        "verifier_body_name": b.string("verifier_body_name"),
        "status": "FIELDWORK",
        "reported_ci_score": None,
        "ci_delta": None,
        "finding_severity": None,
        "remediation_round": 0,
    })
    for name, _scale in ACTUAL_FIELDS:
        row[name] = None
    db.audits[row["id"]] = row
    return created(derive.ser_audit(row))


@bp.get("/verification-audits")
@endpoint(READ_ROLES)
def list_audits():
    return paged_list(db.audits, derive.ser_audit, ("pathway_id", "status"))


@bp.get("/verification-audits/<audit_id>")
@endpoint(READ_ROLES)
def read_audit(audit_id):
    return ok(derive.ser_audit(get_audit(audit_id)))


@bp.post("/verification-audits/<audit_id>/fieldwork")
@endpoint(["CreditVerifier"])
def record_fieldwork(audit_id):
    audit = get_audit(audit_id)
    b = body()
    values = {}
    for name, scale in ACTUAL_FIELDS:
        values[name] = b.number(name, scale, ge=0)
    pathway = db.pathways[audit["pathway_id"]]

    if audit["status"] not in ("FIELDWORK", "REMEDIATION"):
        fail("ERR_INVALID_STATE",
             "Fieldwork may only be recorded from FIELDWORK or REMEDIATION.")
    if pathway["status"] != "CERTIFIED" or pathway["certified_ci_score"] is None:
        fail("ERR_PATHWAY_NOT_CERTIFIED",
             "The pathway must be CERTIFIED with a certified carbon intensity.")

    audit.update(values)
    audit["reported_ci_score"] = derive.verified_ci_score(audit)
    audit["ci_delta"] = q(D(audit["reported_ci_score"])
                          - D(pathway["certified_ci_score"]), 2)
    audit["finding_severity"] = None
    audit["status"] = "FIELDWORK"
    db.touch(audit)
    return ok(derive.ser_audit(audit))


@bp.post("/verification-audits/<audit_id>/findings")
@endpoint(["CreditVerifier"])
def issue_findings(audit_id):
    audit = get_audit(audit_id)
    b = body()
    b.string("narrative", required=False)
    pathway = db.pathways[audit["pathway_id"]]

    if audit["status"] != "FIELDWORK":
        fail("ERR_INVALID_STATE", "Findings may only be issued from FIELDWORK.")
    if audit["reported_ci_score"] is None:
        fail("ERR_INVALID_STATE", "Fieldwork must be recorded before findings.")

    severity = calc.finding_severity(audit["ci_delta"])
    audit["finding_severity"] = severity
    audit["status"] = "FINDINGS_ISSUED"
    db.touch(audit)

    certified = pathway["certified_ci_score"]
    if severity == "NONE":
        pathway["verified_ci_score"] = q(certified, 2)
        pathway["ci_adjustment"] = Decimal("0.00")
    else:
        pathway["verified_ci_score"] = q(audit["reported_ci_score"], 2)
        pathway["ci_adjustment"] = q(D(pathway["verified_ci_score"]) - D(certified), 2)
        if severity == "MATERIAL" and pathway["status"] == "CERTIFIED":
            pathway["status"] = "SUSPENDED"
    db.touch(pathway)
    if severity == "MATERIAL":
        cascade.cascade_material_finding(pathway)
    return ok(derive.ser_audit(audit))


@bp.post("/verification-audits/<audit_id>/remediation")
@endpoint(["ProjectOperator"])
def open_remediation(audit_id):
    audit = get_audit(audit_id)
    b = body()
    b.string("remediation_plan")

    if audit["status"] != "FINDINGS_ISSUED":
        fail("ERR_INVALID_STATE", "Remediation may only be opened from FINDINGS_ISSUED.")
    if audit["finding_severity"] not in ("MINOR", "MATERIAL"):
        fail("ERR_INVALID_STATE", "A clean audit has nothing to remediate.")
    if audit["remediation_round"] >= config.MAX_REMEDIATION_ROUNDS:
        fail("ERR_REMEDIATION_ROUNDS_EXHAUSTED",
             "The remediation round ceiling is reached.")

    audit["status"] = "REMEDIATION"
    audit["remediation_round"] += 1
    db.touch(audit)
    return ok(derive.ser_audit(audit))


@bp.post("/verification-audits/<audit_id>/close")
@endpoint(["CreditVerifier"])
def close_audit(audit_id):
    audit = get_audit(audit_id)
    b = body()
    b.string("closing_note", required=False)

    if audit["status"] not in ("REMEDIATION", "FINDINGS_ISSUED"):
        fail("ERR_INVALID_STATE",
             "Only a REMEDIATION or FINDINGS_ISSUED audit may be closed.")
    if audit["status"] == "FINDINGS_ISSUED" and audit["finding_severity"] != "NONE":
        fail("ERR_INVALID_STATE",
             "A findings-bearing audit must pass through remediation first.")

    audit["status"] = "CLOSED"
    db.touch(audit)
    return ok(derive.ser_audit(audit))
