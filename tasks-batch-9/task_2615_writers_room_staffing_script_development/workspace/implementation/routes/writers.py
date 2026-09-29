"""Writer registry, credit awards and availability windows (PRD 3.1)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, SHOWRUNNER, STUDIO_EXECUTIVE, WRITER,
                        LEGAL_COUNSEL, fetch, require)
from response import created, ok
from routes.common import date_range, list_out, match, out
from services import calc
from validation import (body_json, filter_bool, filter_value, raw, v_bool, v_dt,
                        v_enum, v_int, v_str)

bp = Blueprint("writers", __name__)

READ_ROLES = (GUILD_ADMINISTRATOR, STUDIO_EXECUTIVE, SHOWRUNNER, LEGAL_COUNSEL, WRITER)
WINDOW_READ_ROLES = (GUILD_ADMINISTRATOR, STUDIO_EXECUTIVE, SHOWRUNNER, WRITER)


def _body_agreement(body):
    """Step 6: a supplied agreement_id must resolve before the schema check."""
    reference = raw(body, "agreement_id")
    if reference is None:
        return None
    return fetch(db.agreements, reference, "ERR_AGREEMENT_NOT_FOUND")


@bp.post("/writers")
def create_writer():
    require(GUILD_ADMINISTRATOR)
    body = body_json()
    agreement = _body_agreement(body)
    row = base_row()
    row["legal_name"] = v_str(body, "legal_name", 1, 200)
    row["guild_member_id"] = v_str(body, "guild_member_id", 1, 40)
    if agreement is None:
        raise ApiError("ERR_INVALID_REQUEST")
    row["career_episodic_credits"] = v_int(
        body, "career_episodic_credits", lo=0, required=False, default=0)
    row["diversity_program_participant"] = v_bool(
        body, "diversity_program_participant", required=False, default=False)
    row["is_showrunner_eligible"] = v_bool(
        body, "is_showrunner_eligible", required=False, default=False)
    for existing in db.writers.values():
        if existing["guild_member_id"] == row["guild_member_id"]:
            raise ApiError("ERR_DUPLICATE_GUILD_MEMBER_ID")
    row["determined_level"] = calc.determine_level(agreement, row["career_episodic_credits"])
    row["level_determination_agreement_id"] = agreement["id"]
    row["active_seat_count"] = 0
    row["on_screen_credit_count"] = 0
    db.writers[row["id"]] = row
    return created(out(row))


@bp.post("/writers/<writer_id>/credit-history")
def award_credits(writer_id):
    require(GUILD_ADMINISTRATOR)
    writer = fetch(db.writers, writer_id, "ERR_WRITER_NOT_FOUND")
    body = body_json()
    agreement = _body_agreement(body)
    awarded = v_int(body, "episodic_credits_awarded", lo=1)
    if agreement is None:
        raise ApiError("ERR_INVALID_REQUEST")
    writer["career_episodic_credits"] += awarded
    writer["determined_level"] = calc.determine_level(
        agreement, writer["career_episodic_credits"])
    writer["level_determination_agreement_id"] = agreement["id"]
    touch(writer)
    return ok(out(writer))


@bp.get("/writers/<writer_id>")
def get_writer(writer_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.writers, writer_id, "ERR_WRITER_NOT_FOUND")))


@bp.get("/writers")
def list_writers():
    require(*READ_ROLES)
    rows = list(db.writers.values())
    rows = match(rows, "determined_level", filter_value("determined_level"))
    rows = match(rows, "diversity_program_participant",
                 filter_bool("diversity_program_participant"))
    return list_out(rows)


@bp.post("/writers/<writer_id>/availability-windows")
def create_window(writer_id):
    require(WRITER, GUILD_ADMINISTRATOR)
    writer = fetch(db.writers, writer_id, "ERR_WRITER_NOT_FOUND")
    body = body_json()
    row = base_row()
    start = v_dt(body, "start_date")
    end = v_dt(body, "end_date")
    row["commitment_type"] = v_enum(body, "commitment_type", calc.COMMITMENT_TYPES)
    date_range(start, end)
    row["writer_id"] = writer["id"]
    row["start_date"] = start
    row["end_date"] = end
    row["status"] = "OPEN"
    row["consumed_by_seat_id"] = None
    db.windows[row["id"]] = row
    return created(out(row))


@bp.get("/availability-windows/<window_id>")
def get_window(window_id):
    require(*WINDOW_READ_ROLES)
    return ok(out(fetch(db.windows, window_id, "ERR_WINDOW_NOT_FOUND")))


@bp.get("/availability-windows")
def list_windows():
    require(*WINDOW_READ_ROLES)
    rows = list(db.windows.values())
    rows = match(rows, "writer_id", filter_value("writer_id"))
    rows = match(rows, "consumed_by_seat_id", filter_value("consumed_by_seat_id"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)
