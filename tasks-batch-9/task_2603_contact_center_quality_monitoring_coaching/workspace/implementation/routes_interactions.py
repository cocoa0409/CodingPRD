"""Interactions, consent adjudication and analytics screening (PRD 3.2, 3.3)."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import shape
from authz import endpoint
from common import (body, created, fail, get, new_row, ok, ok_list, require,
                    rows, sorted_rows, touch)
from listing import page
from serial import view, views

bp = Blueprint("interactions", __name__)

CHANNELS = ("VOICE", "CHAT", "EMAIL")
DISCLOSURES = ("RECORDING", "MINI_MIRANDA", "RATE_CHANGE", "THIRD_PARTY")
CONSENT_STATUSES = ("PENDING", "VERIFIED", "DENIED", "NOT_REQUIRED")
CONSENT_OUTCOMES = ("VERIFIED", "DENIED", "NOT_REQUIRED")
CATEGORIES = ("PROFANITY", "NO_DISCLOSURE", "ESCALATION_REQUEST", "CONSENT_OBJECTION")
SCAN_STATUSES = ("CURRENT", "SUPERSEDED")
TIERS = ("P1", "P2", "P3")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")


@bp.post("/interactions")
@endpoint("QualityManager", "ComplianceAuditor")
def create_interaction():
    payload = body()
    agent_id = shape.want_string(payload, "agent_id")
    channel = shape.want_enum(payload, "channel", CHANNELS)
    started_raw, started = shape.want_datetime(payload, "started_at")
    ended_raw, ended = shape.want_datetime(payload, "ended_at")
    required_disclosures = shape.want_enum_array(payload, "required_disclosures",
                                                 DISCLOSURES, default=[])
    customer_flagged = shape.want_bool(payload, "customer_flagged", default=False)
    csat_score = shape.want_int(payload, "csat_score", required=False, default=None,
                                minimum=1, maximum=5)
    repeat_contact = shape.want_bool(payload, "repeat_contact_within_72h", default=False)

    require("agents", agent_id, "ERR_AGENT_NOT_FOUND")

    if not ended > started:
        fail("ERR_INVALID_TIME_RANGE", "ended_at must be strictly after started_at")
    duration = int((ended - started).total_seconds())

    interaction = new_row("interactions", {
        "agent_id": agent_id,
        "channel": channel,
        "started_at": started_raw,
        "ended_at": ended_raw,
        "duration_seconds": duration,
        "required_disclosures": required_disclosures,
        "captured_disclosures": [],
        "recording_consent_status": "PENDING",
        "customer_flagged": customer_flagged,
        "csat_score": csat_score,
        "repeat_contact_within_72h": repeat_contact,
        "compliance_hold": False,
        "sampled_count": 0,
    })
    return created(view(interaction))


@bp.post("/interactions/<interaction_id>/consent-review")
@endpoint("ComplianceAuditor")
def consent_review(interaction_id):
    payload = body()
    outcome = shape.want_enum(payload, "consent_outcome", CONSENT_OUTCOMES)
    captured = shape.want_enum_array(payload, "captured_disclosures", DISCLOSURES,
                                     default=[])
    interaction = require("interactions", interaction_id, "ERR_INTERACTION_NOT_FOUND")

    if interaction["recording_consent_status"] == "DENIED":
        fail("ERR_CONSENT_ALREADY_DENIED",
             "a denied interaction is frozen against further consent review")

    if outcome == "VERIFIED":
        missing = [code for code in interaction["required_disclosures"]
                   if code not in captured]
        if missing:
            shape.bad("captured_disclosures must contain every required disclosure")
    elif outcome == "NOT_REQUIRED":
        if interaction["channel"] not in ("CHAT", "EMAIL"):
            shape.bad("NOT_REQUIRED is only available on a CHAT or EMAIL contact")

    if outcome in ("VERIFIED", "NOT_REQUIRED"):
        interaction["recording_consent_status"] = outcome
        interaction["captured_disclosures"] = captured
        touch(interaction)
        return ok(view(interaction))

    # ---- DENIED: the three-hop withdrawal cascade (PRD 3.2) ----
    interaction["recording_consent_status"] = "DENIED"

    swept = [s for s in sorted_rows(rows("selections"))
             if s["interaction_id"] == interaction["id"]
             and s["status"] in ("SELECTED", "ASSIGNED")]
    evaluator_ids = []
    plan_ids = []
    for selection in swept:
        evaluator_id = selection.get("assigned_evaluator_id")
        selection["status"] = "EXCLUDED"
        selection["exclusion_reason"] = "CONSENT_DENIED"
        selection["assigned_evaluator_id"] = None
        selection["review_window_start"] = None
        selection["review_window_end"] = None
        touch(selection)
        if evaluator_id is not None and evaluator_id not in evaluator_ids:
            evaluator_ids.append(evaluator_id)
        if selection["plan_id"] not in plan_ids:
            plan_ids.append(selection["plan_id"])

    for evaluator_id in evaluator_ids:
        derive.recompute_evaluator(evaluator_id)
    for plan_id in plan_ids:
        derive.recompute_plan_by_id(plan_id)

    interaction["sampled_count"] = calc.interaction_sampled_count(interaction["id"])
    touch(interaction)

    for scan in sorted_rows(rows("scans")):
        if scan["interaction_id"] == interaction["id"] and scan["status"] == "CURRENT":
            scan["status"] = "SUPERSEDED"
            touch(scan)

    return ok(view(interaction))


@bp.get("/interactions/<interaction_id>")
@endpoint(*READ_ROLES)
def read_interaction(interaction_id):
    return ok(view(require("interactions", interaction_id, "ERR_INTERACTION_NOT_FOUND")))


@bp.get("/interactions")
@endpoint(*READ_ROLES)
def list_interactions():
    limit, offset = shape.pagination()
    agent_id = shape.query_str("agent_id")
    channel = shape.query_enum("channel", CHANNELS)
    customer_flagged = shape.query_bool("customer_flagged")
    consent_status = shape.query_enum("recording_consent_status", CONSENT_STATUSES)
    compliance_hold = shape.query_bool("compliance_hold")
    items = sorted_rows(rows("interactions"))
    if agent_id is not None:
        items = [i for i in items if i["agent_id"] == agent_id]
    if channel is not None:
        items = [i for i in items if i["channel"] == channel]
    if customer_flagged is not None:
        items = [i for i in items if i["customer_flagged"] == customer_flagged]
    if consent_status is not None:
        items = [i for i in items if i["recording_consent_status"] == consent_status]
    if compliance_hold is not None:
        items = [i for i in items if i["compliance_hold"] == compliance_hold]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)


# --- analytics scans ------------------------------------------------------

@bp.post("/analytics-scans")
@endpoint("QualityManager", "ComplianceAuditor")
def create_scan():
    payload = body()
    interaction_id = shape.want_string(payload, "interaction_id")
    silence_pct = shape.want_decimal(payload, "silence_pct", minimum=Decimal("0.00"),
                                     maximum=Decimal("100.00"))
    sentiment_delta = shape.want_decimal(payload, "sentiment_delta",
                                         minimum=Decimal("-1.00"),
                                         maximum=Decimal("1.00"))
    expected_version = shape.want_int(payload, "expected_interaction_version")
    categories = shape.want_enum_array(payload, "flagged_categories", CATEGORIES,
                                       default=[], allow_duplicates=False)

    interaction = require("interactions", interaction_id, "ERR_INTERACTION_NOT_FOUND")

    if expected_version != interaction["version"]:
        fail("ERR_STALE_INTERACTION_VERSION",
             "expected_interaction_version does not match the interaction's version")

    if interaction["recording_consent_status"] == "DENIED":
        fail("ERR_CONSENT_ALREADY_DENIED",
             "a denied interaction is frozen against new analytics screening")

    risk, tier = calc.analytics_priority_score(silence_pct, sentiment_delta,
                                               categories, interaction)

    for scan in sorted_rows(rows("scans")):
        if scan["interaction_id"] == interaction["id"] and scan["status"] == "CURRENT":
            scan["status"] = "SUPERSEDED"
            touch(scan)

    scan = new_row("scans", {
        "interaction_id": interaction["id"],
        "silence_pct": silence_pct,
        "sentiment_delta": sentiment_delta,
        "flagged_categories": categories,
        "risk_score": risk,
        "priority_tier": tier,
        "status": "CURRENT",
    })
    touch(interaction)
    return created(view(scan))


@bp.get("/analytics-scans/<scan_id>")
@endpoint(*READ_ROLES)
def read_scan(scan_id):
    return ok(view(require("scans", scan_id, "ERR_SCAN_NOT_FOUND")))


@bp.get("/analytics-scans")
@endpoint(*READ_ROLES)
def list_scans():
    limit, offset = shape.pagination()
    interaction_id = shape.query_str("interaction_id")
    status = shape.query_enum("status", SCAN_STATUSES)
    tier = shape.query_enum("priority_tier", TIERS)
    items = rows("scans")
    if interaction_id is not None:
        items = [s for s in items if s["interaction_id"] == interaction_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if tier is not None:
        items = [s for s in items if s["priority_tier"] == tier]
    # risk_score DESC, created_at ASC (PRD 2.3)
    items = sorted(items, key=lambda s: (-s["risk_score"], s["created_at"], s["_seq"]))
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
