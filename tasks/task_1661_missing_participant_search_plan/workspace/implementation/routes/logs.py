"""FiduciaryLogEntry endpoints (PRD section 3.8): the append-only record."""

import db
from errors import ApiError, ERR_NARRATIVE_TOO_SHORT
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_log
from util import (
    apply_filters,
    body_fk,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = make_blueprint("logs")

ENTRY_TYPES = {
    "SEARCH_PROTOCOL_SUMMARY",
    "NOTICE_DECISION",
    "DISTRIBUTION_DECISION",
    "FORFEITURE_RATIONALE",
    "PBGC_TRANSFER_RATIONALE",
    "CLOSURE_SIGNOFF",
}

NARRATIVE_MIN_CHARS = 50


@bp.post("/fiduciary-log-entries")
def create_log_entry():
    user_id, role = authenticate(["PlanAdministrator", "IndependentFiduciary"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "entry_type": {"type": "enum", "values": ENTRY_TYPES, "required": True},
        "narrative": {"type": "string", "required": True},
        "related_entity_id": {"type": "string"},
    })
    # The narrative length check is reported separately (still priority 2.5).
    if len(body["narrative"]) < NARRATIVE_MIN_CHARS:
        raise ApiError(
            ERR_NARRATIVE_TOO_SHORT, 422,
            "narrative must be at least 50 characters",
        )
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    entry = db.new_entity("logs", {
        "termination_case_id": case["id"],
        "entry_type": body["entry_type"],
        "narrative": body["narrative"],
        # Polymorphic reference, not a strict FK.
        "related_entity_id": body.get("related_entity_id"),
        "author_user_id": user_id,
        "author_role": role,
    }, common=False)
    return success_obj(public_log(entry), 201)


@bp.get("/termination-cases/<case_id>/fiduciary-log-entries")
def list_log_entries(case_id):
    authenticate(ALL_ROLES)
    case = path_entity("cases", case_id, "termination case")
    limit, offset = pagination_params()
    items = [
        e for e in db.all_of("logs") if e["termination_case_id"] == case["id"]
    ]
    items = apply_filters(items, ["entry_type"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_log(e) for e in page], limit, offset, total, has_more
    )
