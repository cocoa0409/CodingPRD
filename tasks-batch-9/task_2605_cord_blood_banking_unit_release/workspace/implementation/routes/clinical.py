"""Maternal panels, volume reduction, quality testing, eligibility and freezing."""
from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import (endpoint, get_body, v_bool, v_enum, v_int, v_num, v_str,
                        v_ts)
from response import object_response
from store import base_row, db, iso, now, pdt, public, touch

bp = Blueprint("clinical", __name__)

MARKER_VALUES = ("NON_REACTIVE", "REACTIVE", "INDETERMINATE", "PENDING")
GOVERNING_MARKERS = ("hiv_result", "hbv_result", "hcv_result", "htlv_result",
                     "syphilis_result")


def derive_panel(screening, enrollment, recompute_status=True):
    """calculations.maternal_panel_result -- evaluated in its pinned order."""
    values = [screening[m] for m in GOVERNING_MARKERS]
    collected = pdt(screening["collected_at"])
    if recompute_status:
        delivery = pdt(enrollment["expected_delivery_date"]) if enrollment else None
        window = timedelta(days=calc.MATERNAL_SCREEN_WINDOW_DAYS)
        if any(v == "PENDING" for v in values):
            screening["status"] = "PENDING"
            screening["overall_result"] = None
        elif delivery is None or collected < delivery - window \
                or collected > delivery + window:
            screening["status"] = "INVALID"
            screening["overall_result"] = None
        else:
            screening["status"] = "COMPLETED"
            if any(v == "REACTIVE" for v in values):
                screening["overall_result"] = "REACTIVE"
            elif any(v == "INDETERMINATE" for v in values):
                screening["overall_result"] = "INDETERMINATE"
            else:
                screening["overall_result"] = "NON_REACTIVE"
    screening["reactive_marker_codes"] = sorted(
        [m for m in GOVERNING_MARKERS if screening[m] == "REACTIVE"])
    screening["valid_until"] = iso(
        collected + timedelta(days=calc.MATERNAL_SCREEN_VALIDITY_DAYS))


@bp.route("/cbb/maternal-screenings", methods=["POST"])
@endpoint("MedicalDirector", "IntakeCoordinator", "PlatformAdmin")
def file_screening(user_id, role):
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id", min_len=1)
    collected_at = v_ts(body, "collected_at")
    markers = {}
    for name in GOVERNING_MARKERS:
        markers[name] = v_enum(body, name, MARKER_VALUES)
    cmv = v_enum(body, "cmv_result", MARKER_VALUES, required=False)
    nat = v_bool(body, "nat_confirmed", default=False)
    enrollment = svc.get_enrollment(enrollment_id)

    row = base_row()
    row.update({
        "enrollment_id": enrollment_id,
        "collected_at": iso(collected_at),
        "hiv_result": markers["hiv_result"],
        "hbv_result": markers["hbv_result"],
        "hcv_result": markers["hcv_result"],
        "htlv_result": markers["htlv_result"],
        "syphilis_result": markers["syphilis_result"],
        "cmv_result": cmv,
        "nat_confirmed": nat,
        "overall_result": None,
        "reactive_marker_codes": [],
        "valid_until": None,
        "status": "PENDING",
    })
    derive_panel(row, enrollment)
    db.screenings[row["id"]] = row
    return object_response(public(row), 201)


@bp.route("/cbb/maternal-screenings/<sid>", methods=["PATCH"])
@endpoint("MedicalDirector", "PlatformAdmin")
def amend_screening(user_id, role, sid):
    body = get_body()
    updates = {}
    for name in GOVERNING_MARKERS + ("cmv_result",):
        value = v_enum(body, name, MARKER_VALUES, required=False)
        if value is not None:
            updates[name] = value
    nat = v_bool(body, "nat_confirmed")
    screening = svc.get_screening(sid)
    enrollment = db.enrollments.get(screening["enrollment_id"])

    screening.update(updates)
    if nat is not None:
        screening["nat_confirmed"] = nat
    recompute = screening["status"] in ("PENDING", "COMPLETED")
    derive_panel(screening, enrollment, recompute_status=recompute)
    touch(screening)

    if enrollment is not None and screening["status"] == "COMPLETED" \
            and screening["overall_result"] == "REACTIVE":
        governing = svc.governing_panel(enrollment["id"])
        if governing is not None and governing["id"] == screening["id"]:
            svc.cascade_maternal_reactive(enrollment)
    return object_response(public(screening))


# ------------------------------------------------------------- processing runs
@bp.route("/cbb/processing-runs", methods=["POST"])
@endpoint("ProcessingTechnologist", "PlatformAdmin")
def open_run(user_id, role):
    body = get_body()
    unit_id = v_str(body, "unit_id", min_len=1)
    method = v_enum(body, "method", ("HES_SEDIMENTATION", "AUTOMATED_SEPARATION"))
    pre_tnc = v_int(body, "pre_tnc_millions", gt=0)
    unit = svc.get_unit(unit_id)

    for run in svc.unit_runs(unit_id):
        if run["status"] == "IN_PROGRESS":
            fail("ERR_INVALID_RUN_STATE")
    if unit["availability_status"] in ("DISPOSED", "RELEASED", "QUARANTINED"):
        fail("ERR_INVALID_UNIT_STATE")
    if unit["processing_status"] != "RECEIVED":
        fail("ERR_INVALID_UNIT_STATE")

    collection = db.collections.get(unit["collection_id"])
    row = base_row()
    row.update({
        "unit_id": unit_id,
        "method": method,
        "pre_tnc_millions": pre_tnc,
        "pre_volume_ml": collection["net_volume_ml"] if collection else None,
        "post_volume_ml": None,
        "post_tnc_millions": None,
        "tnc_recovery_pct": None,
        "volume_reduction_pct": None,
        "started_at": iso(now()),
        "completed_at": None,
        "operator_user_id": user_id,
        "status": "IN_PROGRESS",
    })
    db.runs[row["id"]] = row
    unit["processing_status"] = "PROCESSING"
    touch(unit)
    return object_response(public(row), 201)


@bp.route("/cbb/processing-runs/<rid>/complete", methods=["POST"])
@endpoint("ProcessingTechnologist", "PlatformAdmin")
def complete_run(user_id, role, rid):
    body = get_body()
    outcome = v_enum(body, "outcome", ("COMPLETED", "FAILED"))
    post_volume = v_num(body, "post_volume_ml", gt=0)
    post_tnc = v_int(body, "post_tnc_millions", gt=0)
    run = svc.get_run(rid)

    if run["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_RUN_STATE")

    run["post_volume_ml"] = calc.num(post_volume)
    run["post_tnc_millions"] = post_tnc
    run["tnc_recovery_pct"] = calc.num(
        calc.tnc_recovery_pct(post_tnc, run["pre_tnc_millions"]))
    if run["pre_volume_ml"] is not None:
        run["volume_reduction_pct"] = calc.num(
            calc.volume_reduction_pct(run["pre_volume_ml"], post_volume))
    run["completed_at"] = iso(now())
    run["status"] = outcome
    touch(run)

    unit = db.units.get(run["unit_id"])
    if unit is not None:
        if outcome == "COMPLETED":
            unit["processing_status"] = "VOLUME_REDUCED"
            unit["post_processing_volume_ml"] = calc.num(post_volume)
        else:
            unit["processing_status"] = "RECEIVED"
            unit["post_processing_volume_ml"] = None
        touch(unit)
    return object_response(public(run))


# --------------------------------------------------------------- quality tests
@bp.route("/cbb/quality-tests", methods=["POST"])
@endpoint("ProcessingTechnologist", "PlatformAdmin")
def record_test(user_id, role):
    body = get_body()
    unit_id = v_str(body, "unit_id", min_len=1)
    kind = v_enum(body, "test_kind", ("POST_PROCESSING", "CONFIRMATORY"))
    tnc = v_int(body, "tnc_millions", gt=0)
    cd34 = v_int(body, "cd34_thousands", gt=0)
    viability = v_num(body, "viability_pct", ge=0, le=100)
    volume = v_num(body, "volume_ml", gt=0)
    sterility = v_enum(body, "sterility_result", ("NEGATIVE", "POSITIVE", "PENDING"))
    reservation_id = v_str(body, "reservation_id", required=False, min_len=1)
    unit = svc.get_unit(unit_id)
    reservation = svc.get_reservation(reservation_id) if reservation_id else None

    if kind == "POST_PROCESSING" and svc.post_processing_test(unit_id) is not None:
        fail("ERR_INVALID_UNIT_STATE")

    row = base_row(with_common=False)
    row.update({
        "unit_id": unit_id,
        "test_kind": kind,
        "tnc_millions": tnc,
        "cd34_thousands": cd34,
        "viability_pct": calc.num(viability),
        "volume_ml": calc.num(volume),
        "sterility_result": sterility,
        "performed_at": iso(now()),
        "performed_by_user_id": user_id,
        "outcome": None,
        "failure_reason_codes": [],
        "_reservation_id": reservation_id,
    })

    if kind == "POST_PROCESSING":
        outcome, codes = calc.post_processing_outcome(
            unit["program_type"], tnc, cd34, viability, sterility)
        row["outcome"] = outcome
        row["failure_reason_codes"] = codes
        db.tests[row["id"]] = row
        unit["post_processing_tnc_millions"] = tnc
        unit["post_processing_cd34_thousands"] = cd34
        unit["post_processing_viability_pct"] = calc.num(viability)
        svc.recompute_score(unit)
        touch(unit)
    else:
        unit_tnc = unit.get("post_processing_tnc_millions")
        recovery = None
        if unit_tnc:
            recovery = calc.confirmatory_recovery_pct(tnc, unit_tnc)
        codes = []
        if sterility == "POSITIVE":
            codes.append("STERILITY")
        if calc.D(viability) < calc.CONFIRMATORY_MIN_VIABILITY_PCT:
            codes.append("VIABILITY")
        if recovery is not None and recovery < calc.CONFIRMATORY_MIN_RECOVERY_PCT:
            codes.append("RECOVERY")
        row["failure_reason_codes"] = sorted(codes)
        row["outcome"] = "PASS" if not codes else "FAIL"
        db.tests[row["id"]] = row
        if reservation is not None and row["outcome"] == "PASS" and unit_tnc:
            _recovery, _effective, dose = calc.post_thaw_dose(
                unit_tnc, tnc, viability, reservation["patient_weight_kg"])
            reservation["confirmatory_test_id"] = row["id"]
            reservation["post_thaw_dose_x1e7_per_kg"] = calc.num(dose)
            touch(reservation)
    return object_response(public(row), 201)


# ----------------------------------------------------- eligibility determination
@bp.route("/cbb/units/<uid>/eligibility-determination", methods=["POST"])
@endpoint("MedicalDirector", "PlatformAdmin")
def determine_eligibility(user_id, role, uid):
    body = get_body()
    v_str(body, "decision_note", required=False, min_len=0, max_len=500)
    unit = svc.get_unit(uid)

    # rung 9 -- processing axis admissibility plus the PENDING eligibility axis
    if unit["processing_status"] not in ("VOLUME_REDUCED", "CRYOPRESERVED"):
        fail("ERR_INVALID_UNIT_STATE")
    if unit["eligibility_status"] != "PENDING":
        fail("ERR_INVALID_UNIT_STATE")
    # rung 10 -- segregation of duties against the acceptance test's author
    test = svc.post_processing_test(uid)
    if test is not None and test["performed_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    # rung 13 / 14 -- the maternal panel
    enrollment = svc.unit_enrollment(unit)
    panel = svc.governing_panel(enrollment["id"]) if enrollment is not None else None
    if enrollment is None or panel is None \
            or not svc.has_current_completed_screening(enrollment["id"]):
        fail("ERR_MATERNAL_SCREENING_INCOMPLETE")
    if panel["overall_result"] == "REACTIVE":
        fail("ERR_MATERNAL_SCREENING_REACTIVE")
    # rung 15 -- sterility, evaluated before the presence rung on purpose
    if test is not None and test["sterility_result"] != "NEGATIVE":
        fail("ERR_STERILITY_POSITIVE")
    # rung 16 -- the acceptance test must exist at all
    if test is None:
        fail("ERR_NO_QUALITY_TEST")

    if panel["overall_result"] == "INDETERMINATE":
        unit["eligibility_status"] = "INDETERMINATE"
        unit["eligibility_reason_code"] = "MATERNAL_INDETERMINATE"
    else:
        score = unit.get("quality_acceptance_score")
        minimum = calc.accept_score_min(unit["program_type"])
        if score is not None and calc.D(score) >= minimum:
            unit["eligibility_status"] = "ELIGIBLE"
            unit["eligibility_reason_code"] = "ACCEPTED"
        else:
            unit["eligibility_status"] = "INELIGIBLE"
            unit["eligibility_reason_code"] = "SCORE_BELOW_TIER_MINIMUM"
    unit["eligibility_determined_by_user_id"] = user_id
    touch(unit)
    return object_response(public(unit))


# ------------------------------------------------------------- cryopreservation
@bp.route("/cbb/units/<uid>/cryopreserve", methods=["POST"])
@endpoint("ProcessingTechnologist", "PlatformAdmin")
def cryopreserve(user_id, role, uid):
    body = get_body()
    tank_id = v_str(body, "tank_id", min_len=1)
    slot_code = v_str(body, "slot_code", min_len=1, max_len=20)
    freeze_at = v_ts(body, "freeze_at")
    unit = svc.get_unit(uid)
    tank = svc.get_tank(tank_id)

    # rung 9
    if unit["processing_status"] != "VOLUME_REDUCED":
        fail("ERR_INVALID_UNIT_STATE")
    if unit["availability_status"] != "UNAVAILABLE":
        fail("ERR_INVALID_UNIT_STATE")
    # rung 11 -- consent currency
    enrollment = svc.unit_enrollment(unit)
    if enrollment is None or enrollment["consent_status"] != "CONSENTED" \
            or enrollment["consent_version"] < 1:
        fail("ERR_CONSENT_NOT_CURRENT")
    # rung 15 / 16 -- sterility then presence of the acceptance test
    test = svc.post_processing_test(uid)
    if test is not None and test["sterility_result"] != "NEGATIVE":
        fail("ERR_STERILITY_POSITIVE")
    if test is None:
        fail("ERR_NO_QUALITY_TEST")
    # rung 27 -- capacity
    if tank["occupied_slots"] >= tank["capacity_slots"]:
        fail("ERR_TANK_CAPACITY_EXCEEDED")
    # rung 28 -- operability
    if tank["status"] != "ONLINE":
        fail("ERR_TANK_NOT_OPERATIONAL")
    # rung 29 -- the half-open maintenance window
    start = pdt(tank["maintenance_window_start"])
    end = pdt(tank["maintenance_window_end"])
    if start is not None and end is not None and start <= freeze_at < end:
        fail("ERR_MAINTENANCE_WINDOW_CONFLICT")
    # rung 30 -- the rolling excursion budget
    if tank["cumulative_excursion_minutes_30d"] > calc.CUMULATIVE_EXCURSION_LIMIT_MINUTES:
        fail("ERR_EXCURSION_LIMIT_EXCEEDED")

    unit["tank_id"] = tank_id
    unit["slot_code"] = slot_code
    unit["cryopreserved_at"] = iso(freeze_at)
    unit["processing_status"] = "CRYOPRESERVED"
    if unit["program_type"] == "PRIVATE_FAMILY":
        unit["availability_status"] = "PRIVATE_STORED"
    touch(unit)
    svc.recompute_occupancy(tank)
    svc.recompute_excursion_minutes(tank)
    return object_response(public(unit))
