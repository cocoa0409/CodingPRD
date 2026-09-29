"""Documentation, de-escalation authority and the override step limit."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant, assert_version_is

LONG_ESCALATION_NARRATIVE = (
    "Crushing chest pain radiating to the left arm with diaphoresis; escalating to 911."
)
LONG_SOFTENING_NARRATIVE = (
    "Caller declines the emergency department and has no transport available tonight."
)


@pytest.fixture
def assessed_call_recommending_ed_now(world):
    """Base severity 62 plus one red flag: acuity 70, recommendation ED_NOW."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call, assessment = world.call_through_assessment(
        "nurse_a", "protocol", red_flag_count=1, reason_text="chest discomfort"
    )
    return call, assessment


class TestDispositionCreateDocumentationGates:
    def test_an_undocumented_escalation_is_refused(
        self, world, assessed_call_recommending_ed_now
    ):
        """PRD §3.6: "Any `final_level` that differs from `recommended_level` in either
        direction is an override and demands documentation: `override_reason_code` must
        be present, chosen from `CALLER_REFUSED_ED`, `TRANSPORT_UNAVAILABLE`,
        `CLINICIAN_DIRECTED`, `PROTOCOL_MISMATCH` and `LANGUAGE_BARRIER`, and
        `override_narrative` must be at least forty characters long."

        Design: Corner/validations/disposition_create_rejects_an_undocumented_escalation_then_a_deescalation
        """
        call, assessment = assessed_call_recommending_ed_now
        assert assessment["acuity_score"] == 70

        response = world.api.create_disposition(
            f.disposition_payload(
                call["id"], assessment["id"], "EMERGENCY_911", call["version"]
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_DOCUMENTATION_REQUIRED, 422)

    def test_a_ten_character_narrative_misses_the_forty_character_bar(
        self, world, assessed_call_recommending_ed_now
    ):
        """PRD §3.6: "A missing code or a shorter narrative is refused with
        `ERR_OVERRIDE_DOCUMENTATION_REQUIRED`."

        Design: Corner/validations/disposition_create_rejects_an_undocumented_escalation_then_a_deescalation
        """
        call, assessment = assessed_call_recommending_ed_now

        response = world.api.create_disposition(
            f.disposition_payload(
                call["id"],
                assessment["id"],
                "EMERGENCY_911",
                call["version"],
                override_reason_code="CLINICIAN_DIRECTED",
                override_narrative="Too short.",
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_DOCUMENTATION_REQUIRED, 422)

    def test_a_triage_nurse_may_not_soften_the_advice_even_with_documentation(
        self, world, assessed_call_recommending_ed_now
    ):
        """PRD §3.6: "A `final_level` whose ordinal is below the computed
        `recommended_level` on the create path is refused with
        `ERR_DEESCALATION_REQUIRES_CHARGE_NURSE`, because softening advice is a
        supervisory act performed against an already-created disposition."

        Design: Corner/validations/disposition_create_rejects_an_undocumented_escalation_then_a_deescalation
        """
        call, assessment = assessed_call_recommending_ed_now

        response = world.api.create_disposition(
            f.disposition_payload(
                call["id"],
                assessment["id"],
                "URGENT_CARE_24H",
                call["version"],
                override_reason_code="TRANSPORT_UNAVAILABLE",
                override_narrative=LONG_SOFTENING_NARRATIVE,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_DEESCALATION_REQUIRES_CHARGE_NURSE, 403)

    def test_the_three_refusals_leave_the_call_version_reusable(
        self, world, assessed_call_recommending_ed_now
    ):
        """PRD §2.12: "no later rule is evaluated and no state is written."

        Design: Corner/validations/disposition_create_rejects_an_undocumented_escalation_then_a_deescalation
        """
        call, assessment = assessed_call_recommending_ed_now
        for payload in (
            f.disposition_payload(
                call["id"], assessment["id"], "EMERGENCY_911", call["version"]
            ),
            f.disposition_payload(
                call["id"],
                assessment["id"],
                "EMERGENCY_911",
                call["version"],
                override_reason_code="CLINICIAN_DIRECTED",
                override_narrative="Too short.",
            ),
            f.disposition_payload(
                call["id"],
                assessment["id"],
                "URGENT_CARE_24H",
                call["version"],
                override_reason_code="TRANSPORT_UNAVAILABLE",
                override_narrative=LONG_SOFTENING_NARRATIVE,
            ),
        ):
            world.api.create_disposition(payload, world.nurse_headers("nurse_a"))

        disposition = world.create_disposition(
            call["id"],
            assessment["id"],
            "EMERGENCY_911",
            "nurse_a",
            expected_call_version=call["version"],
            override_reason_code="CLINICIAN_DIRECTED",
            override_narrative=LONG_ESCALATION_NARRATIVE,
        )

        assert disposition["recommended_level"] == "ED_NOW"
        assert disposition["final_level"] == "EMERGENCY_911"
        assert disposition["advice_status"] == "AUTHORIZED"
        assert disposition["determined_by_nurse_id"] == world.nurse_id("nurse_a")

    def test_the_accepted_escalation_arms_the_warm_transfer_chain(
        self, world, assessed_call_recommending_ed_now
    ):
        """PRD §3.6: "When the `final_level` is `EMERGENCY_911`, the first hop sets the
        call's `requires_warm_transfer` to true; the second hop, caused by that flag
        turning on, increases the determining nurse's `pending_high_risk_count` by
        one".

        Design: Corner/validations/disposition_create_rejects_an_undocumented_escalation_then_a_deescalation
        """
        call, assessment = assessed_call_recommending_ed_now
        world.create_disposition(
            call["id"],
            assessment["id"],
            "EMERGENCY_911",
            "nurse_a",
            override_reason_code="CLINICIAN_DIRECTED",
            override_narrative=LONG_ESCALATION_NARRATIVE,
        )

        after = world.call(call["id"])
        nurse = world.nurse("nurse_a")

        assert after["status"] == "DISPOSITIONED"
        assert after["requires_warm_transfer"] is True
        assert nurse["pending_high_risk_count"] == 1
        assert nurse["intake_eligibility"] == "ON_ROTATION", (
            "the cap of two has not been reached yet"
        )
        _, meta = validate_paginated(
            world.api.list_dispositions(world.admin, {"call_id": call["id"]})
        )
        assert meta["total_count"] == 1


@pytest.fixture
def emergency_recommendation_with_a_charge_nurse(world):
    """Acuity 86 (62 plus the capped 24 red-flag points): EMERGENCY_911."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b"),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "EMERGENCY_911", "nurse_a", red_flag_count=3, reason_text="crushing chest pain"
    )
    return call, assessment, disposition


class TestEmergencyRecommendationCannotBeSoftened:
    def test_a_documented_one_step_softening_is_still_forbidden(
        self, world, emergency_recommendation_with_a_charge_nurse
    ):
        """PRD §3.6: "If the disposition's `recommended_level` is `EMERGENCY_911`, then
        the only permitted `final_level` is `EMERGENCY_911` itself: de-escalating away
        from an emergency recommendation is forbidden outright and answers
        `ERR_EMERGENCY_DEESCALATION_FORBIDDEN`."

        Design: Corner/validations/override_of_an_emergency_recommendation_cannot_be_softened
        """
        _, assessment, disposition = emergency_recommendation_with_a_charge_nurse
        assert assessment["acuity_score"] == 86
        assert disposition["recommended_level"] == "EMERGENCY_911"

        response = world.api.override_disposition(
            disposition["id"],
            f.override_payload(
                "ED_NOW",
                override_reason_code="CALLER_REFUSED_ED",
                override_narrative=(
                    "Caller flatly refuses an ambulance and a family member will drive "
                    "them to the emergency department."
                ),
            ),
            world.charge_headers("nurse_b"),
        )

        validate_error(response, ApiErrorId.ERR_EMERGENCY_DEESCALATION_FORBIDDEN, 422)

    def test_the_refusal_leaves_the_disposition_byte_for_byte_as_it_was(
        self, world, emergency_recommendation_with_a_charge_nurse
    ):
        """PRD §2.12: "the **first** rule whose condition holds produces the response;
        no later rule is evaluated and no state is written."

        Design: Corner/validations/override_of_an_emergency_recommendation_cannot_be_softened
        """
        _, _, disposition = emergency_recommendation_with_a_charge_nurse
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("ED_NOW"),
            world.charge_headers("nurse_b"),
        )

        after = world.disposition(disposition["id"])

        assert after["advice_status"] == "AUTHORIZED"
        assert after["final_level"] == "EMERGENCY_911"
        assert after["overridden_by_nurse_id"] is None
        assert_version_is(after, 1)

    def test_the_warm_transfer_hold_survives_the_refusal(
        self, world, emergency_recommendation_with_a_charge_nurse
    ):
        """PRD §3.6: "if the disposition's `final_level` had been `EMERGENCY_911` and
        the new level is not, the call's `requires_warm_transfer` is set back to false,
        the `determined_by_nurse_id` nurse's `pending_high_risk_count` decreases by
        one" — consequences a refused override must not produce.

        Design: Corner/validations/override_of_an_emergency_recommendation_cannot_be_softened
        """
        call, _, disposition = emergency_recommendation_with_a_charge_nurse
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("ED_NOW"),
            world.charge_headers("nurse_b"),
        )

        assert world.call(call["id"])["requires_warm_transfer"] is True
        assert world.nurse("nurse_a")["pending_high_risk_count"] == 1


@pytest.fixture
def ed_now_disposition_with_a_high_risk_task(world):
    """An ED_NOW disposition by nurse_a with nurse_b standing by as charge."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b"),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    task = world.callback_for(disposition["id"])
    return disposition, task


class TestOverrideStepLimit:
    def test_three_ordinal_steps_are_beyond_the_limit(
        self, world, ed_now_disposition_with_a_high_risk_task
    ):
        """PRD §3.6: "The requested `final_level` must be within one severity step of
        the disposition's current `final_level` in either direction — a difference of
        two or more ordinals is refused with `ERR_OVERRIDE_STEP_LIMIT`."

        Design: Corner/validations/override_beyond_one_ordinal_step_is_rejected
        """
        disposition, task = ed_now_disposition_with_a_high_risk_task
        assert task["risk_class"] == "HIGH_RISK"

        response = world.api.override_disposition(
            disposition["id"],
            f.override_payload("HOME_CARE"),
            world.charge_headers("nurse_b"),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_STEP_LIMIT, 422)

    def test_exactly_one_step_is_accepted_and_recorded(
        self, world, ed_now_disposition_with_a_high_risk_task
    ):
        """PRD §3.6: "A successful override sets `final_level` to the requested level,
        sets `is_override` true, records `override_reason_code`, `override_narrative`
        and `overridden_by_nurse_id` as the acting nurse's identifier, moves
        `advice_status` to `OVERRIDDEN`".

        Design: Corner/validations/override_beyond_one_ordinal_step_is_rejected
        """
        disposition, _ = ed_now_disposition_with_a_high_risk_task
        world.api.override_disposition(
            disposition["id"],
            f.override_payload("HOME_CARE"),
            world.charge_headers("nurse_b"),
        )

        overridden = world.override_disposition(
            disposition["id"],
            "URGENT_CARE_24H",
            "nurse_b",
            override_reason_code="TRANSPORT_UNAVAILABLE",
            override_narrative=(
                "No transport to the emergency department tonight; urgent care within "
                "24 hours agreed with the caller."
            ),
        )

        assert overridden["advice_status"] == "OVERRIDDEN"
        assert overridden["final_level"] == "URGENT_CARE_24H"
        assert overridden["overridden_by_nurse_id"] == world.nurse_id("nurse_b")
        assert overridden["recommended_level"] == "ED_NOW"

    def test_the_softening_swaps_the_high_risk_task_for_a_standard_one(
        self, world, ed_now_disposition_with_a_high_risk_task
    ):
        """PRD §3.6: "if the recomputed `requires_callback` is still true, a replacement
        task is created carrying the `risk_class`, `due_by_utc` and `max_attempts` of
        the **new** level, and `open_callback_count` increases again."

        Design: Corner/validations/override_beyond_one_ordinal_step_is_rejected
        """
        disposition, task = ed_now_disposition_with_a_high_risk_task
        world.override_disposition(
            disposition["id"],
            "URGENT_CARE_24H",
            "nurse_b",
            override_reason_code="TRANSPORT_UNAVAILABLE",
            override_narrative=(
                "No transport to the emergency department tonight; urgent care within "
                "24 hours agreed with the caller."
            ),
        )

        assert world.callback(task["id"])["status"] == "CANCELLED"
        pending, pending_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.charge_headers("nurse_b"),
                {"disposition_id": disposition["id"], "status": "PENDING"},
            )
        )
        assert pending_meta["total_count"] == 1
        assert pending[0]["risk_class"] == "STANDARD"
        assert_instant(pending[0]["due_by_utc"], "2026-08-04T02:30:00Z", "due_by_utc")
        assert pending[0]["max_attempts"] == 2
        assert pending[0]["attempt_count"] == 0
        assert world.practice()["open_callback_count"] == 1
        _, all_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin, {"disposition_id": disposition["id"]}
            )
        )
        assert all_meta["total_count"] == 2
