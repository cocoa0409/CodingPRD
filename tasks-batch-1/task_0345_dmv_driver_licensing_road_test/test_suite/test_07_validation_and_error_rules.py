"""Body-domain validations and operation-specific error rules.

Queue B (Corner): validations, errors sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    make_proctor_headers,
    create_driver_record,
    create_examiner,
    eligible_record_with_passed_appointment,
    setup_served_suspension,
    active_licensed_record,
    suspend_active_record,
    get_first_suspension,
    capture_fee,
    get_record_version,
    create_license_payload,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")
PROCTOR = make_proctor_headers("kp-1")


# ===========================================================================
# Corner/validations/occurred_period_in_future_rejected
# ===========================================================================
def test_violation_occurred_period_in_future_rejected(api):
    """PRD §3.7: "the occurred_period it took place, which must be at or before the
    current clock (otherwise ERR_OCCURRED_IN_FUTURE)."

    occurred_period 10 with the clock at 0 -> ERR_OCCURRED_IN_FUTURE 400.

    Design: Corner/validations/occurred_period_in_future_rejected
    """
    record = create_driver_record(full_name="Oda Fut", date_of_birth="1986-01-01")
    resp = api.create_violation(
        {"driver_record_id": record["id"], "code": "SPEEDING_10_OVER",
         "points": 4, "occurred_period": 10}, OFFICER,
    )
    validate_error(resp, "ERR_OCCURRED_IN_FUTURE", expected_status=400)


# ===========================================================================
# Corner/validations/knowledge_scheduled_in_past_rejected
# ===========================================================================
def test_knowledge_scheduled_in_past_rejected(api):
    """PRD §3.3: "The chosen scheduled_period must be at or after the current clock
    at booking time, or the booking is rejected as ERR_SCHEDULED_IN_PAST."

    With the clock advanced to 5, scheduling at period 0 -> ERR_SCHEDULED_IN_PAST.

    Design: Corner/validations/knowledge_scheduled_in_past_rejected
    """
    record = create_driver_record(full_name="Pia Past", date_of_birth="1986-01-01")
    api.advance_clock(5, OFFICER)
    resp = api.create_knowledge_test(
        {"driver_record_id": record["id"], "scheduled_period": 0}, PROCTOR,
    )
    validate_error(resp, "ERR_SCHEDULED_IN_PAST", expected_status=400)


# ===========================================================================
# Corner/validations/road_slot_end_not_after_start_rejected
# ===========================================================================
def test_road_slot_end_not_after_start_rejected(api):
    """PRD §3.4: "The slot is a half-open interval: slot_end_period must be
    strictly greater than slot_start_period, and a booking that violates this is
    rejected with ERR_INVALID_SLOT_INTERVAL."

    slot_start_period 10 == slot_end_period 10 -> ERR_INVALID_SLOT_INTERVAL 400.

    Design: Corner/validations/road_slot_end_not_after_start_rejected
    """
    record = create_driver_record(full_name="Qi Slot", date_of_birth="1986-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-slot")
    resp = api.create_road_test_appointment(
        {"driver_record_id": record["id"], "examiner_id": examiner["id"],
         "license_class": "D", "slot_start_period": 10, "slot_end_period": 10}, CLERK,
    )
    validate_error(resp, "ERR_INVALID_SLOT_INTERVAL", expected_status=400)


# ===========================================================================
# Corner/validations/examiner_not_certified_for_class_rejected
# ===========================================================================
def test_examiner_not_certified_for_class_rejected(api):
    """PRD §3.4: "The examiner must be certified for the requested class — the
    appointment's license_class must appear in the examiner's certified_classes
    list, or the booking fails with ERR_EXAMINER_NOT_CERTIFIED."

    Booking class A on an examiner certified only for [D] -> ERR_EXAMINER_NOT_CERTIFIED.

    Design: Corner/validations/examiner_not_certified_for_class_rejected
    """
    record = create_driver_record(full_name="Rob Cert", date_of_birth="1986-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-donly")
    resp = api.create_road_test_appointment(
        {"driver_record_id": record["id"], "examiner_id": examiner["id"],
         "license_class": "A", "slot_start_period": 0, "slot_end_period": 1}, CLERK,
    )
    validate_error(resp, "ERR_EXAMINER_NOT_CERTIFIED", expected_status=409)


# ===========================================================================
# Corner/validations/real_id_approve_insufficient_documents_rejected
# ===========================================================================
def test_real_id_approve_insufficient_documents_rejected(api):
    """PRD §3.2: "A decision to approve requires that the last submitted documents
    covered all three categories — that is, real_id_categories_met equals 3 — and
    on approval real_id_status advances to APPROVED; if fewer than all three
    categories are covered the approval is rejected with ERR_INSUFFICIENT_DOCUMENTS
    (HTTP 422)."

    Documents covering only IDENTITY + RESIDENCY (2 of 3) -> 422; status stays SUBMITTED.

    Design: Corner/validations/real_id_approve_insufficient_documents_rejected
    """
    record = create_driver_record(full_name="Sue Doc", date_of_birth="1986-01-01")
    submitted = validate_success(
        api.real_id_submit(
            record["id"],
            {"documents": [
                {"doc_type": "PASSPORT", "category": "IDENTITY"},
                {"doc_type": "LEASE", "category": "RESIDENCY"},
            ]},
            CLERK,
        ),
        200,
    )
    assert submitted["real_id_status"] == "SUBMITTED"
    resp = api.real_id_adjudicate(record["id"], {"decision": "APPROVE"}, CLERK)
    validate_error(resp, "ERR_INSUFFICIENT_DOCUMENTS", expected_status=422)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["real_id_status"] == "SUBMITTED"


# ===========================================================================
# Corner/validations/real_id_license_without_verification_rejected
# ===========================================================================
def test_real_id_license_without_verification_rejected(api):
    """PRD §3.6: "when is_real_id is true the record's real_id_status must be
    APPROVED (otherwise ERR_REAL_ID_NOT_VERIFIED)."

    Issuing with is_real_id true while real_id_status is NONE -> ERR_REAL_ID_NOT_VERIFIED.

    Design: Corner/validations/real_id_license_without_verification_rejected
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", opaque_user_id="exu-rid", full_name="Tia NoRid",
    )
    record, appt = ctx["record"], ctx["appointment"]
    capture_fee(record["id"], "RENEWAL", 7000)
    resp = api.create_license(
        create_license_payload(record["id"], appt["id"], license_class="D", is_real_id=True),
        CLERK,
    )
    validate_error(resp, "ERR_REAL_ID_NOT_VERIFIED", expected_status=409)


# ===========================================================================
# Corner/errors/reinstate_without_fee_unpaid_error
# ===========================================================================
def test_reinstate_without_fee_unpaid_error(api):
    """PRD §3.7: "a captured fee payment of purpose REINSTATEMENT for this record
    must exist whose cents amount is at least the reinstatement fee converted to
    cents ... or the request is rejected with ERR_REINSTATEMENT_FEE_UNPAID."

    A SERVED suspension with no REINSTATEMENT fee captured -> 402.

    Design: Corner/errors/reinstate_without_fee_unpaid_error
    """
    ctx = setup_served_suspension(full_name="Xan Nofee", opaque_user_id="exu-nf")
    record, suspension = ctx["record"], ctx["suspension"]
    version = get_record_version(record["id"])
    resp = api.reinstate_suspension(
        suspension["id"], {"expected_driver_record_version": version}, CLERK,
    )
    validate_error(resp, "ERR_REINSTATEMENT_FEE_UNPAID", expected_status=402)


# ===========================================================================
# Corner/errors/dismiss_suspension_wrong_officer_segregation_error
# ===========================================================================
def test_dismiss_suspension_wrong_officer_segregation_error(api):
    """PRD §3.7: "the segregation rule — the acting X-User-ID to differ from that
    triggering violation's recorded_by_officer (otherwise ERR_SEGREGATION_OF_DUTIES)."

    The same officer who recorded the (now DISMISSED) triggering violation tries to
    dismiss the suspension -> ERR_SEGREGATION_OF_DUTIES 403; suspension stays ACTIVE.

    Design: Corner/errors/dismiss_suspension_wrong_officer_segregation_error
    """
    ctx = active_licensed_record(full_name="Yon Sod", opaque_user_id="exu-sod")
    record = ctx["record"]
    violation = suspend_active_record(record["id"], points=12, occurred_period=0)
    suspension = get_first_suspension(record["id"])
    validate_success(api.dismiss_violation(violation["id"], OFFICER), 200)
    # Act as officer-1, the recording officer.
    resp = api.dismiss_suspension(suspension["id"], OFFICER)
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    susp = validate_success(api.get_suspension(suspension["id"], CLERK), 200)
    assert susp["status"] == "ACTIVE"
