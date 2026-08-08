"""Holder audit cases and penalties."""
from flask import request, g

from store import STORE, new_id
from common import (
    ApiError, ok, ok_list, require_roles, get_json, require_str, require_int,
    stamp_new, touch, serialize, serialize_list, paginate,
)
import lookups

NON_TERMINAL_AUDIT = {"OPEN", "INFO_REQUESTED"}


def recompute_audit_hold(holder):
    active = any(a["holder_id"] == holder["id"] and a["status"] in NON_TERMINAL_AUDIT
                 for a in STORE.audit_cases.values())
    if holder.get("audit_hold") != active:
        holder["audit_hold"] = active
        touch(holder)
    else:
        holder["audit_hold"] = active


def register(app):
    @app.post("/audit-cases")
    @require_roles("StateExaminer")
    def open_audit_case():
        body = get_json()
        holder_id = require_str(body, "holder_id")
        holder = lookups.holder(holder_id)
        ent = {
            "id": new_id(),
            "holder_id": holder_id,
            "examiner_user_id": g.user_id,
            "assessed_penalty_cents": 0,
            "findings": None,
            "status": "OPEN",
        }
        stamp_new(ent)
        STORE.audit_cases[ent["id"]] = ent
        holder["audit_hold"] = True
        touch(holder)
        return ok(serialize(ent), 201)

    @app.get("/audit-cases/<aid>")
    @require_roles("StateAdmin", "StateExaminer", "Holder")
    def get_audit_case(aid):
        return ok(serialize(lookups.audit_case(aid)))

    @app.get("/audit-cases")
    @require_roles("StateAdmin", "StateExaminer", "Holder")
    def list_audit_cases():
        items = list(STORE.audit_cases.values())
        for key in ("holder_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [a for a in items if a.get(key) == val]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(a) for a in page], limit, offset, total)

    @app.post("/audit-cases/<aid>/request-info")
    @require_roles("StateExaminer")
    def request_info(aid):
        case = lookups.audit_case(aid)
        if case["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Audit case is not OPEN.")
        case["status"] = "INFO_REQUESTED"
        touch(case)
        return ok(serialize(case))

    @app.post("/audit-cases/<aid>/provide-info")
    @require_roles("Holder")
    def provide_info(aid):
        case = lookups.audit_case(aid)
        if case["status"] != "INFO_REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Audit case is not INFO_REQUESTED.")
        case["status"] = "OPEN"
        touch(case)
        return ok(serialize(case))

    @app.post("/audit-cases/<aid>/close-clean")
    @require_roles("StateExaminer")
    def close_clean(aid):
        case = lookups.audit_case(aid)
        if case["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Audit case is not OPEN.")
        case["status"] = "CLOSED_NO_FINDING"
        touch(case)
        holder = STORE.holders.get(case["holder_id"])
        if holder:
            recompute_audit_hold(holder)
        return ok(serialize(case))

    @app.post("/audit-cases/<aid>/close-assess")
    @require_roles("StateExaminer")
    def close_assess(aid):
        case = lookups.audit_case(aid)
        if case["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Audit case is not OPEN.")
        body = get_json()
        assessed_penalty_cents = require_int(body, "assessed_penalty_cents", min_val=1)
        findings = require_str(body, "findings")
        case["status"] = "CLOSED_ASSESSED"
        case["assessed_penalty_cents"] = assessed_penalty_cents
        case["findings"] = findings
        touch(case)
        holder = STORE.holders.get(case["holder_id"])
        if holder:
            holder["assessed_penalty_cents"] = holder.get("assessed_penalty_cents", 0) + assessed_penalty_cents
            holder["status"] = "SUSPENDED"
            touch(holder)
            recompute_audit_hold(holder)
        return ok(serialize(case))
