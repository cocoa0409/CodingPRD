"""ReviewRecord endpoints (seal / transmit) and the final fee."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_RECORD_NOT_FOUND,
    ERR_NOT_RESPONSIBLE_CHARGE,
    ERR_ENGAGEMENT_NOT_APPROVED,
    ERR_RECORD_INVALID_STATE,
    ERR_LICENSE_STATE_MISMATCH,
    ERR_LICENSE_WINDOW_INSUFFICIENT,
    ERR_SE_SEAL_REQUIRED,
    ERR_DEFERRED_SUBMITTALS_OUTSTANDING,
)
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import (
    license_for_state, parse_date, refresh_engagement_counts,
)
from services.fees import compute_final_fee

bp = Blueprint("records", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")


def get_record_or_404(rid):
    r = db.records.get(rid)
    if r is None:
        raise ApiError(ERR_RECORD_NOT_FOUND, 404, "No review record with the given id")
    return r


@bp.get("/plan-review/records")
def list_records():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.records.values())
    engagement_id = request.args.get("engagement_id")
    sealed_by_reviewer_id = request.args.get("sealed_by_reviewer_id")
    status = request.args.get("status")
    if engagement_id is not None:
        items = [r for r in items if r["engagement_id"] == engagement_id]
    if sealed_by_reviewer_id is not None:
        items = [r for r in items if r["sealed_by_reviewer_id"] == sealed_by_reviewer_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(r) for r in page], limit, offset, total)


@bp.get("/plan-review/records/<rid>")
def get_record(rid):
    require_roles(*READ_ROLES)
    r = get_record_or_404(rid)
    return success_object(db.serialize(r))


@bp.post("/plan-review/records/<rid>/seal")
def seal_record(rid):
    uid, _role = require_roles("Reviewer")
    get_json_body(required=False)
    record = get_record_or_404(rid)
    engagement = db.engagements[record["engagement_id"]]

    # ownership: responsible charge
    if uid != engagement["reviewer_of_record_id"]:
        raise ApiError(ERR_NOT_RESPONSIBLE_CHARGE, 403,
                       "X-User-ID does not equal engagement.reviewer_of_record_id")

    # state preconditions
    if record["status"] != "DRAFT":
        raise ApiError(ERR_RECORD_INVALID_STATE, 409, "Record is not DRAFT")
    if engagement["status"] != "APPROVED":
        raise ApiError(ERR_ENGAGEMENT_NOT_APPROVED, 409,
                       "Engagement is not APPROVED")

    # regulatory/licensing
    sealer = db.reviewers.get(uid)
    lic = license_for_state(sealer, engagement["pinned_state_code"]) if sealer else None
    if lic is None:
        raise ApiError(ERR_LICENSE_STATE_MISMATCH, 422,
                       "Sealer holds no license for the engagement's pinned state")
    current_date = db.clock_now().date()
    if parse_date(lic["expires_on"]) < current_date:
        raise ApiError(ERR_LICENSE_WINDOW_INSUFFICIENT, 422,
                       "Sealer's state license expires before the seal date")
    if engagement["pinned_requires_se_seal"] and lic["license_type"] != "SE":
        raise ApiError(ERR_SE_SEAL_REQUIRED, 422,
                       "This jurisdiction requires an SE-licensed sealer")

    # referential completeness
    refresh_engagement_counts(engagement)
    if engagement["deferred_pending_count"] != 0:
        raise ApiError(ERR_DEFERRED_SUBMITTALS_OUTSTANDING, 409,
                       "Deferred submittals remain outstanding on the engagement")

    now = db.clock_now()
    record["status"] = "SEALED"
    record["sealed_by_reviewer_id"] = uid
    record["sealed_at"] = now
    db.touch(record)

    # final fee: current inputs, actual cycle count, approved deferred items
    approved_items = [
        d for d in db.deferred_submittals.values()
        if d["engagement_id"] == engagement["id"] and d["status"] == "APPROVED"
    ]
    engagement["final_fee_cents"] = compute_final_fee(engagement, approved_items)
    db.touch(engagement)
    refresh_engagement_counts(engagement)

    return success_object(db.serialize(record))


@bp.post("/plan-review/records/<rid>/transmit")
def transmit_record(rid):
    require_roles("ReviewCoordinator")
    get_json_body(required=False)
    record = get_record_or_404(rid)
    engagement = db.engagements[record["engagement_id"]]

    if record["status"] != "SEALED":
        raise ApiError(ERR_RECORD_INVALID_STATE, 409, "Record is not SEALED")

    record["status"] = "TRANSMITTED"
    record["transmitted_at"] = db.clock_now()
    db.touch(record)

    # engagement cascade: APPROVED -> COMPLETED
    engagement["status"] = "COMPLETED"
    db.touch(engagement)
    refresh_engagement_counts(engagement)

    return success_object(db.serialize(record))
