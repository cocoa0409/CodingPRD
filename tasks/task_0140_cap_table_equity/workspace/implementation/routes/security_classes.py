"""SecurityClass routes. PRD §3.2."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, optional_id, optional_number, pagination_params, paginate_and_sort,
    require_enum, require_int, require_number, require_string, stamp_common_fields,
)
from errors import APIError, ERR_VALIDATION, ERR_SENIORITY_CYCLE
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("security_classes", __name__)


def _would_cycle(classes_by_id: dict, new_id: str, parent_id) -> bool:
    """Walk the seniority chain from parent_id; cycle if we return to new_id."""
    seen = set()
    cur = parent_id
    while cur is not None:
        if cur == new_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        nxt = classes_by_id.get(cur)
        if nxt is None:
            return False
        cur = nxt.get("seniority_below_class_id")
    return False


@bp.post("/security-classes")
@require_roles("Administrator")
def create_security_class():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    ct = core.get_cap_table(cap_table_id)  # existence first (ERR_NOT_FOUND)
    name = require_string(body, "name", non_empty=True)
    class_type = require_enum(body, "class_type", {"COMMON", "PREFERRED"})
    original_issue_price_cents = require_int(body, "original_issue_price_cents", min_value=0)
    liquidation_pref_multiple = optional_number(body, "liquidation_pref_multiple", default=1.0, min_value=0)
    participating = body.get("participating", False)
    if not isinstance(participating, bool):
        raise APIError(ERR_VALIDATION, "participating must be a boolean.", 400)
    participation_cap_multiple = optional_number(body, "participation_cap_multiple", default=0.0, min_value=0)
    seniority_below_class_id = optional_id(body, "seniority_below_class_id")

    # name unique within cap table
    for c in core.classes_of(cap_table_id):
        if c["name"] == name:
            raise APIError(ERR_VALIDATION, "name must be unique within the cap table.", 400)

    # COMMON must carry a liquidation_pref_multiple of zero. PRD §3.2.
    if class_type == "COMMON" and liquidation_pref_multiple != 0:
        raise APIError(ERR_VALIDATION, "A COMMON class must carry liquidation_pref_multiple of 0.", 400)

    if seniority_below_class_id is not None:
        parent = core.get_security_class(seniority_below_class_id)  # ERR_NOT_FOUND
        classes_by_id = {c["id"]: c for c in core.classes_of(cap_table_id)}
        new_id_placeholder = "__new__"
        classes_by_id[new_id_placeholder] = {
            "id": new_id_placeholder,
            "seniority_below_class_id": seniority_below_class_id,
        }
        if _would_cycle(classes_by_id, new_id_placeholder, seniority_below_class_id):
            raise APIError(ERR_SENIORITY_CYCLE, "seniority_below_class_id introduces a cycle.", 422)

    now = db.now_utc()
    sc = {
        "cap_table_id": cap_table_id,
        "name": name,
        "class_type": class_type,
        "shares_outstanding": 0,
        "original_issue_price_cents": original_issue_price_cents,
        "liquidation_pref_multiple": liquidation_pref_multiple,
        "participating": participating,
        "participation_cap_multiple": participation_cap_multiple,
        "seniority_below_class_id": seniority_below_class_id,
    }
    stamp_common_fields(sc, now)
    db.security_classes[sc["id"]] = sc
    return created(core.serialize(sc))


@bp.get("/security-classes/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_security_class(cid):
    sc = core.get_security_class(cid)
    return success(core.serialize(sc))


@bp.get("/security-classes")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_security_classes():
    limit, offset = pagination_params()
    items = list(db.security_classes.values())
    cap_table_id = request.args.get("cap_table_id")
    seniority = request.args.get("seniority_below_class_id")
    if cap_table_id is not None:
        items = [c for c in items if c["cap_table_id"] == cap_table_id]
    if seniority is not None:
        items = [c for c in items if c.get("seniority_below_class_id") == seniority]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )
