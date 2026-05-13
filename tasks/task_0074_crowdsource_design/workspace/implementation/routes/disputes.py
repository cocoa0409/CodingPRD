"""Dispute routes: file, mediate, escalate, arbitrate, resolve, withdraw, get, list."""
from datetime import timedelta

from flask import Blueprint, request

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, paginate, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import emit_audit


bp = Blueprint("disputes", __name__)


DISPUTE_TYPES = {"PLAGIARISM", "SCORING_FAIRNESS", "COPYRIGHT", "PAYMENT"}
SUBJECT_KINDS = {"SUBMISSION", "REVIEW_ASSIGNMENT", "COPYRIGHT_TRANSFER", "PRIZE_PAYMENT"}
FILER_KINDS = {"CLIENT", "DESIGNER", "REVIEWER", "PLATFORM"}


def _resolve_subject(kind, ref_id):
    if kind == "SUBMISSION":
        return db.submissions.get(ref_id)
    if kind == "REVIEW_ASSIGNMENT":
        return db.review_assignments.get(ref_id)
    if kind == "COPYRIGHT_TRANSFER":
        return db.copyright_transfers.get(ref_id)
    if kind == "PRIZE_PAYMENT":
        return db.prize_payments.get(ref_id)
    return None


def _within_filing_window(dispute_type, subject_kind, subject):
    now = get_now()
    if dispute_type == "SCORING_FAIRNESS":
        # Must be filed before the stage in question transitions to PUBLISHED.
        if subject_kind != "REVIEW_ASSIGNMENT":
            return True
        stage = db.review_stages.get(subject.get("review_stage_id")) if subject else None
        if not stage:
            return True
        return stage.get("status") != "PUBLISHED"
    if dispute_type == "COPYRIGHT":
        if subject_kind == "COPYRIGHT_TRANSFER" and subject:
            reg = subject.get("registered_at")
            if reg is None:
                return True
            return now <= parse_iso(reg) + timedelta(days=14)
        if subject_kind == "SUBMISSION" and subject:
            # Find the transfer for this submission
            sid = subject.get("id")
            for t in db.copyright_transfers.values():
                if t.get("submission_id") == sid and t.get("status") == "REGISTERED":
                    reg = t.get("registered_at")
                    if reg is None:
                        return True
                    return now <= parse_iso(reg) + timedelta(days=14)
            return True
        return True
    if dispute_type == "PAYMENT":
        if subject_kind == "PRIZE_PAYMENT" and subject:
            if subject.get("status") != "PAID":
                return True
            paid_at = subject.get("updated_at")
            if not paid_at:
                return True
            return now <= parse_iso(paid_at) + timedelta(days=14)
        return True
    # PLAGIARISM: always within window per PRD
    return True


@bp.route("/disputes", methods=["POST"])
def file_dispute():
    user_id, role = require_roles({"Client", "Designer", "Reviewer", "PlatformOps"})
    body = get_json_body()
    project_id = body.get("project_id")
    dispute_type = body.get("dispute_type")
    subject_ref_kind = body.get("subject_ref_kind")
    subject_ref_id = body.get("subject_ref_id")
    filer_kind = body.get("filer_kind")
    filer_id = body.get("filer_id")
    evidence_urls = body.get("evidence_urls", []) or []

    if project_id not in db.projects:
        raise api_error("ERR_FK_NOT_FOUND", "project_id not found")
    if dispute_type not in DISPUTE_TYPES:
        raise api_error("ERR_VALIDATION", "dispute_type invalid")
    if subject_ref_kind not in SUBJECT_KINDS:
        raise api_error("ERR_VALIDATION", "subject_ref_kind invalid")
    subject = _resolve_subject(subject_ref_kind, subject_ref_id)
    if subject is None:
        raise api_error("ERR_FK_NOT_FOUND", f"{subject_ref_kind} {subject_ref_id} not found")
    if filer_kind not in FILER_KINDS:
        raise api_error("ERR_VALIDATION", "filer_kind invalid")

    # Filer identity check
    if role == "Client":
        if filer_kind != "CLIENT" or filer_id != user_id:
            raise api_error("ERR_FORBIDDEN", "Client filer must be self with filer_kind=CLIENT")
        if filer_id not in db.clients:
            raise api_error("ERR_FK_NOT_FOUND", "filer_id not found")
    elif role == "Designer":
        if filer_kind != "DESIGNER" or filer_id != user_id:
            raise api_error("ERR_FORBIDDEN", "Designer filer must be self with filer_kind=DESIGNER")
        if filer_id not in db.designers:
            raise api_error("ERR_FK_NOT_FOUND", "filer_id not found")
    elif role == "Reviewer":
        if filer_kind != "REVIEWER" or filer_id != user_id:
            raise api_error("ERR_FORBIDDEN", "Reviewer filer must be self with filer_kind=REVIEWER")
        if filer_id not in db.reviewers:
            raise api_error("ERR_FK_NOT_FOUND", "filer_id not found")
    else:  # PlatformOps
        if filer_kind != "PLATFORM":
            raise api_error("ERR_FORBIDDEN", "PlatformOps filer must use filer_kind=PLATFORM")

    if not isinstance(evidence_urls, list) or len(evidence_urls) > 20:
        raise api_error("ERR_VALIDATION", "evidence_urls must be a list of <= 20 items")

    within = _within_filing_window(dispute_type, subject_ref_kind, subject)
    if not within:
        raise api_error("ERR_DISPUTE_WINDOW_CLOSED", "filing window has closed")

    dispute = stamp_new({
        "project_id": project_id,
        "dispute_type": dispute_type,
        "subject_ref_kind": subject_ref_kind,
        "subject_ref_id": subject_ref_id,
        "filer_kind": filer_kind,
        "filer_id": filer_id,
        "evidence_urls": list(evidence_urls),
        "status": "FILED",
        "resolution_note": None,
        "filed_within_window": True,
    })
    db.disputes[dispute["id"]] = dispute
    emit_audit(
        "DISPUTE_FILED",
        filer_kind if filer_kind != "PLATFORM" else "PLATFORM",
        user_id,
        "DISPUTE",
        dispute["id"],
        {"dispute_type": dispute_type, "subject_ref_kind": subject_ref_kind, "subject_ref_id": subject_ref_id},
    )

    # Cascade: SCORING_FAIRNESS targeting REVIEW_ASSIGNMENT -> assignment SUBMITTED -> DISPUTED
    if dispute_type == "SCORING_FAIRNESS" and subject_ref_kind == "REVIEW_ASSIGNMENT":
        asn = subject
        if asn.get("status") == "SUBMITTED":
            asn["status"] = "DISPUTED"
            stamp_update(asn)
            emit_audit(
                "REVIEW_DISPUTED",
                "PLATFORM",
                user_id,
                "REVIEW_ASSIGNMENT",
                asn["id"],
                {"dispute_id": dispute["id"]},
            )
    return success(dispute, status=201)


@bp.route("/disputes/<dispute_id>/start-mediation", methods=["POST"])
def start_mediation(dispute_id):
    require_roles({"PlatformOps"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    body = get_json_body()
    check_version(d, body)
    if d.get("status") != "FILED":
        raise api_error("ERR_INVALID_STATE", "dispute must be FILED")
    d["status"] = "MEDIATING_STAGE1"
    stamp_update(d)
    return success(d)


@bp.route("/disputes/<dispute_id>/escalate", methods=["POST"])
def escalate(dispute_id):
    require_roles({"PlatformOps"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    body = get_json_body()
    check_version(d, body)
    if d.get("status") != "MEDIATING_STAGE1":
        raise api_error("ERR_INVALID_STATE", "dispute must be MEDIATING_STAGE1")
    d["status"] = "MEDIATING_STAGE2"
    stamp_update(d)
    return success(d)


@bp.route("/disputes/<dispute_id>/request-arbitration", methods=["POST"])
def request_arbitration(dispute_id):
    user_id, role = require_roles({"PlatformOps", "Client", "Designer"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    body = get_json_body()
    check_version(d, body)
    if d.get("status") != "MEDIATING_STAGE2":
        raise api_error("ERR_INVALID_STATE", "dispute must be MEDIATING_STAGE2")
    d["status"] = "ARBITRATION"
    stamp_update(d)
    return success(d)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    user_id, _ = require_roles({"PlatformOps"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    body = get_json_body()
    check_version(d, body)
    outcome = body.get("outcome")
    note = body.get("resolution_note")
    if outcome not in {"UPHELD", "REJECTED"}:
        raise api_error("ERR_VALIDATION", "outcome must be UPHELD or REJECTED")
    if not isinstance(note, str) or not note:
        raise api_error("ERR_VALIDATION", "resolution_note required")
    if d.get("status") not in {"MEDIATING_STAGE1", "MEDIATING_STAGE2", "ARBITRATION"}:
        raise api_error("ERR_INVALID_STATE",
                        "dispute must be in MEDIATING_STAGE1/MEDIATING_STAGE2/ARBITRATION to resolve")

    if outcome == "UPHELD":
        d["status"] = "RESOLVED_UPHELD"
    else:
        d["status"] = "RESOLVED_REJECTED"
    d["resolution_note"] = note
    stamp_update(d)
    emit_audit(
        "DISPUTE_RESOLVED",
        "PLATFORM",
        user_id,
        "DISPUTE",
        d["id"],
        {"outcome": outcome},
    )

    # Cascades on REJECTED for SCORING_FAIRNESS: revert DISPUTED -> SUBMITTED, recompute stage aggregate.
    if outcome == "REJECTED" and d.get("dispute_type") == "SCORING_FAIRNESS" \
            and d.get("subject_ref_kind") == "REVIEW_ASSIGNMENT":
        asn = db.review_assignments.get(d.get("subject_ref_id"))
        if asn and asn.get("status") == "DISPUTED":
            asn["status"] = "SUBMITTED"
            stamp_update(asn)
            _recompute_stage_aggregate_for_assignment(asn)

    # Cascades on UPHELD
    if outcome == "UPHELD":
        if d.get("dispute_type") == "SCORING_FAIRNESS" and d.get("subject_ref_kind") == "REVIEW_ASSIGNMENT":
            asn = db.review_assignments.get(d.get("subject_ref_id"))
            if asn:
                asn["status"] = "VOIDED"
                stamp_update(asn)
                emit_audit(
                    "REVIEW_VOIDED",
                    "SYSTEM",
                    user_id,
                    "REVIEW_ASSIGNMENT",
                    asn["id"],
                    {"dispute_id": d["id"]},
                )
                _recompute_stage_aggregate_for_assignment(asn)
                # Reviewer-quorum recovery: if any in-stage submission falls below quorum,
                # revert AGGREGATING -> OPEN.
                stage = db.review_stages.get(asn.get("review_stage_id"))
                if stage and stage.get("status") == "AGGREGATING":
                    project = db.projects.get(stage.get("project_id"))
                    submissions = _stage_in_scope(stage)
                    for sub in submissions:
                        cnt = sum(
                            1 for a in db.review_assignments.values()
                            if a.get("review_stage_id") == stage["id"]
                            and a.get("submission_id") == sub["id"]
                            and a.get("status") == "SUBMITTED"
                        )
                        if cnt < stage["reviewer_quorum"]:
                            stage["status"] = "OPEN"
                            stamp_update(stage)
                            break

        elif d.get("dispute_type") in {"COPYRIGHT", "PLAGIARISM"}:
            # Caller is expected to follow with a /copyright-transfers/{id}/void call.
            pass
        elif d.get("dispute_type") == "PAYMENT":
            sid = d.get("subject_ref_id")
            payment = db.prize_payments.get(sid)
            if payment and payment.get("status") in {"SCHEDULED", "PAYING", "PAID"}:
                prior = payment["status"]
                payment["status"] = "REVERSED"
                stamp_update(payment)
                emit_audit(
                    "PRIZE_PAID",
                    "SYSTEM",
                    user_id,
                    "PRIZE_PAYMENT",
                    payment["id"],
                    {"reversal_note": f"reversed from {prior} due to upheld payment dispute"},
                )
                key = payment.get("idempotency_key")
                if key and db.payment_idempotency_index.get(key) == payment["id"]:
                    del db.payment_idempotency_index[key]

    return success(d)


@bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw_dispute(dispute_id):
    user_id, _ = require_roles({"Client", "Designer"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    body = get_json_body()
    check_version(d, body)
    if d.get("status") != "FILED":
        raise api_error("ERR_INVALID_STATE", "only FILED disputes can be withdrawn")
    if d.get("filer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "only the original filer can withdraw")
    d["status"] = "WITHDRAWN"
    stamp_update(d)
    return success(d)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    user_id, role = require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    d = db.disputes.get(dispute_id)
    if not d:
        raise api_error("ERR_NOT_FOUND", "dispute not found")
    return success(d)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    require_roles({"PlatformOps", "Client", "Designer"})
    items = list(db.disputes.values())
    project_id = request.args.get("project_id")
    dispute_type = request.args.get("dispute_type")
    status = request.args.get("status")
    if project_id:
        items = [d for d in items if d.get("project_id") == project_id]
    if dispute_type:
        items = [d for d in items if d.get("dispute_type") == dispute_type]
    if status:
        items = [d for d in items if d.get("status") == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# --- internal helpers ------------------------------------------------------


def _stage_in_scope(stage):
    """Submissions still expected to be evaluated by this stage."""
    project_id = stage["project_id"]
    kind = stage["stage_kind"]
    if kind == "PRELIMINARY":
        statuses = {"ACCEPTED", "ADVANCING_SEMIFINAL", "ELIMINATED"}
    elif kind == "SEMIFINAL":
        statuses = {"ADVANCING_SEMIFINAL", "ADVANCING_FINAL", "ELIMINATED"}
    else:
        statuses = {"ADVANCING_FINAL", "WINNER", "RUNNER_UP", "ELIMINATED"}
    return [s for s in db.submissions.values()
            if s.get("project_id") == project_id and s.get("status") in statuses]


def _recompute_stage_aggregate_for_assignment(asn):
    """Recompute the affected submission's aggregate after a status change."""
    stage = db.review_stages.get(asn.get("review_stage_id"))
    if not stage:
        return
    sub = db.submissions.get(asn.get("submission_id"))
    if not sub:
        return
    project = db.projects.get(stage.get("project_id"))
    scores = []
    client_id = project.get("client_id") if project else None
    for a in db.review_assignments.values():
        if (a.get("review_stage_id") == stage["id"]
                and a.get("submission_id") == sub["id"]
                and a.get("status") == "SUBMITTED"):
            scores.append({
                "id": a["id"],
                "score": a.get("aggregated_score", 0),
                "is_client": a.get("reviewer_id") == client_id,
            })
    from services.calculations import stage_aggregate
    if len(scores) >= stage["reviewer_quorum"]:
        agg = stage_aggregate(
            scores, stage["stage_kind"],
            project.get("client_participates_final", False) if project else False,
        )
        m = dict(sub.get("aggregate_score_by_stage") or {})
        if agg is not None:
            m[stage["stage_kind"]] = agg
        else:
            m.pop(stage["stage_kind"], None)
        sub["aggregate_score_by_stage"] = m
        stamp_update(sub)
    else:
        # Remove the stale aggregate so quorum recovery is required.
        m = dict(sub.get("aggregate_score_by_stage") or {})
        if stage["stage_kind"] in m:
            m.pop(stage["stage_kind"], None)
            sub["aggregate_score_by_stage"] = m
            stamp_update(sub)
