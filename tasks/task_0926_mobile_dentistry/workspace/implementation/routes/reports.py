"""Reporting, disclosure and the programme freeze."""

from flask import Blueprint, g, request

import calc
import cascades
import clock
import gates
import serializers
import store
import validation as v
from constants import ENUM_REPORT_TYPE
from envelope import array_response, object_response
from errors import ApiError
from timefmt import render_date

bp = Blueprint("reports", __name__)

SCREENED_STATUSES = ("SCREENED", "EXAMINED", "TREATED", "CLOSED")
BILLED_STATUSES = ("PRICED", "CLAIMED", "PAID", "DENIED")


# --------------------------------------------------------------------------
# Payload construction (PRD 3.8)
# --------------------------------------------------------------------------
def _in_period_encounters(program_period_id):
    result = []
    for encounter in store.all_rows("encounters"):
        visit = store.get("site_visits", encounter["site_visit_id"])
        if visit is not None and visit["program_period_id"] == program_period_id:
            result.append(encounter)
    return result


def _band_counts(encounters):
    urgent = sum(1 for e in encounters if e["triage_band"] == "URGENT")
    early = sum(1 for e in encounters if e["triage_band"] == "EARLY_CARE_NEEDED")
    none_found = sum(1 for e in encounters if e["triage_band"] == "NO_OBVIOUS_PROBLEM")
    return urgent, early, none_found


def _performed_codes(encounters):
    codes = []
    encounter_ids = {e["id"] for e in encounters}
    for procedure in store.all_rows("procedures"):
        if procedure["encounter_id"] in encounter_ids and procedure["status"] == "PERFORMED":
            codes.append(procedure["procedure_code"])
    return codes


def _plan_follow_up_due_date(encounters):
    encounter_ids = {e["id"] for e in encounters}
    latest = None
    for plan in store.all_rows("treatment_plans"):
        if plan["encounter_id"] in encounter_ids:
            latest = plan
    return render_date(latest["follow_up_due_date"]) if latest is not None else None


def _latest_triage_band(encounters):
    band = None
    for encounter in encounters:
        if encounter["triage_band"] is not None:
            band = encounter["triage_band"]
    return band


def build_payload(report):
    period_id = report["program_period_id"]
    encounters = _in_period_encounters(period_id)

    if report["report_type"] == "PROGRAM_PERIOD":
        screened = {e["patient_id"] for e in encounters if e["clinical_status"] in SCREENED_STATUSES}
        urgent, early, none_found = _band_counts(encounters)
        encounter_ids = {e["id"] for e in encounters}
        varnish = 0
        sealants = 0
        for procedure in store.all_rows("procedures"):
            if procedure["encounter_id"] not in encounter_ids or procedure["status"] != "PERFORMED":
                continue
            if procedure["procedure_code"] == "D1206":
                varnish += 1
            elif procedure["procedure_code"] == "D1351":
                sealants += 1
        plan_ids = {p["id"] for p in store.all_rows("treatment_plans") if p["encounter_id"] in encounter_ids}
        referrals = [r for r in store.all_rows("referrals") if r["treatment_plan_id"] in plan_ids]
        sent = [r for r in referrals if r["attempt_count"] >= 1]
        billed = [e for e in encounters if e["billing_status"] in BILLED_STATUSES]
        return {
            "patients_screened_count": len(screened),
            "urgent_count": urgent,
            "early_care_count": early,
            "no_problem_count": none_found,
            "varnish_applications_count": varnish,
            "sealant_teeth_count": sealants,
            "referrals_sent_count": len(sent),
            "referrals_abandoned_count": sum(1 for r in sent if r["status"] == "ABANDONED"),
            "total_charge_cents": sum(e["total_charge_cents"] for e in billed),
            "total_plan_paid_cents": sum(e["plan_paid_cents"] for e in billed),
            "total_patient_responsibility_cents": sum(e["patient_responsibility_cents"] for e in billed),
            "total_write_off_cents": sum(e["write_off_cents"] for e in billed),
        }

    if report["report_type"] == "FACILITY_ROSTER":
        site = store.get("sites", report["site_id"])
        site_encounters = [
            e for e in encounters
            if (store.get("site_visits", e["site_visit_id"]) or {}).get("site_id") == report["site_id"]
        ]
        urgent, early, none_found = _band_counts(site_encounters)
        lines = []
        for patient in store.all_rows("patients"):
            if patient["site_id"] != report["site_id"]:
                continue
            patient_encounters = [e for e in site_encounters if e["patient_id"] == patient["id"]]
            if not patient_encounters:
                continue
            if site["roster_disclosure_level"] == "CLINICAL_DETAIL":
                lines.append({
                    "patient_id": patient["id"],
                    "external_ref": patient["external_ref"],
                    "triage_band": _latest_triage_band(patient_encounters),
                    "procedure_codes_performed": _performed_codes(patient_encounters),
                    "follow_up_due_date": _plan_follow_up_due_date(patient_encounters),
                })
            else:
                lines.append({
                    "patient_id": patient["id"],
                    "external_ref": patient["external_ref"],
                    "seen": True,
                })
        return {
            "site_id": report["site_id"],
            "roster_disclosure_level": site["roster_disclosure_level"],
            "patient_line_count": len(lines),
            "lines": lines,
            "urgent_count": urgent,
            "early_care_count": early,
            "no_problem_count": none_found,
        }

    patient = store.get("patients", report["patient_id"])
    patient_encounters = [e for e in encounters if e["patient_id"] == report["patient_id"]]
    return {
        "patient_id": report["patient_id"],
        "external_ref": patient["external_ref"] if patient else None,
        "triage_band": _latest_triage_band(patient_encounters),
        "procedure_codes_performed": _performed_codes(patient_encounters),
        "follow_up_due_date": _plan_follow_up_due_date(patient_encounters),
        "patient_responsibility_cents": sum(
            e["patient_responsibility_cents"] for e in patient_encounters
        ),
    }


# --------------------------------------------------------------------------
# POST /mobile-dentistry/reports
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/reports", methods=["POST"])
def create_report():
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    body = v.body()
    period = v.fk_row(body, "program_period_id", "program_periods")
    site = v.fk_row(body, "site_id", "sites")
    patient = v.fk_row(body, "patient_id", "patients")

    v.need(body, "program_period_id")
    if not isinstance(body.get("program_period_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'program_period_id' must be a string.")
    v.enum_type_check(body, "report_type", required=True)
    recipient_user_id = v.opt_string(body, "recipient_user_id")

    report_type = body.get("report_type")
    if report_type in ("FACILITY_ROSTER", "PARENT") and site is None:
        raise ApiError("ERR_VALIDATION", "site_id is required for this report type.")
    if report_type == "PARENT":
        if patient is None:
            raise ApiError("ERR_VALIDATION", "patient_id is required for a PARENT report.")
        if not recipient_user_id:
            raise ApiError("ERR_VALIDATION", "recipient_user_id is required for a PARENT report.")

    report_type = v.check_enum(body, "report_type", ENUM_REPORT_TYPE)

    row = store.insert("reports", {
        "program_period_id": period["id"],
        "site_id": site["id"] if site else None,
        "patient_id": patient["id"] if patient else None,
        "report_type": report_type,
        "recipient_user_id": recipient_user_id,
        "status": "DRAFT",
        "payload": None,
        "generated_at": None,
        "submitted_at": None,
        "stale_reason": None,
    })
    v.mark_minted(row)
    return object_response(serializers.report(row), 201)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/reports
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/reports", methods=["GET"])
def list_reports():
    role, user_id = v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("reports"), {
        "program_period_id": "program_period_id",
        "site_id": "site_id",
        "patient_id": "patient_id",
        "report_type": "report_type",
        "status": "status",
    })
    # Rung 5 -- on the list the coordinator's site scoping is a restriction of
    # the result set rather than an error.
    if role == "SiteCoordinator":
        rows = [r for r in rows if r["site_id"] == user_id]
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.report, page), limit, offset, total)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/reports/{id}
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/reports/<report_id>", methods=["GET"])
def read_report(report_id):
    role, user_id = v.authenticate(["ProgramAdmin", "SiteCoordinator", "Guardian"])
    row = v.path_row("reports", report_id)

    # Rung 4 -- the guardian confidentiality wall.
    if role == "Guardian":
        if row["report_type"] != "PARENT" or row["recipient_user_id"] != user_id:
            raise ApiError("ERR_NOT_FOUND")

    # Rung 5 -- coordinator site scoping on the single-report read.
    if role == "SiteCoordinator":
        if row["site_id"] != user_id:
            raise ApiError("ERR_UNAUTHORIZED")

    return object_response(serializers.report(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/reports/{id}/generate
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/reports/<report_id>/generate", methods=["POST"])
def generate_report(report_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("reports", report_id)

    if row["status"] not in ("DRAFT", "GENERATED", "STALE"):
        raise ApiError("ERR_INVALID_STATE")

    row["payload"] = build_payload(row)
    row["generated_at"] = clock.now()
    row["stale_reason"] = None
    row["status"] = "GENERATED"
    v.touch(row)
    return object_response(serializers.report(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/reports/{id}/submit
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    v.authenticate(["ProgramAdmin"])
    row = v.path_row("reports", report_id)
    body = v.body()
    state_submission_ref = v.req_string(body, "state_submission_ref")

    period = store.get("program_periods", row["program_period_id"])

    # Rung 11 -- SUBMITTED is declared only out of GENERATED; a STALE report is
    # answered one rung lower so that rung 38 stays reachable.
    if row["status"] not in ("GENERATED", "STALE"):
        raise ApiError("ERR_INVALID_STATE")
    if row["report_type"] != "PROGRAM_PERIOD":
        raise ApiError("ERR_INVALID_STATE")
    if period["status"] != "REPORTING":
        raise ApiError("ERR_INVALID_STATE")

    # Rung 38 -- a stale programme report must be regenerated first.
    if row["status"] == "STALE":
        raise ApiError("ERR_REPORT_STALE")

    row["status"] = "SUBMITTED"
    row["submitted_at"] = clock.now()
    v.touch(row)
    period["state_submission_ref"] = state_submission_ref
    cascades.run_report_submission_cascade(period)
    return object_response(serializers.report(row), 200)
