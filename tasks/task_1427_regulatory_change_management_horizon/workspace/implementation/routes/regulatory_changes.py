"""Regulatory change ingestion, triage, retriage (PRD §3.1)."""

from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import (ERR_CHANGE_NOT_SUPERSEDABLE, ApiError, invalid_state,
                    sod_violation)
from middleware import (auth_context, get_body, get_or_404, opt_dt, opt_str,
                        req_dt, req_enum, req_str, require_roles)
from response import paginate, success_object
from serializers import created_sorted, regulatory_change_to_api
from services.audit import append_audit
from services.calculations import provisional_risk_tier

bp = Blueprint("regulatory_changes", __name__)

FEED_SOURCES = ("FED_REGISTER", "STATE_BULLETIN", "INT_JOURNAL", "MANUAL_ENTRY")
SEVERITY_HINTS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
VERDICTS = ("APPLICABLE", "NOT_APPLICABLE")


@bp.post("/compliance/regulatory-changes")
def create_change():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    citation = req_str(body, "citation")
    title = req_str(body, "title")
    summary = req_str(body, "summary")
    feed_source = req_enum(body, "feed_source", FEED_SOURCES)
    jurisdiction = req_str(body, "jurisdiction")
    regulator = req_str(body, "regulator")
    published_at = req_dt(body, "published_at")
    effective_date = req_dt(body, "effective_date")
    comment_deadline = opt_dt(body, "comment_deadline")
    severity_hint = req_enum(body, "severity_hint", SEVERITY_HINTS)
    supersedes_change_id = opt_str(body, "supersedes_change_id")

    # Priority 3: body FK existence.
    target = None
    if supersedes_change_id is not None:
        target = get_or_404(store.regulatory_changes, supersedes_change_id,
                            "superseded regulatory change")

    # Priority 4: supersession state precondition on the target.
    if target is not None and target["status"] not in (
            "PENDING_TRIAGE", "TRIAGED_NOT_APPLICABLE"):
        raise ApiError(ERR_CHANGE_NOT_SUPERSEDABLE, 409,
                       "supersedes_change_id targets a change not in "
                       "PENDING_TRIAGE or TRIAGED_NOT_APPLICABLE")

    change = stamp_new({
        "id": new_id(),
        "citation": citation,
        "title": title,
        "summary": summary,
        "feed_source": feed_source,
        "jurisdiction": jurisdiction,
        "regulator": regulator,
        "published_at": published_at,
        "effective_date": effective_date,
        "comment_deadline": comment_deadline,
        "severity_hint": severity_hint,
        "supersedes_change_id": supersedes_change_id,
        "superseded_by_id": None,
        "status": "PENDING_TRIAGE",
        "applicability": "UNDETERMINED",
        "triage_rationale": None,
        "triage_round": 0,
        "provisional_risk_tier": None,
        "risk_tier": None,
        "business_owner_id": None,
        "created_by_user_id": user_id,
        "triaged_by_user_id": None,
    })
    store.regulatory_changes[change["id"]] = change

    if target is not None:
        target["status"] = "SUPERSEDED"
        target["superseded_by_id"] = change["id"]
        touch(target)

    append_audit(user_id, role, "POST /compliance/regulatory-changes",
                 "RegulatoryChange", change["id"])
    return success_object(regulatory_change_to_api(change), status=201)


@bp.get("/compliance/regulatory-changes")
def list_changes():
    auth_context()
    items = created_sorted(store.regulatory_changes.values())
    filters = (
        ("status", "status"),
        ("jurisdiction", "jurisdiction"),
        ("severity_hint", "severity_hint"),
        ("business_owner_id", "business_owner_id"),
        ("supersedes_change_id", "supersedes_change_id"),
        ("superseded_by_id", "superseded_by_id"),
    )
    for param, field in filters:
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[field] == value]
    return paginate(items, regulatory_change_to_api)


@bp.get("/compliance/regulatory-changes/<change_id>")
def get_change(change_id):
    auth_context()
    change = get_or_404(store.regulatory_changes, change_id, "regulatory change")
    return success_object(regulatory_change_to_api(change))


@bp.post("/compliance/regulatory-changes/<change_id>/triage")
def triage_change(change_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    verdict = req_enum(body, "verdict", VERDICTS)
    rationale = req_str(body, "rationale")

    change = get_or_404(store.regulatory_changes, change_id, "regulatory change")
    if change["status"] != "PENDING_TRIAGE":
        raise invalid_state("triage requires status PENDING_TRIAGE")
    if user_id == change["created_by_user_id"]:
        raise sod_violation()

    change["status"] = ("TRIAGED_APPLICABLE" if verdict == "APPLICABLE"
                        else "TRIAGED_NOT_APPLICABLE")
    change["applicability"] = verdict
    change["triage_rationale"] = rationale
    change["triage_round"] += 1
    change["triaged_by_user_id"] = user_id
    change["provisional_risk_tier"] = provisional_risk_tier(change["severity_hint"])
    touch(change)
    append_audit(user_id, role,
                 "POST /compliance/regulatory-changes/{id}/triage",
                 "RegulatoryChange", change["id"])
    return success_object(regulatory_change_to_api(change))


@bp.post("/compliance/regulatory-changes/<change_id>/retriage")
def retriage_change(change_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    rationale = req_str(body, "rationale")

    change = get_or_404(store.regulatory_changes, change_id, "regulatory change")
    if change["status"] != "TRIAGED_NOT_APPLICABLE":
        raise invalid_state("retriage requires status TRIAGED_NOT_APPLICABLE")
    if user_id == change["created_by_user_id"]:
        raise sod_violation()

    change["status"] = "PENDING_TRIAGE"
    change["applicability"] = "UNDETERMINED"
    change["triage_rationale"] = rationale
    # triage_round is NOT advanced; triaged_by_user_id is left unchanged.
    touch(change)
    append_audit(user_id, role,
                 "POST /compliance/regulatory-changes/{id}/retriage",
                 "RegulatoryChange", change["id"])
    return success_object(regulatory_change_to_api(change))
