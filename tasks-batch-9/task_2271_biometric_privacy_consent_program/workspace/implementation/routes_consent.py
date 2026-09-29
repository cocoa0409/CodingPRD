"""Data subjects, consent records and alternative accommodations."""

from datetime import timedelta

from flask import Blueprint

import constants as K
import derive
import serialize
from authz import actor, require_role, require_role_for_target, require_subject_owner
from common import respond, respond_list
from errors import fail
from ops import (
    accommodations_for_consent,
    auto_accommodation,
    new_accommodation,
    published_in_scope_policy,
    require_notice_coverage,
)
from store import add_days, db, new_record, ordered, touch
from validate import (
    body,
    find_accommodation,
    find_asset,
    find_consent,
    find_jurisdiction,
    find_program,
    find_subject,
    opt_bool,
    opt_str,
    query_enum,
    query_str,
    req_datetime,
    req_enum,
    req_str,
)

bp = Blueprint("consents", __name__)

SUBJECT_READ_ROLES = (
    "SystemOperator",
    "PrivacyOfficer",
    "ComplianceApprover",
    "HRAdministrator",
    "Subject",
)
SUBJECT_LIST_ROLES = ("SystemOperator", "PrivacyOfficer", "ComplianceApprover", "HRAdministrator")

CONSENT_GRANTS = {
    "GRANTED": ("HRAdministrator",),
    "DECLINED": ("HRAdministrator",),
    "REVOKED": ("HRAdministrator", "Subject"),
    "SOLICITED": ("HRAdministrator",),
    "RESOLICIT_REQUIRED": ("PrivacyOfficer",),
    "EXPIRED": (),
}


# --- DataSubject ------------------------------------------------------------

@bp.post("/data-subjects")
def create_subject():
    _, role = actor()
    require_role(role, ("HRAdministrator",))
    data = body()
    program_id = req_str(data, "program_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    subject_type = req_enum(data, "subject_type", K.SUBJECT_CLASSES)
    external_ref = req_str(data, "external_ref")
    preferred_locale = req_str(data, "preferred_locale")
    accommodation_needed = opt_bool(data, "accommodation_needed", default=False)

    for existing in db.subjects.values():
        if existing["program_id"] == program_id and existing["external_ref"] == external_ref:
            fail(
                "ERR_INVALID_REQUEST",
                "external_ref %s already exists for this program." % external_ref,
            )

    find_program(program_id)
    find_jurisdiction(jurisdiction_id)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "subject_type": subject_type,
            "external_ref": external_ref,
            "preferred_locale": preferred_locale,
            "accommodation_needed": accommodation_needed,
            "enrollment_status": "NOT_ENROLLED",
            "active_accommodation_count": 0,
        }
    )
    db.subjects[rec["id"]] = rec
    return respond(serialize.subject, rec, 201)


@bp.get("/data-subjects/<subject_id>")
def read_subject(subject_id):
    user_id, role = actor()
    require_role(role, SUBJECT_READ_ROLES)
    subject = find_subject(subject_id)
    require_subject_owner(role, user_id, subject["id"])
    return respond(serialize.subject, subject)


@bp.get("/data-subjects")
def list_subjects():
    _, role = actor()
    require_role(role, SUBJECT_LIST_ROLES)
    program_id = query_str("program_id")
    jurisdiction_id = query_str("jurisdiction_id")
    enrollment_status = query_enum("enrollment_status", K.ENROLLMENT_STATUSES)
    derive.refresh_all()
    rows = list(db.subjects.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if enrollment_status is not None:
        rows = [r for r in rows if r["enrollment_status"] == enrollment_status]
    return respond_list(rows, serialize.subject)


# --- ConsentRecord ----------------------------------------------------------

@bp.post("/consent-records")
def create_consent():
    _, role = actor()
    require_role(role, ("HRAdministrator",))
    data = body()
    data_subject_id = req_str(data, "data_subject_id")
    asset_id = req_str(data, "asset_id")
    locale = req_str(data, "locale")
    written_release_acknowledged = opt_bool(data, "written_release_acknowledged", default=False)
    signature_ref = opt_str(data, "signature_ref")

    asset = find_asset(asset_id)
    subject = find_subject(data_subject_id)

    derive.refresh_all()
    program = db.programs.get(asset["program_id"])

    # step 8: the collection point must be collectable
    if asset["status"] not in K.COLLECTABLE_ASSET_STATUSES:
        fail(
            "ERR_ASSET_NOT_COLLECTABLE",
            "The collection point is %s and cannot take consent." % asset["status"],
        )

    # step 9: posture
    if program is not None:
        if program["posture"] == "FROZEN":
            fail("ERR_PROGRAM_POSTURE_BLOCKED", "The program is FROZEN; consent cannot be solicited.")
        if program["posture"] == "RESTRICTED" and asset["status"] != "ACTIVE":
            fail(
                "ERR_PROGRAM_POSTURE_BLOCKED",
                "The program is RESTRICTED; consent may only be solicited at ACTIVE points.",
            )

    # step 10: regulatory prerequisites
    policy = published_in_scope_policy(asset["program_id"], asset["jurisdiction_id"])
    if policy is None:
        fail(
            "ERR_POLICY_NOT_PUBLISHED",
            "No published policy covers this collection point's jurisdiction.",
        )
    juris = find_jurisdiction(asset["jurisdiction_id"])
    # steps 10 and 11: the notice packet must be published, translated and mature
    require_notice_coverage(juris, asset["subject_class"], check_lead=True)

    # step 13: referential coherence
    if subject["jurisdiction_id"] != asset["jurisdiction_id"]:
        fail(
            "ERR_JURISDICTION_MISMATCH",
            "The data subject is governed by a different state profile.",
        )
    if subject["subject_type"] != asset["subject_class"]:
        fail(
            "ERR_SUBJECT_CLASS_MISMATCH",
            "The data subject's type does not match the collection point's population.",
        )
    for existing in db.consents.values():
        if (
            existing["data_subject_id"] == data_subject_id
            and existing["asset_id"] == asset_id
            and existing["status"] in ("SOLICITED", "GRANTED", "RESOLICIT_REQUIRED")
        ):
            fail(
                "ERR_CONSENT_ALREADY_EXISTS",
                "An open consent record already exists for this subject and collection point.",
            )

    rec = new_record()
    rec.update(
        {
            "data_subject_id": data_subject_id,
            "asset_id": asset_id,
            "pinned_policy_id": asset["pinned_policy_id"],
            "locale": locale,
            "status": "SOLICITED",
            "written_release_acknowledged": written_release_acknowledged,
            "signature_ref": signature_ref,
            "signed_at": None,
            "pinned_retention_days": None,
            "record_retention_until": None,
            "decline_reason": None,
            "revocation_reason": None,
            "solicitation_round": 1,
        }
    )
    db.consents[rec["id"]] = rec
    return respond(serialize.consent, rec, 201)


@bp.post("/consent-records/<consent_id>/transitions")
def consent_transition(consent_id):
    user_id, role = actor()
    raw = body()
    require_role_for_target(
        role,
        raw.get("to_status"),
        K.CONSENT_STATUSES,
        CONSENT_GRANTS,
        ("HRAdministrator", "PrivacyOfficer", "Subject"),
    )
    to_status = req_enum(raw, "to_status", K.CONSENT_STATUSES)
    decline_reason = None
    revocation_reason = None
    if to_status == "DECLINED":
        decline_reason = req_str(raw, "decline_reason")
    if to_status == "REVOKED":
        revocation_reason = req_str(raw, "revocation_reason")
    body_release = opt_bool(raw, "written_release_acknowledged")
    body_signature = opt_str(raw, "signature_ref")

    consent = find_consent(consent_id)

    # step 3 (continued): the signature may arrive here or at solicitation time
    if to_status == "GRANTED":
        effective_signature = (
            body_signature if body_signature is not None else consent["signature_ref"]
        )
        if effective_signature is None:
            fail("ERR_INVALID_REQUEST", "Field 'signature_ref' is required to grant consent.")

    # step 5: subject ownership
    require_subject_owner(role, user_id, consent["data_subject_id"])

    current = consent["status"]
    edges = {
        ("SOLICITED", "GRANTED"),
        ("SOLICITED", "DECLINED"),
        ("GRANTED", "REVOKED"),
        ("EXPIRED", "RESOLICIT_REQUIRED"),
        ("REVOKED", "RESOLICIT_REQUIRED"),
        ("RESOLICIT_REQUIRED", "SOLICITED"),
    }
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "A consent record cannot move from %s to %s." % (current, to_status),
        )

    asset = db.assets.get(consent["asset_id"])
    derive.refresh_all()
    program = db.programs.get(asset["program_id"]) if asset is not None else None

    # step 8 (continued): collectable-asset requirement
    if to_status in ("GRANTED", "RESOLICIT_REQUIRED", "SOLICITED"):
        if asset is None or asset["status"] not in K.COLLECTABLE_ASSET_STATUSES:
            fail(
                "ERR_ASSET_NOT_COLLECTABLE",
                "The collection point is not in a collectable status.",
            )

    if to_status == "GRANTED":
        # step 9
        if program is not None and program["posture"] == "FROZEN":
            fail("ERR_PROGRAM_POSTURE_BLOCKED", "The program is FROZEN; consent cannot be granted.")
        # step 10
        if body_release is not None:
            consent["written_release_acknowledged"] = body_release
        if body_signature is not None:
            consent["signature_ref"] = body_signature
        subject = db.subjects.get(consent["data_subject_id"])
        juris = db.jurisdictions.get(subject["jurisdiction_id"]) if subject is not None else None
        if (
            juris is not None
            and juris["requires_written_release"]
            and not consent["written_release_acknowledged"]
        ):
            fail(
                "ERR_WRITTEN_RELEASE_REQUIRED",
                "The written release must be acknowledged in this state.",
            )

        consent["status"] = "GRANTED"
        consent["signed_at"] = db.clock
        policy = db.policies.get(consent["pinned_policy_id"])
        consent["pinned_retention_days"] = (
            int(policy["retention_days"]) if policy is not None else None
        )
        consent["record_retention_until"] = add_days(
            consent["signed_at"], K.CONSENT_RECORD_RETENTION_DAYS
        )
        # compensation: a later grant closes every accommodation this refusal spawned
        for accommodation in accommodations_for_consent(
            consent_id, ("REQUESTED", "PROVISIONED", "ACTIVE")
        ):
            accommodation["status"] = "ENDED"
            touch(accommodation)
        touch(consent)

    elif to_status == "DECLINED":
        consent["status"] = "DECLINED"
        consent["decline_reason"] = decline_reason
        touch(consent)
        auto_accommodation(consent, "AUTO_DECLINE")

    elif to_status == "REVOKED":
        consent["status"] = "REVOKED"
        consent["revocation_reason"] = revocation_reason
        touch(consent)
        auto_accommodation(consent, "AUTO_REVOKE")

    elif to_status == "RESOLICIT_REQUIRED":
        consent["status"] = "RESOLICIT_REQUIRED"
        touch(consent)

    else:  # RESOLICIT_REQUIRED -> SOLICITED
        # step 10
        pinned = asset["pinned_policy_id"] if asset is not None else None
        policy = db.policies.get(pinned) if pinned is not None else None
        if policy is None or policy["status"] != "PUBLISHED":
            fail(
                "ERR_POLICY_NOT_PUBLISHED",
                "The collection point does not pin a published policy.",
            )
        consent["status"] = "SOLICITED"
        consent["solicitation_round"] += 1
        consent["pinned_policy_id"] = pinned
        consent["signed_at"] = None
        consent["pinned_retention_days"] = None
        consent["record_retention_until"] = None
        consent["written_release_acknowledged"] = False
        consent["signature_ref"] = None
        touch(consent)

    return respond(serialize.consent, consent)


@bp.get("/consent-records/<consent_id>")
def read_consent(consent_id):
    user_id, role = actor()
    require_role(role, SUBJECT_READ_ROLES)
    consent = find_consent(consent_id)
    require_subject_owner(role, user_id, consent["data_subject_id"])
    return respond(serialize.consent, consent)


@bp.get("/consent-records")
def list_consents():
    _, role = actor()
    require_role(role, SUBJECT_LIST_ROLES)
    data_subject_id = query_str("data_subject_id")
    asset_id = query_str("asset_id")
    pinned_policy_id = query_str("pinned_policy_id")
    status = query_enum("status", K.CONSENT_STATUSES)
    rows = list(db.consents.values())
    if data_subject_id is not None:
        rows = [r for r in rows if r["data_subject_id"] == data_subject_id]
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if pinned_policy_id is not None:
        rows = [r for r in rows if r["pinned_policy_id"] == pinned_policy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.consent)


# --- AlternativeAccommodation ----------------------------------------------

BUFFER = timedelta(hours=K.ACCOMMODATION_CHANGEOVER_BUFFER_HOURS)


@bp.post("/accommodations")
def create_accommodation():
    _, role = actor()
    require_role(role, ("HRAdministrator",))
    data = body()
    data_subject_id = req_str(data, "data_subject_id")
    asset_id = req_str(data, "asset_id")
    method = req_enum(data, "method", K.ACCOMMODATION_METHODS)
    starts_at = req_datetime(data, "starts_at")
    ends_at = req_datetime(data, "ends_at")

    asset = find_asset(asset_id)
    find_subject(data_subject_id)

    # step 11: closed intervals inflated by the 24h changeover buffer on both ends
    lower = starts_at - BUFFER
    upper = ends_at + BUFFER
    for other in ordered(list(db.accommodations.values())):
        if other["data_subject_id"] != data_subject_id:
            continue
        if other["status"] not in ("REQUESTED", "PROVISIONED", "ACTIVE"):
            continue
        if lower <= other["ends_at"] and other["starts_at"] <= upper:
            fail(
                "ERR_ACCOMMODATION_WINDOW_CONFLICT",
                "The requested window collides with another accommodation for this subject.",
            )

    # step 12: exactly one method is permitted per collection surface
    if K.ACCOMMODATION_METHOD_MAP[asset["system_category"]] != method:
        fail(
            "ERR_ACCOMMODATION_METHOD_NOT_PERMITTED",
            "Method %s is not permitted for a %s surface."
            % (method, asset["system_category"]),
        )

    rec = new_accommodation(data_subject_id, asset_id, method, starts_at, ends_at, "MANUAL")
    return respond(serialize.accommodation, rec, 201)


@bp.post("/accommodations/<accommodation_id>/transitions")
def accommodation_transition(accommodation_id):
    _, role = actor()
    require_role(role, ("HRAdministrator",))
    raw = body()
    to_status = req_enum(raw, "to_status", K.ACCOMMODATION_STATUSES)

    accommodation = find_accommodation(accommodation_id)
    current = accommodation["status"]

    edges = {
        ("REQUESTED", "PROVISIONED"),
        ("PROVISIONED", "ACTIVE"),
        ("ACTIVE", "ENDED"),
        ("PROVISIONED", "ENDED"),
        ("REQUESTED", "ENDED"),
    }
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "An accommodation cannot move from %s to %s." % (current, to_status),
        )

    if to_status == "PROVISIONED":
        asset = db.assets.get(accommodation["asset_id"])
        if (
            asset is not None
            and K.ACCOMMODATION_METHOD_MAP[asset["system_category"]] != accommodation["method"]
        ):
            fail(
                "ERR_ACCOMMODATION_METHOD_NOT_PERMITTED",
                "Method %s is not permitted for a %s surface."
                % (accommodation["method"], asset["system_category"]),
            )
        if accommodation["sla_due_at"] is not None and db.clock > accommodation["sla_due_at"]:
            accommodation["sla_breached"] = True
        accommodation["status"] = "PROVISIONED"
        touch(accommodation)

    elif to_status == "ACTIVE":
        if db.clock < accommodation["starts_at"]:
            fail(
                "ERR_INVALID_TRANSITION",
                "An accommodation cannot be activated before its window opens.",
            )
        accommodation["status"] = "ACTIVE"
        touch(accommodation)

    else:  # ENDED
        accommodation["status"] = "ENDED"
        touch(accommodation)

    return respond(serialize.accommodation, accommodation)


@bp.get("/accommodations/<accommodation_id>")
def read_accommodation(accommodation_id):
    user_id, role = actor()
    require_role(role, SUBJECT_READ_ROLES)
    accommodation = find_accommodation(accommodation_id)
    require_subject_owner(role, user_id, accommodation["data_subject_id"])
    return respond(serialize.accommodation, accommodation)


@bp.get("/accommodations")
def list_accommodations():
    _, role = actor()
    require_role(role, SUBJECT_LIST_ROLES)
    data_subject_id = query_str("data_subject_id")
    asset_id = query_str("asset_id")
    created_from_consent_id = query_str("created_from_consent_id")
    status = query_enum("status", K.ACCOMMODATION_STATUSES)
    origin = query_enum("origin", K.ACCOMMODATION_ORIGINS)
    rows = list(db.accommodations.values())
    if data_subject_id is not None:
        rows = [r for r in rows if r["data_subject_id"] == data_subject_id]
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if created_from_consent_id is not None:
        rows = [r for r in rows if r["created_from_consent_id"] == created_from_consent_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    return respond_list(rows, serialize.accommodation)
