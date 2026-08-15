"""Fraud-bureau referral endpoints (PRD §3.6).

Filing is deadline-bound but never blocked by lateness by default: filed_at
strictly after deadline_at marks late_filing and lands the referral in
LATE_FILED, while the case still advances to REFERRED_TO_BUREAU. Strict mode
(enforce_bureau_deadline=true) rejects late filings — the last check evaluated.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_IN_REQUIRED_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_BUREAU_DEADLINE_PASSED,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_bureau
from util import (
    apply_filters,
    child_or_404,
    get_json_body,
    optional_bool,
    page_of,
    parse_pagination,
    path_or_404,
    require_string,
    require_version,
    sort_created,
)

bp = Blueprint("bureau", __name__)

MGR = ("SIUManager",)
LIST_READERS = ("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
ITEM_READERS = ("SIUManager", "SIUComplianceOfficer")


def _resolve(caseId: str, referralId: str = None):
    case = path_or_404(db.cases, caseId, "SIUCase")
    referral = None
    if referralId is not None:
        referral = child_or_404(db.bureau_referrals, referralId, "case_id", case["id"], "FraudBureauReferral")
    return case, referral


@bp.get("/siu/cases/<caseId>/bureau-referrals")
@require_roles(*LIST_READERS)
def list_case_bureau_referrals(caseId: str, _user_id: str, _role: str):
    case, _ = _resolve(caseId)
    limit, offset = parse_pagination()
    items = sort_created([r for r in db.bureau_referrals.values() if r.get("case_id") == case["id"]])
    page, total = page_of(items, limit, offset)
    return success_list([pub_bureau(r) for r in page], limit, offset, total)


@bp.get("/siu/bureau-referrals")
@require_roles(*LIST_READERS)
def list_all_bureau_referrals(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.bureau_referrals.values()), ["case_id", "status", "state_code"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_bureau(r) for r in page], limit, offset, total)


@bp.get("/siu/bureau-referrals/<referralId>")
@require_roles(*ITEM_READERS)
def get_bureau_referral(referralId: str, _user_id: str, _role: str):
    referral = path_or_404(db.bureau_referrals, referralId, "FraudBureauReferral")
    return success_object(pub_bureau(referral))


@bp.get("/siu/cases/<caseId>/bureau-referrals/<referralId>")
@require_roles(*ITEM_READERS)
def get_case_bureau_referral(caseId: str, referralId: str, _user_id: str, _role: str):
    _, referral = _resolve(caseId, referralId)
    return success_object(pub_bureau(referral))


@bp.post("/siu/cases/<caseId>/bureau-referrals/<referralId>/file")
@require_roles("SIUManager")
def file_bureau_referral(caseId: str, referralId: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_referral_version = require_version(body, "expected_referral_version")
    enforce_deadline = optional_bool(body, "enforce_bureau_deadline", False)
    case, referral = _resolve(caseId, referralId)
    # Rung 5: the referral itself must be DRAFT.
    if referral.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Bureau referral must be DRAFT to be filed")
    # Rung 6: the parent case must be CLOSED_SUBSTANTIATED.
    if case.get("status") != "CLOSED_SUBSTANTIATED":
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "Case must be CLOSED_SUBSTANTIATED to file")
    # Rung 8: optimistic concurrency on the referral.
    if expected_referral_version != int(referral.get("version", 0)):
        raise_err(ERR_STALE_VERSION, "expected_referral_version does not match the referral version")

    now = db.clock.now
    deadline = db.parse_instant(referral.get("deadline_at"))
    late = deadline is not None and now > deadline

    # Rung 9 (last): strict-mode deadline enforcement.
    if enforce_deadline and late:
        raise_err(ERR_BUREAU_DEADLINE_PASSED, "Bureau filing deadline has passed")

    referral["filed_at"] = db.clock.now_string()
    referral["late_filing"] = bool(late)
    referral["status"] = "LATE_FILED" if late else "FILED"
    referral["_filed_by_user_id"] = _user_id
    db.touch(referral)
    # Lateness never blocks the case transition.
    case["status"] = "REFERRED_TO_BUREAU"
    db.touch(case)
    return success_object(pub_bureau(referral))


@bp.post("/siu/cases/<caseId>/bureau-referrals/<referralId>/acknowledge")
@require_roles("SIUManager")
def acknowledge_bureau_referral(caseId: str, referralId: str, _user_id: str, _role: str):
    get_json_body()
    _, referral = _resolve(caseId, referralId)
    if referral.get("status") != "FILED":
        raise_err(ERR_INVALID_STATE, "Bureau referral must be FILED to be acknowledged")
    # Segregation of duties: the acking manager must differ from the filer.
    if referral.get("_filed_by_user_id") is not None and str(referral.get("_filed_by_user_id")) == str(_user_id):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The acknowledging manager must differ from the filing manager")
    referral["status"] = "ACKNOWLEDGED"
    referral["ack_received_at"] = db.clock.now_string()
    db.touch(referral)
    return success_object(pub_bureau(referral))


@bp.post("/siu/cases/<caseId>/bureau-referrals/<referralId>/reject")
@require_roles("SIUManager")
def reject_bureau_referral(caseId: str, referralId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    _, referral = _resolve(caseId, referralId)
    if referral.get("status") != "FILED":
        raise_err(ERR_INVALID_STATE, "Bureau referral must be FILED to be rejected")
    referral["status"] = "REJECTED_BY_BUREAU"
    db.touch(referral)
    return success_object(pub_bureau(referral))
