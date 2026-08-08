"""Sleep studies and referrals."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_frozen, in_scope, new_row, path_row,
                    require_identity, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, clock_date, day_span, dec

bp = Blueprint("clinical", __name__)


# ----------------------------------------------------------- sleep studies

@bp.post("/sleep-studies")
def create_sleep_study():
    uid, role = actor(["SleepPhysician"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "ordering_physician_id", "appliance_id"])
    gate_frozen(refs["patient_id"])
    # Scope bootstrapping: the ordering physician establishes his own scope by
    # naming himself; naming a different provider is refused here.
    if body.get("ordering_physician_id") is not None and body["ordering_physician_id"] != uid:
        fail("ERR_NOT_CARE_TEAM", "A physician may only order a study naming himself.")
    fields = [
        v.S("patient_id", required=True),
        v.S("ordering_physician_id", required=True),
        v.S("modality", required=True, enum=v.ENUM_MODALITY),
        v.S("study_purpose", required=True, enum=v.ENUM_STUDY_PURPOSE),
        v.S("appliance_id"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if body["study_purpose"] == "EFFICACY" and body.get("appliance_id") is None:
        fail("ERR_VALIDATION", "An efficacy study must name the appliance it is testing.")
    if body["study_purpose"] == "DIAGNOSTIC" and body.get("appliance_id") is not None:
        fail("ERR_VALIDATION", "A diagnostic study must not name an appliance.")
    physician = refs["ordering_physician_id"]
    if physician["provider_type"] != "SLEEP_PHYSICIAN" or physician["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "ordering_physician_id must be an ACTIVE SLEEP_PHYSICIAN.")
    row = new_row("sleep_studies", {
        "patient_id": body["patient_id"],
        "ordering_physician_id": body["ordering_physician_id"],
        "appliance_id": body.get("appliance_id"),
        "modality": body["modality"],
        "study_purpose": body["study_purpose"],
        "performed_on": None,
        "respiratory_events": None,
        "recording_minutes": None,
        "sleep_minutes": None,
        "artifact_pct": None,
        "attended": None,
        "severity_index": None,
        "severity_band": None,
        "repeat_count": 0,
        "status": "ORDERED",
    })
    return created(dump("sleep_study", row))


@bp.get("/sleep-studies/<study_id>")
def read_sleep_study(study_id):
    uid, role = actor(["SleepPhysician", "Dentist", "ClinicCoordinator", "PlatformAdmin"])
    row = path_row("study_id", study_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("sleep_study", row))


@bp.get("/sleep-studies")
def list_sleep_studies():
    uid, role = actor(["SleepPhysician", "Dentist", "ClinicCoordinator", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "ordering_physician_id": request.args.get("ordering_physician_id"),
        "appliance_id": request.args.get("appliance_id"),
        "study_purpose": request.args.get("study_purpose"),
        "status": request.args.get("status"),
    }
    return domain.paginate("sleep_study", "sleep_studies", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/sleep-studies/<study_id>/results")
def post_results(study_id):
    uid, role = actor(["SleepPhysician"])
    study = path_row("study_id", study_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(study["patient_id"]))
    require_identity(uid, study["ordering_physician_id"])
    fields = [
        v.D("performed_on", required=True),
        v.I("respiratory_events", required=True),
        v.I("recording_minutes", required=True),
        v.I("sleep_minutes"),
        v.N("artifact_pct"),
        v.B("attended"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    performed_on = v.date_of(body, "performed_on")
    v.at_least(body, "respiratory_events", 0)
    v.at_least(body, "recording_minutes", 0)
    v.at_least(body, "sleep_minutes", 0)
    v.between(body, "artifact_pct", 0, 100)
    sleep_minutes = body.get("sleep_minutes")
    if sleep_minutes is not None and sleep_minutes > body["recording_minutes"]:
        fail("ERR_VALIDATION", "sleep_minutes may not exceed recording_minutes.")
    artifact_pct = v.get(body, "artifact_pct", 0)
    attended = v.get(body, "attended", False)
    denominator = calc.severity_denominator_hours(
        study["modality"], body["recording_minutes"], sleep_minutes)
    if denominator is None or denominator <= 0:
        fail("ERR_VALIDATION", "The severity denominator must be greater than zero.")
    if study["status"] != "ORDERED":
        fail("ERR_INVALID_STATE", "Only an ORDERED study may be resulted.")

    study["performed_on"] = performed_on
    study["respiratory_events"] = body["respiratory_events"]
    study["recording_minutes"] = body["recording_minutes"]
    study["sleep_minutes"] = sleep_minutes
    study["artifact_pct"] = artifact_pct
    study["attended"] = attended
    index = calc.severity_index(body["respiratory_events"], denominator)
    study["severity_index"] = index
    valid = calc.study_is_diagnostic(study["modality"], body["recording_minutes"],
                                     artifact_pct, sleep_minutes, attended)
    if valid:
        study["status"] = "DIAGNOSTIC_VALID"
        study["severity_band"] = calc.severity_band(index)
    else:
        study["status"] = "NON_DIAGNOSTIC"
        study["severity_band"] = None
    touch(study)
    return ok(dump("sleep_study", study))


@bp.post("/sleep-studies/<study_id>/reorder")
def reorder_study(study_id):
    uid, role = actor(["SleepPhysician"])
    study = path_row("study_id", study_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(study["patient_id"]))
    require_identity(uid, study["ordering_physician_id"])
    fields = [v.S("modality", enum=v.ENUM_MODALITY)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if study["status"] != "NON_DIAGNOSTIC":
        fail("ERR_INVALID_STATE", "Only a NON_DIAGNOSTIC study may be re-ordered.")
    if body.get("modality") is not None:
        study["modality"] = body["modality"]
    study["status"] = "ORDERED"
    study["repeat_count"] = study["repeat_count"] + 1
    for field in ("performed_on", "respiratory_events", "recording_minutes", "sleep_minutes",
                  "artifact_pct", "attended", "severity_index", "severity_band"):
        study[field] = None
    touch(study)
    return ok(dump("sleep_study", study))


# --------------------------------------------------------------- referrals

@bp.post("/referrals")
def create_referral():
    uid, role = actor(["SleepPhysician"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "referring_physician_id",
                            "treating_dentist_id", "diagnostic_study_id"])
    gate_frozen(refs["patient_id"])
    if body.get("referring_physician_id") is not None and body["referring_physician_id"] != uid:
        fail("ERR_NOT_CARE_TEAM", "A physician may only refer naming himself.")
    fields = [
        v.S("patient_id", required=True),
        v.S("referring_physician_id", required=True),
        v.S("treating_dentist_id", required=True),
        v.S("diagnostic_study_id", required=True),
        v.S("cpap_history", enum=v.ENUM_CPAP_HISTORY),
        v.I("cpap_nights_used"),
        v.D("cpap_documented_on"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    cpap_documented_on = v.date_of(body, "cpap_documented_on")
    v.at_least(body, "cpap_nights_used", 0)

    if body["treating_dentist_id"] == body["referring_physician_id"]:
        fail("ERR_SELF_REFERRAL", "The treating dentist may not be the referring physician.")

    physician = refs["referring_physician_id"]
    dentist = refs["treating_dentist_id"]
    if physician["provider_type"] != "SLEEP_PHYSICIAN" or physician["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "referring_physician_id must be an ACTIVE SLEEP_PHYSICIAN.")
    if dentist["provider_type"] != "DENTIST" or dentist["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "treating_dentist_id must be an ACTIVE DENTIST.")

    study = refs["diagnostic_study_id"]
    if study["status"] != "DIAGNOSTIC_VALID":
        fail("ERR_STUDY_NON_DIAGNOSTIC", "The grounding study is not DIAGNOSTIC_VALID.")
    if study["study_purpose"] != "DIAGNOSTIC" or study["severity_band"] not in ("MILD", "MODERATE", "SEVERE"):
        fail("ERR_DIAGNOSIS_REQUIRED", "The grounding study carries no OSA diagnosis.")

    patient = refs["patient_id"]
    band = study["severity_band"]
    cpap_history = v.get(body, "cpap_history", "NONE")
    cpap_nights_used = v.get(body, "cpap_nights_used", 0)
    if band == "SEVERE":
        documented = cpap_history in ("FAILURE", "INTOLERANCE", "REFUSAL")
        trial_ok = (cpap_history == "REFUSAL") or (cpap_nights_used >= calc.MIN_CPAP_TRIAL_NIGHTS)
        fresh = (cpap_documented_on is not None
                 and day_span(cpap_documented_on, clock_date()) <= calc.CPAP_LOOKBACK_DAYS)
        if not (documented and trial_ok and fresh):
            fail("ERR_CPAP_TRIAL_REQUIRED", "Severe apnoea requires a documented, fresh PAP trial.")
        eligibility_basis = "CPAP_INTOLERANT_SEVERE"
    elif band == "MODERATE":
        eligibility_basis = "FIRST_LINE_MILD_MODERATE"
    else:
        if not (patient["epworth_score"] >= calc.MIN_SYMPTOM_SCORE or cpap_history != "NONE"):
            fail("ERR_CPAP_TRIAL_REQUIRED", "Mild apnoea requires symptoms or a PAP history.")
        eligibility_basis = "FIRST_LINE_MILD_MODERATE"

    row = new_row("referrals", {
        "patient_id": body["patient_id"],
        "referring_physician_id": body["referring_physician_id"],
        "treating_dentist_id": body["treating_dentist_id"],
        "diagnostic_study_id": body["diagnostic_study_id"],
        "cpap_history": cpap_history,
        "cpap_nights_used": cpap_nights_used,
        "cpap_documented_on": cpap_documented_on,
        "severity_band_at_referral": band,
        "eligibility_basis": eligibility_basis,
        "diagnosis_valid_until": calc.diagnosis_valid_until(study["modality"], study["performed_on"]),
        "loop_status": "OPEN",
        "status": "ISSUED",
    })
    return created(dump("referral", row))


@bp.get("/referrals/<referral_id>")
def read_referral(referral_id):
    uid, role = actor(["SleepPhysician", "Dentist", "ClinicCoordinator",
                       "BillingSpecialist", "PlatformAdmin"])
    row = path_row("referral_id", referral_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("referral", row))


@bp.get("/referrals")
def list_referrals():
    uid, role = actor(["SleepPhysician", "Dentist", "ClinicCoordinator",
                       "BillingSpecialist", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "referring_physician_id": request.args.get("referring_physician_id"),
        "treating_dentist_id": request.args.get("treating_dentist_id"),
        "diagnostic_study_id": request.args.get("diagnostic_study_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("referral", "referrals", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/referrals/<referral_id>/respond")
def respond_referral(referral_id):
    uid, role = actor(["Dentist"])
    referral = path_row("referral_id", referral_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(referral["patient_id"]))
    require_identity(uid, referral["treating_dentist_id"])
    fields = [
        v.S("decision", required=True, enum=v.ENUM_REFERRAL_DECISION),
        v.S("reason"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if referral["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED referral may be answered.")
    domain.rung18_diagnosis_currency(referral)
    referral["status"] = "ACCEPTED" if body["decision"] == "ACCEPTED" else "DECLINED"
    touch(referral)
    return ok(dump("referral", referral))
