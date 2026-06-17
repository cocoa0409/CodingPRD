"""Cross-entity state dependencies, resource overlap, compensating invariants.

Queue A (Difficulty): cross_entity_state_dependency, resource_temporal_overlap,
compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    create_license_payload,
    create_cdl_endorsement_payload,
    create_driver_record,
    create_examiner,
    book_appointment,
    eligible_record_with_passed_appointment,
    active_licensed_record,
    suspend_active_record,
    get_first_suspension,
    capture_fee,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


# ===========================================================================
# cross_entity_state_dependency / license_issue_requires_appointment_pass_outcome
# ===========================================================================
def test_license_issue_rejected_when_appointment_outcome_fail(api):
    """PRD §3.6: "the referenced road-test appointment must have outcome of PASS
    (otherwise ERR_ROAD_TEST_NOT_PASSED)."
    PRD §3.4: "sets outcome to PASS when final_score is at least the road-test
    passing threshold of 80, and to FAIL otherwise."

    An appointment scored to final 79.0 (outcome FAIL) cannot authorize issuance.

    Design: Difficulty/cross_entity_state_dependency/license_issue_requires_appointment_pass_outcome
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", opaque_user_id="exu-10", full_name="Ned Fail",
        auto_items=[("ALL", 1, 79)], score_items=[("ALL", 1, 79)],
    )
    record, appt = ctx["record"], ctx["appointment"]
    assert appt["outcome"] == "FAIL", f"got {appt['outcome']}"
    capture_fee(record["id"], "RENEWAL", 4000)
    resp = api.create_license(
        create_license_payload(record["id"], appt["id"], license_class="D"), CLERK,
    )
    validate_error(resp, "ERR_ROAD_TEST_NOT_PASSED", expected_status=409)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ELIGIBLE"


def test_license_issue_succeeds_when_appointment_outcome_pass(api):
    """PRD §3.6: "the referenced road-test appointment must have outcome of PASS
    (otherwise ERR_ROAD_TEST_NOT_PASSED)."
    PRD §3.6: "On success the system mints the license in ISSUED status ... advances
    the record's licensing_status from ELIGIBLE to ACTIVE."

    The same path with a PASS outcome issues the license, isolating the outcome
    dependency.

    Design: Difficulty/cross_entity_state_dependency/license_issue_requires_appointment_pass_outcome
    """
    ctx = active_licensed_record(
        license_class="D", opaque_user_id="exu-10b", full_name="Ned Pass",
    )
    assert ctx["appointment"]["outcome"] == "PASS"
    assert ctx["license"]["status"] == "ISSUED"
    rec = validate_success(api.get_driver_record(ctx["record"]["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"


# ===========================================================================
# cross_entity_state_dependency / cdl_grant_requires_valid_medical_card
# ===========================================================================
def test_cdl_grant_rejected_without_valid_medical_card(api):
    """PRD §3.8: "Granting requires a medical card for the record in VALID status
    whose valid_through_period is at or after the current clock (otherwise
    ERR_NO_VALID_MEDICAL_CARD)."

    An ACTIVE record with no medical card on file cannot be granted its first
    endorsement.

    Design: Difficulty/cross_entity_state_dependency/cdl_grant_requires_valid_medical_card
    """
    ctx = active_licensed_record(
        license_class="A", examiner_classes=["A"], opaque_user_id="exu-11",
        full_name="Oma Cdl",
    )
    record = ctx["record"]
    resp = api.create_cdl_endorsement(
        create_cdl_endorsement_payload(record["id"], endorsement_code="H"), CLERK,
    )
    validate_error(resp, "ERR_NO_VALID_MEDICAL_CARD", expected_status=409)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["cdl_status"] == "NONE"


def test_cdl_grant_succeeds_with_valid_medical_card(api):
    """PRD §3.8: "Granting requires a medical card for the record in VALID status
    whose valid_through_period is at or after the current clock (otherwise
    ERR_NO_VALID_MEDICAL_CARD)."
    PRD §3.8: "on success it advances cdl_status from NONE to ACTIVE. The
    endorsement opens in GRANTED status."

    With a VALID card on file the same grant succeeds, isolating the medical-card
    dependency.

    Design: Difficulty/cross_entity_state_dependency/cdl_grant_requires_valid_medical_card
    """
    from test_helpers import active_record_with_medical_card
    ctx = active_record_with_medical_card(
        valid_through_period=100, license_class="A", opaque_user_id="exu-11b",
        full_name="Oma Cdl 2",
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


# ===========================================================================
# resource_temporal_overlap / examiner_slot_overlap_rejected_half_open
# ===========================================================================
def test_examiner_slot_strict_overlap_rejected(api):
    """PRD §3.4: "the slot must not overlap any existing non-cancelled appointment
    on the same examiner; because intervals are half-open, two slots that merely
    touch at an endpoint (one slot's end equal to the next slot's start) do not
    overlap, but any genuine overlap is rejected with ERR_EXAMINER_SLOT_CONFLICT."

    Slots [10,20) and [15,25) genuinely overlap -> ERR_EXAMINER_SLOT_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/examiner_slot_overlap_rejected_half_open
    """
    dr1 = create_driver_record(full_name="Pat Ov1", date_of_birth="1990-01-01")
    dr2 = create_driver_record(full_name="Quin Ov2", date_of_birth="1990-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-12")
    book_appointment(dr1["id"], examiner, license_class="D",
                     slot_start_period=10, slot_end_period=20)
    resp = api.create_road_test_appointment(
        {"driver_record_id": dr2["id"], "examiner_id": examiner["id"],
         "license_class": "D", "slot_start_period": 15, "slot_end_period": 25},
        CLERK,
    )
    validate_error(resp, "ERR_EXAMINER_SLOT_CONFLICT", expected_status=409)


def test_examiner_slot_containment_overlap_rejected(api):
    """PRD §3.4: "the slot must not overlap any existing non-cancelled appointment
    on the same examiner ... any genuine overlap is rejected with
    ERR_EXAMINER_SLOT_CONFLICT."

    A fully contained slot [12,18) inside the existing [10,20) is a genuine
    overlap -> rejected.

    Design: Difficulty/resource_temporal_overlap/examiner_slot_overlap_rejected_half_open
    """
    dr1 = create_driver_record(full_name="Pat Ov3", date_of_birth="1990-01-01")
    dr2 = create_driver_record(full_name="Quin Ov4", date_of_birth="1990-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-12b")
    book_appointment(dr1["id"], examiner, license_class="D",
                     slot_start_period=10, slot_end_period=20)
    resp = api.create_road_test_appointment(
        {"driver_record_id": dr2["id"], "examiner_id": examiner["id"],
         "license_class": "D", "slot_start_period": 12, "slot_end_period": 18},
        CLERK,
    )
    validate_error(resp, "ERR_EXAMINER_SLOT_CONFLICT", expected_status=409)


# ===========================================================================
# resource_temporal_overlap / knowledge_sitting_same_period_rejected_point_occupancy
# ===========================================================================
def test_knowledge_sitting_same_period_rejected(api):
    """PRD §3.3: "A record may not have two sittings competing for the same slot:
    if another knowledge test for the same record is already SCHEDULED in the same
    scheduled_period, the new booking is rejected with
    ERR_KNOWLEDGE_SITTING_CONFLICT."

    Two sittings for the same record both at scheduled_period 5 -> the second is
    rejected.

    Design: Difficulty/resource_temporal_overlap/knowledge_sitting_same_period_rejected_point_occupancy
    """
    record = create_driver_record(full_name="Rae Sit", date_of_birth="1990-01-01")
    from test_helpers import make_proctor_headers
    proctor = make_proctor_headers("kp-1")
    get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 5}, proctor)
    )
    resp = api.create_knowledge_test(
        {"driver_record_id": record["id"], "scheduled_period": 5}, proctor,
    )
    validate_error(resp, "ERR_KNOWLEDGE_SITTING_CONFLICT", expected_status=409)


def test_knowledge_sitting_different_period_allowed(api):
    """PRD §3.3: "if another knowledge test for the same record is already
    SCHEDULED in the same scheduled_period, the new booking is rejected with
    ERR_KNOWLEDGE_SITTING_CONFLICT."

    A second sitting in a DIFFERENT period (6 vs 5) is point-distinct and is
    accepted, isolating the same-period occupancy rule.

    Design: Difficulty/resource_temporal_overlap/knowledge_sitting_same_period_rejected_point_occupancy
    """
    record = create_driver_record(full_name="Rae Sit 2", date_of_birth="1990-01-01")
    from test_helpers import make_proctor_headers
    proctor = make_proctor_headers("kp-1")
    get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 5}, proctor)
    )
    second = validate_success(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 6}, proctor),
        201,
    )
    assert second["scheduled_period"] == 6


# ===========================================================================
# compensating_invariant / dismiss_suspension_conserves_prior_suspension_count
# ===========================================================================
def test_dismiss_suspension_keeps_prior_suspension_count_zero(api):
    """PRD §3.7: "On success the suspension moves ACTIVE → LIFTED_BY_DISMISSAL, the
    record's licensing_status returns to ACTIVE, and — unlike a reinstatement —
    `prior_suspension_count` is *not* incremented."
    PRD §3.7: "The prior_suspension_count is the count of this record's
    suspensions in either SERVED or LIFTED_BY_REINSTATEMENT status."

    A dismissed suspension is never SERVED/LIFTED_BY_REINSTATEMENT, so
    prior_suspension_count stays 0.

    Design: Difficulty/compensating_invariant/dismiss_suspension_conserves_prior_suspension_count
    """
    ctx = active_licensed_record(full_name="Sam Comp", opaque_user_id="exu-13")
    record = ctx["record"]
    violation = suspend_active_record(record["id"], points=12, occurred_period=0)
    suspension = get_first_suspension(record["id"])
    # Dismiss the triggering violation (officer-1 recorded it), then dismiss the
    # suspension as a DIFFERENT officer (segregation of duties).
    validate_success(api.dismiss_violation(violation["id"], OFFICER), 200)
    susp = validate_success(api.dismiss_suspension(suspension["id"], OFFICER2), 200)
    assert susp["status"] == "LIFTED_BY_DISMISSAL"
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"
    assert rec["prior_suspension_count"] == 0, f"got {rec['prior_suspension_count']}"


def test_dismiss_suspension_restores_active_without_count(api):
    """PRD §3.7: "This is a compensating action that restores licensing without
    charging a reinstatement fee."
    PRD §3.7: "`prior_suspension_count` is *not* incremented."

    The compensating dismissal path returns licensing to ACTIVE while conserving
    prior_suspension_count at its pre-suspension value of 0.

    Design: Difficulty/compensating_invariant/dismiss_suspension_conserves_prior_suspension_count
    """
    ctx = active_licensed_record(full_name="Sam Comp 2", opaque_user_id="exu-13b")
    record = ctx["record"]
    violation = suspend_active_record(record["id"], points=12, occurred_period=0)
    suspension = get_first_suspension(record["id"])
    rec_susp = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec_susp["prior_suspension_count"] == 0
    validate_success(api.dismiss_violation(violation["id"], OFFICER), 200)
    validate_success(api.dismiss_suspension(suspension["id"], OFFICER2), 200)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"
    assert rec["prior_suspension_count"] == 0


# ===========================================================================
# compensating_invariant / dismiss_violation_conserves_point_balance
# ===========================================================================
def test_dismiss_violation_returns_point_balance_to_zero(api):
    """PRD §3.7: "A violation itself is dismissed by an AdjudicationOfficer only
    while it is ACTIVE (otherwise ERR_VIOLATION_NOT_ACTIVE); dismissal moves it
    ACTIVE → DISMISSED and recomputes the record's point_balance so it no longer
    contributes."
    PRD §3.7: "Violations in DISMISSED or EXPIRED status never contribute."

    Posting a 4-point violation raises balance to 4; dismissing it returns the
    balance exactly to 0.

    Design: Difficulty/compensating_invariant/dismiss_violation_conserves_point_balance
    """
    record = create_driver_record(full_name="Tom Pts", date_of_birth="1986-01-01")
    violation = get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "SPEEDING_10_OVER",
             "points": 4, "occurred_period": 0}, OFFICER,
        )
    )
    rec_before = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec_before["point_balance"] == 4
    dismissed = validate_success(api.dismiss_violation(violation["id"], OFFICER), 200)
    assert dismissed["status"] == "DISMISSED"
    rec_after = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec_after["point_balance"] == 0, f"got {rec_after['point_balance']}"


def test_dismiss_violation_marks_dismissed_status(api):
    """PRD §3.7: "dismissal moves it ACTIVE → DISMISSED and recomputes the record's
    point_balance so it no longer contributes."

    The dismissed violation lands in DISMISSED status and stops contributing its
    points — the conserved quantity (point_balance) returns to its pre-action value.

    Design: Difficulty/compensating_invariant/dismiss_violation_conserves_point_balance
    """
    record = create_driver_record(full_name="Tom Pts 2", date_of_birth="1986-01-01")
    violation = get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "SPEEDING_10_OVER",
             "points": 4, "occurred_period": 0}, OFFICER,
        )
    )
    validate_success(api.dismiss_violation(violation["id"], OFFICER), 200)
    fetched = validate_success(api.get_violation(violation["id"], OFFICER), 200)
    assert fetched["status"] == "DISMISSED"
    rec = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec["point_balance"] == 0
