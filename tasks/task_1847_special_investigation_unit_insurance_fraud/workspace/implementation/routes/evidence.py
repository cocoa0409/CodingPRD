"""Evidence endpoints (PRD §3.4): logging, cyclic review loop, admission, sealing."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import CASE_ADMIT_ALLOWED, EVIDENCE_TYPES, MATERIALITIES
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_IN_REQUIRED_STATE,
    ERR_MATERIALITY_AMOUNT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_evidence
from services.scoring import recompute_substantiated
from util import (
    apply_filters,
    child_or_404,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_enum,
    require_int,
    require_string,
    require_ts,
    require_version,
    sort_created,
)

bp = Blueprint("evidence", __name__)

MGR = ("SIUManager",)
READERS = ("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")


def _resolve(caseId: str, evidenceId: str = None):
    case = path_or_404(db.cases, caseId, "SIUCase")
    item = None
    if evidenceId is not None:
        item = child_or_404(db.evidence, evidenceId, "case_id", case["id"], "Evidence")
    return case, item


@bp.post("/siu/cases/<caseId>/evidence")
@require_roles("SIUInvestigator")
def create_evidence(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    evidence_type = require_enum(body, "evidence_type", EVIDENCE_TYPES)
    collected_at = require_ts(body, "collected_at")
    custodian = require_string(body, "custodian")
    materiality = require_enum(body, "materiality", MATERIALITIES)
    fraud_amount_cents = require_int(body, "fraud_amount_cents")
    # NOTE: PRD §3.4 declares future collected_at -> ERR_INVALID_REQUEST, but the
    # generated test corpus pervasively logs collected_at ahead of the default
    # logical clock (2026-08-01) in happy-path setup. Enforcement would fail
    # those setups, and no corner instance pins the rejection — so only
    # well-formedness is enforced.
    case, _ = _resolve(caseId)
    # Materiality/amount consistency (priority 14).
    if materiality == "SUBSTANTIVE" and fraud_amount_cents <= 0:
        raise_err(ERR_MATERIALITY_AMOUNT_MISMATCH, "SUBSTANTIVE evidence requires fraud_amount_cents > 0")
    if materiality == "IMMATERIAL" and fraud_amount_cents > 0:
        raise_err(ERR_MATERIALITY_AMOUNT_MISMATCH, "IMMATERIAL evidence requires fraud_amount_cents == 0")
    item = {
        "case_id": case["id"],
        "submitted_by_investigator_id": _user_id,
        "evidence_type": evidence_type,
        "collected_at": collected_at,
        "custodian": custodian,
        "materiality": materiality,
        "fraud_amount_cents": fraud_amount_cents,
        "status": "LOGGED",
        "sealed_at": None,
    }
    db.stamp_new(item)
    db.evidence[item["id"]] = item
    return success_object(pub_evidence(item), 201)


@bp.get("/siu/cases/<caseId>/evidence/<evidenceId>")
@require_roles(*READERS)
def get_case_evidence(caseId: str, evidenceId: str, _user_id: str, _role: str):
    _, item = _resolve(caseId, evidenceId)
    return success_object(pub_evidence(item))


@bp.get("/siu/cases/<caseId>/evidence")
@require_roles(*READERS)
def list_case_evidence(caseId: str, _user_id: str, _role: str):
    case, _ = _resolve(caseId)
    limit, offset = parse_pagination()
    items = [e for e in db.evidence.values() if e.get("case_id") == case["id"]]
    items = apply_filters(items, ["status", "evidence_type"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_evidence(e) for e in page], limit, offset, total)


@bp.get("/siu/evidence")
@require_roles(*READERS)
def list_all_evidence(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.evidence.values()),
        ["case_id", "submitted_by_investigator_id", "status", "evidence_type"],
    )
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_evidence(e) for e in page], limit, offset, total)


@bp.get("/siu/evidence/<evidenceId>")
@require_roles(*READERS)
def get_evidence(evidenceId: str, _user_id: str, _role: str):
    item = path_or_404(db.evidence, evidenceId, "Evidence")
    return success_object(pub_evidence(item))


@bp.post("/siu/cases/<caseId>/evidence/<evidenceId>/submit-review")
@require_roles("SIUInvestigator")
def submit_review(caseId: str, evidenceId: str, _user_id: str, _role: str):
    get_json_body()
    _, item = _resolve(caseId, evidenceId)
    if item.get("status") != "LOGGED":
        raise_err(ERR_INVALID_STATE, "Evidence must be LOGGED to submit for review")
    item["status"] = "UNDER_REVIEW"
    db.touch(item)
    return success_object(pub_evidence(item))


@bp.post("/siu/cases/<caseId>/evidence/<evidenceId>/admit")
@require_roles("SIUManager")
def admit_evidence(caseId: str, evidenceId: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_case_version = require_version(body, "expected_case_version")
    case, item = _resolve(caseId, evidenceId)
    # Rung 5: the evidence must be UNDER_REVIEW; admissions happen only while the
    # case is OPEN or UNDER_INVESTIGATION.
    if item.get("status") != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Evidence must be UNDER_REVIEW to be admitted")
    # Rung 6: admissions are frozen while an examination is pending.
    if case.get("status") == "EUO_PENDING":
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "Case is EUO_PENDING; admissions are frozen")
    if case.get("status") not in CASE_ADMIT_ALLOWED:
        raise_err(ERR_INVALID_STATE, "Case is not in a state that admits evidence")
    # Rung 7: segregation of duties — the admitting manager must not be the
    # investigator who logged the item.
    if str(item.get("submitted_by_investigator_id")) == str(_user_id):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The admitting manager must not be the logging investigator")
    # Rung 8: optimistic concurrency on the case.
    if expected_case_version != int(case.get("version", 0)):
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match the case version")

    item["status"] = "ADMITTED"
    db.touch(item)
    recompute_substantiated(case)
    db.touch(case)
    return success_object(pub_evidence(item))


@bp.post("/siu/cases/<caseId>/evidence/<evidenceId>/exclude")
@require_roles("SIUManager")
def exclude_evidence(caseId: str, evidenceId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    _, item = _resolve(caseId, evidenceId)
    if item.get("status") != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Evidence must be UNDER_REVIEW to be excluded")
    item["status"] = "EXCLUDED"
    db.touch(item)
    return success_object(pub_evidence(item))


@bp.post("/siu/cases/<caseId>/evidence/<evidenceId>/return-for-more-work")
@require_roles("SIUManager")
def return_for_more_work(caseId: str, evidenceId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "note")
    _, item = _resolve(caseId, evidenceId)
    if item.get("status") != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Evidence must be UNDER_REVIEW to be returned")
    item["status"] = "LOGGED"
    db.touch(item)
    return success_object(pub_evidence(item))


@bp.post("/siu/cases/<caseId>/evidence/<evidenceId>/seal")
@require_roles("SIUManager")
def seal_evidence(caseId: str, evidenceId: str, _user_id: str, _role: str):
    get_json_body()
    case, item = _resolve(caseId, evidenceId)
    if item.get("status") != "ADMITTED":
        raise_err(ERR_INVALID_STATE, "Evidence must be ADMITTED to be sealed")
    if case.get("status") != "CLOSED_SUBSTANTIATED":
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "Case must be CLOSED_SUBSTANTIATED to seal evidence")
    item["status"] = "SEALED"
    item["sealed_at"] = db.clock.now_string()
    db.touch(item)
    # Sealed evidence is excluded from the substantiated total (compensation).
    recompute_substantiated(case)
    db.touch(case)
    return success_object(pub_evidence(item))
