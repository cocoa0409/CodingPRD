"""InjuryReport (FROI/SROI EDI) endpoints + EDI state machine (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_FROI_NOT_ACKNOWLEDGED,
    ERR_INVALID_MTC,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_enum
from routes._common import get_claim, get_injury_report

bp = Blueprint("injury_reports", __name__)

REPORT_KINDS = ["FROI", "SROI"]
FROI_MTCS = {"00"}
SROI_MTCS = {"IP", "CB", "SX", "FN"}


def _froi_acknowledged(claim_id: str) -> bool:
    for r in db.injury_reports.values():
        if (r["claim_id"] == claim_id and r["report_kind"] == "FROI"
                and r["edi_status"] == "ACKNOWLEDGED"):
            return True
    return False


@bp.post("/injury-reports")
def create_injury_report():
    require_auth(["ClaimsAdjuster"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    get_claim(claim_id)  # existence (priority 4)

    report_kind = require_enum(body, "report_kind", REPORT_KINDS)
    mtc = require_str(body, "maintenance_type_code")

    # MTC validity (priority 7) — must match report_kind.
    if report_kind == "FROI" and mtc not in FROI_MTCS:
        raise APIError(ERR_INVALID_MTC, 422, "FROI requires maintenance_type_code 00")
    if report_kind == "SROI" and mtc not in SROI_MTCS:
        raise APIError(ERR_INVALID_MTC, 422,
                       "SROI requires maintenance_type_code in {IP, CB, SX, FN}")

    rep = {
        "claim_id": claim_id,
        "report_kind": report_kind,
        "maintenance_type_code": mtc,
        "edi_status": "DRAFT",
        "rejection_code": None,
    }
    db.stamp_common(rep)
    db.injury_reports[rep["id"]] = rep
    return ok_object(rep, 201)


@bp.get("/injury-reports/<rid>")
def get_injury_report_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    return ok_object(get_injury_report(rid), 200)


@bp.get("/claims/<rid>/injury-reports")
def list_claim_injury_reports(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [r for r in db.injury_reports.values() if r["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/injury-reports/<rid>/transmit")
def transmit_report(rid):
    require_auth(["ClaimsAdjuster"])()
    rep = get_injury_report(rid)
    # State check (priority 5) before the FROI-before-SROI gate (priority 6).
    if rep["edi_status"] not in ("DRAFT", "REJECTED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot transmit a report in edi_status {rep['edi_status']}")
    if rep["report_kind"] == "SROI" and not _froi_acknowledged(rep["claim_id"]):
        raise APIError(ERR_FROI_NOT_ACKNOWLEDGED, 409,
                       "A FROI for this claim must be ACKNOWLEDGED before SROI transmit")
    rep["edi_status"] = "TRANSMITTED"
    db.bump(rep)
    return ok_object(rep, 200)


@bp.post("/injury-reports/<rid>/ack")
def ack_report(rid):
    require_auth(["PlatformAdmin"])()
    rep = get_injury_report(rid)
    if rep["edi_status"] != "TRANSMITTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot acknowledge a report in edi_status {rep['edi_status']}")
    rep["edi_status"] = "ACKNOWLEDGED"
    db.bump(rep)
    return ok_object(rep, 200)


@bp.post("/injury-reports/<rid>/reject")
def reject_report(rid):
    require_auth(["PlatformAdmin"])()
    rep = get_injury_report(rid)
    if rep["edi_status"] != "TRANSMITTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot reject a report in edi_status {rep['edi_status']}")
    body = get_json_body()
    rejection_code = require_str(body, "rejection_code")
    rep["edi_status"] = "REJECTED"
    rep["rejection_code"] = rejection_code
    db.bump(rep)
    return ok_object(rep, 200)
