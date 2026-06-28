"""ISF (10+2) filing endpoints (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_str, require_int, stamp_create, bump_version,
    lookup, list_response, parse_iso8601, iso_now,
)
from middleware import require_roles, check_importer_ownership
from response import object_response
from serializers import isf_view
from services.calc import ISF_CUTOFF_HOURS

bp = Blueprint("isf_filings", __name__)


@bp.post("/isf-filings")
@require_roles("LicensedBroker", "ImporterUser")
def create_isf():
    body = get_body()
    importer_id = body.get("importer_id")
    if importer_id is None or not isinstance(importer_id, str) or importer_id == "":
        raise err("ERR_VALIDATION", "importer_id is required.")
    bill_of_lading = require_str(body, "bill_of_lading")  # non-empty, unique
    vessel_eta_raw = require_str(body, "vessel_eta")
    parse_iso8601(vessel_eta_raw, "vessel_eta")  # validate format
    data_element_count = require_int(body, "data_element_count")
    if data_element_count < 0 or data_element_count > 10:
        raise err("ERR_VALIDATION", "data_element_count must be in 0..10.")

    # existence (404) then ownership (403) before business rules.
    importer = lookup(db.importers, importer_id)
    check_importer_ownership(importer)

    # bill_of_lading unique across ISF filings -> ERR_DUPLICATE (409).
    for r in db.isf_filings.values():
        if r["bill_of_lading"] == bill_of_lading:
            raise err("ERR_DUPLICATE", "bill_of_lading already in use.")

    rec = {
        "importer_id": importer_id,
        "bill_of_lading": bill_of_lading,
        "vessel_eta": vessel_eta_raw,
        "data_element_count": data_element_count,
        "filed_at": None,
        "late_filing": False,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.isf_filings[rec["id"]] = rec
    return object_response(isf_view(rec), status=201)


@bp.get("/isf-filings/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_isf(id):
    return object_response(isf_view(lookup(db.isf_filings, id)))


@bp.get("/isf-filings")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_isf():
    return list_response(
        db.isf_filings.values(), isf_view, filters=[("importer_id", "importer_id")]
    )


@bp.post("/isf-filings/<id>/file")
@require_roles("LicensedBroker")
def file_isf(id):
    isf = lookup(db.isf_filings, id)
    # DRAFT -> FILED; permitted only while DRAFT.
    if isf["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "ISF is not DRAFT.")
    # All 10 data elements required.
    if isf["data_element_count"] != 10:
        raise err("ERR_ISF_INCOMPLETE", "All 10 ISF data elements required to file.")

    now_dt = db.now()
    isf["filed_at"] = iso_now(now_dt)
    eta = parse_iso8601(isf["vessel_eta"], "vessel_eta")
    cutoff = eta - timedelta(hours=ISF_CUTOFF_HOURS)
    # Late exactly when filed_at is strictly later than (vessel_eta - 24h).
    isf["late_filing"] = now_dt > cutoff
    isf["status"] = "FILED"
    bump_version(isf)
    return object_response(isf_view(isf))


@bp.post("/isf-filings/<id>/cancel")
@require_roles("LicensedBroker")
def cancel_isf(id):
    isf = lookup(db.isf_filings, id)
    # DRAFT -> CANCELLED; permitted only while DRAFT.
    if isf["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "ISF is not DRAFT.")
    isf["status"] = "CANCELLED"
    bump_version(isf)
    return object_response(isf_view(isf))
