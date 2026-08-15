"""DueDiligenceReview endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from validate import body, opt_num

bp = Blueprint("dd_reviews", __name__)

SCORE_FIELDS = ("score_strategy_fit", "score_track_record",
                "score_operations", "score_compliance")


def get_vehicle_or_404(vid):
    v = STORE.vehicles.get(vid)
    if v is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    return v


def get_review_or_404(vid, rid):
    r = STORE.dd_reviews.get(rid)
    if r is None or r["vehicle_id"] != vid:
        raise_err(ERR_NOT_FOUND, "dd review id does not exist")
    return r


@bp.route("/fof/vehicles/<vid>/dd-reviews", methods=["POST"])
def create_review(vid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    v = get_vehicle_or_404(vid)
    if v["status"] != "IN_DILIGENCE":
        raise_err(ERR_INVALID_STATE, "vehicle is not IN_DILIGENCE")
    prior = [r for r in STORE.dd_reviews.values() if r["vehicle_id"] == vid]
    round_index = max((r["round_index"] for r in prior), default=0) + 1
    r = new_entity(STORE.dd_reviews, {
        "vehicle_id": vid,
        "round_index": round_index,
        "score_strategy_fit": None,
        "score_track_record": None,
        "score_operations": None,
        "score_compliance": None,
        "composite_score": None,
        "status": "DRAFT",
    })
    return ok(public(r), status=201)


@bp.route("/fof/vehicles/<vid>/dd-reviews", methods=["GET"])
def list_reviews(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_vehicle_or_404(vid)
    rows = [r for r in STORE.dd_reviews.values() if r["vehicle_id"] == vid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>", methods=["GET"])
def get_review(vid, rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_vehicle_or_404(vid)
    return ok(public(get_review_or_404(vid, rid)))


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>", methods=["PUT"])
def update_review(vid, rid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    get_vehicle_or_404(vid)
    r = get_review_or_404(vid, rid)
    data = body()
    if r["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise_err(ERR_INVALID_STATE,
                  "scores may be updated only while DRAFT or INFO_REQUESTED")
    for f in SCORE_FIELDS:
        v = opt_num(data, f)
        if v is not None:
            if not (0 <= v <= 100):
                raise_err(ERR_INVALID_REQUEST, "%s must be in [0, 100]" % f)
            r[f] = v
    touch(r)
    return ok(public(r))


def _transition(vid, rid, action):
    user_id, role = auth_context()
    get_vehicle_or_404(vid)
    r = get_review_or_404(vid, rid)
    st = r["status"]
    if action == "submit":
        require_role(role, ["Analyst"])
        if st != "DRAFT":
            raise_err(ERR_INVALID_STATE, "review is not in DRAFT")
        for f in SCORE_FIELDS:
            if r[f] is None:
                raise_err(ERR_INVALID_REQUEST,
                          "all four score fields must be non-null to submit")
        r["composite_score"] = domain.dd_composite(r)
        r["status"] = "SUBMITTED"
    elif action == "request-info":
        require_role(role, ["InvestmentCommittee"])
        if st != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "review is not SUBMITTED")
        r["status"] = "INFO_REQUESTED"
    elif action == "resubmit":
        require_role(role, ["Analyst"])
        if st != "INFO_REQUESTED":
            raise_err(ERR_INVALID_STATE, "review is not INFO_REQUESTED")
        for f in SCORE_FIELDS:
            if r[f] is None:
                raise_err(ERR_INVALID_REQUEST,
                          "all four score fields must be non-null to resubmit")
        r["composite_score"] = domain.dd_composite(r)
        r["status"] = "SUBMITTED"
    elif action == "complete":
        require_role(role, ["InvestmentCommittee"])
        if st != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "review is not SUBMITTED")
        r["status"] = "COMPLETED"
    elif action == "withdraw":
        require_role(role, ["Analyst"])
        if st != "DRAFT":
            raise_err(ERR_INVALID_STATE, "review is not in DRAFT")
        r["status"] = "WITHDRAWN"
    touch(r)
    return ok(public(r))


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>/submit", methods=["POST"])
def submit_review(vid, rid):
    return _transition(vid, rid, "submit")


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>/request-info", methods=["POST"])
def request_info(vid, rid):
    return _transition(vid, rid, "request-info")


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>/resubmit", methods=["POST"])
def resubmit_review(vid, rid):
    return _transition(vid, rid, "resubmit")


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>/complete", methods=["POST"])
def complete_review(vid, rid):
    return _transition(vid, rid, "complete")


@bp.route("/fof/vehicles/<vid>/dd-reviews/<rid>/withdraw", methods=["POST"])
def withdraw_review(vid, rid):
    return _transition(vid, rid, "withdraw")
