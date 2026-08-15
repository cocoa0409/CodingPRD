"""Routes: fair-use assessments, takedown notices."""
from flask import request

import state as S
import services as svc
import serializers as SZ

FUA_READ_ROLES = ["AssetCurator", "ClearanceOfficer", "Requester",
                  "LegalCertifier"]
TD_READ_ROLES = ["AssetCurator", "ClearanceOfficer", "LegalCertifier",
                 "FinancePayer"]
FAIR_USE_MEDIA = {"SOCIAL", "PRINT"}


def _get_asset_or_404(aid):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    return a


def _get_assessment_or_404(aid):
    a = svc.get_assessment(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "FairUseAssessment not found")
    return a


def _get_notice_or_404(nid):
    n = svc.get_notice(nid)
    if n is None:
        raise S.err("ERR_NOT_FOUND", 404, "TakedownNotice not found")
    return n


def _composite_score(factor_scores):
    return (factor_scores["purpose"] + factor_scores["nature"]
            + factor_scores["amount"] + 2 * factor_scores["market"])


def _validate_factor_scores(body):
    fs = body.get("factor_scores")
    if not isinstance(fs, dict):
        raise S.err("ERR_INVALID_REQUEST", 400,
                    "factor_scores must be an object")
    out = {}
    for k in ("purpose", "nature", "amount", "market"):
        v = fs.get(k)
        if not S.is_intlike(v):
            raise S.err("ERR_INVALID_REQUEST", 400,
                        "factor_scores.%s must be an integer" % k)
        iv = int(v)
        if iv < 1 or iv > 4:
            raise S.err("ERR_INVALID_REQUEST", 400,
                        "factor_scores.%s must be in 1..4" % k)
        out[k] = iv
    return out


# ---------------------------------------------------------------------------
# Fair-use assessments (PRD 3.8)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/assets/<aid>/fair-use-assessments", ["POST"], ["Requester"])
def create_fair_use_assessment(aid, user_id, user_role):
    asset = _get_asset_or_404(aid)
    body = S.get_body()
    clearance_request_id = S.req_str(body, "clearance_request_id")
    factor_scores = _validate_factor_scores(body)
    req = svc.get_request(clearance_request_id)
    if req is None or req["asset_id"] != aid:
        raise S.err("ERR_NOT_FOUND", 404,
                    "clearance_request_id not found on this asset")
    # media eligibility gate (PRD 3.8)
    if req["media"] not in FAIR_USE_MEDIA:
        raise S.err("ERR_FAIR_USE_MEDIA_INELIGIBLE", 409,
                    "Fair-use route allowed only for SOCIAL or PRINT media")
    if req["status"] != "SUBMITTED":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Linked request must be in SUBMITTED")
    # supersede prior DRAFT for the same request
    for prior in S.fair_use_assessments.values():
        if (prior["clearance_request_id"] == clearance_request_id
                and prior["status"] == "DRAFT"):
            prior["status"] = "SUPERSEDED"
            S.touch(prior)
    a = S.stamp_new({
        "asset_id": aid,
        "clearance_request_id": clearance_request_id,
        "factor_scores": factor_scores,
        "composite_score": _composite_score(factor_scores),
        "certified": False,
        "status": "DRAFT",
        "created_by_requester_id": user_id,
    })
    S.fair_use_assessments[a["id"]] = a
    # reroute the linked request
    req["status"] = "FAIR_USE_ROUTE"
    req["fair_use_assessment_id"] = a["id"]
    S.touch(req)
    svc.touch_asset(asset)
    return SZ.serialize_fair_use_assessment(a), 201


@S.endpoint("/rights/fair-use-assessments/<aid>", ["GET"], FUA_READ_ROLES)
def get_fair_use_assessment(aid, user_id, user_role):
    a = _get_assessment_or_404(aid)
    return SZ.serialize_fair_use_assessment(a), 200


@S.endpoint("/rights/assets/<aid>/fair-use-assessments", ["GET"], FUA_READ_ROLES)
def list_asset_fair_use_assessments(aid, user_id, user_role):
    _get_asset_or_404(aid)
    limit, offset = S.pagination_params()
    status_f = request.args.get("status")
    items = sorted(
        [a for a in S.fair_use_assessments.values() if a["asset_id"] == aid],
        key=lambda a: (a["created_at"], a["_seq"]),
    )
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return S.paginate([SZ.serialize_fair_use_assessment(a) for a in items],
                      limit, offset)


@S.endpoint("/rights/fair-use-assessments", ["GET"], FUA_READ_ROLES)
def list_fair_use_assessments(user_id, user_role):
    limit, offset = S.pagination_params()
    cr_f = request.args.get("clearance_request_id")
    status_f = request.args.get("status")
    items = sorted(S.fair_use_assessments.values(),
                   key=lambda a: (a["created_at"], a["_seq"]))
    if cr_f is not None:
        items = [a for a in items if a["clearance_request_id"] == cr_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return S.paginate([SZ.serialize_fair_use_assessment(a) for a in items],
                      limit, offset)


@S.endpoint("/rights/fair-use-assessments/<aid>/certify", ["POST"],
            ["LegalCertifier"])
def certify_fair_use_assessment(aid, user_id, user_role):
    a = _get_assessment_or_404(aid)
    if a["status"] != "DRAFT":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Only a DRAFT assessment may be certified")
    # gates: composite >= 13; certifier != creating requester; posture != RETIRED
    if a["composite_score"] < S.FAIR_USE_CERTIFY_MIN:
        raise S.err("ERR_FAIR_USE_SCORE_LOW", 422,
                    "composite_score below certification threshold")
    if a.get("created_by_requester_id") == user_id:
        raise S.err("ERR_SEGREGATION_OF_DUTIES", 422,
                    "Creating requester may not certify the assessment")
    asset = svc.get_asset(a["asset_id"])
    if asset is not None and asset["posture"] == "RETIRED":
        raise S.err("ERR_ASSET_POSTURE_BLOCKED", 409,
                    "Asset is retired")
    a["certified"] = True
    a["status"] = "CERTIFIED"
    S.touch(a)
    return SZ.serialize_fair_use_assessment(a), 200


@S.endpoint("/rights/fair-use-assessments/<aid>/reject", ["POST"],
            ["LegalCertifier"])
def reject_fair_use_assessment(aid, user_id, user_role):
    a = _get_assessment_or_404(aid)
    if a["status"] != "DRAFT":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Only a DRAFT assessment may be rejected")
    a["status"] = "REJECTED"
    S.touch(a)
    return SZ.serialize_fair_use_assessment(a), 200


# ---------------------------------------------------------------------------
# Takedown notices (PRD 3.7)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/assets/<aid>/takedown-notices", ["POST"], ["AssetCurator"])
def create_takedown_notice(aid, user_id, user_role):
    asset = _get_asset_or_404(aid)
    body = S.get_body()
    claimant_name = S.req_str(body, "claimant_name")
    received = S.now_dt()
    from datetime import timedelta
    n = S.stamp_new({
        "asset_id": aid,
        "claimant_name": claimant_name,
        "received_at": received,
        "counter_notice_due_at": received + timedelta(days=S.DMCA_COUNTER_WINDOW_DAYS),
        "status": "PENDING",
    })
    S.takedown_notices[n["id"]] = n
    svc.recompute_asset_posture(asset)
    return SZ.serialize_takedown_notice(n), 201


@S.endpoint("/rights/assets/<aid>/takedown-notices", ["GET"], TD_READ_ROLES)
def list_asset_takedown_notices(aid, user_id, user_role):
    _get_asset_or_404(aid)
    limit, offset = S.pagination_params()
    status_f = request.args.get("status")
    items = sorted(svc.asset_notices(aid),
                   key=lambda n: (n["created_at"], n["_seq"]))
    if status_f is not None:
        items = [n for n in items if n["status"] == status_f]
    return S.paginate([SZ.serialize_takedown_notice(n) for n in items],
                      limit, offset)


@S.endpoint("/rights/takedown-notices/<nid>", ["GET"], TD_READ_ROLES)
def get_takedown_notice(nid, user_id, user_role):
    n = _get_notice_or_404(nid)
    return SZ.serialize_takedown_notice(n), 200


@S.endpoint("/rights/takedown-notices/<nid>/counter", ["POST"], ["AssetCurator"])
def counter_takedown_notice(nid, user_id, user_role):
    n = _get_notice_or_404(nid)
    if n["status"] != "PENDING":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Only a PENDING notice may be countered")
    clock = S.now_dt()
    # strictly-earlier: at clock == due_at exactly, the window has lapsed
    if clock >= n["counter_notice_due_at"]:
        raise S.err("ERR_COUNTER_WINDOW_LAPSED", 409,
                    "Counter window has lapsed")
    n["status"] = "COUNTERED"
    S.touch(n)
    asset = svc.get_asset(n["asset_id"])
    if asset is not None:
        svc.recompute_asset_posture(asset)
    return SZ.serialize_takedown_notice(n), 200


@S.endpoint("/rights/takedown-notices/<nid>/retract", ["POST"], ["AssetCurator"])
def retract_takedown_notice(nid, user_id, user_role):
    n = _get_notice_or_404(nid)
    if n["status"] not in ("PENDING", "COUNTERED", "UPHELD"):
        raise S.err("ERR_INVALID_STATE", 409,
                    "Only a PENDING, COUNTERED, or UPHELD notice may be retracted")
    n["status"] = "RETRACTED"
    S.touch(n)
    asset = svc.get_asset(n["asset_id"])
    if asset is not None:
        svc.recompute_asset_posture(asset)
    return SZ.serialize_takedown_notice(n), 200
