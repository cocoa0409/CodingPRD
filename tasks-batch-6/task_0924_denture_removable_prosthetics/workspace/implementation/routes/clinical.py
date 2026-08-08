"""Impression capture with the three-band quality review (PRD 3.3) and try-in
milestones with the type-parameterised sequence (PRD 3.4)."""
from flask import Blueprint

import calc
import domain
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import db, now, sorted_rows, touch
from util import ZERO

bp = Blueprint("clinical", __name__)

CLINICAL_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


# ===========================================================================
# ImpressionRecord
# ===========================================================================
@bp.post("/prosthetics/impressions")
@guards.endpoint(["Prosthodontist"])
def create_impression(ctx):
    arch = guards.fk_row(ctx, "case_arch_id")
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.body_fks(ctx, ["case_arch_id"])  # rung 6
    guards.require_string(ctx, "case_arch_id")  # rung 7
    capture_method = guards.require_enum_value(ctx, "capture_method")
    guards.check_enum("capture_method", capture_method)  # rung 8
    if arch["arch_status"] != "IMPRESSION_PENDING":  # rung 13
        raise ApiError("ERR_CROSS_ENTITY_STATE")

    row = db.create(
        "impressions",
        {
            "case_arch_id": arch["id"],
            "capture_method": capture_method,
            "attempt_number": arch["retake_count"] + 1,
            "quality_score": None,
            "quality_status": "PENDING_REVIEW",
            "reviewed_at": None,
            "superseded_by_impression_id": None,
        },
    )
    return envelope.created(projections.impression(row))


@bp.get("/prosthetics/impressions/<impression_id>")
@guards.endpoint(CLINICAL_READ)
def get_impression(ctx, impression_id):
    row = guards.path_row("impression_id", impression_id)
    return envelope.ok(projections.impression(row))


@bp.get("/prosthetics/impressions")
@guards.endpoint(CLINICAL_READ)
def list_impressions(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.impressions.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_arch_id", "case_arch_id", None),
            (
                "quality_status",
                "quality_status",
                guards.status_members("quality_status"),
            ),
            ("superseded_by_impression_id", "superseded_by_impression_id", None),
        ],
    )
    return envelope.listing(
        [projections.impression(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/impressions/<impression_id>/review")
@guards.endpoint(["Prosthodontist"])
def review_impression(ctx, impression_id):
    record = guards.path_row("impression_id", impression_id)  # rung 4
    # Outside the global write gate: the appointment already happened.
    score = guards.require_int(  # rung 7
        ctx,
        "quality_score",
        pconst.IMPRESSION_SCORE_MIN,
        pconst.IMPRESSION_SCORE_MAX,
    )
    guards.terminal_guard(record, "quality_status")  # rung 10
    guards.from_state_guard(record, "quality_status", ("PENDING_REVIEW",))  # rung 12

    band = calc.impression_quality_band(score)
    record["quality_score"] = score
    record["quality_status"] = band
    record["reviewed_at"] = now()
    touch(record)

    if band == "ACCEPTED":
        arch = nav.arch_of(record)
        if arch is not None and arch["arch_status"] == "IMPRESSION_PENDING":
            if arch["required_milestones"]:
                arch["arch_status"] = "MILESTONE_PENDING"
                # The declared MILESTONE_PENDING -> LAB_FABRICATION transition
                # fires as soon as its precondition holds -- next_required_
                # milestone is null.  That is already the case on a remake
                # restart, whose arch carries every required milestone in
                # completed_milestones from the round before.  The empty-list
                # branch below still holds only for an IMMEDIATE_DENTURE.
                if domain.arch_next_required_milestone(arch) is None:
                    arch["arch_status"] = "LAB_FABRICATION"
            else:
                arch["arch_status"] = "LAB_FABRICATION"
            touch(arch)
    return envelope.ok(projections.impression(record))


@bp.post("/prosthetics/impressions/<impression_id>/request-retake")
@guards.endpoint(["Prosthodontist"])
def request_retake(ctx, impression_id):
    record = guards.path_row("impression_id", impression_id)  # rung 4
    arch = nav.arch_of(record)
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    capture_method = guards.require_enum_value(ctx, "capture_method")  # rung 7
    guards.check_enum("capture_method", capture_method)  # rung 8
    guards.terminal_guard(record, "quality_status")  # rung 10
    guards.from_state_guard(  # rung 12
        record, "quality_status", ("PROVISIONAL_ACCEPTED", "REJECTED")
    )
    if arch["retake_count"] >= pconst.IMPRESSION_RETAKE_CEILING:  # rung 17
        raise ApiError("ERR_RETAKE_LIMIT_EXCEEDED")

    arch["retake_count"] = arch["retake_count"] + 1
    touch(arch)

    successor = db.create(
        "impressions",
        {
            "case_arch_id": arch["id"],
            "capture_method": capture_method,
            "attempt_number": record["attempt_number"] + 1,
            "quality_score": None,
            "quality_status": "PENDING_REVIEW",
            "reviewed_at": None,
            "superseded_by_impression_id": None,
        },
    )

    record["quality_status"] = "SUPERSEDED"
    record["superseded_by_impression_id"] = successor["id"]
    touch(record)

    # The response body is the SUPERSEDED row, not the successor.
    return envelope.ok(projections.impression(record))


# ===========================================================================
# TryInMilestone
# ===========================================================================
@bp.post("/prosthetics/try-ins")
@guards.endpoint(["Prosthodontist"])
def create_tryin(ctx):
    arch = guards.fk_row(ctx, "case_arch_id")
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.body_fks(ctx, ["case_arch_id"])  # rung 6
    guards.require_string(ctx, "case_arch_id")  # rung 7
    milestone_kind = guards.require_enum_value(ctx, "milestone_kind")
    guards.check_enum("milestone_kind", milestone_kind)  # rung 8
    if arch["arch_status"] != "MILESTONE_PENDING":  # rung 13
        raise ApiError("ERR_CROSS_ENTITY_STATE")
    if milestone_kind != domain.arch_next_required_milestone(arch):  # rung 16
        raise ApiError("ERR_MILESTONE_SEQUENCE")

    row = db.create(
        "tryins",
        {
            "case_arch_id": arch["id"],
            "milestone_kind": milestone_kind,
            "approval_status": "PENDING_APPROVAL",
            "adjust_count": 0,
            "decided_at": None,
            "decided_by_user_id": None,
        },
    )
    return envelope.created(projections.tryin(row))


@bp.get("/prosthetics/try-ins/<try_in_id>")
@guards.endpoint(CLINICAL_READ)
def get_tryin(ctx, try_in_id):
    row = guards.path_row("try_in_id", try_in_id)
    return envelope.ok(projections.tryin(row))


@bp.get("/prosthetics/try-ins")
@guards.endpoint(CLINICAL_READ)
def list_tryins(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.tryins.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_arch_id", "case_arch_id", None),
            (
                "approval_status",
                "approval_status",
                guards.status_members("approval_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.tryin(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/try-ins/<try_in_id>/decide")
@guards.endpoint(["Prosthodontist"])
def decide_tryin(ctx, try_in_id):
    milestone = guards.path_row("try_in_id", try_in_id)  # rung 4
    # Outside the global write gate: judging an appointment that already
    # happened is not a new start.
    decision = guards.require_enum_value(ctx, "decision")  # rung 7
    guards.check_enum("decision", decision)  # rung 8
    guards.terminal_guard(milestone, "approval_status")  # rung 10

    origins = ("ADJUST_REQUESTED",) if decision == "RESUBMIT" else ("PENDING_APPROVAL",)
    guards.from_state_guard(milestone, "approval_status", origins)  # rung 12

    arch = nav.arch_of(milestone)
    if decision == "APPROVE":  # rung 16
        if milestone["milestone_kind"] != domain.arch_next_required_milestone(arch):
            raise ApiError("ERR_MILESTONE_SEQUENCE")
    if decision == "ADJUST":  # rung 18
        if milestone["adjust_count"] >= pconst.TRYIN_ADJUST_CEILING:
            raise ApiError("ERR_TRYIN_LIMIT_EXCEEDED")

    milestone["decided_at"] = now()
    milestone["decided_by_user_id"] = ctx.user_id

    if decision == "APPROVE":
        milestone["approval_status"] = "APPROVED"
        touch(milestone)
        if domain.arch_next_required_milestone(arch) is None:
            if arch["arch_status"] == "MILESTONE_PENDING":
                arch["arch_status"] = "LAB_FABRICATION"
                touch(arch)
    elif decision == "ADJUST":
        milestone["approval_status"] = "ADJUST_REQUESTED"
        milestone["adjust_count"] = milestone["adjust_count"] + 1
        touch(milestone)
    elif decision == "RESUBMIT":
        # adjust_count is deliberately NOT reset: the ceiling is cumulative.
        milestone["approval_status"] = "PENDING_APPROVAL"
        touch(milestone)
    else:  # REJECT
        milestone["approval_status"] = "REJECTED_FOR_REMAKE"
        touch(milestone)
        domain.create_remake_request(arch, "TRYIN_REJECTED", ctx.user_id, None)

    return envelope.ok(projections.tryin(milestone))
