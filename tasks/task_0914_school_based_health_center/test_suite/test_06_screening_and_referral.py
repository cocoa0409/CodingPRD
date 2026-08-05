"""Screenings, the referrals they raise, and working the outreach loop."""

from test_helpers import (
    CARE_COORDINATOR,
    REGISTRAR,
    ApiErrorId,
    assert_referral,
    assert_screening,
    assert_instant_ordering,
    get_clearance,
    get_referral,
    log_outreach,
    notifications_for_student,
    record_screening,
    screening_payload,
    setup_active_clearance,
    setup_referral_open,
    setup_referral_outreach_in_progress,
    setup_visit_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_referring_screening_creates_the_open_referral_and_sets_the_back_link(api):
    """PRD §3.8: "A referring screening moves `RECORDED → REFERRED` and fires a
    four-link cascade. **Link one** writes the `REFER` outcome and the `ABNORMAL`
    band. **Link two** auto-creates a referral in `OPEN` whose
    `source_screening_id` is this screening, whose `source_visit_id` is the
    encounter, whose `requested_by_user_id` is the acting clinician's `X-User-ID`,
    and whose `specialty` comes from the instrument: `VISION` refers to
    `OPHTHALMOLOGY`, `HEARING` to `AUDIOLOGY`, `DENTAL` to `DENTISTRY`, `BMI` to
    `NUTRITION` and `BEHAVIORAL` to `BEHAVIORAL_HEALTH`; the screening's
    `generated_referral_id` is set to that new referral, and the referral itself
    raises a parent notification of event type `REFERRAL_CREATED`."
    PRD §3.8: "A `VISION` result refers at 40 or more — the boundary is inclusive."

    Design: Difficulty/transitive_cascade/screening_refer_drives_four_link_referral_and_clearance_cascade
    """
    ctx = setup_active_clearance(exemption="RELIGIOUS")

    resp = api.create_screening(
        ctx["visit"]["id"], screening_payload("VISION", 50), ctx["clinician_headers"]
    )
    screening = validate_success(resp, 201)

    assert_screening(screening)
    assert screening["outcome"] == "REFER"
    assert screening["band_label"] == "ABNORMAL"
    assert screening["status"] == "REFERRED"
    assert screening["generated_referral_id"] is not None

    referral = get_referral(screening["generated_referral_id"])
    assert_referral(referral)
    assert referral["status"] == "OPEN"
    assert referral["specialty"] == "OPHTHALMOLOGY"
    assert referral["source_screening_id"] == screening["id"]
    assert referral["source_visit_id"] == ctx["visit"]["id"]
    assert referral["requested_by_user_id"] == ctx["clinician"]["id"]


def test_referring_screening_voids_the_clearance_and_orders_both_notifications(api):
    """PRD §3.8: "**Link three** fires because a referral with a non-null
    `source_screening_id` now exists for this student: the student's sports-physical
    clearance whose status is `ACTIVE` or `PENDING_REEVALUATION` moves to `VOIDED`
    with a `void_reason` of `SCREENING_REFERRAL_RAISED`. **Link four** creates the
    `CLEARANCE_VOIDED` parent notification for that void. The two notifications are
    ordered: `REFERRAL_CREATED` is created **before** `CLEARANCE_VOIDED`."

    Design: Difficulty/transitive_cascade/screening_refer_drives_four_link_referral_and_clearance_cascade
    """
    ctx = setup_active_clearance(exemption="RELIGIOUS")
    assert ctx["clearance"]["status"] == "ACTIVE"

    record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "VISION", 50)

    clearance = get_clearance(ctx["clearance"]["id"])
    assert clearance["status"] == "VOIDED"
    assert clearance["void_reason"] == "SCREENING_REFERRAL_RAISED"

    student = validate_success(api.get_student(ctx["student"]["id"], REGISTRAR))
    assert student["immunization_compliance_status"] == "COMPLIANT", (
        "The screening cascade never touches the immunization posture"
    )

    created = notifications_for_student(ctx["student"]["id"], event_type="REFERRAL_CREATED")
    voided = notifications_for_student(ctx["student"]["id"], event_type="CLEARANCE_VOIDED")
    assert len(created) == 1, f"Expected one REFERRAL_CREATED notification, got {len(created)}"
    assert len(voided) == 1, f"Expected one CLEARANCE_VOIDED notification, got {len(voided)}"
    assert created[0]["status"] == "QUEUED"
    assert voided[0]["status"] == "QUEUED"
    assert_instant_ordering(
        created[0]["created_at"],
        voided[0]["created_at"],
        "REFERRAL_CREATED before CLEARANCE_VOIDED",
    )


def test_third_no_answer_takes_the_referral_out_of_the_outreach_loop(api):
    """PRD §3.8: "A `NO_ANSWER` from `OPEN` moves the referral `OPEN →
    OUTREACH_IN_PROGRESS`. A further `NO_ANSWER` while the counter is still
    strictly below 2 keeps it looping `OUTREACH_IN_PROGRESS →
    OUTREACH_IN_PROGRESS`. The `NO_ANSWER` logged when the counter stands at
    exactly 2 is the third attempt: it takes the counter to 3 and moves the
    referral `OUTREACH_IN_PROGRESS → LOST_TO_FOLLOW_UP`, which is terminal."

    Design: Difficulty/non_linear_state_machine/referral_outreach_capped_self_loop_ends_in_lost_to_follow_up
    """
    ctx = setup_referral_outreach_in_progress(attempts=2)
    assert ctx["referral"]["status"] == "OUTREACH_IN_PROGRESS"
    assert ctx["referral"]["outreach_attempt_count"] == 2

    third = validate_success(
        api.log_outreach_attempt(
            ctx["referral"]["id"], {"outcome": "NO_ANSWER"}, CARE_COORDINATOR
        )
    )

    assert_referral(third)
    assert third["status"] == "LOST_TO_FOLLOW_UP"
    assert third["outreach_attempt_count"] == 3


def test_fourth_outreach_attempt_reports_the_cap_rather_than_a_state_error(api):
    """PRD §3.8: "Once the counter has reached 3, any further attempt is refused
    with `ERR_OUTREACH_LIMIT_EXCEEDED` — and per §2.6 that is the answer even on a
    referral already sitting in `LOST_TO_FOLLOW_UP`, where a naive reading would
    have produced a state error instead."
    PRD §2.6: "A fourth outreach attempt on a referral already lost to follow-up
    produces `ERR_OUTREACH_LIMIT_EXCEEDED`, not `ERR_INVALID_STATE` (rung 16
    precedes rung 17)"

    Design: Difficulty/non_linear_state_machine/referral_outreach_capped_self_loop_ends_in_lost_to_follow_up
    """
    ctx = setup_referral_outreach_in_progress(attempts=2)
    log_outreach(ctx["referral"]["id"], "NO_ANSWER")

    resp = api.log_outreach_attempt(
        ctx["referral"]["id"], {"outcome": "NO_ANSWER"}, CARE_COORDINATOR
    )

    validate_error(resp, ApiErrorId.ERR_OUTREACH_LIMIT_EXCEEDED.value, 409)

    referral = get_referral(ctx["referral"]["id"])
    assert referral["status"] == "LOST_TO_FOLLOW_UP"
    assert referral["outreach_attempt_count"] == 3, (
        "A rejected attempt must not advance the outreach counter"
    )


def test_hearing_and_bmi_band_edges_decide_pass_versus_refer(api):
    """PRD §3.8: "A `HEARING` result refers only when it is strictly greater than
    25, so exactly 25 passes. A `DENTAL` result refers at 1 or more, inclusive, so
    a single untreated carie refers. A `BMI` result refers when it is strictly below
    5 **or** at or above 95 — the low boundary excludes 5 itself while the high
    boundary includes 95."
    PRD §3.8: "A passing screening moves `RECORDED → CLOSED_PASS`, leaves
    `generated_referral_id` null and cascades to nothing."

    Design: Corner/calculations/screening_band_boundaries_for_hearing_and_bmi_instruments
    """
    ctx = setup_visit_in_progress()

    hearing_25 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "HEARING", 25)
    hearing_26 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "HEARING", 26)
    bmi_5 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "BMI", 5)
    bmi_4 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "BMI", 4)
    bmi_94 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "BMI", 94)
    bmi_95 = record_screening(ctx["visit"]["id"], ctx["clinician"]["id"], "BMI", 95)

    assert hearing_25["outcome"] == "PASS"
    assert hearing_25["band_label"] == "NORMAL"
    assert hearing_25["status"] == "CLOSED_PASS"
    assert hearing_25["generated_referral_id"] is None

    assert hearing_26["outcome"] == "REFER"
    assert hearing_26["band_label"] == "ABNORMAL"
    assert hearing_26["status"] == "REFERRED"

    assert bmi_5["outcome"] == "PASS"
    assert bmi_4["outcome"] == "REFER"
    assert bmi_94["outcome"] == "PASS"
    assert bmi_95["outcome"] == "REFER"

    assert get_referral(hearing_26["generated_referral_id"])["specialty"] == "AUDIOLOGY"
    assert get_referral(bmi_95["generated_referral_id"])["specialty"] == "NUTRITION"

    _rows, meta = validate_paginated(
        api.list_referrals(CARE_COORDINATOR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 3, (
        f"Three referring screenings must raise three referrals, got {meta['total_count']}"
    )


def test_segregation_of_duties_outranks_the_state_check_on_referral_close(api):
    """PRD §2.6: "And a referral closure attempted by the original requester on a
    referral that is in the wrong state still produces `ERR_SEGREGATION_OF_DUTIES`
    (rung 13 precedes rung 17)."
    PRD §3.8: "Only from `REPORT_RECEIVED` may the loop be closed, and closure is
    where segregation of duties bites: the closer's `X-User-ID` must differ from the
    referral's `requested_by_user_id`, otherwise the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_outranks_the_state_check_on_referral_close
    """
    ctx = setup_referral_open(guardians=[], consents=())
    referral_id = ctx["referral"]["id"]

    by_requester = api.close_referral(
        referral_id, {"closure_note": "Closing my own referral"}, ctx["clinician_headers"]
    )
    validate_error(by_requester, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    by_coordinator = api.close_referral(
        referral_id, {"closure_note": "Closing too early"}, CARE_COORDINATOR
    )
    validate_error(by_coordinator, ApiErrorId.ERR_INVALID_STATE.value, 409)

    referral = get_referral(referral_id)
    assert referral["status"] == "OPEN"
    assert referral["closed_by_user_id"] is None
    assert referral["requested_by_user_id"] == ctx["clinician"]["id"]
