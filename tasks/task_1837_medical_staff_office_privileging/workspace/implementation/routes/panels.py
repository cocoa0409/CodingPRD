from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, paginate, require_enum, require_fields

bp = Blueprint("panels", __name__)

OFFICER = "HearingOfficer"
PANEL_ROLES = ("CHAIR", "MEMBER")
SEATABLE_STATES = ("MEC_ENDORSED", "HEARING_REQUESTED", "REMANDED",
                   "HEARING_HELD")


@bp.route("/mso/hearing-panels", methods=["POST"])
@require_roles(OFFICER)
def create_panel():
    body = get_body()
    # Rung 3: existence.
    case_id = body.get("case_id")
    case = None
    if case_id is not None:
        case = db.cases.get(case_id)
        if case is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "AdverseActionCase not found")
    panelist_id = body.get("panel_member_id")
    panelist = None
    if panelist_id is not None:
        panelist = db.members.get(panelist_id)
        if panelist is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "MedicalStaffMember not found")
    # Rung 5: state — the case must be in a seatable state.
    if case is not None and case["case_status"] not in SEATABLE_STATES:
        errors.raise_err(errors.ERR_INVALID_STATE,
                         "Case is not in a hearing state that admits seating")
    # Rung 6: SoD — a tagged member is barred from the case's panel.
    if case is not None and panelist is not None and \
            case["id"] in (panelist.get("sod_exclusion_tags") or []):
        errors.raise_err(errors.ERR_PANELIST_SOD_EXCLUDED,
                         "Panelist is excluded from this case by segregation "
                         "of duties")
    # Rung 11: input shape.
    require_fields(body, ["case_id", "panel_member_id", "panel_role"])
    require_enum(body, "panel_role", PANEL_ROLES)

    rec = services.base_record()
    rec.update({
        "case_id": case_id,
        "panel_member_id": panelist_id,
        "panel_role": body["panel_role"],
        "panel_status": "SEATED",
        "seated_at": services.now_iso(),
    })
    db.panels[rec["id"]] = rec
    return ok_object(serializers.panel(rec), 201)


@bp.route("/mso/hearing-panels", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_panels():
    items, limit, offset, total = paginate(
        db.panels.values(), serializers.panel,
        ["case_id", "panel_member_id", "panel_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/hearing-panels/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_panel(pid):
    rec = db.panels.get(pid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "HearingPanel not found")
    return ok_object(serializers.panel(rec))


@bp.route("/mso/hearing-panels/<pid>/recuse", methods=["POST"])
@require_roles(OFFICER)
def recuse_panel(pid):
    get_body()
    rec = db.panels.get(pid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "HearingPanel not found")
    if rec["panel_status"] != "SEATED":
        errors.raise_err(errors.ERR_PANELIST_NOT_SEATED,
                         "Panelist is not SEATED")
    rec["panel_status"] = "RECUSED"
    services.touch(rec)
    return ok_object(serializers.panel(rec))
