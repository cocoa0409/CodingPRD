"""ICAAPDocument endpoints (PRD 3.8)."""

from __future__ import annotations

from flask import Blueprint

from db import icaap_documents, capital_plans, stamp_new, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_CROSS_BANK_REFERENCE, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_PLAN_NOT_FINAL, ERR_SECTION_MISSING,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_icaap, get_bank, get_icaap, bump_bank, REQUIRED_ICAAP_SECTIONS,
)
from util import (
    get_body, req_int, apply_filters, sorted_page,
    require_occ_field, check_occ_matches,
)

bp = Blueprint("icaap", __name__)


@bp.route("/banks/<bankId>/icaap-documents", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_icaap(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    document_year = req_int(body, "document_year")
    plan_id = body.get("governing_capital_plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: governing_capital_plan_id")
    sections = body.get("sections")
    if sections is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: sections")
    if not isinstance(sections, list):
        raise_err(ERR_INVALID_REQUEST, "sections must be an array")
    for entry in sections:
        if not isinstance(entry, dict) or not isinstance(entry.get("section_code"), str):
            raise_err(ERR_INVALID_REQUEST,
                      "Each section must be an object with a section_code string")
    # Cross-bank referential integrity (priority 4).
    plan = capital_plans.get(plan_id)
    if plan is None or plan["bank_id"] != bank["id"]:
        raise_err(ERR_CROSS_BANK_REFERENCE, "governing_capital_plan_id not owned by this bank")
    doc = {
        "bank_id": bank["id"],
        "document_year": document_year,
        "governing_capital_plan_id": plan["id"],
        "sections": sections,
        "board_attested_by_user_id": None,
        "prepared_by_user_id": _user_id,
        "status": "DRAFT",
    }
    stamp_new(doc)
    icaap_documents[doc["id"]] = doc
    return success_object(ser_icaap(doc), 201)


@bp.route("/banks/<bankId>/icaap-documents/<docId>", methods=["GET"])
@require_roles("Any")
def get_one_icaap(bankId: str, docId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_icaap(get_icaap(bank, docId)))


@bp.route("/banks/<bankId>/icaap-documents", methods=["GET"])
@require_roles("Any")
def list_icaap(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [d for d in icaap_documents.values() if d["bank_id"] == bank["id"]]
    items = apply_filters(items, {"status": "status", "document_year": "document_year"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_icaap(d) for d in page], limit, offset, total)


@bp.route("/banks/<bankId>/icaap-documents/<docId>/submit_review", methods=["POST"])
@require_roles("CapitalAnalyst")
def submit_review_icaap(bankId: str, docId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    doc = get_icaap(bank, docId)
    if doc["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT ICAAP can be submitted for review")
    # Plan finality (priority 15).
    plan = capital_plans.get(doc["governing_capital_plan_id"])
    if plan is None or plan["status"] not in ("APPROVED", "EFFECTIVE"):
        raise_err(ERR_PLAN_NOT_FINAL,
                  "Governing CapitalPlan must be APPROVED or EFFECTIVE at submit_review")
    # Section completeness (priority 16).
    present = {s.get("section_code") for s in doc["sections"] if isinstance(s, dict)}
    if not REQUIRED_ICAAP_SECTIONS.issubset(present):
        raise_err(ERR_SECTION_MISSING,
                  "ICAAP is missing one or more required sections")
    doc["status"] = "REVIEW"
    touch(doc)
    return success_object(ser_icaap(doc))


@bp.route("/banks/<bankId>/icaap-documents/<docId>/attest", methods=["POST"])
@require_roles("BoardApprover")
def attest_icaap(bankId: str, docId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    doc = get_icaap(bank, docId)
    if doc["status"] != "REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a REVIEW ICAAP can be attested")
    # Segregation of duties (priority 7).
    if doc.get("prepared_by_user_id") is not None and doc["prepared_by_user_id"] == _user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "Attester must differ from the preparer")
    doc["board_attested_by_user_id"] = _user_id
    doc["status"] = "ATTESTED"
    touch(doc)
    return success_object(ser_icaap(doc))


@bp.route("/banks/<bankId>/icaap-documents/<docId>/file", methods=["POST"])
@require_roles("CapitalAnalyst")
def file_icaap(bankId: str, docId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    doc = get_icaap(bank, docId)
    # Envelope-level: expected_bank_version presence/type (PRD 2.8 requires it).
    body = get_body()
    expected = require_occ_field(body)
    if doc["status"] != "ATTESTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ATTESTED ICAAP can be filed")
    # Plan finality (priority 15): governing plan must be EFFECTIVE at file time.
    plan = capital_plans.get(doc["governing_capital_plan_id"])
    if plan is None or plan["status"] != "EFFECTIVE":
        raise_err(ERR_PLAN_NOT_FINAL, "Governing CapitalPlan must be EFFECTIVE at file time")
    # OCC (priority 19).
    check_occ_matches(expected, bank)

    doc["status"] = "FILED"
    touch(doc)
    # Supersede every other document of this bank (prior FILED plus anything
    # still in DRAFT/REVIEW/ATTESTED) per PRD 3.8.
    for other in icaap_documents.values():
        if (other["bank_id"] == bank["id"] and other["id"] != doc["id"]
                and other["status"] in ("FILED", "DRAFT", "REVIEW", "ATTESTED")):
            other["status"] = "SUPERSEDED"
            touch(other)
    bump_bank(bank)
    return success_object(ser_icaap(doc))
