"""Routes: pass holders, season passes, daily admissions."""
from datetime import timedelta

import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_admission_date, err_already_checked_in, err_facility_at_capacity,
                    err_facility_closed, err_forbidden, err_holder_banned,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_pass_not_valid)
from util import req_enum, req_str

GA_AM = ["GateAttendant", "AquaticsManager"]


def _get_holder_or_404(hid):
    holder = store.pass_holders.get(hid)
    if not holder:
        raise err_not_found("PassHolder not found")
    return holder


def _holder_self_check(role, user_id, holder_id):
    if role == "PassHolder" and user_id != holder_id:
        raise err_forbidden("PassHolder may only access their own record")


def register(app):
    # ----------------------------------------------------------- pass holders
    @app.route("/pass-holders", methods=["POST"])
    def create_pass_holder():
        authenticate(GA_AM)
        body = get_body()
        full_name = req_str(body, "full_name")
        dob = store.date_or_datetime_to_date(body.get("date_of_birth"))
        if dob is None:
            raise err_invalid_request("Field 'date_of_birth' must be an ISO date")
        residency = req_enum(body, "residency_status", {"RESIDENT", "NON_RESIDENT"})
        email = req_str(body, "email")
        holder = store.base_fields()
        holder.update({
            "full_name": full_name,
            "date_of_birth": store.iso_date(dob),
            "residency_status": residency,
            "email": email,
            "strike_count": 0,
            "banned_until": None,
            "_dob": dob,
            "_seq": store.next_seq(),
        })
        store.pass_holders[holder["id"]] = holder
        return success(serialize(holder), 201)

    @app.route("/pass-holders/<hid>", methods=["GET"])
    def get_pass_holder(hid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        holder = _get_holder_or_404(hid)
        _holder_self_check(role, uid, hid)
        return success(serialize(holder), 200)

    @app.route("/pass-holders/<hid>/passes", methods=["GET"])
    def list_holder_passes(hid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        _get_holder_or_404(hid)
        _holder_self_check(role, uid, hid)
        items = [p for p in store.season_passes.values() if p["pass_holder_id"] == hid]
        return list_response([serialize(p) for p in sort_created(items)])

    @app.route("/pass-holders/<hid>/admissions", methods=["GET"])
    def list_holder_admissions(hid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        _get_holder_or_404(hid)
        _holder_self_check(role, uid, hid)
        items = [a for a in store.admissions.values() if a["pass_holder_id"] == hid]
        return list_response([serialize(a) for a in sort_created(items)])

    @app.route("/pass-holders/<hid>/rentals", methods=["GET"])
    def list_holder_rentals(hid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        _get_holder_or_404(hid)
        _holder_self_check(role, uid, hid)
        items = [r for r in store.rentals.values() if r["pass_holder_id"] == hid]
        return list_response([serialize(r) for r in sort_created(items)])

    @app.route("/pass-holders/<hid>/enrollments", methods=["GET"])
    def list_holder_enrollments(hid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        _get_holder_or_404(hid)
        _holder_self_check(role, uid, hid)
        items = [e for e in store.enrollments.values() if e["pass_holder_id"] == hid]
        return list_response([serialize(e) for e in sort_created(items)])

    # ----------------------------------------------------------- season passes
    @app.route("/passes", methods=["POST"])
    def create_pass():
        authenticate(GA_AM)
        body = get_body()
        # priority 5: FK resolution
        hid = body.get("pass_holder_id")
        sid = body.get("season_id")
        if isinstance(hid, str) and hid not in store.pass_holders:
            raise err_not_found("pass_holder_id does not resolve")
        if isinstance(sid, str) and sid not in store.seasons:
            raise err_not_found("season_id does not resolve")
        # priority 22: shape
        if not isinstance(hid, str) or not hid:
            raise err_invalid_request("Field 'pass_holder_id' is required")
        if not isinstance(sid, str) or not sid:
            raise err_invalid_request("Field 'season_id' is required")
        holder = store.pass_holders[hid]
        season = store.seasons[sid]
        # priority 6: purchases open only while the season is PUBLISHED
        if season["status"] != "PUBLISHED":
            raise err_invalid_state("SeasonPass purchases are only allowed against a PUBLISHED season")
        price = (season["resident_pass_price_cents"] if holder["residency_status"] == "RESIDENT"
                 else season["non_resident_pass_price_cents"])
        p = store.base_fields()
        p.update({
            "pass_holder_id": hid,
            "season_id": sid,
            "purchase_price_cents": price,
            "refunded_cents": 0,
            "status": "ACTIVE",
            "_seq": store.next_seq(),
        })
        store.season_passes[p["id"]] = p
        return success(serialize(p), 201)

    @app.route("/passes/<pid>", methods=["GET"])
    def get_pass(pid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        p = store.season_passes.get(pid)
        if not p:
            raise err_not_found("SeasonPass not found")
        _holder_self_check(role, uid, p["pass_holder_id"])
        return success(serialize(p), 200)

    @app.route("/passes/<pid>/refund", methods=["POST"])
    def refund_pass(pid):
        authenticate(["AquaticsManager"])
        p = store.season_passes.get(pid)
        if not p:
            raise err_not_found("SeasonPass not found")
        if p["status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE pass can be refunded")
        season = store.seasons.get(p["season_id"])
        # precondition: current clock still before the season's (inclusive) end date
        if season and store.now() >= store.day_start(season["_end_date"]) + timedelta(days=1):
            raise err_invalid_state("Season has ended; pass can no longer be refunded")
        p["status"] = "REFUNDED"
        p["refunded_cents"] = p["purchase_price_cents"]
        store.touch(p)
        return success(serialize(p), 200)

    @app.route("/passes/<pid>/admissions", methods=["GET"])
    def list_pass_admissions(pid):
        authenticate(GA_AM)
        p = store.season_passes.get(pid)
        if not p:
            raise err_not_found("SeasonPass not found")
        items = [a for a in store.admissions.values() if a.get("season_pass_id") == pid]
        return list_response([serialize(a) for a in sort_created(items)])

    # --------------------------------------------------------- daily admissions
    @app.route("/admissions", methods=["POST"])
    def create_admission():
        authenticate(["GateAttendant"])
        body = get_body()
        fid = body.get("facility_id")
        hid = body.get("pass_holder_id")
        pid = body.get("season_pass_id")
        # priority 5: FK resolution
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        if isinstance(hid, str) and hid not in store.pass_holders:
            raise err_not_found("pass_holder_id does not resolve")
        if pid is not None and isinstance(pid, str) and pid not in store.season_passes:
            raise err_not_found("season_pass_id does not resolve")
        # priority 9: banned patron
        now = store.now()
        if isinstance(hid, str) and hid in store.pass_holders:
            if domain.is_banned(store.pass_holders[hid], now):
                raise err_holder_banned()
        # priority 14: admission_date must be today and covered by a PUBLISHED season
        admission_date = store.date_or_datetime_to_date(body.get("admission_date"))
        season = None
        early_bird = False
        if isinstance(fid, str) and fid in store.facilities and admission_date is not None:
            if admission_date != store.today():
                raise err_admission_date("admission_date must be today per the logical clock")
            season, early_bird = domain.find_current_season(fid, admission_date)
            if season is None:
                raise err_admission_date("No PUBLISHED season covers admission_date")
        # pass validity (ERR_PASS_NOT_VALID)
        if pid is not None and isinstance(pid, str) and pid in store.season_passes:
            p = store.season_passes[pid]
            if (p["status"] != "ACTIVE" or season is None or p["season_id"] != season["id"]
                    or p["pass_holder_id"] != hid):
                raise err_pass_not_valid()
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if not isinstance(hid, str) or not hid:
            raise err_invalid_request("Field 'pass_holder_id' is required")
        if pid is not None and not isinstance(pid, str):
            raise err_invalid_request("Field 'season_pass_id' must be a string")
        if admission_date is None:
            raise err_invalid_request("Field 'admission_date' must be an ISO date")

        holder = store.pass_holders[hid]
        if pid:
            charge = 0
        else:
            charge = domain.daily_admission_charge(season, holder, admission_date, early_bird)
        adm = store.base_fields()
        adm.update({
            "facility_id": fid,
            "pass_holder_id": hid,
            "season_pass_id": pid,
            "admission_date": store.iso_date(admission_date),
            "charge_cents": charge,
            "entered_at": None,
            "exited_at": None,
            "status": "ISSUED",
            "_seq": store.next_seq(),
        })
        store.admissions[adm["id"]] = adm
        return success(serialize(adm), 201)

    @app.route("/admissions/<aid>", methods=["GET"])
    def get_admission(aid):
        role, uid = authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        adm = store.admissions.get(aid)
        if not adm:
            raise err_not_found("DailyAdmission not found")
        _holder_self_check(role, uid, adm["pass_holder_id"])
        return success(serialize(adm), 200)

    @app.route("/admissions", methods=["GET"])
    def list_admissions():
        authenticate(GA_AM)
        from flask import request
        items = list(store.admissions.values())
        fid = request.args.get("facility_id")
        if fid is not None:
            items = [a for a in items if a["facility_id"] == fid]
        hid = request.args.get("pass_holder_id")
        if hid is not None:
            items = [a for a in items if a["pass_holder_id"] == hid]
        status = request.args.get("status")
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return list_response([serialize(a) for a in sort_created(items)])

    @app.route("/admissions/<aid>/enter", methods=["POST"])
    def enter_admission(aid):
        authenticate(["GateAttendant"])
        adm = store.admissions.get(aid)
        if not adm:
            raise err_not_found("DailyAdmission not found")
        # priority 6: state
        if adm["status"] == "ENTERED":
            raise err_already_checked_in("Admission is already ENTERED")
        if adm["status"] != "ISSUED":
            raise err_invalid_state("Only an ISSUED admission can enter")
        fac = store.facilities[adm["facility_id"]]
        # priority 8: facility posture
        if fac["operational_status"] not in ("OPEN", "RESTRICTED"):
            raise err_facility_closed()
        # priority 9: banned patron
        now = store.now()
        holder = store.pass_holders.get(adm["pass_holder_id"])
        if holder and domain.is_banned(holder, now):
            raise err_holder_banned()
        # admission_date must equal today
        if adm["admission_date"] != store.iso_date(now.date()):
            raise err_admission_date("admission_date is not today")
        # priority 20: capacity
        if fac["current_bather_count"] >= fac["max_bather_capacity"]:
            raise err_facility_at_capacity()
        adm["status"] = "ENTERED"
        adm["entered_at"] = store.iso(now)
        store.touch(adm)
        domain.change_bather_count(fac, 1)
        return success(serialize(adm), 200)

    @app.route("/admissions/<aid>/exit", methods=["POST"])
    def exit_admission(aid):
        authenticate(["GateAttendant"])
        adm = store.admissions.get(aid)
        if not adm:
            raise err_not_found("DailyAdmission not found")
        if adm["status"] != "ENTERED":
            raise err_invalid_state("Only an ENTERED admission can exit")
        adm["status"] = "EXITED"
        adm["exited_at"] = store.now_iso()
        store.touch(adm)
        fac = store.facilities[adm["facility_id"]]
        domain.change_bather_count(fac, -1)
        return success(serialize(adm), 200)
