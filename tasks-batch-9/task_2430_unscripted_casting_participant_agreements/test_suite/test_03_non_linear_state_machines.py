"""State machines that are not straight lines: the unbounded negotiation cycle,
the applicant's two independent dimensions, and the complaint fork that rejoins
at resolution.
"""

from test_helpers import (
    TEST_USERS,
    assert_money,
    assert_negotiation_round,
    assert_score,
    get_agreement,
    get_applicant,
    get_production,
    make_applicant_headers,
    record_screening_items,
    setup_applicant,
    setup_cleared_applicant,
    setup_complaint,
    setup_drafted_agreement,
    setup_production,
    setup_published_casting_call,
    validate_paginated,
    validate_success,
)

CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]
WO2 = TEST_USERS["welfare_officer_2_headers"]

HIGH_STRESS = {
    "format_type": "COMPETITION_HIGH_STRESS",
    "jurisdiction_code": "CA",
    "episode_order": 10,
    "stipend_pool_cents": 50_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 2,
}

NEGOTIATED_TERMS = {
    "exclusivity_window_days": 90,
    "confidentiality_tier": "ENHANCED",
    "depiction_rights_scope": "LIMITED",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 250_000,
    "episodes_committed": 6,
    "press_appearance_obligation_count": 2,
    "reunion_obligation": True,
}


def _sent_agreement(api, title, **applicant_overrides):
    production = setup_production(title=title, **HIGH_STRESS)
    call = setup_published_casting_call(
        production["id"], min_age=18, max_age=45, exclusivity_window_days=90
    )
    applicant = setup_cleared_applicant(call["id"], **applicant_overrides)
    agreement = setup_drafted_agreement(
        applicant["id"], production["id"], **NEGOTIATED_TERMS
    )
    sent = validate_success(api.send_agreement(agreement["id"], BA1))
    return production, applicant, sent


class TestNegotiationCycle:
    """SENT -> COUNTERED -> REVISED -> SENT, traversed without bound."""

    def test_two_full_loops_leave_round_number_at_four(self, api):
        """PRD §3.6: "From `REVISED` the agreement is sent again, and the cycle
        `SENT → COUNTERED → REVISED → SENT` may repeat without any bound on the
        number of rounds."
        PRD §3.6: "A negotiation round is appended against the `agreement_id` of
        the agreement under negotiation, recording `proposed_by` as
        `PARTICIPANT`, `disposition` as `COUNTERED`, `proposer_user_id` as the
        caller's `X-User-ID`, `recorded_at` at the logical clock, and
        `round_number` as one more than the agreement's current round count; the
        agreement's own `round_number` is incremented by one, its `status`
        becomes `COUNTERED`, and its `version` is incremented by one."
        PRD §3.6: "Sending never changes `round_number`."

        Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycle_two_full_loops
        """
        _production, applicant, sent = _sent_agreement(
            api, "Island Trials S4", legal_name="Jo Meade", date_of_birth="1991-02-17"
        )
        participant = make_applicant_headers(applicant["id"])
        assert_money(sent["provisional_stipend_cents"], 3_945_000, "first provisional")

        first_version = get_agreement(sent["id"])["version"]
        countered = validate_success(
            api.counter_offer_agreement(
                sent["id"],
                {
                    "requested_base_stipend_cents": 280_000,
                    "requested_exclusivity_window_days": 60,
                    "requested_depiction_rights_scope": "PSEUDONYMIZED",
                    "expected_agreement_version": first_version,
                },
                participant,
            )
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 1

        revised = validate_success(
            api.revise_agreement(
                sent["id"],
                {
                    "base_stipend_cents": 260_000,
                    "exclusivity_window_days": 60,
                    "depiction_rights_scope": "LIMITED",
                },
                BA1,
            )
        )
        assert revised["status"] == "REVISED"
        assert revised["round_number"] == 2

        validate_success(api.send_agreement(sent["id"], BA1))
        second_version = get_agreement(sent["id"])["version"]
        assert second_version > first_version, (
            "each negotiation write increments the agreement's version"
        )

        validate_success(
            api.counter_offer_agreement(
                sent["id"],
                {
                    "requested_base_stipend_cents": 320_000,
                    "requested_exclusivity_window_days": 120,
                    "requested_depiction_rights_scope": "FULL",
                    "expected_agreement_version": second_version,
                },
                participant,
            )
        )
        validate_success(
            api.revise_agreement(
                sent["id"],
                {
                    "base_stipend_cents": 300_000,
                    "exclusivity_window_days": 120,
                    "depiction_rights_scope": "FULL",
                },
                BA1,
            )
        )
        final = validate_success(api.send_agreement(sent["id"], BA1))

        assert final["status"] == "SENT"
        assert final["round_number"] == 4
        assert final["base_stipend_cents"] == 300_000
        assert final["exclusivity_window_days"] == 120
        assert final["depiction_rights_scope"] == "FULL"
        # 300,000 x 10 episodes x 1.30 = 3,900,000 base, 390,000 hazard, four
        # 30-day exclusivity blocks 160,000, four press appearances 100,000 and
        # the unconditional reunion 150,000.
        assert_money(
            final["provisional_stipend_cents"], 4_700_000, "second provisional"
        )

        rounds, meta = validate_paginated(
            api.list_negotiation_rounds(sent["id"], BA1)
        )
        assert meta["total_count"] == 4
        for row in rounds:
            assert_negotiation_round(row)
        assert [row["round_number"] for row in rounds] == [1, 2, 3, 4]
        assert [row["disposition"] for row in rounds] == [
            "COUNTERED",
            "REVISED",
            "COUNTERED",
            "REVISED",
        ]
        assert [row["proposed_by"] for row in rounds] == [
            "PARTICIPANT",
            "PRODUCTION",
            "PARTICIPANT",
            "PRODUCTION",
        ]

    def test_resend_recomputes_the_provisional_from_the_revised_terms(self, api):
        """PRD §3.6: "On success the provisional stipend variant is written to
        `provisional_stipend_cents` — recomputed from the revised terms when the
        send follows a revision — and the status becomes `SENT`."
        PRD §3.6: "Note what the cycle implies for the stipend computation:
        negotiation history is never re-read, because each revision has already
        overwritten the agreement's own term fields, and those current fields are
        the sole authority."

        Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycle_two_full_loops
        """
        _production, applicant, sent = _sent_agreement(
            api, "Island Trials Loop", legal_name="Ira Vance", date_of_birth="1990-07-21"
        )
        participant = make_applicant_headers(applicant["id"])

        validate_success(
            api.counter_offer_agreement(
                sent["id"],
                {
                    "requested_base_stipend_cents": 280_000,
                    "requested_exclusivity_window_days": 60,
                    "requested_depiction_rights_scope": "PSEUDONYMIZED",
                    "expected_agreement_version": sent["version"],
                },
                participant,
            )
        )
        revised = validate_success(
            api.revise_agreement(
                sent["id"],
                {
                    "base_stipend_cents": 260_000,
                    "exclusivity_window_days": 60,
                    "depiction_rights_scope": "LIMITED",
                },
                BA1,
            )
        )
        assert revised["round_number"] == 2

        resent = validate_success(api.send_agreement(sent["id"], BA1))
        assert resent["status"] == "SENT"
        assert resent["round_number"] == 2, "sending never changes round_number"
        # Revised terms only: 260,000 x 10 x 1.30 = 3,380,000 base, 338,000
        # hazard, two exclusivity blocks 80,000, four press appearances 100,000,
        # unconditional reunion 150,000.
        assert_money(
            resent["provisional_stipend_cents"], 4_048_000, "recomputed provisional"
        )


class TestApplicantParallelDimensions:
    """Screening and medical clearance advance independently on one row."""

    def test_medical_clears_while_screening_only_reaches_screening(self, api):
        """PRD §3.4: "Medical clearance runs on its own dimension and neither
        gates nor is gated by the screening dimension — only the agreement send
        gate reads both together."
        PRD §3.4: "Recording a `MEDICAL_EXAM` item with outcome `PASS` moves
        `medical_status` to `CLEARED` from any of `NOT_STARTED`, `PENDING`,
        `DEFERRED` or `EXPIRED`, and stamps that item's `expires_at` 30 days
        after its `recorded_at`."
        PRD §3.4: "Opening any screening item while the applicant's
        `screening_status` is `SUBMITTED` or `SCREENING` advances that dimension
        `SUBMITTED → SCREENING` and refreshes the provisional risk figure."

        Design: Difficulty/non_linear_state_machine/applicant_parallel_dimensions_medical_advances_alone
        """
        production = setup_production(title="Island Trials S5", **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=90
        )
        applicant = setup_applicant(
            call["id"], legal_name="Kai Bhatt", date_of_birth="1996-06-30"
        )
        assert applicant["screening_status"] == "SUBMITTED"
        assert applicant["medical_status"] == "NOT_STARTED"

        record_screening_items(applicant["id"], [("MEDICAL_EXAM", "PASS", 0, CO1)])
        after_medical = get_applicant(applicant["id"])
        assert after_medical["screening_status"] == "SCREENING"
        assert after_medical["medical_status"] == "CLEARED"
        assert_score(
            after_medical["provisional_risk_score"], 0.00, "provisional risk score"
        )

        # An interview opened without an outcome is charged at the ceiling of
        # 5 flags x weight 1.5 x factor 1, and touches neither dimension.
        record_screening_items(applicant["id"], [("INTERVIEW", None, 0, CO1)])
        after_pending = get_applicant(applicant["id"])
        assert after_pending["screening_status"] == "SCREENING"
        assert after_pending["medical_status"] == "CLEARED"
        assert_score(
            after_pending["provisional_risk_score"], 7.50, "provisional risk score"
        )
        assert_score(
            after_pending["final_risk_score"],
            0.00,
            "final risk score with required kinds still unrecorded",
        )
        assert after_pending["psych_eval_required"] is True

    def test_conditional_medical_defers_that_dimension_alone(self, api):
        """PRD §3.4: "Recording a `MEDICAL_EXAM` item with outcome `CONDITIONAL`
        moves `medical_status` to `DEFERRED` from either `NOT_STARTED` or
        `PENDING`, and a deferred applicant cannot have an agreement sent to them
        until a passing exam is recorded."
        PRD §3.4: "A recorded item's points are its `severity_flags` multiplied
        by its kind weight multiplied by its outcome factor, so a passing item
        contributes nothing however many flags it carries."

        Design: Difficulty/non_linear_state_machine/applicant_parallel_dimensions_medical_advances_alone
        """
        production = setup_production(title="Island Trials Deferred", **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=90
        )
        applicant = setup_applicant(
            call["id"], legal_name="Nia Duarte", date_of_birth="1995-05-05"
        )

        record_screening_items(
            applicant["id"], [("MEDICAL_EXAM", "CONDITIONAL", 2, CO1)]
        )
        deferred = get_applicant(applicant["id"])
        assert deferred["medical_status"] == "DEFERRED"
        assert deferred["screening_status"] == "SCREENING", (
            "the screening dimension advances only to SCREENING"
        )
        # 2 flags x weight 2.0 x CONDITIONAL factor one half.
        assert_score(deferred["provisional_risk_score"], 2.00, "provisional risk score")

        record_screening_items(applicant["id"], [("MEDICAL_EXAM", "PASS", 0, CO1)])
        cleared = get_applicant(applicant["id"])
        assert cleared["medical_status"] == "CLEARED"
        assert cleared["screening_status"] == "SCREENING"


class TestComplaintForkJoin:
    """The aftercare branch and the escalation branch diverge sharply, then join
    at resolution without the escalation being undone."""

    def _executed_agreement(self, api, title):
        production = setup_production(title=title, **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=0
        )
        applicant = setup_cleared_applicant(
            call["id"], legal_name="Lena Poe", date_of_birth="1990-10-10"
        )
        agreement = setup_drafted_agreement(
            applicant["id"],
            production["id"],
            exclusivity_window_days=0,
            confidentiality_tier="STANDARD",
            depiction_rights_scope="FULL",
            stipend_structure="FLAT",
            base_stipend_cents=100_000,
            episodes_committed=2,
            press_appearance_obligation_count=0,
            reunion_obligation=False,
        )
        validate_success(api.send_agreement(agreement["id"], BA1))
        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 220_000, "executed stipend"
        )
        return production, applicant, executed

    def test_aftercare_branch_is_quiet_and_escalation_branch_escalates(self, api):
        """PRD §3.9: "The aftercare branch is the quiet one. It moves the
        complaint `TRIAGED → AFTERCARE_ACTIVE`, stamps `routed_by_user_id`,
        writes `aftercare_sessions_authorized` from the pre-transition tier,
        leaves `duty_of_care_breach` false, and mutates no field on the
        production whatsoever."
        PRD §3.9: "The escalation branch moves the complaint `TRIAGED →
        ESCALATED`, stamps `routed_by_user_id`, writes
        `aftercare_sessions_authorized` from the pre-escalation tier, and derives
        `duty_of_care_breach` as true exactly when the complaint's `category` is
        `WELFARE` or `HARASSMENT` **and** its `severity` is 4 or more."
        PRD §3.9: "Resolution is deliberately not a reversal:
        `welfare_incident_count` is never decremented, and `duty_of_care_tier`
        never steps back down, so a production that has sustained an escalated
        breach keeps its escalated tier — and therefore its higher welfare
        surcharge — for the remainder of the season."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_branch_side_effects_diverge
        """
        production, applicant, agreement = self._executed_agreement(
            api, "Island Trials S6"
        )
        quiet = setup_complaint(
            agreement["id"],
            applicant["id"],
            category="MISREPRESENTATION",
            severity=3,
            narrative="Edit implied a storyline that never happened.",
        )
        loud = setup_complaint(
            agreement["id"],
            applicant["id"],
            category="WELFARE",
            severity=4,
            narrative="No welfare officer present during the 3am challenge.",
        )
        validate_success(api.triage_complaint(quiet["id"], WO1))
        validate_success(api.triage_complaint(loud["id"], WO1))

        # Severity 3 authorises 8 base sessions, scaled by the ENHANCED tier
        # factor of one and a half.
        routed_quiet = validate_success(
            api.route_complaint(quiet["id"], {"route": "AFTERCARE"}, WO2)
        )
        assert routed_quiet["status"] == "AFTERCARE_ACTIVE"
        assert routed_quiet["duty_of_care_breach"] is False
        assert routed_quiet["aftercare_sessions_authorized"] == 12

        after_quiet = get_production(production["id"])
        assert after_quiet["duty_of_care_tier"] == "ENHANCED"
        assert after_quiet["welfare_incident_count"] == 0

        # Severity 4 authorises 12 base sessions, still read against the
        # pre-escalation ENHANCED tier, giving 18.
        routed_loud = validate_success(
            api.route_complaint(loud["id"], {"route": "ESCALATION"}, WO2)
        )
        assert routed_loud["status"] == "ESCALATED"
        assert routed_loud["duty_of_care_breach"] is True
        assert routed_loud["aftercare_sessions_authorized"] == 18

        after_loud = get_production(production["id"])
        assert after_loud["duty_of_care_tier"] == "CRITICAL"
        assert after_loud["welfare_incident_count"] == 1

        resolved_quiet = validate_success(
            api.resolve_complaint(
                quiet["id"], {"resolution_note": "Aftercare programme completed."}, WO1
            )
        )
        resolved_loud = validate_success(
            api.resolve_complaint(
                loud["id"],
                {"resolution_note": "Escalation closed with corrective action plan."},
                WO1,
            )
        )
        assert resolved_quiet["status"] == "RESOLVED"
        assert resolved_loud["status"] == "RESOLVED"

        final = get_production(production["id"])
        assert final["duty_of_care_tier"] == "CRITICAL"
        assert final["welfare_incident_count"] == 1
        assert_money(final["welfare_committed_cents"], 0, "committed welfare")
        assert final["casting_posture"] == "OPEN"

    def test_escalation_without_a_breach_stops_after_the_first_link(self, api):
        """PRD §3.9: "An escalation that is *not* a duty-of-care breach stops
        after the first link: the complaint is `ESCALATED`, sessions are
        authorised, and nothing on the production changes."
        PRD §3.9: "The base session count is 2 sessions at severity 1, 4 at
        severity 2, 8 at severity 3, 12 at severity 4 and 16 at severity 5."
        PRD §3.9: "The authorised figure is then the smaller of that rounded
        number and a hard ceiling of 24 sessions."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_branch_side_effects_diverge
        """
        production, applicant, agreement = self._executed_agreement(
            api, "Island Trials Payment"
        )
        complaint = setup_complaint(
            agreement["id"],
            applicant["id"],
            category="PAYMENT",
            severity=5,
            narrative="Two stipend installments were never paid after wrap.",
        )
        validate_success(api.triage_complaint(complaint["id"], WO1))

        # 16 base sessions at the ENHANCED tier factor is 24, exactly the cap.
        routed = validate_success(
            api.route_complaint(complaint["id"], {"route": "ESCALATION"}, WO2)
        )
        assert routed["status"] == "ESCALATED"
        assert routed["duty_of_care_breach"] is False, (
            "a PAYMENT complaint is not a duty-of-care breach at any severity"
        )
        assert routed["aftercare_sessions_authorized"] == 24

        unchanged = get_production(production["id"])
        assert unchanged["duty_of_care_tier"] == "ENHANCED"
        assert unchanged["welfare_incident_count"] == 0
        assert unchanged["casting_posture"] == "OPEN"
