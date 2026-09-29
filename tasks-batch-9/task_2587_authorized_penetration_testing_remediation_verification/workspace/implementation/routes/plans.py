"""The annual test plan, its prioritization mode, activation and trend analysis."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import core
import serialize
from auth import authorize
from core import new_immutable, new_record, ordered, recompute_coverage, recompute_ranks, touch
from envelope import array_response, object_response
from errors import ApiError
from resolve import filtered, get_test_plan, get_training, paginate
from store import store
from validate import body, get_datetime, get_enum, get_int

bp = Blueprint("plans", __name__)

MODES = ("RISK_DRIVEN", "COMPLIANCE_DRIVEN")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin")
RESCORED_STATUSES = ("PROPOSED", "APPROVED", "DEFERRED")


@bp.post("/test-plans")
def open_plan():
    authorize("ProgramManager")
    data = body()
    fiscal_year = get_int(data, "fiscal_year", minimum=2026, maximum=2099)
    appetite = get_int(data, "risk_appetite_score", minimum=0, maximum=100)
    planned = get_int(data, "planned_engagement_count", minimum=1, maximum=50)
    mode = get_enum(data, "prioritization_mode", MODES, required=False, default="RISK_DRIVEN")
    record = new_record(
        fiscal_year=fiscal_year,
        prioritization_mode=mode,
        risk_appetite_score=appetite,
        planned_engagement_count=planned,
        admission_threshold=Decimal(100 - appetite),
        coverage_score=Decimal("0"),
        status="DRAFT",
        total_risk_points=0,
        open_risk_points=0,
        closed_risk_points=0,
        accepted_risk_points=0,
        duplicate_risk_points=0,
    )
    store.test_plans[record["id"]] = record
    return object_response(serialize.test_plan(record), 201)


@bp.get("/test-plans/<plan_id>")
def read_plan(plan_id):
    authorize(*READ_ROLES)
    return object_response(serialize.test_plan(get_test_plan(plan_id)))


@bp.get("/test-plans")
def list_plans():
    authorize(*READ_ROLES)
    rows = filtered(list(store.test_plans.values()), status=request.args.get("status"))
    year = request.args.get("fiscal_year")
    if year is not None:
        try:
            wanted = int(str(year).strip())
        except (TypeError, ValueError):
            wanted = None
        rows = [row for row in rows if row["fiscal_year"] == wanted]
    return paginate(rows, serialize.test_plan)


@bp.post("/test-plans/<plan_id>/prioritization-mode")
def switch_mode(plan_id):
    authorize("ProgramManager")
    plan = get_test_plan(plan_id)
    data = body()
    mode = get_enum(data, "prioritization_mode", MODES)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT")
    plan["prioritization_mode"] = mode
    for item in core.plan_scope_items(plan["id"]):
        if item["status"] in RESCORED_STATUSES:
            core.score_scope_item(item, plan)
            touch(item)
    recompute_ranks(plan["id"])
    touch(plan)
    return object_response(serialize.test_plan(plan))


@bp.post("/test-plans/<plan_id>/activate")
def activate_plan(plan_id):
    authorize("ProgramManager")
    plan = get_test_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT")
    approved = [i for i in core.plan_scope_items(plan["id"]) if i["status"] == "APPROVED"]
    if not approved:
        raise ApiError("ERR_EMPTY_SCOPE_SELECTION")
    coverage = core.coverage_value(plan)
    if coverage < calc.COVERAGE_MIN_PCT:
        raise ApiError("ERR_COVERAGE_BELOW_MINIMUM")
    plan["coverage_score"] = coverage
    plan["status"] = "ACTIVE"
    touch(plan)
    return object_response(serialize.test_plan(plan))


@bp.post("/test-plans/<plan_id>/training-recommendations")
def run_trend_analysis(plan_id):
    """One immutable recommendation per theme with at least one contributing finding."""
    authorize("ProgramManager", "ComplianceOfficer")
    plan = get_test_plan(plan_id)
    data = body()
    start_raw, window_start = get_datetime(data, "window_start")
    end_raw, window_end = get_datetime(data, "window_end")
    generated_at = store.now()
    engagement_ids = {eng["id"] for eng in core.plan_engagements(plan["id"])}
    contributors = {}
    for finding in store.findings.values():
        if finding["engagement_id"] not in engagement_ids:
            continue
        if finding["status"] in ("DUPLICATE", "RISK_ACCEPTED"):
            continue
        if finding["discovered_at"] < window_start or finding["discovered_at"] > window_end:
            continue
        contributors.setdefault(finding["root_cause_theme"], []).append(finding)
    emitted = []
    for theme in calc.ROOT_CAUSE_THEMES:
        findings = contributors.get(theme)
        if not findings:
            continue
        findings.sort(key=lambda f: (f["discovered_at"], f["created_at"], f["_seq"]))
        score = calc.training_priority_score(findings, generated_at)
        record = new_immutable(
            test_plan_id=plan["id"],
            root_cause_theme=theme,
            window_start=window_start,
            window_start_raw=start_raw,
            window_end=window_end,
            window_end_raw=end_raw,
            recurrence_count=len(findings),
            priority_score=score,
            urgency_band=calc.urgency_band(len(findings), score),
            source_engagement_count=len({f["engagement_id"] for f in findings}),
            generated_at=generated_at,
            contributing_finding_ids=[f["id"] for f in findings],
        )
        store.training[record["id"]] = record
        emitted.append(record)
    emitted.sort(key=lambda rec: (-rec["priority_score"], rec["root_cause_theme"]))
    return array_response([serialize.training(rec) for rec in emitted], 201)


@bp.get("/test-plans/<plan_id>/training-recommendations")
def list_plan_recommendations(plan_id):
    authorize(*READ_ROLES)
    plan = get_test_plan(plan_id)
    rows = [r for r in store.training.values() if r["test_plan_id"] == plan["id"]]
    rows = filtered(
        rows,
        urgency_band=request.args.get("urgency_band"),
        root_cause_theme=request.args.get("root_cause_theme"),
    )
    return paginate(rows, serialize.training)


@bp.get("/training-recommendations/<training_id>")
def read_recommendation(training_id):
    authorize(*READ_ROLES)
    return object_response(serialize.training(get_training(training_id)))
