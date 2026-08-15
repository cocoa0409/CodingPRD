"""Study lifecycle (PRD §3.2) and the correlation computed read (§3.6)."""
import math
from datetime import timedelta

import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STUDY_STATE,
    ERR_NO_ARMS_DEFINED, ERR_NO_CONTROL_ARM, ERR_NO_TIME_POINTS,
    ERR_OPEN_TIME_POINTS_REMAIN, ERR_SESSIONS_STILL_OPEN,
    ERR_INSUFFICIENT_RETAINER_HOURS, ERR_STALE_STUDY_VERSION,
    ERR_INSUFFICIENT_CORRELATION_PAIRS,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    arms_of_study, tps_of_study, sessions_of_study, ser_study,
    cancel_session, discard_unit, supersede_recommendation,
    consumed_hours_for,
    BASE_RESERVE_HOURS, PER_TIME_POINT_HOURS, PER_ARM_HOURS, STUDY_TYPES,
    TEST_TYPES, ATTRIBUTES,
)
from util import (
    body, opt_int, opt_num, paginate, req_dt, req_enum, req_int, req_num,
    req_str, round_half_up, sort_created, touch,
)

bp = Blueprint("studies", __name__)


def get_study(study_id):
    s = db.store["studies"].get(study_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    return s


def _check_accelerated(study_type, storage_temp_c, reference_temp_c,
                       q10_factor):
    if study_type == "ACCELERATED":
        if not (q10_factor > 1.0):
            raise_err(ERR_INVALID_REQUEST,
                      "ACCELERATED study requires q10_factor > 1.0")
        if not (storage_temp_c > reference_temp_c):
            raise_err(ERR_INVALID_REQUEST,
                      "ACCELERATED study requires storage_temp_c > "
                      "reference_temp_c")


@bp.route("/studies", methods=["POST"])
@require_roles("SensoryScientist")
def create_study():
    b = body()
    client_id = req_str(b, "client_id")
    product_name = req_str(b, "product_name")
    study_type = req_enum(b, "study_type", STUDY_TYPES)
    storage_temp_c = req_num(b, "storage_temp_c")
    target_shelf_life_days = req_int(b, "target_shelf_life_days")
    sensory_fail_threshold = req_num(b, "sensory_fail_threshold")
    min_detectable_difference = req_num(b, "min_detectable_difference")
    planned_start_utc = req_dt(b, "planned_start_utc")
    reference_temp_c = opt_num(b, "reference_temp_c", default=20)
    q10_factor = opt_num(b, "q10_factor", default=2.0)
    _check_accelerated(study_type, storage_temp_c, reference_temp_c,
                       q10_factor)
    client = db.store["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"ClientAccount {client_id} not found")
    now = clock.now()
    study = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "client_id": client_id,
        "product_name": product_name,
        "study_type": study_type,
        "storage_temp_c": storage_temp_c,
        "reference_temp_c": reference_temp_c,
        "q10_factor": q10_factor,
        "target_shelf_life_days": target_shelf_life_days,
        "sensory_fail_threshold": sensory_fail_threshold,
        "min_detectable_difference": min_detectable_difference,
        "planned_start_utc": planned_start_utc,
        "actual_start_utc": None,
        "reserved_hours_escrow": 0,
        "consumed_hours": 0,
        "earliest_failure_day_equiv": None,
        "status": "DRAFT",
        "_reopened": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["studies"][study["id"]] = study
    return respond(ser_study(study), 201)


@bp.route("/studies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_studies():
    items = sort_created(db.store["studies"].values())
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if client_id is not None:
        items = [s for s in items if s["client_id"] == client_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate(items)
    return respond_list([ser_study(s) for s in page], pagination)


@bp.route("/studies/<study_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_study(study_id):
    return respond(ser_study(get_study(study_id)), 200)


@bp.route("/studies/<study_id>", methods=["PUT"])
@require_roles("SensoryScientist")
def update_study(study_id):
    study = get_study(study_id)
    b = body()
    # OCC guard (PRD §2.6 rung 4) — after existence, before state.
    if "expected_study_version" not in b or b["expected_study_version"] is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Missing required field: expected_study_version")
    expected = b["expected_study_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_study_version must be an integer")
    if expected != study["version"]:
        raise_err(
            ERR_STALE_STUDY_VERSION,
            f"expected_study_version {expected} does not match current "
            f"version {study['version']}",
        )
    if study["status"] != "DRAFT":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "Study design fields may only be updated in DRAFT")
    product_name = b.get("product_name")
    if product_name is not None and not isinstance(product_name, str):
        raise_err(ERR_INVALID_REQUEST, "product_name must be a string")
    storage_temp_c = opt_num(b, "storage_temp_c")
    reference_temp_c = opt_num(b, "reference_temp_c")
    q10_factor = opt_num(b, "q10_factor")
    target = opt_int(b, "target_shelf_life_days")
    threshold = opt_num(b, "sensory_fail_threshold")
    mdd = opt_num(b, "min_detectable_difference")
    planned = None
    if b.get("planned_start_utc") is not None:
        from util import parse_datetime
        planned = parse_datetime(b["planned_start_utc"], "planned_start_utc")
    new_storage = storage_temp_c if storage_temp_c is not None \
        else study["storage_temp_c"]
    new_reference = reference_temp_c if reference_temp_c is not None \
        else study["reference_temp_c"]
    new_q10 = q10_factor if q10_factor is not None else study["q10_factor"]
    _check_accelerated(study["study_type"], new_storage, new_reference,
                       new_q10)
    if product_name is not None:
        study["product_name"] = product_name
    if storage_temp_c is not None:
        study["storage_temp_c"] = storage_temp_c
    if reference_temp_c is not None:
        study["reference_temp_c"] = reference_temp_c
    if q10_factor is not None:
        study["q10_factor"] = q10_factor
    if target is not None:
        study["target_shelf_life_days"] = target
    if threshold is not None:
        study["sensory_fail_threshold"] = threshold
    if mdd is not None:
        study["min_detectable_difference"] = mdd
    if planned is not None:
        study["planned_start_utc"] = planned
    touch(study)
    return respond(ser_study(study), 200)


def _transition(study, to):
    study["status"] = to
    touch(study)


@bp.route("/studies/<study_id>/submit-design", methods=["POST"])
@require_roles("SensoryScientist")
def submit_design(study_id):
    study = get_study(study_id)
    if study["status"] != "DRAFT":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "submit-design requires status DRAFT")
    arms = arms_of_study(study_id)
    if not arms:
        raise_err(ERR_NO_ARMS_DEFINED,
                  "submit-design requires at least one study arm")
    controls = [a for a in arms if a["is_control"]]
    if len(controls) != 1:
        raise_err(ERR_NO_CONTROL_ARM,
                  "submit-design requires exactly one control arm")
    if not tps_of_study(study_id):
        raise_err(ERR_NO_TIME_POINTS,
                  "submit-design requires at least one sampling time point")
    _transition(study, "DESIGN_REVIEW")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/approve-design", methods=["POST"])
@require_roles("LabDirector")
def approve_design(study_id):
    study = get_study(study_id)
    if study["status"] != "DESIGN_REVIEW":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "approve-design requires status DESIGN_REVIEW")
    _transition(study, "SCHEDULED")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/reject-design", methods=["POST"])
@require_roles("LabDirector")
def reject_design(study_id):
    study = get_study(study_id)
    if study["status"] != "DESIGN_REVIEW":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "reject-design requires status DESIGN_REVIEW")
    _transition(study, "DRAFT")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/activate", methods=["POST"])
@require_roles("SensoryScientist")
def activate_study(study_id):
    study = get_study(study_id)
    if study["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "activate requires status SCHEDULED")
    # Fiscal sufficiency is checked LAST (PRD §2.6 rung 10).
    required = (BASE_RESERVE_HOURS
                + PER_TIME_POINT_HOURS * len(tps_of_study(study_id))
                + PER_ARM_HOURS * len(arms_of_study(study_id)))
    client = db.store["clients"][study["client_id"]]
    if client["retainer_hours_balance"] < required:
        raise_err(ERR_INSUFFICIENT_RETAINER_HOURS,
                  "client retainer_hours_balance is below the reserved "
                  "hours required")
    client["retainer_hours_balance"] -= required
    touch(client)
    study["actual_start_utc"] = clock.now()
    study["reserved_hours_escrow"] = required
    _transition(study, "IN_PROGRESS")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/close-fieldwork", methods=["POST"])
@require_roles("SensoryScientist")
def close_fieldwork(study_id):
    study = get_study(study_id)
    if study["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "close-fieldwork requires status IN_PROGRESS")
    for tp in tps_of_study(study_id):
        if tp["status"] in ("PENDING", "PULLED"):
            raise_err(ERR_OPEN_TIME_POINTS_REMAIN,
                      "a sampling time point is still PENDING or PULLED")
    for sess in sessions_of_study(study_id):
        if sess["status"] in ("PLANNED", "OPEN", "LOCKED"):
            raise_err(ERR_SESSIONS_STILL_OPEN,
                      "an evaluation session is still PLANNED, OPEN or LOCKED")
    _transition(study, "ANALYSIS")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/reopen-fieldwork", methods=["POST"])
@require_roles("SensoryScientist")
def reopen_fieldwork(study_id):
    study = get_study(study_id)
    if study["status"] != "ANALYSIS":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "reopen-fieldwork requires status ANALYSIS")
    study["_reopened"] = True
    _transition(study, "IN_PROGRESS")
    return respond(ser_study(study), 200)


@bp.route("/studies/<study_id>/abort", methods=["POST"])
@require_roles("LabDirector")
def abort_study(study_id):
    study = get_study(study_id)
    if study["status"] not in ("DRAFT", "DESIGN_REVIEW", "SCHEDULED",
                               "IN_PROGRESS"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "abort is permitted only from DRAFT, DESIGN_REVIEW, "
                  "SCHEDULED or IN_PROGRESS")
    client = db.store["clients"][study["client_id"]]
    if study["reserved_hours_escrow"]:
        client["retainer_hours_balance"] += study["reserved_hours_escrow"]
        study["reserved_hours_escrow"] = 0
        touch(client)
    for sess in sessions_of_study(study_id):
        if sess["status"] in ("PLANNED", "OPEN"):
            cancel_session(sess)
    for unit in db.store["sample_units"].values():
        if unit["study_id"] == study_id:
            discard_unit(unit)
    for rec in db.store["recommendations"].values():
        if rec["study_id"] == study_id:
            supersede_recommendation(rec)
    _transition(study, "ABORTED")
    return respond(ser_study(study), 200)


def complete_study(study):
    """REPORTING -> COMPLETED closing trio (PRD §3.7): retention window,
    retainer settlement, active-count exit (derived)."""
    now = clock.now()
    retention_until = now + timedelta(days=90)
    for unit in db.store["sample_units"].values():
        if (unit["study_id"] == study["id"]
                and unit["unit_purpose"] == "RETAIN"
                and unit["status"] in ("STORED", "CHECKED_OUT")):
            unit["retention_until_utc"] = retention_until
            touch(unit)
    consumed = consumed_hours_for(study)
    client = db.store["clients"][study["client_id"]]
    client["retainer_hours_balance"] += (
        study["reserved_hours_escrow"] - consumed)
    touch(client)
    study["consumed_hours"] = consumed
    study["reserved_hours_escrow"] = 0
    study["status"] = "COMPLETED"
    touch(study)


@bp.route("/studies/<study_id>/correlation", methods=["GET"])
@require_roles("SensoryScientist", "LabDirector", "QAOfficer")
def correlation(study_id):
    get_study(study_id)
    arm_id = request.args.get("arm_id")
    test_type = request.args.get("test_type")
    attribute = request.args.get("attribute")
    if not arm_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required parameter: arm_id")
    if not test_type:
        raise_err(ERR_INVALID_REQUEST, "Missing required parameter: test_type")
    if not attribute:
        raise_err(ERR_INVALID_REQUEST, "Missing required parameter: attribute")
    if test_type not in TEST_TYPES:
        raise_err(ERR_INVALID_REQUEST, f"test_type must be one of "
                                       f"{sorted(TEST_TYPES)}")
    if attribute not in ATTRIBUTES:
        raise_err(ERR_INVALID_REQUEST, f"attribute must be one of "
                                       f"{sorted(ATTRIBUTES)}")
    arm = db.store["arms"].get(arm_id)
    if arm is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    # Pair per sampling time point of this study where both sides exist
    # for the arm (PRD §3.6 micro_sensory_correlation).
    lab_by_tp = {}
    for lr in sort_created(db.store["lab_results"].values()):
        if (lr["study_id"] == study_id and lr["arm_id"] == arm_id
                and lr["test_type"] == test_type):
            lab_by_tp.setdefault(lr["time_point_id"], lr["measured_value"])
    mean_by_tp = {}
    for sess in sessions_of_study(study_id):
        if (sess["arm_id"] == arm_id and sess["status"] == "ANALYZED"
                and sess["overall_mean"] is not None):
            mean_by_tp[sess["time_point_id"]] = sess["overall_mean"]
    pairs = []
    for tp in tps_of_study(study_id):
        if tp["id"] in lab_by_tp and tp["id"] in mean_by_tp:
            pairs.append((lab_by_tp[tp["id"]], mean_by_tp[tp["id"]]))
    if len(pairs) < 3:
        raise_err(ERR_INSUFFICIENT_CORRELATION_PAIRS,
                  "fewer than 3 paired time points for the requested "
                  "correlation")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    n = len(pairs)
    mx = sum(xs) / n
    my = sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxy = sum(a * b for a, b in zip(dx, dy))
    sxx = sum(a * a for a in dx)
    syy = sum(b * b for b in dy)
    denom = math.sqrt(sxx * syy)
    r = 0.0 if denom == 0 else sxy / denom
    return respond({
        "coefficient": round_half_up(r, 4),
        "pair_count": n,
        "arm_id": arm_id,
        "test_type": test_type,
        "attribute": attribute,
    }, 200)
