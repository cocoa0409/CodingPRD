"""ForensicReview, DemandLetter, PreservationNotice, EvidenceItem routes
(PRD §3.6, §3.7, §3.8)."""

import re

from flask import Blueprint, request

from db import (
    add_days,
    all_rows,
    by_id,
    created_asc,
    db,
    new_record,
    now,
    serialize,
    stamp,
    touch,
)
from errors import (
    err_invalid_hash,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_preservation,
    err_review_window_expired,
    err_sod,
    err_unauthorized_role,
)
from middleware import actor, body, require_enum, require_field, require_int, require_roles, require_str
from response import ok_list, ok_object, paginate
from services import (
    CLAIM_FACTOR,
    REVIEW_WINDOW_DAYS,
    demand_letter_damages,
    recompute_counterparty_exposure,
)

bp = Blueprint("legal", __name__)

TRIGGER_REASONS = ("VOLUNTARY_DEPARTURE", "INVOLUNTARY_DEPARTURE", "POLICY", "LITIGATION")
REVIEW_STATUSES = (
    "OPENED",
    "IMAGING",
    "FINDINGS_DRAFTED",
    "COUNSEL_REVIEW",
    "CLOSED_NO_ACTION",
    "ESCALATED",
)
CLAIM_TYPES = ("CEASE_AND_DESIST", "RETURN_OF_PROPERTY", "PRESERVATION")
LETTER_STATUSES = (
    "DRAFTED",
    "COUNSEL_APPROVED",
    "ISSUED",
    "ACKNOWLEDGED",
    "COMPLIED",
    "IGNORED",
    "LITIGATION",
    "WITHDRAWN",
)
NOTICE_STATUSES = ("DRAFT", "ISSUED", "ACTIVE", "RELEASED")
EVIDENCE_SOURCES = ("FORENSIC_IMAGE", "EMAIL_EXPORT", "ACCESS_LOG", "DEVICE_IMAGE", "MARKED_COPY")
EVIDENCE_STATUSES = ("COLLECTED", "SEALED", "RELEASED")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _paginate_list(store_name, filters):
    rows = []
    for r in created_asc(all_rows(store_name)):
        if all(r.get(k) == v for k, v in filters):
            rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# ForensicReview
# ---------------------------------------------------------------------------
@bp.post("/api/forensic-reviews")
def create_review():
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel")
    data = body()
    employee_id = require_str(data, "employee_id")
    emp = by_id("employees", employee_id)
    if emp is None:
        raise err_not_found("employee not found")
    trigger = require_enum(data, "trigger_reason", TRIGGER_REASONS)
    # Manual open: ACTIVE/NOTICE, or DEPARTED within the 90-day window (§3.6).
    if emp["status"] == "DEPARTED":
        departed_dt = emp.get("_departed_at_dt")
        if departed_dt is not None and now() > add_days(departed_dt, REVIEW_WINDOW_DAYS):
            raise err_review_window_expired()
    elif emp["status"] not in ("ACTIVE", "NOTICE"):
        raise err_invalid_state("Employee must be ACTIVE, NOTICE, or recently DEPARTED")
    rec = new_record(
        "forensic_reviews",
        {
            "employee_id": employee_id,
            "trigger_reason": trigger,
            "status": "OPENED",
            "exfil_indicator_count": 0,
            "findings_notes": "",
            "reviewed_by_counsel_id": None,
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/forensic-reviews")
def list_reviews():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "SecurityOfficer", "HRPartner")
    filters = [(f, request.args[f]) for f in ("employee_id", "status", "trigger_reason") if f in request.args]
    return _paginate_list("forensic_reviews", filters)


@bp.get("/api/forensic-reviews/<rid>")
def get_review(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "SecurityOfficer", "HRPartner")
    r = by_id("forensic_reviews", rid)
    if r is None:
        raise err_not_found("forensic review not found")
    return ok_object(serialize(r))


@bp.patch("/api/forensic-reviews/<rid>")
def patch_review(rid):
    """Findings fields are recorded while IMAGING or FINDINGS_DRAFTED."""
    _uid, role = actor()
    require_roles(role, "SecurityOfficer")
    r = by_id("forensic_reviews", rid)
    if r is None:
        raise err_not_found("forensic review not found")
    if r["status"] not in ("IMAGING", "FINDINGS_DRAFTED"):
        raise err_invalid_state("Findings may be recorded only while IMAGING or FINDINGS_DRAFTED")
    data = body()
    if "exfil_indicator_count" in data and data["exfil_indicator_count"] is not None:
        val = data["exfil_indicator_count"]
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise err_invalid_request("exfil_indicator_count must be a non-negative integer")
        r["exfil_indicator_count"] = val
    if "findings_notes" in data and data["findings_notes"] is not None:
        if not isinstance(data["findings_notes"], str):
            raise err_invalid_request("findings_notes must be a string")
        r["findings_notes"] = data["findings_notes"]
    touch(r)
    return ok_object(serialize(r))


@bp.post("/api/forensic-reviews/<rid>/state")
def review_state(rid):
    user_id, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    r = by_id("forensic_reviews", rid)
    if r is None:
        raise err_not_found("forensic review not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in REVIEW_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(REVIEW_STATUSES)}")
    cur = r["status"]

    if to_status == "IMAGING":
        if role != "SecurityOfficer":
            raise err_unauthorized_role("IMAGING requires SecurityOfficer")
        if cur != "OPENED":
            raise err_invalid_state(f"Cannot move review from {cur} to IMAGING")
        r["status"] = "IMAGING"
        touch(r)
    elif to_status == "FINDINGS_DRAFTED":
        if cur == "IMAGING":
            if role != "SecurityOfficer":
                raise err_unauthorized_role("FINDINGS_DRAFTED from IMAGING requires SecurityOfficer")
            has_evidence = any(
                e["review_id"] == r["id"] and e["status"] in ("COLLECTED", "SEALED")
                for e in all_rows("evidence_items")
            )
            if not has_evidence:
                raise err_invalid_state("FINDINGS_DRAFTED requires at least one collected/sealed evidence item")
        elif cur == "COUNSEL_REVIEW":
            if role != "IPCounsel":
                raise err_unauthorized_role("Counsel kickback requires IPCounsel")
        else:
            raise err_invalid_state(f"Cannot move review from {cur} to FINDINGS_DRAFTED")
        r["status"] = "FINDINGS_DRAFTED"
        touch(r)
    elif to_status == "COUNSEL_REVIEW":
        if role != "IPCounsel":
            raise err_unauthorized_role("COUNSEL_REVIEW requires IPCounsel")
        if cur != "FINDINGS_DRAFTED":
            raise err_invalid_state(f"Cannot move review from {cur} to COUNSEL_REVIEW")
        r["status"] = "COUNSEL_REVIEW"
        r["reviewed_by_counsel_id"] = user_id
        touch(r)
    elif to_status == "CLOSED_NO_ACTION":
        if role != "IPCounsel":
            raise err_unauthorized_role("CLOSED_NO_ACTION requires IPCounsel")
        if cur != "COUNSEL_REVIEW":
            raise err_invalid_state(f"Cannot move review from {cur} to CLOSED_NO_ACTION")
        r["status"] = "CLOSED_NO_ACTION"
        touch(r)
    elif to_status == "ESCALATED":
        if role != "IPCounsel":
            raise err_unauthorized_role("ESCALATED requires IPCounsel")
        if cur != "COUNSEL_REVIEW":
            raise err_invalid_state(f"Cannot move review from {cur} to ESCALATED")
        if r["exfil_indicator_count"] < 1:
            raise err_invalid_state("Nothing to escalate: exfil_indicator_count is 0")
        r["status"] = "ESCALATED"
        touch(r)
    else:  # OPENED is never a manual target
        raise err_invalid_state(f"Cannot move review from {cur} to {to_status}")
    return ok_object(serialize(r))


# ---------------------------------------------------------------------------
# DemandLetter
# ---------------------------------------------------------------------------
@bp.post("/api/demand-letters")
def create_letter():
    user_id, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    review_id = require_str(data, "forensic_review_id")
    review = by_id("forensic_reviews", review_id)
    if review is None:
        raise err_not_found("forensic review not found")
    claim_lines = data.get("claim_lines")
    if not isinstance(claim_lines, list) or len(claim_lines) == 0:
        raise err_invalid_request("claim_lines must be a non-empty array")
    normalized = []
    for line in claim_lines:
        if not isinstance(line, dict):
            raise err_invalid_request("each claim line must be an object")
        asset_id = line.get("asset_id")
        if not asset_id:
            raise err_invalid_request("each claim line needs an asset_id")
        asset = by_id("assets", asset_id)
        if asset is None:
            raise err_not_found("claim line asset not found")
        claim_type = line.get("claim_type")
        if claim_type not in CLAIM_TYPES:
            raise err_invalid_request(f"claim_type must be one of {list(CLAIM_TYPES)}")
        normalized.append({"asset_id": asset_id, "claim_type": claim_type})
    # Referenced-entity state gate: the source review must be ESCALATED.
    if review["status"] != "ESCALATED":
        raise err_invalid_state("Demand letters require an ESCALATED forensic review")
    days = require_int(data, "response_deadline_days")
    if days <= 0:
        raise err_invalid_request("response_deadline_days must be > 0")
    damages = demand_letter_damages(normalized)
    rec = new_record(
        "demand_letters",
        {
            "forensic_review_id": review_id,
            "employee_id": review["employee_id"],
            "claim_lines": normalized,
            "response_deadline_days": days,
            "damages_estimate_cents": damages,
            "drafted_by_user_id": user_id,
            "approved_by_user_id": None,
            "issued_at": None,
            "response_deadline": None,
            "_response_deadline_dt": None,
            "status": "DRAFTED",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/demand-letters")
def list_letters():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    filters = [(f, request.args[f]) for f in ("forensic_review_id", "employee_id", "status") if f in request.args]
    return _paginate_list("demand_letters", filters)


@bp.get("/api/demand-letters/<rid>")
def get_letter(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    letter = by_id("demand_letters", rid)
    if letter is None:
        raise err_not_found("demand letter not found")
    return ok_object(serialize(letter))


@bp.post("/api/demand-letters/<rid>/state")
def letter_state(rid):
    user_id, role = actor()
    require_roles(role, "SeniorCounsel", "IPCounsel")
    letter = by_id("demand_letters", rid)
    if letter is None:
        raise err_not_found("demand letter not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in LETTER_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(LETTER_STATUSES)}")
    cur = letter["status"]

    if to_status == "COUNSEL_APPROVED":
        if role != "SeniorCounsel":
            raise err_unauthorized_role("COUNSEL_APPROVED requires SeniorCounsel")
        if user_id == letter["drafted_by_user_id"]:
            raise err_sod("The letter drafter may not approve it")
        if cur != "DRAFTED":
            raise err_invalid_state(f"Cannot move letter from {cur} to COUNSEL_APPROVED")
        letter["status"] = "COUNSEL_APPROVED"
        letter["approved_by_user_id"] = user_id
        touch(letter)
    elif to_status == "ISSUED":
        if role != "SeniorCounsel":
            raise err_unauthorized_role("ISSUED requires SeniorCounsel")
        if cur != "COUNSEL_APPROVED":
            raise err_invalid_state(f"Cannot move letter from {cur} to ISSUED")
        letter["status"] = "ISSUED"
        stamp(letter, "issued_at")
        deadline = add_days(now(), letter["response_deadline_days"])
        from db import fmt_ts

        letter["response_deadline"] = fmt_ts(deadline)
        letter["_response_deadline_dt"] = deadline
        touch(letter)
    elif to_status == "ACKNOWLEDGED":
        if role != "IPCounsel":
            raise err_unauthorized_role("ACKNOWLEDGED requires IPCounsel")
        if cur != "ISSUED":
            raise err_invalid_state(f"Cannot move letter from {cur} to ACKNOWLEDGED")
        letter["status"] = "ACKNOWLEDGED"
        touch(letter)
    elif to_status == "COMPLIED":
        if role != "IPCounsel":
            raise err_unauthorized_role("COMPLIED requires IPCounsel")
        if cur != "ACKNOWLEDGED":
            raise err_invalid_state(f"Cannot move letter from {cur} to COMPLIED")
        letter["status"] = "COMPLIED"
        touch(letter)
    elif to_status == "LITIGATION":
        if role != "SeniorCounsel":
            raise err_unauthorized_role("LITIGATION requires SeniorCounsel")
        if cur != "IGNORED":
            raise err_invalid_state(f"Cannot move letter from {cur} to LITIGATION")
        letter["status"] = "LITIGATION"
        touch(letter)
        # Auto-create the preservation notice directly in ISSUED (§3.7).
        asset_ids = []
        for line in letter["claim_lines"]:
            if line["asset_id"] not in asset_ids:
                asset_ids.append(line["asset_id"])
        new_record(
            "preservation_notices",
            {
                "legal_matter_ref": "AUTO:" + letter["id"],
                "asset_ids": asset_ids,
                "employee_ids": [letter["employee_id"]],
                "review_ids": [letter["forensic_review_id"]],
                "status": "ISSUED",
            },
        )
    elif to_status == "WITHDRAWN":
        if role != "IPCounsel":
            raise err_unauthorized_role("WITHDRAWN requires IPCounsel")
        if cur not in ("DRAFTED", "COUNSEL_APPROVED"):
            raise err_invalid_state(f"Cannot move letter from {cur} to WITHDRAWN")
        letter["status"] = "WITHDRAWN"
        touch(letter)
    else:  # IGNORED is sweep-only
        raise err_invalid_state(f"Cannot move letter from {cur} to {to_status}")
    return ok_object(serialize(letter))


# ---------------------------------------------------------------------------
# PreservationNotice
# ---------------------------------------------------------------------------
@bp.post("/api/preservation-notices")
def create_notice():
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    ref = require_str(data, "legal_matter_ref")
    asset_ids = _opt_id_list(data, "asset_ids")
    employee_ids = _opt_id_list(data, "employee_ids")
    review_ids = _opt_id_list(data, "review_ids")
    for aid in asset_ids:
        if by_id("assets", aid) is None:
            raise err_not_found("asset in asset_ids not found")
    for eid in employee_ids:
        if by_id("employees", eid) is None:
            raise err_not_found("employee in employee_ids not found")
    for rvid in review_ids:
        if by_id("forensic_reviews", rvid) is None:
            raise err_not_found("review in review_ids not found")
    rec = new_record(
        "preservation_notices",
        {
            "legal_matter_ref": ref,
            "asset_ids": asset_ids,
            "employee_ids": employee_ids,
            "review_ids": review_ids,
            "status": "DRAFT",
        },
    )
    return ok_object(serialize(rec), code=201)


def _opt_id_list(data, field):
    val = data.get(field)
    if val is None:
        return []
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise err_invalid_request(f"{field} must be an array of ids")
    return val


@bp.get("/api/preservation-notices")
def list_notices():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    filters = [("status", request.args["status"])] if "status" in request.args else []
    return _paginate_list("preservation_notices", filters)


@bp.get("/api/preservation-notices/<rid>")
def get_notice(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    n = by_id("preservation_notices", rid)
    if n is None:
        raise err_not_found("preservation notice not found")
    return ok_object(serialize(n))


@bp.post("/api/preservation-notices/<rid>/state")
def notice_state(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    n = by_id("preservation_notices", rid)
    if n is None:
        raise err_not_found("preservation notice not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in NOTICE_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(NOTICE_STATUSES)}")
    cur = n["status"]

    if to_status == "ISSUED":
        if role != "IPCounsel":
            raise err_unauthorized_role("ISSUED requires IPCounsel")
        if cur != "DRAFT":
            raise err_invalid_state(f"Cannot move notice from {cur} to ISSUED")
        if not (n["asset_ids"] or n["employee_ids"] or n["review_ids"]):
            raise err_invalid_request("At least one scope array must be non-empty")
        n["status"] = "ISSUED"
        touch(n)
    elif to_status == "ACTIVE":
        if role != "IPCounsel":
            raise err_unauthorized_role("ACTIVE requires IPCounsel")
        if cur != "ISSUED":
            raise err_invalid_state(f"Cannot move notice from {cur} to ACTIVE")
        n["status"] = "ACTIVE"
        touch(n)
    elif to_status == "RELEASED":
        if role != "SeniorCounsel":
            raise err_unauthorized_role("RELEASED requires SeniorCounsel")
        if cur != "ACTIVE":
            raise err_invalid_state(f"Cannot move notice from {cur} to RELEASED")
        review_ids = set(n["review_ids"] or [])
        for letter in all_rows("demand_letters"):
            if letter["status"] == "LITIGATION" and letter["forensic_review_id"] in review_ids:
                raise err_invalid_state(
                    "A demand letter in LITIGATION references a covered review"
                )
        n["status"] = "RELEASED"
        touch(n)
    else:  # DRAFT is never a manual target
        raise err_invalid_state(f"Cannot move notice from {cur} to {to_status}")
    return ok_object(serialize(n))


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------
@bp.post("/api/evidence-items")
def create_evidence():
    _uid, role = actor()
    require_roles(role, "SecurityOfficer")
    data = body()
    # Exactly one owner pointer: review_id is the accepted input; disclosure_id
    # is set only by the disclosure-execution cascade (PRD §3.8).
    if data.get("disclosure_id") is not None:
        raise err_invalid_request("disclosure_id is never accepted as input")
    review_id = require_str(data, "review_id")
    review = by_id("forensic_reviews", review_id)
    if review is None:
        raise err_not_found("forensic review not found")
    source = require_enum(data, "source", EVIDENCE_SOURCES)
    sha = require_str(data, "sha256")
    size = require_int(data, "byte_size")
    if not SHA256_RE.match(sha):
        raise err_invalid_hash()
    if size < 0:
        raise err_invalid_request("byte_size must be >= 0")
    rec = new_record(
        "evidence_items",
        {
            "review_id": review_id,
            "disclosure_id": None,
            "source": source,
            "sha256": sha,
            "byte_size": size,
            "sealed_at": None,
            "status": "COLLECTED",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/evidence-items")
def list_evidence():
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel", "SeniorCounsel")
    filters = [(f, request.args[f]) for f in ("review_id", "disclosure_id", "status") if f in request.args]
    return _paginate_list("evidence_items", filters)


@bp.get("/api/evidence-items/<rid>")
def get_evidence(rid):
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel", "SeniorCounsel")
    e = by_id("evidence_items", rid)
    if e is None:
        raise err_not_found("evidence item not found")
    return ok_object(serialize(e))


@bp.post("/api/evidence-items/<rid>/state")
def evidence_state(rid):
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    e = by_id("evidence_items", rid)
    if e is None:
        raise err_not_found("evidence item not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in EVIDENCE_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(EVIDENCE_STATUSES)}")
    cur = e["status"]

    if to_status == "SEALED":
        if role != "SecurityOfficer":
            raise err_unauthorized_role("SEALED requires SecurityOfficer")
        if cur != "COLLECTED":
            raise err_invalid_state(f"Cannot move evidence from {cur} to SEALED")
        e["status"] = "SEALED"
        stamp(e, "sealed_at")
        touch(e)
    elif to_status == "RELEASED":
        if role != "IPCounsel":
            raise err_unauthorized_role("RELEASED requires IPCounsel")
        if cur != "SEALED":
            raise err_invalid_state(f"Cannot move evidence from {cur} to RELEASED")
        if e["review_id"] is not None:
            for n in all_rows("preservation_notices"):
                if n["status"] in ("ISSUED", "ACTIVE") and e["review_id"] in (n["review_ids"] or []):
                    raise err_preservation()
        e["status"] = "RELEASED"
        touch(e)
    else:  # COLLECTED is never a manual target
        raise err_invalid_state(f"Cannot move evidence from {cur} to {to_status}")
    return ok_object(serialize(e))
