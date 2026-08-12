"""Routes: clock, facilities, chemistry logs, closures, reopen, seasons."""
from datetime import timedelta

import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_chemistry_input, err_invalid_request, err_invalid_state,
                    err_not_found, err_reopen_criteria, err_season_overlap)
from util import is_int, is_num, req_enum, req_int, req_str

ALL = ["AquaticsManager", "GateAttendant", "Lifeguard", "PassHolder"]
AM = ["AquaticsManager"]


def register(app):
    # ------------------------------------------------------------------ clock
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authenticate(AM)
        body = get_body()
        dt = store.parse_datetime(body.get("to_iso8601"))
        if dt is None:
            raise err_invalid_request("Field 'to_iso8601' must be an ISO 8601 timestamp")
        store.set_clock(dt)
        domain.reevaluate_time_transitions()
        return success({"current_utc": store.iso(dt)}, 200)

    # ------------------------------------------------------------- facilities
    @app.route("/facilities", methods=["POST"])
    def create_facility():
        authenticate(AM)
        body = get_body()
        name = req_str(body, "name")
        address = req_str(body, "address")
        max_cap = req_int(body, "max_bather_capacity", minimum=1)
        lanes = req_int(body, "lap_lane_count", minimum=0)
        fac = store.base_fields()
        fac.update({
            "name": name,
            "address": address,
            "max_bather_capacity": max_cap,
            "lap_lane_count": lanes,
            "current_bather_count": 0,
            "required_lifeguard_count": 0,
            "operational_status": "OPEN",
            "chemistry_state": "IN_RANGE",
            "chemistry_out_of_range_since": None,
            "_seq": store.next_seq(),
            "_consec_oor": 0,
            "_consec_in_range": 0,
            "_oor_streak_max": 0,
        })
        store.facilities[fac["id"]] = fac
        return success(serialize(fac), 201)

    @app.route("/facilities/<fid>", methods=["GET"])
    def get_facility(fid):
        authenticate(ALL)
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        return success(serialize(fac), 200)

    @app.route("/facilities", methods=["GET"])
    def list_facilities():
        authenticate(ALL)
        return list_response([serialize(f) for f in sort_created(store.facilities.values())])

    # --------------------------------------------------------- chemistry logs
    @app.route("/facilities/<fid>/chemistry-logs", methods=["GET"])
    def list_chemistry_logs(fid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        logs = [c for c in store.chemistry_logs.values() if c["facility_id"] == fid]
        # newest first by recorded_at (PRD §2.3 exception)
        logs.sort(key=lambda c: (store.parse_datetime(c["recorded_at"]) or store.now(),
                                 c.get("_seq", 0)), reverse=True)
        return list_response([serialize(c) for c in logs])

    @app.route("/facilities/<fid>/chemistry-logs", methods=["POST"])
    def create_chemistry_log(fid):
        role, _ = authenticate(["Lifeguard", "AquaticsManager"])
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        body = get_body()
        # priority 5: body FK resolution
        lg_id = body.get("recorded_by_lifeguard_id")
        if isinstance(lg_id, str) and lg_id not in store.lifeguards:
            raise err_not_found("recorded_by_lifeguard_id does not resolve")
        # priority 18: plausible instrument bounds (before shape checks)
        fc, ph, cc = body.get("free_chlorine_ppm"), body.get("ph"), body.get("combined_chlorine_ppm")
        if is_num(fc) and is_num(ph) and is_num(cc):
            if not (0 <= fc <= 10 and 6.0 <= ph <= 9.0 and 0 <= cc <= 5):
                raise err_chemistry_input()
        # priority 22: shape
        recorded_at = store.parse_datetime(body.get("recorded_at"))
        if recorded_at is None:
            raise err_invalid_request("Field 'recorded_at' must be an ISO 8601 timestamp")
        if not is_num(fc):
            raise err_invalid_request("Field 'free_chlorine_ppm' must be a number")
        if not is_num(ph):
            raise err_invalid_request("Field 'ph' must be a number")
        if not is_num(cc):
            raise err_invalid_request("Field 'combined_chlorine_ppm' must be a number")
        if not isinstance(lg_id, str) or not lg_id:
            raise err_invalid_request("Field 'recorded_by_lifeguard_id' is required")

        classification = domain.classify_chemistry(fc, ph, cc)
        log = {
            "id": store.new_id(),
            "created_at": store.now_iso(),
            "facility_id": fid,
            "recorded_at": store.iso(recorded_at),
            "free_chlorine_ppm": fc,
            "ph": ph,
            "combined_chlorine_ppm": cc,
            "classification": classification,
            "recorded_by_lifeguard_id": lg_id,
            "_seq": store.next_seq(),
        }
        store.chemistry_logs[log["id"]] = log

        # derived chemistry state + streak bookkeeping
        prev_state = fac["chemistry_state"]
        fac["chemistry_state"] = classification
        if classification == "OUT_OF_RANGE":
            fac["_consec_oor"] = fac.get("_consec_oor", 0) + 1
            fac["_consec_in_range"] = 0
            fac["_oor_streak_max"] = max(fac.get("_oor_streak_max", 0), fac["_consec_oor"])
            if prev_state != "OUT_OF_RANGE":
                fac["chemistry_out_of_range_since"] = store.iso(recorded_at)
        elif classification == "WARNING":
            fac["_consec_oor"] = 0
            fac["_consec_in_range"] = 0
            fac["chemistry_out_of_range_since"] = None
        else:  # IN_RANGE
            fac["_consec_oor"] = 0
            fac["_consec_in_range"] = fac.get("_consec_in_range", 0) + 1
            fac["chemistry_out_of_range_since"] = None

        # posture transitions driven by the new reading
        status = fac["operational_status"]
        if classification == "OUT_OF_RANGE" and status in ("OPEN", "RESTRICTED"):
            domain.apply_closure(fac, "CHEMISTRY", store.now())
        elif classification == "WARNING" and status == "OPEN":
            fac["operational_status"] = "RESTRICTED"
            domain.recompute_required_lifeguards(fac)
            store.touch(fac)
        elif classification == "IN_RANGE" and status == "RESTRICTED":
            fac["operational_status"] = "OPEN"
            domain.recompute_required_lifeguards(fac)
            store.touch(fac)
        # every chemistry log post mutates the facility (version bump)
        store.touch(fac)
        return success(serialize(log), 201)

    # --------------------------------------------------------------- closures
    @app.route("/facilities/<fid>/closures", methods=["GET"])
    def list_closures(fid):
        authenticate(ALL)
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        events = [c for c in store.closures.values() if c["facility_id"] == fid]
        return list_response([serialize(c) for c in sort_created(events)])

    @app.route("/facilities/<fid>/closures", methods=["POST"])
    def create_closure(fid):
        authenticate(AM)
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        body = get_body()
        # priority 6: facility must not already be closed
        if fac["operational_status"] in domain.CLOSED_STATUSES:
            raise err_invalid_state("Facility is already in a CLOSED_* status")
        reason = req_enum(body, "closure_reason",
                          {"WEATHER", "CHEMISTRY", "STAFFING_SHORTAGE", "SEASON_END"})
        started_at = store.parse_datetime(body.get("started_at"))
        if started_at is None:
            raise err_invalid_request("Field 'started_at' must be an ISO 8601 timestamp")
        event = domain.apply_closure(fac, reason, started_at)
        return success(serialize(event), 201)

    # ---------------------------------------------------------------- reopen
    @app.route("/facilities/<fid>/reopen", methods=["POST"])
    def reopen_facility(fid):
        authenticate(AM)
        fac = store.facilities.get(fid)
        if not fac:
            raise err_not_found("Facility not found")
        if fac["operational_status"] not in domain.REOPENABLE_STATUSES:
            raise err_invalid_state("Facility is not in a reopenable CLOSED_* status")
        _check_reopen_criteria(fac)
        now = store.now()
        for c in store.closures.values():
            if c["facility_id"] == fid and c["status"] == "ACTIVE":
                c["status"] = "RESOLVED"
                c["ended_at"] = store.iso(now)
                store.touch(c)
        fac["operational_status"] = "OPEN"
        fac["_oor_streak_max"] = 0
        fac["_consec_in_range"] = 0
        fac["_consec_oor"] = 0
        domain.recompute_required_lifeguards(fac)
        store.touch(fac)
        return success(serialize(fac), 200)

    # ---------------------------------------------------------------- seasons
    @app.route("/seasons", methods=["POST"])
    def create_season():
        authenticate(AM)
        body = get_body()
        # priority 5: FK
        fid = body.get("facility_id")
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        season_name = req_str(body, "season_name")
        start_date = store.date_or_datetime_to_date(body.get("start_date"))
        end_date = store.date_or_datetime_to_date(body.get("end_date"))
        if start_date is None:
            raise err_invalid_request("Field 'start_date' must be an ISO date")
        if end_date is None:
            raise err_invalid_request("Field 'end_date' must be an ISO date")
        if end_date <= start_date:
            raise err_invalid_request("end_date must be after start_date")
        rpp = req_int(body, "resident_pass_price_cents", minimum=0)
        npp = req_int(body, "non_resident_pass_price_cents", minimum=0)
        rdp = req_int(body, "resident_daily_price_cents", minimum=0)
        ndp = req_int(body, "non_resident_daily_price_cents", minimum=0)
        season = store.base_fields()
        season.update({
            "facility_id": fid,
            "season_name": season_name,
            "start_date": store.iso_date(start_date),
            "end_date": store.iso_date(end_date),
            "resident_pass_price_cents": rpp,
            "non_resident_pass_price_cents": npp,
            "resident_daily_price_cents": rdp,
            "non_resident_daily_price_cents": ndp,
            "status": "DRAFT",
            "_start_date": start_date,
            "_end_date": end_date,
            "_seq": store.next_seq(),
        })
        store.seasons[season["id"]] = season
        return success(serialize(season), 201)

    @app.route("/seasons/<sid>", methods=["GET"])
    def get_season(sid):
        authenticate(ALL)
        season = store.seasons.get(sid)
        if not season:
            raise err_not_found("MembershipSeason not found")
        return success(serialize(season), 200)

    @app.route("/seasons", methods=["GET"])
    def list_seasons():
        authenticate(ALL)
        from flask import request
        items = list(store.seasons.values())
        fid = request.args.get("facility_id")
        if fid is not None:
            items = [s for s in items if s["facility_id"] == fid]
        status = request.args.get("status")
        if status is not None:
            items = [s for s in items if s["status"] == status]
        return list_response([serialize(s) for s in sort_created(items)])

    @app.route("/seasons/<sid>/passes", methods=["GET"])
    def list_season_passes(sid):
        authenticate(["AquaticsManager", "GateAttendant"])
        season = store.seasons.get(sid)
        if not season:
            raise err_not_found("MembershipSeason not found")
        items = [p for p in store.season_passes.values() if p["season_id"] == sid]
        return list_response([serialize(p) for p in sort_created(items)])

    @app.route("/seasons/<sid>/publish", methods=["POST"])
    def publish_season(sid):
        authenticate(AM)
        season = store.seasons.get(sid)
        if not season:
            raise err_not_found("MembershipSeason not found")
        if season["status"] != "DRAFT":
            raise err_invalid_state("Only a DRAFT season can be published")
        # priority 17: pricing order + PUBLISHED overlap (half-open [start, end+1d))
        if (season["resident_pass_price_cents"] > season["non_resident_pass_price_cents"]
                or season["resident_daily_price_cents"] > season["non_resident_daily_price_cents"]):
            raise err_season_overlap("Resident prices must not exceed non-resident prices")
        for other in store.seasons.values():
            if other["id"] == sid or other["facility_id"] != season["facility_id"]:
                continue
            if other["status"] != "PUBLISHED":
                continue
            if (season["_start_date"] <= other["_end_date"]
                    and other["_start_date"] <= season["_end_date"]):
                raise err_season_overlap("Overlaps another PUBLISHED season for the facility")
        season["status"] = "PUBLISHED"
        store.touch(season)
        return success(serialize(season), 200)

    @app.route("/seasons/<sid>/close", methods=["POST"])
    def close_season(sid):
        authenticate(AM)
        season = store.seasons.get(sid)
        if not season:
            raise err_not_found("MembershipSeason not found")
        if season["status"] != "PUBLISHED":
            raise err_invalid_state("Only a PUBLISHED season can be closed")
        domain.close_season(season)
        return success(serialize(season), 200)


def _check_reopen_criteria(fac):
    """PRD §3.9 reopen gate: chemistry streak rule and staffing coverage."""
    status = fac["operational_status"]
    if status == "CLOSED_CHEMISTRY":
        if fac["chemistry_state"] != "IN_RANGE":
            raise err_reopen_criteria("Most recent chemistry log is not IN_RANGE")
        if fac.get("_oor_streak_max", 0) >= 2 and fac.get("_consec_in_range", 0) < 2:
            raise err_reopen_criteria(
                "Two consecutive IN_RANGE readings required after a multi-reading OUT_OF_RANGE streak")
    if status == "CLOSED_STAFFING":
        now = store.now()
        covered = domain.scheduled_guard_count(fac["id"], now, now + timedelta(hours=2))
        if covered < fac["required_lifeguard_count"]:
            raise err_reopen_criteria("Staffing coverage for the next two hours is insufficient")
