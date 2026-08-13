"""ProgramCycle endpoints: CRUD, lifecycle transitions, waitlist promotion, close cascade."""

from flask import request, Blueprint

import db
import util
from util import D, is_multiple_quarter
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("program_cycles", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]


def _get_cycle_or_404(cycle_id):
    cycle = db.program_cycles.get(cycle_id)
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "ProgramCycle not found")
    return cycle


def _validate_cycle_config(body, partial=False):
    """Schema (priority 3) validation for cycle config fields."""
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")

    def req_field(name):
        if not partial and name not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return body.get(name)

    out = {}
    if not partial or "year_label" in body:
        v = req_field("year_label")
        if not isinstance(v, str) or not v:
            raise_err("ERR_INVALID_REQUEST", "year_label must be a string")
        out["year_label"] = v
    if not partial or "start_date" in body:
        v = req_field("start_date")
        if not isinstance(v, str) or not util.is_iso_date(v):
            raise_err("ERR_INVALID_REQUEST", "start_date must be an ISO 8601 date")
        out["start_date"] = v
    if not partial or "end_date" in body:
        v = req_field("end_date")
        if not isinstance(v, str) or not util.is_iso_date(v):
            raise_err("ERR_INVALID_REQUEST", "end_date must be an ISO 8601 date")
        out["end_date"] = v
    if "start_date" in out and "end_date" in out:
        if util.parse_date(out["end_date"]) < util.parse_date(out["start_date"]):
            raise_err("ERR_INVALID_FIELD_VALUE", "end_date must be >= start_date")
    if not partial or "admission_capacity" in body:
        v = req_field("admission_capacity")
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "admission_capacity must be an integer")
        if v < 1:
            raise_err("ERR_INVALID_FIELD_VALUE", "admission_capacity must be >= 1")
        out["admission_capacity"] = v
    if not partial or "hour_requirement" in body:
        v = req_field("hour_requirement")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "hour_requirement must be a number")
        d = D(v)
        if d <= 0 or not is_multiple_quarter(d):
            raise_err("ERR_INVALID_FIELD_VALUE", "hour_requirement must be a positive multiple of 0.25")
        out["hour_requirement"] = float(d)
    if not partial or "ce_requirement" in body:
        v = req_field("ce_requirement")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "ce_requirement must be a number")
        d = D(v)
        if d < 0 or not is_multiple_quarter(d):
            raise_err("ERR_INVALID_FIELD_VALUE", "ce_requirement must be a multiple of 0.25 >= 0")
        out["ce_requirement"] = float(d)
    if not partial or "training_module_count" in body:
        v = req_field("training_module_count")
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "training_module_count must be an integer")
        if v < 1:
            raise_err("ERR_INVALID_FIELD_VALUE", "training_module_count must be >= 1")
        out["training_module_count"] = v
    if not partial or "training_pass_quiz_average" in body:
        v = req_field("training_pass_quiz_average")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "training_pass_quiz_average must be a number")
        if D(v) < 0 or D(v) > 100:
            raise_err("ERR_INVALID_FIELD_VALUE", "training_pass_quiz_average must be 0..100")
        out["training_pass_quiz_average"] = float(D(v))
    if not partial or "training_capacity" in body:
        v = req_field("training_capacity")
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "training_capacity must be an integer")
        if v < 1:
            raise_err("ERR_INVALID_FIELD_VALUE", "training_capacity must be >= 1")
        out["training_capacity"] = v
    if not partial or "recert_opens_at" in body:
        v = req_field("recert_opens_at")
        if not isinstance(v, str) or not util.is_iso_datetime(v):
            raise_err("ERR_INVALID_REQUEST", "recert_opens_at must be an ISO 8601 datetime")
        out["recert_opens_at"] = v
    if not partial or "priority_counties" in body:
        v = body.get("priority_counties", [])
        if v is None:
            v = []
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise_err("ERR_INVALID_REQUEST", "priority_counties must be a list of strings")
        out["priority_counties"] = v
    return out


@bp.route("/program-cycles", methods=["POST"])
def create_cycle():
    auth_context(PC)
    body = request.get_json(silent=True)
    fields = _validate_cycle_config(body or {}, partial=False)
    cycle = util.new_resource({
        **fields,
        "priority_counties": fields.get("priority_counties", []),
        "accepted_count": 0,
        "enrolled_count": 0,
        "status": "DRAFT",
    })
    db.program_cycles[cycle["id"]] = cycle
    return success_object(cycle, 201)


@bp.route("/program-cycles", methods=["GET"])
def list_cycles():
    auth_context(ALL_ROLES)
    items = list(db.program_cycles.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/program-cycles/<cycleId>", methods=["GET"])
def get_cycle(cycleId):
    auth_context(ALL_ROLES)
    return success_object(_get_cycle_or_404(cycleId))


@bp.route("/program-cycles/<cycleId>", methods=["PUT"])
def update_cycle(cycleId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "expected_cycle_version" not in body:
        raise_err("ERR_INVALID_REQUEST", "expected_cycle_version is required")
    if not isinstance(body["expected_cycle_version"], int) or isinstance(body["expected_cycle_version"], bool):
        raise_err("ERR_INVALID_REQUEST", "expected_cycle_version must be an integer")
    # Validate supplied editable fields (schema tier) before existence/state tiers
    partial_fields = {k: body[k] for k in
                      ("admission_capacity", "hour_requirement", "ce_requirement",
                       "training_capacity", "recert_opens_at", "priority_counties")
                      if k in body}
    if partial_fields:
        # schema check on the subset (types/ranges)
        probe = {}
        for k, v in partial_fields.items():
            probe[k] = v
        # reuse validators by treating as partial
        if "admission_capacity" in probe:
            v = probe["admission_capacity"]
            if not isinstance(v, int) or isinstance(v, bool):
                raise_err("ERR_INVALID_REQUEST", "admission_capacity must be an integer")
            if v < 1:
                raise_err("ERR_INVALID_FIELD_VALUE", "admission_capacity must be >= 1")
        for k in ("hour_requirement", "ce_requirement"):
            if k in probe:
                v = probe[k]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise_err("ERR_INVALID_REQUEST", f"{k} must be a number")
                d = D(v)
                if k == "hour_requirement":
                    if d <= 0 or not is_multiple_quarter(d):
                        raise_err("ERR_INVALID_FIELD_VALUE", "hour_requirement must be a positive multiple of 0.25")
                else:
                    if d < 0 or not is_multiple_quarter(d):
                        raise_err("ERR_INVALID_FIELD_VALUE", "ce_requirement must be a multiple of 0.25 >= 0")
        if "training_capacity" in probe:
            v = probe["training_capacity"]
            if not isinstance(v, int) or isinstance(v, bool):
                raise_err("ERR_INVALID_REQUEST", "training_capacity must be an integer")
            if v < 1:
                raise_err("ERR_INVALID_FIELD_VALUE", "training_capacity must be >= 1")
        if "recert_opens_at" in probe:
            v = probe["recert_opens_at"]
            if not isinstance(v, str) or not util.is_iso_datetime(v):
                raise_err("ERR_INVALID_REQUEST", "recert_opens_at must be an ISO 8601 datetime")
        if "priority_counties" in probe:
            v = probe["priority_counties"]
            if v is None:
                v = []
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise_err("ERR_INVALID_REQUEST", "priority_counties must be a list of strings")
            probe["priority_counties"] = v

    cycle = _get_cycle_or_404(cycleId)
    # OCC (priority 6)
    if body["expected_cycle_version"] != cycle["version"]:
        raise_err("ERR_STALE_CYCLE_VERSION", "expected_cycle_version does not match the cycle's current version")
    # posture (priority 7)
    if cycle["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_CYCLE_NOT_EDITABLE", "Cycle configuration may only be edited while DRAFT or OPEN")
    for k, v in partial_fields.items():
        cycle[k] = v
    util.touch(cycle)
    return success_object(cycle)


@bp.route("/program-cycles/<cycleId>/open", methods=["POST"])
def open_cycle(cycleId):
    auth_context(PC)
    cycle = _get_cycle_or_404(cycleId)
    if cycle["status"] != "DRAFT":
        raise_err("ERR_INVALID_CYCLE_STATE", "Cycle must be DRAFT to open")
    cycle["status"] = "OPEN"
    util.touch(cycle)
    # Provision PENDING RecertificationRecords for ACTIVE volunteers lacking one
    for vol in list(db.volunteers.values()):
        if vol["status"] == "ACTIVE":
            if calc.record_for(vol["id"], cycle["id"]) is None:
                calc.provision_record(vol["id"], cycle["id"])
    return success_object(cycle)


@bp.route("/program-cycles/<cycleId>/begin-recertification", methods=["POST"])
def begin_recertification(cycleId):
    auth_context(PC)
    cycle = _get_cycle_or_404(cycleId)
    if cycle["status"] != "OPEN":
        raise_err("ERR_INVALID_CYCLE_STATE", "Cycle must be OPEN to begin recertification")
    clock = util.logical_clock()
    recert_opens = util.parse_dt(cycle["recert_opens_at"])
    if clock < recert_opens:
        raise_err("ERR_RECERT_WINDOW_NOT_OPEN", "Logical clock is before recert_opens_at")
    cycle["status"] = "RECERTIFICATION"
    util.touch(cycle)
    return success_object(cycle)


@bp.route("/program-cycles/<cycleId>/close", methods=["POST"])
def close_cycle(cycleId):
    auth_context(PC)
    cycle = _get_cycle_or_404(cycleId)
    if cycle["status"] != "RECERTIFICATION":
        raise_err("ERR_INVALID_CYCLE_STATE", "Cycle must be RECERTIFICATION to close")
    cycle["status"] = "CLOSED"
    util.touch(cycle)

    # Link 1: finalize every PENDING record in this cycle, volunteer created_at ASC
    records = [r for r in db.recertification_records.values()
               if r["cycle_id"] == cycle["id"] and r["status"] == "PENDING"]
    records.sort(key=lambda r: (
        db.volunteers[r["volunteer_id"]]["created_at"] if r["volunteer_id"] in db.volunteers else ""))
    finalized = []
    for rec in records:
        calc.recompute_record(rec)
        off_s = D(rec["official_service_hours"])
        off_c = D(rec["official_ce_hours"])
        eff_h = D(rec["effective_hour_requirement"])
        eff_c = D(rec["effective_ce_requirement"])
        outcome = "RECERTIFIED" if (off_s >= eff_h and off_c >= eff_c) else "SHORTFALL"
        rec["status"] = outcome
        rec["finalized_at"] = util.logical_clock_iso()
        util.touch(rec)
        finalized.append((rec, outcome))

    # Link 2: volunteer consequences
    deactivated = []
    for rec, outcome in finalized:
        vol = db.volunteers.get(rec["volunteer_id"])
        if vol is None:
            continue
        if outcome == "RECERTIFIED":
            if vol["status"] == "ACTIVE":
                vol["consecutive_shortfall_cycles"] = 0
                util.touch(vol)
        else:  # SHORTFALL
            if vol["status"] == "ACTIVE":
                vol["status"] = "INACTIVE"
                vol["consecutive_shortfall_cycles"] += 1
                util.touch(vol)
                deactivated.append(vol)
                if vol["consecutive_shortfall_cycles"] >= 2:
                    vol["status"] = "EXITED"
                    util.touch(vol)

    # Link 3: deactivation cascade for each deactivated volunteer
    for vol in deactivated:
        calc.deactivation_cascade(vol)

    # Recognition recompute for volunteers with finalized records in this cycle
    for rec, _ in finalized:
        vol = db.volunteers.get(rec["volunteer_id"])
        if vol is not None:
            calc.recompute_recognition(vol)

    return success_object(cycle)


@bp.route("/program-cycles/<cycleId>/promote-waitlisted", methods=["POST"])
def promote_waitlisted(cycleId):
    auth_context(PC)
    cycle = _get_cycle_or_404(cycleId)
    if cycle["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS",
                  "Cycle must be DRAFT or OPEN for waitlist promotion")
    # seat check precedes candidate evaluation
    if cycle["accepted_count"] >= cycle["admission_capacity"]:
        raise_err("ERR_NO_SEATS_AVAILABLE", "No seats available in this cycle")
    candidates = [a for a in db.applications.values()
                  if a["cycle_id"] == cycle["id"] and a["status"] == "WAITLISTED"]
    if not candidates:
        raise_err("ERR_WAITLIST_EMPTY", "No WAITLISTED applications for this cycle")
    candidates.sort(key=lambda a: (-D(a["composite_score"] or 0), a["created_at"]))
    app = candidates[0]
    _accept_application(app, cycle)
    return success_object(app)


def _accept_application(app, cycle):
    """Shared side effects of acceptance: seat, counter, Volunteer creation."""
    app["status"] = "ACCEPTED"
    app["decided_at"] = util.logical_clock_iso()
    util.touch(app)
    cycle["accepted_count"] += 1
    util.touch(cycle)
    volunteer = util.new_resource({
        "application_id": app["id"],
        "full_name": app["applicant_name"],
        "email": app["email"],
        "status": "TRAINEE",
        "consecutive_shortfall_cycles": 0,
        "no_show_strikes": 0,
        "lifetime_base_hours": 0.0,
        "recognition_tier": "BRONZE",
        "recognition_points": 0.0,
    })
    db.volunteers[volunteer["id"]] = volunteer
    return volunteer
