"""Segregation of duties, once-only override, and the two assessment gates."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant, assert_version_is

TRANSPORT_NARRATIVE = (
    "No transport to the emergency department tonight; urgent care within 24 hours "
    "agreed with the caller."
)


@pytest.fixture
def own_disposition_with_its_high_risk_callback(world):
    """An ED_NOW disposition determined by nurse_a; nurse_c took no part in it."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    task = world.callback_for(disposition["id"])
    return call, assessment, disposition, task


class TestSegregationOfDutiesGuardsTwoEndpoints:
    def test_the_advising_nurse_cannot_override_their_own_disposition(
        self, world, own_disposition_with_its_high_risk_callback
    ):
        """PRD §3.6: "And the acting nurse must not be the disposition's
        `determined_by_nurse_id`, or the answer is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/the_advising_nurse_can_neither_verify_nor_override_their_own_disposition
        """
        _, _, disposition, task = own_disposition_with_its_high_risk_callback
        assert task["risk_class"] == "HIGH_RISK"
        assert_instant(task["due_by_utc"], "2026-08-03T16:30:00Z", "due_by_utc")

        response = world.api.override_disposition(
            disposition["id"],
            f.override_payload(
                "URGENT_CARE_24H",
                override_reason_code="TRANSPORT_UNAVAILABLE",
                override_narrative=TRANSPORT_NARRATIVE,
            ),
            world.charge_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_the_same_nurse_may_still_place_the_attempt_but_not_verify_it(
        self, world, own_disposition_with_its_high_risk_callback
    ):
        """PRD §2.11: "The same nurse is nonetheless the nurse who records callback
        attempts, because logging an unanswered call is not a clinical judgement."

        Design: Corner/validations/the_advising_nurse_can_neither_verify_nor_override_their_own_disposition
        """
        _, _, disposition, task = own_disposition_with_its_high_risk_callback
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("URGENT_CARE_24H"),
            world.charge_headers("nurse_a"),
        )

        reached = world.record_attempt(task["id"], "nurse_a", "REACHED")
        assert reached["status"] == "REACHED"

        response = world.api.verify_callback(
            task["id"],
            f.verify_payload("IMPROVED", True),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_an_uninvolved_nurse_closes_the_loop_and_the_advice_never_moved(
        self, world, own_disposition_with_its_high_risk_callback
    ):
        """PRD §3.8: "Verification is only possible from `REACHED`, and it is where
        segregation of duties bites: the acting nurse must not be the disposition's
        `determined_by_nurse_id`, and an attempt by that nurse is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/the_advising_nurse_can_neither_verify_nor_override_their_own_disposition
        """
        _, _, disposition, task = own_disposition_with_its_high_risk_callback
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("URGENT_CARE_24H"),
            world.charge_headers("nurse_a"),
        )
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.api.verify_callback(
            task["id"],
            f.verify_payload("IMPROVED", True),
            world.nurse_headers("nurse_a"),
        )

        verified = world.verify_callback(task["id"], "nurse_c", "IMPROVED", True)

        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_nurse_id"] == world.nurse_id("nurse_c")
        assert verified["attempt_count"] == 0, "a REACHED outcome is not a failed attempt"
        after = world.disposition(disposition["id"])
        assert after["advice_status"] == "AUTHORIZED"
        assert after["final_level"] == "ED_NOW"
        assert after["overridden_by_nurse_id"] is None
        assert_instant(
            after["callback_verified_at"],
            "2026-08-03T14:30:00Z",
            "callback_verified_at",
        )
        assert world.practice()["open_callback_count"] == 0


@pytest.fixture
def disposition_already_overridden_once(world):
    """nurse_b has softened nurse_a's ED_NOW advice by exactly one step."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b"),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    first = world.override_disposition(
        disposition["id"],
        "URGENT_CARE_24H",
        "nurse_b",
        override_reason_code="TRANSPORT_UNAVAILABLE",
        override_narrative=TRANSPORT_NARRATIVE,
    )
    return disposition, first


class TestOverrideIsOnceOnly:
    def test_the_first_override_lands_in_the_overridden_state(
        self, world, disposition_already_overridden_once
    ):
        """PRD §3.6: "Overriding a determined disposition is the charge nurse's
        compensating operation, and it moves the advice dimension
        `AUTHORIZED → OVERRIDDEN`."

        Design: Corner/validations/override_of_an_already_overridden_disposition_is_rejected
        """
        _, first = disposition_already_overridden_once

        assert first["advice_status"] == "OVERRIDDEN"
        assert first["final_level"] == "URGENT_CARE_24H"
        assert first["overridden_by_nurse_id"] == world.nurse_id("nurse_b")
        assert_version_is(first, 2)

    def test_a_second_override_is_refused_on_the_from_set(
        self, world, disposition_already_overridden_once
    ):
        """PRD §3.6: "The disposition's `advice_status` must be `AUTHORIZED` — a
        `VOIDED` disposition or one already `OVERRIDDEN` is refused with
        `ERR_DISPOSITION_INVALID_STATE`".

        Design: Corner/validations/override_of_an_already_overridden_disposition_is_rejected
        """
        disposition, _ = disposition_already_overridden_once

        response = world.api.override_disposition(
            disposition["id"],
            f.override_payload(
                "OFFICE_APPT_72H",
                override_reason_code="CLINICIAN_DIRECTED",
                override_narrative=(
                    "The caller improved overnight and an office appointment inside "
                    "seventy-two hours is now sufficient."
                ),
            ),
            world.charge_headers("nurse_b"),
        )

        validate_error(response, ApiErrorId.ERR_DISPOSITION_INVALID_STATE, 409)
        after = world.disposition(disposition["id"])
        assert after["final_level"] == "URGENT_CARE_24H"
        assert after["override_reason_code"] == "TRANSPORT_UNAVAILABLE"
        assert after["overridden_by_nurse_id"] == world.nurse_id("nurse_b")
        assert_version_is(after, 2, "the refusal wrote nothing")

    def test_the_replacement_task_from_the_first_override_is_untouched(
        self, world, disposition_already_overridden_once
    ):
        """PRD §3.6: "a replacement task is created carrying the `risk_class`,
        `due_by_utc` and `max_attempts` of the **new** level, and
        `open_callback_count` increases again."

        Design: Corner/validations/override_of_an_already_overridden_disposition_is_rejected
        """
        disposition, _ = disposition_already_overridden_once
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("OFFICE_APPT_72H"),
            world.charge_headers("nurse_b"),
        )

        pending, meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin,
                {"disposition_id": disposition["id"], "status": "PENDING"},
            )
        )

        assert meta["total_count"] == 1
        assert pending[0]["risk_class"] == "STANDARD"
        assert_instant(pending[0]["due_by_utc"], "2026-08-04T02:30:00Z", "due_by_utc")
        assert pending[0]["max_attempts"] == 2
        assert world.practice()["open_callback_count"] == 1


@pytest.fixture
def reassessed_call_with_a_voided_disposition(world):
    """assessment_1 carried ED_NOW advice; a 0-red-flag re-score superseded it."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call, assessment_1, disposition_1 = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    assessment_2 = world.create_assessment(
        call["id"], "nurse_a", "protocol", red_flag_count=0
    )
    return call, assessment_1, disposition_1, assessment_2


class TestSupersededAssessmentCannotCarryAdvice:
    def test_the_re_score_supersedes_the_old_assessment_and_voids_its_advice(
        self, world, reassessed_call_with_a_voided_disposition
    ):
        """PRD §3.5: "In the first hop, the new assessment is created `ACTIVE` and the
        call's previously `ACTIVE` assessment flips to `SUPERSEDED`."

        Design: Corner/validations/disposition_on_a_superseded_assessment_is_rejected
        """
        _, assessment_1, disposition_1, assessment_2 = (
            reassessed_call_with_a_voided_disposition
        )

        old = world.assessment(assessment_1["id"])

        assert old["status"] == "SUPERSEDED", "still fetchable, no longer able to advise"
        assert assessment_2["status"] == "ACTIVE"
        assert world.disposition(disposition_1["id"])["advice_status"] == "VOIDED"
        cancelled, meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin, {"disposition_id": disposition_1["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert cancelled[0]["status"] == "CANCELLED"

    def test_quoting_the_superseded_assessment_is_refused(
        self, world, reassessed_call_with_a_voided_disposition
    ):
        """PRD §3.6: "The named assessment must exist, must have `status` `ACTIVE` — a
        superseded one is refused with `ERR_ASSESSMENT_SUPERSEDED` — and must belong to
        the call named in the body, or the answer is `ERR_ASSESSMENT_CALL_MISMATCH`."

        Design: Corner/validations/disposition_on_a_superseded_assessment_is_rejected
        """
        call, assessment_1, _, _ = reassessed_call_with_a_voided_disposition
        current = world.call(call["id"])
        assert current["status"] == "ASSESSING"

        response = world.api.create_disposition(
            f.disposition_payload(
                call["id"], assessment_1["id"], "ED_NOW", current["version"]
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_ASSESSMENT_SUPERSEDED, 409)

    def test_the_replacement_assessment_is_accepted_in_the_very_same_call_state(
        self, world, reassessed_call_with_a_voided_disposition
    ):
        """PRD §3.6: "The flag `is_override` is set true whenever `final_level` differs
        from `recommended_level` at any point in the disposition's life."

        Design: Corner/validations/disposition_on_a_superseded_assessment_is_rejected
        """
        call, assessment_1, _, assessment_2 = reassessed_call_with_a_voided_disposition
        assert assessment_2["acuity_score"] == 62
        current = world.call(call["id"])
        world.api.create_disposition(
            f.disposition_payload(
                call["id"], assessment_1["id"], "ED_NOW", current["version"]
            ),
            world.nurse_headers("nurse_a"),
        )

        disposition_2 = world.create_disposition(
            call["id"],
            assessment_2["id"],
            "URGENT_CARE_24H",
            "nurse_a",
            expected_call_version=current["version"],
        )

        assert disposition_2["recommended_level"] == "URGENT_CARE_24H"
        assert disposition_2["advice_status"] == "AUTHORIZED"
        assert disposition_2["is_override"] is False
        assert disposition_2["requires_callback"] is True
        assert world.practice()["open_callback_count"] == 1
        assert world.call(call["id"])["status"] == "DISPOSITIONED"


@pytest.fixture
def two_sibling_calls_assessed_by_the_same_nurse(world):
    """Two calls for the same chart, both ASSESSING under nurse_a."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call_1, assessment_1 = world.call_through_assessment(
        "nurse_a",
        "protocol",
        red_flag_count=1,
        reason_text="first call about chest discomfort",
    )
    call_2, assessment_2 = world.call_through_assessment(
        "nurse_a",
        "protocol",
        red_flag_count=0,
        reason_text="second call about chest discomfort",
    )
    return (call_1, assessment_1), (call_2, assessment_2)


class TestAssessmentMustBelongToTheCallInTheBody:
    def test_borrowing_the_sibling_calls_assessment_is_refused(
        self, world, two_sibling_calls_assessed_by_the_same_nurse
    ):
        """PRD §2.12: "34. `ERR_ASSESSMENT_CALL_MISMATCH` — the referenced assessment's
        `call_id` is not the `call_id` in the body. Guards `POST /dispositions`."

        Design: Corner/validations/disposition_built_on_another_calls_assessment_is_rejected
        """
        (call_1, assessment_1), (call_2, _) = two_sibling_calls_assessed_by_the_same_nurse
        assert assessment_1["acuity_score"] == 70, "its own recommendation is ED_NOW"

        response = world.api.create_disposition(
            f.disposition_payload(
                call_2["id"], assessment_1["id"], "ED_NOW", call_2["version"]
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_ASSESSMENT_CALL_MISMATCH, 409)
        after_2 = world.call(call_2["id"])
        assert after_2["status"] == "ASSESSING"
        assert_version_is(after_2, call_2["version"], "the refusal wrote nothing")
        borrowed = world.assessment(assessment_1["id"])
        assert borrowed["status"] == "ACTIVE"
        assert borrowed["call_id"] == call_1["id"]

    def test_the_calls_own_assessment_is_accepted_and_stays_on_its_own_call(
        self, world, two_sibling_calls_assessed_by_the_same_nurse
    ):
        """PRD §3.6: "The assigned nurse determines the disposition for the call's
        `ACTIVE` assessment, moving the call `ASSESSING → DISPOSITIONED`."

        Design: Corner/validations/disposition_built_on_another_calls_assessment_is_rejected
        """
        (call_1, assessment_1), (call_2, assessment_2) = (
            two_sibling_calls_assessed_by_the_same_nurse
        )
        world.api.create_disposition(
            f.disposition_payload(
                call_2["id"], assessment_1["id"], "ED_NOW", call_2["version"]
            ),
            world.nurse_headers("nurse_a"),
        )

        disposition_2 = world.create_disposition(
            call_2["id"],
            assessment_2["id"],
            "URGENT_CARE_24H",
            "nurse_a",
            expected_call_version=call_2["version"],
        )

        assert disposition_2["final_level"] == "URGENT_CARE_24H"
        assert disposition_2["assessment_id"] == assessment_2["id"]
        assert world.call(call_1["id"])["status"] == "ASSESSING"
        _, meta = validate_paginated(
            world.api.list_dispositions(world.admin, {"call_id": call_1["id"]})
        )
        assert meta["total_count"] == 0
        assert world.nurse("nurse_a")["active_call_load"] == 2
