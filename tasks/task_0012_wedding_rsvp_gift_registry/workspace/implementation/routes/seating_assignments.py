"""SeatingAssignment routes: create (manual), list, read, delete."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_CROSS_WEDDING_REFERENCE,
    ERR_KIDS_SEATING_VIOLATION,
    ERR_TABLE_FULL,
    ERR_ALREADY_SEATED,
)
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, ok_no_content, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_seating_or_404,
    get_wedding_or_404,
    get_table_or_404,
    assert_couple_owns,
    assert_not_archived,
)

bp = Blueprint("seating_assignments", __name__)


def _kids_only_open(wedding_id: str) -> bool:
    """True iff any kids_only Table of this wedding has open capacity."""
    # Count current assignments per kids_only table.
    per_table = {}
    for sa in db.seating_assignments.values():
        if sa.get("wedding_id") != wedding_id:
            continue
        per_table[sa["table_id"]] = per_table.get(sa["table_id"], 0) + 1
    for t in db.tables.values():
        if t.get("wedding_id") != wedding_id:
            continue
        if t.get("kids_only") and per_table.get(t["id"], 0) < int(t["capacity"]):
            return True
    return False


@bp.route("/seating-assignments", methods=["POST"])
def create_seating_assignment():
    require_auth(["Couple"])()
    body = get_json_body()
    wedding_id = body.get("wedding_id")
    table_id = body.get("table_id")
    assignee_type = body.get("assignee_type")
    assignee_id = body.get("assignee_id")
    if not isinstance(wedding_id, str) or not wedding_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "wedding_id required")
    if not isinstance(table_id, str) or not table_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "table_id required")
    if assignee_type not in ("GUEST", "PLUS_ONE"):
        raise APIError(ERR_INVALID_REQUEST, 400, "assignee_type must be GUEST or PLUS_ONE")
    if not isinstance(assignee_id, str) or not assignee_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "assignee_id required")

    # Existence checks. Note path validation §2.5 normally applies left-to-right
    # for path params; here all 4 ids are in the body, so we use a logical
    # order: wedding -> table -> assignee.
    w = db.weddings.get(wedding_id)
    if w is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Wedding {wedding_id} not found")
    assert_couple_owns(w)
    assert_not_archived(w)

    t = db.tables.get(table_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Table {table_id} not found")
    if assignee_type == "GUEST":
        a = db.guests.get(assignee_id)
        if a is None:
            raise APIError(ERR_NOT_FOUND, 404, f"Guest {assignee_id} not found")
    else:
        a = db.plus_ones.get(assignee_id)
        if a is None:
            raise APIError(ERR_NOT_FOUND, 404, f"PlusOne {assignee_id} not found")

    # State precondition: wedding must be in RSVP_CLOSED or SEATED (otherwise
    # there's no meaningful seating). PRD doesn't make this explicit at write
    # time, but the algorithm only operates in those states. To be permissive
    # we allow seating creation in RSVP_CLOSED and SEATED; reject earlier.
    if w.get("status") not in ("RSVP_CLOSED", "SEATED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Wedding must be RSVP_CLOSED or SEATED to create seating assignments")

    # Validations in priority order (§2.9):
    # 7. Kids-only seating violation.
    a_is_child = bool(a.get("is_child"))
    if t.get("kids_only") and not a_is_child:
        raise APIError(ERR_KIDS_SEATING_VIOLATION, 422,
                       "kids_only table cannot seat a non-child")
    if not t.get("kids_only") and a_is_child:
        if _kids_only_open(wedding_id):
            raise APIError(ERR_KIDS_SEATING_VIOLATION, 422,
                           "child must be seated at a kids_only table when one has open capacity")
    # 9. Cross-wedding reference.
    if t.get("wedding_id") != wedding_id:
        raise APIError(ERR_CROSS_WEDDING_REFERENCE, 422,
                       "table belongs to a different wedding")
    if a.get("wedding_id") != wedding_id:
        raise APIError(ERR_CROSS_WEDDING_REFERENCE, 422,
                       "assignee belongs to a different wedding")
    # 11. Table capacity.
    per_table = sum(1 for sa in db.seating_assignments.values()
                    if sa.get("table_id") == table_id)
    if per_table >= int(t["capacity"]):
        raise APIError(ERR_TABLE_FULL, 422, "Table is at full capacity")
    # 12. Uniqueness on (wedding_id, assignee_type, assignee_id).
    for sa in db.seating_assignments.values():
        if (sa.get("wedding_id") == wedding_id
                and sa.get("assignee_type") == assignee_type
                and sa.get("assignee_id") == assignee_id):
            raise APIError(ERR_ALREADY_SEATED, 422, "assignee already seated")

    sa = {
        "wedding_id": wedding_id,
        "table_id": table_id,
        "assignee_type": assignee_type,
        "assignee_id": assignee_id,
    }
    db.stamp_common(sa)
    db.seating_assignments[sa["id"]] = sa

    # If wedding was SEATED, revert to RSVP_CLOSED.
    if w.get("status") == "SEATED":
        w["status"] = "RSVP_CLOSED"
        w["seating_dirty"] = True
        db.bump(w)
    return ok_object(sa, 201)


@bp.route("/seating-assignments", methods=["GET"])
def list_seating_assignments():
    require_auth(["Couple", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    w_id = request.args.get("wedding_id")
    t_id = request.args.get("table_id")
    atype = request.args.get("assignee_type")
    aid = request.args.get("assignee_id")
    rows = list(db.seating_assignments.values())
    if current_role() == "Couple":
        owned = {w["id"] for w in db.weddings.values()
                 if w.get("couple_user_id") == current_user_id()}
        rows = [r for r in rows if r.get("wedding_id") in owned]
    if w_id is not None:
        rows = [r for r in rows if r.get("wedding_id") == w_id]
    if t_id is not None:
        rows = [r for r in rows if r.get("table_id") == t_id]
    if atype is not None:
        rows = [r for r in rows if r.get("assignee_type") == atype]
    if aid is not None:
        rows = [r for r in rows if r.get("assignee_id") == aid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.route("/seating-assignments/<sid>", methods=["GET"])
def get_seating(sid):
    require_auth(["Couple", "PlatformAdmin"])()
    sa = get_seating_or_404(sid)
    if current_role() == "Couple":
        w = db.weddings.get(sa["wedding_id"])
        if w:
            assert_couple_owns(w)
    return ok_object(sa)


@bp.route("/seating-assignments/<sid>", methods=["DELETE"])
def delete_seating(sid):
    require_auth(["Couple"])()
    sa = get_seating_or_404(sid)
    w = db.weddings.get(sa["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    w_state = w.get("status")
    del db.seating_assignments[sid]
    if w_state == "SEATED":
        w["status"] = "RSVP_CLOSED"
        w["seating_dirty"] = True
        db.bump(w)
    return ok_no_content()
