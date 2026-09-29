"""Qualification requests, the review cycle, verification and the two sweeps."""
from flask import Blueprint

import calc
import validation as V
from auth import (OPERATOR_ROLES, ROLE_CIRCULATION_MANAGER,
                  ROLE_QUALIFICATION_SPECIALIST, current_user, endpoint)
from envelope import created, ok, paginate
from errors import ApiError
from lookups import (get_publication, get_qualification_request,
                     get_source_document, get_subscriber)
from store import (add_months, base_record, collection_sorted, db, now,
                   serialize, touch)

requests_bp = Blueprint("requests", __name__)

REQUEST_WRITE_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_QUALIFICATION_SPECIALIST)
LIVE_REQUEST_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
TERMINAL_REQUEST_STATUSES = ("VERIFIED", "REJECTED")


def _no_future(values, key="signed_at"):
    value = values.get(key)
    if value is not None and value > now():
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s may not lie in the future of the logical clock." % key)


# --------------------------------------------------------------------------
# POST /circulation/qualification-requests
# --------------------------------------------------------------------------
@requests_bp.route("/circulation/qualification-requests", methods=["POST"])
@endpoint(*REQUEST_WRITE_ROLES)
def create_qualification_request():
    payload = V.body()
    sub = get_subscriber(payload.get("subscriber_id"))
    doc = get_source_document(payload.get("source_document_id"))

    fields = V.parse(payload, [
        V.f_id("subscriber_id"),
        V.f_id("source_document_id"),
        V.f_enum("request_channel", V.REQUEST_CHANNELS),
        V.f_dt("signed_at"),
        V.f_str("attested_job_function_code", max_len=40),
        V.f_str("attested_industry_code", max_len=40),
        V.f_enum("attested_purchasing_authority", V.PURCHASING_AUTHORITIES),
        V.f_int("expected_subscriber_version", minimum=0),
    ], cross=_no_future)

    if fields["expected_subscriber_version"] != sub["version"]:
        raise ApiError("ERR_STALE_SUBSCRIBER_VERSION",
                       "expected_subscriber_version %s does not match the recipient's "
                       "current version %s." % (fields["expected_subscriber_version"],
                                                sub["version"]))

    if sub["qualification_status"] == "PENDING_QUALIFICATION":
        raise ApiError("ERR_INVALID_STATE",
                       "This recipient already has a qualification request in flight.")
    if sub["delivery_status"] == "REMOVED" \
            and sub["qualification_status"] != "REQUALIFICATION_REQUIRED":
        raise ApiError("ERR_INVALID_STATE",
                       "A removed recipient may only be re-attested from "
                       "REQUALIFICATION_REQUIRED.")

    if doc["purge_status"] == "PURGED":
        raise ApiError("ERR_SOURCE_DOCUMENT_PURGED",
                       "The cited source document has been purged.")
    if doc["subscriber_id"] != sub["id"]:
        raise ApiError("ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH",
                       "The cited source document belongs to another recipient.")

    # supersede any live request of the same recipient
    for other in collection_sorted(db.qualification_requests.values()):
        if other["subscriber_id"] != sub["id"]:
            continue
        if other["status"] not in LIVE_REQUEST_STATUSES:
            continue
        other["status"] = "REJECTED"
        other["decided_at"] = now()
        other["decision_reason"] = "SUPERSEDED_BY_NEWER_REQUEST"
        touch(other)

    req = base_record()
    req.update({
        "subscriber_id": sub["id"],
        "source_document_id": doc["id"],
        "request_channel": fields["request_channel"],
        "signed_at": fields["signed_at"],
        "attested_job_function_code": fields["attested_job_function_code"],
        "attested_industry_code": fields["attested_industry_code"],
        "attested_purchasing_authority": fields["attested_purchasing_authority"],
        "status": "SUBMITTED",
        "computed_score": 0,
        "info_request_count": 0,
        "reviewed_by_user_id": None,
        "decided_at": None,
        "decision_reason": None,
        "effective_from": None,
        "effective_to": None,
    })
    db.qualification_requests[req["id"]] = req

    sub["qualification_status"] = "PENDING_QUALIFICATION"
    touch(sub)
    return created(serialize(req))


@requests_bp.route("/circulation/qualification-requests/<req_id>", methods=["GET"])
@endpoint(*OPERATOR_ROLES)
def read_qualification_request(req_id):
    return ok(serialize(get_qualification_request(req_id)))


@requests_bp.route("/circulation/qualification-requests", methods=["GET"])
@endpoint(*OPERATOR_ROLES)
def list_qualification_requests():
    subscriber_id = V.filter_str("subscriber_id")
    source_document_id = V.filter_str("source_document_id")
    status = V.filter_enum("status", V.REQUEST_STATUSES)
    rows = list(db.qualification_requests.values())
    if subscriber_id:
        rows = [r for r in rows if r["subscriber_id"] == subscriber_id]
    if source_document_id:
        rows = [r for r in rows if r["source_document_id"] == source_document_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# review / request-info / resubmit
# --------------------------------------------------------------------------
def _publication_of_request(req):
    sub = db.subscribers.get(req["subscriber_id"])
    if sub is None:
        return None, None
    return sub, db.publications.get(sub["publication_id"])


def _require_under_review(req):
    if req["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_UNDER_REVIEW",
                       "This request is %s, not UNDER_REVIEW." % req["status"])


@requests_bp.route("/circulation/qualification-requests/<req_id>/review", methods=["POST"])
@endpoint(ROLE_QUALIFICATION_SPECIALIST)
def review_qualification_request(req_id):
    req = get_qualification_request(req_id)
    payload = V.body()
    V.parse(payload, [V.f_str("review_note", required=False, max_len=1000, default=None)])

    if req["status"] in TERMINAL_REQUEST_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This request has already reached %s." % req["status"])
    if req["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED request may be taken into review.")

    sub, pub = _publication_of_request(req)
    rules = calc.rules_for(pub["id"]) if pub else {}
    score, _ = calc.qualification_score(req, rules)

    req["status"] = "UNDER_REVIEW"
    req["reviewed_by_user_id"] = current_user()
    req["computed_score"] = score
    touch(req)
    return ok(serialize(req))


@requests_bp.route("/circulation/qualification-requests/<req_id>/request-info", methods=["POST"])
@endpoint(ROLE_QUALIFICATION_SPECIALIST)
def request_info(req_id):
    req = get_qualification_request(req_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_str("info_request_note", max_len=1000)])

    _require_under_review(req)
    if req["info_request_count"] >= calc.INFO_REQUEST_LIMIT:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED",
                       "This request has already been sent back %s times."
                       % req["info_request_count"])

    req["status"] = "INFO_REQUESTED"
    req["info_request_count"] = req["info_request_count"] + 1
    req["_info_request_note"] = fields["info_request_note"]
    touch(req)
    return ok(serialize(req))


@requests_bp.route("/circulation/qualification-requests/<req_id>/resubmit", methods=["POST"])
@endpoint(*REQUEST_WRITE_ROLES)
def resubmit_qualification_request(req_id):
    req = get_qualification_request(req_id)
    payload = V.body()
    fields = V.parse(payload, [
        V.f_dt("signed_at", required=False, default=None),
        V.f_enum("request_channel", V.REQUEST_CHANNELS, required=False, default=None),
        V.f_str("attested_job_function_code", required=False, max_len=40, default=None),
        V.f_str("attested_industry_code", required=False, max_len=40, default=None),
        V.f_enum("attested_purchasing_authority", V.PURCHASING_AUTHORITIES,
                 required=False, default=None),
    ], cross=_no_future)

    if req["status"] in TERMINAL_REQUEST_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This request has already reached %s." % req["status"])
    if req["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an INFO_REQUESTED request may be resubmitted.")

    for key in ("signed_at", "request_channel", "attested_job_function_code",
                "attested_industry_code", "attested_purchasing_authority"):
        if fields[key] is not None:
            req[key] = fields[key]

    req["status"] = "SUBMITTED"
    req["computed_score"] = 0
    touch(req)
    return ok(serialize(req))


# --------------------------------------------------------------------------
# verify  (PRD 3.4)
# --------------------------------------------------------------------------
@requests_bp.route("/circulation/qualification-requests/<req_id>/verify", methods=["POST"])
@endpoint(ROLE_QUALIFICATION_SPECIALIST)
def verify_qualification_request(req_id):
    req = get_qualification_request(req_id)
    payload = V.body()
    V.parse(payload, [V.f_str("decision_reason", required=False, max_len=1000, default=None)])

    _require_under_review(req)

    doc = db.source_documents.get(req["source_document_id"])
    if doc is not None and doc["purge_status"] == "PURGED":
        raise ApiError("ERR_SOURCE_DOCUMENT_PURGED",
                       "The evidence backing this request has been purged.")

    sub, pub = _publication_of_request(req)
    at = now()
    grace = calc.grace_window_open(sub, pub, at) if pub else False
    if pub and calc.window_collides(sub, pub, at) and not grace:
        raise ApiError("ERR_QUALIFICATION_WINDOW_OVERLAP",
                       "The new qualification window would overlap the running one.")

    rules = calc.rules_for(pub["id"]) if pub else {}
    for dimension in ("JOB_FUNCTION", "INDUSTRY", "PURCHASING_AUTHORITY"):
        if dimension not in rules:
            raise ApiError("ERR_QUALIFICATION_RULES_INCOMPLETE",
                           "The publication has no %s rule." % dimension)

    score, points = calc.qualification_score(req, rules, at)
    req["computed_score"] = score
    if score < calc.QUALIFY_SCORE_THRESHOLD:
        raise ApiError("ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD",
                       "Computed score %s is below the threshold of %s."
                       % (score, calc.QUALIFY_SCORE_THRESHOLD))
    for dimension, rule in rules.items():
        if rule["is_mandatory"] and points.get(dimension, 0) <= 0:
            raise ApiError("ERR_MANDATORY_CRITERION_NOT_MET",
                           "Mandatory criterion %s scored no points." % dimension)

    validity = pub["qualification_validity_months"]
    window_end = add_months(at, validity)

    if grace:
        for other in collection_sorted(db.qualification_requests.values()):
            if other["id"] == req["id"] or other["subscriber_id"] != sub["id"]:
                continue
            if other["status"] != "VERIFIED" or other["effective_to"] is None:
                continue
            if other["effective_to"] > at:
                other["effective_to"] = at
                touch(other)

    req["status"] = "VERIFIED"
    req["decided_at"] = at
    req["effective_from"] = at
    req["effective_to"] = window_end
    touch(req)

    sub["qualification_status"] = "QUALIFIED"
    sub["qualification_score"] = score
    sub["qualified_at"] = at
    sub["qualification_expires_at"] = window_end
    sub["job_function_code"] = req["attested_job_function_code"]
    sub["industry_code"] = req["attested_industry_code"]
    sub["purchasing_authority_level"] = req["attested_purchasing_authority"]
    if sub["delivery_status"] in ("UNDELIVERABLE", "REMOVED"):
        sub["delivery_status"] = "DELIVERABLE"
        sub["undeliverable_count"] = 0
    touch(sub)

    calc.recompute_publication(pub)
    calc.mark_drafts_stale(pub["id"])
    touch(pub)
    return ok(serialize(req))


# --------------------------------------------------------------------------
# reject  (PRD 3.3)
# --------------------------------------------------------------------------
@requests_bp.route("/circulation/qualification-requests/<req_id>/reject", methods=["POST"])
@endpoint(ROLE_QUALIFICATION_SPECIALIST)
def reject_qualification_request(req_id):
    req = get_qualification_request(req_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_str("decision_reason", max_len=1000)])

    _require_under_review(req)

    at = now()
    req["status"] = "REJECTED"
    req["decided_at"] = at
    req["decision_reason"] = fields["decision_reason"]
    touch(req)

    sub, pub = _publication_of_request(req)
    if sub is not None and sub["qualification_status"] == "PENDING_QUALIFICATION":
        if sub["qualified_at"] is None:
            sub["qualification_status"] = "UNQUALIFIED"
        elif sub["qualification_expires_at"] is not None \
                and sub["qualification_expires_at"] > at:
            sub["qualification_status"] = "QUALIFIED"
        else:
            sub["qualification_status"] = "LAPSED"
        touch(sub)
    return ok(serialize(req))


# --------------------------------------------------------------------------
# POST /circulation/hygiene-runs  (PRD 3.5)
# --------------------------------------------------------------------------
@requests_bp.route("/circulation/hygiene-runs", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def execute_hygiene_run():
    payload = V.body()
    pub = get_publication(payload.get("publication_id"))
    fields = V.parse(payload, [
        V.f_id("publication_id"),
        V.f_enum("run_type", V.RUN_TYPES),
        V.f_int("undeliverable_threshold", required=False, minimum=1, default=2),
    ])

    at = now()
    threshold = fields["undeliverable_threshold"]
    flagged = removed = lapsed = requal = 0
    rows = collection_sorted(calc.subscribers_of(pub["id"]))

    if fields["run_type"] == "UNDELIVERABLE_SWEEP":
        for sub in rows:
            count = sub["undeliverable_count"]
            if count <= 0:
                continue
            if count >= threshold:
                if sub["delivery_status"] in ("DELIVERABLE", "UNDELIVERABLE"):
                    sub["delivery_status"] = "REMOVED"
                    removed += 1
                    if sub["qualification_status"] in ("QUALIFIED", "LAPSED",
                                                       "PENDING_QUALIFICATION"):
                        sub["qualification_status"] = "REQUALIFICATION_REQUIRED"
                        requal += 1
                    touch(sub)
            elif sub["delivery_status"] == "DELIVERABLE":
                sub["delivery_status"] = "UNDELIVERABLE"
                flagged += 1
                touch(sub)
    else:
        for sub in rows:
            if sub["qualification_status"] != "QUALIFIED":
                continue
            expires = sub["qualification_expires_at"]
            if expires is not None and expires <= at:
                sub["qualification_status"] = "LAPSED"
                lapsed += 1
                touch(sub)

    before, after, invalidated = calc.recompute_publication(pub)
    touch(pub)

    run = base_record(with_version=False)
    run.update({
        "publication_id": pub["id"],
        "run_type": fields["run_type"],
        "undeliverable_threshold": threshold,
        "executed_at": at,
        "undeliverable_flagged_count": flagged,
        "removed_count": removed,
        "lapsed_count": lapsed,
        "requalification_required_count": requal,
        "statements_invalidated_count": invalidated,
        "posture_before": before,
        "posture_after": after,
    })
    db.hygiene_runs[run["id"]] = run
    return created(serialize(run))
