"""Readouts, decision confidence and follow-ups (PRD 3.8)."""
from flask import Blueprint, g

import serializers
from auth import ALL_ROLES, require_roles
from calc import bump_theme_reuse, recompute_decision_confidence, set_field
from clock import clock
from envelope import created, ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    body,
    decision_or_404,
    filter_enum,
    finding_or_404,
    followup_or_404,
    opt_str,
    readout_or_404,
    ref,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    req_str_array,
    study_or_404,
)

bp = Blueprint("readouts", __name__)

ACTIONS = ("PROCEED", "PIVOT", "HOLD")
READOUT_STATUSES = ("DRAFT", "SUPERSEDED", "DELIVERED", "ACCEPTED", "DEFERRED")
RESPONSE_OUTCOMES = ("ACCEPTED", "DEFERRED")
FOLLOWUP_STATUSES = ("OPEN", "OVERDUE", "DONE")


@bp.post("/studies/<study_id>/readouts")
@require_roles("Researcher", "ResearchLead")
def draft_readout(study_id):
    data = body()
    decision = decision_or_404(ref(data, "roadmap_decision_id"))
    study = study_or_404(study_id)
    raw_citations = data.get("cited_finding_ids")
    if isinstance(raw_citations, list):
        for item in raw_citations:
            if isinstance(item, str) and item != "":
                finding_or_404(item)
    req_str(data, "roadmap_decision_id")
    recommendation = req_str(data, "recommendation", max_len=1000)
    action = req_enum(data, "recommended_action", ACTIONS)
    citations = req_str_array(data, "cited_finding_ids", allow_empty=False, allow_duplicates=False)
    expected = req_int(data, "expected_study_version")
    if expected != study["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION", "The supplied expected_study_version is stale.")
    findings = [db.findings[fid] for fid in citations]
    if any(f["study_id"] != study["id"] for f in findings):
        raise ApiError("ERR_CITATION_STUDY_MISMATCH", "Every cited finding must belong to this study.")
    row = db.new("readouts", {
        "study_id": study["id"],
        "roadmap_decision_id": decision["id"],
        "recommendation": recommendation,
        "recommended_action": action,
        "cited_finding_ids": list(citations),
        "status": "DRAFT",
        "delivered_at": None,
        "responded_at": None,
        "response_note": None,
        "decision_confidence_before": None,
        "decision_confidence_after": None,
    })
    for other in db.readouts.values():
        if other["id"] == row["id"]:
            continue
        if other["study_id"] == study["id"] and other["status"] == "DRAFT":
            set_field(other, "status", "SUPERSEDED")
    db.mark(study)
    return created(serializers.readout(row))


@bp.post("/readouts/<readout_id>/deliver")
@require_roles("Researcher", "ResearchLead")
def deliver_readout(readout_id):
    readout = readout_or_404(readout_id)
    study = db.studies.get(readout["study_id"])
    if readout["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT readout can be delivered.")
    if study is None or study["execution_status"] != "ANALYSIS":
        raise ApiError("ERR_INVALID_STATE", "The study must be in ANALYSIS.")
    citations = readout["cited_finding_ids"]
    published = [
        db.findings.get(fid) for fid in citations
    ]
    if not citations or any(f is None or f["status"] != "PUBLISHED" for f in published):
        raise ApiError("ERR_NO_PUBLISHED_FINDINGS", "Every cited finding must still be PUBLISHED.")
    set_field(readout, "status", "DELIVERED")
    set_field(readout, "delivered_at", clock.now())
    set_field(study, "execution_status", "REPORTED")
    db.mark(study)
    return ok(serializers.readout(readout))


@bp.post("/readouts/<readout_id>/respond")
@require_roles("Stakeholder")
def respond_readout(readout_id):
    existing = db.readouts.get(readout_id)
    if existing is not None and _requester_of(existing) != g.user_id:
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "Only the requester behind the study may respond.")
    readout = readout_or_404(readout_id)
    data = body()
    outcome = req_enum(data, "outcome", RESPONSE_OUTCOMES)
    note = opt_str(data, "note")
    if readout["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "Only a DELIVERED readout can be responded to.")
    decision = db.decisions.get(readout["roadmap_decision_id"])
    if outcome == "ACCEPTED" and decision is not None and decision["status"] == "LOCKED":
        raise ApiError("ERR_DECISION_LOCKED", "The roadmap decision is LOCKED.")
    set_field(readout, "status", outcome)
    set_field(readout, "responded_at", clock.now())
    set_field(readout, "response_note", note)
    if outcome == "ACCEPTED":
        before = decision["evidence_confidence"]
        set_field(readout, "decision_confidence_before", before)
        after = recompute_decision_confidence(decision)
        set_field(readout, "decision_confidence_after", after)
        _bump_reuse(readout)
        study = db.studies.get(readout["study_id"])
        if study is not None:
            set_field(study, "execution_status", "CLOSED")
            db.mark(study)
            research_request = db.requests.get(study["research_request_id"])
            if research_request is not None and research_request["status"] == "IN_STUDY":
                set_field(research_request, "status", "CLOSED")
    return ok(serializers.readout(readout))


def _requester_of(readout):
    study = db.studies.get(readout["study_id"])
    if study is None:
        return None
    research_request = db.requests.get(study["research_request_id"])
    if research_request is None:
        return None
    return research_request["requester_user_id"]


def _bump_reuse(readout):
    """reuse_count counts ACCEPTED readouts per theme, so each theme in the
    ancestor closure of the cited findings' themes rises by exactly one."""
    targets = []
    for fid in readout["cited_finding_ids"]:
        finding = db.findings.get(fid)
        if finding is None:
            continue
        current = db.themes.get(finding["theme_id"])
        while current is not None:
            if current["id"] not in [t["id"] for t in targets]:
                targets.append(current)
            current = db.themes.get(current["parent_theme_id"]) if current["parent_theme_id"] else None
    for theme in targets:
        set_field(theme, "reuse_count", theme["reuse_count"] + 1)


@bp.post("/readouts/<readout_id>/follow-ups")
@require_roles("Stakeholder", "ResearchLead", "ResearchOpsAdmin")
def create_followup(readout_id):
    readout = readout_or_404(readout_id)
    data = body()
    owner = req_str(data, "owner_user_id")
    description = req_str(data, "description", max_len=500)
    due_date = req_datetime(data, "due_date")
    row = db.new("followups", {
        "readout_id": readout["id"],
        "owner_user_id": owner,
        "description": description,
        "due_date": due_date,
        "status": "OPEN",
        "completed_at": None,
    })
    return created(serializers.followup(row))


@bp.post("/follow-ups/<followup_id>/complete")
@require_roles("Stakeholder", "ResearchLead", "ResearchOpsAdmin")
def complete_followup(followup_id):
    existing = db.followups.get(followup_id)
    if existing is not None and existing["owner_user_id"] != g.user_id:
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "Only the follow-up's owner may complete it.")
    followup = followup_or_404(followup_id)
    if followup["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN or OVERDUE follow-up can be completed.")
    set_field(followup, "status", "DONE")
    set_field(followup, "completed_at", clock.now())
    return ok(serializers.followup(followup))


@bp.get("/readouts/<readout_id>")
@require_roles(*ALL_ROLES)
def read_readout(readout_id):
    return ok(serializers.readout(readout_or_404(readout_id)))


@bp.get("/readouts")
@require_roles(*ALL_ROLES)
def list_readouts():
    decision = decision_or_404(_filter_id("roadmap_decision_id"))
    study = study_or_404(_filter_id("study_id"))
    status = filter_enum("status", READOUT_STATUSES)
    rows = list(db.readouts.values())
    if study is not None:
        rows = [r for r in rows if r["study_id"] == study["id"]]
    if decision is not None:
        rows = [r for r in rows if r["roadmap_decision_id"] == decision["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged_listing(by_created(rows), serializers.readout)


@bp.get("/readouts/<readout_id>/follow-ups")
@require_roles(*ALL_ROLES)
def list_followups(readout_id):
    readout = readout_or_404(readout_id)
    status = filter_enum("status", FOLLOWUP_STATUSES)
    rows = [f for f in db.followups.values() if f["readout_id"] == readout["id"]]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    rows = sorted(rows, key=lambda f: (f["due_date"], f["created_at"], f["_seq"]))
    return paged_listing(rows, serializers.followup)


def _filter_id(name):
    from flask import request as flask_request
    raw = flask_request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
