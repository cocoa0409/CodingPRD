"""Disparity findings: manual drafting, triage, substantiation, refutation, reopen."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_request, invalid_state, not_found
from middleware import (
    body, check_enum, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj

bp = Blueprint("findings", __name__)

KINDS = (
    "DENIAL_DISPARITY", "PRICING_DISPARITY", "PENETRATION_SHORTFALL",
    "OVERRIDE_ASYMMETRY", "MANUAL",
)
ROLES = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")
EVIDENCE_KINDS = ("DENIAL_DISPARITY", "OVERRIDE_ASYMMETRY")


def _bump_open(run, delta):
    run["open_finding_count"] += delta
    db.touch(run)


@bp.post("/fair-lending/findings")
@require_roles("FairLendingAnalyst")
def create_finding():
    data = body()
    run_id = require_field(data, "analysis_run_id")
    kind = check_enum(require_field(data, "kind"), KINDS, "kind")
    notes = data.get("notes")
    supersedes_id = data.get("supersedes_finding_id")
    run = get_or_404("runs", run_id, "AnalysisRun")
    if run["status"] not in ("COMPUTED", "UNDER_REVIEW"):
        raise invalid_state(
            "Manual findings may be drafted only on COMPUTED/UNDER_REVIEW runs"
        )
    old = None
    if supersedes_id is not None:
        old = db.STORES["findings"].get(supersedes_id)
        if old is None:
            raise not_found("DisparityFinding")
        if old["status"] in ("CLOSED", "SUPERSEDED"):
            raise already_terminal("Superseded target finding is terminal")
        if old["status"] not in ("FLAGGED", "UNDER_REVIEW", "REFUTED"):
            raise invalid_state(
                "Finding in state %s cannot be superseded" % old["status"]
            )
    rec = db.new_record(
        {
            "analysis_run_id": run["id"],
            "kind": kind,
            "source": "MANUAL",
            "metric_value": None,
            "threshold_value": None,
            "notes": notes,
            "status": "FLAGGED",
            "harmed_application_ids": [],
            "created_by_user_id": g.user_id,
            "substantiated_by_user_id": None,
            "refute_reason": None,
            "reopen_count": 0,
            "superseded_by_finding_id": None,
        }
    )
    db.STORES["findings"][rec["id"]] = rec
    _bump_open(run, 1)
    if old is not None:
        was_open = old["status"] in ("FLAGGED", "UNDER_REVIEW")
        old["status"] = "SUPERSEDED"
        old["superseded_by_finding_id"] = rec["id"]
        db.touch(old)
        if was_open:
            _bump_open(run, -1)
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/findings")
@require_roles(*ROLES)
def list_findings():
    page, total, limit, offset = list_page(
        "findings",
        {
            "analysis_run_id": request.args.get("analysis_run_id"),
            "status": request.args.get("status"),
            "kind": request.args.get("kind"),
            "superseded_by_finding_id": request.args.get("superseded_by_finding_id"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/findings/<findingId>")
@require_roles(*ROLES)
def get_finding(findingId):
    rec = get_or_404("findings", findingId, "DisparityFinding")
    return success_obj(db.public(rec))


def _load(findingId):
    rec = get_or_404("findings", findingId, "DisparityFinding")
    return rec


def _terminal_guard(rec):
    if rec["status"] in ("CLOSED", "SUPERSEDED"):
        raise already_terminal("DisparityFinding is in terminal state %s" % rec["status"])


@bp.post("/fair-lending/findings/<findingId>/begin-review")
@require_roles("FairLendingAnalyst")
def begin_review(findingId):
    rec = _load(findingId)
    _terminal_guard(rec)
    if rec["status"] != "FLAGGED":
        raise invalid_state("Finding is not FLAGGED")
    rec["status"] = "UNDER_REVIEW"
    db.touch(rec)
    run = db.STORES["runs"].get(rec["analysis_run_id"])
    if run is not None and run["status"] == "COMPUTED":
        run["status"] = "UNDER_REVIEW"
        db.touch(run)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/findings/<findingId>/substantiate")
@require_roles("FairLendingOfficer")
def substantiate(findingId):
    rec = _load(findingId)
    data = body()
    # SoD (identity-level, priority 3): manual findings cannot be substantiated
    # by their creator.
    if rec["source"] == "MANUAL" and rec["created_by_user_id"] == g.user_id:
        raise err(
            "ERR_SOD_VIOLATION",
            "Substantiating officer must differ from the finding's creator",
        )
    _terminal_guard(rec)
    if rec["status"] != "UNDER_REVIEW":
        raise invalid_state("Finding is not UNDER_REVIEW")
    harmed = require_field(data, "harmed_application_ids")
    if not isinstance(harmed, list):
        raise invalid_request("harmed_application_ids must be an array")
    for app_id in harmed:
        if app_id not in db.STORES["applications"]:
            raise not_found("Application")
    if rec["kind"] in EVIDENCE_KINDS:
        has_confirmed = any(
            r["finding_id"] == rec["id"] and r["status"] == "CONFIRMED"
            for r in db.STORES["reviews"].values()
        )
        if not has_confirmed:
            raise err(
                "ERR_NO_CONFIRMED_MATCHED_PAIR",
                "Substantiation requires a CONFIRMED matched-pair review",
            )
    rec["status"] = "SUBSTANTIATED"
    rec["harmed_application_ids"] = list(harmed)
    rec["substantiated_by_user_id"] = g.user_id
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/findings/<findingId>/refute")
@require_roles("FairLendingOfficer")
def refute(findingId):
    rec = _load(findingId)
    _terminal_guard(rec)
    if rec["status"] != "UNDER_REVIEW":
        raise invalid_state("Finding is not UNDER_REVIEW")
    data = body()
    rec["status"] = "REFUTED"
    rec["refute_reason"] = data.get("reason")
    db.touch(rec)
    run = db.STORES["runs"].get(rec["analysis_run_id"])
    if run is not None:
        _bump_open(run, -1)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/findings/<findingId>/reopen")
@require_roles("FairLendingAnalyst")
def reopen(findingId):
    rec = _load(findingId)
    _terminal_guard(rec)
    if rec["status"] != "REFUTED":
        raise invalid_state("Only a REFUTED finding can be reopened")
    rec["status"] = "UNDER_REVIEW"
    rec["reopen_count"] += 1
    db.touch(rec)
    run = db.STORES["runs"].get(rec["analysis_run_id"])
    if run is not None:
        _bump_open(run, 1)
    return success_obj(db.public(rec))
