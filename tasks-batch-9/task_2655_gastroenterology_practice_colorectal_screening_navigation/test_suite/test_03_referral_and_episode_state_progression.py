"""Non-linear progressions: the triage information-request cycle whose branch is chosen
by a counter, and the episode whose two status dimensions advance independently."""
from test_helpers import (
    REFERRAL_COORDINATOR,
    abort_exam,
    api_client,
    apply_block_action,
    attest_prep,
    book_slot,
    check_in,
    create_block,
    move_clock,
    open_episode,
    read_block,
    read_booking,
    read_episode,
    record_outreach,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    staff_block,
    start_exam,
    submit_referral,
    triage,
    triage_action_payload,
    validate_error,
)


def _referral_after_two_information_rounds():
    """Drive a cleared referral through both permitted information rounds, the second
    response revising the ASA class upward so the screen no longer clears."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    referral = submit_referral(patient["id"], reason="AVERAGE_RISK_SCREENING",
                              asa_class_reported=2, anticoagulant_reported=False)
    after_begin = triage(referral["id"], "BEGIN_TRIAGE")
    after_first_request = triage(referral["id"], "REQUEST_INFO")
    triage(referral["id"], "RESPOND_INFO", updated_anticoagulant=False)
    after_second_request = triage(referral["id"], "REQUEST_INFO")
    after_second_response = triage(referral["id"], "RESPOND_INFO", updated_asa_class=4)
    return {
        "referral_id": referral["id"],
        "created": referral,
        "after_begin": after_begin,
        "after_first_request": after_first_request,
        "after_second_request": after_second_request,
        "after_second_response": after_second_response,
    }


def test_begin_triage_clears_open_access_and_the_first_request_increments_the_counter():
    """A new referral begins with `status` `SUBMITTED`, `info_request_rounds` at 0, and
    `risk_screen_result` at `PENDING`.

    Applied from `UNDER_TRIAGE` while `info_request_rounds` is strictly below two, it
    moves `UNDER_TRIAGE → INFO_REQUESTED`, increases `info_request_rounds` by 1, and
    copies the supplied `note` into `triage_decision_note` when one is present.

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_auto_declines_on_third_request
    """
    scenario = _referral_after_two_information_rounds()

    assert scenario["created"]["status"] == "SUBMITTED"
    assert scenario["created"]["info_request_rounds"] == 0
    assert scenario["created"]["risk_screen_result"] == "PENDING"
    assert scenario["after_begin"]["status"] == "UNDER_TRIAGE"
    assert scenario["after_begin"]["risk_screen_result"] == "CLEARED_OPEN_ACCESS"
    assert scenario["after_first_request"]["status"] == "INFO_REQUESTED"
    assert scenario["after_first_request"]["info_request_rounds"] == 1
    assert scenario["after_second_request"]["info_request_rounds"] == 2


def test_respond_info_recomputes_the_screen_from_the_revised_asa_class():
    """`RESPOND_INFO` returns the referral from `INFO_REQUESTED → UNDER_TRIAGE`. When
    `updated_asa_class` is supplied it overwrites `asa_class_reported`; when
    `updated_anticoagulant` is supplied it overwrites `anticoagulant_reported`; then the
    risk screen is recomputed from the revised values.

    An ASA class of 4 or 5, a patient on anticoagulants, or a bleeding complaint each
    independently forces a clinic visit.

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_auto_declines_on_third_request
    """
    scenario = _referral_after_two_information_rounds()
    revised = scenario["after_second_response"]

    assert revised["status"] == "UNDER_TRIAGE"
    assert revised["asa_class_reported"] == 4
    assert revised["risk_screen_result"] == "OFFICE_VISIT_REQUIRED"
    assert revised["info_request_rounds"] == 2


def test_third_request_info_auto_declines_and_holds_the_counter_at_two():
    """Applied from `UNDER_TRIAGE` when `info_request_rounds` has already reached two, it
    moves `UNDER_TRIAGE → DECLINED` instead, sets `triage_decision_note` to the literal
    string `AUTO_DECLINED_INFO_EXHAUSTED` while ignoring any supplied `note`, and leaves
    `info_request_rounds` unchanged at two.

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_auto_declines_on_third_request
    """
    scenario = _referral_after_two_information_rounds()
    response = api_client.referral_triage_action(
        scenario["referral_id"],
        triage_action_payload("REQUEST_INFO", note="Third chase attempt"),
        REFERRAL_COORDINATOR,
    )

    assert response.status_code == 200
    declined = response.json()["data"]
    assert declined["status"] == "DECLINED"
    assert declined["triage_decision_note"] == "AUTO_DECLINED_INFO_EXHAUSTED"
    assert declined["info_request_rounds"] == 2


def test_declined_referral_admits_no_acceptance_action():
    """Requesting an action that is not declared from the referral's current state is
    rejected with `ERR_INVALID_REFERRAL_STATE`.

    `ACCEPT_OFFICE_VISIT` moves `UNDER_TRIAGE → ACCEPTED_OFFICE_VISIT` and is always
    permitted from `UNDER_TRIAGE` — it is the deliberate fallback when the open-access
    screen fails.

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_auto_declines_on_third_request
    """
    scenario = _referral_after_two_information_rounds()
    triage(scenario["referral_id"], "REQUEST_INFO")

    response = api_client.referral_triage_action(
        scenario["referral_id"],
        triage_action_payload("ACCEPT_OFFICE_VISIT"),
        REFERRAL_COORDINATOR,
    )
    validate_error(response, "ERR_INVALID_REFERRAL_STATE")

    still_declined = api_client.get_referral(scenario["referral_id"], REFERRAL_COORDINATOR)
    assert still_declined.json()["data"]["status"] == "DECLINED"


def _episode_through_booking_outreach_and_abort():
    """Book a MAC slot, then walk the navigation dimension up to `PREP_CONFIRMED` and
    abort the exam for inadequate preparation."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    after_outreach = record_outreach(episode["id"], "PHONE", True)
    after_attestation = attest_prep(episode["id"], patient["id"], True)
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    aborted = abort_exam(booking["id"], endoscopist["id"], prep_quality_bbps=3,
                         cancellation_reason="INADEQUATE_PREP")
    return {
        "block_id": block["id"],
        "episode_id": episode["id"],
        "patient_id": patient["id"],
        "booking_id": booking["id"],
        "created_episode": episode,
        "after_outreach": after_outreach,
        "after_attestation": after_attestation,
        "aborted": aborted,
    }


def test_the_two_episode_dimensions_advance_on_unrelated_events():
    """The navigation dimension advances purely on preparation-adherence thresholds and
    never reads `clinical_status`; the clinical dimension advances on scheduling and
    pathology events. Neither dimension is derivable from the other.

    The resulting score is then compared against the higher threshold of 5.00: at 5.00
    or above the episode advances `OUTREACH_ACTIVE → PREP_CONFIRMED` or `PREP_AT_RISK →
    PREP_CONFIRMED`; below 5.00 the episode lands in `PREP_AT_RISK`, including the
    `OUTREACH_ACTIVE → PREP_AT_RISK` demotion, and the patient must be worked again.

    Design: Difficulty/non_linear_state_machine/episode_parallel_dimensions_advance_independently
    """
    scenario = _episode_through_booking_outreach_and_abort()

    assert scenario["created_episode"]["navigation_status"] == "NOT_STARTED"
    assert scenario["created_episode"]["clinical_status"] == "OPEN"
    assert scenario["after_outreach"]["navigation_status"] == "OUTREACH_ACTIVE"
    assert scenario["after_outreach"]["prep_adherence_score"] == 3.00
    assert scenario["after_outreach"]["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert scenario["after_attestation"]["navigation_status"] == "PREP_CONFIRMED"
    assert scenario["after_attestation"]["prep_adherence_score"] == 5.50
    assert scenario["after_attestation"]["clinical_status"] == "PROCEDURE_SCHEDULED"


def test_abort_reverts_the_clinical_dimension_and_resets_the_attestation():
    """The episode's clinical dimension reverts `PROCEDURE_SCHEDULED → OPEN` so the patient
    can be rebooked, and when the recorded `prep_quality_bbps` is 5 or below the
    navigation dimension is demoted to `PREP_AT_RISK` and `prep_attestation` is reset to
    `NONE`.

    Crucially, **an abort releases no room minutes**: `booked_minutes` is left as it
    stands, because the room really was occupied.

    Design: Difficulty/non_linear_state_machine/episode_parallel_dimensions_advance_independently
    """
    scenario = _episode_through_booking_outreach_and_abort()
    booking = read_booking(scenario["booking_id"])
    episode = read_episode(scenario["episode_id"])
    block = read_block(scenario["block_id"])

    assert booking["status"] == "ABORTED_INADEQUATE_PREP"
    assert episode["clinical_status"] == "OPEN"
    assert episode["navigation_status"] == "PREP_AT_RISK"
    assert episode["prep_attestation"] == "NONE"
    assert block["capacity_minutes"] == 480
    assert block["booked_minutes"] == 60


def test_navigation_cycles_back_to_outreach_active_without_touching_the_clinical_status():
    """Because a recovering score sends `PREP_AT_RISK → OUTREACH_ACTIVE` again, this pair of
    states genuinely cycles, and the cycle is bounded only by the score threshold and
    never by a round counter.

    An attestation bonus is then added to the raw total: 2.50 when the episode's
    `prep_attestation` is `COMPLETED`, minus 1.00 when it is `NOT_COMPLETED`, and zero
    when it is `NONE`.

    Design: Difficulty/non_linear_state_machine/episode_parallel_dimensions_advance_independently
    """
    scenario = _episode_through_booking_outreach_and_abort()
    recovered = record_outreach(scenario["episode_id"], "SMS", True)

    assert recovered["navigation_status"] == "OUTREACH_ACTIVE"
    assert recovered["prep_adherence_score"] == 5.00
    assert recovered["clinical_status"] == "OPEN"
