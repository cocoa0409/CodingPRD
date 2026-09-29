"""Reopen window, practice suspension, protocol eligibility, capacity and holds."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_version_is,
    assert_whole_minutes,
)


@pytest.fixture
def closed_call_with_its_billing_posted(world):
    """An ED_NOW call closed at 14:30 on twelve handled minutes."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call, _, _ = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    closed = world.complete_call(call["id"], "nurse_a", handle_minutes=12)
    return call, closed


class TestReopenWindowFarEdgeIsInclusive:
    def test_the_closure_posts_the_rounded_up_minutes_and_fee(
        self, world, closed_call_with_its_billing_posted
    ):
        """PRD §3.9: "First, `billable_minutes` is `handle_minutes` rounded **up** to
        the next whole multiple of five: thirteen minutes bills as fifteen, eighteen as
        twenty, twenty-eight as thirty, and exactly twenty bills as twenty with no
        inflation to twenty-five."

        Design: Corner/validations/reopen_after_seventy_two_hours_is_rejected
        """
        _, closed = closed_call_with_its_billing_posted

        assert closed["status"] == "CLOSED"
        assert_instant(closed["closed_at"], "2026-08-03T14:30:00Z", "closed_at")
        assert_whole_minutes(closed["billable_minutes"], 15, "billable_minutes")
        assert_cents(closed["advice_fee_cents"], 63, "advice_fee_cents")

    def test_exactly_seventy_two_hours_later_is_already_expired(
        self, world, closed_call_with_its_billing_posted
    ):
        """PRD §3.9: "It is available only while the logical clock is strictly earlier
        than seventy-two hours after the call's `closed_at`; at or beyond that instant
        the request is refused with `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/validations/reopen_after_seventy_two_hours_is_rejected
        """
        call, _ = closed_call_with_its_billing_posted
        world.set_clock("2026-08-06T14:30:00Z")

        response = world.api.reopen_call(
            call["id"],
            f.reopen_payload(
                reopen_reason="Caller phoned back exactly seventy-two hours later."
            ),
            world.charge_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED, 409)
        after = world.call(call["id"])
        assert after["status"] == "CLOSED"
        assert after["reopen_count"] == 0

    def test_one_minute_earlier_still_reopens_and_reverses_the_billing(
        self, world, closed_call_with_its_billing_posted
    ):
        """PRD §3.9: "The call's own `handle_minutes` returns to absent,
        `billable_minutes` to 0 and `advice_fee_cents` to 0; `reopen_count` increases by
        one; the assigned nurse's `active_call_load` increases by one because the call
        is live again".

        Design: Corner/validations/reopen_after_seventy_two_hours_is_rejected
        """
        call, _ = closed_call_with_its_billing_posted
        world.set_clock("2026-08-06T14:30:00Z")
        world.api.reopen_call(
            call["id"], f.reopen_payload(), world.charge_headers("nurse_a")
        )
        world.set_clock("2026-08-06T14:29:00Z")

        reopened = world.reopen_call(
            call["id"],
            "nurse_a",
            reopen_reason="Caller phoned back one minute inside the reopen window.",
        )

        assert reopened["status"] == "DISPOSITIONED"
        assert reopened["reopen_count"] == 1
        assert_whole_minutes(reopened["billable_minutes"], 0, "billable_minutes")
        assert_cents(reopened["advice_fee_cents"], 0, "advice_fee_cents")
        assert world.call(call["id"])["handle_minutes"] is None
        assert world.nurse("nurse_a")["active_call_load"] == 1


@pytest.fixture
def suspended_practice_with_one_patient(world):
    """A practice with one registered patient, then suspended."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice()
    world.create_patient("patient")
    suspended = world.suspend_practice()
    return suspended


class TestSuspensionClosesThreeWritePaths:
    def test_intake_patient_registration_and_coverage_drafting_all_close(
        self, world, suspended_practice_with_one_patient
    ):
        """PRD §3.1: "while a practice is `SUSPENDED`, opening a call for it, adding a
        patient to its panel and drafting a coverage window for it are all rejected with
        `ERR_PRACTICE_SUSPENDED`."

        Design: Corner/validations/suspending_a_practice_blocks_new_intake_and_new_patients
        """
        assert suspended_practice_with_one_patient["status"] == "SUSPENDED"
        pid = world.practice_id

        call_response = world.api.create_triage_call(
            f.triage_call_payload(pid, reason_text="sore throat"), world.intake
        )
        patient_response = world.api.create_patient(
            pid,
            f.patient_payload(
                full_name="Milo Reyes",
                dob="2015-04-02",
                sex="MALE",
                phone="+14155550101",
                mrn="MRN-0002",
            ),
            world.intake,
        )
        window_response = world.api.create_coverage_window(
            f.coverage_window_payload(
                pid,
                start_utc="2026-08-10T02:00:00Z",
                end_utc="2026-08-10T13:00:00Z",
                coverage_kind="NIGHTS",
            ),
            world.liaison_headers(pid),
        )

        validate_error(call_response, ApiErrorId.ERR_PRACTICE_SUSPENDED, 409)
        validate_error(patient_response, ApiErrorId.ERR_PRACTICE_SUSPENDED, 409)
        validate_error(window_response, ApiErrorId.ERR_PRACTICE_SUSPENDED, 409)

    def test_nothing_was_written_while_the_practice_was_suspended(
        self, world, suspended_practice_with_one_patient
    ):
        """PRD §3.1: "Reads of a suspended practice, including its counters and
        ledgers, continue to work."

        Design: Corner/validations/suspending_a_practice_blocks_new_intake_and_new_patients
        """
        pid = world.practice_id
        world.api.create_patient(
            pid,
            f.patient_payload(
                full_name="Milo Reyes",
                dob="2015-04-02",
                sex="MALE",
                phone="+14155550101",
                mrn="MRN-0002",
            ),
            world.intake,
        )
        world.api.create_coverage_window(
            f.coverage_window_payload(
                pid,
                start_utc="2026-08-10T02:00:00Z",
                end_utc="2026-08-10T13:00:00Z",
                coverage_kind="NIGHTS",
            ),
            world.liaison_headers(pid),
        )

        _, patient_meta = validate_paginated(
            world.api.list_patients(pid, world.intake, None)
        )
        _, window_meta = validate_paginated(
            world.api.list_practice_coverage_windows(pid, world.admin, None)
        )

        assert patient_meta["total_count"] == 1
        assert window_meta["total_count"] == 0

    def test_reinstating_the_practice_reopens_intake(
        self, world, suspended_practice_with_one_patient
    ):
        """PRD §3.1: "A practice's contract state is a two-value enumeration, `ACTIVE`
        or `SUSPENDED`, and operations can flip it either way by supplying a new
        `status`; the flip bumps the practice's `version`."

        Design: Corner/validations/suspending_a_practice_blocks_new_intake_and_new_patients
        """
        pid = world.practice_id
        world.api.create_triage_call(
            f.triage_call_payload(pid, reason_text="sore throat"), world.intake
        )

        reinstated = get_success_data(
            world.api.patch_practice_status(
                pid, f.practice_status_payload("ACTIVE"), world.admin
            )
        )
        call = world.open_call(pid, reason_text="sore throat")

        assert reinstated["status"] == "ACTIVE"
        assert_version_is(reinstated, 3, "one suspend and one reinstate")
        assert call["status"] == "INTAKE"
        assert call["practice_id"] == pid


@pytest.fixture
def assigned_call_with_three_protocols(world):
    """An ASSIGNED adult call and a retired, a paediatric and an adult protocol."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    retired = world.create_protocol(
        "retired", code="SORE_THROAT", title="Sore Throat", base_severity=20
    )
    world.retire_protocol(retired["id"])
    world.create_protocol(
        "peds",
        code="PEDS_FEVER",
        title="Fever In Children Under Twelve",
        base_severity=40,
        min_age_years=0,
        max_age_years=12,
        infant_modifier_points=18,
    )
    call = world.call_through_assignment("nurse_a", reason_text="chest discomfort")
    return call


class TestProtocolEligibilityIsScreenedOnTwoAxes:
    def test_a_retired_protocol_is_refused_even_for_an_in_band_caller(
        self, world, assigned_call_with_three_protocols
    ):
        """PRD §3.1: "Retirement is forward-only in effect: assessments already scored
        against the protocol keep their scores and their dispositions untouched, but a
        new assessment naming a retired protocol is rejected with
        `ERR_PROTOCOL_INACTIVE`."

        Design: Corner/validations/retired_and_age_ineligible_protocols_are_both_rejected_at_assessment
        """
        call = assigned_call_with_three_protocols
        assert world.protocols["retired"]["status"] == "ACTIVE", "before retirement"
        assert call["status"] == "ASSIGNED"

        response = world.api.create_assessment(
            call["id"],
            f.assessment_payload(world.protocols["retired"]["id"], red_flag_count=0),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_PROTOCOL_INACTIVE, 409)

    def test_a_paediatric_protocol_is_refused_for_a_thirty_six_year_old(
        self, world, assigned_call_with_three_protocols
    ):
        """PRD §3.5: "Whichever mode was chosen, the age that resulted must fall inside
        the protocol's eligibility band, at or above `min_age_years` and at or below
        `max_age_years`; an age outside that band is refused with
        `ERR_PROTOCOL_AGE_INELIGIBLE`."

        Design: Corner/validations/retired_and_age_ineligible_protocols_are_both_rejected_at_assessment
        """
        call = assigned_call_with_three_protocols

        response = world.api.create_assessment(
            call["id"],
            f.assessment_payload(world.protocols["peds"]["id"], red_flag_count=0),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_PROTOCOL_AGE_INELIGIBLE, 422)
        assert world.call(call["id"])["status"] == "ASSIGNED", (
            "the call stays ASSIGNED through both refusals"
        )

    def test_only_the_eligible_protocol_moves_the_call_to_assessing(
        self, world, assigned_call_with_three_protocols
    ):
        """PRD §3.5: "The protocol must exist and its `status` must be `ACTIVE`, or the
        request is refused with `ERR_PROTOCOL_NOT_FOUND` or `ERR_PROTOCOL_INACTIVE`
        respectively."

        Design: Corner/validations/retired_and_age_ineligible_protocols_are_both_rejected_at_assessment
        """
        call = assigned_call_with_three_protocols
        for key in ("retired", "peds"):
            world.api.create_assessment(
                call["id"],
                f.assessment_payload(world.protocols[key]["id"], red_flag_count=0),
                world.nurse_headers("nurse_a"),
            )

        assessment = world.create_assessment(
            call["id"], "nurse_a", "protocol", red_flag_count=0
        )

        assert assessment["protocol_id"] == world.protocols["protocol"]["id"]
        assert assessment["age_years_used"] == 36
        assert assessment["acuity_score"] == 62
        _, meta = validate_paginated(
            world.api.list_assessments(world.admin, {"call_id": call["id"]})
        )
        assert meta["total_count"] == 1
        assert world.call(call["id"])["status"] == "ASSESSING"


@pytest.fixture
def a_capped_preferred_nurse_and_a_second_call(world):
    """nurse_a caps at one concurrent call and already holds it; nurse_c is free."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice()
    world.create_nurse(
        "nurse_a",
        full_name="Nora Vance",
        seniority_level=3,
        max_concurrent_calls=1,
        high_risk_cap=2,
    )
    world.add_license(
        "nurse_a", state_code="CA", license_number="CA-11111", expires_on="2027-01-31"
    )
    world.add_shift(
        "nurse_a", start_utc="2026-08-03T12:00:00Z", end_utc="2026-08-03T20:00:00Z"
    )
    world.create_nurse(
        "nurse_c",
        full_name="Cira Lund",
        seniority_level=2,
        max_concurrent_calls=2,
        high_risk_cap=2,
    )
    world.add_license(
        "nurse_c", state_code="CA", license_number="CA-33333", expires_on="2027-01-31"
    )
    world.add_shift(
        "nurse_c", start_utc="2026-08-03T12:00:00Z", end_utc="2026-08-03T20:00:00Z"
    )
    world.create_protocol("protocol")
    world.create_patient("patient")
    first = world.call_through_assignment(
        "nurse_a", reason_text="first call about chest discomfort"
    )
    second = world.call_through_consent(
        reason_text="second call about chest discomfort"
    )
    return first, second


class TestPreferredNurseAtConcurrencyCap:
    def test_naming_the_capped_nurse_is_refused_without_deferring_anything(
        self, world, a_capped_preferred_nurse_and_a_second_call
    ):
        """PRD §3.4: "an optional `preferred_nurse_id` may be supplied, and that nurse
        must independently satisfy every eligibility clause below as well as having
        `active_call_load` strictly below `max_concurrent_calls`; a preferred nurse who
        is already at their concurrency cap is refused with `ERR_NURSE_AT_CAPACITY`".

        Design: Corner/validations/preferred_nurse_already_at_max_concurrent_calls_is_rejected
        """
        first, second = a_capped_preferred_nurse_and_a_second_call
        assert first["assigned_nurse_id"] == world.nurse_id("nurse_a")

        response = world.api.assign_nurse(
            second["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_NURSE_AT_CAPACITY, 409)
        after = world.call(second["id"])
        assert after["status"] == "CONSENTED"
        assert after["assigned_nurse_id"] is None
        assert after["deferred_assignment_count"] == 0, (
            "a capacity refusal is not a deferral"
        )

    def test_letting_the_server_choose_lands_on_the_other_nurse(
        self, world, a_capped_preferred_nurse_and_a_second_call
    ):
        """PRD §3.4: "Routing is a server-side selection, not a client choice: the
        request carries no nurse at all in the ordinary case, and the server picks."

        Design: Corner/validations/preferred_nurse_already_at_max_concurrent_calls_is_rejected
        """
        _, second = a_capped_preferred_nurse_and_a_second_call
        world.api.assign_nurse(
            second["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.intake,
        )

        assigned = world.assign_nurse(second["id"])

        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_nurse_id"] == world.nurse_id("nurse_c")
        assert assigned["deferred_assignment_count"] == 0
        assert_instant(assigned["assigned_at"], "2026-08-03T14:30:00Z", "assigned_at")
        assert world.nurse("nurse_a")["active_call_load"] == 1
        assert world.nurse("nurse_c")["active_call_load"] == 1


@pytest.fixture
def ed_now_advice_with_its_callback_closed_out(world):
    """An ED_NOW disposition whose HIGH_RISK callback nurse_c has verified."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        practice={
            "variance_review_threshold": 1,
            "audit_period_start_utc": "2026-08-01T00:00:00Z",
        },
        protocol={"base_severity": 62},
    )
    _, _, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    task = world.callback_for(disposition["id"])
    world.record_attempt(task["id"], "nurse_a", "REACHED")
    world.verify_callback(
        task["id"],
        "nurse_c",
        "IMPROVED",
        True,
        verifier_attestation=(
            "Independent nurse confirmed the caller attended the emergency department "
            "as advised."
        ),
    )
    return disposition


class TestComplianceHoldBlocksCoverageActivation:
    def test_the_undertriage_record_puts_the_practice_under_review(
        self, world, ed_now_advice_with_its_callback_closed_out
    ):
        """PRD §3.10: "An `UNDERTRIAGE` record advances it
        `OUTCOME_RECORDED → VARIANCE_ESCALATED` and sets off the same four-hop cascade
        the worsened callback does: the practice's `open_variance_count` increases by
        one; because that count reached the practice's `variance_review_threshold`,
        `compliance_posture` becomes `UNDER_REVIEW`".

        Design: Corner/validations/a_practice_under_compliance_review_cannot_activate_a_new_coverage_window
        """
        disposition = ed_now_advice_with_its_callback_closed_out

        record = world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T20:00:00Z",
        )
        # PRD §3.10: the readout's input set is the records created "strictly
        # before the logical clock", so the clock must move past the filing
        # instant for this record to be counted.
        world.set_clock("2026-08-03T21:00:00Z")
        summary = world.compliance_summary()

        assert record["variance_class"] == "UNDERTRIAGE"
        assert record["variance_severity_points"] == 7
        assert summary["compliance_posture"] == "UNDER_REVIEW"
        assert summary["open_variance_count"] == 1
        assert summary["undertriage_count"] == 1
        assert (
            world.disposition(disposition["id"])["audit_status"]
            == "VARIANCE_ESCALATED"
        )

    def test_a_window_drafted_after_the_hold_cannot_be_activated(
        self, world, ed_now_advice_with_its_callback_closed_out
    ):
        """PRD §3.2: "If the window is a genuine `DRAFT` but its practice's
        `compliance_posture` is `UNDER_REVIEW`, the answer is
        `ERR_PRACTICE_COMPLIANCE_HOLD`, because a practice under compliance review may
        not extend its coverage footprint."

        Design: Corner/validations/a_practice_under_compliance_review_cannot_activate_a_new_coverage_window
        """
        disposition = ed_now_advice_with_its_callback_closed_out
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T20:00:00Z",
        )

        window = world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-08-10T02:00:00Z",
            end_utc="2026-08-10T13:00:00Z",
            coverage_kind="NIGHTS",
        )
        assert window["status"] == "DRAFT"

        response = world.api.activate_coverage_window(
            window["id"], {}, world.liaison_headers()
        )

        validate_error(response, ApiErrorId.ERR_PRACTICE_COMPLIANCE_HOLD, 409)

    def test_the_refused_activation_leaves_the_window_a_clean_draft(
        self, world, ed_now_advice_with_its_callback_closed_out
    ):
        """PRD §3.2: "`DRAFT` windows can also be taken out of play without anyone
        asking: the final hop of the compliance variance cascade flips every `DRAFT`
        window of the affected practice to `BLOCKED` and stamps `suspend_reason` with
        the exact string `PRACTICE_UNDER_COMPLIANCE_REVIEW`."

        Design: Corner/validations/a_practice_under_compliance_review_cannot_activate_a_new_coverage_window
        """
        disposition = ed_now_advice_with_its_callback_closed_out
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T20:00:00Z",
        )
        window = world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-08-10T02:00:00Z",
            end_utc="2026-08-10T13:00:00Z",
            coverage_kind="NIGHTS",
        )
        world.api.activate_coverage_window(window["id"], {}, world.liaison_headers())

        after = world.coverage_window(window["id"])

        assert after["status"] == "DRAFT", (
            "the cascade had already run before this window existed"
        )
        assert after["suspend_reason"] is None
        assert_version_is(after, 1, "the refused activation wrote nothing")
        assert world.practice()["status"] == "ACTIVE", (
            "a compliance hold is not a commercial suspension"
        )
