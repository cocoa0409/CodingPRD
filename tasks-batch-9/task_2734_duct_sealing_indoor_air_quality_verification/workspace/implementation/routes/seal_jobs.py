"""Sealing runs: booking, masking, the injection curve, completion and warranty."""

from flask import Blueprint

import calc
import cascade
import lookup
import serialize
from envelope import array_response, object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_FIELD_TECHNICIAN, ROLE_PROGRAM_ADMIN, authenticate, body,
                   fk_candidate, pagination, qenum, qstr, vid, vint, vlist_str,
                   vnum, vstr, vdt)
from routes import PREFIX
from store import by_created, clock, db, new_record, plus_days, touch

bp = Blueprint("seal_jobs", __name__)

CUTOFF_ABORT_REASON = "injection pressure cutoff"


def _project_of(job):
    return lookup.project_of_job(job)


def _system_of(job):
    return db.duct_systems.get(job["duct_system_id"])


def _assert_not_held(project):
    """Rung 8(c): no seal job may advance while the project is on safety hold."""
    if project is not None and project["status"] == "SAFETY_HOLD":
        raise ApiError("ERR_PROJECT_SAFETY_HOLD",
                       "The project is on safety hold.")


def _assert_eligible(system):
    if system is None:
        return
    if system["eligibility_status"] == "EXCLUDED":
        raise ApiError("ERR_DUCT_SYSTEM_EXCLUDED",
                       "The duct system is excluded from the retrofit.")
    if system["eligibility_status"] == "PENDING_SCREENING":
        raise ApiError("ERR_ASBESTOS_SCREENING_REQUIRED",
                       "The duct system has not passed asbestos screening.")


def _assert_certified(technician):
    """Rung 10: certification standing then expiry against the logical clock."""
    if technician["certification_status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED",
                       "The technician's certification is not ACTIVE.")
    expires_at = technician.get("certification_expires_at")
    if expires_at is not None and expires_at <= clock():
        raise ApiError("ERR_CERTIFICATION_EXPIRED",
                       "The technician's certification has expired.")


def _pre_combustion_gate(project):
    """Rung 8(a): PRE-phase coverage, skipped entirely when the dwelling has no
    atmospherically vented appliance."""
    if project is None or project["gas_appliance_count"] <= 0:
        return
    ok_count, has_fail = lookup.combustion_coverage(project, "PRE")
    if has_fail:
        raise ApiError("ERR_COMBUSTION_SPILLAGE_FAIL",
                       "A PRE-phase combustion test on this project failed.")
    if ok_count < project["gas_appliance_count"]:
        raise ApiError("ERR_COMBUSTION_SAFETY_REQUIRED",
                       "PRE-phase combustion coverage is incomplete.")


# --------------------------------------------------------------------------
# booking
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/seal-jobs")
def create_seal_job():
    authenticate((ROLE_FIELD_TECHNICIAN,))
    data = body()

    # --- rung 4: payload foreign keys in declared field order ---
    system_id = fk_candidate(data, "duct_system_id")
    if system_id is None:
        vid(data, "duct_system_id")
    system = lookup.duct_system_or_404(system_id)

    pre_test_id = fk_candidate(data, "pre_test_id")
    if pre_test_id is None:
        vid(data, "pre_test_id")
    pre_test = lookup.leakage_test_or_404(pre_test_id)

    technician_id = fk_candidate(data, "technician_id")
    if technician_id is None:
        vid(data, "technician_id")
    technician = lookup.technician_or_404(technician_id)

    parent_id = fk_candidate(data, "retest_of_job_id")
    parent = None
    if parent_id is not None:
        parent = lookup.seal_job_or_404(parent_id)
    elif data.get("retest_of_job_id") is not None:
        vid(data, "retest_of_job_id", required=False)

    # --- rung 5 ---
    start_at = vdt(data, "scheduled_start_at")
    end_at = vdt(data, "scheduled_end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'scheduled_end_at' must be strictly after "
                       "'scheduled_start_at'.")
    target = vnum(data, "target_leakage_cfm", exclusive_minimum=0)
    expected = vint(data, "expected_duct_system_version", minimum=0)

    # --- rung 7: optimistic concurrency on the duct system ---
    if expected != system["version"]:
        raise ApiError("ERR_STALE_DUCT_SYSTEM_VERSION",
                       "expected_duct_system_version does not match the duct system.")

    # --- rung 8: no new run may be booked under a held project ---
    project = lookup.project_of_system(system)
    _assert_not_held(project)

    # --- rung 9: cross-entity coherence ---
    if pre_test["duct_system_id"] != system["id"]:
        raise ApiError("ERR_PRE_TEST_SYSTEM_MISMATCH",
                       "The pre-test belongs to a different duct system.")
    if pre_test["phase"] != "PRE" or pre_test["status"] != "ACCEPTED":
        raise ApiError("ERR_TEST_PHASE_MISMATCH",
                       "The pre-test must be an ACCEPTED PRE-phase measurement.")
    if parent is not None:
        if parent["duct_system_id"] != system["id"] \
                or parent["status"] not in ("VERIFIED", "RETEST_REQUIRED"):
            raise ApiError("ERR_RETEST_TARGET_INVALID",
                           "retest_of_job_id must name a VERIFIED or RETEST_REQUIRED "
                           "run on this duct system.")
    _assert_eligible(system)

    # --- rung 10: the technician's standing ---
    _assert_certified(technician)

    # --- rung 11: the half-open booked slot, then the re-test deadline ---
    for job in db.rows("seal_jobs"):
        if job["technician_id"] != technician["id"]:
            continue
        if job["status"] in calc.SEAL_JOB_TERMINAL:
            continue
        if job["scheduled_start_at"] < end_at and start_at < job["scheduled_end_at"]:
            raise ApiError("ERR_TECHNICIAN_SCHEDULE_CONFLICT",
                           "The technician already owns an overlapping run.")
    if parent is not None:
        due_at = parent.get("retest_due_at")
        if due_at is not None and clock() > due_at:
            raise ApiError("ERR_RETEST_WINDOW_ELAPSED",
                           "The parent run's re-test window has elapsed.")

    # --- supersede any run on this system still sitting in SCHEDULED ---
    for job in lookup.seal_jobs_of_system(system["id"]):
        if job["status"] != "SCHEDULED":
            continue
        job["status"] = "ABORTED_SUPERSEDED"
        job["abort_reason"] = "superseded by a newer scheduled job"
        touch(job)

    row = new_record()
    row.update({
        "duct_system_id": system["id"],
        "pre_test_id": pre_test["id"],
        "technician_id": technician["id"],
        "retest_of_job_id": parent["id"] if parent is not None else None,
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "target_leakage_cfm": target,
        "status": "SCHEDULED",
        "masked_register_labels": [],
        "sample_count": 0,
        "current_leakage_cfm": None,
        "target_reached": False,
        "stall_flag": False,
        "pause_count": 0,
        "sealant_lbs_used": None,
        "abort_reason": None,
        "warranty_suspended": False,
        "warranty_registered_at": None,
        "retest_due_at": None,
        "homeowner_name": None,
        "homeowner_email": None,
    })
    db.seal_jobs[row["id"]] = row

    # Booking a re-test is the ONLY way a VERIFIED system is reopened.
    if parent is not None and parent["status"] == "RETEST_REQUIRED":
        cascade.compensate_ledger(system)
    touch(system)
    return object_response(serialize.seal_job(row), 201)


@bp.get(PREFIX + "/seal-jobs/<job_id>")
def read_seal_job(job_id):
    authenticate(ALL_ROLES)
    row = lookup.seal_job_or_404(job_id)
    return object_response(serialize.seal_job(row))


@bp.get(PREFIX + "/seal-jobs")
def list_seal_jobs():
    authenticate(ALL_ROLES)
    duct_system_id = qstr("duct_system_id")
    pre_test_id = qstr("pre_test_id")
    technician_id = qstr("technician_id")
    retest_of_job_id = qstr("retest_of_job_id")
    status = qenum("status", calc.SEAL_JOB_STATUS)
    limit, offset = pagination()
    rows = []
    for row in by_created(db.rows("seal_jobs")):
        if duct_system_id is not None and row["duct_system_id"] != duct_system_id:
            continue
        if pre_test_id is not None and row["pre_test_id"] != pre_test_id:
            continue
        if technician_id is not None and row["technician_id"] != technician_id:
            continue
        if retest_of_job_id is not None and row.get("retest_of_job_id") != retest_of_job_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    window = rows[offset:offset + limit]
    return array_response([serialize.seal_job(r) for r in window], limit, offset, len(rows))


# --------------------------------------------------------------------------
# masking and injection start
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/seal-jobs/<job_id>/masks")
def add_masks(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    labels = vlist_str(data, "register_labels")
    # rung 6
    if job["status"] not in ("SCHEDULED", "MASKING"):
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Masking requires status SCHEDULED or MASKING.")
    system = _system_of(job)
    # the first masking call requires an eligible duct system
    if job["status"] == "SCHEDULED":
        _assert_eligible(system)

    present = list(job["masked_register_labels"])
    for label in labels:
        if label not in present:
            present.append(label)
    job["masked_register_labels"] = present
    job["status"] = "MASKING"
    touch(job)
    return object_response(serialize.seal_job(job))


@bp.post(PREFIX + "/seal-jobs/<job_id>/start-injection")
def start_injection(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    # rung 6
    if job["status"] != "MASKING":
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Starting injection requires status MASKING.")
    system = _system_of(job)
    project = lookup.project_of_system(system) if system is not None else None
    # rung 8 - combustion coverage then the project safety hold
    _pre_combustion_gate(project)
    _assert_not_held(project)
    # rung 9
    _assert_eligible(system)
    # rung 10 - masking completeness then the technician's standing
    if system is not None \
            and len(job["masked_register_labels"]) != system["total_register_count"]:
        raise ApiError("ERR_MASKING_INCOMPLETE",
                       "Every register of the duct system must be masked before "
                       "injection starts.")
    _assert_certified(lookup.technician_or_404(job["technician_id"]))

    job["status"] = "INJECTING"
    touch(job)
    if system is not None:
        system["seal_status"] = "SEALING"
        touch(system)
    return object_response(serialize.seal_job(job))


# --------------------------------------------------------------------------
# the real-time leakage curve
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/seal-jobs/<job_id>/leakage-samples")
def create_leakage_sample(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    # rung 5
    sample_seq = vint(data, "sample_seq", minimum=1)
    elapsed = vint(data, "elapsed_seconds", minimum=0)
    leakage = vnum(data, "instantaneous_leakage_cfm", minimum=0)
    pressure = vnum(data, "injection_pressure_pa", minimum=0)
    # rung 6.  The pressure cutoff may fire on a run that is INJECTING or
    # PAUSED, so a cutoff-tripping point is accepted from PAUSED as well; every
    # other point requires INJECTING.
    trips_cutoff = pressure > calc.MAX_INJECTION_PA
    if job["status"] != "INJECTING" and not (job["status"] == "PAUSED" and trips_cutoff):
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Appending a curve point requires status INJECTING.")
    # rung 10
    if sample_seq != job["sample_count"] + 1:
        raise ApiError("ERR_SAMPLE_SEQUENCE_INVALID",
                       "sample_seq must equal the run's sample_count plus 1.")

    earlier = lookup.samples_of_job(job["id"])
    row = new_record(versioned=False)
    row.update({
        "seal_job_id": job["id"],
        "sample_seq": sample_seq,
        "elapsed_seconds": elapsed,
        "instantaneous_leakage_cfm": leakage,
        "injection_pressure_pa": pressure,
        "seal_rate_cfm_per_min": None,
        "cutoff_triggered": False,
    })
    # the fixed three-sample backward window
    if sample_seq >= calc.STALL_WINDOW_SAMPLES:
        older = None
        for candidate in earlier:
            if candidate["sample_seq"] == sample_seq - 2:
                older = candidate
        if older is not None:
            row["seal_rate_cfm_per_min"] = calc.seal_rate(older, row)
    db.leakage_samples[row["id"]] = row

    job["sample_count"] = job["sample_count"] + 1
    job["current_leakage_cfm"] = leakage
    if job["target_leakage_cfm"] is not None and leakage <= job["target_leakage_cfm"]:
        job["target_reached"] = True

    system = _system_of(job)
    project = lookup.project_of_system(system) if system is not None else None
    if system is not None:
        system["working_leakage_cfm25"] = leakage
        baseline = system.get("baseline_leakage_cfm25")
        if baseline is not None:
            system["sealed_leakage_reduction_cfm"] = calc.rhu(
                calc.dec(baseline) - calc.dec(leakage), 2)

    # the cutoff is evaluated BEFORE the stall check
    if trips_cutoff:
        row["cutoff_triggered"] = True
        if system is not None:
            cascade.injection_pressure_cutoff(job, system, project)
    elif row["seal_rate_cfm_per_min"] is not None \
            and row["seal_rate_cfm_per_min"] < calc.MIN_SEAL_RATE_CFM_PER_MIN:
        job["status"] = "PAUSED"
        job["stall_flag"] = True
        job["pause_count"] = job["pause_count"] + 1

    touch(job)
    if system is not None:
        touch(system)
    return object_response(serialize.leakage_sample(row), 201)


@bp.get(PREFIX + "/seal-jobs/<job_id>/leakage-samples")
def list_leakage_samples(job_id):
    authenticate(ALL_ROLES)
    job = lookup.seal_job_or_404(job_id)
    limit, offset = pagination()
    rows = lookup.samples_of_job(job["id"])
    window = rows[offset:offset + limit]
    return array_response([serialize.leakage_sample(r) for r in window],
                          limit, offset, len(rows))


# --------------------------------------------------------------------------
# the INJECTING <-> PAUSED cycle
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/seal-jobs/<job_id>/pause")
def pause_seal_job(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    reason = vstr(data, "pause_reason")
    # rung 6 - a pause aimed at an ABORTED_SAFETY run is a plain state error
    if job["status"] != "INJECTING":
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Pausing requires status INJECTING.")

    job["status"] = "PAUSED"
    job["pause_count"] = job["pause_count"] + 1
    job["abort_reason"] = None
    # the reason lives on the run log, not on the serialised run
    job["_pause_reason"] = reason
    touch(job)
    return object_response(serialize.seal_job(job))


@bp.post(PREFIX + "/seal-jobs/<job_id>/resume")
def resume_seal_job(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    # gate 8(d): the single carve-out to the state rung.  A resume aimed at a run
    # the safety cutoff aborted is entitled to hear why, and it outranks the
    # safety hold the cutoff itself raised.
    if job["status"] == "ABORTED_SAFETY":
        raise ApiError("ERR_INJECTION_PRESSURE_LIMIT",
                       "The run was aborted by the injection pressure cutoff.")
    # rung 6
    if job["status"] != "PAUSED":
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Resuming requires status PAUSED.")
    system = _system_of(job)
    project = lookup.project_of_system(system) if system is not None else None
    # rung 8(c)
    _assert_not_held(project)
    # rung 9
    _assert_eligible(system)

    job["status"] = "INJECTING"
    job["stall_flag"] = False
    touch(job)
    return object_response(serialize.seal_job(job))


# --------------------------------------------------------------------------
# closing a run out
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/seal-jobs/<job_id>/complete-seal")
def complete_seal(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    sealant = vnum(data, "sealant_lbs_used", minimum=0)
    # rung 6 - completion is legal only from INJECTING and only once the target
    # has actually been hit
    if job["status"] != "INJECTING":
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Completion requires status INJECTING.")
    if not job["target_reached"]:
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Completion requires target_reached to be true.")
    system = _system_of(job)
    project = lookup.project_of_system(system) if system is not None else None
    # rung 8(c)
    _assert_not_held(project)

    job["status"] = "SEALED"
    job["sealant_lbs_used"] = sealant
    touch(job)
    if system is not None:
        system["seal_status"] = "SEALED"
        system["working_leakage_cfm25"] = job["current_leakage_cfm"]
        baseline = system.get("baseline_leakage_cfm25")
        if baseline is not None and job["current_leakage_cfm"] is not None:
            system["sealed_leakage_reduction_cfm"] = calc.rhu(
                calc.dec(baseline) - calc.dec(job["current_leakage_cfm"]), 2)
        touch(system)
    return object_response(serialize.seal_job(job))


@bp.post(PREFIX + "/seal-jobs/<job_id>/abort")
def abort_seal_job(job_id):
    authenticate((ROLE_FIELD_TECHNICIAN, ROLE_PROGRAM_ADMIN))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    reason = vstr(data, "abort_reason")
    # rung 6
    if job["status"] not in calc.SEAL_JOB_OPEN:
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Aborting requires status SCHEDULED, MASKING, INJECTING or "
                       "PAUSED.")

    job["status"] = "ABORTED_MANUAL"
    job["abort_reason"] = reason
    touch(job)
    system = _system_of(job)
    if system is not None:
        # the compensation is the SEALING -> SEAL_PENDING return; a run aborted
        # before injection started never moved the ledger, and an older sealed
        # run's ledger must not be rewritten by it
        if system["seal_status"] == "SEALING":
            cascade.compensate_ledger(system)
        touch(system)
    return object_response(serialize.seal_job(job))


@bp.post(PREFIX + "/seal-jobs/<job_id>/warranty-registration")
def register_warranty(job_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    job = lookup.seal_job_or_404(job_id)
    data = body()
    homeowner_name = vstr(data, "homeowner_name")
    homeowner_email = vstr(data, "homeowner_email")
    # rung 6
    if job["status"] != "VERIFIED":
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Warranty registration requires status VERIFIED.")

    registered_at = clock()
    job["homeowner_name"] = homeowner_name
    job["homeowner_email"] = homeowner_email
    job["warranty_registered_at"] = registered_at
    job["retest_due_at"] = plus_days(registered_at, calc.RETEST_INTERVAL_DAYS)
    touch(job)
    return object_response(serialize.seal_job(job))
