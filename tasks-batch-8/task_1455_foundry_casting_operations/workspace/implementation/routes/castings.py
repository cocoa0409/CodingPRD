"""Casting routing advance on parallel routing/quality tracks (PRD 3.6)."""

from flask import request

from db import all_of, get, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object

CASTING_GET_ROLES = {"FoundryAdmin", "LineOperator", "QualityInspector",
                     "WarrantyManager"}

NEXT_ROUTING = {
    "SHAKEOUT": "CLEANING",
    "CLEANING": "GRINDING",
    "GRINDING": "FINAL_INSPECTION",
    "FINAL_INSPECTION": "COMPLETE",
}


def register(app):
    @app.route("/api/castings/<cid>", methods=["GET"])
    def get_casting(cid):
        auth_user, role = auth()
        require_role(role, CASTING_GET_ROLES)
        rec = get("castings", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "casting not found")
        return ok_object(rec, 200)

    @app.route("/api/castings", methods=["GET"])
    def list_castings():
        auth_user, role = auth()
        require_role(role, CASTING_GET_ROLES)
        mold_id = request.args.get("mold_id")
        order_id = request.args.get("order_id")
        routing = request.args.get("routing_status")
        quality = request.args.get("quality_status")
        recs = list(all_of("castings"))
        if mold_id is not None:
            recs = [c for c in recs if c["mold_id"] == mold_id]
        if order_id is not None:
            recs = [c for c in recs if c["order_id"] == order_id]
        if routing is not None:
            recs = [c for c in recs if c["routing_status"] == routing]
        if quality is not None:
            recs = [c for c in recs if c["quality_status"] == quality]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/castings/<cid>/advance", methods=["POST"])
    def advance_casting(cid):
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        rec = get("castings", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "casting not found")
        if rec["routing_status"] == "COMPLETE":
            fail("ERR_ALREADY_TERMINAL", "casting routing is terminal")
        nxt = NEXT_ROUTING[rec["routing_status"]]
        # every step requires quality not SCRAPPED
        if rec["quality_status"] == "SCRAPPED":
            fail("ERR_INVALID_STATE", "casting quality is SCRAPPED")
        if rec["routing_status"] == "SHAKEOUT":
            mold = get("molds", rec["mold_id"])
            if mold is None or mold["status"] not in ("SHAKEOUT", "CLOSED"):
                fail("ERR_INVALID_STATE",
                     "mold must be SHAKEOUT or CLOSED to leave SHAKEOUT")
        if nxt == "COMPLETE" and rec["quality_status"] not in ("ACCEPTED", "USE_AS_IS"):
            fail("ERR_INVALID_STATE",
                 "only ACCEPTED or USE_AS_IS castings can complete routing")
        rec["routing_status"] = nxt
        touch(rec)
        return ok_object(rec, 200)
