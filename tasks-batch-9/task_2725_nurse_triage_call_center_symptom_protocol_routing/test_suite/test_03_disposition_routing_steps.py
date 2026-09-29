"""The five ordered steps that produce `recommended_level`."""

import pytest

from test_helpers.assertions import assert_instant


@pytest.fixture
def override_protocol_world(world):
    """A protocol that both forces 911 on a red flag and floors at 72 hours."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        practice={"variance_review_threshold": 1},
        protocol={
            "code": "ABD_PAIN_OVR",
            "title": "Abdominal Pain With Red Flag Override",
            "base_severity": 20,
            "pregnancy_sensitive": False,
            "emergency_override": True,
            "min_disposition_level": "OFFICE_APPT_72H",
        },
    )
    flagged = world.call_through_assignment(
        "nurse_a", reason_text="abdominal pain with rigid abdomen"
    )
    unflagged = world.call_through_assignment(
        "nurse_a", reason_text="abdominal pain, settling"
    )
    return flagged, unflagged


class TestRoutingStepOrder:
    def test_step_two_promotes_a_home_care_band_to_emergency(
        self, world, override_protocol_world
    ):
        """PRD §3.6: "**Step two — the hard protocol override.** If the protocol's
        `emergency_override` flag is true and the assessment's `red_flag_count` is
        at least one, the level becomes `EMERGENCY_911` regardless of which band
        step one produced."

        Design: Difficulty/combinatorial_formula/disposition_routing_step_two_override_beats_band_and_step_five_floor_lifts_home_care
        """
        flagged, _ = override_protocol_world
        assessment = world.create_assessment(
            flagged["id"], "nurse_a", red_flag_count=1
        )
        assert assessment["acuity_score"] == 28, (
            "base 20 plus eight red-flag points is 28, which bands to HOME_CARE"
        )

        disposition = world.create_disposition(
            flagged["id"], assessment["id"], "EMERGENCY_911", "nurse_a"
        )

        assert disposition["recommended_level"] == "EMERGENCY_911", (
            "step two overrides the band before the protocol floor is consulted"
        )
        assert disposition["is_override"] is False

    def test_step_five_lifts_an_unflagged_home_care_band_to_the_protocol_floor(
        self, world, override_protocol_world
    ):
        """PRD §3.6: "An acuity of 20 bands to `HOME_CARE`, and a protocol floor of
        `OFFICE_APPT_72H` raises it by step five from ordinal one to ordinal two."

        Design: Difficulty/combinatorial_formula/disposition_routing_step_two_override_beats_band_and_step_five_floor_lifts_home_care
        """
        _, unflagged = override_protocol_world
        assessment = world.create_assessment(
            unflagged["id"], "nurse_a", red_flag_count=0
        )
        assert assessment["acuity_score"] == 20, "no red flags leaves the base score"

        disposition = world.create_disposition(
            unflagged["id"], assessment["id"], "OFFICE_APPT_72H", "nurse_a"
        )

        assert disposition["recommended_level"] == "OFFICE_APPT_72H", (
            "with no red flag step two is inert and step five applies the floor"
        )
        assert disposition["is_override"] is False

    def test_the_two_branches_owe_callbacks_of_different_classes(
        self, world, override_protocol_world
    ):
        """PRD §3.6: "The task's `risk_class` is `HIGH_RISK` when the `final_level`
        ordinal is at least four — that is, `ED_NOW` or `EMERGENCY_911`; otherwise
        it is `NEXT_DAY` when the call is after-hours and the ordinal is at most
        two — that is, `OFFICE_APPT_72H` or `HOME_CARE`; otherwise it is
        `STANDARD`."

        Design: Difficulty/combinatorial_formula/disposition_routing_step_two_override_beats_band_and_step_five_floor_lifts_home_care
        """
        flagged, unflagged = override_protocol_world
        flagged_assessment = world.create_assessment(
            flagged["id"], "nurse_a", red_flag_count=1
        )
        emergency = world.create_disposition(
            flagged["id"], flagged_assessment["id"], "EMERGENCY_911", "nurse_a"
        )
        unflagged_assessment = world.create_assessment(
            unflagged["id"], "nurse_a", red_flag_count=0
        )
        office = world.create_disposition(
            unflagged["id"], unflagged_assessment["id"], "OFFICE_APPT_72H", "nurse_a"
        )

        high_risk = world.callback_for(emergency["id"])
        standard = world.callback_for(office["id"])

        assert high_risk["risk_class"] == "HIGH_RISK"
        assert high_risk["max_attempts"] == 3
        assert_instant(
            high_risk["due_by_utc"], "2026-08-03T16:30:00Z", "high-risk due_by_utc"
        )
        assert standard["risk_class"] == "STANDARD"
        assert standard["max_attempts"] == 2
        assert_instant(
            standard["due_by_utc"], "2026-08-04T02:30:00Z", "standard due_by_utc"
        )

    def test_both_open_callbacks_are_counted_on_the_practice(
        self, world, override_protocol_world
    ):
        """PRD §2.9: "`Practice.open_callback_count` must equal the number of
        `CallbackTask` rows belonging to that practice whose `status` is `PENDING`,
        `ATTEMPTED` or `REACHED`."

        Design: Difficulty/combinatorial_formula/disposition_routing_step_two_override_beats_band_and_step_five_floor_lifts_home_care
        """
        flagged, unflagged = override_protocol_world
        flagged_assessment = world.create_assessment(
            flagged["id"], "nurse_a", red_flag_count=1
        )
        world.create_disposition(
            flagged["id"], flagged_assessment["id"], "EMERGENCY_911", "nurse_a"
        )
        unflagged_assessment = world.create_assessment(
            unflagged["id"], "nurse_a", red_flag_count=0
        )
        world.create_disposition(
            unflagged["id"], unflagged_assessment["id"], "OFFICE_APPT_72H", "nurse_a"
        )

        assert world.practice()["open_callback_count"] == 2
