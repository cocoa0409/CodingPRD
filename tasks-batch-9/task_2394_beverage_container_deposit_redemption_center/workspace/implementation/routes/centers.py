from flask import Blueprint, g, request

import calculations as calc
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own
from routes.common import filter_eq, listing, lookup, unique
from services import projections as proj

bp = Blueprint("centers", __name__)

CENTER_ACTIONS = ("ACTIVATE", "SUSPEND", "REINSTATE", "CLOSE")
CENTER_ADMIN_ONLY = ("ACTIVATE", "REINSTATE", "CLOSE")
CENTER_TRANSITIONS = {
    "ACTIVATE": (("PROVISIONAL",), "OPERATIONAL"),
    "SUSPEND": (("OPERATIONAL",), "SUSPENDED"),
    "REINSTATE": (("SUSPENDED",), "OPERATIONAL"),
    "CLOSE": (("OPERATIONAL", "SUSPENDED"), "CLOSED"),
}


@bp.post("/redemption-centers")
def create_center():
    authenticate("ProgramAdmin")
    body = v.body()
    site_name = v.req_str(body, "site_name")
    x_miles = v.req_num(body, "x_miles")
    y_miles = v.req_num(body, "y_miles")
    accepted_materials = v.req_str_list(body, "accepted_materials",
                                        choices=calc.COVERED_MATERIALS)
    accepts_all = v.opt_bool(body, "accepts_all_materials", True)
    cap = v.opt_int(body, "daily_account_cap_containers", 350, minimum=0)
    opening_cash = v.opt_int(body, "opening_cash_cents", 0, minimum=0)
    rec = db.new_record({
        "site_name": site_name,
        "x_miles": x_miles,
        "y_miles": y_miles,
        "accepts_all_materials": accepts_all,
        "accepted_materials": accepted_materials,
        "daily_account_cap_containers": cap,
        "opening_cash_cents": opening_cash,
        "cash_drawer_balance_cents": 0,
        "status": "PROVISIONAL",
        "suspension_reason": None,
        "machine_count": 0,
        "out_of_service_machine_count": 0,
        "accepted_container_count": 0,
        "unbatched_container_count": 0,
        "batched_container_count": 0,
        "withheld_visit_count": 0,
    })
    db.centers[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/redemption-centers/<rid>")
def get_center(rid):
    authenticate("ProgramAdmin", "CenterOperator", "RetailClerk")
    own(center_id=rid)
    rec = lookup("center", rid)
    return response.obj(db.public(rec))


@bp.get("/redemption-centers")
def list_centers():
    authenticate("ProgramAdmin", "CenterOperator", "RetailClerk")
    rows = db.ordered(db.centers)
    rows = filter_eq(rows, "status", request.args.get("status"))
    return listing(rows)


@bp.post("/redemption-centers/<rid>/status-changes")
def center_status_change(rid):
    authenticate("ProgramAdmin", "CenterOperator")
    own(center_id=rid)
    body = v.body()
    raw_action = body.get("action")
    if isinstance(raw_action, str):
        narrow(raw_action, program_admin_only=CENTER_ADMIN_ONLY,
               role_actions={"CenterOperator": ("SUSPEND",)})
    center = lookup("center", rid)
    action = v.req_enum(body, "action", CENTER_ACTIONS)
    v.opt_str(body, "reason")

    froms, target = CENTER_TRANSITIONS[action]
    if center["status"] not in froms:
        fail("ERR_INVALID_CENTER_STATE",
             "Action %s is not available from %s." % (action, center["status"]))

    if action == "ACTIVATE":
        if center["machine_count"] < 1:
            fail("ERR_CENTER_HAS_NO_MACHINE", "The centre has no installed machine.")
        center["cash_drawer_balance_cents"] = center["opening_cash_cents"]
        center["suspension_reason"] = None
    elif action == "SUSPEND":
        center["suspension_reason"] = (
            "OPERATOR_REQUEST" if g.role == "CenterOperator" else "PROGRAM_ACTION")
    elif action == "REINSTATE":
        if not (center["out_of_service_machine_count"] < center["machine_count"]):
            fail("ERR_MACHINE_FLEET_DOWN", "The centre's whole fleet is out of service.")
        center["suspension_reason"] = None
    elif action == "CLOSE":
        if proj.center_has_open_visits(center["id"]):
            fail("ERR_CENTER_HAS_OPEN_VISITS", "The centre still has unfinished counting.")
        center["suspension_reason"] = None

    center["status"] = target
    touch(center)
    if action == "CLOSE":
        proj.close_center_cascades(center)
    return response.obj(db.public(center))


@bp.post("/redemption-centers/<rid>/machines")
def create_machine(rid):
    authenticate("ProgramAdmin", "CenterOperator")
    own(center_id=rid)
    center = lookup("center", rid)
    body = v.body()
    asset_tag = v.req_str(body, "asset_tag")
    material = v.req_enum(body, "accepted_material", calc.COVERED_MATERIALS)
    capacity = v.opt_int(body, "bin_capacity_containers", 2000, minimum=1)
    unique(db.machines, "asset_tag", asset_tag, "ERR_DUPLICATE_ASSET_TAG")
    rec = db.new_record({
        "center_id": center["id"],
        "asset_tag": asset_tag,
        "accepted_material": material,
        "bin_capacity_containers": capacity,
        "bin_filled_count": 0,
        "status": "IDLE",
        "jam_day": None,
        "jam_count_today": 0,
        "session_started_at": None,
        "last_session_closed_at": None,
        "open_session_count": 0,
        "jam_hold_count": 0,
    })
    db.machines[rec["id"]] = rec
    proj.recompute_center_machine_counts(center)
    return response.obj(db.public(rec), 201)


@bp.get("/redemption-centers/<rid>/machines")
def list_machines(rid):
    authenticate("ProgramAdmin", "CenterOperator")
    own(center_id=rid)
    center = lookup("center", rid)
    rows = proj.center_machines(center["id"])
    return listing(rows)
