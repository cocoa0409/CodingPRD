"""Deliverables, cuts, technical QC, the client review loop and change orders.

PRD 3.1 (registration), 3.8 (post-production), 3.9 (change orders).
"""

from flask import Blueprint, request

import calc
import derive
import workflow
from auth import authenticate
from envelope import respond_created, respond_list, respond_object
from errors import ApiError
from lookups import find_change_order, find_deliverable, find_project, find_version
from store import clock_now, db, iso, new_row, touch
from validation import (field_boolean, field_enum, field_identifier, field_instant,
                        field_integer, field_number, field_string, json_body,
                        paginate, pagination)

bp = Blueprint("deliverables", __name__)

CHANNELS = ("BROADCAST", "OLV", "SOCIAL", "INTERNAL", "OOH")
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:5", "2.39:1")
CAPTION_VALUES = ("NONE", "CLOSED_SRT", "BURNED_IN_SUBTITLES", "OPEN_CAPTIONS")
DELIVERABLE_OPEN_FOR_CUTS = ("PENDING", "IN_REVIEW", "CHANGES_REQUESTED")

REVIEW_DECISIONS = ("APPROVE", "REQUEST_CHANGES")
CHANGE_ORDER_DECISIONS = ("APPROVE", "REJECT", "VOID")


# --------------------------------------------------------------------------
# Deliverables
# --------------------------------------------------------------------------
@bp.get("/deliverables/<deliverable_id>")
def read_deliverable(deliverable_id):
    authenticate(("ProductionCoordinator", "LineProducer", "PostSupervisor", "ClientApprover"))
    deliverable = find_deliverable(deliverable_id)
    return respond_object(derive.deliverable_out(deliverable))


@bp.get("/deliverables/<deliverable_id>/change-orders")
def list_deliverable_change_orders(deliverable_id):
    authenticate(("ProductionCoordinator", "LineProducer", "ClientApprover"))
    limit, offset = pagination()
    deliverable = find_deliverable(deliverable_id)
    rows = derive.deliverable_change_orders(deliverable["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    trigger_reason = request.args.get("trigger_reason")
    if trigger_reason is not None:
        rows = [r for r in rows if r["trigger_reason"] == trigger_reason]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.change_order_out(r) for r in page], limit, offset, total)


@bp.post("/deliverables")
def create_deliverable():
    caller = authenticate(("ProductionCoordinator", "LineProducer"))
    body = json_body()
    project_id = field_identifier(body, "project_id")
    title = field_string(body, "title", 1, 120)
    channel = field_enum(body, "channel", CHANNELS)
    aspect_ratio = field_enum(body, "aspect_ratio", ASPECT_RATIOS)
    target_duration_seconds = field_integer(body, "target_duration_seconds", 1, 3600)
    caption_requirement = field_enum(body, "caption_requirement", CAPTION_VALUES)
    usage_rights_months = field_integer(body, "usage_rights_months", 1, 60)
    air_date = field_instant(body, "air_date")

    project = find_project(project_id)
    if project["status"] not in ("DRAFT", "SCOPED", "IN_PRODUCTION", "IN_POST"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Deliverables may not be registered while the project is %s."
                       % project["status"])
    if channel not in project["channel_scope"]:
        raise ApiError("ERR_CHANNEL_OUT_OF_SCOPE",
                       "Channel %s is outside the project's licensed channel scope." % channel)
    if usage_rights_months > project["usage_term_months"]:
        raise ApiError("ERR_USAGE_RIGHTS_EXCEED_TERM",
                       "usage_rights_months %d exceeds the project's master term of %d months."
                       % (usage_rights_months, project["usage_term_months"]))

    watch = workflow.LedgerWatch(project)
    row = new_row(
        project_id=project["id"],
        title=title,
        channel=channel,
        aspect_ratio=aspect_ratio,
        target_duration_seconds=target_duration_seconds,
        caption_requirement=caption_requirement,
        usage_rights_months=usage_rights_months,
        air_date=iso(air_date),
        status="PENDING",
    )
    db["deliverables"][row["id"]] = row
    # Registering after the scope lock buys a new deliverable, priced as a
    # change order that grants no extra review round (PRD 3.9).
    if project["status"] != "DRAFT":
        workflow.create_change_order(row, "DELIVERABLE_ADDED_AFTER_SCOPE_LOCK", 0, caller.user_id)
    watch.finish()
    return respond_created(derive.deliverable_out(row))


# --------------------------------------------------------------------------
# Cuts
# --------------------------------------------------------------------------
@bp.get("/deliverable-versions/<version_id>")
def read_version(version_id):
    authenticate(("ProductionCoordinator", "LineProducer", "PostSupervisor", "ClientApprover"))
    version = find_version(version_id)
    return respond_object(derive.deliverable_version_out(version))


@bp.get("/deliverable-versions")
def list_versions():
    authenticate(("ProductionCoordinator", "LineProducer", "PostSupervisor", "ClientApprover"))
    limit, offset = pagination()
    rows = list(db["deliverable_versions"].values())
    deliverable_id = request.args.get("deliverable_id")
    if deliverable_id is not None:
        rows = [r for r in rows if r["deliverable_id"] == deliverable_id]
    supersedes = request.args.get("supersedes_version_id")
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_version_id"] == supersedes]
    review_status = request.args.get("review_status")
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    technical_status = request.args.get("technical_status")
    if technical_status is not None:
        rows = [r for r in rows if r["technical_status"] == technical_status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.deliverable_version_out(r) for r in page], limit, offset, total)


@bp.post("/deliverable-versions")
def create_version():
    authenticate(("PostSupervisor",))
    body = json_body()
    deliverable_id = field_identifier(body, "deliverable_id")
    expected_deliverable_version = field_integer(body, "expected_deliverable_version", 0)
    cut_label = field_string(body, "cut_label", 1, 80)
    aspect_ratio = field_enum(body, "aspect_ratio", ASPECT_RATIOS)
    duration_seconds = field_integer(body, "duration_seconds", 1, 3600)
    has_captions = field_boolean(body, "has_captions", required=False, default=False)
    caption_format = field_enum(body, "caption_format", CAPTION_VALUES,
                                required=False, default="NONE")
    file_size_gb = field_number(body, "file_size_gb", minimum=0, required=False, default=0)
    supersedes_version_id = field_identifier(body, "supersedes_version_id", required=False,
                                             default=None)

    deliverable = find_deliverable(deliverable_id)
    superseded = None
    if supersedes_version_id is not None:
        superseded = find_version(supersedes_version_id)

    if expected_deliverable_version != deliverable["version"]:
        raise ApiError("ERR_STALE_DELIVERABLE_VERSION",
                       "expected_deliverable_version %d does not match the deliverable's "
                       "current version %d."
                       % (expected_deliverable_version, deliverable["version"]))
    if deliverable["status"] not in DELIVERABLE_OPEN_FOR_CUTS:
        raise ApiError("ERR_DELIVERABLE_STATE_INVALID",
                       "A deliverable in %s accepts no further cuts." % deliverable["status"])
    if superseded is not None:
        if superseded["deliverable_id"] != deliverable["id"] \
                or superseded["review_status"] != "CHANGES_REQUESTED":
            raise ApiError("ERR_VERSION_DELIVERABLE_MISMATCH",
                           "supersedes_version_id must name a CHANGES_REQUESTED cut of the "
                           "same deliverable.")

    row = new_row(
        deliverable_id=deliverable["id"],
        supersedes_version_id=supersedes_version_id,
        cut_label=cut_label,
        round_index=derive.consumed_review_rounds(deliverable["id"]) + 1,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        has_captions=has_captions,
        caption_format=caption_format,
        file_size_gb=file_size_gb,
        review_status="DRAFT",
        technical_status="PENDING_QC",
        qc_failure_reasons=[],
        submitted_by_user_id=None,
        reviewed_by_user_id=None,
        submitted_at=None,
        decided_at=None,
    )
    db["deliverable_versions"][row["id"]] = row
    touch(deliverable)
    if superseded is not None:
        superseded["review_status"] = "SUPERSEDED"
        touch(superseded)
    return respond_created(derive.deliverable_version_out(row))


@bp.post("/deliverable-versions/<version_id>/qc")
def record_qc(version_id):
    authenticate(("PostSupervisor",))
    json_body(required=False)
    version = find_version(version_id)
    if version["technical_status"] != "PENDING_QC":
        raise ApiError("ERR_QC_ALREADY_RECORDED",
                       "Technical QC has already been recorded for this cut.")
    deliverable = derive.deliverable_of_version(version)
    findings = calc.version_qc_evaluation(version, deliverable)
    version["qc_failure_reasons"] = findings
    version["technical_status"] = "QC_FAILED" if findings else "QC_PASSED"
    touch(version)
    return respond_object(derive.deliverable_version_out(version))


@bp.post("/deliverable-versions/<version_id>/submit")
def submit_version(version_id):
    caller = authenticate(("PostSupervisor",))
    json_body(required=False)
    version = find_version(version_id)
    deliverable = derive.deliverable_of_version(version)
    project = derive.project_of_deliverable(deliverable)

    if project["status"] not in ("IN_PRODUCTION", "IN_POST"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Cut submission requires the project to be IN_PRODUCTION or IN_POST.")
    if deliverable["status"] not in ("PENDING", "CHANGES_REQUESTED"):
        raise ApiError("ERR_DELIVERABLE_STATE_INVALID",
                       "A deliverable in %s does not accept a submission." % deliverable["status"])
    if version["review_status"] != "DRAFT":
        raise ApiError("ERR_VERSION_REVIEW_STATE_INVALID",
                       "Submission requires the cut's review_status to be DRAFT.")
    if version["technical_status"] != "QC_PASSED":
        raise ApiError("ERR_VERSION_QC_NOT_PASSED",
                       "A cut whose technical_status is %s may not be submitted."
                       % version["technical_status"])
    if derive.consumed_review_rounds(deliverable["id"]) >= derive.round_entitlement(deliverable):
        raise ApiError("ERR_REVISION_ROUNDS_EXHAUSTED",
                       "The deliverable has consumed its entire review-round entitlement.")
    if derive.review_gate(project) != "OPEN":
        raise ApiError("ERR_CHANGE_ORDER_PENDING",
                       "A pending change order freezes cut submission across the project.")

    version["review_status"] = "SUBMITTED"
    version["submitted_by_user_id"] = caller.user_id
    version["submitted_at"] = iso(clock_now())
    touch(version)
    # bubble up: PENDING -> IN_REVIEW on a first cut, CHANGES_REQUESTED -> IN_REVIEW later
    deliverable["status"] = "IN_REVIEW"
    touch(deliverable)
    return respond_object(derive.deliverable_version_out(version))


@bp.post("/deliverable-versions/<version_id>/review-decision")
def review_decision(version_id):
    caller = authenticate(("ClientApprover",))
    body = json_body()
    decision = field_enum(body, "decision", REVIEW_DECISIONS)
    review_note = field_string(body, "review_note", 1, 2000, required=False, default=None)
    version = find_version(version_id)
    deliverable = derive.deliverable_of_version(version)
    project = derive.project_of_deliverable(deliverable)

    if project["status"] not in ("IN_PRODUCTION", "IN_POST"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "A review decision requires the project to be IN_PRODUCTION or IN_POST.")
    if version["review_status"] != "SUBMITTED":
        raise ApiError("ERR_VERSION_REVIEW_STATE_INVALID",
                       "A review decision requires the cut's review_status to be SUBMITTED.")
    if caller.user_id == version["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who submitted this cut may not record its review decision.")

    watch = workflow.LedgerWatch(project)
    version["reviewed_by_user_id"] = caller.user_id
    version["decided_at"] = iso(clock_now())
    version["_review_note"] = review_note

    if decision == "APPROVE":
        version["review_status"] = "APPROVED"
        touch(version)
        if deliverable["status"] == "IN_REVIEW":
            deliverable["status"] = "APPROVED"
            touch(deliverable)
        workflow.bubble_project_into_delivered(project)
    else:
        version["review_status"] = "CHANGES_REQUESTED"
        touch(version)
        # The append-only decision log is what consumed_review_rounds counts:
        # superseding the cut later must not erase the round it consumed.
        db["review_decisions"].append({
            "deliverable_id": deliverable["id"],
            "deliverable_version_id": version["id"],
            "decision": "REQUEST_CHANGES",
            "reviewed_by_user_id": caller.user_id,
        })
        # hop one
        deliverable["status"] = "CHANGES_REQUESTED"
        touch(deliverable)
        # hop two: the entitlement is now spent, so the extra round is priced
        if derive.consumed_review_rounds(deliverable["id"]) \
                >= derive.round_entitlement(deliverable):
            workflow.create_change_order(deliverable, "REVISION_ROUND_EXCEEDED", 1,
                                         caller.user_id)
    # hops three and four: the ledgers, the variance and the balance follow
    watch.finish()
    return respond_object(derive.deliverable_version_out(version))


# --------------------------------------------------------------------------
# Change orders
# --------------------------------------------------------------------------
@bp.post("/change-orders/<change_order_id>/decision")
def decide_change_order(change_order_id):
    caller = authenticate(("ClientApprover", "LineProducer"))
    body = json_body()
    decision = field_enum(body, "decision", CHANGE_ORDER_DECISIONS)
    decision_note = field_string(body, "decision_note", 1, 2000, required=False, default=None)
    change_order = find_change_order(change_order_id)

    if decision in ("APPROVE", "REJECT"):
        if change_order["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_CHANGE_ORDER_STATE_INVALID",
                           "An %s decision requires the change order to be PENDING_APPROVAL."
                           % decision)
    elif change_order["status"] != "APPROVED":
        raise ApiError("ERR_CHANGE_ORDER_STATE_INVALID",
                       "A VOID decision requires the change order to be APPROVED.")
    if caller.user_id == change_order["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who requested this change order may not decide it.")

    project = derive.project_of_change_order(change_order)
    watch = workflow.LedgerWatch(project)
    change_order["approved_by_user_id"] = caller.user_id
    change_order["_decision_note"] = decision_note
    if decision == "APPROVE":
        change_order["status"] = "APPROVED"
    elif decision == "REJECT":
        change_order["status"] = "REJECTED"
    else:
        change_order["status"] = "VOIDED"
    touch(change_order)
    watch.finish()
    return respond_object(derive.change_order_out(change_order))
