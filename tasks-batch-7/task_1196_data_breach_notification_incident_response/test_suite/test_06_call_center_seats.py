"""Call-center seat formula — multi-input pinned evaluation order
(difficulty rule combinatorial_formula)."""
from test_helpers import (
    TEST_USERS,
    create_call_center_staffing_plan_payload,
    create_incident_confirmed,
    get_success_data,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]


class TestCallCenterSeatFormula:
    def test_tier1_with_multilang_surcharge(self, api):
        """PRD §3.10: "If P is below 100, the base seat count is 2. ... After
        the base tier is determined, if the incident's `severity` is
        `CRITICAL` the base is multiplied by 1.5 and the result is rounded
        half-up to an integer. Finally, if `languages_supported` contains
        more than one language, 2 seats are added on top of the
        severity-adjusted result."

        With one VERIFIED subject, total_pending_subjects=1 (tier1 base=2).
        Severity remains UNCLASSIFIED at intake (PRD §3.1) and no endpoint
        transitions it, so the CRITICAL multiplier does not apply. Multi-lang
        ['en','es'] adds +2 on top: 2 + 2 = 4.

        Design: Difficulty/combinatorial_formula/call_center_seats_tiered_multi_input_mode_a
        """
        ctx = create_incident_confirmed(subject_count=1)
        inc = ctx["incident"]
        # Sanity: one verified subject contributes 1 to total_pending_subjects.
        inc_now = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_now["total_pending_subjects"] == 1

        resp = api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                effective_from="2026-05-02T00:00:00Z",
                effective_until="2026-06-02T00:00:00Z",
                languages_supported=["en", "es"],
            ),
            IC,
        )
        plan = validate_success(resp, expected_status=201)
        assert plan["seats_required"] == 4
