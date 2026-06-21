"""Drug-test endpoints (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import (
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_fields,
    sorted_by_created,
)

bp = Blueprint("drug_tests", __name__)

PANELS = {"FIVE_PANEL", "TEN_PANEL"}
RESULTS = {"NEGATIVE", "POSITIVE", "DILUTE", "REFUSED"}


@bp.post("/supervisees/<sid>/check-ins/<cid>/drug-tests")
@require_roles("Officer")
def create(sid, cid):
    get_supervisee_or_404(sid)
    get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    body = get_body()
    require_fields(body, ["result"])
    check_enum(body["result"], RESULTS, "result")

    panel = body.get("panel", "FIVE_PANEL")
    if panel is None:
        panel = "FIVE_PANEL"
    check_enum(panel, PANELS, "panel")

    substances = body.get("substances", [])
    if substances is None:
        substances = []
    if not isinstance(substances, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "substances must be an array.")

    # ERR_VALIDATION (422): non-empty substances when result != POSITIVE.
    if body["result"] != "POSITIVE" and len(substances) > 0:
        raise ApiError(*ERR_VALIDATION, "substances must be empty when result is not POSITIVE.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "check_in_id": cid,
            "panel": panel,
            "result": body["result"],
            "substances": substances,
        }
    )
    db.drug_tests[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/check-ins/<cid>/drug-tests")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_drug_tests(sid, cid):
    get_supervisee_or_404(sid)
    get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    limit, offset = paginate(request.args)
    records = [d for d in db.drug_tests.values() if d.get("check_in_id") == cid]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)
