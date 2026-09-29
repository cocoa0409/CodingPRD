"""Helpers shared by every route module: path resolution (rung 6), body
reference resolution (rung 7) and the seated-board-chair test (rung 14)."""

import db
from errors import ApiError
from response import list_response
from validation import filter_rows, paginate

NOT_FOUND = {
    "health_centers": "ERR_HEALTH_CENTER_NOT_FOUND",
    "poverty_guidelines": "ERR_POVERTY_GUIDELINE_NOT_FOUND",
    "board_members": "ERR_BOARD_MEMBER_NOT_FOUND",
    "service_sites": "ERR_SERVICE_SITE_NOT_FOUND",
    "service_definitions": "ERR_SERVICE_DEFINITION_NOT_FOUND",
    "scope_change_requests": "ERR_SCOPE_CHANGE_REQUEST_NOT_FOUND",
    "fee_schedules": "ERR_FEE_SCHEDULE_NOT_FOUND",
    "discount_tiers": "ERR_DISCOUNT_TIER_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "income_verifications": "ERR_INCOME_VERIFICATION_NOT_FOUND",
    "encounters": "ERR_ENCOUNTER_NOT_FOUND",
    "waivers": "ERR_WAIVER_NOT_FOUND",
    "uds_reports": "ERR_UDS_REPORT_NOT_FOUND",
    "quality_measure_results": "ERR_QUALITY_MEASURE_RESULT_NOT_FOUND",
    "site_visit_findings": "ERR_SITE_VISIT_FINDING_NOT_FOUND",
    "corrective_action_plans": "ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND",
}


def require(collection, row_id):
    row = getattr(db.db, collection).get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def owner_ref(parsed, key, collection, path_id):
    """A child creation may name its owner in the body; the reference must
    resolve (rung 7) and must agree with the path (PRD 2.10)."""
    if key not in parsed or parsed[key] is None:
        return
    require(collection, parsed[key])
    if parsed[key] != path_id:
        raise ApiError("ERR_VALIDATION")


def body_ref(parsed, key, collection):
    """Resolve an optional body foreign key, returning the row or None."""
    if key not in parsed or parsed[key] is None:
        return None
    return require(collection, parsed[key])


def seated_chair(user_id, hc_id):
    """Rung 14: a BoardChair acting on board business is identified by a
    BoardMember row of that grantee whose status is SEATED."""
    member = db.db.board_members.get(user_id)
    if member is None or member["health_center_id"] != hc_id or member["status"] != "SEATED":
        raise ApiError("ERR_NOT_SEATED_BOARD_MEMBER")
    return member


def state(row, field, allowed):
    """Rung 11."""
    if row[field] not in allowed:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def segregation(acting_user_id, recorded_user_id):
    """Rung 13."""
    if recorded_user_id is not None and acting_user_id == recorded_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def listing(rows, serializer, limit, offset, specs=(), predicate=None):
    """Filter, count, paginate and serialise a list response."""
    rows = filter_rows(rows, list(specs))
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    total_count = len(rows)
    page = paginate(rows, limit, offset)
    return list_response([serializer(r) for r in page], limit, offset, total_count)
