"""Product submissions, review decisions and sample inspections (PRD 3.5)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from routes.agreements import find_agreement
from services import domain

bp = Blueprint("submissions", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE]

REVIEW_DECISIONS = ("BEGIN_REVIEW", "REQUEST_REVISION", "REQUEST_SAMPLE", "APPROVE",
                    "REJECT")


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _find(submission_id):
    row = S.submissions.get(submission_id)
    if row is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND")
    return row


def _resolve_marks(mark_ids):
    marks = []
    for mark_id in mark_ids:
        mark = S.marks.get(mark_id)
        if mark is None:
            raise ApiError("ERR_MARK_NOT_FOUND")
        marks.append(mark)
    return marks


def _check_mark_set(agreement, marks):
    """Rule 19: class envelope, then the group/individual rights conflict."""
    category = domain.category_of(agreement)
    envelope = domain.MARK_CLASS_ENVELOPE[category["mark_usage_class"]]
    for mark in marks:
        if mark["owner_type"] not in envelope:
            raise ApiError("ERR_MARK_CLASS_NOT_PERMITTED")
    group_players = {m["player_id"] for m in marks if m["owner_type"] == "PLAYER_GROUP"}
    for mark in marks:
        if mark["owner_type"] == "PLAYER_INDIVIDUAL" and mark["player_id"] in group_players:
            raise ApiError("ERR_MARK_RIGHTS_CONFLICT")


def _check_mark_availability(agreement, marks):
    """Rules 20, 21 and 22 in their fixed order."""
    for mark in marks:
        if mark["status"] != "ACTIVE":
            raise ApiError("ERR_MARK_NOT_ACTIVE")
    for mark in marks:
        if mark["owner_type"] == "PLAYER_GROUP":
            player = S.players.get(mark["player_id"])
            if player is None or not player["group_licensing_opt_in"]:
                raise ApiError("ERR_PLAYER_GROUP_OPT_OUT")
    for mark in marks:
        if mark["owner_type"] == "PLAYER_INDIVIDUAL":
            player = S.players.get(mark["player_id"])
            if player is None or \
                    agreement["category_id"] not in player["individual_grant_category_ids"]:
                raise ApiError("ERR_PLAYER_INDIVIDUAL_GRANT_MISSING")


def _defect_codes(body, required=False):
    if not V.present(body, "defect_codes"):
        if required:
            _bad("defect_codes must hold at least one entry.")
        return []
    codes = V.req_string_list(body, "defect_codes", 1 if required else 0, 20,
                              distinct=False)
    if required and len(codes) < 1:
        _bad("defect_codes must hold at least one entry.")
    return codes


# --------------------------------------------------------------------------- #
# creation, reads and revision                                                #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/agreements/<agreement_id>/product-submissions")
def create_submission(agreement_id):
    ctx = guard([ROLE_LICENSEE, ROLE_MANAGER])
    agreement = find_agreement(agreement_id)
    mw.scope_agreement(ctx, agreement)
    body = ctx.body

    raw_marks = body.get("mark_ids")
    if isinstance(raw_marks, list):
        for mark_id in raw_marks:
            if isinstance(mark_id, str) and mark_id not in S.marks:
                raise ApiError("ERR_MARK_NOT_FOUND")

    sku_class = V.req_enum(body, "sku_class", K.SKU_CLASSES)
    product_name = V.req_string(body, "product_name", 1, 200)
    mark_ids = V.req_string_list(body, "mark_ids", 1, 8)
    retail_price = V.req_cents(body, "retail_price_cents")
    if retail_price <= 0:
        _bad("retail_price_cents must be greater than 0.")
    sample_required = V.opt_bool(body, "sample_required", True)

    marks = _resolve_marks(mark_ids)

    if agreement["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")

    _check_mark_set(agreement, marks)
    _check_mark_availability(agreement, marks)

    row = db.base_row()
    row.update({
        "agreement_id": agreement_id,
        "product_name": product_name,
        "sku_class": sku_class,
        "mark_ids": mark_ids,
        "retail_price_cents": retail_price,
        "sample_required": sample_required,
        "status": "DRAFT",
        "revision_round": 0,
        "review_hold": False,
        "defect_codes": [],
        "approved_mark_snapshot": [],
        "mark_snapshot_stale": False,
        "approved_by_user_id": None,
        "approved_at": None,
        "revocation_reason": None,
        "rejection_reason": None,
    })
    S.submissions[row["id"]] = row
    return response.created(serializers.dump("ProductSubmission", row))


@bp.get("/licensing/product-submissions")
def list_submissions():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    agreement_id = mw.filter_str("agreement_id")
    status = mw.filter_enum("status", K.SUBMISSION_STATUSES)
    sku_class = mw.filter_enum("sku_class", K.SKU_CLASSES)
    review_hold = mw.filter_bool("review_hold")
    stale = mw.filter_bool("mark_snapshot_stale")

    rows = list(S.submissions.values())
    if ctx.role == ROLE_LICENSEE:
        own = {a["id"] for a in domain.agreements_of(ctx.uid)}
        rows = [r for r in rows if r["agreement_id"] in own]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if sku_class is not None:
        rows = [r for r in rows if r["sku_class"] == sku_class]
    if review_hold is not None:
        rows = [r for r in rows if r["review_hold"] == review_hold]
    if stale is not None:
        rows = [r for r in rows if r["mark_snapshot_stale"] == stale]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("ProductSubmission", page),
                            limit, offset, total)


@bp.get("/licensing/product-submissions/<submission_id>")
def get_submission(submission_id):
    ctx = guard(READ_ROLES)
    submission = _find(submission_id)
    mw.scope_agreement(ctx, S.agreements[submission["agreement_id"]])
    return response.ok(serializers.dump("ProductSubmission", submission))


@bp.patch("/licensing/product-submissions/<submission_id>")
def patch_submission(submission_id):
    ctx = guard([ROLE_LICENSEE])
    submission = _find(submission_id)
    agreement = S.agreements[submission["agreement_id"]]
    mw.scope_agreement(ctx, agreement)
    body = ctx.body

    raw_marks = body.get("mark_ids")
    if isinstance(raw_marks, list):
        for mark_id in raw_marks:
            if isinstance(mark_id, str) and mark_id not in S.marks:
                raise ApiError("ERR_MARK_NOT_FOUND")

    changes = {}
    if V.present(body, "product_name"):
        changes["product_name"] = V.req_string(body, "product_name", 1, 200)
    if V.present(body, "retail_price_cents"):
        price = V.req_cents(body, "retail_price_cents")
        if price <= 0:
            _bad("retail_price_cents must be greater than 0.")
        changes["retail_price_cents"] = price
    if V.present(body, "mark_ids"):
        changes["mark_ids"] = V.req_string_list(body, "mark_ids", 1, 8)
    if V.present(body, "sample_required"):
        changes["sample_required"] = V.req_bool(body, "sample_required")

    if submission["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")

    marks = _resolve_marks(changes.get("mark_ids", submission["mark_ids"]))
    _check_mark_set(agreement, marks)

    submission.update(changes)
    touch(submission)
    return response.ok(serializers.dump("ProductSubmission", submission))


# --------------------------------------------------------------------------- #
# submit                                                                      #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/product-submissions/<submission_id>/submit")
def submit_submission(submission_id):
    ctx = guard([ROLE_LICENSEE])
    submission = _find(submission_id)
    agreement = S.agreements[submission["agreement_id"]]
    mw.scope_agreement(ctx, agreement)

    origin = submission["status"]
    if origin not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    if agreement["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "The governing agreement is not ACTIVE.")
    if submission["review_hold"]:
        raise ApiError("ERR_REVIEW_ON_HOLD")
    if agreement["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")

    marks = _resolve_marks(submission["mark_ids"])
    _check_mark_availability(agreement, marks)

    submission["status"] = "SUBMITTED"
    if origin == "REVISION_REQUESTED":
        submission["defect_codes"] = []
    touch(submission)
    return response.ok(serializers.dump("ProductSubmission", submission))


# --------------------------------------------------------------------------- #
# review decisions                                                            #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/product-submissions/<submission_id>/review-decisions")
def review_decision(submission_id):
    ctx = guard([ROLE_MANAGER])
    submission = _find(submission_id)
    agreement = S.agreements[submission["agreement_id"]]
    body = ctx.body
    decision = V.req_enum(body, "decision", REVIEW_DECISIONS)
    codes = _defect_codes(body, required=(decision == "REQUEST_REVISION"))
    note = V.opt_string(body, "note")

    status = submission["status"]
    if decision == "BEGIN_REVIEW":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")
    elif decision == "REQUEST_REVISION":
        if status not in ("IN_REVIEW", "SAMPLE_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE")
    elif decision == "REQUEST_SAMPLE":
        if status != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        if not submission["sample_required"]:
            raise ApiError("ERR_INVALID_STATE",
                           "This submission does not require a physical sample.")
    elif decision == "APPROVE":
        if status == "IN_REVIEW":
            if submission["sample_required"]:
                raise ApiError("ERR_INVALID_STATE",
                               "A sample inspection is required before approval.")
        elif status != "SAMPLE_PASSED":
            raise ApiError("ERR_INVALID_STATE")
        if agreement["contract_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE",
                           "The governing agreement is not ACTIVE.")
    else:
        if status not in ("IN_REVIEW", "SAMPLE_REQUESTED", "SAMPLE_PASSED"):
            raise ApiError("ERR_INVALID_STATE")

    if submission["review_hold"]:
        raise ApiError("ERR_REVIEW_ON_HOLD")
    if agreement["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")

    if decision == "BEGIN_REVIEW":
        submission["status"] = "IN_REVIEW"
        touch(submission)
    elif decision == "REQUEST_REVISION":
        submission["status"] = "REVISION_REQUESTED"
        submission["revision_round"] += 1
        submission["defect_codes"] = codes
        touch(submission)
    elif decision == "REQUEST_SAMPLE":
        submission["status"] = "SAMPLE_REQUESTED"
        touch(submission)
    elif decision == "APPROVE":
        marks = _resolve_marks(submission["mark_ids"])
        _check_mark_set(agreement, marks)
        _check_mark_availability(agreement, marks)
        submission["status"] = "APPROVED"
        submission["approved_mark_snapshot"] = [
            {"mark_id": mark["id"], "mark_version": mark["version"],
             "usage_class": mark["usage_class"]}
            for mark in marks
        ]
        submission["approved_by_user_id"] = ctx.uid
        submission["approved_at"] = db.now_iso()
        submission["mark_snapshot_stale"] = False
        touch(submission)
        domain.refresh_agreement_aggregates(agreement)
    else:
        submission["status"] = "REJECTED"
        submission["rejection_reason"] = note
        touch(submission)
        domain.refresh_risk_index(domain.licensee_of(agreement))

    return response.ok(serializers.dump("ProductSubmission", submission))


# --------------------------------------------------------------------------- #
# sample reviews                                                              #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/product-submissions/<submission_id>/sample-reviews")
def create_sample_review(submission_id):
    ctx = guard([ROLE_COMPLIANCE])
    submission = _find(submission_id)
    agreement = S.agreements[submission["agreement_id"]]
    body = ctx.body
    verdict = V.req_enum(body, "verdict", K.SAMPLE_VERDICTS)
    codes = _defect_codes(body)
    note = V.opt_string(body, "note")

    if submission["status"] != "SAMPLE_REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if submission["review_hold"]:
        raise ApiError("ERR_REVIEW_ON_HOLD")

    review = db.base_row(versioned=False)
    review.update({
        "submission_id": submission_id,
        "verdict": verdict,
        "sample_round": submission["revision_round"] + 1,
        "defect_codes": codes,
        "conditions": note if verdict == "CONDITIONAL_PASS" else None,
        "reviewer_user_id": ctx.uid,
        "occurrence_quarter": db.current_quarter(),
    })
    S.sample_reviews[review["id"]] = review

    if verdict == "FAIL":
        submission["status"] = "REVISION_REQUESTED"
        submission["revision_round"] += 1
        submission["defect_codes"] = codes
        touch(submission)
        domain.refresh_risk_index(domain.licensee_of(agreement))
    else:
        submission["status"] = "SAMPLE_PASSED"
        submission["defect_codes"] = [] if verdict == "PASS" else codes
        touch(submission)

    return response.created(serializers.dump("SampleReview", review))


@bp.get("/licensing/sample-reviews")
def list_sample_reviews():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    submission_id = mw.filter_str("submission_id")
    verdict = mw.filter_enum("verdict", K.SAMPLE_VERDICTS)
    quarter = mw.filter_str("occurrence_quarter")

    rows = list(S.sample_reviews.values())
    if ctx.role == ROLE_LICENSEE:
        own_agreements = {a["id"] for a in domain.agreements_of(ctx.uid)}
        own_subs = {s["id"] for s in S.submissions.values()
                    if s["agreement_id"] in own_agreements}
        rows = [r for r in rows if r["submission_id"] in own_subs]
    if submission_id is not None:
        rows = [r for r in rows if r["submission_id"] == submission_id]
    if verdict is not None:
        rows = [r for r in rows if r["verdict"] == verdict]
    if quarter is not None:
        rows = [r for r in rows if r["occurrence_quarter"] == quarter]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("SampleReview", page),
                            limit, offset, total)


@bp.get("/licensing/sample-reviews/<review_id>")
def get_sample_review(review_id):
    ctx = guard(READ_ROLES)
    review = S.sample_reviews.get(review_id)
    if review is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND")
    submission = S.submissions[review["submission_id"]]
    mw.scope_agreement(ctx, S.agreements[submission["agreement_id"]])
    return response.ok(serializers.dump("SampleReview", review))
