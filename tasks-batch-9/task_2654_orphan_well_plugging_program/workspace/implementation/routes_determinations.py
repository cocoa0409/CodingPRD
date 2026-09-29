"""Orphan determination authoring, submission and decision (PRD 3.3)."""
from flask import Blueprint

import calc
import validate as v
from auth import (DETERMINATION_REVIEWER, FIELD_INSPECTOR, PROGRAM_ADMIN,
                  endpoint, sod, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import collect, get_determination, get_well
from store import clock, db, new_row, touch

bp = Blueprint("determinations", __name__)

DETERMINATION_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "CONFIRMED",
                          "REJECTED", "SUPERSEDED")
DECISION_ACTIONS = ("CONFIRM", "REJECT", "REQUEST_REVISION")
MAX_REVISION_ROUNDS = 2
OPEN_STATUSES = ("DRAFT", "REVISION_REQUESTED")
TROUBLED_OPERATOR_STATUSES = ("DELINQUENT", "INSOLVENT", "REVOKED")

READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def _promote_candidate(well):
    """Well PRODUCING|INACTIVE -> ORPHAN_CANDIDATE with score recomputation."""
    well["status"] = "ORPHAN_CANDIDATE"
    calc.recompute_scores(well)
    touch(well)
    calc.recompute_operator(db.operators.get(well["operator_id"]))


@bp.route("/wells/<well_id>/orphan-determinations", methods=["POST"])
@endpoint((FIELD_INSPECTOR, PROGRAM_ADMIN), needs_user_id=True)
def create_determination(well_id):
    well = get_well(well_id)
    data = v.body()
    notes = v.str_field(data, "inspector_notes")
    expected = v.int_field(data, "expected_well_version")

    if expected != well["version"]:
        raise ApiError(
            "ERR_STALE_WELL_VERSION",
            "expected_well_version %s does not match the well's current version "
            "%s." % (expected, well["version"]),
        )

    row = new_row()
    row.update({
        "well_id": well_id,
        "inspector_notes": notes,
        "status": "DRAFT",
        "revision_round": 0,
        "created_by_user_id": user_id(),
        "decided_by_user_id": None,
        "snapshot_idle_months": None,
        "snapshot_cumulative_boe_60mo": None,
        "snapshot_screening_score": None,
        "decision_rationale": None,
        "submitted_at": None,
        "decided_at": None,
    })

    for other in sorted(db.determinations.values(), key=lambda d: d["_seq"]):
        if other["well_id"] != well_id:
            continue
        if other["status"] in OPEN_STATUSES:
            other["status"] = "SUPERSEDED"
            touch(other)

    db.determinations[row["id"]] = row

    calc.recompute_criteria(well)
    if (well["status"] == "PRODUCING"
            and well["idle_months"] >= calc.IDLE_MONTHS_INACTIVE):
        well["status"] = "INACTIVE"
        calc.recompute_criteria(well)
        calc.recompute_scores(well)
    touch(well)

    return object_response(row, 201)


@bp.route("/orphan-determinations/<determination_id>", methods=["GET"])
@endpoint(READERS)
def fetch_determination(determination_id):
    return object_response(get_determination(determination_id))


@bp.route("/wells/<well_id>/orphan-determinations", methods=["GET"])
@endpoint(READERS)
def list_determinations(well_id):
    get_well(well_id)
    status = filter_value("status")

    def keep(row):
        if row["well_id"] != well_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.determinations, keep))


@bp.route("/orphan-determinations/<determination_id>/submit", methods=["POST"])
@endpoint((FIELD_INSPECTOR, PROGRAM_ADMIN), needs_user_id=True)
def submit_determination(determination_id):
    determination = get_determination(determination_id)
    data = v.body()
    notes = v.str_field(data, "inspector_notes", required=False)

    if determination["status"] not in OPEN_STATUSES:
        raise bad_transition(
            "A determination in %s cannot be submitted." % determination["status"]
        )
    if determination["created_by_user_id"] != user_id():
        raise bad_transition(
            "Only the authoring inspector may submit this determination."
        )

    resubmission = determination["status"] == "REVISION_REQUESTED"
    if resubmission and determination["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError(
            "ERR_REVISION_LIMIT_EXCEEDED",
            "This determination has already used its %d revision cycles."
            % MAX_REVISION_ROUNDS,
        )

    well = get_well(determination["well_id"])

    if notes is not None:
        determination["inspector_notes"] = notes
    if resubmission:
        determination["revision_round"] += 1
    determination["status"] = "SUBMITTED"
    determination["submitted_at"] = clock()
    determination["snapshot_idle_months"] = well["idle_months"]
    determination["snapshot_cumulative_boe_60mo"] = well["cumulative_boe_60mo"]
    determination["snapshot_screening_score"] = well["screening_score"]
    touch(determination)

    if well["status"] in ("PRODUCING", "INACTIVE"):
        _promote_candidate(well)

    return object_response(determination)


@bp.route("/orphan-determinations/<determination_id>/decision", methods=["POST"])
@endpoint((DETERMINATION_REVIEWER,), needs_user_id=True)
def decide_determination(determination_id):
    determination = get_determination(determination_id)

    # Step 4: segregation of duties precedes schema validation.
    if determination["created_by_user_id"] == user_id():
        raise sod("A reviewer may not decide a determination it authored.")

    data = v.body()
    action = v.enum_field(data, "action", DECISION_ACTIONS)
    rationale = v.str_field(data, "rationale")

    if determination["status"] != "SUBMITTED":
        raise bad_transition(
            "A determination in %s cannot be decided." % determination["status"]
        )

    well = get_well(determination["well_id"])
    operator = db.operators.get(well["operator_id"])

    if action == "CONFIRM":
        if operator is None or operator["status"] not in TROUBLED_OPERATOR_STATUSES:
            raise bad_transition(
                "Confirmation requires the owning operator to be DELINQUENT, "
                "INSOLVENT or REVOKED."
            )
        live_idle = calc.compute_idle_months(well)
        live_boe = calc.compute_cumulative_boe(well)
        candidate = dict(well)
        candidate["idle_months"] = live_idle
        candidate["cumulative_boe_60mo"] = live_boe
        if not calc.criteria_met(candidate):
            raise ApiError(
                "ERR_ORPHAN_CRITERIA_NOT_MET",
                "The well does not satisfy the statutory orphan criteria.",
            )
        well["idle_months"] = live_idle
        well["cumulative_boe_60mo"] = live_boe
    elif action == "REQUEST_REVISION":
        if determination["revision_round"] >= MAX_REVISION_ROUNDS:
            raise ApiError(
                "ERR_REVISION_LIMIT_EXCEEDED",
                "A revision may be requested at most %d times."
                % MAX_REVISION_ROUNDS,
            )

    determination["decision_rationale"] = rationale
    determination["decided_by_user_id"] = user_id()
    determination["decided_at"] = clock()

    if action == "REQUEST_REVISION":
        determination["status"] = "REVISION_REQUESTED"
        touch(determination)
        return object_response(determination)

    determination["snapshot_idle_months"] = well["idle_months"]
    determination["snapshot_cumulative_boe_60mo"] = well["cumulative_boe_60mo"]
    determination["snapshot_screening_score"] = well["screening_score"]

    if action == "CONFIRM":
        determination["status"] = "CONFIRMED"
        if well["status"] == "ORPHAN_CANDIDATE":
            well["status"] = "ORPHAN_CONFIRMED"
            well["orphan_confirmed_at"] = clock()
            well["remediation_score"] = calc.remediation_score(well)
            touch(well)
            calc.recompute_operator(operator)
    else:
        determination["status"] = "REJECTED"
        if well["status"] == "ORPHAN_CANDIDATE":
            well["status"] = "INACTIVE"
            touch(well)
            calc.recompute_operator(operator)

    touch(determination)
    return object_response(determination)
