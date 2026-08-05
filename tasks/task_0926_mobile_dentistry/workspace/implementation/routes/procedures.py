"""Procedures: planning, performing and voiding."""

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
    ENUM_SURFACE,
    PROCEDURE_CHAIR_MINUTES,
    PROCEDURE_CODES,
    PROCEDURE_FEE_SCHEDULE_CENTS,
    PROCEDURE_REQUIRED_TIER,
    VARNISH_MAX_APPLICATIONS_PER_PERIOD,
    VARNISH_MIN_INTERVAL_DAYS,
)
from envelope import array_response, object_response
from errors import ApiError
from timefmt import whole_days_between

bp = Blueprint("procedures", __name__)


def _context(procedure_or_encounter):
    encounter = procedure_or_encounter
    visit = store.get("site_visits", encounter["site_visit_id"])
    consent = store.get("consents", encounter["consent_id"])
    site = store.get("sites", visit["site_id"]) if visit else None
    return encounter, visit, consent, site


def _tier_gate(consent, required_tier):
    if CONSENT_TIER_RANK[required_tier] > CONSENT_TIER_RANK[consent["scope_tier"]]:
        raise ApiError("ERR_CONSENT_TIER_INSUFFICIENT")


# --------------------------------------------------------------------------
# POST /mobile-dentistry/procedures
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/procedures", methods=["POST"])
def create_procedure():
    v.authenticate(["FieldDentist", "FieldHygienist"])
    body = v.body()
    encounter = v.fk_row(body, "encounter_id", "encounters")
    plan = v.fk_row(body, "treatment_plan_id", "treatment_plans")

    v.need(body, "encounter_id")
    if not isinstance(body.get("encounter_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'encounter_id' must be a string.")
    v.enum_type_check(body, "procedure_code", required=True)
    expected_encounter_version = v.req_int(body, "expected_encounter_version")
    tooth_number = v.opt_int(body, "tooth_number", minimum=1, maximum=32)
    v.enum_type_check(body, "surface")
    if body.get("treatment_plan_id") is not None and not isinstance(body.get("treatment_plan_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'treatment_plan_id' must be a string.")

    procedure_code = v.check_enum(body, "procedure_code", PROCEDURE_CODES)
    surface = v.check_enum(body, "surface", ENUM_SURFACE)

    _e, visit, consent, _site = _context(encounter)
    gates.period_gate(visit["program_period_id"])

    if expected_encounter_version != encounter["version"]:
        raise ApiError("ERR_STALE_VERSION")

    gates.consent_revoked_gate(consent)
    gates.consent_expiry_sweep(consent)
    _tier_gate(consent, PROCEDURE_REQUIRED_TIER[procedure_code])

    if procedure_code == "D1351":
        if not calc.sealant_eligible(encounter["patient_id"], tooth_number, surface):
            raise ApiError("ERR_SURFACE_INELIGIBLE")

    chair_minutes = PROCEDURE_CHAIR_MINUTES[procedure_code]
    if calc.booked_chair_minutes(visit["id"]) + chair_minutes > visit["capacity_chair_minutes"]:
        raise ApiError("ERR_CHAIR_CAPACITY_EXCEEDED")

    row = store.insert("procedures", {
        "encounter_id": encounter["id"],
        "treatment_plan_id": plan["id"] if plan else None,
        "sterilization_load_id": None,
        "performing_staff_id": None,
        "procedure_code": procedure_code,
        "tooth_number": tooth_number,
        "surface": surface,
        "required_tier": PROCEDURE_REQUIRED_TIER[procedure_code],
        "chair_minutes": chair_minutes,
        "charge_cents": PROCEDURE_FEE_SCHEDULE_CENTS[procedure_code],
        "status": "PLANNED",
        "performed_at": None,
        "taint_reason": None,
        "void_reason": None,
        "_auto_created": False,
    })
    v.mark_minted(row)
    v.touch(encounter)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.procedure(row), 201)


@bp.route("/mobile-dentistry/procedures", methods=["GET"])
def list_procedures():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("procedures"), {
        "encounter_id": "encounter_id",
        "treatment_plan_id": "treatment_plan_id",
        "sterilization_load_id": "sterilization_load_id",
        "performing_staff_id": "performing_staff_id",
        "procedure_code": "procedure_code",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.procedure, page), limit, offset, total)


@bp.route("/mobile-dentistry/procedures/<procedure_id>", methods=["GET"])
def read_procedure(procedure_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    row = v.path_row("procedures", procedure_id)
    return object_response(serializers.procedure(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/procedures/{id}/perform
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/procedures/<procedure_id>/perform", methods=["POST"])
def perform_procedure(procedure_id):
    v.authenticate(["FieldDentist", "FieldHygienist"])
    row = v.path_row("procedures", procedure_id)
    body = v.body()
    staff = v.fk_row(body, "performing_staff_id", "staff_members")
    load = v.fk_row(body, "sterilization_load_id", "sterilization_loads")

    for field in ("performing_staff_id", "sterilization_load_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)

    encounter = store.get("encounters", row["encounter_id"])
    _e, visit, consent, site = _context(encounter)
    gates.period_gate(visit["program_period_id"])

    if row["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    if visit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")

    gates.credential_gate([staff])
    gates.license_state_gate([staff], site)
    if not calc.supervision_permitted(row["procedure_code"], staff, visit):
        raise ApiError("ERR_SUPERVISION_NOT_PERMITTED")

    gates.consent_revoked_gate(consent)
    gates.consent_expiry_sweep(consent)
    _tier_gate(consent, row["required_tier"])

    if row["procedure_code"] == "D1351":
        if not calc.sealant_eligible(
            encounter["patient_id"], row["tooth_number"], row["surface"],
            exclude_procedure_id=row["id"],
        ):
            raise ApiError("ERR_SURFACE_INELIGIBLE")

    if row["procedure_code"] == "D1206":
        count, last_date = calc.varnish_stats(encounter["patient_id"], visit["program_period_id"])
        if last_date is not None:
            if whole_days_between(last_date, clock.today()) < VARNISH_MIN_INTERVAL_DAYS:
                raise ApiError("ERR_VARNISH_INTERVAL")
        if count >= VARNISH_MAX_APPLICATIONS_PER_PERIOD:
            raise ApiError("ERR_VARNISH_CAP_EXCEEDED")

    row["status"] = "PERFORMED"
    row["performed_at"] = clock.now()
    row["performing_staff_id"] = staff["id"]
    row["sterilization_load_id"] = load["id"]
    v.touch(row)

    if row["procedure_code"] == "D1206":
        calc.recompute_varnish(encounter["patient_id"], visit["program_period_id"])

    if encounter["clinical_status"] == "EXAMINED":
        encounter["clinical_status"] = "TREATED"
        v.touch(encounter)

    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.procedure(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/procedures/{id}/void
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/procedures/<procedure_id>/void", methods=["POST"])
def void_procedure(procedure_id):
    v.authenticate(["FieldDentist"])
    row = v.path_row("procedures", procedure_id)
    body = v.body()
    void_reason = v.opt_string(body, "void_reason")

    encounter = store.get("encounters", row["encounter_id"])
    visit = store.get("site_visits", encounter["site_visit_id"])
    gates.period_gate(visit["program_period_id"])

    if row["status"] not in ("PLANNED", "PERFORMED", "TAINTED"):
        raise ApiError("ERR_INVALID_STATE")

    row["status"] = "VOIDED"
    row["void_reason"] = void_reason
    v.touch(row)

    if row["procedure_code"] == "D1206":
        calc.recompute_varnish(encounter["patient_id"], visit["program_period_id"])

    cascades.recompute_encounter_charges(encounter)
    v.touch(encounter)

    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.procedure(row), 200)
