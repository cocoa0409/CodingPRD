"""SafeNote routes. PRD §3.10."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import (
    get_body, optional_int, optional_number, pagination_params, paginate_and_sort,
    require_datetime, require_enum, require_int, require_string, stamp_common_fields, touch,
)
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TABLE_NOT_OPEN,
    ERR_WRONG_CLASS_TYPE, ERR_STALE_VERSION, ERR_VALIDATION,
)
from middleware import require_roles
from response import created, success, list_response
from services import core
from services.calc import conversion_share_count

bp = Blueprint("safe_notes", __name__)


@bp.post("/safe-notes")
@require_roles("Administrator")
def create_safe_note():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    shareholder_id = require_string(body, "shareholder_id")
    sh = core.get_shareholder(shareholder_id)
    if sh["cap_table_id"] != cap_table_id:
        raise APIError(ERR_NOT_FOUND, "Shareholder not found.", 404)
    instrument_type = require_enum(body, "instrument_type", {"SAFE", "NOTE"})
    principal_cents = require_int(body, "principal_cents", strict_positive=True)
    valuation_cap_cents = optional_int(body, "valuation_cap_cents", default=0, min_value=0)
    discount_pct = optional_number(body, "discount_pct", default=0.0, min_value=0, max_value_exclusive=1.0)
    interest_rate_pct = optional_number(body, "interest_rate_pct", default=0.0, min_value=0)
    issue_date = require_datetime(body, "issue_date")

    # SAFE must carry interest_rate_pct of 0 (PRD §3.10)
    if instrument_type == "SAFE" and interest_rate_pct != 0:
        raise APIError(ERR_VALIDATION, "A SAFE must carry interest_rate_pct of 0.", 400)

    now = db.now_utc()
    note = {
        "cap_table_id": cap_table_id,
        "shareholder_id": shareholder_id,
        "instrument_type": instrument_type,
        "principal_cents": principal_cents,
        "valuation_cap_cents": valuation_cap_cents,
        "discount_pct": discount_pct,
        "interest_rate_pct": interest_rate_pct,
        "issue_date": issue_date,
        "converted_share_count": 0,
        "converted_into_class_id": None,
        "status": "DRAFT",
    }
    stamp_common_fields(note, now)
    db.safe_notes[note["id"]] = note
    return created(core.serialize(note))


@bp.get("/safe-notes/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_safe_note(cid):
    return success(core.serialize(core.get_safe_note(cid)))


@bp.get("/safe-notes")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_safe_notes():
    limit, offset = pagination_params()
    items = list(db.safe_notes.values())
    for key in ("cap_table_id", "shareholder_id", "converted_into_class_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    if g.user_role == "Stakeholder":
        items = [i for i in items if i["shareholder_id"] == g.user_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/safe-notes/<cid>/submit-terms")
@require_roles("Administrator")
def submit_terms(cid):
    note = core.get_safe_note(cid)
    if note["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Note must be DRAFT to submit terms.", 409)
    now = db.now_utc()
    note["status"] = "NEGOTIATING"
    touch(note, now)
    return success(core.serialize(note))


@bp.post("/safe-notes/<cid>/revise")
@require_roles("Administrator")
def revise(cid):
    note = core.get_safe_note(cid)
    if note["status"] != "NEGOTIATING":
        raise APIError(ERR_INVALID_STATE, "Note must be NEGOTIATING to revise.", 409)
    now = db.now_utc()
    note["status"] = "DRAFT"
    touch(note, now)
    return success(core.serialize(note))


@bp.post("/safe-notes/<cid>/execute")
@require_roles("BoardApprover")
def execute(cid):
    note = core.get_safe_note(cid)
    ct = core.get_cap_table(note["cap_table_id"])
    if note["status"] != "NEGOTIATING":
        raise APIError(ERR_INVALID_STATE, "Note must be NEGOTIATING to execute.", 409)
    if ct["status"] != "OPEN":
        raise APIError(ERR_TABLE_NOT_OPEN, "Cap table is not OPEN.", 409)
    now = db.now_utc()
    note["status"] = "OUTSTANDING"
    touch(note, now)
    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize(note))


@bp.post("/safe-notes/<cid>/convert")
@require_roles("BoardApprover")
def convert(cid):
    note = core.get_safe_note(cid)
    body = get_body()
    target_class_id = require_string(body, "target_class_id")
    target = core.get_security_class(target_class_id)

    if note["status"] != "OUTSTANDING":
        raise APIError(ERR_INVALID_STATE, "Note must be OUTSTANDING to convert.", 409)

    # OCC check (priority): expected_note_version must match
    expected = body.get("expected_note_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) \
            or expected != note["version"]:
        raise APIError(ERR_STALE_VERSION, "expected_note_version does not match current version.", 412)

    # target must be PREFERRED on the same cap table
    if target["cap_table_id"] != note["cap_table_id"]:
        raise APIError(ERR_NOT_FOUND, "SecurityClass not found.", 404)
    if target["class_type"] != "PREFERRED":
        raise APIError(ERR_WRONG_CLASS_TYPE, "Conversion target class must be PREFERRED.", 422)

    ct = core.get_cap_table(note["cap_table_id"])
    now = db.now_utc()
    # fully_diluted at conversion time drives the cap price; ensure it's current
    core.refresh_cap_table_read(ct)
    shares = conversion_share_count(note, target, ct, now)

    note["converted_share_count"] = shares
    note["converted_into_class_id"] = target_class_id
    note["status"] = "CONVERTED"
    # cascade: target class shares_outstanding += shares; recompute ledger
    target["shares_outstanding"] += shares
    touch(target, now)
    touch(note, now)  # increments SafeNote.version by 1
    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize(note))


@bp.post("/safe-notes/<cid>/repay")
@require_roles("BoardApprover")
def repay(cid):
    note = core.get_safe_note(cid)
    if note["status"] != "OUTSTANDING":
        raise APIError(ERR_INVALID_STATE, "Note must be OUTSTANDING to repay.", 409)
    now = db.now_utc()
    note["status"] = "REPAID"
    touch(note, now)
    return success(core.serialize(note))
