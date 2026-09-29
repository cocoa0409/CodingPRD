"""Enrollment creation, reads, usage, recertification and de-enrollment."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (BENEFIT_STATUSES, DEVICE_DIMENSION_STATUSES,
                           MANUAL_DE_ENROLLMENT_REASONS, PROGRAM_ADMINISTRATOR,
                           PROVIDER_AGENT, QUALIFYING_BENEFITS, RECERT_STATUSES,
                           ROLES_ALL, SERVICE_TYPES, SUBSCRIBER, USAGE_STATUSES,
                           authenticate, get_address, get_check, get_enrollment,
                           get_provider, get_subscriber, require_provider_owner,
                           require_subscriber_owner)
from services import calc, cascades, derive

bp = Blueprint("enrollments", __name__)


def overlapping_interval_count(address_id, new_start):
    """A candidate benefit has a null end, so its interval is unbounded above.
    The test ranges over every benefit ever certified at the dwelling."""
    count = 0
    for existing in derive.enrollments_at_address(address_id):
        existing_end = existing["benefit_end_date"]
        if existing_end is None or new_start < existing_end:
            count += 1
    return count


@bp.post("/lifeline/enrollments")
def create_enrollment():
    caller = authenticate((PROVIDER_AGENT,))
    body = v.get_body()
    subscriber_id = v.string_field(body, "subscriber_id", min_len=1)
    provider_id = v.string_field(body, "provider_id", min_len=1)
    eligibility_check_id = v.string_field(body, "eligibility_check_id", min_len=1)
    certified_address_id = v.string_field(body, "certified_address_id", min_len=1)
    service_type = v.enum_field(body, "service_type", SERVICE_TYPES)
    attested = v.bool_field(body, "one_per_household_attested", required=False,
                            default=None)
    benefit_start_date = v.datetime_field(body, "benefit_start_date",
                                          required=False, default=None)

    subscriber = get_subscriber(subscriber_id)
    provider = get_provider(provider_id)
    check = get_check(eligibility_check_id)
    address = get_address(certified_address_id)

    if certified_address_id != subscriber["address_id"]:
        v.bad("certified_address_id must name the applicant's own address_id")

    require_provider_owner(caller, provider_id)

    now = db.now()
    if benefit_start_date is None:
        benefit_start_date = now

    if check["status"] != "ELIGIBLE_CONFIRMED":
        raise ApiError("ERR_ELIGIBILITY_CHECK_NOT_CONFIRMED",
                       "The certifying eligibility check is not confirmed")
    if check["expires_at"] is None or now > check["expires_at"]:
        raise ApiError("ERR_ELIGIBILITY_CHECK_EXPIRED",
                       "The eligibility certification has lapsed")
    if subscriber["status"] != "VERIFIED_ELIGIBLE":
        raise ApiError("ERR_SUBSCRIBER_NOT_ELIGIBLE",
                       "The applicant is not in the verified-eligible posture")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "The carrier is not operating")

    permitted = derive.max_permitted_benefit_slots(address)
    if overlapping_interval_count(address["id"], benefit_start_date) + 1 > permitted:
        raise ApiError("ERR_ONE_PER_HOUSEHOLD_VIOLATION",
                       "The dwelling's permitted benefit occupancy is exhausted")
    if address["status"] == "DUPLICATE_FLAGGED":
        raise ApiError("ERR_ADDRESS_DUPLICATE_UNRESOLVED",
                       "The dwelling sits in an unresolved duplicate cohort")
    if attested is not True:
        raise ApiError("ERR_HOUSEHOLD_CERTIFICATION_MISSING",
                       "one_per_household_attested must be present and true")
    licensed = [c.upper() for c in provider["licensed_state_codes"]]
    if address["state_code"].upper() not in licensed:
        raise ApiError("ERR_PROVIDER_NOT_LICENSED_IN_STATE",
                       "The carrier is not licensed in the dwelling's state")
    if derive.active_enrollment_count(provider["id"]) + 1 > provider["enrollment_cap"]:
        raise ApiError("ERR_PROVIDER_ENROLLMENT_CAP_EXCEEDED",
                       "The carrier is at its enrollment cap")

    row = db.base_row()
    row.update({
        "subscriber_id": subscriber_id,
        "provider_id": provider_id,
        "eligibility_check_id": eligibility_check_id,
        "certified_address_id": certified_address_id,
        "service_type": service_type,
        "one_per_household_attested": True,
        "benefit_status": "ACTIVE",
        "usage_status": "PENDING_FIRST_USE",
        "recert_status": "NOT_DUE",
        "device_status": "AWAITING_DEVICE",
        "benefit_start_date": benefit_start_date,
        "benefit_end_date": None,
        "last_usage_at": None,
        "non_usage_flagged_at": None,
        "cure_deadline_at": None,
        "recert_due_date": calc.recert_due_date(benefit_start_date),
        "recert_notice_sent_at": None,
        "recert_response_deadline_at": None,
        "recert_last_responded_at": None,
        "recert_evaluated_income_cents": None,
        "recert_income_threshold_cents": None,
        "de_enrollment_reason": None,
        "de_enrolled_at": None,
        "de_enrolled_by_ref": None,
        "appeal_deadline_at": None,
        "device_issuance_count": 0,
        "last_device_issued_at": None,
        "audit_risk_score": 0,
    })
    db.db.enrollments[row["id"]] = row
    derive.recompute_risk(row)

    subscriber["status"] = "ENROLLED"
    db.touch(subscriber)
    db.touch(address)
    db.touch(provider)

    return response.ok(derive.enrollment_json(row), 201)


@bp.get("/lifeline/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    authenticate(ROLES_ALL)
    enrollment = get_enrollment(enrollment_id)
    return response.ok(derive.enrollment_json(enrollment))


@bp.get("/lifeline/enrollments")
def list_enrollments():
    authenticate(ROLES_ALL)
    filters = [
        ("subscriber_id", response.filter_str("subscriber_id")),
        ("provider_id", response.filter_str("provider_id")),
        ("eligibility_check_id", response.filter_str("eligibility_check_id")),
        ("certified_address_id", response.filter_str("certified_address_id")),
        ("benefit_status", response.filter_enum("benefit_status", BENEFIT_STATUSES)),
        ("usage_status", response.filter_enum("usage_status", USAGE_STATUSES)),
        ("recert_status", response.filter_enum("recert_status", RECERT_STATUSES)),
        ("device_status", response.filter_enum("device_status",
                                               DEVICE_DIMENSION_STATUSES)),
    ]
    rows = list(db.db.enrollments.values())
    for key, value in filters:
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return response.paginate(db.by_created(rows), derive.enrollment_json)


@bp.post("/lifeline/enrollments/<enrollment_id>/usage")
def record_usage(enrollment_id):
    caller = authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    enrollment = get_enrollment(enrollment_id)

    body = v.get_body()
    usage_at = v.datetime_field(body, "usage_at", required=False, default=None)
    v.string_field(body, "usage_kind", required=False, min_len=0, default=None)

    require_provider_owner(caller, enrollment["provider_id"])

    now = db.now()
    if enrollment["benefit_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "The benefit is not active")

    if enrollment["usage_status"] == "NON_USAGE_FLAGGED":
        if (enrollment["cure_deadline_at"] is not None
                and now > enrollment["cure_deadline_at"]):
            raise ApiError("ERR_CURE_PERIOD_EXPIRED",
                           "The cure period has already elapsed")
        enrollment["usage_status"] = "USING"
        enrollment["last_usage_at"] = now
        enrollment["non_usage_flagged_at"] = None
        enrollment["cure_deadline_at"] = None
    else:
        candidate = usage_at if usage_at is not None else now
        previous = enrollment["last_usage_at"]
        # The activity anchor only ever moves forward.
        if previous is None or candidate > previous:
            enrollment["last_usage_at"] = candidate
        if enrollment["usage_status"] == "PENDING_FIRST_USE":
            enrollment["usage_status"] = "USING"

    derive.recompute_risk(enrollment)
    db.touch(enrollment)
    return response.ok(derive.enrollment_json(enrollment))


@bp.post("/lifeline/enrollments/<enrollment_id>/recertify")
def recertify(enrollment_id):
    caller = authenticate((SUBSCRIBER,))
    enrollment = get_enrollment(enrollment_id)

    body = v.get_body()
    household_size = v.int_field(body, "household_size", minimum=1, maximum=12)
    annual_income_cents = v.int_field(body, "annual_income_cents", minimum=0)
    last_3mo_income_cents = v.int_field(body, "last_3mo_income_cents", minimum=0)
    attested_benefit = v.enum_field(body, "attested_qualifying_benefit",
                                    QUALIFYING_BENEFITS)
    v.string_field(body, "attestation_ref", required=False, min_len=0, default=None)

    require_subscriber_owner(caller, enrollment["subscriber_id"])

    now = db.now()
    if enrollment["benefit_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "The benefit is not active")
    if enrollment["recert_status"] != "NOTICED":
        raise ApiError("ERR_RECERT_NOT_NOTICED",
                       "No recertification notice is outstanding")
    if (enrollment["recert_response_deadline_at"] is not None
            and now > enrollment["recert_response_deadline_at"]):
        raise ApiError("ERR_RECERT_WINDOW_CLOSED",
                       "The recertification response window has closed")

    subscriber = db.db.subscribers.get(enrollment["subscriber_id"])
    if subscriber is not None:
        subscriber["household_size"] = household_size
        subscriber["annual_income_cents"] = annual_income_cents
        subscriber["last_3mo_income_cents"] = last_3mo_income_cents
        subscriber["qualifying_benefit"] = attested_benefit
        db.touch(subscriber)
        tribal = subscriber["tribal_lands_flag"]
    else:
        tribal = False

    evaluated = calc.annualize_three_month(last_3mo_income_cents)
    threshold = calc.fpg_income_threshold(household_size, tribal)
    enrollment["recert_evaluated_income_cents"] = evaluated
    enrollment["recert_income_threshold_cents"] = threshold

    qualifies = attested_benefit != "NONE" or evaluated <= threshold
    if qualifies:
        enrollment["recert_status"] = "NOT_DUE"
        enrollment["recert_last_responded_at"] = now
        enrollment["recert_notice_sent_at"] = None
        enrollment["recert_response_deadline_at"] = None
        enrollment["recert_due_date"] = calc.recert_due_date(now)
        derive.recompute_risk(enrollment)
        db.touch(enrollment)
    else:
        enrollment["recert_status"] = "RESPONDED_INELIGIBLE"
        cascades.de_enroll(enrollment, "INELIGIBLE_ON_RECERT", caller.user_id)

    return response.ok(derive.enrollment_json(enrollment))


@bp.post("/lifeline/enrollments/<enrollment_id>/de-enroll")
def de_enroll_endpoint(enrollment_id):
    caller = authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    enrollment = get_enrollment(enrollment_id)

    body = v.get_body()
    reason = v.enum_field(body, "de_enrollment_reason",
                          MANUAL_DE_ENROLLMENT_REASONS)
    v.string_field(body, "note", required=False, min_len=0, default=None)

    require_provider_owner(caller, enrollment["provider_id"])

    if enrollment["benefit_status"] == "DE_ENROLLED":
        raise ApiError("ERR_ENROLLMENT_ALREADY_DE_ENROLLED",
                       "The benefit has already been de-enrolled")

    cascades.de_enroll(enrollment, reason, caller.user_id)
    return response.ok(derive.enrollment_json(enrollment))
