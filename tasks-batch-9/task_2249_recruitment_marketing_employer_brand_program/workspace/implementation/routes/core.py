"""Logical clock, programs, job families and channels."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import calc, serialize

bp = Blueprint("core", __name__)

READ_ROLES = ("BrandProgramLead", "PersonaResearcher", "ComplianceReviewer",
              "MediaBuyer", "CommunityManager", "RecruitingOps")
CHANNEL_TYPES = ("JOB_BOARD", "SOCIAL", "PROGRAMMATIC", "CAREER_SITE", "EVENT", "EMAIL")
PACING_STATUSES = ("PACING_UNKNOWN", "ON_TARGET", "THROTTLED", "IDLE")
ATTRIBUTION_MODELS = ("LINEAR", "POSITION_BASED")


# ------------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("RecruitingOps")
def set_current_utc():
    data = V.body()
    instant = V.field(data, "current_utc", "datetime", required=True)
    db.set_clock(instant)
    # PRD 2.4 - moving the clock "re-evaluates `sla_status` on every
    # `EmployerReview` ... and it recomputes the brand health score of every
    # `Program`".  Program.brand_health_score is derived from the clock and the
    # stored reviews on every read, so re-evaluating the verdicts is sufficient.
    for review in db.reviews.values():
        calc.reevaluate_sla(review)
    return response.ok({})


# ----------------------------------------------------------------- programs
@bp.route("/programs", methods=["POST"])
@require("BrandProgramLead")
def create_program():
    data = V.body()
    row = {
        "id": db.new_id(),
        "name": V.field(data, "name", "string", required=True, min_len=1, max_len=160),
        "fiscal_year": V.field(data, "fiscal_year", "integer", required=True,
                               min_value=2000, max_value=2100),
        "attribution_model": V.field(data, "attribution_model", "enum",
                                     default="LINEAR", values=ATTRIBUTION_MODELS),
        "pool_job_board_cents": V.field(data, "pool_job_board_cents", "integer",
                                        default=0, min_value=0),
        "pool_social_cents": V.field(data, "pool_social_cents", "integer",
                                     default=0, min_value=0),
        "pool_programmatic_cents": V.field(data, "pool_programmatic_cents", "integer",
                                           default=0, min_value=0),
        "flex_reserve_cents": V.field(data, "flex_reserve_cents", "integer",
                                      default=0, min_value=0),
        "send_quota_total": V.field(data, "send_quota_total", "integer",
                                    default=0, min_value=0),
        "last_attribution_recompute_at": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.programs[row["id"]] = row
    return response.ok(serialize.program(row), 201)


@bp.route("/programs/<program_id>", methods=["PATCH"])
@require("BrandProgramLead")
def patch_program(program_id):
    data = V.body()
    edits = {
        "attribution_model": V.field(data, "attribution_model", "enum",
                                     default=V.MISSING, values=ATTRIBUTION_MODELS),
        "pool_job_board_cents": V.field(data, "pool_job_board_cents", "integer",
                                        default=V.MISSING, min_value=0),
        "pool_social_cents": V.field(data, "pool_social_cents", "integer",
                                     default=V.MISSING, min_value=0),
        "pool_programmatic_cents": V.field(data, "pool_programmatic_cents", "integer",
                                           default=V.MISSING, min_value=0),
        "flex_reserve_cents": V.field(data, "flex_reserve_cents", "integer",
                                      default=V.MISSING, min_value=0),
        "send_quota_total": V.field(data, "send_quota_total", "integer",
                                    default=V.MISSING, min_value=0),
    }
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for key, value in edits.items():
        if value is not V.MISSING:
            program[key] = value
    db.touch(program)
    return response.ok(serialize.program(program))


@bp.route("/programs/<program_id>", methods=["GET"])
@require(*READ_ROLES)
def get_program(program_id):
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return response.ok(serialize.program(program))


@bp.route("/programs", methods=["GET"])
@require(*READ_ROLES)
def list_programs():
    limit, offset = V.pagination()
    rows = calc.by_created(db.programs.values())
    fiscal_year = V.qs_int("fiscal_year")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.program(r) for r in page], meta)


# -------------------------------------------------------------- job families
@bp.route("/job-families", methods=["POST"])
@require("BrandProgramLead")
def create_job_family():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    name = V.field(data, "name", "string", required=True, min_len=1, max_len=120)
    code = V.field(data, "code", "string", required=True, min_len=2, max_len=12)
    if code != code.upper():
        V.bad_request("Field 'code' must be uppercase.")
    cpqa_target_cents = V.field(data, "cpqa_target_cents", "integer",
                                required=True, min_value=1)
    dedicated_budget_cents = V.field(data, "dedicated_budget_cents", "integer",
                                     default=0, min_value=0)
    priority_rank = V.field(data, "priority_rank", "integer", required=True, min_value=1)

    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for existing in db.job_families.values():
        if existing["program_id"] == program["id"] and existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_FAMILY_CODE",
                           "Code %s already exists in this program." % code)
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "name": name,
        "code": code,
        "cpqa_target_cents": cpqa_target_cents,
        "dedicated_budget_cents": dedicated_budget_cents,
        "priority_rank": priority_rank,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.job_families[row["id"]] = row
    return response.ok(serialize.job_family(row), 201)


@bp.route("/job-families/<family_id>", methods=["GET"])
@require(*READ_ROLES)
def get_job_family(family_id):
    family = calc.must_get(db.job_families, family_id, "ERR_JOB_FAMILY_NOT_FOUND")
    return response.ok(serialize.job_family(family))


@bp.route("/job-families", methods=["GET"])
@require(*READ_ROLES)
def list_job_families():
    limit, offset = V.pagination()
    rows = sorted(db.job_families.values(),
                  key=lambda r: (r["priority_rank"], r["created_at"]))
    program_id = V.qs("program_id")
    if program_id:
        rows = [r for r in rows if r["program_id"] == program_id]
    code = V.qs("code")
    if code:
        rows = [r for r in rows if r["code"] == code]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.job_family(r) for r in page], meta)


# ------------------------------------------------------------------ channels
@bp.route("/channels", methods=["POST"])
@require("BrandProgramLead")
def create_channel():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    name = V.field(data, "name", "string", required=True, min_len=1, max_len=120)
    channel_type = V.field(data, "channel_type", "enum", required=True,
                           values=CHANNEL_TYPES)
    daily_capacity_cents = V.field(data, "daily_capacity_cents", "integer",
                                   default=0, min_value=0)
    min_flight_days = V.field(data, "min_flight_days", "integer",
                              default=1, min_value=1)
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "name": name,
        "channel_type": channel_type,
        "daily_capacity_cents": daily_capacity_cents,
        "min_flight_days": min_flight_days,
        "blended_target_cents": None,
        "cpqa_cents": None,
        "pacing_status": "PACING_UNKNOWN",
        "idle_since": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.channels[row["id"]] = row
    return response.ok(serialize.channel(row), 201)


@bp.route("/channels/<channel_id>", methods=["GET"])
@require(*READ_ROLES)
def get_channel(channel_id):
    channel = calc.must_get(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    return response.ok(serialize.channel(channel))


@bp.route("/channels", methods=["GET"])
@require(*READ_ROLES)
def list_channels():
    limit, offset = V.pagination()
    rows = calc.by_created(db.channels.values())
    program_id = V.qs("program_id")
    if program_id:
        rows = [r for r in rows if r["program_id"] == program_id]
    channel_type = V.qs("channel_type")
    if channel_type:
        rows = [r for r in rows if r["channel_type"] == channel_type]
    pacing_status = V.qs("pacing_status")
    if pacing_status:
        rows = [r for r in rows if r["pacing_status"] == pacing_status]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.channel(r) for r in page], meta)
