"""Routes: lifeguards and lifeguard shifts."""
from datetime import timedelta

import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_already_checked_in, err_forbidden,
                    err_guard_not_certified, err_invalid_request,
                    err_invalid_state, err_not_found, err_shift_window)
from util import req_str

AM = ["AquaticsManager"]


def _get_guard_or_404(gid):
    g = store.lifeguards.get(gid)
    if not g:
        raise err_not_found("Lifeguard not found")
    return g


def register(app):
    # -------------------------------------------------------------- lifeguards
    @app.route("/lifeguards", methods=["POST"])
    def create_lifeguard():
        authenticate(AM)
        body = get_body()
        full_name = req_str(body, "full_name")
        certification_id = req_str(body, "certification_id")
        cert_exp = store.date_or_datetime_to_date(body.get("cert_expires_on"))
        if cert_exp is None:
            raise err_invalid_request("Field 'cert_expires_on' must be an ISO date")
        hired = store.date_or_datetime_to_date(body.get("hired_on"))
        if hired is None:
            raise err_invalid_request("Field 'hired_on' must be an ISO date")
        # cert status is derived from cert_expires_on vs the logical clock:
        # EXPIRED once the clock has passed the end of the expiry day
        expires_dt = store.day_start(cert_exp) + timedelta(days=1)
        status = "EXPIRED" if store.now() > expires_dt else "ACTIVE"
        g = store.base_fields()
        g.update({
            "full_name": full_name,
            "certification_id": certification_id,
            "cert_expires_on": store.iso_date(cert_exp),
            "cert_status": status,
            "hired_on": store.iso_date(hired),
            "_cert_expires_on": expires_dt,
            "_seq": store.next_seq(),
        })
        store.lifeguards[g["id"]] = g
        return success(serialize(g), 201)

    @app.route("/lifeguards/<gid>", methods=["GET"])
    def get_lifeguard(gid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        return success(serialize(_get_guard_or_404(gid)), 200)

    @app.route("/lifeguards", methods=["GET"])
    def list_lifeguards():
        authenticate(["AquaticsManager", "GateAttendant"])
        from flask import request
        items = list(store.lifeguards.values())
        status = request.args.get("cert_status")
        if status is not None:
            items = [g for g in items if g["cert_status"] == status]
        return list_response([serialize(g) for g in sort_created(items)])

    @app.route("/lifeguards/<gid>/shifts", methods=["GET"])
    def list_guard_shifts(gid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        _get_guard_or_404(gid)
        items = [s for s in store.shifts.values() if s["lifeguard_id"] == gid]
        return list_response([serialize(s) for s in sort_created(items)])

    @app.route("/lifeguards/<gid>/suspend", methods=["POST"])
    def suspend_lifeguard(gid):
        authenticate(AM)
        g = _get_guard_or_404(gid)
        body = get_body()
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason:
            raise err_invalid_request("Field 'reason' is required")
        if g["cert_status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE lifeguard can be suspended")
        g["cert_status"] = "SUSPENDED"
        store.touch(g)
        affected = domain.cancel_future_shifts_for_guard(g, store.now())
        for fid in affected:
            fac = store.facilities.get(fid)
            if fac:
                domain.evaluate_staffing_closure(fac)
        return success(serialize(g), 200)

    @app.route("/lifeguards/<gid>/reinstate", methods=["POST"])
    def reinstate_lifeguard(gid):
        authenticate(AM)
        g = _get_guard_or_404(gid)
        if g["cert_status"] != "SUSPENDED":
            raise err_invalid_state("Only a SUSPENDED lifeguard can be reinstated")
        if store.now() >= g["_cert_expires_on"]:
            raise err_invalid_state("Certification has expired; cannot reinstate")
        g["cert_status"] = "ACTIVE"
        store.touch(g)
        return success(serialize(g), 200)

    @app.route("/lifeguards/<gid>/chemistry-logs", methods=["GET"])
    def list_guard_chemistry_logs(gid):
        authenticate(["AquaticsManager", "GateAttendant"])
        _get_guard_or_404(gid)
        items = [c for c in store.chemistry_logs.values()
                 if c["recorded_by_lifeguard_id"] == gid]
        return list_response([serialize(c) for c in sort_created(items)])

    @app.route("/lifeguards/<gid>/incident-reports", methods=["GET"])
    def list_guard_incidents(gid):
        authenticate(["AquaticsManager", "GateAttendant"])
        _get_guard_or_404(gid)
        items = [r for r in store.incident_reports.values()
                 if r["reporting_lifeguard_id"] == gid]
        return list_response([serialize(r) for r in sort_created(items)])

    # ------------------------------------------------------------------ shifts
    @app.route("/shifts", methods=["POST"])
    def create_shift():
        authenticate(AM)
        body = get_body()
        fid = body.get("facility_id")
        gid = body.get("lifeguard_id")
        # priority 5: FKs
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        if isinstance(gid, str) and gid not in store.lifeguards:
            raise err_not_found("lifeguard_id does not resolve")
        start = store.parse_datetime(body.get("shift_start"))
        end = store.parse_datetime(body.get("shift_end"))
        # priority 15: window well-formed and within [now-1h, now+60d]
        now = store.now()
        if start is not None and end is not None:
            if start >= end or start < now - timedelta(hours=1) or end > now + timedelta(days=60):
                raise err_shift_window()
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if not isinstance(gid, str) or not gid:
            raise err_invalid_request("Field 'lifeguard_id' is required")
        if start is None:
            raise err_invalid_request("Field 'shift_start' must be an ISO 8601 timestamp")
        if end is None:
            raise err_invalid_request("Field 'shift_end' must be an ISO 8601 timestamp")
        s = store.base_fields()
        s.update({
            "facility_id": fid,
            "lifeguard_id": gid,
            "shift_start": store.iso(start),
            "shift_end": store.iso(end),
            "status": "SCHEDULED",
            "_shift_start": start,
            "_shift_end": end,
            "_seq": store.next_seq(),
        })
        store.shifts[s["id"]] = s
        return success(serialize(s), 201)

    @app.route("/shifts/<sid>", methods=["GET"])
    def get_shift(sid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        s = store.shifts.get(sid)
        if not s:
            raise err_not_found("LifeguardShift not found")
        return success(serialize(s), 200)

    @app.route("/shifts", methods=["GET"])
    def list_shifts():
        authenticate(["AquaticsManager", "GateAttendant"])
        from flask import request
        items = list(store.shifts.values())
        for param, field in (("facility_id", "facility_id"),
                             ("lifeguard_id", "lifeguard_id"), ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [s for s in items if s[field] == v]
        return list_response([serialize(s) for s in sort_created(items)])

    @app.route("/shifts/<sid>/check-in", methods=["POST"])
    def check_in_shift(sid):
        role, uid = authenticate(["Lifeguard"])
        s = store.shifts.get(sid)
        if not s:
            raise err_not_found("LifeguardShift not found")
        # instance identity: the assigned lifeguard checks in personally
        if s["lifeguard_id"] != uid:
            raise err_forbidden("X-User-ID must equal the shift's lifeguard_id")
        # priority 6: state
        if s["status"] == "COVERED":
            raise err_already_checked_in("Shift is already checked in")
        if s["status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED shift can be checked in")
        # priority 10: cert must be ACTIVE at check-in
        guard = store.lifeguards.get(s["lifeguard_id"])
        if not guard or guard["cert_status"] != "ACTIVE":
            raise err_guard_not_certified()
        # grace: no more than 15 minutes past shift_start
        if store.now() > s["_shift_start"] + timedelta(minutes=15):
            raise err_invalid_state("Check-in grace period (15 minutes) has passed")
        s["status"] = "COVERED"
        store.touch(s)
        return success(serialize(s), 200)

    @app.route("/shifts/<sid>/cancel", methods=["POST"])
    def cancel_shift(sid):
        authenticate(AM)
        s = store.shifts.get(sid)
        if not s:
            raise err_not_found("LifeguardShift not found")
        if s["status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED shift can be cancelled")
        s["status"] = "CANCELLED"
        store.touch(s)
        fac = store.facilities.get(s["facility_id"])
        if fac:
            domain.evaluate_staffing_closure(fac)
        return success(serialize(s), 200)
