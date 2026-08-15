"""CallProgram lifecycle: create/list/get, generate, regenerate (OCC), publish,
reconcile, fairness-report, coverage-report."""
from datetime import timedelta

from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, created, paginate
from services import domain as D

bp = Blueprint("programs", __name__)

ADMIN = ["SchedulerAdmin"]
ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]

_COUNT_FIELDS = [
    "weekday_primary_required", "weekend_primary_required", "holiday_primary_required",
    "weekday_backup_required", "weekend_backup_required", "holiday_backup_required",
]


def get_program_or_404(program_id):
    program = store.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", 404, "CallProgram id does not exist")
    return program


@bp.route("/api/call-programs", methods=["POST"])
def create_program():
    require_roles(ADMIN)
    body = V.json_body()
    # --- shape (priority 4) ---
    name = V.req_str(body, "name")
    service_line = V.req_str(body, "service_line")
    period_start = V.req_date(body, "period_start")
    period_end = V.req_date(body, "period_end")
    payroll_budget_cents = V.req_int(body, "payroll_budget_cents")

    holiday_dates = body.get("holiday_dates")
    if holiday_dates is None:
        holiday_dates = []
    if not isinstance(holiday_dates, list):
        V._bad("holiday_dates must be an array of ISO date strings")
    for h in holiday_dates:
        V.parse_date_str(h, "holiday_dates")

    config = {}
    for f in _COUNT_FIELDS:
        config[f] = V.opt_int(body, f, 1 if "primary" in f else 0)
    for f in _COUNT_FIELDS:
        if config[f] < 0:
            V._bad("%s must be >= 0" % f)
    if all(config[f] == 0 for f in _COUNT_FIELDS):
        V._bad("At least one of the six required slot counts must be > 0")
    if D.parse_date(period_end) < D.parse_date(period_start):
        V._bad("period_end must be >= period_start")
    if payroll_budget_cents <= 0:
        V._bad("payroll_budget_cents must be > 0")

    program = db.new_common({
        "name": name,
        "service_line": service_line,
        "period_start": period_start,
        "period_end": period_end,
        "holiday_dates": list(holiday_dates),
        **config,
        "swap_cutoff_hours": V.opt_int(body, "swap_cutoff_hours", 48),
        "credentialing_lead_hours": V.opt_int(body, "credentialing_lead_hours", 120),
        "equity_band_points": V.opt_num(body, "equity_band_points", D.Decimal("4.0")),
        "payroll_budget_cents": payroll_budget_cents,
        "primary_rate_cents": V.opt_int(body, "primary_rate_cents", 50000),
        "backup_rate_cents": V.opt_int(body, "backup_rate_cents", 20000),
        "weekend_multiplier": V.opt_num(body, "weekend_multiplier", D.Decimal("1.25")),
        "holiday_multiplier": V.opt_num(body, "holiday_multiplier", D.Decimal("1.5")),
        "backup_activation_multiplier": V.opt_num(body, "backup_activation_multiplier", D.Decimal("2.0")),
        "moonlight_premium_multiplier": V.opt_num(body, "moonlight_premium_multiplier", D.Decimal("1.15")),
        "moonlight_premium_threshold_hours": V.opt_int(body, "moonlight_premium_threshold_hours", 40),
        "weekday_call_points": V.opt_num(body, "weekday_call_points", D.Decimal("1.0")),
        "weekend_call_points": V.opt_num(body, "weekend_call_points", D.Decimal("2.0")),
        "holiday_call_points": V.opt_num(body, "holiday_call_points", D.Decimal("3.0")),
        "backup_point_multiplier": V.opt_num(body, "backup_point_multiplier", D.Decimal("0.5")),
        "payroll_reserved_cents": 0,
        "payroll_accrued_cents": 0,
        "status": "DRAFT",
    })
    store.programs[program["id"]] = program
    return created(program)


@bp.route("/api/call-programs", methods=["GET"])
def list_programs():
    require_roles(ALL)
    rows = list(store.programs.values())
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "service_line")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/call-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_roles(ALL)
    return ok(get_program_or_404(program_id))


@bp.route("/api/call-programs/<program_id>/generate", methods=["POST"])
def generate(program_id):
    require_roles(ADMIN)
    V.json_body()
    program = get_program_or_404(program_id)
    if program["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_DRAFT", 409, "generate requires the program in DRAFT")
    slots = D.generate_slots(program)
    D.rotation_auto_assignment(program, slots)
    D.sync_program_totals(program)
    program["status"] = "GENERATED"
    db.touch(program)
    return ok(program)


@bp.route("/api/call-programs/<program_id>/regenerate", methods=["POST"])
def regenerate(program_id):
    require_roles(ADMIN)
    body = V.json_body()
    expected = V.req_int(body, "expected_call_program_version")
    program = get_program_or_404(program_id)
    if program["status"] != "GENERATED":
        raise ApiError("ERR_PROGRAM_NOT_GENERATED", 409,
                       "regenerate requires the program in GENERATED")
    for a in D.assignments_of_program(program["id"]):
        if a["status"] in ("ACTIVATED", "SERVED"):
            raise ApiError("ERR_REGENERATE_HAS_PROGRESS", 409,
                           "regenerate blocked: an assignment is ACTIVATED or SERVED")
    # OCC (priority 7): expected_call_program_version must equal current version.
    if expected != program["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_call_program_version does not match the program's current version")
    # Full replacement: wipe the program's slots, assignments, and coverage gaps.
    for coll, key in ((store.slots, "program_id"), (store.assignments, "program_id"),
                      (store.gaps, "program_id")):
        for rid in [r["id"] for r in coll.values() if r.get("program_id") == program["id"]]:
            del coll[rid]
    slots = D.generate_slots(program)
    D.rotation_auto_assignment(program, slots)
    D.sync_program_totals(program)
    db.touch(program)
    return ok(program)


@bp.route("/api/call-programs/<program_id>/publish", methods=["POST"])
def publish(program_id):
    require_roles(ADMIN)
    V.json_body()
    program = get_program_or_404(program_id)
    if program["status"] != "GENERATED":
        raise ApiError("ERR_PROGRAM_NOT_GENERATED", 409,
                       "publish requires the program in GENERATED")
    program["status"] = "PUBLISHED"
    db.touch(program)
    return ok(program)


@bp.route("/api/call-programs/<program_id>/reconcile", methods=["POST"])
def reconcile(program_id):
    require_roles(ADMIN)
    V.json_body()
    program = get_program_or_404(program_id)
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED", 409,
                       "reconcile requires the program in PUBLISHED")
    for a in D.assignments_of_program(program["id"]):
        if a["status"] not in ("SERVED", "SWAPPED", "CANCELLED"):
            raise ApiError("ERR_UNRESOLVED_ASSIGNMENTS_EXIST", 409,
                           "reconcile requires every assignment terminal (SERVED/SWAPPED/CANCELLED)")
    period_close = D.window_start_of(program["period_end"]) - timedelta(hours=7) \
        + timedelta(days=1)  # (period_end + 1 day)T00:00:00Z
    if db.now_logical() < period_close:
        raise ApiError("ERR_PERIOD_NOT_ENDED", 409,
                       "reconcile requires now >= (period_end + 1 day)T00:00:00Z")
    for p in store.pay_entries.values():
        if p["program_id"] == program["id"] and p["status"] == "ACCRUED":
            p["status"] = "FINALIZED"
            db.touch(p)
    for s in D.slots_of_program(program["id"]):
        if s["status"] == "OPEN":
            s["status"] = "UNCOVERED"
            db.touch(s)
    program["status"] = "RECONCILED"
    D.sync_program_totals(program)
    db.touch(program)
    return ok(program)


@bp.route("/api/call-programs/<program_id>/fairness-report", methods=["GET"])
def fairness(program_id):
    require_roles(ALL)
    program = get_program_or_404(program_id)
    return ok(D.fairness_report(program))


@bp.route("/api/call-programs/<program_id>/coverage-report", methods=["GET"])
def coverage(program_id):
    require_roles(ALL)
    program = get_program_or_404(program_id)
    return ok(D.coverage_report(program))
