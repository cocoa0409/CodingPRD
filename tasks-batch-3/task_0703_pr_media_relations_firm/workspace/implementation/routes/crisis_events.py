"""CrisisEvent endpoints and dual-dimension lifecycle (PRD 3.12)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_enum, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import crisis_event_out

bp = Blueprint("crisis_events", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@bp.post("/agency/crisis-events")
@authorize(["AccountManager"])
def create_crisis_event():
    body = get_json_body()
    client_id = body.get("client_id")
    campaign_id = body.get("campaign_id")
    ref_or_404(db.clients, client_id, "client_id")
    if campaign_id is not None:
        ref_or_404(db.campaigns, campaign_id, "campaign_id")
    summary = require_str(body, "summary")
    severity = require_enum(body, "severity", SEVERITIES)
    holding_statement = body.get("holding_statement")
    if holding_statement is not None and not isinstance(holding_statement, str):
        raise err("ERR_INVALID_REQUEST", "holding_statement must be a string")

    rec = new_record({
        "client_id": client_id,
        "campaign_id": campaign_id,
        "summary": summary,
        "severity": severity,
        "severity_status": "ASSESSING",
        "response_status": "DRAFTING",
        "holding_statement": holding_statement,
    })
    db.crisis_events[rec["id"]] = rec
    return success(crisis_event_out(rec), status=201)


@bp.get("/agency/crisis-events/<crisis_id>")
@authorize(["AccountManager", "PlatformAdmin"])
def get_crisis_event(crisis_id):
    rec = get_or_404(db.crisis_events, crisis_id)
    return success(crisis_event_out(rec))


@bp.get("/agency/crisis-events")
@authorize(["AccountManager", "PlatformAdmin"])
def list_crisis_events():
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    campaign_id = request.args.get("campaign_id")
    records = []
    for r in db.crisis_events.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if campaign_id is not None and r.get("campaign_id") != campaign_id:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([crisis_event_out(r) for r in page], pagination=meta)


@bp.post("/agency/crisis-events/<crisis_id>/escalate")
@authorize(["AccountManager"])
def escalate_crisis(crisis_id):
    rec = get_or_404(db.crisis_events, crisis_id)
    if rec["severity_status"] != "ASSESSING":
        raise err("ERR_INVALID_STATE", "severity_status is not ASSESSING")
    if rec["severity"] not in ("HIGH", "CRITICAL"):
        raise err("ERR_SEVERITY_TOO_LOW", "Severity must be HIGH or CRITICAL to escalate")
    rec["severity_status"] = "ESCALATED"
    touch(rec)
    return success(crisis_event_out(rec))


@bp.post("/agency/crisis-events/<crisis_id>/contain")
@authorize(["AccountManager"])
def contain_crisis(crisis_id):
    rec = get_or_404(db.crisis_events, crisis_id)
    if rec["severity_status"] not in ("ASSESSING", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "severity_status cannot be contained from its current state")
    # Cross-dimension guard: reads response dimension, mutates severity only.
    if rec["response_status"] != "PUBLISHED":
        raise err("ERR_RESPONSE_NOT_PUBLISHED", "Response dimension is not PUBLISHED")
    rec["severity_status"] = "CONTAINED"
    touch(rec)
    return success(crisis_event_out(rec))


@bp.post("/agency/crisis-events/<crisis_id>/approve-response")
@authorize(["AccountManager"])
def approve_response(crisis_id):
    rec = get_or_404(db.crisis_events, crisis_id)
    body = get_json_body()
    # The approve-response operation may itself supply a holding_statement.
    supplied = body.get("holding_statement")
    if supplied is not None and not isinstance(supplied, str):
        raise err("ERR_INVALID_REQUEST", "holding_statement must be a string")
    # Priority 7: state validity before any mutation.
    if rec["response_status"] != "DRAFTING":
        raise err("ERR_INVALID_STATE", "response_status is not DRAFTING")
    # Apply the optionally-supplied holding statement, then guard non-null.
    if supplied is not None:
        rec["holding_statement"] = supplied
    if rec.get("holding_statement") is None:
        raise err("ERR_NO_HOLDING_STATEMENT", "No holding statement present")
    rec["response_status"] = "APPROVED"
    touch(rec)
    return success(crisis_event_out(rec))


@bp.post("/agency/crisis-events/<crisis_id>/publish-response")
@authorize(["AccountManager"])
def publish_response(crisis_id):
    rec = get_or_404(db.crisis_events, crisis_id)
    if rec["response_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "response_status is not APPROVED")
    rec["response_status"] = "PUBLISHED"
    touch(rec)
    return success(crisis_event_out(rec))
