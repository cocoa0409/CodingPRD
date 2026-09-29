"""Findings: the most heavily guarded write in the system (PRD 3.6, 3.7)."""
from flask import Blueprint, g, request

import calc
import core
import serialize
from auth import authorize, require_role
from core import asset_open_delta, ledger_move, new_record, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_asset, get_engagement, get_finding, paginate
from store import store
from validate import body, get_enum, get_int, get_number, get_str

bp = Blueprint("findings", __name__)

EXPOSURE_CLASSES = ("INTERNAL", "PARTNER", "INTERNET")
TRIAGE_ACTIONS = ("ACCEPT", "MARK_DUPLICATE", "RISK_ACCEPT", "REVOKE_RISK_ACCEPTANCE")
READ_ROLES = (
    "ProgramManager",
    "ComplianceOfficer",
    "PlatformAdmin",
    "Tester",
    "RemediationOwner",
)


@bp.post("/findings")
def report_finding():
    authorize("Tester")
    data = body()
    engagement_id = get_str(data, "engagement_id")
    asset_id = get_str(data, "asset_id")
    title = get_str(data, "title", min_len=1, max_len=160)
    steps = get_str(data, "reproduction_steps", min_len=1, max_len=2000)
    narrative = get_str(data, "business_impact_narrative", min_len=1, max_len=2000)
    base_score = get_number(data, "technical_base_score", minimum=0, maximum=10, max_decimals=2)
    exposure_class = get_enum(data, "exposure_class", EXPOSURE_CLASSES)
    theme = get_enum(data, "root_cause_theme", calc.ROOT_CAUSE_THEMES)
    expected_version = get_int(data, "expected_engagement_version")
    asset = get_asset(asset_id)
    engagement = get_engagement(engagement_id)
    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")
    if engagement["authorization_state"] == "SUSPENDED":
        raise ApiError("ERR_ENGAGEMENT_SUSPENDED")
    if engagement["authorization_state"] != "AUTHORIZED":
        raise ApiError("ERR_ENGAGEMENT_NOT_AUTHORIZED")
    if engagement["execution_state"] != "EXECUTING":
        raise ApiError("ERR_ENGAGEMENT_NOT_EXECUTING")
    now = store.now()
    roe = core.roe_of_engagement(engagement["id"])
    targets = core.roe_targets(roe["id"]) if roe is not None else []
    # The target's state is deliberately not consulted for the open-window proof.
    if not any(t["window_start"] <= now <= t["window_end"] for t in targets):
        raise ApiError("ERR_NO_OPEN_TESTING_WINDOW")
    asset_targets = [t for t in targets if t["asset_id"] == asset["id"]]
    if any(t["state"] == "EXCLUDED" for t in asset_targets):
        raise ApiError("ERR_TARGET_EXCLUDED")
    if not any(t["state"] == "ACTIVE" for t in asset_targets):
        raise ApiError("ERR_TARGET_NOT_AUTHORIZED")
    assignment = None
    for candidate in core.ordered(core.engagement_assignments(engagement["id"])):
        if candidate["tester_id"] == g.user_id and candidate["access_state"] == "PROVISIONED":
            assignment = candidate
            break
    if assignment is None:
        raise ApiError("ERR_TESTER_NOT_ASSIGNED")
    if asset["id"] not in assignment["granted_asset_ids"]:
        raise ApiError("ERR_ASSET_NOT_GRANTED")
    if now < engagement["window_start"] or now > engagement["window_end"]:
        raise ApiError("ERR_OUTSIDE_TESTING_WINDOW")
    score = calc.severity_score(base_score, exposure_class, asset)
    band = calc.severity_band(score)
    record = new_record(
        engagement_id=engagement["id"],
        asset_id=asset["id"],
        discovered_by_tester_id=g.user_id,
        duplicate_of_finding_id=None,
        title=title,
        reproduction_steps=steps,
        business_impact_narrative=narrative,
        technical_base_score=base_score,
        exposure_class=exposure_class,
        root_cause_theme=theme,
        severity_score=score,
        severity_band=band,
        severity_points=calc.SEVERITY_POINTS[band],
        immediate_action_required=band == "CRITICAL",
        status="REPORTED",
        discovered_at=now,
        closed_at=None,
    )
    store.findings[record["id"]] = record
    if band == "CRITICAL":
        alert = new_record(
            finding_id=record["id"],
            raised_at=now,
            ack_deadline_at=calc.ack_deadline(now, exposure_class),
            acknowledged_at=None,
            acknowledged_by_user_id=None,
            containment_action=None,
            escalation_level=1,
            state="RAISED",
        )
        store.alerts[alert["id"]] = alert
    plan = core.plan_of_engagement(engagement)
    if plan is not None:
        plan["total_risk_points"] = plan["total_risk_points"] + record["severity_points"]
        plan["open_risk_points"] = plan["open_risk_points"] + record["severity_points"]
        touch(plan)
    asset_open_delta(asset, record, 1)
    touch(engagement)
    return object_response(serialize.finding(record), 201)


@bp.get("/findings/<finding_id>")
def read_finding(finding_id):
    authorize(*READ_ROLES)
    return object_response(serialize.finding(get_finding(finding_id)))


@bp.get("/findings")
def list_findings():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.findings.values()),
        engagement_id=request.args.get("engagement_id"),
        asset_id=request.args.get("asset_id"),
        discovered_by_tester_id=request.args.get("discovered_by_tester_id"),
        duplicate_of_finding_id=request.args.get("duplicate_of_finding_id"),
        status=request.args.get("status"),
        severity_band=request.args.get("severity_band"),
        root_cause_theme=request.args.get("root_cause_theme"),
    )
    return paginate(rows, serialize.finding)


@bp.post("/findings/<finding_id>/triage")
def triage_finding(finding_id):
    """The conserved risk-point ledger: points only ever move between buckets."""
    authorize("ProgramManager", "ComplianceOfficer")
    finding = get_finding(finding_id)
    data = body()
    action = get_enum(data, "action", TRIAGE_ACTIONS)
    if action in ("RISK_ACCEPT", "REVOKE_RISK_ACCEPTANCE"):
        require_role("ComplianceOfficer")
    note = get_str(data, "note", required=action == "RISK_ACCEPT")
    duplicate_id = get_str(data, "duplicate_of_finding_id", required=action == "MARK_DUPLICATE")
    target = get_finding(duplicate_id) if duplicate_id is not None else None
    if action == "ACCEPT":
        if finding["status"] != "REPORTED":
            raise ApiError("ERR_FINDING_NOT_TRIAGEABLE")
    elif action in ("MARK_DUPLICATE", "RISK_ACCEPT"):
        if finding["status"] not in ("REPORTED", "TRIAGED"):
            raise ApiError("ERR_FINDING_NOT_TRIAGEABLE")
    else:
        if finding["status"] != "RISK_ACCEPTED":
            raise ApiError("ERR_FINDING_NOT_TRIAGEABLE")
    if action == "MARK_DUPLICATE":
        if target["id"] == finding["id"]:
            raise ApiError("ERR_DUPLICATE_SELF_REFERENCE")
        if target["status"] == "DUPLICATE":
            raise ApiError("ERR_DUPLICATE_CHAIN_NOT_ALLOWED")
    plan = core.plan_of_finding(finding)
    asset = store.assets.get(finding["asset_id"])
    points = finding["severity_points"]
    if action == "ACCEPT":
        finding["status"] = "TRIAGED"
        touch(finding)
    elif action == "MARK_DUPLICATE":
        finding["status"] = "DUPLICATE"
        finding["duplicate_of_finding_id"] = target["id"]
        touch(finding)
        if plan is not None:
            ledger_move(plan, "open_risk_points", "duplicate_risk_points", points)
        if asset is not None:
            asset_open_delta(asset, finding, -1)
        for alert in core.finding_alerts(finding["id"]):
            if alert["state"] == "RAISED":
                alert["state"] = "ACKNOWLEDGED"
                alert["containment_action"] = "DUPLICATE_OF_PRIOR_FINDING"
                touch(alert)
    elif action == "RISK_ACCEPT":
        finding["status"] = "RISK_ACCEPTED"
        touch(finding)
        if plan is not None:
            ledger_move(plan, "open_risk_points", "accepted_risk_points", points)
        if asset is not None:
            asset_open_delta(asset, finding, -1)
    else:
        finding["status"] = "TRIAGED"
        touch(finding)
        if plan is not None:
            ledger_move(plan, "accepted_risk_points", "open_risk_points", points)
        if asset is not None:
            asset_open_delta(asset, finding, 1)
    return object_response(serialize.finding(finding))
