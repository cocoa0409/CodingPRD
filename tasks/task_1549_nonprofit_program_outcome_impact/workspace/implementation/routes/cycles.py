"""Program cycles: creation, lifecycle state machine, milestones, dashboard."""
from flask import Blueprint, g, request

from db import db, parse_dt, new_entity, now_iso, now_dt
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_datetime,
    req_number,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("cycles", __name__)

CYCLE_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "PrivacyOfficer", "FieldCollector")


def _vendor_scope_for_cycle(cycle_id):
    """VendorAnalyst scoping (SCAFFOLD 1.4 priority 4): engagement must exist,
    be ACTIVE, the current time must be inside [access_start, access_end), and
    the target cycle must be in scope. Any failure -> ERR_SCOPE_DENIED."""
    if g.role != "VendorAnalyst":
        return
    engagement = db.engagements.get(g.user_id)
    if engagement is None:
        raise ApiError("ERR_SCOPE_DENIED", 403, "No vendor engagement matches the caller.")
    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_SCOPE_DENIED", 403, "Vendor engagement is not ACTIVE.")
    now = now_dt()
    if not (parse_dt(engagement["access_start"]) <= now < parse_dt(engagement["access_end"])):
        raise ApiError("ERR_SCOPE_DENIED", 403, "Current time is outside the engagement window.")
    if cycle_id not in engagement["scope_program_cycle_ids"]:
        raise ApiError("ERR_SCOPE_DENIED", 403, "Cycle is outside the engagement scope.")


# ------------------------------------------------------------------ create
@bp.post("/programs/<pid>/cycles")
@require_roles("ProgramDirector")
def create_cycle(pid):
    get_or_404(db.programs, pid)
    body = get_body()
    label = req_str(body, "label")
    enrollment_start = req_datetime(body, "enrollment_start")
    enrollment_end = req_datetime(body, "enrollment_end")
    cycle_start = req_datetime(body, "cycle_start")
    cycle_end = req_datetime(body, "cycle_end")
    reporting_due_date = req_datetime(body, "reporting_due_date")
    # Closed-interval ordering + overlap semantics (PRD 2.6).
    if parse_dt(enrollment_start) > parse_dt(enrollment_end) or parse_dt(
        cycle_start
    ) > parse_dt(cycle_end):
        raise ApiError(
            "ERR_CYCLE_WINDOW_OVERLAP",
            409,
            "enrollment_start must be <= enrollment_end and cycle_start <= cycle_end.",
        )
    s1, e1 = parse_dt(cycle_start), parse_dt(cycle_end)
    for other in db.cycles.values():
        if other["program_id"] != pid:
            continue
        s2, e2 = parse_dt(other["cycle_start"]), parse_dt(other["cycle_end"])
        # Closed intervals: sharing a boundary instant IS an intersection.
        if s1 <= e2 and s2 <= e1:
            raise ApiError(
                "ERR_CYCLE_WINDOW_OVERLAP",
                409,
                "Cycle window intersects an existing cycle of this program.",
            )
    ent = new_entity(
        db.cycles,
        {
            "program_id": pid,
            "label": label,
            "enrollment_start": enrollment_start,
            "enrollment_end": enrollment_end,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "reporting_due_date": reporting_due_date,
            "status": "SETUP",
            "pinned_logic_model_id": None,
            "consent_form_version_snapshot": None,
            "active_participant_count": 0,
            "total_observation_count": 0,
            "validated_observation_count": 0,
            "data_completeness_pct": None,
            "latest_dq_score": None,
        },
    )
    return ok_object(serialize(ent), 201)


# ------------------------------------------------------------------- reads
@bp.get("/programs/<pid>/cycles")
@require_roles(*CYCLE_READ_ROLES)
def list_program_cycles(pid):
    get_or_404(db.programs, pid)
    items = [c for c in db.cycles.values() if c["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/cycles")
@require_roles(*CYCLE_READ_ROLES)
def list_cycles():
    items = list(db.cycles.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    pinned = request.args.get("pinned_logic_model_id")
    if pinned is not None:
        items = [c for c in items if c["pinned_logic_model_id"] == pinned]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/cycles/<cid>")
@require_roles(*CYCLE_READ_ROLES, "VendorAnalyst")
def get_cycle(cid):
    _vendor_scope_for_cycle(cid)
    return ok_object(serialize(get_or_404(db.cycles, cid)))


# --------------------------------------------------------------- lifecycle
def _cycle(cid):
    return get_or_404(db.cycles, cid)


def _bad_state(cycle, to):
    raise ApiError(
        "ERR_INVALID_STATE",
        409,
        f"Cycle in state {cycle['status']} cannot transition to {to}.",
    )


@bp.post("/cycles/<cid>/open-enrollment")
@require_roles("ProgramDirector")
def open_enrollment(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "SETUP":
        _bad_state(cycle, "ENROLLING")
    program = services.program_of_cycle(cycle)
    if program is None or program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Enrollment can open only while the program is ACTIVE."
        )
    cycle["status"] = "ENROLLING"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/revert-setup")
@require_roles("ProgramDirector")
def revert_setup(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "ENROLLING":
        _bad_state(cycle, "SETUP")
    if services.cycle_participants(cid):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "A cycle with participants cannot revert to SETUP."
        )
    cycle["status"] = "SETUP"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/activate")
@require_roles("ProgramDirector")
def activate_cycle(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "ENROLLING":
        _bad_state(cycle, "ACTIVE")
    program = services.program_of_cycle(cycle)
    if program is None or program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Cycle activation requires the program to be ACTIVE."
        )
    if program["current_logic_model_id"] is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Cycle activation requires an APPROVED logic model."
        )
    # Version pinning: immutable thereafter (PRD 3.4).
    cycle["pinned_logic_model_id"] = program["current_logic_model_id"]
    cycle["consent_form_version_snapshot"] = program["current_consent_form_version"]
    cycle["status"] = "ACTIVE"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/close-data")
@require_roles("ProgramDirector")
def close_data(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "ACTIVE":
        _bad_state(cycle, "DATA_CLOSED")
    cycle["status"] = "DATA_CLOSED"
    touch(db.cycles, cycle)
    for p in services.cycle_participants(cid):
        if p["status"] == "ACTIVE":
            p["status"] = "COMPLETED"
            touch(db.participants, p)
    services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/reopen-data")
@require_roles("ProgramDirector")
def reopen_data(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "DATA_CLOSED":
        _bad_state(cycle, "ACTIVE")
    cycle["status"] = "ACTIVE"
    touch(db.cycles, cycle)
    for p in services.cycle_participants(cid):
        if p["status"] == "COMPLETED":
            p["status"] = "ACTIVE"
            touch(db.participants, p)
    services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/begin-review")
@require_roles("ProgramDirector")
def begin_review(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "DATA_CLOSED":
        _bad_state(cycle, "UNDER_REVIEW")
    cycle["status"] = "UNDER_REVIEW"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/mark-reported")
@require_roles("ProgramDirector")
def mark_reported(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "UNDER_REVIEW":
        _bad_state(cycle, "REPORTED")
    open_reports = [
        r
        for r in db.reports.values()
        if r["program_cycle_id"] == cid
        and r["status"] in ("DRAFT", "GENERATED", "DELIVERED", "RETURNED")
    ]
    if open_reports:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Cycle cannot be marked REPORTED while a report is in flight.",
        )
    cycle["status"] = "REPORTED"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


@bp.post("/cycles/<cid>/archive")
@require_roles("ProgramDirector")
def archive_cycle(cid):
    cycle = _cycle(cid)
    if cycle["status"] != "REPORTED":
        _bad_state(cycle, "ARCHIVED")
    cycle["status"] = "ARCHIVED"
    touch(db.cycles, cycle)
    return ok_object(serialize(cycle))


# --------------------------------------------------------------- milestones
@bp.post("/cycles/<cid>/milestones")
@require_roles("EvaluationLead")
def create_milestone(cid):
    cycle = _cycle(cid)
    body = get_body()
    indicator_id = req_str(body, "indicator_id")
    due_date = req_datetime(body, "due_date")
    milestone_target = req_number(body, "milestone_target")
    if cycle["status"] not in ("ACTIVE", "DATA_CLOSED", "UNDER_REVIEW"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Milestones can be defined only on an ACTIVE, DATA_CLOSED, or UNDER_REVIEW cycle.",
        )
    indicator = db.indicators.get(indicator_id)
    if (
        indicator is None
        or indicator["status"] != "ACTIVE"
        or indicator["logic_model_id"] != cycle["pinned_logic_model_id"]
    ):
        raise ApiError(
            "ERR_INDICATOR_NOT_IN_MODEL",
            422,
            "Indicator is not ACTIVE in the cycle's pinned logic model.",
        )
    ent = new_entity(
        db.milestones,
        {
            "program_cycle_id": cid,
            "indicator_id": indicator_id,
            "due_date": due_date,
            "milestone_target": milestone_target,
            "status": "PENDING",
            "evaluated_at": None,
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/cycles/<cid>/milestones")
@require_roles("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")
def list_cycle_milestones(cid):
    _cycle(cid)
    items = [m for m in db.milestones.values() if m["program_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/milestones/<mid>")
@require_roles("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")
def get_milestone(mid):
    return ok_object(serialize(get_or_404(db.milestones, mid)))


@bp.post("/cycles/<cid>/evaluate-milestones")
@require_roles("ProgramDirector")
def evaluate_milestones(cid):
    cycle = _cycle(cid)
    get_body()
    now = now_dt()
    evaluated = met = missed = 0
    pending = sorted(
        (
            m
            for m in db.milestones.values()
            if m["program_cycle_id"] == cid and m["status"] == "PENDING"
        ),
        key=lambda m: m["_seq"],
    )
    for m in pending:
        if parse_dt(m["due_date"]) > now:
            continue  # inclusive boundary: evaluated only when due_date <= now
        indicator = db.indicators.get(m["indicator_id"])
        agg = None
        if indicator is not None:
            agg, _, _, _ = services.indicator_attainment(indicator, cycle, "FINAL")
        target = m["milestone_target"]
        if agg is None:
            m["status"] = "MISSED"
        elif indicator["direction"] == "HIGHER_IS_BETTER":
            m["status"] = "MET" if agg >= target else "MISSED"
        else:
            m["status"] = "MET" if agg <= target else "MISSED"
        m["evaluated_at"] = now_iso()
        touch(db.milestones, m)
        evaluated += 1
        if m["status"] == "MET":
            met += 1
        else:
            missed += 1
    return ok_object(
        {"evaluated_count": evaluated, "met_count": met, "missed_count": missed}
    )


# --------------------------------------------------------------- dashboard
@bp.get("/cycles/<cid>/dashboard")
@require_roles("ProgramDirector", "EvaluationLead", "DataSteward")
def cycle_dashboard(cid):
    cycle = _cycle(cid)
    return ok_object(
        {
            "overall_impact_index": services.overall_impact_index(cycle),
            "data_completeness_pct": services.compute_completeness(cycle),
            "dq_score_standard": services.compute_dq(cycle, "STANDARD"),
            "dq_score_strict": services.compute_dq(cycle, "STRICT"),
        }
    )
