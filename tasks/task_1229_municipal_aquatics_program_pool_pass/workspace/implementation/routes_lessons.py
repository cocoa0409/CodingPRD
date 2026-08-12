"""Routes: swim lesson levels, lesson sessions, enrollments."""
from datetime import timedelta

import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_facility_closed, err_forbidden, err_holder_banned,
                    err_invalid_request, err_invalid_state, err_lane_capacity,
                    err_not_found, err_prerequisite, err_session_outside_season,
                    err_stale_version)
from util import is_int, req_int, req_str

AM = ["AquaticsManager"]
ALL = ["AquaticsManager", "GateAttendant", "PassHolder", "Lifeguard"]


def _session_window_inside_season(session_start, session_end, season):
    """start >= season.start_date and end <= day after season.end_date (PRD §3.6)."""
    if session_start < store.day_start(season["_start_date"]):
        return False
    if session_end > store.day_start(season["_end_date"]) + timedelta(days=1):
        return False
    return True


def register(app):
    # ------------------------------------------------------------ lesson levels
    @app.route("/lesson-levels", methods=["POST"])
    def create_level():
        authenticate(AM)
        body = get_body()
        # priority 5: FK
        prereq = body.get("prerequisite_level_id")
        if prereq is not None and isinstance(prereq, str) and prereq not in store.lesson_levels:
            raise err_not_found("prerequisite_level_id does not resolve")
        # priority 22: shape
        level_code = req_str(body, "level_code")
        display_name = req_str(body, "display_name")
        min_age = req_int(body, "min_age_years", minimum=0)
        capacity = req_int(body, "capacity_per_session", minimum=1)
        if prereq is not None and not isinstance(prereq, str):
            raise err_invalid_request("Field 'prerequisite_level_id' must be a string or null")
        for lvl in store.lesson_levels.values():
            if lvl["level_code"] == level_code:
                raise err_invalid_request("level_code must be unique")
        lvl = store.base_fields()
        lvl.update({
            "level_code": level_code,
            "display_name": display_name,
            "min_age_years": min_age,
            "prerequisite_level_id": prereq,
            "capacity_per_session": capacity,
            "_seq": store.next_seq(),
        })
        store.lesson_levels[lvl["id"]] = lvl
        return success(serialize(lvl), 201)

    @app.route("/lesson-levels/<lid>", methods=["GET"])
    def get_level(lid):
        authenticate(ALL)
        lvl = store.lesson_levels.get(lid)
        if not lvl:
            raise err_not_found("SwimLessonLevel not found")
        return success(serialize(lvl), 200)

    @app.route("/lesson-levels", methods=["GET"])
    def list_levels():
        authenticate(ALL)
        from flask import request
        items = list(store.lesson_levels.values())
        prereq = request.args.get("prerequisite_level_id")
        if prereq is not None:
            items = [l for l in items if l.get("prerequisite_level_id") == prereq]
        return list_response([serialize(l) for l in sort_created(items)])

    @app.route("/lesson-levels/<lid>/enrollments-as-evidence", methods=["GET"])
    def list_evidence_enrollments(lid):
        authenticate(["AquaticsManager", "GateAttendant"])
        lvl = store.lesson_levels.get(lid)
        if not lvl:
            raise err_not_found("SwimLessonLevel not found")
        items = [e for e in store.enrollments.values()
                 if e.get("placement_evidence_level_id") == lid]
        return list_response([serialize(e) for e in sort_created(items)])

    # ---------------------------------------------------------- lesson sessions
    @app.route("/lesson-sessions", methods=["POST"])
    def create_session():
        authenticate(AM)
        body = get_body()
        fid = body.get("facility_id")
        lid = body.get("level_id")
        sid = body.get("season_id")
        # priority 5: FKs
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        if isinstance(lid, str) and lid not in store.lesson_levels:
            raise err_not_found("level_id does not resolve")
        if isinstance(sid, str) and sid not in store.seasons:
            raise err_not_found("season_id does not resolve")
        start = store.parse_datetime(body.get("start_datetime"))
        end = store.parse_datetime(body.get("end_datetime"))
        # priority 13: window inside season
        if (isinstance(sid, str) and sid in store.seasons
                and start is not None and end is not None):
            if not _session_window_inside_season(start, end, store.seasons[sid]):
                raise err_session_outside_season()
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if not isinstance(lid, str) or not lid:
            raise err_invalid_request("Field 'level_id' is required")
        if not isinstance(sid, str) or not sid:
            raise err_invalid_request("Field 'season_id' is required")
        if start is None:
            raise err_invalid_request("Field 'start_datetime' must be an ISO 8601 timestamp")
        if end is None:
            raise err_invalid_request("Field 'end_datetime' must be an ISO 8601 timestamp")
        if end <= start:
            raise err_invalid_request("end_datetime must be after start_datetime")
        lanes = req_int(body, "lanes_required", minimum=1)
        sess = store.base_fields()
        sess.update({
            "facility_id": fid,
            "level_id": lid,
            "season_id": sid,
            "start_datetime": store.iso(start),
            "end_datetime": store.iso(end),
            "lanes_required": lanes,
            "enrolled_count": 0,
            "status": "DRAFT",
            "_start": start,
            "_end": end,
            "_seq": store.next_seq(),
        })
        store.lesson_sessions[sess["id"]] = sess
        return success(serialize(sess), 201)

    @app.route("/lesson-sessions/<sid>", methods=["GET"])
    def get_session(sid):
        authenticate(ALL)
        sess = store.lesson_sessions.get(sid)
        if not sess:
            raise err_not_found("LessonSession not found")
        return success(serialize(sess), 200)

    @app.route("/lesson-sessions", methods=["GET"])
    def list_sessions():
        authenticate(ALL)
        from flask import request
        items = list(store.lesson_sessions.values())
        for param, field in (("facility_id", "facility_id"), ("level_id", "level_id"),
                             ("season_id", "season_id"), ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [s for s in items if s[field] == v]
        return list_response([serialize(s) for s in sort_created(items)])

    @app.route("/lesson-sessions/<sid>/enrollments", methods=["GET"])
    def list_session_enrollments(sid):
        authenticate(ALL)
        sess = store.lesson_sessions.get(sid)
        if not sess:
            raise err_not_found("LessonSession not found")
        items = [e for e in store.enrollments.values() if e["lesson_session_id"] == sid]
        return list_response([serialize(e) for e in sort_created(items)])

    @app.route("/lesson-sessions/<sid>/lane-allocations", methods=["GET"])
    def list_session_allocations(sid):
        authenticate(["AquaticsManager", "GateAttendant"])
        sess = store.lesson_sessions.get(sid)
        if not sess:
            raise err_not_found("LessonSession not found")
        items = [a for a in store.lane_allocations.values()
                 if a.get("owning_lesson_session_id") == sid]
        return list_response([serialize(a) for a in sort_created(items)])

    @app.route("/lesson-sessions/<sid>/schedule", methods=["POST"])
    def schedule_session(sid):
        authenticate(AM)
        sess = store.lesson_sessions.get(sid)
        if not sess:
            raise err_not_found("LessonSession not found")
        # priority 6: state
        if sess["status"] != "DRAFT":
            raise err_invalid_state("Only a DRAFT session can be scheduled")
        body = get_body()
        fac = store.facilities[sess["facility_id"]]
        # priority 7: OCC on the parent facility
        expected = body.get("expected_facility_version")
        if is_int(expected) and expected != fac["version"]:
            raise err_stale_version()
        # priority 8: scheduling requires the facility to be OPEN exactly
        if fac["operational_status"] != "OPEN":
            raise err_facility_closed("Lesson sessions can only be scheduled while OPEN")
        # priority 12: lane availability at every instant of the window
        worst = domain.max_reserved_lanes(fac["id"], sess["_start"], sess["_end"])
        if worst + sess["lanes_required"] > fac["lap_lane_count"]:
            raise err_lane_capacity()
        # priority 13: window still inside its season
        season = store.seasons.get(sess["season_id"])
        if season and not _session_window_inside_season(sess["_start"], sess["_end"], season):
            raise err_session_outside_season()
        # priority 22: OCC field is required by PRD §2.7
        if not is_int(expected):
            raise err_invalid_request("Field 'expected_facility_version' is required and must be an integer")

        sess["status"] = "SCHEDULED"
        store.touch(sess)
        alloc = store.base_fields()
        alloc.update({
            "facility_id": fac["id"],
            "purpose": "LESSON",
            "start_datetime": sess["start_datetime"],
            "end_datetime": sess["end_datetime"],
            "lane_count": sess["lanes_required"],
            "owning_lesson_session_id": sess["id"],
            "status": "RESERVED",
            "_start": sess["_start"],
            "_end": sess["_end"],
            "_seq": store.next_seq(),
        })
        store.lane_allocations[alloc["id"]] = alloc
        store.touch(fac)  # scheduling increments Facility.version
        return success(serialize(sess), 200)

    @app.route("/lesson-sessions/<sid>/cancel", methods=["POST"])
    def cancel_session(sid):
        authenticate(AM)
        sess = store.lesson_sessions.get(sid)
        if not sess:
            raise err_not_found("LessonSession not found")
        if sess["status"] not in ("DRAFT", "SCHEDULED"):
            raise err_invalid_state("Only a DRAFT or SCHEDULED session can be cancelled")
        domain.cancel_session(sess)
        return success(serialize(sess), 200)

    # -------------------------------------------------------------- enrollments
    @app.route("/enrollments", methods=["POST"])
    def create_enrollment():
        authenticate(["GateAttendant", "AquaticsManager", "PassHolder"])
        body = get_body()
        sid = body.get("lesson_session_id")
        hid = body.get("pass_holder_id")
        evid = body.get("placement_evidence_level_id")
        # priority 5: FKs
        if isinstance(sid, str) and sid not in store.lesson_sessions:
            raise err_not_found("lesson_session_id does not resolve")
        if isinstance(hid, str) and hid not in store.pass_holders:
            raise err_not_found("pass_holder_id does not resolve")
        if evid is not None and isinstance(evid, str) and evid not in store.lesson_levels:
            raise err_not_found("placement_evidence_level_id does not resolve")
        # priority 6: session must be enrollable
        sess = store.lesson_sessions.get(sid) if isinstance(sid, str) else None
        if sess is not None and sess["status"] in ("CANCELLED", "COMPLETED"):
            raise err_invalid_state("Cannot enroll in a CANCELLED or COMPLETED session")
        # priority 9: banned patron
        now = store.now()
        holder = store.pass_holders.get(hid) if isinstance(hid, str) else None
        if holder and domain.is_banned(holder, now):
            raise err_holder_banned()
        # priority 16: prerequisite + age minimum
        if sess is not None and holder is not None:
            level = store.lesson_levels.get(sess["level_id"])
            if level is not None:
                prereq = level.get("prerequisite_level_id")
                if prereq is not None and evid != prereq:
                    raise err_prerequisite("placement_evidence_level_id does not match the level prerequisite")
                age = store.age_years(holder["_dob"], sess["_start"].date())
                if age < level["min_age_years"]:
                    raise err_prerequisite("Holder does not meet the level minimum age")
        # priority 22: shape
        if not isinstance(sid, str) or not sid:
            raise err_invalid_request("Field 'lesson_session_id' is required")
        if not isinstance(hid, str) or not hid:
            raise err_invalid_request("Field 'pass_holder_id' is required")
        if evid is not None and not isinstance(evid, str):
            raise err_invalid_request("Field 'placement_evidence_level_id' must be a string or null")

        level = store.lesson_levels[sess["level_id"]]
        enr = store.base_fields()
        if sess["enrolled_count"] < level["capacity_per_session"]:
            status = "ENROLLED"
            position = None
        else:
            status = "WAITLISTED"
            waiting = sum(1 for e in store.enrollments.values()
                          if e["lesson_session_id"] == sid and e["status"] == "WAITLISTED")
            position = waiting + 1
        enr.update({
            "lesson_session_id": sid,
            "pass_holder_id": hid,
            "placement_evidence_level_id": evid,
            "status": status,
            "waitlist_position": position,
            "_seq": store.next_seq(),
        })
        store.enrollments[enr["id"]] = enr
        if status == "ENROLLED":
            sess["enrolled_count"] += 1
            store.touch(sess)
        return success(serialize(enr), 201)

    @app.route("/enrollments/<eid>", methods=["GET"])
    def get_enrollment(eid):
        role, uid = authenticate(["AquaticsManager", "GateAttendant", "PassHolder"])
        e = store.enrollments.get(eid)
        if not e:
            raise err_not_found("LessonEnrollment not found")
        if role == "PassHolder" and e["pass_holder_id"] != uid:
            raise err_forbidden("PassHolder may only access their own enrollments")
        return success(serialize(e), 200)

    @app.route("/enrollments/<eid>/drop", methods=["POST"])
    def drop_enrollment(eid):
        role, uid = authenticate(["AquaticsManager", "PassHolder"])
        e = store.enrollments.get(eid)
        if not e:
            raise err_not_found("LessonEnrollment not found")
        # instance ownership: patron may only drop their own enrollment
        if role == "PassHolder" and e["pass_holder_id"] != uid:
            raise err_forbidden("PassHolder may only drop their own enrollments")
        if e["status"] not in ("ENROLLED", "WAITLISTED"):
            raise err_invalid_state("Only an ENROLLED or WAITLISTED enrollment can be dropped")
        was_enrolled = e["status"] == "ENROLLED"
        e["status"] = "DROPPED"
        e["waitlist_position"] = None
        store.touch(e)
        sess = store.lesson_sessions.get(e["lesson_session_id"])
        if sess and was_enrolled:
            sess["enrolled_count"] = max(0, sess["enrolled_count"] - 1)
            store.touch(sess)
            # promote the waitlist head (lowest position, earliest created_at wins ties)
            waiting = [w for w in store.enrollments.values()
                       if w["lesson_session_id"] == sess["id"] and w["status"] == "WAITLISTED"]
            if waiting:
                waiting.sort(key=lambda w: (w.get("waitlist_position") or 1 << 30, w["_seq"]))
                head = waiting[0]
                head["status"] = "ENROLLED"
                head["waitlist_position"] = None
                store.touch(head)
                sess["enrolled_count"] += 1
                store.touch(sess)
        if sess:
            domain.renumber_waitlist(sess["id"])
        return success(serialize(e), 200)
