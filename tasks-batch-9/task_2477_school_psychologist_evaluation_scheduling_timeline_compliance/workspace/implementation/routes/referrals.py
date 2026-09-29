"""Referral intake and the polymorphic consent event stream (PRD §3.2)."""

from flask import Blueprint, request

import lookups
import serializers
import services
import validators as v
from auth import ALL_ROLES, authorize
from envelope import paginate, pagination, respond_array, respond_object
from errors import ApiError
from store import base_record, db, iso, now, sort_key, touch

bp = Blueprint("referrals", __name__)

REFERRAL_TYPES = ("INITIAL", "REEVALUATION")
CONSENT_EVENT_TYPES = ("CONSENT_RECEIVED", "CONSENT_WAIVED", "CONSENT_WITHDRAWN")
CONSENT_ON_FILE = ("CONSENTED", "CONSENT_WAIVED")


@bp.post("/psych-services/referrals")
@authorize("IntakeCoordinator")
def create_referral():
    body = v.body()
    school_id = v.req_str(body, "school_id")
    student_local_id = v.req_str(body, "student_local_id")
    referral_type = v.req_enum(body, "referral_type", REFERRAL_TYPES)
    prior_supplied = v.has(body, "prior_evaluation_id")
    if referral_type == "REEVALUATION" and not prior_supplied:
        raise ApiError("ERR_INVALID_REQUEST",
                       "prior_evaluation_id is required when referral_type is REEVALUATION.")
    if referral_type == "INITIAL" and prior_supplied:
        raise ApiError("ERR_INVALID_REQUEST",
                       "prior_evaluation_id must be omitted when referral_type is INITIAL.")
    prior_evaluation_id = v.req_str(body, "prior_evaluation_id") if prior_supplied else None
    primary_language = v.opt_str(body, "primary_language", "en", allow_empty=False)
    interpreter_required = v.opt_bool(body, "interpreter_required", False)
    bilingual_required = v.opt_bool(body, "bilingual_evaluation_required", False)
    requested_domains = v.domain_list(body, "requested_domains")
    summary = v.opt_str(body, "intervention_team_summary", "")

    lookups.school(school_id)
    if prior_evaluation_id is not None:
        lookups.evaluation(prior_evaluation_id)

    record = base_record()
    record.update({
        "school_id": school_id,
        "active_evaluation_id": None,
        "student_local_id": student_local_id,
        "referral_type": referral_type,
        "prior_evaluation_id": prior_evaluation_id,
        "primary_language": primary_language,
        "interpreter_required": interpreter_required,
        "bilingual_evaluation_required": bilingual_required,
        "requested_domains": requested_domains,
        "intervention_team_summary": summary,
        "status": "INTAKE_RECEIVED",
        "consent_received_at": None,
        "last_consent_event_type": None,
        "parent_signature_reference": None,
        "waiver_reason": None,
    })
    db.referrals[record["id"]] = record
    return respond_object(serializers.referral(record), 201)


@bp.post("/psych-services/referrals/<referral_id>/consent-events")
@authorize("IntakeCoordinator")
def create_consent_event(referral_id):
    body = v.body()
    event_type = v.req_enum(body, "event_type", CONSENT_EVENT_TYPES)
    effective_at = v.req_dt(body, "effective_at")
    signature_reference = v.opt_str(body, "parent_signature_reference")
    waiver_reason = v.opt_str(body, "waiver_reason")

    referral = lookups.referral(referral_id)

    # ladder 8 — the referral's status must permit this event
    status = referral["status"]
    if event_type in ("CONSENT_RECEIVED", "CONSENT_WAIVED"):
        permitted = status == "INTAKE_RECEIVED"
    else:
        permitted = status in CONSENT_ON_FILE
    if not permitted:
        raise ApiError("ERR_REFERRAL_STATE_INVALID",
                       "A %s event is not permitted while the referral is %s." % (event_type, status))

    # ladder 20 — no back-dating into the future
    if effective_at > now():
        raise ApiError("ERR_CONSENT_TIMESTAMP_FUTURE",
                       "effective_at may not be later than the current logical clock instant.")

    # ladder 24 — consent-to-waive applicability
    if event_type == "CONSENT_WAIVED":
        if referral["referral_type"] != "REEVALUATION" or \
                waiver_reason is None or waiver_reason.strip() == "":
            raise ApiError("ERR_WAIVER_NOT_APPLICABLE",
                           "A consent waiver requires a REEVALUATION referral and a non-empty waiver_reason.")

    referral["last_consent_event_type"] = event_type

    if event_type in ("CONSENT_RECEIVED", "CONSENT_WAIVED"):
        referral["status"] = "CONSENTED" if event_type == "CONSENT_RECEIVED" else "CONSENT_WAIVED"
        referral["consent_received_at"] = iso(effective_at)
        if event_type == "CONSENT_RECEIVED":
            referral["parent_signature_reference"] = signature_reference
        else:
            referral["waiver_reason"] = waiver_reason
        evaluation = services.create_evaluation(referral, effective_at)
        referral["active_evaluation_id"] = evaluation["id"]
        touch(referral)
    else:
        referral["status"] = "CONSENT_WITHDRAWN"
        touch(referral)
        services.withdraw_consent_cascade(referral)

    return respond_object(serializers.referral(referral))


@bp.get("/psych-services/referrals/<referral_id>")
@authorize(*ALL_ROLES)
def get_referral(referral_id):
    record = lookups.referral(referral_id)
    return respond_object(serializers.referral(record))


@bp.get("/psych-services/referrals")
@authorize(*ALL_ROLES)
def list_referrals():
    limit, offset = pagination(request.args)
    rows = list(db.referrals.values())
    for field in ("school_id", "status", "referral_type", "prior_evaluation_id",
                  "active_evaluation_id"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.referral(r) for r in page], limit, offset, total)
