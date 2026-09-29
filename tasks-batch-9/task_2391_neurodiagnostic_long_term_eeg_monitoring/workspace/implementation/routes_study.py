"""Video-EEG acquisition: segments, electrode maintenance and data residency."""
import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import ListResult, ObjectResult, bp, endpoint, get_admission, get_shift, get_study

STUDY_READ_ROLES = ("UnitCoordinator", "Technologist", "Nurse", "Epileptologist")


def _new_report(study):
    report = base_record("report")
    report.update({
        "study_id": study["id"],
        "status": "PRELIM_DRAFT",
        "localization": None,
        "prelim_issued_at": None,
        "final_issued_at": None,
        "prelim_author_user_id": None,
        "final_author_user_id": None,
        "turnaround_calendar_hours": None,
        "turnaround_coverage_hours": None,
        "sla_breached": False,
        "addendum_count": 0,
        "addendum_reason": None,
    })
    insert("reports", report)
    return report


def _close_open_segment(study):
    started_at = study.get("current_segment_started_at")
    if started_at is None:
        return
    now = clock.now()
    minutes = derive.floor_int(derive.minutes_between(started_at, now))
    study.setdefault("_segments", []).append({
        "started_at": started_at,
        "ended_at": now,
        "minutes": minutes,
        "_seq": db.next_seq(),
    })
    study["current_segment_started_at"] = None


@bp.route("/neurodiagnostics/studies", methods=["POST"])
@endpoint(roles=("Technologist",), mutating=True)
def create_study(user_id, role):
    data = validation.body()
    admission_id = validation.req_id(data, "admission_id")
    channel_count = validation.req_int(data, "channel_count", minimum=8)
    modality = validation.req_enum(data, "modality", config.SETTINGS)
    get_admission(admission_id)
    study = base_record("study")
    study.update({
        "admission_id": admission_id,
        "shift_id": None,
        "channel_count": channel_count,
        "modality": modality,
        "acquisition_state": "PREPARING",
        "data_state": "ONLINE",
        "current_segment_started_at": None,
        "completed_at": None,
        "last_impedance_kohm": None,
        "impedance_fail_count": 0,
        "export_hold_reason": None,
        "_segments": [],
    })
    insert("studies", study)
    return ObjectResult(study, 201)


@bp.route("/neurodiagnostics/studies", methods=["GET"])
@endpoint(roles=STUDY_READ_ROLES)
def list_studies(user_id, role):
    from flask import request
    args = request.args
    limit, offset = response.read_pagination(args)
    admission_id = validation.query_string(args, "admission_id")
    shift_id = validation.query_string(args, "shift_id")
    acquisition_state = validation.query_enum(args, "acquisition_state",
                                              config.ACQUISITION_STATES)
    data_state = validation.query_enum(args, "data_state", config.DATA_STATES)
    records = []
    for study in db.studies.values():
        if admission_id and study["admission_id"] != admission_id:
            continue
        if shift_id and study.get("shift_id") != shift_id:
            continue
        if acquisition_state and study["acquisition_state"] != acquisition_state:
            continue
        if data_state and study["data_state"] != data_state:
            continue
        records.append(study)
    return ListResult(derive.ordered(records), limit, offset)


@bp.route("/neurodiagnostics/studies/<study_id>", methods=["GET"])
@endpoint(roles=STUDY_READ_ROLES)
def read_study(user_id, role, study_id):
    return ObjectResult(get_study(study_id))


@bp.route("/neurodiagnostics/studies/<study_id>/start", methods=["POST"])
@endpoint(roles=("Technologist",), mutating=True)
def start_study(user_id, role, study_id):
    data = validation.body()
    shift_id = validation.req_id(data, "shift_id")
    study = get_study(study_id)
    shift = get_shift(shift_id)

    # rung 6 — the study's own dimension, then the admission's
    if study["acquisition_state"] != "PREPARING":
        raise ApiError("ERR_INVALID_STUDY_STATE",
                       "Only a PREPARING study may begin acquisition.")
    admission = db.admissions.get(study["admission_id"])
    if admission is None or admission["clinical_state"] != "ADMITTED":
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "The admission must be ADMITTED to begin acquisition.")
    # rung 11 — technologist coverage
    if not derive.shift_covers_now(shift):
        raise ApiError("ERR_NO_TECH_COVERAGE",
                       "The named coverage window is not active right now.")
    # rung 12 — concurrent capacity
    if derive.shift_assigned_study_count(shift) >= shift["max_concurrent_studies"]:
        raise ApiError("ERR_TECH_CAPACITY_EXCEEDED",
                       "The coverage window is at its concurrent-study capacity.")
    # rung 13 — setting agreement
    if study["modality"] != admission["setting"]:
        raise ApiError("ERR_SETTING_MISMATCH",
                       "The study modality does not match the admission setting.")
    # rung 21 — storage lock
    unit = derive.unit_of_admission(admission)
    if unit is not None and derive.unit_posture(unit) == "STORAGE_LOCKED":
        raise ApiError("ERR_UNIT_STORAGE_LOCKED", "The unit is storage locked.")

    study["shift_id"] = shift["id"]
    study["acquisition_state"] = "ACQUIRING"
    study["current_segment_started_at"] = clock.now()
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/pause", methods=["POST"])
@endpoint(roles=("Technologist",), mutating=True)
def pause_study(user_id, role, study_id):
    data = validation.body()
    validation.req_string(data, "reason")
    maintenance_kind = validation.opt_string(data, "maintenance_kind")
    impedance = validation.opt_number(data, "impedance_kohm")
    study = get_study(study_id)
    if study["acquisition_state"] != "ACQUIRING":
        raise ApiError("ERR_INVALID_STUDY_STATE", "Only an ACQUIRING study may be paused.")
    _close_open_segment(study)
    study["acquisition_state"] = "PAUSED"
    if maintenance_kind == "ELECTRODE_REGEL" and impedance is not None:
        study["last_impedance_kohm"] = impedance
        if impedance > config.IMPEDANCE_LIMIT_KOHM:
            study["impedance_fail_count"] += 1
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/resume", methods=["POST"])
@endpoint(roles=("Technologist",), mutating=True)
def resume_study(user_id, role, study_id):
    study = get_study(study_id)
    if study["acquisition_state"] != "PAUSED":
        raise ApiError("ERR_INVALID_STUDY_STATE", "Only a PAUSED study may be resumed.")
    shift = db.shifts.get(study.get("shift_id"))
    # rung 11 — the pinned coverage window must still cover the clock
    if shift is None or not derive.shift_covers_now(shift):
        raise ApiError("ERR_NO_TECH_COVERAGE",
                       "The pinned coverage window is not active right now.")
    # rung 21 — storage lock
    unit = derive.unit_of_study(study)
    if unit is not None and derive.unit_posture(unit) == "STORAGE_LOCKED":
        raise ApiError("ERR_UNIT_STORAGE_LOCKED", "The unit is storage locked.")
    study["acquisition_state"] = "ACQUIRING"
    study["current_segment_started_at"] = clock.now()
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/complete", methods=["POST"])
@endpoint(roles=("Technologist",), mutating=True)
def complete_study(user_id, role, study_id):
    study = get_study(study_id)
    if study["acquisition_state"] not in ("ACQUIRING", "PAUSED"):
        raise ApiError("ERR_INVALID_STUDY_STATE",
                       "Only an ACQUIRING or PAUSED study may be completed.")
    if study["acquisition_state"] == "ACQUIRING":
        _close_open_segment(study)
    study["acquisition_state"] = "COMPLETED"
    study["completed_at"] = clock.now()
    _new_report(study)
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/archive", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def archive_study(user_id, role, study_id):
    study = get_study(study_id)
    if study["data_state"] != "ONLINE":
        raise ApiError("ERR_INVALID_DATA_STATE", "Only ONLINE study data may be archived.")
    if study["acquisition_state"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STUDY_STATE",
                       "Acquisition must be COMPLETED before the data may be archived.")
    study["data_state"] = "ARCHIVED"
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/export-hold", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def export_hold_study(user_id, role, study_id):
    data = validation.body()
    hold_reason = validation.req_string(data, "hold_reason")
    study = get_study(study_id)
    if study["data_state"] != "ONLINE":
        raise ApiError("ERR_INVALID_DATA_STATE",
                       "Only ONLINE study data may be placed on export hold.")
    study["data_state"] = "EXPORT_HELD"
    study["export_hold_reason"] = hold_reason
    for package in derive.packages_of_study(study["id"]):
        if package["status"] == "QUEUED":
            package["status"] = "BLOCKED"
            package["blocked_reason"] = config.BLOCK_REASON_STUDY
    return ObjectResult(study)


@bp.route("/neurodiagnostics/studies/<study_id>/export-release", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def export_release_study(user_id, role, study_id):
    study = get_study(study_id)
    if study["data_state"] != "EXPORT_HELD":
        raise ApiError("ERR_INVALID_DATA_STATE",
                       "Only a study on export hold may be released.")
    study["data_state"] = "ONLINE"
    for package in derive.packages_of_study(study["id"]):
        if (package["status"] == "BLOCKED"
                and package.get("blocked_reason") == config.BLOCK_REASON_STUDY):
            package["status"] = "QUEUED"
            package["blocked_reason"] = None
    return ObjectResult(study)
