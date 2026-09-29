from flask import Blueprint, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own
from routes.common import filter_eq, listing, lookup
from services import projections as proj

bp = Blueprint("retailers", __name__)

EXEMPTION_ACTIONS = ("CLAIM_EXEMPTION", "REVOKE_EXEMPTION")


@bp.post("/retailers")
def create_retailer():
    authenticate("ProgramAdmin")
    body = v.body()
    store_name = v.req_str(body, "store_name")
    x_miles = v.req_num(body, "x_miles")
    y_miles = v.req_num(body, "y_miles")
    area = v.req_int(body, "store_area_sqft", minimum=1)
    rec = db.new_record({
        "store_name": store_name,
        "x_miles": x_miles,
        "y_miles": y_miles,
        "store_area_sqft": area,
        "daily_limit_containers": calc.retailer_daily_limit(area),
        "obligation_status": "OBLIGATED",
        "nearest_center_id": None,
        "nearest_center_distance_miles": None,
        "exemption_granted_at": None,
    })
    db.retailers[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/retailers/<rid>")
def get_retailer(rid):
    authenticate("ProgramAdmin", "RetailClerk")
    own(retailer_id=rid)
    rec = lookup("retailer", rid)
    return response.obj(db.public(rec))


@bp.get("/retailers")
def list_retailers():
    authenticate("ProgramAdmin", "RetailClerk")
    rows = db.ordered(db.retailers)
    for field in ("obligation_status", "nearest_center_id"):
        rows = filter_eq(rows, field, request.args.get(field))
    return listing(rows)


@bp.post("/retailers/<rid>/exemption-actions")
def exemption_action(rid):
    authenticate("RetailClerk", "ProgramAdmin")
    own(retailer_id=rid)
    body = v.body()
    raw_action = body.get("action")
    if isinstance(raw_action, str):
        narrow(raw_action, program_admin_only=("REVOKE_EXEMPTION",),
               role_actions={"RetailClerk": ("CLAIM_EXEMPTION",)})
    retailer = lookup("retailer", rid)
    action = v.req_enum(body, "action", EXEMPTION_ACTIONS)
    v.opt_str(body, "reason")

    if action == "CLAIM_EXEMPTION":
        if retailer["obligation_status"] != "OBLIGATED":
            fail("ERR_INVALID_OBLIGATION_STATE",
                 "CLAIM_EXEMPTION is not available from %s." % retailer["obligation_status"])
        if proj.retailer_has_open_visits(retailer["id"]):
            fail("ERR_RETAILER_HAS_OPEN_VISITS", "The store still has unfinished counting.")
        candidates = [c for c in db.ordered(db.centers)
                      if c["status"] == "OPERATIONAL" and c["accepts_all_materials"]]
        if not candidates:
            fail("ERR_NO_ELIGIBLE_CENTER", "No full-service operational centre exists.")
        ranked = sorted(
            ((calc.planar_distance(c["x_miles"], c["y_miles"],
                                   retailer["x_miles"], retailer["y_miles"]), c["_seq"], c)
             for c in candidates),
            key=lambda item: (item[0], item[1]))
        distance, _, selected = ranked[0]
        if distance > calc.EXEMPTION_RADIUS_MILES:
            fail("ERR_EXEMPTION_DISTANCE_EXCEEDED",
                 "The nearest qualifying centre is more than 3.50 miles away.")
        retailer["obligation_status"] = "EXEMPT"
        retailer["nearest_center_id"] = selected["id"]
        retailer["nearest_center_distance_miles"] = float(distance)
        retailer["exemption_granted_at"] = clock.now_iso()
        touch(retailer)
    else:
        if retailer["obligation_status"] != "EXEMPT":
            fail("ERR_INVALID_OBLIGATION_STATE",
                 "REVOKE_EXEMPTION is not available from %s." % retailer["obligation_status"])
        proj.clear_retailer_exemption(retailer)

    return response.obj(db.public(retailer))
