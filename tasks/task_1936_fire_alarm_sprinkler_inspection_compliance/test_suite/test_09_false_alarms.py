"""False-alarm adjudication: chargeability, rolling-window sequencing, fee
tiers, the habitual surcharge, the residential variant, and waiver invariants."""
from test_helpers import (
    assert_false_alarm,
    create_contractor,
    create_property,
    record_and_assess_alarm,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


def _site(api, legal_name, occupancy_class="BUSINESS"):
    con = create_contractor(legal_name=legal_name)
    return create_property(con, occupancy_class=occupancy_class)


class TestThirdAlarmBoundary:
    def test_first_two_chargeable_alarms_cost_nothing(self, api):
        """PRD §3.8: "In the standard schedule — every class except `RESIDENTIAL`
        — the first and second chargeable cases in the window cost nothing, the
        third and fourth cost 15000 cents each tier-wide, the fifth and sixth
        30000, and the seventh and beyond 50000."
        PRD §3.8: "Only `NEGLIGENCE`, `EQUIPMENT_FAULT`, and `UNKNOWN` are
        chargeable; the server computes `chargeable` accordingly."

        Design: Difficulty/boundary_precision_check/false_alarm_third_alarm_exactly_triggers_fee
        """
        prop = _site(api, "Boundary Co")
        a1 = record_and_assess_alarm(prop, "2026-08-02T01:00:00Z", "EQUIPMENT_FAULT")
        a2 = record_and_assess_alarm(prop, "2026-08-03T01:00:00Z", "UNKNOWN")
        assert a1["sequence_number"] == 1 and a1["fee_cents"] == 0
        assert a2["sequence_number"] == 2 and a2["fee_cents"] == 0, (
            "the first and second chargeable cases in the window cost nothing")

    def test_third_alarm_exactly_triggers_fee(self, api):
        """PRD §3.8: "In the standard schedule — every class except `RESIDENTIAL`
        — the first and second chargeable cases in the window cost nothing, the
        third and fourth cost 15000 cents each tier-wide, the fifth and sixth
        30000, and the seventh and beyond 50000."

        Design: Difficulty/boundary_precision_check/false_alarm_third_alarm_exactly_triggers_fee
        """
        prop = _site(api, "Boundary Co")
        record_and_assess_alarm(prop, "2026-08-02T01:00:00Z", "EQUIPMENT_FAULT")
        record_and_assess_alarm(prop, "2026-08-03T01:00:00Z", "UNKNOWN")
        a3 = record_and_assess_alarm(prop, "2026-08-04T01:00:00Z", "NEGLIGENCE")
        assert a3["sequence_number"] == 3, (
            "the one-indexed position within the rolling window")
        assert a3["fee_cents"] == 15000, (
            "the third chargeable alarm crosses into the 15000-cent tier")


class TestHabitualSurcharge:
    def test_seventh_alarm_adds_habitual_surcharge(self, api):
        """PRD §3.8: "the fifth and sixth 30000, and the seventh and beyond
        50000."
        PRD §3.8: "In both variants a habitual surcharge of 25000 cents is added
        whenever the sequence number is at least seven. The fee is the tier plus
        the surcharge, in integer cents."

        Design: Corner/calculations/false_alarm_seventh_alarm_habitual_surcharge
        """
        prop = _site(api, "Habitual Co")
        causes = ["NEGLIGENCE", "NEGLIGENCE", "EQUIPMENT_FAULT", "UNKNOWN",
                  "NEGLIGENCE", "NEGLIGENCE"]
        cases = [record_and_assess_alarm(prop, f"2026-08-0{i + 2}T01:00:00Z", c)
                 for i, c in enumerate(causes)]
        assert cases[4]["fee_cents"] == 30000, "sequence 5 tier is 30000"
        assert cases[5]["fee_cents"] == 30000, "sequence 6 tier is 30000"

        a7 = record_and_assess_alarm(prop, "2026-08-08T01:00:00Z", "NEGLIGENCE")
        assert a7["sequence_number"] == 7
        assert a7["fee_cents"] == 75000, (
            "50000 tier plus the 25000 habitual surcharge at sequence seven")


class TestRollingWindow:
    def test_alarm_older_than_365_days_excluded(self, api):
        """PRD §3.8: "For a chargeable case, `sequence_number` is computed as one
        plus the count of the property's other chargeable, non-`WAIVED` cases
        whose alarm dates fall within the trailing 365-day window — on or after
        364 days before the current alarm's date and strictly before it — making
        the sequence number the one-indexed position within the rolling window
        ending on the alarm date inclusive."

        Design: Corner/calculations/false_alarm_rolling_window_excludes_older_than_365
        """
        prop = _site(api, "Window Co")
        record_and_assess_alarm(prop, "2025-08-10T01:00:00Z", "NEGLIGENCE")
        record_and_assess_alarm(prop, "2026-08-09T01:00:00Z", "NEGLIGENCE")
        new = record_and_assess_alarm(prop, "2026-08-10T01:00:00Z", "NEGLIGENCE")
        assert new["sequence_number"] == 2, (
            "2025-08-10 is more than 364 days before 2026-08-10, so only the "
            "in-window prior alarm counts")
        assert new["fee_cents"] == 0


class TestResidentialVariant:
    def test_residential_third_alarm_half_rate(self, api):
        """PRD §3.8: "For a `RESIDENTIAL` property every tier is halved with
        round-half-up applied to the halved tier: free, 7500, 15000, and 25000
        respectively."

        Design: Corner/calculations/false_alarm_residential_half_rate_variant
        """
        prop = _site(api, "Resi Co", occupancy_class="RESIDENTIAL")
        record_and_assess_alarm(prop, "2026-08-02T01:00:00Z", "NEGLIGENCE")
        record_and_assess_alarm(prop, "2026-08-03T01:00:00Z", "NEGLIGENCE")
        a3 = record_and_assess_alarm(prop, "2026-08-04T01:00:00Z", "NEGLIGENCE")
        assert a3["sequence_number"] == 3
        assert a3["fee_cents"] == 7500, "the residential third-tier rate is halved"


class TestWaivePoolInvariant:
    def _three_assessed(self, api):
        prop = _site(api, "Waive Co")
        record_and_assess_alarm(prop, "2026-08-02T01:00:00Z", "NEGLIGENCE")
        record_and_assess_alarm(prop, "2026-08-03T01:00:00Z", "EQUIPMENT_FAULT")
        a3 = record_and_assess_alarm(prop, "2026-08-04T01:00:00Z", "UNKNOWN")
        return prop, a3

    def test_waive_zeroes_fee_and_marks_waived(self, api):
        """PRD §3.8: "A marshal may waive a case from either `OPEN` or
        `ASSESSED`, which zeroes `fee_cents`, sets `waived` true, and lands in
        `WAIVED`; a waived case no longer counts in future sequence windows."

        Design: Difficulty/compensating_invariant/false_alarm_waive_restores_fee_pool_invariant
        """
        prop, a3 = self._three_assessed(api)
        assert a3["fee_cents"] == 15000
        waived = validate_success(api.waive_false_alarm(a3["id"], MARSHAL))
        assert_false_alarm(waived)
        assert waived["status"] == "WAIVED"
        assert waived["fee_cents"] == 0, "the waiver zeroes the assessed fee"
        assert waived["waived"] is True

    def test_waived_case_excluded_from_future_sequence(self, api):
        """PRD §3.8: "a waived case no longer counts in future sequence windows."
        PRD §3.8: "For a chargeable case, `sequence_number` is computed as one
        plus the count of the property's other chargeable, non-`WAIVED` cases
        whose alarm dates fall within the trailing 365-day window"

        Design: Difficulty/compensating_invariant/false_alarm_waive_restores_fee_pool_invariant
        """
        prop, a3 = self._three_assessed(api)
        validate_success(api.waive_false_alarm(a3["id"], MARSHAL))
        a4 = record_and_assess_alarm(prop, "2026-08-05T01:00:00Z", "NEGLIGENCE")
        assert a4["sequence_number"] == 3, (
            "with the waived third case excluded, the new case takes the "
            "sequence slot the waived case vacated")
        assert a4["fee_cents"] == 15000
