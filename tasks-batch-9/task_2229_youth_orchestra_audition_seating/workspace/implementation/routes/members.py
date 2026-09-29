"""Musicians, their two state dimensions, and the adjudicator roster."""

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, NO_PANELIST, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db
from validate import Body, pagination

bp = Blueprint("members", __name__)

ENROLLMENT_STATUSES = ("PROSPECT", "ENROLLED", "GRADUATED", "WITHDRAWN", "ALUMNI")
STANDING_STATUSES = ("CLEAR", "ATTENDANCE_PROBATION", "FINANCIAL_HOLD")
INCOME_BANDS = ("BAND_A", "BAND_B", "BAND_C")

ENROLLMENT_TRANSITIONS = {
    "PROSPECT": ("WITHDRAWN",),
    "ENROLLED": ("GRADUATED", "WITHDRAWN"),
    "GRADUATED": ("ALUMNI",),
    "WITHDRAWN": (),
    "ALUMNI": (),
}
STANDING_TRANSITIONS = {
    "CLEAR": (),
    "ATTENDANCE_PROBATION": ("CLEAR",),
    "FINANCIAL_HOLD": (),
}


# -------------------------------------------------------------------- members
@bp.route("/members", methods=["POST"])
@endpoint("RegistrarStaff")
def create_member():
    body = Body()
    legal_name = body.string("legal_name", required=True, min_len=1, max_len=200)
    instrument = body.enum("primary_instrument", calc.INSTRUMENTS, required=True)
    grade_level = body.integer("grade_level", required=True, minimum=4, maximum=12)
    graduation_year = body.integer("graduation_year", required=True, minimum=2026)
    income_band = body.enum("household_income_band", INCOME_BANDS, required=True)
    years_in_org = body.integer("years_in_org", required=False, default=0,
                                minimum=0, maximum=12)
    sibling_enrolled = body.boolean("sibling_enrolled", default=False)
    alumni_opt_in = body.boolean("alumni_engagement_opt_in", default=False)

    row = svc.new_row()
    row.update({
        "legal_name": legal_name,
        "primary_instrument": instrument,
        "instrument_class": calc.instrument_class(instrument),
        "grade_level": grade_level,
        "graduation_year": graduation_year,
        "years_in_org": years_in_org,
        "household_income_band": income_band,
        "sibling_enrolled": sibling_enrolled,
        "alumni_engagement_opt_in": alumni_opt_in,
        "enrollment_status": "PROSPECT",
        "standing_status": "CLEAR",
        "probation_baseline_count": 0,
    })
    db.members[row["id"]] = row
    return ok(svc.member_json(row), 201)


@bp.route("/members", methods=["GET"])
@endpoint(*NO_PANELIST)
def list_members():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.members.values())), request.args,
                             ["enrollment_status", "standing_status",
                              "primary_instrument"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.member_json(r) for r in page], limit, offset, len(rows))


@bp.route("/members/<member_id>", methods=["GET"])
@endpoint(*NO_PANELIST)
def read_member(member_id):
    return ok(svc.member_json(svc.member_or_404(member_id)))


@bp.route("/members/<member_id>/status-transition", methods=["POST"])
@endpoint("RegistrarStaff")
def status_transition(member_id):
    member = svc.member_or_404(member_id)
    body = Body()
    dimension = body.enum("dimension", ("ENROLLMENT", "STANDING"), required=True)
    to_status = body.enum("to_status", ENROLLMENT_STATUSES + STANDING_STATUSES,
                          required=True)

    if dimension == "ENROLLMENT":
        allowed = ENROLLMENT_TRANSITIONS[member["enrollment_status"]]
        if to_status not in allowed:
            raise ApiError("ERR_INVALID_MEMBER_TRANSITION",
                           "%s is not reachable from %s on the ENROLLMENT dimension."
                           % (to_status, member["enrollment_status"]))
        if to_status == "ALUMNI" and not member["alumni_engagement_opt_in"]:
            raise ApiError("ERR_INVALID_MEMBER_TRANSITION",
                           "ALUMNI requires alumni_engagement_opt_in.")
        if to_status == "GRADUATED":
            _refuse_when_delinquent(member)
            member["enrollment_status"] = "GRADUATED"
            svc.touch(member)
            _vacate_all_seats(member)
        elif to_status == "WITHDRAWN":
            previous = member["enrollment_status"]
            member["enrollment_status"] = "WITHDRAWN"
            svc.touch(member)
            svc.withdraw_open_placements(member["id"])
            if previous == "ENROLLED":
                _vacate_all_seats(member)
        else:
            member["enrollment_status"] = to_status
            svc.touch(member)
    else:
        allowed = STANDING_TRANSITIONS[member["standing_status"]]
        if to_status not in allowed:
            raise ApiError("ERR_INVALID_MEMBER_TRANSITION",
                           "%s is not reachable from %s on the STANDING dimension."
                           % (to_status, member["standing_status"]))
        _refuse_when_delinquent(member)
        member["standing_status"] = "CLEAR"
        member["probation_baseline_count"] = svc.effective_unexcused_count(member)
        svc.touch(member)

    return ok(svc.member_json(member))


def _refuse_when_delinquent(member):
    for account in svc.accounts_of_member(member["id"]):
        if account["billing_status"] == "DELINQUENT":
            raise ApiError("ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE",
                           "A delinquent tuition account blocks this transition.")


def _vacate_all_seats(member):
    for seat in svc.active_seats_of_member(member["id"]):
        svc.vacate_seat(seat)


# ------------------------------------------------------------------ panelists
@bp.route("/panelists", methods=["POST"])
@endpoint("ArtisticDirector")
def create_panelist():
    body = Body()
    display_name = body.string("display_name", required=True, min_len=1, max_len=200)
    expertise = body.enum("instrument_expertise", calc.INSTRUMENTS, required=True)
    panel_role = body.enum("panel_role", ("ADJUDICATOR", "CHAIR"), required=False,
                           default="ADJUDICATOR")
    conflicts = body.str_array("conflict_member_ids", required=False, default=None)
    available = body.boolean("available_for_panels", required=False, default=True)

    row = svc.new_row()
    row.update({
        "display_name": display_name,
        "instrument_expertise": expertise,
        "panel_role": panel_role,
        "conflict_member_ids": list(conflicts) if conflicts else [],
        "available_for_panels": available,
    })
    db.panelists[row["id"]] = row
    return ok(svc.panelist_json(row), 201)


@bp.route("/panelists", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_panelists():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.panelists.values())), request.args,
                             ["instrument_expertise", "available_for_panels"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.panelist_json(r) for r in page], limit, offset, len(rows))


@bp.route("/panelists/<panelist_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_panelist(panelist_id):
    return ok(svc.panelist_json(svc.panelist_or_404(panelist_id)))
