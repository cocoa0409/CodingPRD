"""Discharge referral intake and the ordered intake gauntlet (PRD 3.1)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("referrals", __name__)


def new_risk_assessment(episode, referral, inputs, supersedes_id):
    components = domain.risk_components(
        referral["stay_type"],
        referral["length_of_stay_days"],
        referral["length_of_stay_hours"],
        referral["admission_acuity"],
        inputs["comorbidity_count"],
        inputs["prior_ed_visits_6mo"],
        inputs["prior_admissions_6mo"],
        inputs["social_risk_flags_count"],
    )
    fields = {
        "episode_id": episode["id"],
        "supersedes_id": supersedes_id,
        "stay_type": referral["stay_type"],
        "length_of_stay_days": referral["length_of_stay_days"],
        "length_of_stay_hours": referral["length_of_stay_hours"],
        "admission_acuity": referral["admission_acuity"],
        "comorbidity_count": inputs["comorbidity_count"],
        "prior_ed_visits_6mo": inputs["prior_ed_visits_6mo"],
        "prior_admissions_6mo": inputs["prior_admissions_6mo"],
        "social_risk_flags_count": inputs["social_risk_flags_count"],
    }
    fields.update(components)
    fields["risk_tier"] = domain.risk_tier(components["risk_score"])
    fields["is_current"] = True
    fields["assessed_at"] = store.now()
    return store.new_row("risk_assessments", fields)


# ------------------------------------------------------------------- create
@bp.post("/tcm/referrals")
def create_referral():
    G.auth(["IntakeCoordinator"])
    data = G.body()

    patient_id = G.req_string(data, "patient_id")
    facility_id = G.req_string(data, "facility_id")
    payer_id = G.req_string(data, "payer_id")
    discharge_date = G.req_date(data, "discharge_date")
    discharge_datetime = G.req_instant(data, "discharge_datetime")
    discharge_disposition = G.req_string(data, "discharge_disposition")
    stay_type = G.req_string(data, "stay_type")
    los_days = None
    los_hours = None
    if stay_type == "INPATIENT":
        los_days = G.req_int(data, "length_of_stay_days", minimum=0, maximum=90)
    elif stay_type == "OBSERVATION":
        los_hours = G.req_int(data, "length_of_stay_hours", minimum=0, maximum=240)
    admission_acuity = G.req_string(data, "admission_acuity")
    comorbidity_count = G.req_int(data, "comorbidity_count", minimum=0, maximum=30)
    prior_ed_visits_6mo = G.req_int(data, "prior_ed_visits_6mo", minimum=0, maximum=30)
    prior_admissions_6mo = G.req_int(data, "prior_admissions_6mo", minimum=0, maximum=30)
    social_risk_flags_count = G.req_int(data, "social_risk_flags_count", minimum=0, maximum=12)

    G.enum(discharge_disposition, C.DISCHARGE_DISPOSITIONS, "discharge_disposition")
    G.enum(stay_type, C.STAY_TYPES, "stay_type")
    G.enum(admission_acuity, C.ADMISSION_ACUITIES, "admission_acuity")

    G.get_row("patients", patient_id)
    G.get_row("facilities", facility_id)
    G.get_row("payers", payer_id)

    row = store.new_row(
        "referrals",
        {
            "patient_id": patient_id,
            "facility_id": facility_id,
            "payer_id": payer_id,
            "discharge_date": discharge_date,
            "discharge_datetime": discharge_datetime,
            "discharge_disposition": discharge_disposition,
            "stay_type": stay_type,
            "length_of_stay_days": los_days,
            "length_of_stay_hours": los_hours,
            "admission_acuity": admission_acuity,
            "comorbidity_count": comorbidity_count,
            "prior_ed_visits_6mo": prior_ed_visits_6mo,
            "prior_admissions_6mo": prior_admissions_6mo,
            "social_risk_flags_count": social_risk_flags_count,
            "referred_at": store.now(),
            "status": "RECEIVED",
            "closure_reason_code": None,
            "created_episode_id": None,
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/referrals/<referral_id>")
def read_referral(referral_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("referrals", referral_id)))


@bp.get("/tcm/referrals")
def list_referrals():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("patient_id", "facility_id", "payer_id", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("referrals", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


# ------------------------------------------------------------------- accept
@bp.post("/tcm/referrals/<referral_id>/accept")
def accept_referral(referral_id):
    G.auth(["IntakeCoordinator"])
    data = G.body()
    navigator_id = G.req_string(data, "navigator_id")

    referral = G.get_row("referrals", referral_id)
    navigator = G.get_row("navigators", navigator_id)

    if referral["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED referral may be accepted.")

    # --- the ordered intake gauntlet (rungs 13-17) -------------------------
    if referral["discharge_disposition"] not in C.ELIGIBLE_DISPOSITIONS:
        raise ApiError("ERR_DISPOSITION_INELIGIBLE")

    referred_date = referral["referred_at"].date().isoformat()
    if store.day_diff(referred_date, referral["discharge_date"]) > C.INTAKE_WINDOW_DAYS:
        raise ApiError("ERR_INTAKE_WINDOW_EXPIRED")

    patient = DB["patients"][referral["patient_id"]]
    if patient["open_episode_count"] != 0:
        raise ApiError("ERR_EPISODE_ALREADY_OPEN")

    payer = DB["payers"][referral["payer_id"]]
    if not payer["tcm_covered"]:
        raise ApiError("ERR_PAYER_NOT_COVERED")

    facility = DB["facilities"][referral["facility_id"]]
    if facility["network_status"] != "IN_NETWORK":
        raise ApiError("ERR_FACILITY_OUT_OF_NETWORK")

    # --- mint the episode and everything hanging off it --------------------
    episode = store.new_row(
        "episodes",
        {
            "referral_id": referral["id"],
            "patient_id": referral["patient_id"],
            "payer_id": referral["payer_id"],
            "facility_id": referral["facility_id"],
            "navigator_id": navigator_id,
            "discharge_date": referral["discharge_date"],
            "discharge_datetime": referral["discharge_datetime"],
            "status": "INTAKE",
            "record_posture": "OPEN",
            "pre_readmission_status": None,
            "risk_score": None,
            "risk_tier": None,
            "current_risk_assessment_id": None,
            "contact_sla_business_days": None,
            "contact_deadline_at": None,
            "contact_status": "NOT_STARTED",
            "contact_attempt_count": 0,
            "successful_contact_at": None,
            "contact_timely": False,
            "required_visit_complexity": None,
            "visit_due_date": None,
            "visit_completed_at": None,
            "visit_timely": False,
            "medrec_complete": False,
            "service_period_end_date": store.add_days(referral["discharge_date"], 29),
            "readmission_window_end_date": store.add_days(
                referral["discharge_date"], C.READMISSION_WINDOW_DAYS
            ),
            "readmission_event_count": 0,
            "counted_readmission_count": 0,
            "excluded_readmission_count": 0,
            "retracted_readmission_count": 0,
            "open_red_flag_count": 0,
            "escalation_state": "NONE",
            "billing_eligible": True,
            "recoupment_required": False,
            "claim_id": None,
            "_flags_frozen": False,
        },
    )

    assessment = new_risk_assessment(
        episode,
        referral,
        {
            "comorbidity_count": referral["comorbidity_count"],
            "prior_ed_visits_6mo": referral["prior_ed_visits_6mo"],
            "prior_admissions_6mo": referral["prior_admissions_6mo"],
            "social_risk_flags_count": referral["social_risk_flags_count"],
        },
        None,
    )
    domain.apply_tier_to_episode(episode, assessment)

    referral["status"] = "ACCEPTED"
    referral["created_episode_id"] = episode["id"]
    store.touch(referral)

    domain.recompute_patient(referral["patient_id"])
    domain.recompute_navigator(navigator["id"])

    return envelope.ok(serialize(referral))


# -------------------------------------------------------------------- close
@bp.post("/tcm/referrals/<referral_id>/close")
def close_referral(referral_id):
    G.auth(["IntakeCoordinator"])
    data = G.body()
    outcome = G.req_string(data, "outcome")
    closure_reason_code = G.req_string(data, "closure_reason_code")
    G.validation_enum(closure_reason_code, C.CLOSURE_REASON_CODES, "closure_reason_code")
    G.enum(outcome, C.REFERRAL_CLOSE_OUTCOMES, "outcome")

    referral = G.get_row("referrals", referral_id)
    if referral["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED referral may be closed.")

    referral["status"] = outcome
    referral["closure_reason_code"] = closure_reason_code
    store.touch(referral)
    return envelope.ok(serialize(referral))
