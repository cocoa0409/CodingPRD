"""ReservingStudy endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_SELECTED_RUN,
    ERR_RANGE_WIDTH_EXCEEDED,
    ERR_RUN_STALE,
    ERR_SOD_REVIEWER_IS_PREPARER,
    ERR_STALE_VERSION,
    ERR_STUDY_ALREADY_EXISTS,
    ERR_STUDY_ATTACHED,
    ERR_STUDY_STALE_DATA,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, touch, sorted_by_creation
from services.calculations import any_run_for_study, matched_run_for_study
from services.serializers import study_view
from util import dec, round_4dp
from validate import (
    get_body,
    opt_bool,
    opt_enum,
    parse_pagination,
    reject_server_managed,
    req_enum,
    req_int,
    req_quarter,
    req_str,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("studies", __name__)

STUDY_COMPUTED = [
    "status", "stale_data_flag", "created_by_user_id", "reviewed_by_user_id",
    "opinion_id", "selected_ultimate_cents", "selected_ibnr_cents",
    "selected_range_low_cents", "selected_range_high_cents",
    "reconciliation_variance_pct",
]


@bp.post("/actuarial/studies")
def create_study():
    caller = authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, STUDY_COMPUTED)
    segment_id = req_str(body, "segment_id")
    valuation_quarter = req_quarter(body, "valuation_quarter")
    selected_method = req_enum(body, "selected_method", ["CHAIN_LADDER", "BORNHUETTER_FERGUSON"])
    selected_basis = req_enum(body, "selected_basis", ["PAID", "INCURRED"])

    require_body_fk("segments", segment_id, "segment_id")

    # Uniqueness: at most one non-WITHDRAWN study per (segment, valuation_quarter).
    for s in db["studies"].values():
        if (s["segment_id"] == segment_id
                and s["valuation_quarter"] == valuation_quarter
                and s["status"] != "WITHDRAWN"):
            raise_error(ERR_STUDY_ALREADY_EXISTS,
                        "a non-WITHDRAWN study already exists for (segment, valuation_quarter)")

    rec = new_common_record({
        "segment_id": segment_id,
        "valuation_quarter": valuation_quarter,
        "selected_method": selected_method,
        "selected_basis": selected_basis,
        "status": "DRAFT",
        "stale_data_flag": False,
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "opinion_id": None,
    })
    db["studies"][rec["id"]] = rec
    return success_object(study_view(rec), status=201)


@bp.get("/actuarial/studies/<sid>")
def get_study(sid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("studies", sid)
    return success_object(study_view(rec))


@bp.get("/actuarial/studies")
def list_studies():
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    opinion_id = request.args.get("opinion_id")
    status = request.args.get("status")
    vq = request.args.get("valuation_quarter")
    items = list(db["studies"].values())
    if segment_id is not None:
        items = [s for s in items if s["segment_id"] == segment_id]
    if opinion_id is not None:
        items = [s for s in items if s.get("opinion_id") == opinion_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if vq is not None:
        items = [s for s in items if s["valuation_quarter"] == vq]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([study_view(s) for s in page], total, limit, offset)


@bp.patch("/actuarial/studies/<sid>")
def patch_study(sid):
    caller = authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, STUDY_COMPUTED)
    study = require_path_resource("studies", sid)

    # Only DRAFT studies can be revised (state-machine legality).
    if study["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "study revision is allowed only while DRAFT")

    # OCC: expected_study_version must match.
    if "expected_study_version" not in body or body.get("expected_study_version") is None:
        raise_error(ERR_INVALID_REQUEST, "expected_study_version is required")
    expected = body.get("expected_study_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_study_version must be an integer")
    if expected != study["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_study_version does not match the study's current version")

    # Optional revisions.
    new_method = opt_enum(body, "selected_method", ["CHAIN_LADDER", "BORNHUETTER_FERGUSON"], default=None)
    new_basis = opt_enum(body, "selected_basis", ["PAID", "INCURRED"], default=None)
    # Reject any other unexpected field.
    allowed = {"expected_study_version", "selected_method", "selected_basis"}
    for k in body.keys():
        if k not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"unsupported field for study PATCH: {k}")

    if new_method is not None:
        study["selected_method"] = new_method
    if new_basis is not None:
        study["selected_basis"] = new_basis
    study["stale_data_flag"] = False
    touch(study)
    return success_object(study_view(study))


@bp.post("/actuarial/studies/<sid>/submit")
def submit_study(sid):
    authorized(["ActuarialAnalyst"])
    study = require_path_resource("studies", sid)
    if study["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only DRAFT studies can be submitted")

    # Referential tier order (PRD §3.7):
    #   1) stale_data_flag -> ERR_STUDY_STALE_DATA
    #   2) matched run existence -> ERR_NO_SELECTED_RUN
    #   3) matched run freshness -> ERR_RUN_STALE
    if study["stale_data_flag"]:
        raise_error(ERR_STUDY_STALE_DATA,
                    "study has an unacknowledged staleness cascade; revise (PATCH) to clear")
    matched = matched_run_for_study(study)
    if matched is None:
        if any_run_for_study(study) is None:
            raise_error(ERR_NO_SELECTED_RUN,
                        "no run exists for (segment, valuation_quarter, selected_method, selected_basis)")
        raise_error(ERR_RUN_STALE, "matched run is stale")

    study["status"] = "IN_REVIEW"
    touch(study)
    return success_object(study_view(study))


@bp.post("/actuarial/studies/<sid>/review")
def review_study(sid):
    caller = authorized(["PeerReviewer"])
    body = get_body()
    reject_server_managed(body, STUDY_COMPUTED)
    study = require_path_resource("studies", sid)
    if study["status"] != "IN_REVIEW":
        raise_error(ERR_INVALID_STATE, "only IN_REVIEW studies can be reviewed")

    decision = req_enum(body, "decision", ["APPROVE", "REJECT"])
    override = opt_bool(body, "chief_actuary_override", default=False)

    # SoD: reviewer must differ from creator.
    if caller.user_id == study["created_by_user_id"]:
        raise_error(ERR_SOD_REVIEWER_IS_PREPARER,
                    "reviewer must differ from the study's creator")

    if decision == "APPROVE":
        # Range-width gate.
        matched = matched_run_for_study(study)
        # matched run must exist (study was submitted with a fresh matched run)
        # but compute defensively anyway.
        if matched is not None:
            srl = matched["range_low_cents"]
            srh = matched["range_high_cents"]
            si = matched["ibnr_cents"]
            if si == 0:
                width_pct = dec(0)
            else:
                width_pct = (dec(srh) - dec(srl)) / dec(si)
            segment = db["segments"].get(study["segment_id"])
            max_w = dec(segment["max_range_width_pct"]) if segment else dec(0)
            if not override and width_pct > max_w:
                raise_error(ERR_RANGE_WIDTH_EXCEEDED,
                            "range width exceeds segment.max_range_width_pct and no chief_actuary_override")
        study["status"] = "APPROVED"
        study["reviewed_by_user_id"] = caller.user_id
        touch(study)
        # Quarter-close checkpoint: segment.last_closed_quarter = max(lcq, study.valuation_quarter).
        segment = db["segments"].get(study["segment_id"])
        if segment is not None:
            lcq = segment.get("last_closed_quarter")
            if lcq is None or study["valuation_quarter"] > lcq:
                segment["last_closed_quarter"] = study["valuation_quarter"]
                touch(segment)
    else:  # REJECT
        study["status"] = "DRAFT"
        study["reviewed_by_user_id"] = caller.user_id
        touch(study)
    return success_object(study_view(study))


@bp.post("/actuarial/studies/<sid>/withdraw")
def withdraw_study(sid):
    authorized(["ActuarialAnalyst"])
    study = require_path_resource("studies", sid)
    if study["status"] in ("LOCKED", "WITHDRAWN"):
        raise_error(ERR_INVALID_STATE, "cannot withdraw a terminal study")
    if study["status"] == "APPROVED" and study.get("opinion_id") is not None:
        raise_error(ERR_STUDY_ATTACHED,
                    "cannot withdraw an APPROVED study attached to an opinion")

    # Clear opinion link when set (only reachable for non-APPROVED studies).
    if study.get("opinion_id") is not None:
        study["opinion_id"] = None
    study["status"] = "WITHDRAWN"
    touch(study)
    return success_object(study_view(study))
