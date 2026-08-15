"""Equipment registration and furnace maintenance windows (PRD 3.1)."""

from flask import request

from db import all_of, get, new_record, logical_now, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from util import as_enum, as_nonneg_num, as_pos_int, as_str, body_dict, opt, parse_dt, req

EQUIPMENT_GET_ROLES = {"FoundryAdmin", "MeltSupervisor", "LineOperator"}


def register(app):
    @app.route("/api/equipment", methods=["POST"])
    def create_equipment():
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        kind = as_enum(req(body, "kind"), "kind", {"FURNACE", "MOLDING_LINE"})
        label = as_str(req(body, "label"), "label")
        tap_cap = opt(body, "daily_tap_capacity_kg")
        if tap_cap is not None:
            tap_cap = as_nonneg_num(tap_cap, "daily_tap_capacity_kg")
        minute_cap = opt(body, "daily_minute_capacity")
        if minute_cap is not None:
            minute_cap = as_pos_int(minute_cap, "daily_minute_capacity")
        buffer_min = opt(body, "cleanup_buffer_minutes")
        if buffer_min is not None:
            if not isinstance(buffer_min, int) or isinstance(buffer_min, bool) or buffer_min < 0:
                fail("ERR_INVALID_REQUEST", "cleanup_buffer_minutes must be a non-negative integer")
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        rec = new_record("equipment", {
            "foundry_id": foundry_id,
            "kind": kind,
            "label": label,
            "daily_tap_capacity_kg": tap_cap,
            "daily_minute_capacity": minute_cap,
            "cleanup_buffer_minutes": buffer_min,
            "maintenance_windows": [],
        })
        return ok_object(rec, 201)

    @app.route("/api/equipment/<eid>", methods=["GET"])
    def get_equipment(eid):
        auth_user, role = auth()
        require_role(role, EQUIPMENT_GET_ROLES)
        rec = get("equipment", eid)
        if rec is None:
            fail("ERR_NOT_FOUND", "equipment not found")
        return ok_object(rec, 200)

    @app.route("/api/equipment", methods=["GET"])
    def list_equipment():
        auth_user, role = auth()
        require_role(role, EQUIPMENT_GET_ROLES)
        foundry_id = request.args.get("foundry_id")
        kind = request.args.get("kind")
        recs = list(all_of("equipment"))
        if foundry_id is not None:
            recs = [e for e in recs if e["foundry_id"] == foundry_id]
        if kind is not None:
            recs = [e for e in recs if e["kind"] == kind]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/equipment/<eid>/windows", methods=["POST"])
    def add_window(eid):
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        rec = get("equipment", eid)
        if rec is None:
            fail("ERR_NOT_FOUND", "equipment not found")
        body = body_dict(request.get_json(silent=True))
        start_raw = req(body, "start_iso")
        end_raw = req(body, "end_iso")
        # equipment-kind matching (priority 7)
        if rec["kind"] != "FURNACE":
            fail("ERR_INVALID_REQUEST", "maintenance windows apply to FURNACE equipment only")
        start = parse_dt(start_raw, "start_iso")
        end = parse_dt(end_raw, "end_iso")
        if end <= start:
            fail("ERR_INVALID_REQUEST", "window end must be after its start")
        # closed-interval overlap: touching endpoints conflict (PRD 3.1)
        for w in rec["maintenance_windows"]:
            if start <= w["_end_dt"] and w["_start_dt"] <= end:
                fail("ERR_FURNACE_WINDOW_CONFLICT",
                     "maintenance window overlaps an existing window")
        # window whose end lies before the logical now (priority 8)
        if end < logical_now():
            fail("ERR_SLOT_IN_PAST", "maintenance window lies in the past")
        rec["maintenance_windows"].append({
            "start_iso": start_raw,
            "end_iso": end_raw,
            "_start_dt": start,
            "_end_dt": end,
        })
        touch(rec)
        return ok_object(rec, 201)
