"""Consistency coverage: a decision recorded against one aggregate is already
reflected in the parent aggregate's derived figures when a different role reads
that parent immediately afterwards.
"""

from test_helpers import (
    OFFICER,
    REVIEWER,
    api_client,
    decide_safety_review_payload,
    file_safety_review,
    recruit_employer_partner,
    register_worksite,
    set_clock,
    validate_success,
)

ALDER_GATE_RECYCLING = {
    "legal_name": "Alder Gate Recycling",
    "naics_code": "562920",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10271",
}


class TestPartnerScoreIsVisibleImmediately:
    def test_the_conditional_penalty_is_on_the_partner_the_moment_it_is_read(self):
        """The employer's score is recomputed with a 10-point penalty for each of the
        partner's worksites currently sitting at `CONDITIONAL`, and `posture` is re-derived
        from the new score — landing on `PROBATION` when the score is at least 50 but below
        70. Otherwise, if at least one worksite of the partner has `safety_status` of
        `APPROVED` or `CONDITIONAL`, the posture is `ELIGIBLE`.

        Design: Corner/consistency model/cross_aggregate_score_is_visible_on_the_very_next_read
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**ALDER_GATE_RECYCLING)
        worksite = register_worksite(
            partner["id"],
            site_name="Alder Gate Sort Line",
            address_line="31 Alder Gate",
            hazard_class="LIMITED_HAZARD",
            has_power_machinery=True,
            max_concurrent_students=1,
        )
        review = file_safety_review(
            worksite["id"], worksite["version"], hazard_findings_count=3
        )
        validate_success(
            api_client.decide_safety_review(
                review["id"], decide_safety_review_payload("CONDITIONAL"), REVIEWER
            )
        )

        read_back = validate_success(
            api_client.get_employer_partner(partner["id"], OFFICER)
        )

        assert read_back["safety_score"] == 90
        assert read_back["posture"] == "ELIGIBLE"
        assert read_back["substantiated_minor_count"] == 0
        assert read_back["substantiated_moderate_count"] == 0
        assert read_back["substantiated_critical_count"] == 0
        assert read_back["wage_liability_cents"] == 0
