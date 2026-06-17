"""Gate scans, gate events, incidents."""
from flask import request
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
import serialize as S
from common import (
    body, pagination, paginate, find, auth,
    as_str, as_enum,
)


def _log_gate_event(fields):
    return insert(db.gate_events, fields, common=False)


def register(app):

    # ===================== Gate scan =====================
    @app.route("/festivals/<fid>/gate-scan", methods=["POST"])
    def gate_scan(fid):
        auth(["GateAttendant"])
        fest = find(db.festivals, fid)
        data = body()
        wristband_id = data.get("wristband_id")
        if wristband_id is None:
            raise err("ERR_INVALID_REQUEST", "wristband_id is required")
        direction = as_enum(data, "direction", ("ENTER", "EXIT"))
        # priority 4: FK resolution of wristband (same festival)
        w = db.wristbands.get(wristband_id)
        if w is None or w["festival_id"] != fid:
            raise err("ERR_FK_NOT_FOUND",
                      "wristband_id does not resolve in this festival")

        if direction == "EXIT":
            # EXIT permitted even while SUSPENDED. Requires presence INSIDE.
            if w["presence_status"] != "INSIDE":
                raise err("ERR_INVALID_STATE",
                          "wristband must be INSIDE to exit")
            w["presence_status"] = "OUTSIDE"
            touch(w)
            ev = _log_gate_event({
                "festival_id": fid,
                "wristband_id": wristband_id,
                "direction": "EXIT",
                "outcome": "EXITED",
                "deny_reason": None,
            })
            return ok_object(S.gate_event(ev), 201)

        # ENTER. Validation order per PRD §3.11:
        #   wristband lifecycle must be ACTIVE
        #   p7 posture must permit (LIVE) -> ERR_FESTIVAL_POSTURE
        #   p8 SUSPENDED -> ERR_FESTIVAL_SUSPENDED
        #   p10 already INSIDE -> ERR_ALREADY_INSIDE
        #   p11 reentry cap -> ERR_REENTRY_LIMIT
        # Lifecycle gate: an ENTER on a non-ACTIVE wristband is rejected.
        if w["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "wristband must be ACTIVE to enter")
        posture = fest["operational_posture"]
        if posture == "SUSPENDED":
            ev = _log_gate_event({
                "festival_id": fid,
                "wristband_id": wristband_id,
                "direction": "ENTER",
                "outcome": "DENIED",
                "deny_reason": "ERR_FESTIVAL_SUSPENDED",
            })
            raise err("ERR_FESTIVAL_SUSPENDED",
                      "gate entry rejected during weather hold")
        if posture != "LIVE":
            ev = _log_gate_event({
                "festival_id": fid,
                "wristband_id": wristband_id,
                "direction": "ENTER",
                "outcome": "DENIED",
                "deny_reason": "ERR_FESTIVAL_POSTURE",
            })
            raise err("ERR_FESTIVAL_POSTURE",
                      "gate entry requires LIVE posture")
        # p10 already inside
        if w["presence_status"] == "INSIDE":
            ev = _log_gate_event({
                "festival_id": fid,
                "wristband_id": wristband_id,
                "direction": "ENTER",
                "outcome": "DENIED",
                "deny_reason": "ERR_ALREADY_INSIDE",
            })
            raise err("ERR_ALREADY_INSIDE", "wristband is already inside")
        # p11 reentry cap: first entry (entry_count == 0) always allowed
        if w["entry_count"] >= 1 and w["reentry_used"] >= fest["max_reentries"]:
            ev = _log_gate_event({
                "festival_id": fid,
                "wristband_id": wristband_id,
                "direction": "ENTER",
                "outcome": "DENIED",
                "deny_reason": "ERR_REENTRY_LIMIT",
            })
            raise err("ERR_REENTRY_LIMIT", "re-entry limit exceeded")

        # admit
        was_inside_before = w["entry_count"] >= 1
        w["presence_status"] = "INSIDE"
        w["entry_count"] += 1
        if was_inside_before:
            w["reentry_used"] += 1
        touch(w)
        ev = _log_gate_event({
            "festival_id": fid,
            "wristband_id": wristband_id,
            "direction": "ENTER",
            "outcome": "ADMITTED",
            "deny_reason": None,
        })
        return ok_object(S.gate_event(ev), 201)

    @app.route("/festivals/<fid>/gate-events", methods=["GET"])
    def list_festival_gate_events(fid):
        auth(["FestivalDirector", "GateAttendant"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [g for g in db.gate_events.values() if g["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.gate_event(r) for r in page], limit, offset, total)

    @app.route("/gate-events", methods=["GET"])
    def list_gate_events():
        auth(["FestivalDirector", "GateAttendant"])
        limit, offset = pagination()
        wid = request.args.get("wristband_id")
        rows = list(db.gate_events.values())
        if wid is not None:
            rows = [g for g in rows if g["wristband_id"] == wid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.gate_event(r) for r in page], limit, offset, total)

    @app.route("/gate-events/<gid>", methods=["GET"])
    def get_gate_event(gid):
        auth(["FestivalDirector", "GateAttendant"])
        return ok_object(S.gate_event(find(db.gate_events, gid)))

    # ===================== Incidents =====================
    @app.route("/festivals/<fid>/incidents", methods=["POST"])
    def create_incident(fid):
        auth(["GateAttendant", "FestivalDirector"])
        find(db.festivals, fid)
        data = body()
        incident_type = as_enum(data, "incident_type", ("LOST_CHILD", "MEDICAL"))
        severity = as_enum(data, "severity",
                           ("LOW", "MEDIUM", "HIGH", "CRITICAL"), required=False)
        if severity is None:
            severity = "LOW"
        linked = data.get("linked_wristband_id")
        if linked is not None:
            w = db.wristbands.get(linked)
            if w is None or w["festival_id"] != fid:
                raise err("ERR_FK_NOT_FOUND",
                          "linked_wristband_id does not resolve in this festival")
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise err("ERR_INVALID_REQUEST", "notes must be a string")
        rec = insert(db.incidents, {
            "festival_id": fid,
            "incident_type": incident_type,
            "linked_wristband_id": linked,
            "severity": severity,
            "status": "OPEN",
            "notes": notes,
        })
        return ok_object(S.incident(rec), 201)

    @app.route("/festivals/<fid>/incidents", methods=["GET"])
    def list_festival_incidents(fid):
        auth(["FestivalDirector", "GateAttendant"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [i for i in db.incidents.values() if i["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.incident(r) for r in page], limit, offset, total)

    @app.route("/incidents/<iid>", methods=["GET"])
    def get_incident(iid):
        auth(["FestivalDirector", "GateAttendant"])
        return ok_object(S.incident(find(db.incidents, iid)))

    @app.route("/incidents", methods=["GET"])
    def list_incidents():
        auth(["FestivalDirector", "GateAttendant"])
        limit, offset = pagination()
        wid = request.args.get("linked_wristband_id")
        rows = list(db.incidents.values())
        if wid is not None:
            rows = [i for i in rows if i["linked_wristband_id"] == wid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.incident(r) for r in page], limit, offset, total)

    @app.route("/incidents/<iid>/escalate", methods=["POST"])
    def escalate_incident(iid):
        auth(["FestivalDirector", "GateAttendant"])
        inc = find(db.incidents, iid)
        if inc["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "escalate requires OPEN")
        if inc["severity"] not in ("HIGH", "CRITICAL"):
            raise err("ERR_INVALID_STATE",
                      "only HIGH/CRITICAL incidents may be escalated")
        inc["status"] = "ESCALATED"
        touch(inc)
        return ok_object(S.incident(inc))

    @app.route("/incidents/<iid>/deescalate", methods=["POST"])
    def deescalate_incident(iid):
        auth(["FestivalDirector"])
        inc = find(db.incidents, iid)
        if inc["status"] != "ESCALATED":
            raise err("ERR_INVALID_STATE", "deescalate requires ESCALATED")
        inc["status"] = "OPEN"
        touch(inc)
        return ok_object(S.incident(inc))

    @app.route("/incidents/<iid>/resolve", methods=["POST"])
    def resolve_incident(iid):
        user_id, role = auth(["FestivalDirector", "GateAttendant"])
        inc = find(db.incidents, iid)
        if inc["status"] not in ("OPEN", "ESCALATED"):
            raise err("ERR_INVALID_STATE", "resolve requires OPEN or ESCALATED")
        # resolving from ESCALATED is restricted to FestivalDirector
        if inc["status"] == "ESCALATED" and role != "FestivalDirector":
            raise err("ERR_FORBIDDEN_ROLE",
                      "only a FestivalDirector may resolve an escalated incident")
        inc["status"] = "RESOLVED"
        touch(inc)
        return ok_object(S.incident(inc))
