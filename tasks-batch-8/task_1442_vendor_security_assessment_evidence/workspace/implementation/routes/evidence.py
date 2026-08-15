"""EvidenceArtifact lifecycle (PRD §3.5): upload moves the cycle into
EVIDENCE_REVIEW; per-artifact review exits clean/with-exceptions/rejected,
with coverage-gap computation and auto-exception on rejection.
"""
from flask import Blueprint

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import body, require_roles, scope_vendor_or_403
from response import ok
from serializers import serialize

bp = Blueprint("evidence", __name__, url_prefix="/vsa/vendors/<vid>/cycles/<cid>/evidence")

KINDS = ("SOC2_TYPE1", "SOC2_TYPE2", "ISO27001", "PENTEST", "OTHER")


def _resolve(vid, cid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    return vendor, cycle


def _compute_gap(artifact, cycle):
    """Whole days between period_end and the cycle's issued_at."""
    if cycle.get("issued_at") is None:
        return 0
    return util.days_between(util.parse_dt(cycle["issued_at"]),
                             util.parse_dt(artifact["period_end"]))


@bp.post("")
@require_roles("VendorContact")
def upload_evidence(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] not in ("SCORED", "EVIDENCE_REVIEW"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not accepting evidence")
    data = body()
    kind = data.get("kind")
    period_start = data.get("period_start")
    period_end = data.get("period_end")
    issued_by = data.get("issued_by")
    if kind not in KINDS:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "kind must be one of %s" % (KINDS,))
    if not util.is_dt(period_start):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "period_start must be an ISO 8601 datetime")
    if not util.is_dt(period_end):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "period_end must be an ISO 8601 datetime")
    if not isinstance(issued_by, str) or not issued_by:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "issued_by is required")
    # Coverage validity (priority 13): period_end must follow period_start.
    if not util.parse_dt(period_end) > util.parse_dt(period_start):
        raise ApiError(errors.ERR_EVIDENCE_COVERAGE_INVALID, 422,
                       "period_end must be after period_start")
    artifact = {
        "cycle_id": cid,
        "kind": kind,
        "period_start": util.iso(util.parse_dt(period_start)),
        "period_end": util.iso(util.parse_dt(period_end)),
        "issued_by": issued_by,
        "status": "RECEIVED",
        "coverage_gap_days": None,
    }
    helpers.stamp_new("artifacts", artifact)
    db.artifacts[artifact["id"]] = artifact
    if cycle["status"] == "SCORED":
        # First artifact moves the cycle into evidence review.
        cycle["status"] = "EVIDENCE_REVIEW"
        helpers.touch("cycles", cycle)
    return ok(serialize("artifact", artifact), 201)


@bp.post("/<aid>/start-review")
@require_roles("RiskAnalyst")
def start_review(vid, cid, aid):
    vendor, cycle = _resolve(vid, cid)
    artifact = helpers.get_child(db.artifacts, "cycle_id", cycle, aid,
                                 "EvidenceArtifact")
    if artifact["status"] != "RECEIVED" or cycle["status"] != "EVIDENCE_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Artifact cannot enter review in its current state")
    artifact["status"] = "UNDER_REVIEW"
    helpers.touch("artifacts", artifact)
    return ok(serialize("artifact", artifact))


@bp.post("/<aid>/complete-review")
@require_roles("RiskAnalyst")
def complete_review(vid, cid, aid):
    vendor, cycle = _resolve(vid, cid)
    artifact = helpers.get_child(db.artifacts, "cycle_id", cycle, aid,
                                 "EvidenceArtifact")
    if artifact["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Artifact is not UNDER_REVIEW")
    artifact["coverage_gap_days"] = _compute_gap(artifact, cycle)
    # Coverage validity (priority 13): gaps beyond 180 days fail completion.
    if artifact["coverage_gap_days"] > 180:
        raise ApiError(errors.ERR_EVIDENCE_COVERAGE_INVALID, 422,
                       "coverage_gap_days exceeds 180")
    standing = any(
        e.get("evidence_artifact_id") == aid
        and e["status"] != "CLOSED_FALSE_POSITIVE"
        for e in db.exceptions.values()
    )
    artifact["status"] = ("REVIEWED_WITH_EXCEPTIONS" if standing
                          else "REVIEWED_CLEAN")
    helpers.touch("artifacts", artifact)
    return ok(serialize("artifact", artifact))


@bp.post("/<aid>/reject")
@require_roles("RiskAnalyst")
def reject_artifact(vid, cid, aid):
    vendor, cycle = _resolve(vid, cid)
    artifact = helpers.get_child(db.artifacts, "cycle_id", cycle, aid,
                                 "EvidenceArtifact")
    if artifact["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Artifact is not UNDER_REVIEW")
    artifact["coverage_gap_days"] = _compute_gap(artifact, cycle)
    artifact["status"] = "REJECTED"
    exception = {
        "cycle_id": cid,
        "source": "EVIDENCE",
        "evidence_artifact_id": aid,
        "severity": "HIGH",
        "description": ("Evidence artifact rejected: coverage gap %s days, "
                        "period %s to %s"
                        % (artifact["coverage_gap_days"],
                           artifact["period_start"], artifact["period_end"])),
        "status": "OPEN",
        "closure_reason": None,
    }
    helpers.stamp_new("exceptions", exception)
    db.exceptions[exception["id"]] = exception
    cycle["open_exception_count"] += 1
    helpers.touch("artifacts", artifact)
    helpers.touch("cycles", cycle)
    return ok(serialize("artifact", artifact))
