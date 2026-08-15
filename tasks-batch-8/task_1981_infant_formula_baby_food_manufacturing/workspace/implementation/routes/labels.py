"""LabelSubmission endpoints."""
from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import authorized
from response import ok, paginate
from services import ser_label, get_or_404, stamp_new, touch, SUBMISSION_TYPES
from util import get_body, require_fields, check_enum

bp = Blueprint("labels", __name__)

LABEL_ROLES = ("REGULATORY_AFFAIRS", "QA_MANAGER")


def _maybe_accept_comments(body, rec):
    """review_comments has no dedicated endpoint; accept an optional array in
    request bodies as the channel through which reviewers record comments."""
    comments = body.get("review_comments")
    if comments is not None:
        if not isinstance(comments, list):
            raise err(ERR_INVALID_REQUEST, "review_comments must be an array")
        rec["review_comments"] = comments


@bp.post("/label-submissions")
@authorized("REGULATORY_AFFAIRS")
def create_label(_user_id=None, _role=None):
    body = get_body()
    formula = None
    if body.get("formula_id") is not None:
        formula = get_or_404(store.formulas, body["formula_id"], "Formula")
    require_fields(body, ["formula_id", "submission_type", "label_text"])
    stype = check_enum(body["submission_type"], SUBMISSION_TYPES, "submission_type")
    if not isinstance(body["label_text"], str):
        raise err(ERR_INVALID_REQUEST, "label_text must be a string")
    claims = body.get("claims", [])
    if not isinstance(claims, list):
        raise err(ERR_INVALID_REQUEST, "claims must be an array")
    rec = stamp_new({
        "id": new_id(),
        "formula_id": formula["id"],
        "submission_type": stype,
        "label_text": body["label_text"],
        "claims": claims,
        "status": "DRAFT",
        "reviewer_id": None,
        "review_comments": [],
        "submitted_at": None,
        "decided_at": None,
        "_submitted_by": None,
    })
    store.labels[rec["id"]] = rec
    return ok(ser_label(rec), 201)


@bp.get("/label-submissions")
@authorized(*LABEL_ROLES)
def list_labels(_user_id=None, _role=None):
    records = list(store.labels.values())
    for param, field in (("formula_id", "formula_id"), ("status", "status"),
                         ("reviewer_id", "reviewer_id")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    return paginate(records, ser_label)


@bp.get("/label-submissions/<lid>")
@authorized(*LABEL_ROLES)
def get_label(lid, _user_id=None, _role=None):
    return ok(ser_label(get_or_404(store.labels, lid, "LabelSubmission")))


@bp.get("/formulas/<fid>/label-submissions")
@authorized(*LABEL_ROLES)
def list_formula_labels(fid, _user_id=None, _role=None):
    get_or_404(store.formulas, fid, "Formula")
    records = [l for l in store.labels.values() if l["formula_id"] == fid]
    return paginate(records, ser_label)


@bp.post("/label-submissions/<lid>/submit")
@authorized("REGULATORY_AFFAIRS")
def submit_label(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be submitted" % rec["status"])
    body = get_body()
    _maybe_accept_comments(body, rec)
    if not isinstance(rec["label_text"], str) or rec["label_text"].strip() == "":
        raise err(ERR_INVALID_REQUEST, "label_text must be non-empty")
    formula = store.formulas.get(rec["formula_id"])
    if formula is None or formula["status"] not in ("APPROVED", "ACTIVE"):
        raise err(ERR_INVALID_STATE,
                  "Referenced formula must be APPROVED or ACTIVE before label submission")
    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = now()
    rec["_submitted_by"] = _user_id
    touch(rec)
    return ok(ser_label(rec))


@bp.post("/label-submissions/<lid>/assign-reviewer")
@authorized("QA_MANAGER")
def assign_reviewer(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be assigned a reviewer" % rec["status"])
    body = get_body()
    require_fields(body, ["reviewer_id"])
    reviewer = store.users.get(body["reviewer_id"])
    if reviewer is None:
        raise err(ERR_NOT_FOUND, "SystemUser '%s' does not exist" % body["reviewer_id"])
    if reviewer["role"] not in ("REGULATORY_AFFAIRS", "QA_MANAGER"):
        raise err(ERR_INVALID_REQUEST,
                  "Reviewer must have role REGULATORY_AFFAIRS or QA_MANAGER")
    _maybe_accept_comments(body, rec)
    rec["reviewer_id"] = reviewer["id"]
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return ok(ser_label(rec))


@bp.post("/label-submissions/<lid>/approve")
@authorized("QA_MANAGER")
def approve_label(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be approved" % rec["status"])
    if rec.get("_submitted_by") is not None and rec["_submitted_by"] == _user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Approver must differ from the user who submitted the label")
    body = get_body()
    _maybe_accept_comments(body, rec)
    if not all(c.get("resolved") is True for c in rec.get("review_comments", [])):
        raise err(ERR_INVALID_STATE,
                  "All review_comments must be resolved before approval")
    rec["status"] = "APPROVED"
    rec["decided_at"] = now()
    touch(rec)
    return ok(ser_label(rec))


@bp.post("/label-submissions/<lid>/reject")
@authorized("QA_MANAGER")
def reject_label(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be rejected" % rec["status"])
    body = get_body()
    _maybe_accept_comments(body, rec)
    if not any(c.get("resolved") is False for c in rec.get("review_comments", [])):
        raise err(ERR_INVALID_STATE,
                  "Rejection requires at least one unresolved review comment")
    require_fields(body, ["rejection_reason"])
    rec["status"] = "REJECTED"
    rec["decided_at"] = now()
    touch(rec)
    return ok(ser_label(rec))


@bp.post("/label-submissions/<lid>/return-for-revision")
@authorized("QA_MANAGER")
def return_label(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be returned for revision"
                  % rec["status"])
    rec["status"] = "DRAFT"
    touch(rec)
    return ok(ser_label(rec))


@bp.post("/label-submissions/<lid>/withdraw")
@authorized("REGULATORY_AFFAIRS")
def withdraw_label(lid, _user_id=None, _role=None):
    rec = get_or_404(store.labels, lid, "LabelSubmission")
    if rec["status"] not in ("DRAFT", "SUBMITTED"):
        raise err(ERR_INVALID_STATE,
                  "LabelSubmission in status %s cannot be withdrawn" % rec["status"])
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok(ser_label(rec))
