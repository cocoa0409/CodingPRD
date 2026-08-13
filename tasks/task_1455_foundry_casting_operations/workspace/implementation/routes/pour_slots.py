"""Pour-slot booking, cancellation, completion (PRD 3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import request

from db import all_of, get, logical_now, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import (create_castings_for_mold, foundry_id_of_mold,
                      foundry_id_of_slot, q2)
from util import as_str, body_dict, parse_dt, req

SLOT_GET_ROLES = {"FoundryAdmin", "MeltSupervisor", "LineOperator"}


def _get_slot_or_404(sid):
    slot = get("pour_slots", sid)
    if slot is None:
        fail("ERR_NOT_FOUND", "pour slot not found")
    return slot


def register(app):
    @app.route("/api/pour-slots", methods=["POST"])
    def create_slot():
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        body = body_dict(request.get_json(silent=True))
        line_id = as_str(req(body, "molding_line_id"), "molding_line_id")
        heat_id = as_str(req(body, "heat_id"), "heat_id")
        mold_ids = req(body, "mold_ids")
        if (not isinstance(mold_ids, list) or len(mold_ids) == 0
                or any(not isinstance(m, str) for m in mold_ids)):
            fail("ERR_INVALID_REQUEST", "mold_ids must be a non-empty array of ids")
        start_raw = req(body, "start_at")
        end_raw = req(body, "end_at")

        # existence + cross-foundry resolution (priority 3)
        line = get("equipment", line_id)
        if line is None:
            fail("ERR_NOT_FOUND", "molding line not found")
        foundry_id = line["foundry_id"]
        heat = get("heats", heat_id)
        if heat is None or heat["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "heat not found")
        molds = []
        for mid in mold_ids:
            m = get("molds", mid)
            if m is None or foundry_id_of_mold(m) != foundry_id:
                fail("ERR_NOT_FOUND", "mold not found")
            molds.append(m)

        # state feasibility (priority 4): every mold ASSEMBLED at booking
        for m in molds:
            if m["status"] != "ASSEMBLED":
                fail("ERR_INVALID_STATE", "every mold must be ASSEMBLED at booking")

        # structural (priority 7): kind matching, interval sanity, overlap
        if line["kind"] != "MOLDING_LINE":
            fail("ERR_INVALID_REQUEST", "molding_line_id must reference MOLDING_LINE equipment")
        start = parse_dt(start_raw, "start_at")
        end = parse_dt(end_raw, "end_at")
        if end <= start:
            fail("ERR_INVALID_REQUEST", "end_at must be after start_at")
        buffer = timedelta(minutes=line["cleanup_buffer_minutes"] or 0)
        for s in all_of("pour_slots"):
            if s["molding_line_id"] != line["id"] or s["status"] not in ("BOOKED", "COMPLETED"):
                continue
            # half-open [start, end) + cleanup buffer; equality at buffer boundary allowed
            if not (start >= s["_end_dt"] + buffer or end + buffer <= s["_start_dt"]):
                fail("ERR_SLOT_WINDOW_CONFLICT", "slot conflicts with an existing slot")

        # temporal (priority 8): no slot starting in the past
        now = logical_now()
        if start < now:
            fail("ERR_SLOT_IN_PAST", "slot start_at lies in the past")

        # fiscal (priority 9): line daily minutes, whole-minute durations
        if line["daily_minute_capacity"] is not None:
            day = start.strftime("%Y-%m-%d")
            used_seconds = 0
            for s in all_of("pour_slots"):
                if (s["molding_line_id"] == line["id"]
                        and s["status"] in ("BOOKED", "COMPLETED")
                        and s["_start_dt"].strftime("%Y-%m-%d") == day):
                    used_seconds += int((s["_end_dt"] - s["_start_dt"]).total_seconds())
            new_seconds = int((end - start).total_seconds())
            if used_seconds + new_seconds > line["daily_minute_capacity"] * 60:
                fail("ERR_LINE_MINUTES_EXCEEDED", "line daily minute capacity exceeded")

        # posture gate (priority 10): evaluated after per-resource checks
        foundry = get("foundries", foundry_id)
        if foundry["posture"] == "EMBARGO":
            fail("ERR_FOUNDRY_EMBARGO", "foundry is in EMBARGO posture")
        if foundry["posture"] == "CURTAILED":
            fail("ERR_FOUNDRY_CURTAILED", "foundry is in CURTAILED posture")

        rec = new_record("pour_slots", {
            "molding_line_id": line_id,
            "heat_id": heat_id,
            "mold_ids": list(mold_ids),
            "start_at": start_raw,
            "end_at": end_raw,
            "status": "BOOKED",
            "_start_dt": start,
            "_end_dt": end,
        })
        for m in molds:
            m["pour_slot_id"] = rec["id"]
            touch(m)
        return ok_object(rec, 201)

    @app.route("/api/pour-slots/<sid>", methods=["GET"])
    def get_slot(sid):
        auth_user, role = auth()
        require_role(role, SLOT_GET_ROLES)
        return ok_object(_get_slot_or_404(sid), 200)

    @app.route("/api/pour-slots", methods=["GET"])
    def list_slots():
        auth_user, role = auth()
        require_role(role, SLOT_GET_ROLES)
        line_id = request.args.get("molding_line_id")
        heat_id = request.args.get("heat_id")
        status = request.args.get("status")
        recs = list(all_of("pour_slots"))
        if line_id is not None:
            recs = [s for s in recs if s["molding_line_id"] == line_id]
        if heat_id is not None:
            recs = [s for s in recs if s["heat_id"] == heat_id]
        if status is not None:
            recs = [s for s in recs if s["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/pour-slots/<sid>/cancel", methods=["POST"])
    def cancel_slot(sid):
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        slot = _get_slot_or_404(sid)
        if slot["status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "pour slot is in a terminal state")
        slot["status"] = "CANCELLED"
        touch(slot)
        for mid in slot["mold_ids"]:
            m = get("molds", mid)
            if m and m["pour_slot_id"] == slot["id"]:
                m["pour_slot_id"] = None
                touch(m)
        return ok_object(slot, 200)

    @app.route("/api/pour-slots/<sid>/complete", methods=["POST"])
    def complete_slot(sid):
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        slot = _get_slot_or_404(sid)
        if slot["status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "pour slot is in a terminal state")
        # state feasibility: every mold still ASSEMBLED
        molds = []
        for mid in slot["mold_ids"]:
            m = get("molds", mid)
            if m is None:
                fail("ERR_INVALID_STATE", "slot references a missing mold")
            molds.append(m)
        for m in molds:
            if m["status"] != "ASSEMBLED":
                fail("ERR_INVALID_STATE", "every mold must still be ASSEMBLED")
        # safety gates (priority 5): heat TAPPED, sand batches IN_SERVICE
        heat = get("heats", slot["heat_id"])
        if heat is None or heat["status"] != "TAPPED":
            fail("ERR_HEAT_NOT_TAPPED", "heat is not TAPPED")
        for m in molds:
            batch = get("sand_batches", m["sand_batch_id"])
            if batch is None or batch["status"] != "IN_SERVICE":
                fail("ERR_SAND_BATCH_INACTIVE", "a mold's sand batch is not IN_SERVICE")
        # temporal (priority 8): completion inside the half-open window
        now = logical_now()
        if not (slot["_start_dt"] <= now < slot["_end_dt"]):
            fail("ERR_SLOT_NOT_IN_WINDOW", "logical now is outside the slot window")
        # fiscal (priority 9): remaining metal must cover the molds
        needed = Decimal("0")
        for m in molds:
            needed += m["metal_weight_kg"]
        if heat["remaining_metal_kg"] < needed:
            fail("ERR_METAL_INSUFFICIENT", "heat remaining metal is insufficient")

        slot["status"] = "COMPLETED"
        touch(slot)
        heat["remaining_metal_kg"] = q2(heat["remaining_metal_kg"] - needed)
        touch(heat)
        for m in molds:
            m["status"] = "POURED"
            m["poured_at"] = now
            touch(m)
            pattern = get("patterns", m["pattern_id"])
            create_castings_for_mold(m, pattern)
        return ok_object(slot, 200)
