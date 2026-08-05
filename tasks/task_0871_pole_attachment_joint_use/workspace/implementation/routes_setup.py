"""Routes: pole owners, crews, poles, attachers, and the logical clock."""

from flask import request

import constants as C
from clock import LOGICAL_CLOCK
from store import DB, touch
from errors import ApiError
from response import object_response, array_response
import serializers as S
import common as X

READ_ALL = ["JointUseCoordinator", "Engineer", "PermitOfficer", "FieldAuditor", "Attacher"]


def _page(records, serializer):
    limit, offset = X.paginate()
    ordered = X.apply_pagination(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)


def register(app):

    # --- logical clock -------------------------------------------------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        _, dt = X.req_datetime(body, "to_iso8601")
        LOGICAL_CLOCK.set(dt)
        now = LOGICAL_CLOCK.now()
        # Scheduled sweeps.
        for inv in DB.invoices.values():
            if inv["status"] == "ISSUED" and inv["due_at"] is not None and now > inv["due_at"]:
                inv["status"] = "OVERDUE"
                touch(inv)
        for appn in DB.applications.values():
            if (appn["status"] == "ESTIMATE_ISSUED"
                    and appn["estimate_expires_at"] is not None
                    and now > appn["estimate_expires_at"]):
                appn["status"] = "ESTIMATE_EXPIRED"
                touch(appn)
        return object_response({}, 200)

    # --- pole owners ---------------------------------------------------------
    @app.route("/joint-use/pole-owners", methods=["POST"])
    def create_pole_owner():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        rec = DB.new_record({
            "legal_name": X.req_str(body, "legal_name"),
            "owner_category": X.req_enum(body, "owner_category", C.OWNER_CATEGORIES),
            "annual_rental_rate_cents": X.req_int(body, "annual_rental_rate_cents"),
            "make_ready_labor_rate_cents_per_hour": X.req_int(body, "make_ready_labor_rate_cents_per_hour"),
        })
        DB.pole_owners[rec["id"]] = rec
        return object_response(S.pole_owner_json(rec), 201)

    @app.route("/joint-use/pole-owners/<owner_id>", methods=["GET"])
    def get_pole_owner(owner_id):
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        rec = X.get_pole_owner(owner_id)
        return object_response(S.pole_owner_json(rec), 200)

    # --- crews ---------------------------------------------------------------
    @app.route("/joint-use/crews", methods=["POST"])
    def create_crew():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        owner = X.get_pole_owner(X.req_str(body, "pole_owner_id"))
        rec = DB.new_record({
            "pole_owner_id": owner["id"],
            "crew_name": X.req_str(body, "crew_name"),
            "region": X.req_str(body, "region"),
        })
        DB.crews[rec["id"]] = rec
        return object_response(S.crew_json(rec), 201)

    @app.route("/joint-use/crews", methods=["GET"])
    def list_crews():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator", "Engineer"])
        owner_id = request.args.get("pole_owner_id")
        recs = [c for c in DB.crews.values()
                if owner_id is None or c["pole_owner_id"] == owner_id]
        return _page(recs, S.crew_json)

    @app.route("/joint-use/crews/<crew_id>", methods=["GET"])
    def get_crew(crew_id):
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator", "Engineer"])
        rec = X.get_crew(crew_id)
        return object_response(S.crew_json(rec), 200)

    # --- poles ---------------------------------------------------------------
    @app.route("/joint-use/poles", methods=["POST"])
    def create_pole():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        owner = X.get_pole_owner(X.req_str(body, "pole_owner_id"))
        tag = X.req_str(body, "tag")
        height_ft = X.req_int(body, "height_ft")
        usable = X.req_int(body, "usable_communication_space_inches")
        for p in DB.poles.values():
            if p["pole_owner_id"] == owner["id"] and p["tag"] == tag:
                raise ApiError("ERR_DUPLICATE_POLE_TAG", "Pole tag already used for this owner.")
        rec = DB.new_record({
            "pole_owner_id": owner["id"],
            "tag": tag,
            "height_ft": height_ft,
            "usable_communication_space_inches": usable,
            "occupied_space_inches": 0,
            "reserved_space_inches": 0,
            "status": "ACTIVE",
        })
        DB.poles[rec["id"]] = rec
        return object_response(S.pole_json(rec), 201)

    @app.route("/joint-use/poles", methods=["GET"])
    def list_poles():
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        owner_id = request.args.get("pole_owner_id")
        recs = [p for p in DB.poles.values()
                if owner_id is None or p["pole_owner_id"] == owner_id]
        return _page(recs, S.pole_json)

    @app.route("/joint-use/poles/<pole_id>", methods=["GET"])
    def get_pole(pole_id):
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        rec = X.get_pole(pole_id)
        return object_response(S.pole_json(rec), 200)

    @app.route("/joint-use/poles/<pole_id>/retire", methods=["POST"])
    def retire_pole(pole_id):
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        pole = X.get_pole(pole_id)
        if pole["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Pole is not ACTIVE.")
        if pole["occupied_space_inches"] != 0 or pole["reserved_space_inches"] != 0:
            raise ApiError("ERR_POLE_HAS_ATTACHMENTS", "Pole still has attachments or reservations.")
        for appn in DB.applications.values():
            if (appn["pole_id"] == pole["id"]
                    and appn["status"] in ("SUBMITTED", "SURVEYED", "ESTIMATE_ISSUED", "ESTIMATE_ACCEPTED")):
                raise ApiError("ERR_POLE_HAS_ATTACHMENTS", "Pole has a non-terminal application.")
        pole["status"] = "RETIRED"
        touch(pole)
        return object_response(S.pole_json(pole), 200)

    # --- attachers -----------------------------------------------------------
    @app.route("/joint-use/attachers", methods=["POST"])
    def create_attacher():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        company_name = X.req_str(body, "company_name")
        cin = X.req_str(body, "cin")
        contact_email = X.req_str(body, "contact_email")
        credit_limit = X.opt_int(body, "credit_limit_cents", C.DEFAULT_CREDIT_LIMIT_CENTS)
        for a in DB.attachers.values():
            if a["cin"] == cin:
                raise ApiError("ERR_DUPLICATE_CIN", "cin already registered.")
        rec = DB.new_record({
            "company_name": company_name,
            "cin": cin,
            "contact_email": contact_email,
            "credit_limit_cents": credit_limit,
            "account_balance_cents": 0,
        })
        DB.attachers[rec["id"]] = rec
        return object_response(S.attacher_json(rec), 201)

    @app.route("/joint-use/attachers/<attacher_id>", methods=["GET"])
    def get_attacher(attacher_id):
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        rec = X.get_attacher(attacher_id)
        return object_response(S.attacher_json(rec), 200)
