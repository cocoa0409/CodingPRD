"""State-transition preconditions and invalid-transition rejections.

Queue B (Corner): state_machines section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    make_proctor_headers,
    make_examiner_headers,
    create_driver_record,
    create_examiner,
    pass_knowledge_test,
    book_appointment,
    active_licensed_record,
    active_record_with_medical_card,
    suspend_active_record,
    setup_served_suspension,
    get_first_suspension,
    capture_fee,
    get_record_version,
    create_cdl_endorsement_payload,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")
PROCTOR = make_proctor_headers("kp-1")


# ===========================================================================
# Corner/state_machines/grade_already_passed_knowledge_test_rejected
# ===========================================================================
def test_grade_already_passed_knowledge_test_rejected(api):
    """PRD §3.3: "Grading requires the test to be in SCHEDULED status (otherwise
    ERR_TEST_NOT_SCHEDULED)."
    PRD §3.3: "the test transitions SCHEDULED → PASSED, which is terminal."

    A second grade on a PASSED test -> ERR_TEST_NOT_SCHEDULED 409; status unchanged.

    Design: Corner/state_machines/grade_already_passed_knowledge_test_rejected
    """
    record = create_driver_record(full_name="Eli Pass", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 0}, PROCTOR)
    )
    validate_success(api.grade_knowledge_test(kt["id"], {"correct_answers": 40}, PROCTOR), 200)
    resp = api.grade_knowledge_test(kt["id"], {"correct_answers": 35}, PROCTOR)
    validate_error(resp, "ERR_TEST_NOT_SCHEDULED", expected_status=409)
    fetched = get_success_data(api.list_record_knowledge_tests(record["id"], PROCTOR))
    items = fetched if isinstance(fetched, list) else fetched.get("data", fetched)
    assert items[0]["status"] == "PASSED"


# ===========================================================================
# Corner/state_machines/grade_before_scheduled_period_rejected
# ===========================================================================
def test_grade_before_scheduled_period_rejected(api):
    """PRD §3.3: "Grading requires the test to be in SCHEDULED status (otherwise
    ERR_TEST_NOT_SCHEDULED) and the current clock to have reached the
    scheduled_period (otherwise ERR_TEST_NOT_YET_DUE)."

    Grading a sitting scheduled at period 5 while the clock is 0 -> ERR_TEST_NOT_YET_DUE.

    Design: Corner/state_machines/grade_before_scheduled_period_rejected
    """
    record = create_driver_record(full_name="Fay Early", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 5}, PROCTOR)
    )
    resp = api.grade_knowledge_test(kt["id"], {"correct_answers": 40}, PROCTOR)
    validate_error(resp, "ERR_TEST_NOT_YET_DUE", expected_status=409)


# ===========================================================================
# Corner/state_machines/reinstate_before_eligible_rejected
# ===========================================================================
def test_reinstate_before_eligible_rejected(api):
    """PRD §3.7: "the suspension must be SERVED — equivalently, the current clock
    must be at or past eligible_period, otherwise ERR_NOT_YET_ELIGIBLE."

    Reinstating an ACTIVE (not yet SERVED) suspension while the clock is still 0
    -> ERR_NOT_YET_ELIGIBLE 409; licensing stays SUSPENDED.

    Design: Corner/state_machines/reinstate_before_eligible_rejected
    """
    ctx = active_licensed_record(full_name="Gus Early", opaque_user_id="exu-erl")
    record = ctx["record"]
    suspend_active_record(record["id"], points=12, occurred_period=0)
    suspension = get_first_suspension(record["id"])
    capture_fee(record["id"], "REINSTATEMENT", 20000)
    version = get_record_version(record["id"])
    resp = api.reinstate_suspension(
        suspension["id"], {"expected_driver_record_version": version}, CLERK,
    )
    validate_error(resp, "ERR_NOT_YET_ELIGIBLE", expected_status=409)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "SUSPENDED"


# ===========================================================================
# Corner/state_machines/proctor_by_wrong_examiner_rejected
# ===========================================================================
def test_proctor_by_wrong_examiner_rejected(api):
    """PRD §3.4: "Proctoring advances the appointment BOOKED → PROCTORED and is
    restricted to the assigned examiner: the acting Examiner id must equal the
    appointment's examiner_id, or the call is rejected with ERR_EXAMINER_MISMATCH."

    Examiner E2 proctoring E1's appointment -> ERR_EXAMINER_MISMATCH 403.

    Design: Corner/state_machines/proctor_by_wrong_examiner_rejected
    """
    record = create_driver_record(full_name="Hal Wrong", date_of_birth="1990-01-01")
    pass_knowledge_test(record["id"])
    ex1 = create_examiner(certified_classes=["D"], opaque_user_id="exu-e1", full_name="Ex E1")
    ex2 = create_examiner(certified_classes=["D"], opaque_user_id="exu-e2", full_name="Ex E2")
    appt = book_appointment(record["id"], ex1, license_class="D",
                            slot_start_period=0, slot_end_period=1)
    resp = api.proctor_appointment(
        appt["id"], {"maneuver_scores": [{"maneuver": "ALL", "weight": 1, "auto_score": 95}]},
        make_examiner_headers(ex2["id"]),
    )
    validate_error(resp, "ERR_EXAMINER_MISMATCH", expected_status=403)


# ===========================================================================
# Corner/state_machines/cdl_reinstate_when_not_downgraded_rejected
# ===========================================================================
def test_cdl_reinstate_when_not_downgraded_rejected(api):
    """PRD §3.8: "the clerk reinstates CDL privileges, which requires the record's
    cdl_status to be MEDICALLY_DOWNGRADED (otherwise ERR_CDL_NOT_DOWNGRADED)."

    A record with cdl_status NONE cannot be CDL-reinstated -> ERR_CDL_NOT_DOWNGRADED.

    Design: Corner/state_machines/cdl_reinstate_when_not_downgraded_rejected
    """
    record = create_driver_record(full_name="Ida None", date_of_birth="1986-01-01")
    resp = api.cdl_reinstate(record["id"], CLERK)
    validate_error(resp, "ERR_CDL_NOT_DOWNGRADED", expected_status=409)


# ===========================================================================
# Corner/state_machines/revoke_below_prior_suspension_threshold_rejected
# ===========================================================================
def test_revoke_below_prior_suspension_threshold_rejected(api):
    """PRD §3.7: "Revocation requires the record to be SUSPENDED (otherwise
    ERR_RECORD_NOT_SUSPENDED) and its prior_suspension_count to be at least the
    revocation threshold of 3 (otherwise ERR_REVOCATION_THRESHOLD_NOT_MET)."

    A SUSPENDED record on its first-ever suspension (prior_suspension_count 0)
    cannot be revoked -> ERR_REVOCATION_THRESHOLD_NOT_MET; stays SUSPENDED.

    Design: Corner/state_machines/revoke_below_prior_suspension_threshold_rejected
    """
    ctx = active_licensed_record(full_name="Jay Susp", opaque_user_id="exu-rev")
    record = ctx["record"]
    suspend_active_record(record["id"], points=12, occurred_period=0)
    resp = api.revoke_record(record["id"], {"reason": "attempt"}, OFFICER)
    validate_error(resp, "ERR_REVOCATION_THRESHOLD_NOT_MET", expected_status=409)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "SUSPENDED"


# ===========================================================================
# Corner/state_machines/cdl_grant_first_endorsement_activates_track
# ===========================================================================
def test_cdl_grant_first_endorsement_activates_track(api):
    """PRD §3.8: "When the record's cdl_status is still NONE, granting the first
    endorsement also requires — this is the single cross-dimension guard — that
    the record's licensing_status be ACTIVE (otherwise ERR_RECORD_NOT_ACTIVE), and
    on success it advances cdl_status from NONE to ACTIVE. The endorsement opens in
    GRANTED status."

    Design: Corner/state_machines/cdl_grant_first_endorsement_activates_track
    """
    ctx = active_record_with_medical_card(
        valid_through_period=100, license_class="A", opaque_user_id="exu-cdl",
        full_name="Kit Cdl",
    )
    record = ctx["record"]
    endorsement = validate_success(
        api.create_cdl_endorsement(
            create_cdl_endorsement_payload(record["id"], endorsement_code="H"), CLERK,
        ),
        201,
    )
    assert endorsement["status"] == "GRANTED"
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["cdl_status"] == "ACTIVE"
