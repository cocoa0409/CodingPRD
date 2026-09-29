"""Airings, playlists, and music logs (PRD 3.5)."""

import response
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_VOLUNTEER,
    authenticate,
    body,
    bool_field,
    bool_query,
    caller_id,
    datetime_field,
    enum_field,
    int_field,
    invalid,
    lookup,
    optional_lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser

AIR_RESULTS = ("AIRED", "SUBSTITUTE_AIRED", "MISSED")
LOG_DECISIONS = ("CERTIFY", "RETURN")

EPISODE_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_VOLUNTEER, ROLE_COMPLIANCE_OFFICER)


def _guard_not_restricted(program):
    if program is not None and domain.program_standing(program) == "RESTRICTED":
        raise ApiError("ERR_PROGRAM_RESTRICTED")


def register(app):
    # --------------------------------------------------------------- airings
    @app.post("/episodes")
    def create_episode():
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        program_id = str_field(data, "program_id")
        slot_id = str_field(data, "slot_assignment_id")
        operator_id = str_field(data, "board_operator_volunteer_id")
        scheduled_start = datetime_field(data, "scheduled_start_utc")

        program = lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        slot = lookup(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
        lookup(db.volunteers, operator_id, "ERR_VOLUNTEER_NOT_FOUND")

        if slot["program_id"] != program["id"]:
            raise ApiError("ERR_SLOT_PROGRAM_MISMATCH")
        weekday = (scheduled_start.weekday() + 1) % 7
        minute_of_day = scheduled_start.hour * 60 + scheduled_start.minute
        if weekday != slot["day_of_week"] or minute_of_day != slot["start_minute"]:
            raise ApiError("ERR_EPISODE_SLOT_MISMATCH")
        _guard_not_restricted(program)
        if not domain.operator_is_live(operator_id):
            raise ApiError("ERR_OPERATOR_NOT_CERTIFIED")

        episode = new_row(db.episodes, {
            "program_id": program["id"],
            "slot_assignment_id": slot["id"],
            "board_operator_volunteer_id": operator_id,
            "scheduled_start_utc": scheduled_start,
            "air_status": "SCHEDULED",
            "log_status": "NOT_REQUIRED",
            "needs_substitute": False,
            "featured_performance_count": 0,
            "local_featured_count": 0,
            "provisional_royalty_cents": None,
            "final_royalty_cents": None,
            "log_due_at": None,
        })
        return response.created(ser.episode(episode))

    @app.get("/episodes")
    def list_episodes():
        authenticate(*EPISODE_READ_ROLES)
        program_id = str_query("program_id")
        slot_id = str_query("slot_assignment_id")
        operator_id = str_query("board_operator_volunteer_id")
        air_status = str_query("air_status")
        log_status = str_query("log_status")
        needs_substitute = bool_query("needs_substitute")

        def keep(row):
            if program_id is not None and row["program_id"] != program_id:
                return False
            if slot_id is not None and row["slot_assignment_id"] != slot_id:
                return False
            if operator_id is not None and row["board_operator_volunteer_id"] != operator_id:
                return False
            if air_status is not None and row["air_status"] != air_status:
                return False
            if log_status is not None and row["log_status"] != log_status:
                return False
            if needs_substitute is not None and row["needs_substitute"] is not needs_substitute:
                return False
            return True

        return response.listing(ordered(db.episodes, keep), ser.episode)

    @app.get("/episodes/<episode_id>")
    def get_episode(episode_id):
        authenticate(*EPISODE_READ_ROLES)
        episode = lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        return response.obj(ser.episode(episode))

    @app.post("/episodes/<episode_id>/air-result")
    def record_air_result(episode_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        air_status = enum_field(data, "air_status", AIR_RESULTS)
        substitute_id = str_field(data, "substitute_board_operator_volunteer_id", required=False, default=None)
        if air_status == "SUBSTITUTE_AIRED" and substitute_id is None:
            invalid("Field 'substitute_board_operator_volunteer_id' is required for a substitute airing.")

        episode = lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        substitute = optional_lookup(db.volunteers, substitute_id, "ERR_VOLUNTEER_NOT_FOUND")
        program = db.programs.get(episode["program_id"])
        _guard_not_restricted(program)
        if episode["air_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a scheduled airing can take an air result.")

        if air_status == "AIRED":
            if not domain.operator_is_live(episode["board_operator_volunteer_id"]):
                raise ApiError("ERR_OPERATOR_NOT_CERTIFIED")
            episode["air_status"] = "AIRED"
            domain.open_music_log(episode, program)
        elif air_status == "SUBSTITUTE_AIRED":
            if not domain.operator_is_live(substitute["id"]):
                raise ApiError("ERR_OPERATOR_NOT_CERTIFIED")
            episode["air_status"] = "SUBSTITUTE_AIRED"
            episode["board_operator_volunteer_id"] = substitute["id"]
            episode["needs_substitute"] = False
            domain.open_music_log(episode, program)
        else:
            episode["air_status"] = "MISSED"
        touch(episode)
        return response.obj(ser.episode(episode))

    # -------------------------------------------------------------- playlists
    @app.post("/episodes/<episode_id>/playlist-entries")
    def file_playlist_entry(episode_id):
        authenticate(ROLE_VOLUNTEER)
        existing = db.episodes.get(episode_id)
        if existing is not None and existing["board_operator_volunteer_id"] != caller_id():
            raise ApiError("ERR_NOT_BOARD_OPERATOR")
        data = body()
        sequence_number = int_field(data, "sequence_number", 1, None)
        artist = str_field(data, "artist", non_empty=True)
        title = str_field(data, "title", non_empty=True)
        album = str_field(data, "album", required=False, default=None)
        label = str_field(data, "label", required=False, default=None)
        is_local = bool_field(data, "is_local_artist", required=False, default=False)
        is_new = bool_field(data, "is_new_release", required=False, default=False)
        duration_seconds = int_field(data, "duration_seconds", 1, None)
        play_source = enum_field(data, "play_source", calc.PLAY_SOURCES)

        if existing is not None:
            for entry in db.entries.values():
                if entry["episode_id"] == existing["id"] and entry["sequence_number"] == sequence_number:
                    raise ApiError("ERR_DUPLICATE_KEY", "That sequence number is already filed for this airing.")
        episode = lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        if episode["log_status"] != "PENDING":
            raise ApiError("ERR_LOG_NOT_PENDING")

        entry = new_row(db.entries, {
            "episode_id": episode["id"],
            "sequence_number": sequence_number,
            "artist": artist,
            "title": title,
            "album": album,
            "label": label,
            "is_local_artist": is_local,
            "is_new_release": is_new,
            "duration_seconds": duration_seconds,
            "play_source": play_source,
            "royalty_class": calc.royalty_class(play_source, duration_seconds),
        }, versioned=False)
        return response.created(ser.playlist_entry(entry))

    @app.get("/playlist-entries")
    def list_playlist_entries():
        authenticate(*EPISODE_READ_ROLES)
        episode_id = str_query("episode_id")
        royalty_class = str_query("royalty_class")
        is_local = bool_query("is_local_artist")

        def keep(row):
            if episode_id is not None and row["episode_id"] != episode_id:
                return False
            if royalty_class is not None and row["royalty_class"] != royalty_class:
                return False
            if is_local is not None and row["is_local_artist"] is not is_local:
                return False
            return True

        return response.listing(ordered(db.entries, keep), ser.playlist_entry)

    @app.get("/playlist-entries/<entry_id>")
    def get_playlist_entry(entry_id):
        authenticate(*EPISODE_READ_ROLES)
        entry = lookup(db.entries, entry_id, "ERR_PLAYLIST_ENTRY_NOT_FOUND")
        return response.obj(ser.playlist_entry(entry))

    # ------------------------------------------------------------- music logs
    @app.post("/episodes/<episode_id>/submit-log")
    def submit_log(episode_id):
        authenticate(ROLE_VOLUNTEER)
        existing = db.episodes.get(episode_id)
        if existing is not None and existing["board_operator_volunteer_id"] != caller_id():
            raise ApiError("ERR_NOT_BOARD_OPERATOR")
        episode = lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        if episode["log_status"] != "PENDING":
            raise ApiError("ERR_LOG_NOT_PENDING")
        program = db.programs.get(episode["program_id"])
        entries = calc.episode_entries(episode["id"])
        if program is not None and program["format_code"] == "MUSIC" and not entries:
            raise ApiError("ERR_PLAYLIST_EMPTY")

        featured = calc.featured_entries(episode["id"])
        episode["featured_performance_count"] = len(featured)
        episode["local_featured_count"] = sum(1 for e in featured if e["is_local_artist"])
        episode["provisional_royalty_cents"] = calc.survey_royalty_cents(episode["id"])
        episode["log_status"] = "SUBMITTED"
        touch(episode)
        return response.obj(ser.episode(episode))

    @app.post("/episodes/<episode_id>/log-decision")
    def decide_log(episode_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        decision = enum_field(data, "decision", LOG_DECISIONS)
        str_field(data, "review_note", required=False, default=None)
        episode = lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        if episode["log_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a submitted log can be certified or returned.")
        if decision == "CERTIFY":
            episode["log_status"] = "CERTIFIED"
            episode["final_royalty_cents"] = calc.census_royalty_cents(episode["id"])
        else:
            episode["log_status"] = "PENDING"
            episode["provisional_royalty_cents"] = None
        touch(episode)
        return response.obj(ser.episode(episode))
