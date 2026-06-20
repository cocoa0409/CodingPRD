"""Sleep Diagnostics Center API — Flask entry point.

In-memory, single-process. The store starts empty on every boot (no seeding).
All routes, error handlers, and bubble-up cascades live here so that the
cross-aggregate state propagation stays coordinated.

Validation ordering follows PRD §2.7: auth -> role -> existence (left to right)
-> body well-formedness -> state legality -> domain guards (cross-entity gate,
auth expiry, modality/bed, bed collision, compliance overlap, CPAP gate,
scoring sufficiency, resupply integrity, OCC).
"""

import os

from flask import Flask, request

from db import db, lock
from errors import ApiError, err
from response import success, error_response
import helpers as h
import domain as dom

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_INVALID_REQUEST", "Resource not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_INVALID_REQUEST", "Method not allowed")
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
    resp.status_code = 422
    return resp


# ---------------------------------------------------------------------------
# Auth + RBAC wrapper. Every handler calls auth(allowed_roles) first.
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    user_id, role = h.require_auth()
    h.require_role(role, allowed_roles)
    return user_id, role


ALL_ROLES = ["SchedulingCoordinator", "SleepTechnologist", "Physician",
             "DMECoordinator", "Patient"]


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    with lock:
        auth(["SchedulingCoordinator"])
        body = h.get_json_body()
        h.require_fields(body, ["full_name", "date_of_birth", "insurance_payer"])
        h.require_string(body["full_name"], "full_name")
        h.require_string(body["date_of_birth"], "date_of_birth")
        h.require_string(body["insurance_payer"], "insurance_payer")
        baseline = body.get("baseline_epworth_score", 0)
        if baseline is None:
            baseline = 0
        h.require_int(baseline, "baseline_epworth_score")
        if baseline < 0 or baseline > 24:
            raise err("ERR_INVALID_REQUEST", "baseline_epworth_score must be 0..24")
        rec = {
            "full_name": body["full_name"],
            "date_of_birth": body["date_of_birth"],
            "insurance_payer": body["insurance_payer"],
            "baseline_epworth_score": baseline,
        }
        db.stamp_new(rec)
        db.patients[rec["id"]] = rec
        return success(dom.ser_patient(rec), 201)


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        p = dom.get_or_404(db.patients, pid, "ERR_PATIENT_NOT_FOUND")
        return success(dom.ser_patient(p), 200)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/referrals", methods=["POST"])
def create_referral():
    with lock:
        auth(["SchedulingCoordinator"])
        body = h.get_json_body()
        # Existence (priority 3): patient_id FK before body validity.
        h.require_fields(body, ["patient_id", "referring_provider_npi",
                                "requested_modality", "clinical_indication"])
        h.require_string(body["patient_id"], "patient_id")
        dom.get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
        # Body validity (priority 4).
        h.require_string(body["referring_provider_npi"], "referring_provider_npi")
        h.require_enum(body["requested_modality"], dom.REQUESTED_MODALITIES,
                       "requested_modality")
        h.require_string(body["clinical_indication"], "clinical_indication")
        pa_required = body.get("prior_auth_required", True)
        if pa_required is None:
            pa_required = True
        h.require_bool(pa_required, "prior_auth_required")
        rec = {
            "patient_id": body["patient_id"],
            "referring_provider_npi": body["referring_provider_npi"],
            "requested_modality": body["requested_modality"],
            "clinical_indication": body["clinical_indication"],
            "prior_auth_required": pa_required,
            "prior_auth_number": None,
            "prior_auth_expires_on": None,
            "status": "SUBMITTED",
        }
        db.stamp_new(rec)
        db.referrals[rec["id"]] = rec
        return success(dom.ser_referral(rec), 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        limit, offset = h.parse_pagination()
        patient_id = request.args.get("patient_id")
        status = request.args.get("status")
        items = list(db.referrals.values())
        if patient_id:
            items = [r for r in items if r["patient_id"] == patient_id]
        if status:
            items = [r for r in items if r["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_referral(x) for x in page], 200, pg)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        r = dom.get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
        return success(dom.ser_referral(r), 200)


@app.route("/referrals/<rid>/request-auth", methods=["POST"])
def referral_request_auth(rid):
    with lock:
        auth(["SchedulingCoordinator"])
        r = dom.get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
        # State (priority 5): must be SUBMITTED.
        if r["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Referral not in SUBMITTED")
        # request-auth only valid when prior_auth_required is true.
        if not r["prior_auth_required"]:
            raise err("ERR_AUTH_NOT_REQUIRED",
                      "Referral does not require prior authorization")
        r["status"] = "PENDING_AUTH"
        db.touch(r)
        return success(dom.ser_referral(r), 200)


@app.route("/referrals/<rid>/approve-auth", methods=["POST"])
def referral_approve_auth(rid):
    with lock:
        auth(["SchedulingCoordinator"])
        r = dom.get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
        body = h.get_json_body()
        h.require_fields(body, ["prior_auth_number", "prior_auth_expires_on"])
        h.require_string(body["prior_auth_number"], "prior_auth_number")
        h.require_string(body["prior_auth_expires_on"], "prior_auth_expires_on")
        # State (priority 5): legal from PENDING_AUTH, or from SUBMITTED only on
        # the no-auth fast path (prior_auth_required == false).
        if r["status"] == "PENDING_AUTH":
            pass
        elif r["status"] == "SUBMITTED":
            if r["prior_auth_required"]:
                raise err("ERR_INVALID_STATE",
                          "Referral requires prior authorization; must go via "
                          "PENDING_AUTH")
        else:
            raise err("ERR_INVALID_STATE", "Referral cannot be approved from "
                      "its current state")
        r["prior_auth_number"] = body["prior_auth_number"]
        r["prior_auth_expires_on"] = body["prior_auth_expires_on"]
        r["status"] = "AUTHORIZED"
        db.touch(r)
        return success(dom.ser_referral(r), 200)


@app.route("/referrals/<rid>/deny-auth", methods=["POST"])
def referral_deny_auth(rid):
    with lock:
        auth(["SchedulingCoordinator"])
        r = dom.get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
        if r["status"] != "PENDING_AUTH":
            raise err("ERR_INVALID_STATE", "Referral not in PENDING_AUTH")
        r["status"] = "DENIED"
        db.touch(r)
        return success(dom.ser_referral(r), 200)


@app.route("/referrals/<rid>/cancel", methods=["POST"])
def referral_cancel(rid):
    with lock:
        auth(["SchedulingCoordinator"])
        r = dom.get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
        # State (priority 5): cancellable from SUBMITTED, PENDING_AUTH,
        # AUTHORIZED, or SCHEDULED. SCHEDULED is included so the cascade that
        # cancels ORDERED/SCHEDULED studies and releases their bed nights (PRD
        # 2.5 / 3.2) is reachable, and so the ERR_REFERRAL_HAS_ACTIVE_STUDY
        # guard (which only applies once a study is IN_PROGRESS/SCORED/
        # INTERPRETED, i.e. when the referral has bubbled to SCHEDULED) can fire.
        if r["status"] not in ("SUBMITTED", "PENDING_AUTH", "AUTHORIZED",
                               "SCHEDULED"):
            raise err("ERR_INVALID_STATE", "Referral cannot be cancelled from "
                      "its current state")
        studies = [s for s in db.study_orders.values()
                   if s["referral_id"] == rid]
        # Blocked if any study has progressed to an active clinical state.
        for s in studies:
            if s["status"] in ("IN_PROGRESS", "SCORED", "INTERPRETED"):
                raise err("ERR_REFERRAL_HAS_ACTIVE_STUDY",
                          "An active study exists under this referral")
        r["status"] = "CANCELLED"
        db.touch(r)
        # Cascade: ORDERED/SCHEDULED studies -> CANCELLED (bed nights released
        # implicitly once the study leaves an active-holding state).
        for s in studies:
            if s["status"] in ("ORDERED", "SCHEDULED"):
                s["status"] = "CANCELLED"
                db.touch(s)
        return success(dom.ser_referral(r), 200)


# ===========================================================================
# SleepBed
# ===========================================================================
@app.route("/beds", methods=["POST"])
def create_bed():
    with lock:
        auth(["SchedulingCoordinator"])
        body = h.get_json_body()
        h.require_fields(body, ["bed_label"])
        h.require_string(body["bed_label"], "bed_label")
        buf = body.get("turnover_buffer_minutes", 60)
        if buf is None:
            buf = 60
        h.require_int(buf, "turnover_buffer_minutes")
        if buf < 0:
            raise err("ERR_INVALID_REQUEST", "turnover_buffer_minutes must be >= 0")
        rec = {
            "bed_label": body["bed_label"],
            "turnover_buffer_minutes": buf,
            "status": "AVAILABLE",
        }
        db.stamp_new(rec)
        db.beds[rec["id"]] = rec
        return success(dom.ser_bed(rec), 201)


@app.route("/beds", methods=["GET"])
def list_beds():
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist"])
        limit, offset = h.parse_pagination()
        status = request.args.get("status")
        items = list(db.beds.values())
        if status:
            items = [b for b in items if b["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_bed(x) for x in page], 200, pg)


@app.route("/beds/<bid>", methods=["GET"])
def get_bed(bid):
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist"])
        b = dom.get_or_404(db.beds, bid, "ERR_BED_NOT_FOUND")
        return success(dom.ser_bed(b), 200)


@app.route("/beds/<bid>/set-out-of-service", methods=["POST"])
def bed_set_out_of_service(bid):
    with lock:
        auth(["SchedulingCoordinator"])
        b = dom.get_or_404(db.beds, bid, "ERR_BED_NOT_FOUND")
        b["status"] = "OUT_OF_SERVICE"
        db.touch(b)
        return success(dom.ser_bed(b), 200)


# ===========================================================================
# StudyOrder
# ===========================================================================
@app.route("/study-orders", methods=["POST"])
def create_study_order():
    with lock:
        auth(["SchedulingCoordinator"])
        body = h.get_json_body()
        # Existence (priority 3): referral_id FK.
        h.require_fields(body, ["referral_id", "modality",
                                "expected_referral_version"])
        h.require_string(body["referral_id"], "referral_id")
        referral = dom.get_or_404(db.referrals, body["referral_id"],
                                  "ERR_REFERRAL_NOT_FOUND")
        # Body validity (priority 4).
        h.require_enum(body["modality"], dom.STUDY_MODALITIES, "modality")
        h.require_int(body["expected_referral_version"],
                      "expected_referral_version")
        # OCC (priority 14): expected_referral_version == referral.version.
        if body["expected_referral_version"] != referral["version"]:
            raise err("ERR_STALE_REFERRAL_VERSION", "Referral version is stale")
        rec = {
            "referral_id": referral["id"],
            "bed_id": None,
            "modality": body["modality"],
            "night_start_utc": None,
            "night_end_utc": None,
            "total_recording_minutes": None,
            "respiratory_event_count": None,
            "titration_optimal_cmh2o": None,
            "ahi": None,
            "severity": None,
            "status": "ORDERED",
        }
        db.stamp_new(rec)
        db.study_orders[rec["id"]] = rec
        # Acquiring a child study mutates the referral: bump its version.
        db.touch(referral)
        return success(dom.ser_study(rec), 201)


@app.route("/study-orders", methods=["GET"])
def list_study_orders():
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist", "Physician",
              "DMECoordinator"])
        limit, offset = h.parse_pagination()
        referral_id = request.args.get("referral_id")
        bed_id = request.args.get("bed_id")
        status = request.args.get("status")
        items = list(db.study_orders.values())
        if referral_id:
            items = [s for s in items if s["referral_id"] == referral_id]
        if bed_id:
            items = [s for s in items if s["bed_id"] == bed_id]
        if status:
            items = [s for s in items if s["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_study(x) for x in page], 200, pg)


@app.route("/study-orders/<sid>", methods=["GET"])
def get_study_order(sid):
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist", "Physician",
              "DMECoordinator"])
        s = dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        return success(dom.ser_study(s), 200)


@app.route("/study-orders/<sid>/schedule", methods=["POST"])
def study_schedule(sid):
    with lock:
        auth(["SchedulingCoordinator"])
        s = dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        body = h.get_json_body()
        h.require_fields(body, ["night_start_utc", "night_end_utc"])
        h.require_string(body["night_start_utc"], "night_start_utc")
        h.require_string(body["night_end_utc"], "night_end_utc")
        bed_id = body.get("bed_id")
        # Existence (priority 3): bed_id FK when provided.
        bed = None
        if bed_id is not None:
            h.require_string(bed_id, "bed_id")
            bed = dom.get_or_404(db.beds, bed_id, "ERR_BED_NOT_FOUND")
        start_dt = h.parse_iso(body["night_start_utc"], "night_start_utc")
        end_dt = h.parse_iso(body["night_end_utc"], "night_end_utc")
        referral = db.referrals[s["referral_id"]]
        # State (priority 5): study must be ORDERED.
        if s["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Study not in ORDERED")
        # Cross-entity gate (priority 6): referral AUTHORIZED.
        if referral["status"] != "AUTHORIZED":
            raise err("ERR_REFERRAL_NOT_AUTHORIZED",
                      "Parent referral is not AUTHORIZED")
        # Auth expiry (priority 7): night_start date <= prior_auth_expires_on.
        if referral["prior_auth_expires_on"] is not None:
            expires = h.parse_date(referral["prior_auth_expires_on"],
                                   "prior_auth_expires_on")
            if start_dt.date() > expires:
                raise err("ERR_AUTH_EXPIRED",
                          "Authorization has lapsed for the requested night")
        # Night-window validity: end strictly after start.
        if not (end_dt > start_dt):
            raise err("ERR_INVALID_NIGHT_WINDOW",
                      "night_end_utc must be strictly after night_start_utc")
        # Modality/bed coherence (priority 8).
        if s["modality"] in dom.IN_LAB_MODALITIES:
            if bed is None:
                raise err("ERR_BED_REQUIRED", "In-lab study requires a bed_id")
        else:  # HSAT
            if bed is not None:
                raise err("ERR_HSAT_BED_NOT_ALLOWED",
                          "HSAT study must not supply a bed_id")
        # Bed availability + collision (priority 9), in-lab only.
        if bed is not None:
            if bed["status"] == "OUT_OF_SERVICE":
                raise err("ERR_BED_OUT_OF_SERVICE", "Bed is OUT_OF_SERVICE")
            if dom.bed_night_collides(bed, start_dt, end_dt):
                raise err("ERR_BED_DOUBLE_BOOKED",
                          "Night collides with an existing booking on this bed")
            s["bed_id"] = bed["id"]
        s["night_start_utc"] = body["night_start_utc"]
        s["night_end_utc"] = body["night_end_utc"]
        s["status"] = "SCHEDULED"
        db.touch(s)
        # Bubble-up: referral AUTHORIZED -> SCHEDULED.
        if referral["status"] == "AUTHORIZED":
            referral["status"] = "SCHEDULED"
            db.touch(referral)
        return success(dom.ser_study(s), 200)


@app.route("/study-orders/<sid>/start", methods=["POST"])
def study_start(sid):
    with lock:
        auth(["SleepTechnologist"])
        s = dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        if s["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Study not in SCHEDULED")
        s["status"] = "IN_PROGRESS"
        db.touch(s)
        return success(dom.ser_study(s), 200)


@app.route("/study-orders/<sid>/score", methods=["POST"])
def study_score(sid):
    with lock:
        user_id, role = auth(["SleepTechnologist"])
        s = dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        body = h.get_json_body()
        h.require_fields(body, ["total_recording_minutes", "respiratory_event_count",
                                "expected_study_order_version"])
        h.require_int(body["total_recording_minutes"], "total_recording_minutes")
        h.require_int(body["respiratory_event_count"], "respiratory_event_count")
        h.require_int(body["expected_study_order_version"],
                      "expected_study_order_version")
        if body["respiratory_event_count"] < 0:
            raise err("ERR_INVALID_REQUEST", "respiratory_event_count must be >= 0")
        titration = body.get("titration_optimal_cmh2o")
        if titration is not None:
            h.require_number(titration, "titration_optimal_cmh2o")
        # State (priority 5): IN_PROGRESS.
        if s["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "Study not in IN_PROGRESS")
        # Scoring sufficiency (priority 12).
        if body["total_recording_minutes"] <= 0:
            raise err("ERR_INSUFFICIENT_RECORDING",
                      "total_recording_minutes must be > 0")
        if s["modality"] == "IN_LAB_TITRATION":
            if titration is None or titration <= 0:
                raise err("ERR_TITRATION_PRESSURE_REQUIRED",
                          "IN_LAB_TITRATION requires titration_optimal_cmh2o > 0")
        # OCC (priority 14).
        if body["expected_study_order_version"] != s["version"]:
            raise err("ERR_STALE_STUDY_VERSION", "Study version is stale")
        # Persist scoring inputs + compute AHI / severity.
        s["total_recording_minutes"] = body["total_recording_minutes"]
        s["respiratory_event_count"] = body["respiratory_event_count"]
        if s["modality"] == "IN_LAB_TITRATION":
            s["titration_optimal_cmh2o"] = titration
        ahi = dom.compute_ahi(s["total_recording_minutes"],
                              s["respiratory_event_count"])
        severity = dom.compute_severity(ahi)
        s["ahi"] = ahi
        s["severity"] = severity
        s["status"] = "SCORED"
        db.touch(s)
        # Create the DRAFT ScoringReport with snapshots.
        report = {
            "study_order_id": s["id"],
            "scored_by_tech_id": user_id,
            "ahi_snapshot": ahi,
            "severity_snapshot": severity,
            "interpretation_text": None,
            "physician_recommends_cpap": False,
            "status": "DRAFT",
        }
        db.stamp_new(report)
        db.scoring_reports[report["id"]] = report
        return success(dom.ser_study(s), 200)


@app.route("/study-orders/<sid>/cancel", methods=["POST"])
def study_cancel(sid):
    with lock:
        auth(["SchedulingCoordinator"])
        s = dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        if s["status"] not in ("ORDERED", "SCHEDULED"):
            raise err("ERR_STUDY_NOT_CANCELLABLE",
                      "Study can only be cancelled from ORDERED or SCHEDULED")
        s["status"] = "CANCELLED"
        db.touch(s)
        return success(dom.ser_study(s), 200)


@app.route("/study-orders/<sid>/scoring-reports", methods=["GET"])
def list_study_scoring_reports(sid):
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist", "Physician",
              "DMECoordinator"])
        dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        limit, offset = h.parse_pagination()
        items = [r for r in db.scoring_reports.values()
                 if r["study_order_id"] == sid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_scoring(x) for x in page], 200, pg)


@app.route("/study-orders/<sid>/follow-ups", methods=["GET"])
def list_study_follow_ups(sid):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        dom.get_or_404(db.study_orders, sid, "ERR_STUDY_NOT_FOUND")
        limit, offset = h.parse_pagination()
        items = [f for f in db.follow_ups.values()
                 if f["study_order_id"] == sid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_followup(x) for x in page], 200, pg)


# ===========================================================================
# ScoringReport
# ===========================================================================
@app.route("/scoring-reports/<rid>", methods=["GET"])
def get_scoring_report(rid):
    with lock:
        auth(["SchedulingCoordinator", "SleepTechnologist", "Physician",
              "DMECoordinator"])
        r = dom.get_or_404(db.scoring_reports, rid, "ERR_SCORING_REPORT_NOT_FOUND")
        return success(dom.ser_scoring(r), 200)


@app.route("/scoring-reports/<rid>/interpret", methods=["POST"])
def scoring_interpret(rid):
    with lock:
        auth(["Physician"])
        r = dom.get_or_404(db.scoring_reports, rid, "ERR_SCORING_REPORT_NOT_FOUND")
        body = h.get_json_body()
        h.require_fields(body, ["interpretation_text"])
        h.require_string(body["interpretation_text"], "interpretation_text")
        recommends = body.get("physician_recommends_cpap", False)
        if recommends is None:
            recommends = False
        h.require_bool(recommends, "physician_recommends_cpap")
        study = db.study_orders[r["study_order_id"]]
        # State (priority 5): report DRAFT and linked study SCORED.
        if r["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Scoring report not in DRAFT")
        if study["status"] != "SCORED":
            raise err("ERR_INVALID_STATE", "Linked study not in SCORED")
        r["interpretation_text"] = body["interpretation_text"]
        r["physician_recommends_cpap"] = recommends
        r["status"] = "FINALIZED"
        db.touch(r)
        # Cross-entity: study SCORED -> INTERPRETED.
        study["status"] = "INTERPRETED"
        db.touch(study)
        # Bubble-up: referral SCHEDULED -> COMPLETED.
        referral = db.referrals[study["referral_id"]]
        if referral["status"] == "SCHEDULED":
            referral["status"] = "COMPLETED"
            db.touch(referral)
        return success(dom.ser_scoring(r), 200)


@app.route("/scoring-reports/<rid>/return", methods=["POST"])
def scoring_return(rid):
    with lock:
        auth(["Physician"])
        r = dom.get_or_404(db.scoring_reports, rid, "ERR_SCORING_REPORT_NOT_FOUND")
        study = db.study_orders[r["study_order_id"]]
        # State (priority 5): report DRAFT and linked study SCORED.
        if r["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Scoring report not in DRAFT")
        if study["status"] != "SCORED":
            raise err("ERR_INVALID_STATE", "Linked study not in SCORED")
        r["status"] = "RETURNED"
        db.touch(r)
        # Revert loop: linked study SCORED -> IN_PROGRESS (bumps version).
        study["status"] = "IN_PROGRESS"
        db.touch(study)
        return success(dom.ser_scoring(r), 200)


# ===========================================================================
# DMEOrder
# ===========================================================================
@app.route("/dme-orders", methods=["POST"])
def create_dme_order():
    with lock:
        auth(["DMECoordinator"])
        body = h.get_json_body()
        # Existence (priority 3): study_order_id, then supersedes_dme_order_id.
        h.require_fields(body, ["study_order_id", "device_type",
                                "prescribed_pressure_cmh2o"])
        h.require_string(body["study_order_id"], "study_order_id")
        study = dom.get_or_404(db.study_orders, body["study_order_id"],
                               "ERR_STUDY_NOT_FOUND")
        supersedes_id = body.get("supersedes_dme_order_id")
        predecessor = None
        if supersedes_id is not None:
            h.require_string(supersedes_id, "supersedes_dme_order_id")
            predecessor = dom.get_or_404(db.dme_orders, supersedes_id,
                                         "ERR_DME_NOT_FOUND")
        # Body validity (priority 4).
        h.require_enum(body["device_type"], dom.DEVICE_TYPES, "device_type")
        h.require_number(body["prescribed_pressure_cmh2o"],
                         "prescribed_pressure_cmh2o")
        if body["prescribed_pressure_cmh2o"] <= 0:
            raise err("ERR_INVALID_REQUEST",
                      "prescribed_pressure_cmh2o must be > 0")
        expected_version = body.get("expected_supersedes_version")
        if predecessor is not None:
            # expected_supersedes_version required when resupply.
            if expected_version is None:
                raise err("ERR_INVALID_REQUEST",
                          "expected_supersedes_version required for resupply")
            h.require_int(expected_version, "expected_supersedes_version")
            # Resupply integrity (priority 13): predecessor FULFILLED + same study.
            if (predecessor["status"] != "FULFILLED"
                    or predecessor["study_order_id"] != study["id"]):
                raise err("ERR_RESUPPLY_PREDECESSOR_INVALID",
                          "Resupply predecessor must be FULFILLED and share the "
                          "same study_order_id")
            # OCC (priority 14).
            if expected_version != predecessor["version"]:
                raise err("ERR_STALE_DME_VERSION",
                          "Predecessor DME version is stale")
        cycle = dom.compute_resupply_cycle(supersedes_id)
        rec = {
            "study_order_id": study["id"],
            "supersedes_dme_order_id": supersedes_id,
            "device_type": body["device_type"],
            "prescribed_pressure_cmh2o": body["prescribed_pressure_cmh2o"],
            "resupply_cycle_number": cycle,
            "status": "DRAFT",
        }
        db.stamp_new(rec)
        db.dme_orders[rec["id"]] = rec
        # Resupply mutates predecessor: bump version.
        if predecessor is not None:
            db.touch(predecessor)
        return success(dom.ser_dme(rec), 201)


@app.route("/dme-orders", methods=["GET"])
def list_dme_orders():
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator"])
        limit, offset = h.parse_pagination()
        study_order_id = request.args.get("study_order_id")
        supersedes_id = request.args.get("supersedes_dme_order_id")
        status = request.args.get("status")
        items = list(db.dme_orders.values())
        if study_order_id:
            items = [d for d in items if d["study_order_id"] == study_order_id]
        if supersedes_id:
            items = [d for d in items
                     if d["supersedes_dme_order_id"] == supersedes_id]
        if status:
            items = [d for d in items if d["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_dme(x) for x in page], 200, pg)


@app.route("/dme-orders/<did>", methods=["GET"])
def get_dme_order(did):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator"])
        d = dom.get_or_404(db.dme_orders, did, "ERR_DME_NOT_FOUND")
        return success(dom.ser_dme(d), 200)


@app.route("/dme-orders/<did>/submit", methods=["POST"])
def dme_submit(did):
    with lock:
        auth(["DMECoordinator"])
        d = dom.get_or_404(db.dme_orders, did, "ERR_DME_NOT_FOUND")
        # State (priority 5): DRAFT.
        if d["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "DME order not in DRAFT")
        study = db.study_orders[d["study_order_id"]]
        # Cross-entity gate (priority 6): study INTERPRETED.
        if study["status"] != "INTERPRETED":
            raise err("ERR_STUDY_NOT_INTERPRETED",
                      "Linked study is not INTERPRETED")
        # CPAP gate (priority 11): the FINALIZED report recommends CPAP.
        finalized = [r for r in db.scoring_reports.values()
                     if r["study_order_id"] == study["id"]
                     and r["status"] == "FINALIZED"]
        recommends = any(r["physician_recommends_cpap"] for r in finalized)
        if not recommends:
            raise err("ERR_CPAP_NOT_RECOMMENDED",
                      "The study's interpretation does not recommend CPAP")
        d["status"] = "SUBMITTED"
        db.touch(d)
        return success(dom.ser_dme(d), 200)


@app.route("/dme-orders/<did>/fulfill", methods=["POST"])
def dme_fulfill(did):
    with lock:
        auth(["DMECoordinator"])
        d = dom.get_or_404(db.dme_orders, did, "ERR_DME_NOT_FOUND")
        if d["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "DME order not in SUBMITTED")
        d["status"] = "FULFILLED"
        db.touch(d)
        return success(dom.ser_dme(d), 200)


@app.route("/dme-orders/<did>/cancel", methods=["POST"])
def dme_cancel(did):
    with lock:
        auth(["DMECoordinator"])
        d = dom.get_or_404(db.dme_orders, did, "ERR_DME_NOT_FOUND")
        if d["status"] not in ("DRAFT", "SUBMITTED"):
            raise err("ERR_DME_NOT_CANCELLABLE",
                      "DME order can only be cancelled from DRAFT or SUBMITTED")
        d["status"] = "CANCELLED"
        db.touch(d)
        return success(dom.ser_dme(d), 200)


@app.route("/dme-orders/<did>/compliance-records", methods=["GET"])
def list_dme_compliance_records(did):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        dom.get_or_404(db.dme_orders, did, "ERR_DME_NOT_FOUND")
        limit, offset = h.parse_pagination()
        items = [c for c in db.compliance_records.values()
                 if c["dme_order_id"] == did]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_compliance(x) for x in page], 200, pg)


# ===========================================================================
# ComplianceRecord
# ===========================================================================
@app.route("/compliance-records", methods=["POST"])
def create_compliance_record():
    with lock:
        auth(["DMECoordinator"])
        body = h.get_json_body()
        # Existence (priority 3): dme_order_id FK.
        h.require_fields(body, ["dme_order_id", "window_start_utc",
                                "window_end_utc", "nights_used_4h_plus",
                                "total_usage_minutes"])
        h.require_string(body["dme_order_id"], "dme_order_id")
        dme = dom.get_or_404(db.dme_orders, body["dme_order_id"],
                             "ERR_DME_NOT_FOUND")
        # Body validity (priority 4).
        h.require_string(body["window_start_utc"], "window_start_utc")
        h.require_string(body["window_end_utc"], "window_end_utc")
        h.require_int(body["nights_used_4h_plus"], "nights_used_4h_plus")
        h.require_int(body["total_usage_minutes"], "total_usage_minutes")
        if body["nights_used_4h_plus"] < 0:
            raise err("ERR_INVALID_REQUEST", "nights_used_4h_plus must be >= 0")
        if body["total_usage_minutes"] < 0:
            raise err("ERR_INVALID_REQUEST", "total_usage_minutes must be >= 0")
        start_dt = h.parse_iso(body["window_start_utc"], "window_start_utc")
        end_dt = h.parse_iso(body["window_end_utc"], "window_end_utc")
        if not (end_dt > start_dt):
            raise err("ERR_INVALID_REQUEST",
                      "window_end_utc must be strictly after window_start_utc")
        # State (priority 5): the device must be FULFILLED.
        if dme["status"] != "FULFILLED":
            raise err("ERR_INVALID_STATE", "DME order is not FULFILLED")
        # Window overlap (priority 10): half-open intervals, same DMEOrder.
        new_start_ms = h.epoch_ms(start_dt)
        new_end_ms = h.epoch_ms(end_dt)
        for c in db.compliance_records.values():
            if c["dme_order_id"] != dme["id"]:
                continue
            ex_start = h.epoch_ms(h.parse_iso(c["window_start_utc"]))
            ex_end = h.epoch_ms(h.parse_iso(c["window_end_utc"]))
            # Half-open overlap: touching endpoints do NOT overlap.
            if new_start_ms < ex_end and ex_start < new_end_ms:
                raise err("ERR_COMPLIANCE_WINDOW_OVERLAP",
                          "Window overlaps an existing window for this device")
        adherent = dom.compute_adherence(start_dt, end_dt,
                                         body["nights_used_4h_plus"],
                                         body["total_usage_minutes"])
        rec = {
            "dme_order_id": dme["id"],
            "window_start_utc": body["window_start_utc"],
            "window_end_utc": body["window_end_utc"],
            "nights_used_4h_plus": body["nights_used_4h_plus"],
            "total_usage_minutes": body["total_usage_minutes"],
            "adherent": adherent,
        }
        db.stamp_new(rec)
        db.compliance_records[rec["id"]] = rec
        return success(dom.ser_compliance(rec), 201)


@app.route("/compliance-records/<cid>", methods=["GET"])
def get_compliance_record(cid):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        c = dom.get_or_404(db.compliance_records, cid, "ERR_COMPLIANCE_NOT_FOUND")
        return success(dom.ser_compliance(c), 200)


# ===========================================================================
# FollowUp
# ===========================================================================
@app.route("/follow-ups", methods=["POST"])
def create_follow_up():
    with lock:
        auth(["SchedulingCoordinator"])
        body = h.get_json_body()
        # Existence (priority 3): study_order_id FK.
        h.require_fields(body, ["study_order_id", "scheduled_for_utc"])
        h.require_string(body["study_order_id"], "study_order_id")
        study = dom.get_or_404(db.study_orders, body["study_order_id"],
                               "ERR_STUDY_NOT_FOUND")
        # Body validity (priority 4).
        h.require_string(body["scheduled_for_utc"], "scheduled_for_utc")
        h.parse_iso(body["scheduled_for_utc"], "scheduled_for_utc")
        # State (priority 5): the study must be INTERPRETED.
        if study["status"] != "INTERPRETED":
            raise err("ERR_INVALID_STATE", "Linked study is not INTERPRETED")
        rec = {
            "study_order_id": study["id"],
            "scheduled_for_utc": body["scheduled_for_utc"],
            "post_treatment_epworth_score": None,
            "epworth_improvement": None,
            "status": "SCHEDULED",
        }
        db.stamp_new(rec)
        db.follow_ups[rec["id"]] = rec
        return success(dom.ser_followup(rec), 201)


@app.route("/follow-ups/<fid>", methods=["GET"])
def get_follow_up(fid):
    with lock:
        auth(["SchedulingCoordinator", "Physician", "DMECoordinator", "Patient"])
        f = dom.get_or_404(db.follow_ups, fid, "ERR_FOLLOWUP_NOT_FOUND")
        return success(dom.ser_followup(f), 200)


@app.route("/follow-ups/<fid>/complete", methods=["POST"])
def follow_up_complete(fid):
    with lock:
        auth(["SchedulingCoordinator"])
        f = dom.get_or_404(db.follow_ups, fid, "ERR_FOLLOWUP_NOT_FOUND")
        body = h.get_json_body()
        h.require_fields(body, ["post_treatment_epworth_score"])
        h.require_int(body["post_treatment_epworth_score"],
                      "post_treatment_epworth_score")
        score = body["post_treatment_epworth_score"]
        if score < 0 or score > 24:
            raise err("ERR_INVALID_REQUEST",
                      "post_treatment_epworth_score must be 0..24")
        # State (priority 5): SCHEDULED.
        if f["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Follow-up not in SCHEDULED")
        f["post_treatment_epworth_score"] = score
        f["epworth_improvement"] = dom.compute_epworth_delta(f, score)
        f["status"] = "COMPLETED"
        db.touch(f)
        return success(dom.ser_followup(f), 200)


@app.route("/follow-ups/<fid>/no-show", methods=["POST"])
def follow_up_no_show(fid):
    with lock:
        auth(["SchedulingCoordinator"])
        f = dom.get_or_404(db.follow_ups, fid, "ERR_FOLLOWUP_NOT_FOUND")
        if f["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Follow-up not in SCHEDULED")
        f["status"] = "NO_SHOW"
        db.touch(f)
        return success(dom.ser_followup(f), 200)


@app.route("/follow-ups/<fid>/cancel", methods=["POST"])
def follow_up_cancel(fid):
    with lock:
        auth(["SchedulingCoordinator"])
        f = dom.get_or_404(db.follow_ups, fid, "ERR_FOLLOWUP_NOT_FOUND")
        if f["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Follow-up not in SCHEDULED")
        f["status"] = "CANCELLED"
        db.touch(f)
        return success(dom.ser_followup(f), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
