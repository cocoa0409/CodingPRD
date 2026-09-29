"""Employers, placements, retention checkpoints and the ops sweep
(PRD sections 3.7 and 3.8)."""

from flask import Blueprint, request

import calc
import constants as C
import derive
import shapes
from auth import must_exist_filter, must_get, require, require_owner
from errors import fail
from response import created, ok, ok_list, paginate, read_pagination
from serialize import dump, dump_many, jsonable
from store import all_records, create_record, days, set_fields, store

bp = Blueprint("placements", __name__)

PLACEMENT_READ_ROLES = ("ProgramDirector", "CaseManager", "FunderAnalyst", "EmployerPartner")


# =========================================================================== #
# Employer
# =========================================================================== #

@bp.route("/employers", methods=["POST"])
def create_employer():
    require(("ProgramDirector",))
    payload = shapes.body()
    name = shapes.req_string(payload, "organization_name", 1, 120)
    industry = shapes.req_string(payload, "industry_code", 1, 32)
    floor = shapes.req_int(payload, "min_starting_wage_cents_per_hour", C.MIN_EMPLOYER_WAGE_CENTS)
    employer = create_record("employers", {
        "organization_name": name,
        "industry_code": industry,
        "partnership_status": "ACTIVE",
        "min_starting_wage_cents_per_hour": floor,
        "failed_retention_count": 0,
        "confirmed_retention_count": 0,
        "placement_count": 0,
        "retention_reliability_pct": None,
    })
    return created(dump(employer))


@bp.route("/employers/<employer_id>", methods=["GET"])
def read_employer(employer_id):
    require(PLACEMENT_READ_ROLES)
    return ok(dump(must_get("employers", employer_id)))


# =========================================================================== #
# Placement
# =========================================================================== #

@bp.route("/placements", methods=["POST"])
def create_placement():
    require(("CaseManager",))
    payload = shapes.body()
    participant = must_get("participants", payload.get("participant_id"))
    employer = must_get("employers", payload.get("employer_id"))
    hire_date = shapes.req_datetime(payload, "hire_date")
    wage = shapes.req_int(payload, "starting_wage_cents_per_hour", C.MIN_EMPLOYER_WAGE_CENTS)
    # PRD 3.7 declares only the range: "`weekly_hours`, the contracted weekly
    # hours at the outside employer, from 1 through 60." It is absent from every
    # integer list in PRD 2.8, so any number inside the range is accepted.
    weekly_hours = shapes.req_number(
        payload, "weekly_hours", C.MIN_WEEKLY_HOURS, C.MAX_WEEKLY_HOURS
    )
    if participant["status"] != "GRADUATED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a GRADUATED participant may be placed.")
    if participant["graduated_at"] is not None and hire_date < participant["graduated_at"]:
        fail("ERR_HIRE_DATE_BEFORE_GRADUATION", "hire_date may not predate graduated_at.")
    if employer["partnership_status"] != "ACTIVE":
        fail("ERR_EMPLOYER_NOT_ACTIVE", "The employer's partnership_status is not ACTIVE.")
    if wage < employer["min_starting_wage_cents_per_hour"]:
        fail("ERR_WAGE_BELOW_EMPLOYER_FLOOR",
             "starting_wage_cents_per_hour is below the employer's wage floor.")
    floor = calc.wage_progression_floor_cents(participant["graduation_wage_cents_per_hour"])
    if floor is not None and wage < floor:
        fail("ERR_WAGE_PROGRESSION_FLOOR_NOT_MET",
             "starting_wage_cents_per_hour must clear the graduation wage uplifted by ten percent.")
    placement = create_record("placements", {
        "participant_id": participant["id"],
        "employer_id": employer["id"],
        "hire_date": hire_date,
        "starting_wage_cents_per_hour": wage,
        "weekly_hours": weekly_hours,
        "employment_status": "ACTIVE",
        "wage_verification_status": "UNVERIFIED",
        "verified_wage_cents_per_hour": None,
        "retention_outcome": "PENDING",
        "separation_date": None,
        "separation_days_after_hire": None,
        "wage_progression_pct": None,
        "at_risk_flag": False,
    })
    set_fields(participant, status="PLACED")
    for interval in C.RETENTION_INTERVAL_DAYS:
        create_record("retention_checkpoints", {
            "placement_id": placement["id"],
            "interval_days": interval,
            "due_date": hire_date + days(interval),
            "status": "SCHEDULED",
            "still_employed": None,
            "verified_wage_cents_per_hour": None,
            "confirmed_at": None,
        })
    derive.recompute_employer(employer)
    return created(dump(placement))


@bp.route("/placements/<placement_id>", methods=["GET"])
def read_placement(placement_id):
    require(PLACEMENT_READ_ROLES)
    return ok(dump(must_get("placements", placement_id)))


@bp.route("/placements", methods=["GET"])
def list_placements():
    require(("ProgramDirector", "CaseManager", "FunderAnalyst"))
    participant = must_exist_filter("participants", shapes.query_id("participant_id"))
    employer = must_exist_filter("employers", shapes.query_id("employer_id"))
    status = shapes.query_enum("employment_status", C.EMPLOYMENT_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("placements")
    if participant is not None:
        rows = [row for row in rows if row["participant_id"] == participant["id"]]
    if employer is not None:
        rows = [row for row in rows if row["employer_id"] == employer["id"]]
    if status is not None:
        rows = [row for row in rows if row["employment_status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/placements/<id>/retention-checkpoints", methods=["GET"])
def list_retention_checkpoints(id):
    require(PLACEMENT_READ_ROLES)
    placement = must_get("placements", id)
    status = shapes.query_enum("status", C.RETENTION_CHECKPOINT_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = derive.checkpoints_of_placement(placement["id"])
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (row["interval_days"], row["created_at"], row["_seq"]))
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/placements/<placement_id>/wage-verification", methods=["POST"])
def wage_verification(placement_id):
    user_id, role = require(("EmployerPartner", "CaseManager"))
    raw = request.get_json(silent=True)
    action = raw.get("action") if isinstance(raw, dict) else None
    if action == "VERIFY" and role != "EmployerPartner":
        fail("ERR_ROLE_NOT_PERMITTED", "Only an EmployerPartner may attest to a wage.")
    if action == "DISPUTE" and role != "CaseManager":
        fail("ERR_ROLE_NOT_PERMITTED", "Only a CaseManager may dispute a wage.")
    placement = must_get("placements", placement_id)
    if role == "EmployerPartner":
        require_owner(placement["employer_id"], user_id)
    payload = shapes.body()
    action = shapes.req_enum(payload, "action", C.WAGE_VERIFICATION_ACTIONS)
    wage = None
    if action == "VERIFY":
        wage = shapes.req_int(payload, "verified_wage_cents_per_hour", C.MIN_EMPLOYER_WAGE_CENTS)
    current = placement["wage_verification_status"]
    if action == "VERIFY":
        if current not in ("UNVERIFIED", "DISPUTED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A wage may only be attested from UNVERIFIED or DISPUTED.")
        set_fields(placement, wage_verification_status="VERIFIED",
                   verified_wage_cents_per_hour=wage)
        derive.recompute_wage_progression(placement)
    else:
        if current not in ("UNVERIFIED", "VERIFIED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A wage may only be disputed from UNVERIFIED or VERIFIED.")
        set_fields(placement, wage_verification_status="DISPUTED",
                   verified_wage_cents_per_hour=None, wage_progression_pct=None)
    return ok(dump(placement))


@bp.route("/placements/<placement_id>/separate", methods=["POST"])
def separate_placement(placement_id):
    user_id, _role = require(("EmployerPartner",))
    placement = must_get("placements", placement_id)
    require_owner(placement["employer_id"], user_id)
    payload = shapes.body()
    separation_type = shapes.req_enum(payload, "separation_type", C.SEPARATION_TYPES)
    separation_date = shapes.req_datetime(payload, "separation_date")
    if separation_date < placement["hire_date"]:
        fail("ERR_INVALID_REQUEST", "separation_date may not predate hire_date.")
    if separation_date > store.now:
        fail("ERR_INVALID_REQUEST", "separation_date may not be in the future.")
    if placement["employment_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE placement may be separated.")

    # hop 1 -- the placement itself and the checkpoints that lost their purpose.
    elapsed = calc.whole_days_between(placement["hire_date"], separation_date)
    outcome = calc.retention_outcome_for(elapsed)
    set_fields(placement,
               employment_status="SEPARATED_VOLUNTARY" if separation_type == "VOLUNTARY"
               else "SEPARATED_INVOLUNTARY",
               separation_date=separation_date,
               separation_days_after_hire=elapsed,
               retention_outcome=outcome)
    checkpoints = [row for row in derive.checkpoints_of_placement(placement["id"])
                   if row["status"] == "SCHEDULED" and row["due_date"] > separation_date]
    checkpoints.sort(key=lambda row: (row["interval_days"], row["created_at"], row["_seq"]))
    for checkpoint in checkpoints:
        set_fields(checkpoint, status="VOIDED")

    # hops 2, 3 and 4 -- the employer's counters, standing and sibling placements.
    employer = store.employers[placement["employer_id"]]
    derive.recompute_employer(employer)
    derive.apply_employer_thresholds(employer)

    # hop 5 -- an early failure returns the participant to the re-entry pool.
    if outcome == "FAILED_EARLY":
        participant = derive.participant_of(placement)
        if participant["status"] == "PLACED":
            set_fields(participant, status="RE_ENTRY_ELIGIBLE", eligible_re_entry_at=store.now)
    return ok(dump(placement))


# =========================================================================== #
# RetentionCheckpoint
# =========================================================================== #

@bp.route("/retention-checkpoints/<retention_checkpoint_id>/confirm", methods=["POST"])
def confirm_retention_checkpoint(retention_checkpoint_id):
    user_id, _role = require(("EmployerPartner",))
    checkpoint = must_get("retention_checkpoints", retention_checkpoint_id)
    placement = store.placements[checkpoint["placement_id"]]
    require_owner(placement["employer_id"], user_id)
    payload = shapes.body()
    still_employed = shapes.req_bool(payload, "still_employed")
    wage = shapes.opt_int(payload, "verified_wage_cents_per_hour", 0)
    if checkpoint["status"] != "SCHEDULED" or placement["employment_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a SCHEDULED checkpoint of an ACTIVE placement may be confirmed.")
    if store.now < checkpoint["due_date"]:
        fail("ERR_CHECKPOINT_NOT_DUE", "The checkpoint is not due yet.")
    earlier = [row for row in derive.checkpoints_of_placement(placement["id"])
               if row["interval_days"] < checkpoint["interval_days"]]
    if any(row["status"] not in ("CONFIRMED", "VOIDED") for row in earlier):
        fail("ERR_CHECKPOINT_OUT_OF_SEQUENCE",
             "Every earlier checkpoint must be CONFIRMED or VOIDED first.")

    # hop 1 -- the checkpoint answer.
    set_fields(checkpoint,
               status="CONFIRMED",
               confirmed_at=store.now,
               still_employed=still_employed,
               verified_wage_cents_per_hour=wage)

    # hop 2 -- the independent wage dimension, unless a dispute is open.
    if still_employed and placement["wage_verification_status"] != "DISPUTED":
        updates = {"wage_verification_status": "VERIFIED"}
        if wage is not None:
            updates["verified_wage_cents_per_hour"] = wage
        set_fields(placement, **updates)
        derive.recompute_wage_progression(placement)

    # hops 3 and 4 -- the 180-day answer is the retention outcome.
    if checkpoint["interval_days"] == C.LATE_SEPARATION_DAYS:
        set_fields(placement, retention_outcome="RETAINED_180")
        derive.recompute_employer(store.employers[placement["employer_id"]])
        participant = derive.participant_of(placement)
        if participant["status"] == "PLACED":
            set_fields(participant, status="ALUMNI_RETAINED")
    return ok(dump(checkpoint))


# =========================================================================== #
# The ops sweep
# =========================================================================== #

@bp.route("/retention-sweeps", methods=["POST"])
def retention_sweep():
    require(("ProgramDirector",))
    payload = shapes.body()
    line = None
    if payload.get("business_line_id") is not None:
        line = must_get("business_lines", payload.get("business_line_id"))
    scope = line["id"] if line is not None else None

    missed_count = 0
    exited_count = 0
    released_count = 0

    # pass 1 -- overdue checkpoints.
    candidates = []
    for checkpoint in all_records("retention_checkpoints"):
        if checkpoint["status"] != "SCHEDULED":
            continue
        if store.now <= checkpoint["due_date"] + days(C.CHECKPOINT_GRACE_DAYS):
            continue
        placement = store.placements[checkpoint["placement_id"]]
        participant = derive.participant_of(placement)
        if scope is not None and participant["business_line_id"] != scope:
            continue
        candidates.append((checkpoint, placement))
    candidates.sort(key=lambda pair: (pair[0]["due_date"], pair[0]["created_at"], pair[0]["_seq"]))
    for checkpoint, placement in candidates:
        set_fields(checkpoint, status="MISSED")
        set_fields(placement, at_risk_flag=True)
        missed_count += 1

    # pass 2 -- duration-limit exits.
    for participant in all_records("participants"):
        if participant["status"] not in C.SLOT_OCCUPYING_STATUSES:
            continue
        if scope is not None and participant["business_line_id"] != scope:
            continue
        limit = participant["enrolled_at"] + days(participant["max_transitional_weeks"] * 7)
        if store.now <= limit:
            continue
        set_fields(participant, status="EXITED_UNSUCCESSFUL")
        exited_count += 1
        released_count += _release_open_seats(participant)
        derive.recompute_line_posture(store.business_lines[participant["business_line_id"]])

    # pass 3 -- stale re-entry exits.
    for participant in all_records("participants"):
        if participant["status"] != "RE_ENTRY_ELIGIBLE":
            continue
        if scope is not None and participant["business_line_id"] != scope:
            continue
        if participant["eligible_re_entry_at"] is None:
            continue
        if store.now <= participant["eligible_re_entry_at"] + days(C.RE_ENTRY_WINDOW_DAYS):
            continue
        set_fields(participant, status="EXITED_UNSUCCESSFUL")
        exited_count += 1
        derive.recompute_line_posture(store.business_lines[participant["business_line_id"]])

    return ok(jsonable({
        "missed_checkpoint_count": missed_count,
        "exited_participant_count": exited_count,
        "released_assignment_count": released_count,
        "swept_at": store.now,
    }))


def _release_open_seats(participant):
    """Release every ASSIGNED seat of an exiting participant, shift starts_at ASC."""
    rows = [row for row in derive.assignments_of_participant(participant["id"])
            if row["status"] == "ASSIGNED"]
    rows.sort(key=lambda row: (derive.shift_of(row)["starts_at"], row["created_at"], row["_seq"]))
    for assignment in rows:
        derive.release_assignment(assignment, "PARTICIPANT_EXITED")
        derive.recompute_shift_counters(derive.shift_of(assignment))
    if rows:
        derive.recompute_participant_metrics(participant)
    return len(rows)
