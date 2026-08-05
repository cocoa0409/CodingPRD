"""The chairside encounter: registration, screening, exam, close and billing."""

from flask import Blueprint

import calc
import cascades
import clock
import gates
import serializers
import store
import validation as v
from constants import (
    CONSENT_TIER_RANK,
    ENUM_ADJUDICATE_OUTCOME,
    ENUM_EXAM_MODALITY,
    PROCEDURE_CHAIR_MINUTES,
    PROCEDURE_FEE_SCHEDULE_CENTS,
    PROCEDURE_REQUIRED_TIER,
    TELEDENTISTRY_REVIEW_WINDOW_HOURS,
)
from envelope import array_response, object_response
from errors import ApiError
from timefmt import add_hours

bp = Blueprint("encounters", __name__)


def _auto_procedure(encounter, visit, code, staff_id):
    """The PERFORMED D0190 / D0150 row that screening and exam auto-create."""
    latest_load = calc.latest_load_for_unit(visit["portable_unit_id"])
    row = store.insert("procedures", {
        "encounter_id": encounter["id"],
        "treatment_plan_id": None,
        "sterilization_load_id": latest_load["id"] if latest_load else None,
        "performing_staff_id": staff_id,
        "procedure_code": code,
        "tooth_number": None,
        "surface": None,
        "required_tier": PROCEDURE_REQUIRED_TIER[code],
        "chair_minutes": PROCEDURE_CHAIR_MINUTES[code],
        "charge_cents": PROCEDURE_FEE_SCHEDULE_CENTS[code],
        "status": "PERFORMED",
        "performed_at": clock.now(),
        "taint_reason": None,
        "void_reason": None,
        "_auto_created": True,
    })
    v.mark_minted(row)
    return row


def _chair_capacity_gate(visit, additional_minutes):
    if calc.booked_chair_minutes(visit["id"]) + additional_minutes > visit["capacity_chair_minutes"]:
        raise ApiError("ERR_CHAIR_CAPACITY_EXCEEDED")


def _tier_gate(consent, code):
    if CONSENT_TIER_RANK[PROCEDURE_REQUIRED_TIER[code]] > CONSENT_TIER_RANK[consent["scope_tier"]]:
        raise ApiError("ERR_CONSENT_TIER_INSUFFICIENT")


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters", methods=["POST"])
def create_encounter():
    v.authenticate(["DentalAssistant", "FieldHygienist", "FieldDentist", "SiteCoordinator"])
    body = v.body()
    visit = v.fk_row(body, "site_visit_id", "site_visits")
    patient = v.fk_row(body, "patient_id", "patients")
    consent = v.fk_row(body, "consent_id", "consents")
    coverage = v.fk_row(body, "coverage_id", "coverages")

    for field in ("site_visit_id", "patient_id", "consent_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    if body.get("coverage_id") is not None and not isinstance(body.get("coverage_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'coverage_id' must be a string.")
    expected_site_visit_version = v.req_int(body, "expected_site_visit_version")

    gates.period_gate(visit["program_period_id"])
    site = store.get("sites", visit["site_id"])
    gates.site_hold_gate(site, visit["scheduled_start_at"], visit["scheduled_end_at"])

    if expected_site_visit_version != visit["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if consent["patient_id"] != patient["id"] or consent["site_id"] != visit["site_id"]:
        raise ApiError("ERR_CONSENT_MISSING")

    gates.consent_revoked_gate(consent)
    gates.consent_expiry_sweep(consent)

    row = store.insert("encounters", {
        "site_visit_id": visit["id"],
        "patient_id": patient["id"],
        "consent_id": consent["id"],
        "coverage_id": coverage["id"] if coverage else None,
        "clinical_status": "REGISTERED",
        "billing_status": "UNBILLED",
        "triage_band": None,
        "cavitated_lesion_count": None,
        "pain_reported": None,
        "abscess_or_swelling": None,
        "untreated_decay_present": None,
        "denture_problem": None,
        "oral_hygiene_score": None,
        "medical_complexity_count": None,
        "exam_modality": None,
        "teledentistry_reviewed_at": None,
        "subtotal_cents": 0,
        "supply_surcharge_cents": 0,
        "total_charge_cents": 0,
        "allowed_amount_cents": 0,
        "patient_responsibility_cents": 0,
        "plan_paid_cents": 0,
        "write_off_cents": 0,
        "pricing_regime": None,
        "deferred_reason": None,
        "denial_reason": None,
    })
    v.mark_minted(row)
    v.touch(visit)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 201)


@bp.route("/mobile-dentistry/encounters", methods=["GET"])
def list_encounters():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("encounters"), {
        "site_visit_id": "site_visit_id",
        "patient_id": "patient_id",
        "consent_id": "consent_id",
        "coverage_id": "coverage_id",
        "clinical_status": "clinical_status",
        "billing_status": "billing_status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.encounter, page), limit, offset, total)


@bp.route("/mobile-dentistry/encounters/<encounter_id>", methods=["GET"])
def read_encounter(encounter_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    row = v.path_row("encounters", encounter_id)
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/screen
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/screen", methods=["POST"])
def screen_encounter(encounter_id):
    v.authenticate(["FieldHygienist", "FieldDentist"])
    row = v.path_row("encounters", encounter_id)
    body = v.body()
    staff = v.fk_row(body, "performing_staff_id", "staff_members")

    v.need(body, "performing_staff_id")
    if not isinstance(body.get("performing_staff_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'performing_staff_id' must be a string.")
    cavitated_lesion_count = v.req_int(body, "cavitated_lesion_count")
    pain_reported = v.req_bool(body, "pain_reported")
    abscess_or_swelling = v.req_bool(body, "abscess_or_swelling")
    untreated_decay_present = v.req_bool(body, "untreated_decay_present")
    denture_problem = v.opt_bool(body, "denture_problem")
    oral_hygiene_score = v.opt_int(body, "oral_hygiene_score", minimum=0, maximum=4)
    medical_complexity_count = v.opt_int(body, "medical_complexity_count")

    visit = store.get("site_visits", row["site_visit_id"])
    site = store.get("sites", visit["site_id"])
    consent = store.get("consents", row["consent_id"])

    gates.period_gate(visit["program_period_id"])

    if row["clinical_status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE")
    if visit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    if consent["status"] == "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE")

    gates.credential_gate([staff])
    gates.license_state_gate([staff], site)
    if not calc.supervision_permitted("D0190", staff, visit):
        raise ApiError("ERR_SUPERVISION_NOT_PERMITTED")

    gates.consent_revoked_gate(consent)
    gates.consent_expiry_sweep(consent)
    _tier_gate(consent, "D0190")
    _chair_capacity_gate(visit, PROCEDURE_CHAIR_MINUTES["D0190"])

    findings = {
        "cavitated_lesion_count": cavitated_lesion_count,
        "pain_reported": pain_reported,
        "abscess_or_swelling": abscess_or_swelling,
        "untreated_decay_present": untreated_decay_present,
        "denture_problem": denture_problem,
        "oral_hygiene_score": oral_hygiene_score,
        "medical_complexity_count": medical_complexity_count,
    }
    row.update(findings)
    row["triage_band"] = calc.triage_band(site["site_type"], findings)
    row["clinical_status"] = "SCREENED"
    v.touch(row)
    _auto_procedure(row, visit, "D0190", staff["id"])

    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/exam
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/exam", methods=["POST"])
def exam_encounter(encounter_id):
    v.authenticate(["FieldDentist", "FieldHygienist"])
    row = v.path_row("encounters", encounter_id)
    body = v.body()
    staff = v.fk_row(body, "performing_staff_id", "staff_members")

    v.need(body, "performing_staff_id")
    if not isinstance(body.get("performing_staff_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'performing_staff_id' must be a string.")
    v.enum_type_check(body, "exam_modality", required=True)
    reviewed_at = v.opt_instant(body, "teledentistry_reviewed_at")

    exam_modality = v.check_enum(body, "exam_modality", ENUM_EXAM_MODALITY)

    visit = store.get("site_visits", row["site_visit_id"])
    site = store.get("sites", visit["site_id"])
    consent = store.get("consents", row["consent_id"])

    gates.period_gate(visit["program_period_id"])

    if row["clinical_status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE")
    if visit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    if consent["status"] == "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE")

    gates.credential_gate([staff])
    gates.license_state_gate([staff], site)
    if not calc.supervision_permitted("D0150", staff, visit):
        raise ApiError("ERR_SUPERVISION_NOT_PERMITTED")

    if exam_modality == "TELEDENTISTRY":
        window_open = visit["scheduled_start_at"]
        window_close = add_hours(window_open, TELEDENTISTRY_REVIEW_WINDOW_HOURS)
        if reviewed_at is None or reviewed_at < window_open or reviewed_at > window_close:
            raise ApiError("ERR_TELEDENTISTRY_REVIEW_WINDOW")

    gates.consent_revoked_gate(consent)
    gates.consent_expiry_sweep(consent)
    _tier_gate(consent, "D0150")
    _chair_capacity_gate(visit, PROCEDURE_CHAIR_MINUTES["D0150"])

    row["exam_modality"] = exam_modality
    if exam_modality == "TELEDENTISTRY":
        row["teledentistry_reviewed_at"] = reviewed_at
    row["clinical_status"] = "EXAMINED"
    v.touch(row)
    _auto_procedure(row, visit, "D0150", staff["id"])

    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/close
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/close", methods=["POST"])
def close_encounter(encounter_id):
    v.authenticate(["FieldDentist", "FieldHygienist"])
    row = v.path_row("encounters", encounter_id)
    visit = store.get("site_visits", row["site_visit_id"])

    gates.period_gate(visit["program_period_id"])

    if row["clinical_status"] not in ("EXAMINED", "TREATED"):
        raise ApiError("ERR_INVALID_STATE")
    for procedure in calc.encounter_procedures(row["id"]):
        if procedure["status"] == "PLANNED":
            raise ApiError("ERR_INVALID_STATE")

    row["clinical_status"] = "CLOSED"
    v.touch(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/price
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/price", methods=["POST"])
def price_encounter(encounter_id):
    v.authenticate(["BillingSpecialist"])
    row = v.path_row("encounters", encounter_id)
    body = v.body()

    _subtotal, _surcharge, prospective_total = calc.charge_projection(row["id"])
    manual = v.opt_int(
        body, "manual_patient_responsibility_cents", minimum=0, maximum=prospective_total
    )

    visit = store.get("site_visits", row["site_visit_id"])
    gates.period_gate(visit["program_period_id"])

    if row["billing_status"] != "UNBILLED":
        raise ApiError("ERR_INVALID_STATE")
    if row["clinical_status"] not in ("EXAMINED", "TREATED", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")

    tainted = sum(1 for p in calc.encounter_procedures(row["id"]) if p["status"] == "TAINTED")
    if tainted > 0:
        raise ApiError("ERR_PROCEDURE_TAINTED")

    # Rung 35 -- the coverage sweep, mutate-then-reject.
    coverage = store.get("coverages", row["coverage_id"]) if row["coverage_id"] else None
    if coverage is None:
        raise ApiError("ERR_COVERAGE_UNVERIFIED")
    if coverage["verification_status"] == "VERIFIED":
        through = coverage.get("verified_through_date")
        if through is not None and through < clock.today():
            coverage["verification_status"] = "EXPIRED"
            v.touch(coverage)
            raise ApiError("ERR_COVERAGE_UNVERIFIED")
    if coverage["verification_status"] != "VERIFIED":
        raise ApiError("ERR_COVERAGE_UNVERIFIED")

    # Rung 37 -- the Medicaid balance-billing prohibition.
    if manual is not None and coverage["payer_type"] == "MEDICAID_MCO":
        raise ApiError("ERR_MEDICAID_BALANCE_BILL")

    priced = calc.price_encounter(row, coverage, manual)
    row.update(priced)
    row["billing_status"] = "PRICED"
    v.touch(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/claim
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/claim", methods=["POST"])
def claim_encounter(encounter_id):
    v.authenticate(["BillingSpecialist"])
    row = v.path_row("encounters", encounter_id)
    visit = store.get("site_visits", row["site_visit_id"])

    gates.period_gate(visit["program_period_id"])

    if row["billing_status"] not in ("PRICED", "DENIED"):
        raise ApiError("ERR_INVALID_STATE")
    if row["billing_status"] == "PRICED" and row["pricing_regime"] == "MEDICAID_ENCOUNTER_RATE":
        if row["patient_responsibility_cents"] != 0:
            raise ApiError("ERR_INVALID_STATE")

    tainted = sum(1 for p in calc.encounter_procedures(row["id"]) if p["status"] == "TAINTED")
    if tainted > 0:
        raise ApiError("ERR_PROCEDURE_TAINTED")

    row["billing_status"] = "CLAIMED"
    row["denial_reason"] = None
    v.touch(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/encounters/{id}/adjudicate
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/encounters/<encounter_id>/adjudicate", methods=["POST"])
def adjudicate_encounter(encounter_id):
    v.authenticate(["BillingSpecialist"])
    row = v.path_row("encounters", encounter_id)
    body = v.body()
    v.enum_type_check(body, "outcome", required=True)
    denial_reason = v.opt_string(body, "denial_reason")
    outcome = v.check_enum(body, "outcome", ENUM_ADJUDICATE_OUTCOME)

    visit = store.get("site_visits", row["site_visit_id"])
    gates.period_gate(visit["program_period_id"])

    if row["billing_status"] != "CLAIMED":
        raise ApiError("ERR_INVALID_STATE")

    if outcome == "PAID":
        row["billing_status"] = "PAID"
    else:
        row["billing_status"] = "DENIED"
        row["denial_reason"] = denial_reason
    v.touch(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.encounter(row), 200)
