"""Treatment plans, the follow-up cadence and the capped referral cycle."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_referral,
    assert_same_date,
    assert_same_instant,
    assert_treatment_plan,
    get_success_data,
    make_program_admin_headers,
    set_clock,
    setup_active_plan_and_referral,
    setup_screened_and_examined,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers()

URGENT_SCREENING = {
    "cavitated_lesion_count": 2,
    "pain_reported": True,
    "abscess_or_swelling": False,
    "untreated_decay_present": True,
}


def test_urgent_plan_cadence_is_seven_days_and_a_contact_restarts_it(api):
    """PRD §3.7: "At creation the plan copies the encounter's `triage_band` into its own
    `urgency_band`, which is what drives both the referral deadline and the follow-up cadence
    from then on."
    PRD §3.7: "Activation stamps `activated_on` with the logical clock date and computes the
    first `follow_up_due_date`. The cadence is keyed on the band: 7 calendar days for an
    `URGENT` plan, 30 for `EARLY_CARE_NEEDED`, and 180 for `NO_OBVIOUS_PROBLEM`."
    PRD §3.7: "The contact stamps `last_contact_at` with the logical clock instant, raises
    `contact_attempt_count` by one, recomputes `follow_up_due_date` from that contact date
    using the same band cadence, and sets `follow_up_status` to `CONTACTED`."

    Design: Corner/calculations/follow_up_due_date_for_an_urgent_plan_is_seven_days_after_activation
    """
    stack = setup_screened_and_examined(clock="2026-05-11T09:00:00Z", screening=URGENT_SCREENING)
    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["triage_band"] == "URGENT"

    plan = validate_success(
        api.create_treatment_plan(
            {
                "encounter_id": stack.enc_id,
                "patient_id": stack.patient_id,
                "authoring_staff_id": stack.dentist_id,
                "planned_procedure_codes": ["D1206"],
            },
            stack.dentist_headers,
        ),
        201,
    )
    assert_treatment_plan(plan)
    assert plan["urgency_band"] == "URGENT"

    activated = validate_success(api.activate_treatment_plan(plan["id"], stack.dentist_headers))
    assert_same_date(activated["activated_on"], "2026-05-11", "activated_on")
    assert_same_date(activated["follow_up_due_date"], "2026-05-18", "follow_up_due_date")
    assert activated["follow_up_status"] == "NOT_DUE"

    set_clock("2026-05-13T09:00:00Z")
    contacted = validate_success(
        api.record_follow_up_contact(
            plan["id"], {"contact_note": "Left voicemail with guardian"}, stack.coord_headers
        )
    )
    assert_same_instant(contacted["last_contact_at"], "2026-05-13T09:00:00Z", "last_contact_at")
    assert contacted["contact_attempt_count"] == 1
    assert_same_date(contacted["follow_up_due_date"], "2026-05-20", "follow_up_due_date")
    assert contacted["follow_up_status"] == "CONTACTED"
    assert contacted["plan_status"] == "ACTIVE"


def _sent_referral_fixture():
    """An EARLY_CARE_NEEDED school plan with one referral already sent on 2026-05-11T14:00Z."""
    stack = setup_active_plan_and_referral(clock="2026-05-11T14:00:00Z")
    stack.first_send = get_success_data(
        api_client.send_referral(stack.ref_id, {}, stack.dentist_headers)
    )
    return stack


def test_no_response_and_resend_cycle_returns_the_referral_to_sent(api):
    """PRD §3.7: "The `NO_RESPONSE` entry deliberately carries **no timing precondition at
    all**: the dental home simply did not answer, and the clinic may record that at any
    moment."
    PRD §3.7: "Both re-sends move the referral back to `SENT`, raise `attempt_count`, restamp
    `last_sent_at` and `next_eligible_send_at`, and leave `due_at` untouched."

    Design: Difficulty/non_linear_state_machine/referral_capped_cycle_no_response_back_to_sent_preserves_first_send_sla
    """
    stack = _sent_referral_fixture()
    assert stack.first_send["status"] == "SENT"
    assert stack.first_send["attempt_count"] == 1

    set_clock("2026-06-01T14:00:00Z")
    no_response = validate_success(
        api.record_referral_response(stack.ref_id, {"outcome": "NO_RESPONSE"}, stack.dentist_headers)
    )
    assert no_response["status"] == "NO_RESPONSE"

    resent = validate_success(api.send_referral(stack.ref_id, {}, stack.dentist_headers))
    assert_referral(resent)
    assert resent["status"] == "SENT"
    assert resent["attempt_count"] == 2
    assert resent["abandoned_at"] is None
    assert validate_success(api.get_treatment_plan(stack.plan_id, ADMIN))["plan_status"] == "ACTIVE"


def test_the_first_send_deadline_survives_the_resend_untouched(api):
    """PRD §3.7: "The service-level deadline `due_at` is computed on the **first** send only
    and is never moved by a re-send; the clock on the dental home runs from the moment the
    case first left the clinic, not from the last time somebody chased it."
    PRD §3.7: "For a `SCHOOL` site the deadline is measured in **business days** advanced from
    the first-send instant — stepping forward one calendar day at a time, counting only Monday
    through Friday, preserving the time of day and applying no holiday calendar: 3 business
    days for an `URGENT` plan, 15 for `EARLY_CARE_NEEDED` and 45 for `NO_OBVIOUS_PROBLEM`."
    PRD §3.7: "Every send raises `attempt_count` by one, stamps `last_sent_at` with the
    logical clock instant, and recomputes `next_eligible_send_at` as that instant plus 21
    days."

    Design: Difficulty/non_linear_state_machine/referral_capped_cycle_no_response_back_to_sent_preserves_first_send_sla
    """
    stack = _sent_referral_fixture()
    assert_same_instant(stack.first_send["due_at"], "2026-06-01T14:00:00Z", "due_at at first send")

    set_clock("2026-06-01T14:00:00Z")
    validate_success(
        api.record_referral_response(stack.ref_id, {"outcome": "NO_RESPONSE"}, stack.dentist_headers)
    )
    resent = validate_success(api.send_referral(stack.ref_id, {}, stack.dentist_headers))

    assert_same_instant(resent["due_at"], "2026-06-01T14:00:00Z", "due_at after the re-send")
    assert_same_instant(resent["last_sent_at"], "2026-06-01T14:00:00Z", "last_sent_at")
    assert_same_instant(
        resent["next_eligible_send_at"], "2026-06-22T14:00:00Z", "next_eligible_send_at"
    )


def _capped_referral_fixture():
    """A referral at attempt_count 3 in NO_RESPONSE, with the clock still short of the re-send date."""
    stack = setup_active_plan_and_referral(clock="2026-05-11T14:00:00Z")
    get_success_data(api_client.send_referral(stack.ref_id, {}, stack.dentist_headers))
    get_success_data(
        api_client.record_referral_response(stack.ref_id, {"outcome": "NO_RESPONSE"},
                                            stack.dentist_headers)
    )
    set_clock("2026-06-01T14:00:00Z")
    get_success_data(api_client.send_referral(stack.ref_id, {}, stack.dentist_headers))
    get_success_data(
        api_client.record_referral_response(stack.ref_id, {"outcome": "NO_RESPONSE"},
                                            stack.dentist_headers)
    )
    set_clock("2026-06-22T14:00:00Z")
    get_success_data(api_client.send_referral(stack.ref_id, {}, stack.dentist_headers))
    get_success_data(
        api_client.record_referral_response(stack.ref_id, {"outcome": "NO_RESPONSE"},
                                            stack.dentist_headers)
    )
    return stack


def test_a_fourth_send_made_too_early_is_not_due_and_suppresses_the_abandon_write(api):
    """PRD §2.6: "A send from status `NO_RESPONSE` requires the logical clock to have reached
    the referral's `next_eligible_send_at`; the instant itself qualifies."
    PRD §2.6: "Because it sits above the cap rung, an over-cap attempt made too early reports
    `ERR_REFERRAL_NOT_DUE` and does **not** abandon the referral."

    Design: Difficulty/priority_pair_validation_conflict/referral_not_due_beats_attempt_cap_and_suppresses_the_abandon_write
    """
    stack = _capped_referral_fixture()
    before = validate_success(api.get_referral(stack.ref_id, ADMIN))
    assert before["attempt_count"] == 3
    assert before["status"] == "NO_RESPONSE"
    assert_same_instant(
        before["next_eligible_send_at"], "2026-07-13T14:00:00Z", "next_eligible_send_at"
    )

    resp = api.send_referral(stack.ref_id, {}, stack.dentist_headers)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_DUE.value, 422)

    after = validate_success(api.get_referral(stack.ref_id, ADMIN))
    assert after["status"] == "NO_RESPONSE", "The abandon write at the cap rung must not have run"
    assert after["abandoned_at"] is None
    assert after["abandon_reason"] is None
    assert after["attempt_count"] == 3
    assert after["version"] == before["version"], "A rung-33 refusal writes nothing"


def test_the_over_cap_send_abandons_first_and_then_refuses(api):
    """PRD §2.8: "When a send is requested against a referral in status `NO_RESPONSE` or
    `DECLINED` whose `attempt_count` has already reached 3, the referral is first written to
    `ABANDONED` with `abandoned_at` and `case_management_opened_at` both stamped with the
    logical clock instant, `abandon_reason` set to `ATTEMPT_CAP_REACHED`, and `attempt_count`
    left frozen at 3 rather than incremented; `Referral.version` increments by 1. The request
    is **then** refused with `ERR_REFERRAL_CAP_REACHED`."

    Design: Difficulty/priority_pair_validation_conflict/referral_not_due_beats_attempt_cap_and_suppresses_the_abandon_write
    """
    stack = _capped_referral_fixture()
    validate_error(
        api.send_referral(stack.ref_id, {}, stack.dentist_headers),
        ApiErrorId.ERR_REFERRAL_NOT_DUE.value, 422,
    )

    set_clock("2026-07-13T14:00:00Z")
    resp = api.send_referral(stack.ref_id, {}, stack.dentist_headers)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_CAP_REACHED.value, 409)

    referral = validate_success(api.get_referral(stack.ref_id, ADMIN))
    assert referral["status"] == "ABANDONED"
    assert referral["abandon_reason"] == "ATTEMPT_CAP_REACHED"
    assert_same_instant(referral["abandoned_at"], "2026-07-13T14:00:00Z", "abandoned_at")
    assert_same_instant(
        referral["case_management_opened_at"], "2026-07-13T14:00:00Z", "case_management_opened_at"
    )
    assert referral["attempt_count"] == 3, "attempt_count stays frozen at the cap"
