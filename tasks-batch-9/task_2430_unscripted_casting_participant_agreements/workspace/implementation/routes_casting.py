"""Casting calls, applicant intake, screening items and minor protections."""

from flask import Blueprint

import calc
import services
import store
from clock import clock, parse_date, parse_iso
from envelope import list_response, object_response
from errors import ApiError
from store import serialize, serialize_all, touch
from validation import (
    ALL_ROLES,
    OPERATOR_ROLES,
    authenticate,
    filter_arg,
    json_body,
    opt_date,
    opt_datetime,
    opt_enum,
    opt_int,
    opt_number,
    opt_string,
    pagination,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_number,
    req_string,
    require_after,
    require_owner,
)

bp = Blueprint("casting", __name__)

STATE_CODES = ("CA", "NY", "GA", "IL")
CHANNELS = ("OPEN_CALL", "DIGITAL_SUBMISSION", "REFERRAL")
SCREENING_KINDS = ("INTERVIEW", "BACKGROUND_CHECK", "PSYCH_EVAL", "MEDICAL_EXAM")
OUTCOMES_INPUT = ("PENDING", "PASS", "CONDITIONAL", "FAIL")
OUTCOMES_RECORDED = ("PASS", "CONDITIONAL", "FAIL")
BLOCKED_SCREENING = ("WITHDRAWN", "REJECTED")


def completed_age(date_of_birth, reference_iso):
    """Completed age in whole years at the reference instant."""
    born = parse_date(date_of_birth)
    reference = parse_iso(reference_iso).date()
    age = reference.year - born.year
    if (reference.month, reference.day) < (born.month, born.day):
        age -= 1
    return age


# ----------------------------------------------------------------- casting calls
@bp.post("/casting/casting-calls")
def draft_casting_call():
    authenticate(("CastingDirector",))
    body = json_body()

    # rung 6 — body foreign keys, left to right
    production = None
    if isinstance(body.get("production_id"), str):
        production = services.get_production(body["production_id"])
    if isinstance(body.get("venue_location_id"), str):
        services.get_location(body["venue_location_id"])

    # rung 7 — body shape
    production_id = req_string(body, "production_id")
    if production is None:
        production = services.get_production(production_id)
    channel = req_enum(body, "channel", CHANNELS)
    min_age = req_int(body, "min_age", minimum=13, maximum=80)
    max_age = req_int(body, "max_age", minimum=13, maximum=99)
    if max_age < min_age:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'max_age' must be >= 'min_age'.")
    exclusivity_window_days = req_int(body, "exclusivity_window_days", minimum=0, maximum=730)
    residency_state_code = opt_enum(body, "residency_state_code", STATE_CODES)
    venue_location_id = opt_string(body, "venue_location_id")
    open_call_window_start_utc = opt_datetime(body, "open_call_window_start_utc")
    open_call_window_end_utc = opt_datetime(body, "open_call_window_end_utc")
    require_after(
        body,
        "open_call_window_end_utc",
        "open_call_window_start_utc",
        open_call_window_end_utc,
        open_call_window_start_utc,
    )
    expected_attendance = opt_int(body, "expected_attendance", default=0, minimum=0)

    record = store.new_record(
        "casting_call",
        {
            "production_id": production["id"],
            "venue_location_id": venue_location_id,
            "channel": channel,
            "min_age": min_age,
            "max_age": max_age,
            "residency_state_code": residency_state_code,
            "open_call_window_start_utc": open_call_window_start_utc,
            "open_call_window_end_utc": open_call_window_end_utc,
            "expected_attendance": expected_attendance,
            "exclusivity_window_days": exclusivity_window_days,
            "status": "DRAFT",
            "published_at": None,
            "closed_reason": None,
            "screened_pass_count": 0,
        },
    )
    store.casting_calls[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/casting-calls")
def list_casting_calls():
    authenticate(OPERATOR_ROLES)
    limit, offset = pagination()
    records = store.by_seq(list(store.casting_calls.values()))
    production_id = filter_arg("production_id")
    if production_id is not None:
        records = [r for r in records if r["production_id"] == production_id]
    venue_location_id = filter_arg("venue_location_id")
    if venue_location_id is not None:
        records = [r for r in records if r["venue_location_id"] == venue_location_id]
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    channel = filter_arg("channel")
    if channel is not None:
        records = [r for r in records if r["channel"] == channel]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.get("/casting/casting-calls/<call_id>")
def read_casting_call(call_id):
    authenticate(OPERATOR_ROLES)
    call = services.get_casting_call(call_id)
    return object_response(serialize(call))


@bp.post("/casting/casting-calls/<call_id>/publish")
def publish_casting_call(call_id):
    authenticate(("CastingDirector",))
    call = services.get_casting_call(call_id)
    production = services.production_of_call(call)

    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    if production["casting_posture"] == "RESTRICTED":
        raise ApiError("ERR_CASTING_RESTRICTED")
    if call["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if call["channel"] == "OPEN_CALL":
        if (
            call["venue_location_id"] is None
            or call["open_call_window_start_utc"] is None
            or call["open_call_window_end_utc"] is None
            or call["expected_attendance"] is None
        ):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "An OPEN_CALL requires a venue, both window bounds and an expected attendance.",
            )
        location = services.get_location(call["venue_location_id"])
        start = parse_iso(call["open_call_window_start_utc"])
        end = parse_iso(call["open_call_window_end_utc"])
        aggregate = call["expected_attendance"]
        for other in store.casting_calls.values():
            if other["id"] == call["id"]:
                continue
            if other["status"] != "PUBLISHED" or other["channel"] != "OPEN_CALL":
                continue
            if other["venue_location_id"] != location["id"]:
                continue
            if other["open_call_window_start_utc"] is None or other["open_call_window_end_utc"] is None:
                continue
            other_start = parse_iso(other["open_call_window_start_utc"])
            other_end = parse_iso(other["open_call_window_end_utc"])
            # inclusive windows intersect unless one starts after the other ends
            if start > other_end or other_start > end:
                continue
            aggregate += other["expected_attendance"]
        if aggregate > location["capacity"]:
            raise ApiError("ERR_VENUE_CAPACITY_EXCEEDED")

    call["status"] = "PUBLISHED"
    call["published_at"] = clock.now_iso()
    touch(call)
    return object_response(serialize(call))


@bp.post("/casting/casting-calls/<call_id>/close")
def close_casting_call(call_id):
    authenticate(("CastingDirector",))
    call = services.get_casting_call(call_id)
    if call["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    call["status"] = "CLOSED"
    call["closed_reason"] = "DIRECTOR_CLOSED"
    touch(call)
    return object_response(serialize(call))


@bp.get("/casting/casting-calls/<call_id>/applicants")
def list_call_applicants(call_id):
    authenticate(OPERATOR_ROLES)
    call = services.get_casting_call(call_id)
    limit, offset = pagination()
    records = services.applicants_of_call(call["id"])
    screening_status = filter_arg("screening_status")
    if screening_status is not None:
        records = [r for r in records if r["screening_status"] == screening_status]
    medical_status = filter_arg("medical_status")
    if medical_status is not None:
        records = [r for r in records if r["medical_status"] == medical_status]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


# ------------------------------------------------------------------- applicants
@bp.post("/casting/applicants")
def create_applicant():
    authenticate(("CastingDirector",))
    body = json_body()

    # rung 6
    call = None
    if isinstance(body.get("casting_call_id"), str):
        call = services.get_casting_call(body["casting_call_id"])

    # rung 7
    casting_call_id = req_string(body, "casting_call_id")
    if call is None:
        call = services.get_casting_call(casting_call_id)
    legal_name = req_string(body, "legal_name")
    date_of_birth = req_date(body, "date_of_birth")
    residency_state_code = req_enum(body, "residency_state_code", STATE_CODES)
    guardian_name = opt_string(body, "guardian_name")

    production = services.production_of_call(call)

    # rung 11 / 12
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    if production["casting_posture"] == "RESTRICTED" and call["channel"] == "OPEN_CALL":
        raise ApiError("ERR_CASTING_RESTRICTED")
    # rung 15
    if call["status"] != "PUBLISHED":
        raise ApiError("ERR_CASTING_CALL_NOT_OPEN")
    # rung 16
    if call["channel"] == "OPEN_CALL":
        now = clock.now()
        window_start = parse_iso(call["open_call_window_start_utc"]) if call["open_call_window_start_utc"] else None
        window_end = parse_iso(call["open_call_window_end_utc"]) if call["open_call_window_end_utc"] else None
        if window_start is None or window_end is None or now < window_start or now > window_end:
            raise ApiError("ERR_OPEN_CALL_WINDOW_CLOSED")

    age = completed_age(date_of_birth, production["photography_start_utc"])
    # rung 33
    if age < call["min_age"] or age > call["max_age"]:
        raise ApiError("ERR_ELIGIBILITY_NOT_MET")
    if call["residency_state_code"] is not None and residency_state_code != call["residency_state_code"]:
        raise ApiError("ERR_ELIGIBILITY_NOT_MET")

    is_minor = age < 18
    # rung 34
    if is_minor and not guardian_name:
        raise ApiError("ERR_GUARDIAN_REQUIRED")

    record = store.new_record(
        "applicant",
        {
            "casting_call_id": call["id"],
            "legal_name": legal_name,
            "date_of_birth": date_of_birth,
            "residency_state_code": residency_state_code,
            "guardian_name": guardian_name,
            "is_minor": is_minor,
            "screening_status": "SUBMITTED",
            "medical_status": "NOT_STARTED",
            "psych_eval_required": production["format_type"] == "COMPETITION_HIGH_STRESS" or is_minor,
            "provisional_risk_score": 0,
            "final_risk_score": 0,
            "enhanced_support_required": False,
        },
    )
    store.applicants[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/applicants/<applicant_id>")
def read_applicant(applicant_id):
    user_id, role = authenticate(ALL_ROLES)
    require_owner(role, user_id, applicant_id)
    applicant = services.get_applicant(applicant_id)
    return object_response(serialize(applicant))


@bp.post("/casting/applicants/<applicant_id>/withdraw")
def withdraw_applicant(applicant_id):
    user_id, role = authenticate(("Applicant",))
    require_owner(role, user_id, applicant_id)
    applicant = services.get_applicant(applicant_id)
    body = json_body()
    reason = req_string(body, "reason")

    if applicant["screening_status"] in BLOCKED_SCREENING:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    applicant["screening_status"] = "WITHDRAWN"
    touch(applicant)

    affected = {}
    voided_any = False
    for agreement in services.agreements_of_applicant(applicant["id"]):
        if agreement["status"] not in services.LIVE_AGREEMENT:
            continue
        prior = agreement["status"]
        agreement["status"] = "VOIDED"
        agreement["void_reason"] = "APPLICANT_WITHDRAWN"
        touch(agreement)
        voided_any = True
        if prior == "EXECUTED":
            agreement["total_stipend_commitment_cents"] = 0
            services.excuse_scheduled_obligations(agreement)
        production = services.production_of_agreement(agreement)
        if production is not None:
            affected[production["id"]] = production

    if voided_any:
        services.release_packets_of_applicant(applicant["id"])

    for production in affected.values():
        services.recompute_stipend_committed(production)
        services.recompute_minor_participant_count(production)
        services.recompute_trust_escrow(production)
        touch(production)
        services.recompute_posture(production)

    return object_response(serialize(applicant))


# --------------------------------------------------------------- screening items
@bp.post("/casting/applicants/<applicant_id>/screening-items")
def open_screening_item(applicant_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    applicant = services.get_applicant(applicant_id)
    body = json_body()
    kind = req_enum(body, "kind", SCREENING_KINDS)
    outcome = opt_enum(body, "outcome", OUTCOMES_INPUT, default="PENDING")
    severity_flags = opt_int(body, "severity_flags", default=0, minimum=0, maximum=5)
    conditional_conditions = opt_string(body, "conditional_conditions")

    # rung 13
    if applicant["screening_status"] in BLOCKED_SCREENING:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    recorded_now = outcome != "PENDING"
    # rung 19
    if recorded_now:
        services.four_eyes_screening_guard(applicant["id"], kind, user_id)

    record = store.new_record(
        "screening_item",
        {
            "applicant_id": applicant["id"],
            "kind": kind,
            "outcome": "PENDING",
            "severity_flags": severity_flags,
            "conditional_conditions": conditional_conditions,
            "recorded_by_user_id": None,
            "recorded_at": None,
            "expires_at": None,
        },
    )
    store.screening_items[record["id"]] = record
    if recorded_now:
        services.record_outcome_on_item(
            record, outcome, severity_flags, conditional_conditions, user_id
        )

    services.apply_screening_write(applicant, record, recorded_now)
    return object_response(serialize(record), 201)


@bp.get("/casting/applicants/<applicant_id>/screening-items")
def list_screening_items(applicant_id):
    authenticate(OPERATOR_ROLES)
    applicant = services.get_applicant(applicant_id)
    limit, offset = pagination()
    records = services.items_of_applicant(applicant["id"])
    kind = filter_arg("kind")
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    outcome = filter_arg("outcome")
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.post("/casting/screening-items/<item_id>/record-outcome")
def record_screening_outcome(item_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    item = services.get_screening_item(item_id)
    body = json_body()
    outcome = req_enum(body, "outcome", OUTCOMES_RECORDED)
    severity_flags = req_int(body, "severity_flags", minimum=0, maximum=5)
    conditional_conditions = opt_string(body, "conditional_conditions")

    applicant = services.get_applicant(item["applicant_id"])
    # rung 13
    if item["outcome"] != "PENDING" or applicant["screening_status"] in BLOCKED_SCREENING:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 19
    services.four_eyes_screening_guard(applicant["id"], item["kind"], user_id)

    services.record_outcome_on_item(item, outcome, severity_flags, conditional_conditions, user_id)
    touch(item)
    services.apply_screening_write(applicant, item, True)
    return object_response(serialize(item))


# ------------------------------------------------------------ minor protections
def _jurisdiction_minimums(applicant):
    production = services.production_of_applicant(applicant)
    code = production["jurisdiction_code"]
    return (
        calc.MIN_EDUCATION_HOURS_BY_JURISDICTION[code],
        calc.MIN_TRUST_PCT_BY_JURISDICTION[code],
        production,
    )


@bp.post("/casting/applicants/<applicant_id>/minor-protections")
def file_minor_protection(applicant_id):
    authenticate(("ComplianceOfficer",))
    applicant = services.get_applicant(applicant_id)
    body = json_body()
    work_permit_number = req_string(body, "work_permit_number")
    permit_expires_on = req_date(body, "permit_expires_on")
    education_hours = req_int(body, "education_hours_scheduled_weekly", minimum=0, maximum=40)
    trust_deposit_pct = req_number(body, "trust_deposit_pct", minimum=0, maximum=1)

    min_hours, min_pct, production = _jurisdiction_minimums(applicant)
    # rung 27
    if education_hours < min_hours:
        raise ApiError("ERR_EDUCATION_HOURS_SHORTFALL")
    # rung 46
    if calc.dec(trust_deposit_pct) < min_pct:
        raise ApiError("ERR_TRUST_DEPOSIT_SHORTFALL")

    record = store.new_record(
        "minor_protection",
        {
            "applicant_id": applicant["id"],
            "work_permit_number": work_permit_number,
            "permit_expires_on": permit_expires_on,
            "education_hours_scheduled_weekly": education_hours,
            "trust_deposit_pct": trust_deposit_pct,
            "trust_deposited_cents": 0,
            "installment_count": None,
            "per_installment_cents": 0,
            "status": "INCOMPLETE",
        },
    )
    record["status"] = services.derive_packet_status(record, production)
    store.minor_protections[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/applicants/<applicant_id>/minor-protections")
def list_minor_protections(applicant_id):
    authenticate(OPERATOR_ROLES)
    applicant = services.get_applicant(applicant_id)
    limit, offset = pagination()
    records = services.packets_of_applicant(applicant["id"])
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.patch("/casting/minor-protections/<packet_id>")
def amend_minor_protection(packet_id):
    authenticate(("ComplianceOfficer",))
    packet = services.get_minor_protection(packet_id)
    body = json_body()
    work_permit_number = opt_string(body, "work_permit_number")
    permit_expires_on = opt_date(body, "permit_expires_on")
    education_hours = opt_int(body, "education_hours_scheduled_weekly", minimum=0, maximum=40)
    trust_deposit_pct = opt_number(body, "trust_deposit_pct", minimum=0, maximum=1)

    applicant = services.get_applicant(packet["applicant_id"])
    min_hours, min_pct, production = _jurisdiction_minimums(applicant)

    effective_hours = (
        education_hours if education_hours is not None else packet["education_hours_scheduled_weekly"]
    )
    effective_pct = trust_deposit_pct if trust_deposit_pct is not None else packet["trust_deposit_pct"]
    # rung 27
    if effective_hours < min_hours:
        raise ApiError("ERR_EDUCATION_HOURS_SHORTFALL")
    # rung 46
    if calc.dec(effective_pct) < min_pct:
        raise ApiError("ERR_TRUST_DEPOSIT_SHORTFALL")

    if work_permit_number is not None:
        packet["work_permit_number"] = work_permit_number
    if permit_expires_on is not None:
        packet["permit_expires_on"] = permit_expires_on
    if education_hours is not None:
        packet["education_hours_scheduled_weekly"] = education_hours
    if trust_deposit_pct is not None:
        packet["trust_deposit_pct"] = trust_deposit_pct

    if packet["status"] in ("INCOMPLETE", "COMPLETE"):
        packet["status"] = services.derive_packet_status(packet, production)
    touch(packet)
    return object_response(serialize(packet))


@bp.post("/casting/minor-protections/<packet_id>/trust-deposits")
def deposit_trust(packet_id):
    authenticate(("BusinessAffairs",))
    packet = services.get_minor_protection(packet_id)
    body = json_body()
    installment_count = req_int(body, "installment_count", minimum=1, maximum=24)

    # rung 17
    agreement = services.executed_agreement_of_applicant(packet["applicant_id"])
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")

    per_installment, deposited = calc.trust_deposit_schedule(
        agreement["total_stipend_commitment_cents"], packet["trust_deposit_pct"], installment_count
    )
    packet["installment_count"] = installment_count
    packet["per_installment_cents"] = per_installment
    packet["trust_deposited_cents"] = deposited
    touch(packet)

    production = services.production_of_agreement(agreement)
    if production is not None:
        services.recompute_trust_escrow(production)
        touch(production)
    return object_response(serialize(packet))
