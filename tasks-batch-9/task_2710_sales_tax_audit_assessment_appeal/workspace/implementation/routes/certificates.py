"""ExemptionCertificate endpoints (PRD 3.5)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import (
    bad,
    body,
    guard,
    opt_bool,
    opt_str,
    present,
    req_bool,
    req_enum,
    req_id,
    req_int,
    req_str,
)
from routes.common import (
    CERT_STATUSES,
    EXEMPTION_TYPES,
    apply_filter,
    body_fk,
    listing,
    one,
    path_get,
    require_owner,
)
from services import calc, derive

bp = Blueprint("certificates", __name__)

DETERMINATIONS = ("VALIDATED", "REJECTED")


def _good_faith(cert):
    return bool(
        cert["received_before_sale"]
        and cert["form_complete"]
        and cert.get("purchaser_permit_number") is not None
        and cert["claimed_exemption_matches_purchaser_business"]
    )


@bp.post("/exemption-certificates")
@guard("FieldAuditor", "Taxpayer")
def create_certificate():
    data = body()
    audit_id = req_id(data, "audit_id")
    purchaser_name = req_str(data, "purchaser_name", 1, None)
    permit_number = None
    if present(data, "purchaser_permit_number"):
        permit_number = req_str(data, "purchaser_permit_number", 1, None)
    exemption_type = req_enum(data, "claimed_exemption_type", EXEMPTION_TYPES)
    covered = req_int(data, "covered_sale_amount_cents", 1)
    received_before_sale = req_bool(data, "received_before_sale")
    form_complete = req_bool(data, "form_complete")
    matches = req_bool(data, "claimed_exemption_matches_purchaser_business")
    unit_id = data.get("sample_unit_id")
    if unit_id is not None and not isinstance(unit_id, str):
        bad("sample_unit_id must be a string.")

    audit = body_fk("audits", audit_id)
    unit = body_fk("sample_units", unit_id) if unit_id is not None else None

    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")

    rec = db.new_record(
        {
            "audit_id": audit["id"],
            "sample_unit_id": unit["id"] if unit else None,
            "purchaser_name": purchaser_name,
            "purchaser_permit_number": permit_number,
            "claimed_exemption_type": exemption_type,
            "covered_sale_amount_cents": covered,
            "received_before_sale": received_before_sale,
            "form_complete": form_complete,
            "claimed_exemption_matches_purchaser_business": matches,
            "good_faith_accepted": False,
            "status": "ON_FILE",
            "cure_count": 0,
            "missing_certificate_tax_cents": 0,
            "review_note": None,
        }
    )
    rec["good_faith_accepted"] = _good_faith(rec)
    db.insert("exemption_certificates", rec)
    return one("exemption_certificates", rec, 201)


@bp.get("/exemption-certificates")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def list_certificates():
    rows = db.all_of("exemption_certificates")
    rows = apply_filter(rows, "audit_id")
    rows = apply_filter(rows, "sample_unit_id")
    rows = apply_filter(rows, "status", CERT_STATUSES)
    rows = apply_filter(rows, "claimed_exemption_type", EXEMPTION_TYPES)
    return listing("exemption_certificates", rows)


@bp.get("/exemption-certificates/<cid>")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def read_certificate(cid):
    return one("exemption_certificates", path_get("exemption_certificates", cid))


@bp.post("/exemption-certificates/<cid>/review")
@guard("FieldAuditor")
def review_certificate(cid):
    cert = path_get("exemption_certificates", cid)
    data = body()
    determination = req_enum(data, "determination", DETERMINATIONS)
    note = opt_str(data, "review_note", 1, None, None)

    if cert["status"] not in ("ON_FILE", "CURED"):
        raise ApiError("ERR_INVALID_STATE")
    audit = db.get("audits", cert["audit_id"])
    if audit is None or audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")

    unit = db.get("sample_units", cert.get("sample_unit_id"))

    if determination == "VALIDATED":
        if not _good_faith(cert):
            raise ApiError("ERR_GOOD_FAITH_STANDARD_NOT_MET")
        cert["status"] = "VALIDATED"
        cert["review_note"] = note
        cert["missing_certificate_tax_cents"] = 0
        db.touch(cert)
        derive.recompute_certificate_deficiency(audit)
        if unit is not None and unit["error_class"] == "CERTIFICATE_DEFECT":
            unit["error_class"] = "NO_ERROR"
            unit["declared_error_amount_cents"] = None
            unit["error_amount_cents"] = 0
            unit["redetermination_count"] = unit["redetermination_count"] + 1
            db.touch(unit)
            derive.mark_projection_stale(audit)
        db.touch(audit)
        return one("exemption_certificates", cert)

    cert["status"] = "REJECTED"
    cert["review_note"] = note
    cert["missing_certificate_tax_cents"] = calc.tax_on(cert["covered_sale_amount_cents"])
    db.touch(cert)
    if unit is not None:
        unit["error_class"] = "CERTIFICATE_DEFECT"
        unit["declared_error_amount_cents"] = None
        unit["error_amount_cents"] = calc.tax_on(unit["exempt_sale_amount_cents"])
        unit["redetermination_count"] = unit["redetermination_count"] + 1
        db.touch(unit)
    derive.recompute_certificate_deficiency(audit)
    derive.mark_projection_stale(audit)
    db.touch(audit)
    return one("exemption_certificates", cert)


@bp.post("/exemption-certificates/<cid>/cure")
@guard("Taxpayer")
def cure_certificate(cid):
    cert = path_get("exemption_certificates", cid)
    audit = db.get("audits", cert["audit_id"])
    require_owner(audit["taxpayer_id"] if audit else None)

    data = body()
    permit_number = None
    if present(data, "purchaser_permit_number"):
        permit_number = req_str(data, "purchaser_permit_number", 1, None)
    received = opt_bool(data, "received_before_sale", None)
    form_complete = opt_bool(data, "form_complete", None)
    matches = opt_bool(data, "claimed_exemption_matches_purchaser_business", None)

    if cert["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE")
    if audit is None or audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")

    if permit_number is not None:
        cert["purchaser_permit_number"] = permit_number
    if received is not None:
        cert["received_before_sale"] = received
    if form_complete is not None:
        cert["form_complete"] = form_complete
    if matches is not None:
        cert["claimed_exemption_matches_purchaser_business"] = matches
    cert["status"] = "CURED"
    cert["cure_count"] = cert["cure_count"] + 1
    cert["good_faith_accepted"] = _good_faith(cert)
    db.touch(cert)
    return one("exemption_certificates", cert)
