from flask import Blueprint, request

import db
from db import STORE
from errors import (
    ApiError,
    ERR_DUPLICATE_SPLIT_PARTICIPANT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SPLIT_LINE_OWNERSHIP_MISMATCH,
    ERR_SPLIT_SUM_INVALID,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    ERR_WORK_RIGHTS_TERMINATED,
    ERR_ZERO_SHARE_LINE,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import split_line_view, split_set_view
from services import (
    get_or_404, new_record, sorted_all, split_lines_of, touch,
)
from validators import body_json, paginate, pagination_params, req_str

bp = Blueprint("splits", __name__)

PARTICIPANT_TYPES = ["WRITER", "PUBLISHER"]


def _validate_lines_payload(body):
    """Tier-3/4 checks; returns normalized line dicts in array order."""
    raw = body.get("lines")
    if raw is None or not isinstance(raw, list):
        raise ApiError(ERR_VALIDATION, 422, "lines is required and must be an array")
    lines = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError(ERR_VALIDATION, 422, "lines[%d] must be an object" % idx)
        ptype = item.get("participant_type")
        if ptype not in PARTICIPANT_TYPES:
            raise ApiError(ERR_VALIDATION, 422,
                           "lines[%d].participant_type must be WRITER or PUBLISHER" % idx)
        share = item.get("share_bp")
        if share is None or isinstance(share, bool) or not isinstance(share, int):
            raise ApiError(ERR_VALIDATION, 422,
                           "lines[%d].share_bp is required and must be an integer" % idx)
        writer_id = item.get("writer_id")
        publisher_name = item.get("publisher_name")
        if ptype == "WRITER":
            if not isinstance(writer_id, str) or not writer_id:
                raise ApiError(ERR_VALIDATION, 422,
                               "lines[%d].writer_id is required for WRITER lines" % idx)
            get_or_404("writers", writer_id, "writer")
            if publisher_name is not None:
                raise ApiError(ERR_VALIDATION, 422,
                               "lines[%d].publisher_name must be null for WRITER lines" % idx)
        else:
            if not isinstance(publisher_name, str) or not publisher_name:
                raise ApiError(ERR_VALIDATION, 422,
                               "lines[%d].publisher_name is required for PUBLISHER lines" % idx)
            if writer_id is not None:
                raise ApiError(ERR_VALIDATION, 422,
                               "lines[%d].writer_id must be null for PUBLISHER lines" % idx)
        lines.append({
            "participant_type": ptype,
            "share_bp": share,
            "writer_id": writer_id if ptype == "WRITER" else None,
            "publisher_name": publisher_name if ptype == "PUBLISHER" else None,
        })
    return lines


def _check_split_aggregates(lines):
    writer_sum = sum(l["share_bp"] for l in lines if l["participant_type"] == "WRITER")
    publisher_sum = sum(l["share_bp"] for l in lines if l["participant_type"] == "PUBLISHER")
    if writer_sum != 10000 or publisher_sum != 10000:
        raise ApiError(ERR_SPLIT_SUM_INVALID, 422,
                       "writer pool and publisher pool must each sum to exactly 10000 bp")
    for l in lines:
        if l["share_bp"] < 1:
            raise ApiError(ERR_ZERO_SHARE_LINE, 422,
                           "every split line must have share_bp >= 1")
    seen_writers = set()
    seen_publishers = set()
    for l in lines:
        if l["participant_type"] == "WRITER":
            if l["writer_id"] in seen_writers:
                raise ApiError(ERR_DUPLICATE_SPLIT_PARTICIPANT, 422,
                               "duplicate writer_id within one split set")
            seen_writers.add(l["writer_id"])
        else:
            if l["publisher_name"] in seen_publishers:
                raise ApiError(ERR_DUPLICATE_SPLIT_PARTICIPANT, 422,
                               "duplicate publisher_name within one split set")
            seen_publishers.add(l["publisher_name"])


def _create_lines(split_set, lines):
    """Create SplitLine rows; strictly increasing created_at in array order."""
    for spec in lines:
        sl = new_record()
        sl.update({
            "split_set_id": split_set["id"],
            "participant_type": spec["participant_type"],
            "writer_id": spec["writer_id"],
            "publisher_name": spec["publisher_name"],
            "share_bp": spec["share_bp"],
            "confirmation_status": "PENDING",
            "rejection_reason": None,
            "confirmed_at": None,
        })
        STORE["split_lines"][sl["id"]] = sl


@bp.route("/split-sets", methods=["POST"], strict_slashes=False)
def create_split_set():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    work_id = body.get("work_id")
    if not isinstance(work_id, str) or not work_id:
        raise ApiError(ERR_VALIDATION, 422, "work_id is required")
    work = get_or_404("works", work_id, "work")
    lines = _validate_lines_payload(body)
    expected = body.get("expected_work_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_VALIDATION, 422,
                       "expected_work_version is required and must be an integer")
    if work["copyright_status"] == "TERMINATED":
        raise ApiError(ERR_WORK_RIGHTS_TERMINATED, 409,
                       "cannot create a split set on a TERMINATED work")
    _check_split_aggregates(lines)
    if expected != work["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_work_version does not match the work's current version")
    revision_index = 1 + sum(
        1 for ss in STORE["split_sets"].values() if ss["work_id"] == work_id)
    ss = new_record()
    ss.update({
        "work_id": work_id,
        "revision_index": revision_index,
        "status": "DRAFT",
        "writer_pool_total_bp": sum(
            l["share_bp"] for l in lines if l["participant_type"] == "WRITER"),
        "publisher_pool_total_bp": sum(
            l["share_bp"] for l in lines if l["participant_type"] == "PUBLISHER"),
        "dispute_reason": None,
    })
    STORE["split_sets"][ss["id"]] = ss
    _create_lines(ss, lines)
    touch(work)  # creating a split set increments the parent Work version
    return success(split_set_view(ss), status=201)


@bp.route("/split-sets", methods=["GET"], strict_slashes=False)
def list_split_sets():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("split_sets")
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    if work_id is not None:
        items = [s for s in items if s["work_id"] == work_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success([split_set_view(s) for s in page],
                   response_type="array", pagination=meta)


@bp.route("/split-sets/<sid>", methods=["GET"], strict_slashes=False)
def get_split_set(sid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    ss = get_or_404("split_sets", sid, "split set")
    return success(split_set_view(ss))


@bp.route("/split-sets/<sid>/submit", methods=["POST"], strict_slashes=False)
def submit_split_set(sid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    ss = get_or_404("split_sets", sid, "split set")
    if ss["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "submit requires status DRAFT")
    work = STORE["works"][ss["work_id"]]
    if work["copyright_status"] == "TERMINATED":
        raise ApiError(ERR_WORK_RIGHTS_TERMINATED, 409,
                       "cannot submit a split set on a TERMINATED work")
    ss["status"] = "PENDING_CONFIRMATIONS"
    touch(ss)
    return success(split_set_view(ss))


@bp.route("/split-sets/<sid>/revise", methods=["POST"], strict_slashes=False)
def revise_split_set(sid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    ss = get_or_404("split_sets", sid, "split set")
    body = body_json()
    lines = _validate_lines_payload(body)
    if ss["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "revise requires status DISPUTED")
    _check_split_aggregates(lines)
    for old in split_lines_of(ss["id"]):
        del STORE["split_lines"][old["id"]]
    _create_lines(ss, lines)
    ss["writer_pool_total_bp"] = sum(
        l["share_bp"] for l in lines if l["participant_type"] == "WRITER")
    ss["publisher_pool_total_bp"] = sum(
        l["share_bp"] for l in lines if l["participant_type"] == "PUBLISHER")
    ss["dispute_reason"] = None
    ss["status"] = "DRAFT"
    touch(ss)
    return success(split_set_view(ss))


# ---------------------------------------------------------------------------
# split lines
# ---------------------------------------------------------------------------

@bp.route("/split-lines", methods=["GET"], strict_slashes=False)
def list_split_lines():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("split_lines")
    split_set_id = request.args.get("split_set_id")
    writer_id = request.args.get("writer_id")
    confirmation_status = request.args.get("confirmation_status")
    if split_set_id is not None:
        items = [l for l in items if l["split_set_id"] == split_set_id]
    if writer_id is not None:
        items = [l for l in items if l["writer_id"] == writer_id]
    if confirmation_status is not None:
        items = [l for l in items if l["confirmation_status"] == confirmation_status]
    page, meta = paginate(items, limit, offset)
    return success([split_line_view(l) for l in page],
                   response_type="array", pagination=meta)


@bp.route("/split-lines/<lid>", methods=["GET"], strict_slashes=False)
def get_split_line(lid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    line = get_or_404("split_lines", lid, "split line")
    return success(split_line_view(line))


def _ownership_check(line, uid, role):
    if line["participant_type"] == "WRITER":
        if role != "Writer" or uid != line["writer_id"]:
            raise ApiError(
                ERR_SPLIT_LINE_OWNERSHIP_MISMATCH, 403,
                "a WRITER line may only be confirmed or rejected by that writer")
    else:
        if role != "PublisherAdmin":
            raise ApiError(
                ERR_SPLIT_LINE_OWNERSHIP_MISMATCH, 403,
                "a PUBLISHER line may only be confirmed or rejected by a PublisherAdmin")


@bp.route("/split-lines/<lid>/confirm", methods=["POST"], strict_slashes=False)
def confirm_split_line(lid):
    uid, role = auth_context()
    require_roles(role, ["Writer", "PublisherAdmin"])
    line = get_or_404("split_lines", lid, "split line")
    _ownership_check(line, uid, role)
    ss = STORE["split_sets"][line["split_set_id"]]
    if ss["status"] != "PENDING_CONFIRMATIONS" or line["confirmation_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "line confirmation requires the parent set to be "
                       "PENDING_CONFIRMATIONS and the line PENDING")
    line["confirmation_status"] = "CONFIRMED"
    line["confirmed_at"] = db.clock_now()
    touch(line)
    siblings = split_lines_of(ss["id"])
    if all(s["confirmation_status"] == "CONFIRMED" for s in siblings):
        ss["status"] = "CONFIRMED"
        touch(ss)
        for other in STORE["split_sets"].values():
            if (other["id"] != ss["id"] and other["work_id"] == ss["work_id"]
                    and other["status"] == "CONFIRMED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        work = STORE["works"][ss["work_id"]]
        touch(work)
    return success(split_line_view(line))


@bp.route("/split-lines/<lid>/reject", methods=["POST"], strict_slashes=False)
def reject_split_line(lid):
    uid, role = auth_context()
    require_roles(role, ["Writer", "PublisherAdmin"])
    line = get_or_404("split_lines", lid, "split line")
    _ownership_check(line, uid, role)
    body = body_json()
    reason = req_str(body, "reason")
    ss = STORE["split_sets"][line["split_set_id"]]
    if ss["status"] != "PENDING_CONFIRMATIONS" or line["confirmation_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "line rejection requires the parent set to be "
                       "PENDING_CONFIRMATIONS and the line PENDING")
    line["confirmation_status"] = "REJECTED"
    line["rejection_reason"] = reason
    touch(line)
    ss["status"] = "DISPUTED"
    ss["dispute_reason"] = reason
    touch(ss)
    return success(split_line_view(line))
