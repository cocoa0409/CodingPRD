"""Certification documents (PRD 3.8)."""

from flask import Blueprint, g

import enums
from db import db, new_record, sorted_records, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.cascades import cascade_certificate_revoked
from services.lookup import (
    cert_doc_or_404,
    guard_disposition,
    lot_test_or_404,
    production_lot_or_404,
    project_traceability,
    require_unique,
    spec_for_lot,
)
from util import dec
from validate import (
    field_int,
    field_str,
    paginate,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("certs", __name__)

DRAFT_ROLES = ("QualityInspector", "QualityManager")


def _segregation_guard(cert):
    test = db.lot_tests.get(cert.get("lot_test_id"))
    if test is not None and test.get("performed_by_user_id") == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


@bp.post("/certification-documents")
@endpoint(DRAFT_ROLES)
def create_certification_document():
    body = g.body
    production_lot_id = field_str(body, "production_lot_id")
    lot_test_id = field_str(body, "lot_test_id")
    cert_serial = field_str(body, "cert_serial")
    expected_production_lot_version = field_int(body, "expected_production_lot_version")

    lot = production_lot_or_404(production_lot_id)
    test = lot_test_or_404(lot_test_id)

    require_unique("certification_documents", "cert_serial", cert_serial)

    if expected_production_lot_version != lot["version"]:
        raise ApiError("ERR_STALE_PRODUCTION_LOT_VERSION")

    guard_disposition(lot)

    heat = db.steel_heats.get(lot.get("traceability_heat_id"))
    if heat is None or heat["cert_status"] != "VERIFIED":
        raise ApiError("ERR_STEEL_HEAT_NOT_VERIFIED")

    spec = spec_for_lot(lot)
    if lot.get("achieved_strength_class") != spec["strength_class"]:
        raise ApiError("ERR_STRENGTH_CLASS_NOT_ACHIEVED")

    if spec.get("qualification_program") == "AEROSPACE_NADCAP":
        utilization = lot.get("tool_utilization_pct")
        if (
            utilization is not None
            and dec(utilization) > calc.AEROSPACE_TOOL_UTILIZATION_CEILING
        ):
            raise ApiError("ERR_AEROSPACE_TOOL_UTILIZATION_EXCEEDED")

    if test["production_lot_id"] != production_lot_id:
        raise ApiError("ERR_TEST_LOT_MISMATCH")
    if test["result"] != "ACCEPT":
        raise ApiError("ERR_TEST_NOT_ACCEPTED")

    cert = new_record(
        {
            "production_lot_id": production_lot_id,
            "lot_test_id": lot_test_id,
            "cert_serial": cert_serial,
            "revision": 1,
            "pinned_part_spec_version": lot["pinned_part_spec_version"],
            "certified_strength_class": lot.get("achieved_strength_class"),
            "traceability_chain": project_traceability(lot),
            "status": "DRAFT",
            "signed_by_user_id": None,
            "issued_at": None,
            "revoked_reason": None,
        }
    )
    db.certification_documents[cert["id"]] = cert
    touch(lot)
    return created(cert)


@bp.get("/certification-documents/<cert_id>")
@endpoint(ANY_ROLE)
def get_certification_document(cert_id):
    return ok(cert_doc_or_404(cert_id))


@bp.get("/certification-documents")
@endpoint(ANY_ROLE)
def list_certification_documents():
    limit, offset = pagination()
    production_lot_id = query_str("production_lot_id")
    lot_test_id = query_str("lot_test_id")
    status = query_enum("status", enums.CERT_DOC_STATUSES)

    records = sorted_records(db.certification_documents.values())
    if production_lot_id is not None:
        records = [r for r in records if r["production_lot_id"] == production_lot_id]
    if lot_test_id is not None:
        records = [r for r in records if r["lot_test_id"] == lot_test_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/certification-documents/<cert_id>/issue")
@endpoint("QualityManager")
def issue_certification_document(cert_id):
    cert = cert_doc_or_404(cert_id)
    lot = db.production_lots.get(cert["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")

    guard_disposition(lot)

    if cert["status"] not in ("DRAFT", "REISSUE_PENDING"):
        raise ApiError("ERR_INVALID_CERT_STATE")

    from_draft = cert["status"] == "DRAFT"
    if from_draft and lot["process_state"] != "TESTED":
        raise ApiError("ERR_INVALID_LOT_STATE")

    _segregation_guard(cert)

    live_spec = db.part_specs.get(lot["part_spec_id"])
    if live_spec is None or cert["pinned_part_spec_version"] != live_spec["version"]:
        raise ApiError("ERR_PART_SPEC_VERSION_DRIFT")

    final = lot.get("risk_score_final")
    if final is not None and dec(final) > calc.RISK_SCORE_CEILING:
        raise ApiError("ERR_RISK_SCORE_TOO_HIGH")

    cert["status"] = "ISSUED"
    cert["issued_at"] = db.now_iso()
    cert["signed_by_user_id"] = g.user_id
    touch(cert)

    if from_draft:
        lot["process_state"] = "CERTIFIED"
        touch(lot)
    return ok(cert)


@bp.post("/certification-documents/<cert_id>/revoke")
@endpoint("QualityManager")
def revoke_certification_document(cert_id):
    reason = field_str(g.body, "reason", allow_empty=True)

    cert = cert_doc_or_404(cert_id)
    if cert["status"] not in ("DRAFT", "ISSUED", "REISSUE_PENDING"):
        raise ApiError("ERR_INVALID_CERT_STATE")

    cert["status"] = "REVOKED"
    cert["revoked_reason"] = reason
    touch(cert)
    cascade_certificate_revoked(cert, reason, from_operator=True)
    return ok(cert)


@bp.post("/certification-documents/<cert_id>/reissue")
@endpoint("QualityManager")
def reissue_certification_document(cert_id):
    cert_serial = field_str(g.body, "cert_serial")

    cert = cert_doc_or_404(cert_id)
    require_unique(
        "certification_documents", "cert_serial", cert_serial, exclude_id=cert["id"]
    )

    lot = db.production_lots.get(cert["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")
    guard_disposition(lot)

    if cert["status"] != "REVOKED":
        raise ApiError("ERR_INVALID_CERT_STATE")

    _segregation_guard(cert)

    cert["cert_serial"] = cert_serial
    cert["revision"] = int(cert["revision"]) + 1
    cert["status"] = "REISSUE_PENDING"
    cert["signed_by_user_id"] = None
    cert["traceability_chain"] = project_traceability(lot)
    touch(cert)
    return ok(cert)
