"""Participants, caregivers, support assessments and consent artifacts."""

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import (
    Body,
    Refs,
    check_transition,
    check_version,
    endpoint,
    pagination,
    paginate,
    resolve_one,
)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, parse_date, sort_rows, touch

bp = Blueprint("intake", __name__)

PARTICIPANT_EDGES = {
    "ACTIVE": ("INTAKE", "INACTIVE"),
    "INACTIVE": ("ACTIVE",),
    "EXITED": ("ACTIVE", "INACTIVE"),
    "INTAKE": (),
}


# --- caregiver-scope resolvers (ladder rung 6) -----------------------------

def _scope_participant_param(context):
    row = db.get("participants", context.params.get("participant_id"))
    return [row["id"]] if row else []


def _scope_caregiver_param(context):
    row = db.get("caregivers", context.params.get("caregiver_id"))
    return [row["participant_id"]] if row else []


def _scope_consent_param(context):
    row = db.get("consents", context.params.get("consent_id"))
    return [row["participant_id"]] if row else []


def _scope_consent_filter(context):
    row = db.get("participants", context.q("participant_id"))
    return [row["id"]] if row else []


# ---------------------------------------------------------------------------
# participants
# ---------------------------------------------------------------------------

@bp.route("/recreation/participants", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def create_participant(context):
    body = Body(context.body)
    fields = {
        "legal_name": body.req_string("legal_name"),
        "date_of_birth": body.req_date("date_of_birth"),
        "household_id": body.req_string("household_id"),
        "household_size": body.req_int("household_size", minimum=1),
        "income_band": body.req_enum("income_band", enums.INCOME_BANDS),
        "weight_kg": body.req_int("weight_kg", minimum=1),
        "mobility_profile": body.req_enum("mobility_profile", enums.MOBILITY_PROFILES),
        "guardianship_status": body.req_enum(
            "guardianship_status", enums.GUARDIANSHIP_STATUSES
        ),
        "status": "INTAKE",
        "effective_support_tier": None,
    }
    body.check_enums()
    return ok(serial.dump(insert("participants", fields)), 201)


@bp.route("/recreation/participants", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_participants(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("participants"))
    status = context.q("status")
    household_id = context.q("household_id")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if household_id is not None:
        rows = [r for r in rows if r["household_id"] == household_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/participants/<participant_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_participant_param)
def read_participant(context, participant_id):
    return ok(serial.dump(resolve_one("participant", participant_id)))


@bp.route("/recreation/participants/<participant_id>", methods=["PATCH"])
@endpoint(roles=("IntakeCoordinator",))
def amend_participant(context, participant_id):
    participant = resolve_one("participant", participant_id)
    body = Body(context.body)
    household_size = body.opt_int("household_size", None, minimum=1)
    income_band = body.opt_enum("income_band", enums.INCOME_BANDS, None)
    weight_kg = body.opt_int("weight_kg", None, minimum=1)
    mobility_profile = body.opt_enum("mobility_profile", enums.MOBILITY_PROFILES, None)
    body.check_enums()
    if household_size is not None:
        participant["household_size"] = household_size
    if income_band is not None:
        participant["income_band"] = income_band
    if weight_kg is not None:
        participant["weight_kg"] = weight_kg
    if mobility_profile is not None:
        participant["mobility_profile"] = mobility_profile
    touch(participant)
    return ok(serial.dump(participant))


@bp.route("/recreation/participants/<participant_id>/status", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def move_participant_status(context, participant_id):
    participant = resolve_one("participant", participant_id)
    body = Body(context.body)
    target = body.req_enum("target_status", enums.PARTICIPANT_STATUSES)
    body.check_enums()
    check_transition(participant["status"], PARTICIPANT_EDGES.get(target, ()), ("EXITED",))

    if target == "ACTIVE":
        active = L.active_assessment(participant)
        if active is None:
            raise ApiError("ERR_INVALID_STATE", "No active support assessment exists.")
        participant["status"] = "ACTIVE"
        participant["effective_support_tier"] = active["support_tier"]
        touch(participant)
    elif target == "INACTIVE":
        participant["status"] = "INACTIVE"
        touch(participant)
    else:
        engine.exit_participant(participant)
    return ok(serial.dump(participant))


@bp.route("/recreation/participants/<participant_id>/eligibility", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_participant_param)
def participant_eligibility(context, participant_id):
    refs = Refs()
    session_id = context.q("session_id")
    if session_id is not None:
        refs.add("session", session_id, path=False)
    refs.add("participant", participant_id)
    resolved = refs.resolve()
    participant = resolved["participant"]
    session = resolved.get("session")
    verdict = calc.participant_enrollment_posture(participant, session)
    data = {"participant_id": participant["id"]}
    data.update(verdict)
    data["effective_support_tier"] = participant.get("effective_support_tier")
    data["age_years"] = calc.age_years(participant)
    return ok(data)


# ---------------------------------------------------------------------------
# caregivers
# ---------------------------------------------------------------------------

@bp.route("/recreation/caregivers", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def create_caregiver(context):
    participant_id = context.body.get("participant_id")
    if isinstance(participant_id, str):
        resolve_one("participant", participant_id)
    body = Body(context.body)
    fields = {
        "participant_id": body.req_string("participant_id"),
        "full_name": body.req_string("full_name"),
        "relationship": body.req_enum("relationship", enums.RELATIONSHIPS),
        "is_legal_guardian": body.opt_bool("is_legal_guardian", False),
        "contact_phone": body.req_string("contact_phone"),
    }
    body.check_enums()
    resolve_one("participant", fields["participant_id"])
    return ok(serial.dump(insert("caregivers", fields)), 201)


@bp.route("/recreation/caregivers", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_caregivers(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("caregivers"))
    participant_id = context.q("participant_id")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/caregivers/<caregiver_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_caregiver_param)
def read_caregiver(context, caregiver_id):
    return ok(serial.dump(resolve_one("caregiver", caregiver_id)))


# ---------------------------------------------------------------------------
# support assessments
# ---------------------------------------------------------------------------

@bp.route("/recreation/support-assessments", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def create_assessment(context):
    participant_id = context.body.get("participant_id")
    participant = None
    if isinstance(participant_id, str):
        participant = resolve_one("participant", participant_id)
    body = Body(context.body)
    body.req_string("participant_id")
    assessed_on = body.req_date("assessed_on")
    effective_from = body.req_instant("effective_from")
    support_tier = body.req_enum("support_tier", enums.SUPPORT_TIERS)
    expected_version = body.req_int("expected_participant_version")
    body.check_enums()
    if participant is None:
        participant = resolve_one("participant", participant_id)
    check_version(expected_version, participant)

    row = insert(
        "support_assessments",
        {
            "participant_id": participant["id"],
            "assessed_on": assessed_on,
            "effective_from": effective_from,
            "support_tier": support_tier,
            "support_points": calc.support_points(support_tier),
            "status": "DRAFT",
        },
    )
    touch(participant)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/support-assessments", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_assessments(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("support_assessments"))
    participant_id = context.q("participant_id")
    status = context.q("status")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/support-assessments/<assessment_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_assessment(context, assessment_id):
    return ok(serial.dump(resolve_one("assessment", assessment_id)))


@bp.route("/recreation/support-assessments/<assessment_id>/activate", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def activate_assessment(context, assessment_id):
    assessment = resolve_one("assessment", assessment_id)
    check_transition(assessment["status"], ("DRAFT",), ("SUPERSEDED",))
    participant = db.get("participants", assessment["participant_id"])
    engine.activate_assessment(assessment, participant)
    return ok(serial.dump(assessment))


# ---------------------------------------------------------------------------
# consent artifacts
# ---------------------------------------------------------------------------

@bp.route("/recreation/consents", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def create_consent(context):
    participant_id = context.body.get("participant_id")
    if isinstance(participant_id, str):
        resolve_one("participant", participant_id)
    body = Body(context.body)
    fields = {
        "participant_id": body.req_string("participant_id"),
        "consent_type": body.req_enum("consent_type", enums.CONSENT_TYPES),
        "signed_by_caregiver_id": None,
        "signer_role": None,
        "signed_on": None,
        "expires_on": body.req_date("expires_on"),
        "status": "PENDING_SIGNATURE",
    }
    body.check_enums()
    resolve_one("participant", fields["participant_id"])
    return ok(serial.dump(insert("consents", fields)), 201)


@bp.route("/recreation/consents", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_consent_filter)
def list_consents(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("consents"))
    participant_id = context.q("participant_id")
    signer = context.q("signed_by_caregiver_id")
    consent_type = context.q("consent_type")
    status = context.q("status")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if signer is not None:
        rows = [r for r in rows if r["signed_by_caregiver_id"] == signer]
    if consent_type is not None:
        rows = [r for r in rows if r["consent_type"] == consent_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/consents/<consent_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_consent_param)
def read_consent(context, consent_id):
    return ok(serial.dump(resolve_one("consent", consent_id)))


@bp.route("/recreation/consents/<consent_id>/sign", methods=["POST"])
@endpoint(roles=("IntakeCoordinator", "CaregiverUser"), scope=_scope_consent_param)
def sign_consent(context, consent_id):
    consent = resolve_one("consent", consent_id)
    caregiver_id = context.body.get("signed_by_caregiver_id")
    caregiver = None
    if isinstance(caregiver_id, str):
        caregiver = resolve_one("caregiver", caregiver_id)
    body = Body(context.body)
    body.opt_string("signed_by_caregiver_id", None)
    body.check_enums()

    check_transition(consent["status"], ("PENDING_SIGNATURE",), ("REVOKED",))
    expires = parse_date(consent["expires_on"])
    if expires is None or expires < db.clock_date:
        raise ApiError("ERR_INVALID_STATE", "The consent has already expired.")

    participant = db.get("participants", consent["participant_id"])
    accepted = calc.accepted_signer_role(participant, consent)
    if accepted == "SELF":
        if caregiver_id is not None or context.role != "IntakeCoordinator":
            raise ApiError("ERR_CONSENT_SIGNER_NOT_AUTHORIZED")
        consent["signer_role"] = "SELF"
        consent["signed_by_caregiver_id"] = None
    else:
        if caregiver is None:
            raise ApiError("ERR_CONSENT_SIGNER_NOT_AUTHORIZED")
        if caregiver["participant_id"] != participant["id"] or not caregiver["is_legal_guardian"]:
            raise ApiError("ERR_CONSENT_SIGNER_NOT_AUTHORIZED")
        consent["signer_role"] = "LEGAL_GUARDIAN"
        consent["signed_by_caregiver_id"] = caregiver["id"]
    consent["status"] = "SIGNED"
    consent["signed_on"] = db.clock_date.strftime("%Y-%m-%d")
    touch(consent)
    return ok(serial.dump(consent))


@bp.route("/recreation/consents/<consent_id>/revoke", methods=["POST"])
@endpoint(roles=("IntakeCoordinator", "CaregiverUser"), scope=_scope_consent_param)
def revoke_consent(context, consent_id):
    consent = resolve_one("consent", consent_id)
    check_transition(consent["status"], ("PENDING_SIGNATURE", "SIGNED"), ("REVOKED",))
    consent["status"] = "REVOKED"
    touch(consent)
    return ok(serial.dump(consent))
