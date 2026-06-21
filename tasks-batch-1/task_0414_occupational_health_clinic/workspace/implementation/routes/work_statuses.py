"""Work-status (return-to-work) endpoints (PRD §3.7, §3.11)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.calculations import osha_recordability
from services.common import base_entity, parse_date, touch
from services.serialize import public

bp = Blueprint("work_statuses", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
DISPOSITIONS = {"FULL_DUTY", "MODIFIED_DUTY", "OFF_WORK"}


@bp.route("/clinic/work-statuses", methods=["POST"])
def create_work_status():
    caller = authenticate()
    require_role(caller, {"Clinician"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        injury_case_id = body.get("injury_case_id")
        ic = db.injury_cases.get(injury_case_id) if injury_case_id is not None else None
        if ic is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "injury case missing or not found")

        # Priority 5: body well-formedness.
        disposition = body.get("disposition")
        if disposition not in DISPOSITIONS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid disposition")

        restriction_text = body.get("restriction_text")
        if disposition == "MODIFIED_DUTY":
            if not isinstance(restriction_text, str) or not restriction_text.strip():
                raise err(errors.ERR_INVALID_REQUEST,
                          "restriction_text is required for MODIFIED_DUTY")

        valid_from_raw = body.get("valid_from")
        valid_to_raw = body.get("valid_to")
        vf = parse_date(valid_from_raw) if valid_from_raw is not None else None
        vt = parse_date(valid_to_raw) if valid_to_raw is not None else None
        if vf is None:
            raise err(errors.ERR_INVALID_REQUEST, "valid_from must be a valid date")
        if vt is None:
            raise err(errors.ERR_INVALID_REQUEST, "valid_to must be a valid date")
        if vf > vt:
            raise err(errors.ERR_INVALID_REQUEST, "valid_from must be on or before valid_to")

        # Priority 7: state precondition + transition selection.
        if disposition == "FULL_DUTY":
            if ic["status"] == "OPEN":
                new_case_status = "CLOSED"
            elif ic["status"] == "RTW_PENDING":
                new_case_status = "CLOSED"
            else:
                raise err(errors.ERR_INJURY_CASE_NOT_OPEN,
                          "Injury case must be OPEN or RTW_PENDING for FULL_DUTY")
        else:
            # MODIFIED_DUTY / OFF_WORK require OPEN -> RTW_PENDING.
            if ic["status"] != "OPEN":
                raise err(errors.ERR_INJURY_CASE_NOT_OPEN,
                          "Injury case must be OPEN to add a non-full-duty note")
            new_case_status = "RTW_PENDING"

        ws = base_entity()
        ws.update({
            "injury_case_id": injury_case_id,
            "employer_id": ic["employer_id"],
            "disposition": disposition,
            "restriction_text": restriction_text,
            "valid_from": valid_from_raw,
            "valid_to": valid_to_raw,
            "superseded": False,
        })

        # Supersession: mark overlapping non-superseded prior notes (created_at ASC).
        existing = [w for w in db.work_statuses.values()
                    if w["injury_case_id"] == injury_case_id and not w["superseded"]]
        existing = sort_by_created(existing)
        for x in existing:
            xf = parse_date(x["valid_from"])
            xt = parse_date(x["valid_to"])
            if xf is None or xt is None:
                continue
            # Closed-interval overlap: x.valid_from <= W.valid_to AND W.valid_from <= x.valid_to.
            if xf <= vt and vf <= xt:
                x["superseded"] = True
                touch(x)

        db.work_statuses[ws["id"]] = ws

        # Case state transition.
        ic["status"] = new_case_status
        # Recompute OSHA recordability (treatment_level/days unchanged here).
        recordable, column = osha_recordability(
            ic["treatment_level"], ic["days_away"], ic["days_restricted"])
        ic["is_osha_recordable"] = recordable
        ic["osha_column"] = column
        touch(ic)

        return object_response(public(ws), 201)


@bp.route("/clinic/work-statuses", methods=["GET"])
def list_work_statuses():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.work_statuses.values())
    for key in ("injury_case_id", "employer_id"):
        val = args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/work-statuses/<ws_id>", methods=["GET"])
def get_work_status(ws_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    ws = lookup.get_work_status(ws_id)
    return object_response(public(ws), 200)
