"""Property lifecycle and due-diligence notices."""
from datetime import timedelta
from flask import request

from store import STORE, new_id, parse_iso, iso
from common import (
    ApiError, ok, ok_list, require_roles, get_json, require_str, require_int,
    require_enum, stamp_new, touch, serialize, serialize_list, paginate,
)
import lookups
import calc

BUFFER_DAYS = 30
METHODS = {"MAIL", "EMAIL"}


def register(app):
    # ---------------- Create property ----------------
    @app.post("/properties")
    @require_roles("Holder")
    def create_property():
        body = get_json()
        holder_id = require_str(body, "holder_id")
        property_type_id = require_str(body, "property_type_id")
        owner_name = require_str(body, "owner_name")
        amount_cents = require_int(body, "amount_cents", min_val=0)
        last_activity_raw = require_str(body, "last_activity_date")
        # Existence (left to right): holder then property type
        holder = lookups.holder(holder_id)
        ptype = lookups.property_type(property_type_id)

        last_activity_dt = parse_iso(last_activity_raw)
        if last_activity_dt is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "last_activity_date must be a valid ISO 8601 instant.")

        owner_last_known_state = body.get("owner_last_known_state")
        if owner_last_known_state is not None and not isinstance(owner_last_known_state, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "owner_last_known_state must be a string.")

        issue_raw = body.get("issue_date")
        issue_dt = None
        if issue_raw is not None:
            if not isinstance(issue_raw, str):
                raise ApiError("ERR_INVALID_REQUEST", 400, "issue_date must be a string.")
            issue_dt = parse_iso(issue_raw)
            if issue_dt is None:
                raise ApiError("ERR_INVALID_REQUEST", 400, "issue_date must be a valid ISO 8601 instant.")

        # escheat_state priority rule
        if owner_last_known_state:
            escheat_state = owner_last_known_state
        else:
            escheat_state = holder["incorporation_state"]

        # dormancy_date
        try:
            dormancy_dt = calc.compute_dormancy_date(ptype, last_activity_dt, issue_dt)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "issue_date is required for an ISSUANCE-basis property type.")

        ent = {
            "id": new_id(),
            "holder_id": holder_id,
            "property_type_id": property_type_id,
            "owner_name": owner_name,
            "owner_last_known_state": owner_last_known_state,
            "amount_cents": amount_cents,
            "last_activity_date": last_activity_raw,
            "issue_date": issue_raw,
            "escheat_state": escheat_state,
            "dormancy_date": iso(dormancy_dt),
            "remitted_amount_cents": 0,
            "report_id": None,
            "status": "ACTIVE",
        }
        stamp_new(ent)
        STORE.properties[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/properties/<pid>")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover", "Owner", "RecoveryAgent")
    def get_property(pid):
        return ok(serialize(lookups.prop(pid)))

    @app.get("/properties")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover")
    def list_properties():
        items = list(STORE.properties.values())
        for key in ("holder_id", "property_type_id", "report_id", "status", "escheat_state"):
            val = request.args.get(key)
            if val is not None:
                items = [p for p in items if p.get(key) == val]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(p) for p in page], limit, offset, total)

    # ---------------- Evaluate dormancy ----------------
    @app.post("/properties/<pid>/evaluate-dormancy")
    @require_roles("Holder")
    def evaluate_dormancy(pid):
        prop = lookups.prop(pid)
        if prop["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Property is not ACTIVE.")
        now = STORE.now()
        dormancy_dt = parse_iso(prop["dormancy_date"])
        if now < dormancy_dt:
            raise ApiError("ERR_NOT_YET_DORMANT", 409, "Property has not yet reached its dormancy date.")
        prop["status"] = "DORMANT"
        touch(prop)
        return ok(serialize(prop))

    # ---------------- Send notice ----------------
    @app.post("/properties/<pid>/notices")
    @require_roles("Holder")
    def send_notice(pid):
        prop = lookups.prop(pid)
        body = get_json()
        method = require_enum(body, "method", METHODS)
        if prop["status"] not in ("DORMANT", "DUE_DILIGENCE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Property is not eligible for a notice.")
        ptype = STORE.property_types.get(prop["property_type_id"])
        if not ptype or not ptype["due_diligence_required"]:
            raise ApiError("ERR_INVALID_STATE", 409, "Property type does not require due diligence.")
        now = STORE.now()
        for n in STORE.notices.values():
            if n["property_id"] == pid:
                sent = parse_iso(n["sent_at"])
                if (now - sent) < timedelta(days=BUFFER_DAYS):
                    raise ApiError("ERR_NOTICE_TOO_SOON", 409,
                                   "A prior notice was sent within the buffer window.")
        notice = {
            "id": new_id(),
            "property_id": pid,
            "method": method,
            "sent_at": iso(now),
            "responded": False,
            "responded_at": None,
        }
        stamp_new(notice)
        STORE.notices[notice["id"]] = notice
        if prop["status"] == "DORMANT":
            prop["status"] = "DUE_DILIGENCE"
            touch(prop)
        return ok(serialize(notice), 201)

    @app.get("/properties/<pid>/notices")
    @require_roles("StateAdmin", "Holder", "StateExaminer")
    def list_notices(pid):
        lookups.prop(pid)
        items = [n for n in STORE.notices.values() if n["property_id"] == pid]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(n) for n in page], limit, offset, total)

    # ---------------- Record response ----------------
    @app.post("/due-diligence-notices/<nid>/record-response")
    @require_roles("Holder")
    def record_response(nid):
        notice = lookups.notice(nid)
        prop = STORE.properties.get(notice["property_id"])
        if prop is None or prop["status"] != "DUE_DILIGENCE":
            raise ApiError("ERR_INVALID_STATE", 409, "Property is not in DUE_DILIGENCE.")
        now = STORE.now()
        notice["responded"] = True
        notice["responded_at"] = iso(now)
        touch(notice)
        prop["status"] = "ACTIVE"
        touch(prop)
        return ok(serialize(notice))
