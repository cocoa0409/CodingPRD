"""Routes: incident reports and individual closure resolution."""
import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_forbidden, err_guard_not_certified, err_invalid_request,
                    err_invalid_state, err_not_found, err_reopen_criteria)
from util import req_enum, req_str

AM = ["AquaticsManager"]


def register(app):
    # ---------------------------------------------------------- incident reports
    @app.route("/incident-reports", methods=["POST"])
    def create_incident():
        authenticate(["Lifeguard", "AquaticsManager"])
        body = get_body()
        fid = body.get("facility_id")
        gid = body.get("reporting_lifeguard_id")
        hid = body.get("involved_pass_holder_id")
        # priority 5: FKs
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        if isinstance(gid, str) and gid not in store.lifeguards:
            raise err_not_found("reporting_lifeguard_id does not resolve")
        if isinstance(hid, str) and hid not in store.pass_holders:
            raise err_not_found("involved_pass_holder_id does not resolve")
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if not isinstance(gid, str) or not gid:
            raise err_invalid_request("Field 'reporting_lifeguard_id' is required")
        if not isinstance(hid, str) or not hid:
            raise err_invalid_request("Field 'involved_pass_holder_id' is required")
        incident_type = req_enum(body, "incident_type",
                                 {"RESCUE", "FIRST_AID", "RULE_VIOLATION", "EQUIPMENT_FAILURE"})
        severity = req_enum(body, "severity", {"MINOR", "MODERATE", "MAJOR"})
        occurred_at = store.parse_datetime(body.get("occurred_at"))
        if occurred_at is None:
            raise err_invalid_request("Field 'occurred_at' must be an ISO 8601 timestamp")
        narrative = req_str(body, "narrative")
        r = store.base_fields()
        r.update({
            "facility_id": fid,
            "reporting_lifeguard_id": gid,
            "involved_pass_holder_id": hid,
            "incident_type": incident_type,
            "occurred_at": store.iso(occurred_at),
            "severity": severity,
            "narrative": narrative,
            "status": "DRAFT",
            "_seq": store.next_seq(),
        })
        store.incident_reports[r["id"]] = r
        return success(serialize(r), 201)

    @app.route("/incident-reports/<rid>", methods=["GET"])
    def get_incident(rid):
        authenticate(["Lifeguard", "AquaticsManager", "GateAttendant"])
        r = store.incident_reports.get(rid)
        if not r:
            raise err_not_found("IncidentReport not found")
        return success(serialize(r), 200)

    @app.route("/incident-reports", methods=["GET"])
    def list_incidents():
        authenticate(["AquaticsManager", "GateAttendant"])
        from flask import request
        items = list(store.incident_reports.values())
        for param, field in (("facility_id", "facility_id"),
                             ("involved_pass_holder_id", "involved_pass_holder_id"),
                             ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [r for r in items if r[field] == v]
        return list_response([serialize(r) for r in sort_created(items)])

    @app.route("/incident-reports/<rid>/submit", methods=["POST"])
    def submit_incident(rid):
        role, uid = authenticate(["Lifeguard"])
        r = store.incident_reports.get(rid)
        if not r:
            raise err_not_found("IncidentReport not found")
        # instance identity: the reporting lifeguard submits personally
        if r["reporting_lifeguard_id"] != uid:
            raise err_forbidden("X-User-ID must equal the report's reporting_lifeguard_id")
        # priority 6: state
        if r["status"] != "DRAFT":
            raise err_invalid_state("Only a DRAFT report can be submitted")
        # priority 10: cert must be ACTIVE at submission time
        guard = store.lifeguards.get(r["reporting_lifeguard_id"])
        if not guard or guard["cert_status"] != "ACTIVE":
            raise err_guard_not_certified()
        r["status"] = "SUBMITTED"
        store.touch(r)
        return success(serialize(r), 200)

    @app.route("/incident-reports/<rid>/confirm", methods=["POST"])
    def confirm_incident(rid):
        authenticate(AM)
        r = store.incident_reports.get(rid)
        if not r:
            raise err_not_found("IncidentReport not found")
        if r["status"] != "SUBMITTED":
            raise err_invalid_state("Only a SUBMITTED report can be confirmed")
        r["status"] = "CONFIRMED"
        store.touch(r)
        holder = store.pass_holders.get(r["involved_pass_holder_id"])
        if holder:
            holder["strike_count"] += 1
            store.touch(holder)
            if r["severity"] == "MAJOR" or holder["strike_count"] >= 3:
                domain.activate_ban(holder, store.now())
        return success(serialize(r), 200)

    @app.route("/incident-reports/<rid>/dismiss", methods=["POST"])
    def dismiss_incident(rid):
        authenticate(AM)
        r = store.incident_reports.get(rid)
        if not r:
            raise err_not_found("IncidentReport not found")
        if r["status"] != "SUBMITTED":
            raise err_invalid_state("Only a SUBMITTED report can be dismissed")
        r["status"] = "DISMISSED"
        store.touch(r)
        return success(serialize(r), 200)

    # ---------------------------------------------------------------- closures
    @app.route("/closures/<cid>", methods=["GET"])
    def get_closure(cid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant", "PassHolder"])
        c = store.closures.get(cid)
        if not c:
            raise err_not_found("PoolClosureEvent not found")
        return success(serialize(c), 200)

    @app.route("/closures/<cid>/resolve", methods=["POST"])
    def resolve_closure(cid):
        authenticate(AM)
        c = store.closures.get(cid)
        if not c:
            raise err_not_found("PoolClosureEvent not found")
        if c["status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE closure can be resolved")
        fac = store.facilities.get(c["facility_id"])
        # reopen gate applies to both resolution paths (PRD §3.9)
        others_active = any(
            o["facility_id"] == c["facility_id"] and o["status"] == "ACTIVE" and o["id"] != cid
            for o in store.closures.values())
        if others_active:
            raise err_reopen_criteria("Other ACTIVE closures exist for this facility")
        if fac is not None and fac["operational_status"] in domain.REOPENABLE_STATUSES:
            if c["closure_reason"] == "CHEMISTRY":
                if fac["chemistry_state"] != "IN_RANGE":
                    raise err_reopen_criteria("Most recent chemistry log is not IN_RANGE")
                if fac.get("_oor_streak_max", 0) >= 2 and fac.get("_consec_in_range", 0) < 2:
                    raise err_reopen_criteria(
                        "Two consecutive IN_RANGE readings required after an OUT_OF_RANGE streak")
            if c["closure_reason"] == "STAFFING_SHORTAGE":
                from datetime import timedelta
                now = store.now()
                covered = domain.scheduled_guard_count(fac["id"], now, now + timedelta(hours=2))
                if covered < fac["required_lifeguard_count"]:
                    raise err_reopen_criteria("Staffing coverage is still insufficient")
        c["status"] = "RESOLVED"
        c["ended_at"] = store.now_iso()
        store.touch(c)
        if fac is not None:
            # recompute posture: no active closures remain after this resolution
            any_active = any(
                o["facility_id"] == fac["id"] and o["status"] == "ACTIVE"
                for o in store.closures.values())
            if not any_active and fac["operational_status"] in domain.REOPENABLE_STATUSES:
                fac["operational_status"] = "RESTRICTED" if fac["chemistry_state"] == "WARNING" else "OPEN"
                if fac["operational_status"] == "OPEN":
                    fac["_oor_streak_max"] = 0
                    fac["_consec_in_range"] = 0
                    fac["_consec_oor"] = 0
                domain.recompute_required_lifeguards(fac)
                store.touch(fac)
        return success(serialize(c), 200)
