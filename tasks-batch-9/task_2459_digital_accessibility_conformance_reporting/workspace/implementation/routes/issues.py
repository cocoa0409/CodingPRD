"""Known issues: intake, triage, prioritization, commitment, resolution (PRD 3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from calc import remediation_risk_score
from db import db, new_row, now_iso, sort_key, touch
from derive import recompute_product, refresh_disclosure_debts
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import issue_out
from validate import (
    ISSUE_STATES,
    PUBLISH_INTENTS,
    SEVERITIES,
    body,
    fk_component,
    fk_criterion,
    fk_product,
    fk_run,
    fk_train,
    pagination,
    paginate,
    path_issue,
    q_enum,
    q_str,
    v_bool,
    v_date,
    v_enum,
    v_str,
    v_int,
)

bp = Blueprint("issues", __name__)


@bp.post("/known-issues")
@endpoint(["AccessibilityTester", "AccessibilityLead"])
def create_issue():
    data = body()
    product = fk_product(data.get("product_id"))        # step 5
    component = fk_component(data.get("component_id"))  # step 5
    criterion = fk_criterion(data.get("criterion_id"))  # step 5

    v_str(data, "product_id", required=True, min_len=1)
    v_str(data, "component_id", required=True, min_len=1)
    v_str(data, "criterion_id", required=True, min_len=1)
    severity = v_enum(data, "severity", SEVERITIES, required=True)
    summary = v_str(data, "summary", required=True, min_len=10, max_len=1000)
    effort = v_int(data, "effort_points", required=True, min_value=1, max_value=100)
    target_raw, target = v_date(data, "target_remediation_date", required=True)
    publish_intent = v_enum(data, "publish_intent", PUBLISH_INTENTS, required=True)

    # step 33: cross-aggregate consistency, component before criterion
    if component["product_id"] != product["id"]:
        raise ApiError("ERR_CROSS_PRODUCT_REFERENCE",
                       "Component %s does not belong to product %s"
                       % (component["id"], product["id"]))
    if criterion["standard_id"] != product["standard_id"]:
        raise ApiError("ERR_CRITERION_STANDARD_MISMATCH",
                       "Criterion %s does not belong to standard %s"
                       % (criterion["id"], product["standard_id"]))

    row = new_row({
        "product_id": product["id"],
        "component_id": component["id"],
        "criterion_id": criterion["id"],
        "severity": severity,
        "summary": summary,
        "effort_points": effort,
        "target_remediation_date": target_raw,
        "publish_intent": publish_intent,
        "state": "OPEN",
        "risk_score": Decimal("0.00"),
        "risk_variant": "INTAKE_ESTIMATE",
        "release_train_id": None,
        "public_target_date": None,
        "funded_cents": 0,
        "funding_state": "UNFUNDED",
        "linked_complaint_count": 0,
        "published_report_id": None,
        "resolution_run_id": None,
        "triage_note": None,
        "_triaged_at": None,
        "board_review_note": None,
        "_board_reviewed_at": None,
        "resolution_note": None,
        "_resolved_at": None,
    })
    row["_target_date"] = target
    row["_public_target_date"] = None
    row["risk_score"] = remediation_risk_score(row, "INTAKE_ESTIMATE")
    db.issues[row["id"]] = row

    refresh_disclosure_debts(product["id"])
    recompute_product(product)
    touch(product)
    return obj_response(issue_out(row), 201)


@bp.get("/known-issues/<issue_id>")
@endpoint(ALL_ROLES)
def get_issue(issue_id):
    return obj_response(issue_out(path_issue(issue_id)))


@bp.get("/known-issues")
@endpoint(ALL_ROLES)
def list_issues():
    filters = {
        "product_id": q_str("product_id"),
        "component_id": q_str("component_id"),
        "criterion_id": q_str("criterion_id"),
        "release_train_id": q_str("release_train_id"),
        "resolution_run_id": q_str("resolution_run_id"),
        "published_report_id": q_str("published_report_id"),
    }
    state = q_enum("state", ISSUE_STATES)
    limit, offset = pagination()
    rows = list(db.issues.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([issue_out(r) for r in page], limit, offset, total)


@bp.post("/known-issues/<issue_id>/triage")
@endpoint(["AccessibilityLead"])
def triage_issue(issue_id):
    issue = path_issue(issue_id)
    data = body()
    note = v_str(data, "triage_note", required=True, min_len=1, max_len=2000)
    severity = v_enum(data, "severity", SEVERITIES)

    # step 11: from-state
    if issue["state"] != "OPEN":
        raise ApiError("ERR_ISSUE_NOT_OPEN",
                       "Known issue %s is %s" % (issue["id"], issue["state"]))

    if severity is not None:
        issue["severity"] = severity
    issue["state"] = "TRIAGED"
    issue["triage_note"] = note
    issue["_triaged_at"] = now_iso()
    issue["risk_score"] = remediation_risk_score(issue, "INTAKE_ESTIMATE")
    issue["risk_variant"] = "INTAKE_ESTIMATE"
    touch(issue)

    product = db.products[issue["product_id"]]
    refresh_disclosure_debts(product["id"])
    recompute_product(product)
    return obj_response(issue_out(issue))


@bp.post("/known-issues/<issue_id>/board-review")
@endpoint(["AccessibilityLead"])
def board_review_issue(issue_id):
    issue = path_issue(issue_id)
    data = body()
    note = v_str(data, "board_review_note", required=True, min_len=1, max_len=2000)
    defer = v_bool(data, "defer", required=True)

    # step 11: from-state
    if issue["state"] != "TRIAGED":
        raise ApiError("ERR_ISSUE_NOT_TRIAGED",
                       "Known issue %s is %s" % (issue["id"], issue["state"]))

    issue["board_review_note"] = note
    issue["_board_reviewed_at"] = now_iso()
    issue["risk_variant"] = "BOARD_REVIEW"
    issue["risk_score"] = remediation_risk_score(issue, "BOARD_REVIEW")
    if defer:
        issue["state"] = "DEFERRED"
    touch(issue)

    product = db.products[issue["product_id"]]
    refresh_disclosure_debts(product["id"])
    recompute_product(product)
    return obj_response(issue_out(issue))


@bp.post("/known-issues/<issue_id>/commit")
@endpoint(["AccessibilityLead"])
def commit_issue(issue_id):
    issue = path_issue(issue_id)
    data = body()
    train = fk_train(data.get("release_train_id"))        # step 5
    v_str(data, "release_train_id", required=True, min_len=1)

    # step 11: from-state
    if issue["state"] != "TRIAGED":
        raise ApiError("ERR_ISSUE_NOT_TRIAGED",
                       "Known issue %s is %s" % (issue["id"], issue["state"]))

    # step 26: the target date must land inside the train's usable window
    usable_end = train["_window_end"] - timedelta(days=train["freeze_days"])
    if not (train["_window_start"] <= issue["_target_date"] <= usable_end):
        raise ApiError("ERR_TARGET_DATE_OUTSIDE_TRAIN_WINDOW",
                       "Target date %s is outside the usable window of train %s"
                       % (issue["target_remediation_date"], train["id"]))

    # step 38: effort capacity
    if (train["committed_effort_points"] + issue["effort_points"]
            > train["effort_capacity_points"]):
        raise ApiError("ERR_TRAIN_CAPACITY_EXCEEDED",
                       "Release train %s cannot absorb %d more effort points"
                       % (train["id"], issue["effort_points"]))

    issue["state"] = "COMMITTED"
    issue["release_train_id"] = train["id"]
    touch(issue)

    train["committed_effort_points"] += issue["effort_points"]
    touch(train)

    product = db.products[issue["product_id"]]
    recompute_product(product)
    return obj_response(issue_out(issue))


@bp.post("/known-issues/<issue_id>/resolve")
@endpoint(["AccessibilityTester"])
def resolve_issue(issue_id):
    issue = path_issue(issue_id)
    data = body()
    run = fk_run(data.get("resolution_run_id"))           # step 5
    note = v_str(data, "resolution_note", required=True, min_len=1, max_len=2000)
    v_str(data, "resolution_run_id", required=True, min_len=1)

    # step 11: from-state
    if issue["state"] not in ("COMMITTED", "PUBLISHED_COMMITTED"):
        raise ApiError("ERR_ISSUE_NOT_RESOLVABLE",
                       "Known issue %s is %s" % (issue["id"], issue["state"]))

    # step 34: resolution evidence
    if run["status"] != "COMPLETED" or run["component_id"] != issue["component_id"]:
        raise ApiError("ERR_RESOLUTION_EVIDENCE_INVALID",
                       "Assessment run %s is not completed evidence on component %s"
                       % (run["id"], issue["component_id"]))

    issue["state"] = "RESOLVED"
    issue["resolution_note"] = note
    issue["resolution_run_id"] = run["id"]
    issue["_resolved_at"] = now_iso()

    train = db.trains.get(issue.get("release_train_id"))
    if train is not None:
        train["committed_effort_points"] -= issue["effort_points"]
        train["unallocated_cents"] += issue["funded_cents"]
        touch(train)
    issue["funded_cents"] = 0
    issue["funding_state"] = "UNFUNDED"
    touch(issue)

    product = db.products[issue["product_id"]]
    refresh_disclosure_debts(product["id"])
    recompute_product(product)
    return obj_response(issue_out(issue))
