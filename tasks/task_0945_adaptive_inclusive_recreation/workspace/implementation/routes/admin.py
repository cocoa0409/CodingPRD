"""Clock, operating periods, fee-scale bands, activity programmes and sessions."""

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import Body, check_transition, endpoint, pagination, paginate, resolve_one
from envelope import ok, ok_list
from errors import ApiError
from store import date_of_instant, db, insert, parse_date, parse_instant, sort_rows, touch

bp = Blueprint("admin", __name__)

PERIOD_EDGES = {
    "RESTRICTED": ("OPEN",),
    "OPEN": ("RESTRICTED", "FROZEN", "CLOSING"),
    "FROZEN": ("OPEN", "RESTRICTED"),
    "CLOSING": ("OPEN",),
    "CLOSED": ("CLOSING",),
}
SESSION_TERMINALS = ("DELIVERED", "CANCELLED")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.route("/recreation/_clock/set_current_utc", methods=["POST"])
@endpoint(roles=("ProgramAdmin",), gate_exempt=True)
def set_clock(context):
    body = Body(context.body)
    to_iso8601 = body.req_instant("to_iso8601")
    body.check_enums()
    counters = engine.set_logical_clock(to_iso8601)
    data = {"current_utc": db.clock_raw}
    data.update(counters)
    return ok(data)


# ---------------------------------------------------------------------------
# operating periods
# ---------------------------------------------------------------------------

@bp.route("/recreation/operating-periods", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_period(context):
    body = Body(context.body)
    name = body.req_string("name")
    starts_on = body.req_date("starts_on")
    ends_on = body.req_date("ends_on")
    body.check_enums()
    if parse_date(ends_on) < parse_date(starts_on):
        raise ApiError("ERR_VALIDATION", "ends_on must be on or after starts_on.")
    row = insert(
        "operating_periods",
        {"name": name, "starts_on": starts_on, "ends_on": ends_on, "status": "OPEN"},
    )
    return ok(serial.dump(row), 201)


@bp.route("/recreation/operating-periods/<period_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_period(context, period_id):
    return ok(serial.dump(resolve_one("period", period_id)))


@bp.route("/recreation/operating-periods/<period_id>/posture", methods=["POST"])
@endpoint(roles=("ProgramAdmin",), gate_exempt=True)
def move_period_posture(context, period_id):
    period = resolve_one("period", period_id)
    body = Body(context.body)
    target = body.req_enum("target_status", enums.PERIOD_STATUSES)
    body.check_enums()
    check_transition(period["status"], PERIOD_EDGES.get(target, ()), ("CLOSED",))
    if target == "CLOSED":
        engine.close_period(period)
    else:
        period["status"] = target
        touch(period)
    return ok(serial.dump(period))


# ---------------------------------------------------------------------------
# fee-scale bands
# ---------------------------------------------------------------------------

@bp.route("/recreation/fee-scale-bands", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_fee_band(context):
    body = Body(context.body)
    minimum = body.req_int("household_size_min", minimum=1)
    maximum = body.req_int("household_size_max", minimum=1)
    income_band = body.req_enum("income_band", enums.INCOME_BANDS)
    per_session_cents = body.req_int("per_session_cents", minimum=0)
    series_cents = body.req_int("series_cents", minimum=0)
    body.check_enums()
    if maximum < minimum:
        raise ApiError("ERR_VALIDATION", "household_size_max must be >= household_size_min.")
    row = insert(
        "fee_scale_bands",
        {
            "household_size_min": minimum,
            "household_size_max": maximum,
            "income_band": income_band,
            "per_session_cents": per_session_cents,
            "series_cents": series_cents,
        },
    )
    return ok(serial.dump(row), 201)


@bp.route("/recreation/fee-scale-bands/<band_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_fee_band(context, band_id):
    return ok(serial.dump(resolve_one("band", band_id)))


# ---------------------------------------------------------------------------
# activity programmes
# ---------------------------------------------------------------------------

@bp.route("/recreation/activity-programs", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_program(context):
    body = Body(context.body)
    fields = {
        "name": body.req_string("name"),
        "activity_type": body.req_enum("activity_type", enums.ACTIVITY_TYPES),
        "risk_tier": body.req_enum("risk_tier", enums.RISK_TIERS),
        "pricing_mode": body.req_enum("pricing_mode", enums.PRICING_MODES),
        "rounding_policy": body.req_enum("rounding_policy", enums.ROUNDING_POLICIES),
        "waitlist_policy": body.req_enum("waitlist_policy", enums.WAITLIST_POLICIES),
        "fee_multiplier_bp": body.req_int("fee_multiplier_bp", minimum=0),
        "scheduled_session_count": body.req_int("scheduled_session_count", minimum=1),
        "required_consent_types": body.opt_enum_list(
            "required_consent_types", enums.CONSENT_TYPES, []
        ),
        "required_certification_types": body.opt_enum_list(
            "required_certification_types", enums.CERTIFICATION_TYPES, []
        ),
        "requires_medication_admin": body.opt_bool("requires_medication_admin", False),
        "required_equipment_model_code": body.opt_string("required_equipment_model_code", None),
        "required_equipment_size_code": body.opt_string("required_equipment_size_code", None),
        "session_count_created": 0,
    }
    body.check_enums()
    return ok(serial.dump(insert("activity_programs", fields)), 201)


@bp.route("/recreation/activity-programs/<program_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_program(context, program_id):
    return ok(serial.dump(resolve_one("program", program_id)))


# ---------------------------------------------------------------------------
# program sessions
# ---------------------------------------------------------------------------

@bp.route("/recreation/program-sessions", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_session(context):
    program_id = context.body.get("program_id")
    program = None
    if isinstance(program_id, str):
        program = resolve_one("program", program_id)
    body = Body(context.body)
    body.req_string("program_id")
    start_at = body.req_instant("start_at")
    end_at = body.req_instant("end_at")
    slot_capacity = body.req_int("slot_capacity", minimum=0)
    one_to_one_pool_size = body.req_int("one_to_one_pool_size", minimum=0)
    body.check_enums()
    if parse_instant(end_at) <= parse_instant(start_at):
        raise ApiError("ERR_VALIDATION", "end_at must be strictly later than start_at.")
    if program is None:
        program = resolve_one("program", program_id)

    row = insert(
        "program_sessions",
        {
            "program_id": program["id"],
            "sequence_number": program["session_count_created"] + 1,
            "start_at": start_at,
            "end_at": end_at,
            "slot_capacity": slot_capacity,
            "slots_committed": 0,
            "slots_available": slot_capacity,
            "one_to_one_pool_size": one_to_one_pool_size,
            "one_to_one_committed": 0,
            "one_to_one_available": one_to_one_pool_size,
            "one_to_one_staffed": 0,
            "assigned_group_staff_count": 0,
            "required_group_staff_planned": 0,
            "required_group_staff_delivered": None,
            "staffing_gap": 0,
            "unlock_count": 0,
            "status": "DRAFT",
        },
    )
    program["session_count_created"] += 1
    touch(program)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/program-sessions", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_sessions(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("program_sessions"))
    program_id = context.q("program_id")
    status = context.q("status")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/program-sessions/<session_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES)
def read_session(context, session_id):
    return ok(serial.dump(resolve_one("session", session_id)))


@bp.route("/recreation/program-sessions/<session_id>/staffing-summary", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def staffing_summary(context, session_id):
    session = resolve_one("session", session_id)
    return ok(
        {
            "session_id": session["id"],
            "pooled_support_points": calc.pooled_support_points(session, "CONFIRMED"),
            "required_group_staff_planned": session["required_group_staff_planned"],
            "required_group_staff_delivered": session["required_group_staff_delivered"],
            "assigned_group_staff_count": session["assigned_group_staff_count"],
            "one_to_one_committed": session["one_to_one_committed"],
            "one_to_one_staffed": session["one_to_one_staffed"],
            "staffing_gap": session["staffing_gap"],
        }
    )


@bp.route("/recreation/program-sessions/<session_id>/open", methods=["POST"])
@endpoint(roles=("ActivityLead", "ProgramAdmin"))
def open_session(context, session_id):
    session = resolve_one("session", session_id)
    check_transition(session["status"], ("DRAFT",), SESSION_TERMINALS)
    if parse_instant(session["start_at"]) <= db.clock_dt:
        raise ApiError("ERR_INVALID_STATE", "The session's start_at is not in the future.")
    session["status"] = "OPEN"
    engine.refresh_session_counters(session)
    return ok(serial.dump(session))


@bp.route("/recreation/program-sessions/<session_id>/lock-staffing", methods=["POST"])
@endpoint(roles=("ActivityLead",))
def lock_staffing(context, session_id):
    session = resolve_one("session", session_id)
    check_transition(session["status"], ("OPEN",), SESSION_TERMINALS)
    program = L.program_of_session(session)
    session_date = date_of_instant(session["start_at"])
    live = [a for a in L.assignments_of_session(session) if a["status"] in ("PROPOSED", "CONFIRMED")]

    # rung 38 -- medication-administration coverage
    if program.get("requires_medication_admin"):
        covered = False
        for assignment in live:
            for certification in L.certifications_of_staff(assignment["staff_member_id"]):
                if certification["certification_type"] != "MEDICATION_ADMIN":
                    continue
                expires = parse_date(certification["expires_on"])
                if expires is not None and expires >= session_date:
                    covered = True
                    break
            if covered:
                break
        if not covered:
            raise ApiError("ERR_MED_ADMIN_COVERAGE_MISSING")

    # rung 39 then rung 41
    verdicts = {}
    for assignment in live:
        has_all, unexpired = calc.staff_certification_verdict(
            assignment["staff_member_id"], program, session_date
        )
        verdicts[assignment["id"]] = (has_all, unexpired)
    for assignment in live:
        if not verdicts[assignment["id"]][0]:
            raise ApiError("ERR_STAFF_CERT_MISSING")
    for assignment in live:
        if not verdicts[assignment["id"]][1]:
            raise ApiError("ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION")

    # rung 47
    if engine.peek_staffing_gap(session) != 0:
        raise ApiError("ERR_STAFFING_GAP")

    for assignment in live:
        if assignment["qualified_at_session_date"] is not True:
            assignment["qualified_at_session_date"] = True
            touch(assignment)
        if assignment["status"] == "PROPOSED":
            assignment["status"] = "CONFIRMED"
            touch(assignment)
    session["status"] = "STAFFING_LOCKED"
    engine.refresh_session_counters(session)
    return ok(serial.dump(session))


@bp.route("/recreation/program-sessions/<session_id>/unlock-staffing", methods=["POST"])
@endpoint(roles=("ActivityLead",))
def unlock_staffing(context, session_id):
    session = resolve_one("session", session_id)
    check_transition(session["status"], ("STAFFING_LOCKED",), SESSION_TERMINALS)
    if session["unlock_count"] >= calc.MAX_SESSION_UNLOCKS:
        raise ApiError("ERR_UNLOCK_LIMIT_REACHED")
    session["status"] = "OPEN"
    session["unlock_count"] += 1
    engine.refresh_session_counters(session)
    return ok(serial.dump(session))


def _deliver_session_ref(context):
    return db.get("program_sessions", context.params.get("session_id"))


@bp.route("/recreation/program-sessions/<session_id>/deliver", methods=["POST"])
@endpoint(roles=("ActivityLead",), delivery=_deliver_session_ref)
def deliver(context, session_id):
    session = resolve_one("session", session_id)
    check_transition(session["status"], ("STAFFING_LOCKED",), SESSION_TERMINALS)
    if db.clock_dt < parse_instant(session["end_at"]):
        raise ApiError("ERR_INVALID_STATE", "The session has not finished yet.")
    engine.deliver_session(session)
    return ok(serial.dump(session))


@bp.route("/recreation/program-sessions/<session_id>/cancel", methods=["POST"])
@endpoint(roles=("ActivityLead", "ProgramAdmin"))
def cancel(context, session_id):
    session = resolve_one("session", session_id)
    check_transition(session["status"], ("DRAFT", "OPEN", "STAFFING_LOCKED"), SESSION_TERMINALS)
    engine.cancel_session(session)
    return ok(serial.dump(session))
