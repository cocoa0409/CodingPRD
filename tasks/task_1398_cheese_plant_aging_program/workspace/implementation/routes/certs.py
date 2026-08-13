"""Export certificate resources (PRD 3.9)."""

import uuid

from flask import request

from db import STORES, new_record, now, touch
from errors import ApiError, invalid_state
from helpers import auth, body, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("export_certificates")

GET_ROLES = ("PlantAdmin", "ComplianceOfficer")
ACTIVE_CERT_STATES = ("REQUESTED", "ISSUED")


@bp.post("/plant/export-certificates")
def create_cert():
    auth("ComplianceOfficer")
    b = body()
    cut_wrap_run_id = f_str(b, "cut_wrap_run_id")
    destination_country = f_str(b, "destination_country")
    consignee = f_str(b, "consignee")
    run = get_or_404("cut_wrap_runs", cut_wrap_run_id, "cut-wrap run")
    # Rung 9: only one active certificate per run; a fresh request may follow
    # a denial or revocation.
    for cert in STORES["export_certificates"].values():
        if cert["cut_wrap_run_id"] == run["id"] and cert["status"] in ACTIVE_CERT_STATES:
            raise ApiError(
                "ERR_CERT_ALREADY_EXISTS",
                409,
                "An active certificate already exists for this run",
            )
    rec = new_record()
    rec.update(
        plant_id=run["plant_id"],
        cut_wrap_run_id=run["id"],
        destination_country=destination_country,
        consignee=consignee,
        certificate_number=None,
        issued_at=None,
        status="REQUESTED",
    )
    STORES["export_certificates"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/export-certificates/<exportCertificateId>")
def get_cert(exportCertificateId):
    auth(*GET_ROLES)
    rec = get_or_404("export_certificates", exportCertificateId, "export certificate")
    return success(serialize(rec))


@bp.get("/plant/export-certificates")
def list_certs():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "export_certificates",
        [
            ("plant_id", request.args.get("plant_id")),
            ("cut_wrap_run_id", request.args.get("cut_wrap_run_id")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/export-certificates/<exportCertificateId>/issue")
def issue_cert(exportCertificateId):
    auth("ComplianceOfficer")
    body(required=False)
    rec = get_or_404("export_certificates", exportCertificateId, "export certificate")
    if rec["status"] != "REQUESTED":
        invalid_state("Export certificate is not REQUESTED")
    # Rung 8 gates at issuance: plant export listing first, then run state.
    plant = STORES["plants"].get(rec["plant_id"])
    if plant is None or not plant["export_listed"]:
        raise ApiError(
            "ERR_PLANT_NOT_EXPORT_LISTED",
            409,
            "Plant is not on the export-eligible regulatory listing",
        )
    run = STORES["cut_wrap_runs"].get(rec["cut_wrap_run_id"])
    if run is None or run["status"] != "RECONCILED":
        raise ApiError("ERR_RUN_NOT_RECONCILED", 409, "Cut-wrap run is not RECONCILED")
    rec["certificate_number"] = "CERT-" + uuid.uuid4().hex[:12].upper()
    rec["issued_at"] = now()
    rec["status"] = "ISSUED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/export-certificates/<exportCertificateId>/deny")
def deny_cert(exportCertificateId):
    auth("ComplianceOfficer")
    body(required=False)
    rec = get_or_404("export_certificates", exportCertificateId, "export certificate")
    if rec["status"] != "REQUESTED":
        invalid_state("Export certificate is not REQUESTED")
    rec["status"] = "DENIED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/export-certificates/<exportCertificateId>/revoke")
def revoke_cert(exportCertificateId):
    auth("ComplianceOfficer")
    body(required=False)
    rec = get_or_404("export_certificates", exportCertificateId, "export certificate")
    if rec["status"] != "ISSUED":
        invalid_state("Export certificate is not ISSUED")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(serialize(rec))
