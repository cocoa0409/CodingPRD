"""Chains where one write propagates through three, four or five further
records.  Each chain is paired with a control run that severs one link, so that
the later links are shown to be caused by the earlier ones rather than merely
co-occurring with the trigger.
"""

from test_helpers import (
    TEST_USERS,
    NO_PSYCH_SCREENING,
    assert_money,
    get_agreement,
    get_production,
    get_shoot_block,
    setup_cleared_applicant,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_executed_agreement,
    setup_location,
    setup_open_call,
    setup_applicant,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_shoot_block,
    setup_triaged_complaint,
    validate_paginated,
    validate_success,
)

CD = TEST_USERS["casting_director_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]
WO2 = TEST_USERS["welfare_officer_2_headers"]

# A four-episode DOCUSOAP with a pool small enough that a single agreement can
# drive utilisation to exactly ninety percent.
HARBOUR_LIVES = {
    "format_type": "DOCUSOAP",
    "jurisdiction_code": "CA",
    "season_number": 1,
    "episode_order": 4,
    "stipend_pool_cents": 10_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 0,
}

ISLAND_TRIALS_S7 = {
    "format_type": "COMPETITION_HIGH_STRESS",
    "jurisdiction_code": "CA",
    "season_number": 7,
    "episode_order": 10,
    "stipend_pool_cents": 50_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 1,
}

SEASON_COVERAGE = {
    "coverage_start_utc": "2026-09-15T00:00:00Z",
    "coverage_end_utc": "2026-12-15T00:00:00Z",
}


class TestExecuteRollupPostureCascade:
    """Executing one agreement writes the final stipend, which rewrites the
    production rollup, which re-derives the posture, which closes open calls."""

    def _staged_production(self, title):
        """A DOCUSOAP production carrying one OPEN_CALL and one REFERRAL call,
        plus one cleared adult recruited through the REFERRAL call."""
        production = setup_docusoap_production(title=title, **HARBOUR_LIVES)
        venue = setup_location(
            name="Venue B", capacity=500, filming_permit_number="PRM-2002"
        )
        open_call = setup_open_call(
            production["id"],
            venue["id"],
            min_age=18,
            max_age=60,
            exclusivity_window_days=30,
            open_call_window_start_utc="2026-08-05T00:00:00Z",
            open_call_window_end_utc="2026-08-15T00:00:00Z",
            expected_attendance=300,
        )
        referral_call = setup_published_casting_call(
            production["id"], min_age=18, max_age=60, exclusivity_window_days=0
        )
        applicant = setup_cleared_applicant(
            referral_call["id"],
            items=NO_PSYCH_SCREENING,
            legal_name="Eva Stone",
            date_of_birth="1990-03-11",
        )
        assert applicant["psych_eval_required"] is False, (
            "a DOCUSOAP production does not demand a psych evaluation"
        )
        return production, open_call, referral_call, applicant

    def test_execution_at_exactly_ninety_percent_closes_only_the_open_call(self, api):
        """PRD §3.6: "The execution cascade then runs in a fixed order. First,
        the final stipend variant is written to
        `total_stipend_commitment_cents`, the status becomes `EXECUTED`,
        `executed_by_user_id` is stamped with the caller's `X-User-ID`,
        `executed_at` is stamped with the logical clock, and the applicant's
        `screening_status` moves to `CAST`. Second, because the final commitment
        was written, the production's `stipend_committed_cents` is recomputed by
        full re-summation over executed agreements and its
        `minor_participant_count` is recomputed as the count of executed
        agreements whose applicant is a minor. Third, because committed stipend
        changed, the production's `casting_posture` is re-derived and may become
        `RESTRICTED`. Fourth, if the posture did become `RESTRICTED`, every
        casting call of that production that is `PUBLISHED` with channel
        `OPEN_CALL` moves to `CLOSED` with `closed_reason`
        `POSTURE_RESTRICTED`."
        PRD §2.7: "Retrospectively it cascades: the moment a production's
        posture becomes `RESTRICTED`, every casting call of that production that
        is `PUBLISHED` **and** whose `channel` is `OPEN_CALL` moves to `CLOSED`
        with `closed_reason` set to `POSTURE_RESTRICTED`, its `version`
        incremented by one; calls on the `DIGITAL_SUBMISSION` and `REFERRAL`
        channels are left `PUBLISHED`."

        Design: Difficulty/transitive_cascade/execute_rollup_restricts_posture_closes_open_calls_depth4
        """
        production, open_call, referral_call, applicant = self._staged_production(
            "Harbour Lives S1"
        )
        agreement = setup_drafted_agreement(
            applicant["id"],
            production["id"],
            exclusivity_window_days=0,
            confidentiality_tier="STANDARD",
            depiction_rights_scope="FULL",
            stipend_structure="PER_EPISODE",
            base_stipend_cents=2_250_000,
            episodes_committed=4,
            press_appearance_obligation_count=0,
            reunion_obligation=False,
        )

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        # Episode count max(4, 4) = 4 keeps the tier multiplier at 1.00, so the
        # provisional figure is the 9,000,000 base plus the two-appearance press
        # reserve and the unconditional reunion charge.
        assert_money(sent["provisional_stipend_cents"], 9_200_000, "provisional stipend")

        # Link 1: the final variant lands on the agreement.
        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 9_000_000, "final stipend"
        )
        assert executed["status"] == "EXECUTED"
        assert validate_success(api.get_applicant(applicant["id"], BA1))[
            "screening_status"
        ] == "CAST"

        # Links 2 and 3: the rollup is re-summed and the posture re-derived at
        # exactly ninety percent utilisation.
        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 9_000_000, "committed stipend"
        )
        assert rolled_up["casting_posture"] == "RESTRICTED", (
            "9,000,000 against a 10,000,000 pool is exactly ninety percent, and "
            "the utilisation clause fires at or above ninety percent"
        )

        # Link 4: the OPEN_CALL call closes, and only that one.
        closed = validate_success(api.get_casting_call(open_call["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "POSTURE_RESTRICTED"
        untouched = validate_success(api.get_casting_call(referral_call["id"], CD))
        assert untouched["status"] == "PUBLISHED", (
            "a REFERRAL call is outside the RESTRICTED cascade"
        )
        assert untouched["closed_reason"] is None

        rows, meta = validate_paginated(
            api.list_post_obligations(agreement["id"], BA1)
        )
        assert meta["total_count"] == 0, (
            "no press appearances and no reunion means no obligations are created"
        )
        assert rows == []

    def test_an_execution_that_stays_below_the_threshold_leaves_the_open_call_live(
        self, api
    ):
        """PRD §2.7: "The utilisation test is performed by integer
        cross-multiplication: `stipend_committed_cents` multiplied by 100 is
        compared against `stipend_pool_cents` multiplied by 90, and the posture
        restricts when the former is greater than or equal to the latter."
        PRD §2.7: "Exactly ninety percent restricts; anything below it, however
        narrowly, does not."
        PRD §3.6: "Fourth, if the posture did become `RESTRICTED`, every casting
        call of that production that is `PUBLISHED` with channel `OPEN_CALL`
        moves to `CLOSED` with `closed_reason` `POSTURE_RESTRICTED`."
        PRD §3.9: "For each ordinal from 1 up to
        `press_appearance_obligation_count`, a press obligation is created with
        `kind` `PRESS_JUNKET`, its `sequence_ordinal` set to that ordinal, its
        `fee_cents` set to the press appearance rate of 25,000 cents, and its
        `due_utc` set to the production's `photography_end_utc` advanced by 30
        days multiplied by the ordinal — so the first junket falls 30 days after
        wrap, the second 60 days after, the third 90 days after, and so on."
        PRD §3.9: "Then, and only when `reunion_obligation` is true, a single
        reunion obligation is created with `kind` `REUNION_TAPING`,
        `sequence_ordinal` 1, `fee_cents` of 150,000 cents, and `due_utc` set to
        `photography_end_utc` advanced by 180 days."

        Design: Difficulty/transitive_cascade/execute_rollup_restricts_posture_closes_open_calls_depth4
        """
        production, open_call, _referral, applicant = self._staged_production(
            "Harbour Lives Control"
        )
        agreement = setup_drafted_agreement(
            applicant["id"],
            production["id"],
            exclusivity_window_days=0,
            confidentiality_tier="STANDARD",
            depiction_rights_scope="FULL",
            stipend_structure="PER_EPISODE",
            base_stipend_cents=2_000_000,
            episodes_committed=4,
            press_appearance_obligation_count=2,
            reunion_obligation=True,
        )
        validate_success(api.send_agreement(agreement["id"], BA1))
        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        # 8,000,000 base plus two contracted junkets and one reunion.
        assert_money(
            executed["total_stipend_commitment_cents"], 8_200_000, "final stipend"
        )

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 8_200_000, "committed stipend"
        )
        # 8,200,000 * 100 is 820,000,000, short of 10,000,000 * 90.
        assert rolled_up["casting_posture"] == "OPEN"

        still_live = validate_success(api.get_casting_call(open_call["id"], CD))
        assert still_live["status"] == "PUBLISHED", (
            "the fourth link is conditional on the third: no RESTRICTED posture, "
            "no closure"
        )
        assert still_live["closed_reason"] is None

        # The obligation fan-out runs alongside the four links, not inside them.
        rows, meta = validate_paginated(
            api.list_post_obligations(agreement["id"], BA1)
        )
        assert meta["total_count"] == 3
        assert [row["kind"] for row in rows] == [
            "PRESS_JUNKET",
            "PRESS_JUNKET",
            "REUNION_TAPING",
        ]
        assert [row["sequence_ordinal"] for row in rows] == [1, 2, 1]
        assert_money(rows[0]["fee_cents"], 25_000, "first junket fee")
        assert_money(rows[1]["fee_cents"], 25_000, "second junket fee")
        assert_money(rows[2]["fee_cents"], 150_000, "reunion fee")
        assert rows[0]["due_utc"].startswith("2027-01-14")
        assert rows[1]["due_utc"].startswith("2027-02-13")
        assert rows[2]["due_utc"].startswith("2027-06-13")


class TestEscalationFreezeCascade:
    """A routed escalation counts an incident, escalates the tier, re-prices the
    welfare commitment, and only then — if the budget is breached — freezes the
    production and sweeps its live records."""

    def _staged_production(self, title, protocol_costs):
        """One high-stress production with planned protocols, a live call, an
        executed agreement, a drafted agreement, a scheduled block and a
        triaged severity-four welfare complaint."""
        production = setup_production(title=title, **ISLAND_TRIALS_S7)
        assert production["duty_of_care_tier"] == "ENHANCED"
        stage = setup_location(
            name="Stage A", capacity=500, filming_permit_number="PRM-1001"
        )
        setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=protocol_costs["DUTY_OF_CARE_OFFICER"],
            **SEASON_COVERAGE,
        )
        setup_planned_welfare_protocol(
            production["id"],
            kind="ONSET_PSYCH_SUPPORT",
            cost_cents=protocol_costs["ONSET_PSYCH_SUPPORT"],
            **SEASON_COVERAGE,
        )
        if "AFTERCARE_PROGRAM" in protocol_costs:
            setup_planned_welfare_protocol(
                production["id"],
                kind="AFTERCARE_PROGRAM",
                cost_cents=protocol_costs["AFTERCARE_PROGRAM"],
                coverage_start_utc="2026-09-15T00:00:00Z",
                coverage_end_utc="2027-06-30T00:00:00Z",
            )

        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=0
        )
        finn = setup_cleared_applicant(
            call["id"], legal_name="Finn Adler", date_of_birth="1992-07-07"
        )
        finn_agreement = setup_executed_agreement(finn["id"], production["id"])
        assert_money(
            finn_agreement["total_stipend_commitment_cents"],
            220_000,
            "Finn's final stipend",
        )

        # Gus is deliberately left unscreened; drafting does not require it.
        gus = setup_applicant(
            call["id"], legal_name="Gus Ivey", date_of_birth="1995-01-15"
        )
        gus_agreement = setup_drafted_agreement(gus["id"], production["id"])
        assert gus_agreement["status"] == "DRAFTED"
        assert gus_agreement["welfare_hold"] is False

        block = setup_shoot_block(
            production["id"],
            stage["id"],
            block_kind="STUDIO",
            start_utc="2026-10-20T08:00:00Z",
            end_utc="2026-10-20T12:00:00Z",
            participant_agreement_ids=[finn_agreement["id"]],
            expected_crowd_headcount=0,
            onset_minor_hours=0,
        )
        assert block["status"] == "SCHEDULED"

        complaint = setup_triaged_complaint(
            finn_agreement["id"],
            finn["id"],
            headers=WO1,
            category="WELFARE",
            severity=4,
            narrative=(
                "Duty-of-care officer absent for the overnight isolation challenge."
            ),
        )
        assert complaint["status"] == "TRIAGED"
        return {
            "production": production,
            "casting_call": call,
            "executed_agreement": finn_agreement,
            "drafted_agreement": gus_agreement,
            "shoot_block": block,
            "complaint": complaint,
        }

    def test_escalation_that_breaches_the_budget_freezes_and_sweeps_everything(
        self, api
    ):
        """PRD §3.9: "Because the escalation is a duty-of-care breach, the
        production's `welfare_incident_count` is incremented and its
        `duty_of_care_tier` escalates one level, `STANDARD` to `ENHANCED` or
        `ENHANCED` to `CRITICAL`, capped at `CRITICAL`. Because the tier
        changed, the production's `welfare_committed_cents` is recomputed with
        the higher tier factor. Because the recomputed commitment can now exceed
        `welfare_budget_cents`, the posture derivation may set `casting_posture`
        to `FROZEN` — and note that a second breach alone freezes the production
        regardless of budget, since the incident-count clause fires at 2."
        PRD §3.9: "Because the posture became `FROZEN`, every `PUBLISHED`
        casting call of the production moves to `CLOSED` with `closed_reason`
        `POSTURE_FROZEN`, every `SCHEDULED` shoot block moves to `CANCELLED`,
        and every participant agreement in `DRAFTED`, `SENT`, `COUNTERED` or
        `REVISED` status has `welfare_hold` set to true."
        PRD §3.9: "The escalation branch moves the complaint `TRIAGED →
        ESCALATED`, stamps `routed_by_user_id`, writes
        `aftercare_sessions_authorized` from the pre-escalation tier, and
        derives `duty_of_care_breach` as true exactly when the complaint's
        `category` is `WELFARE` or `HARASSMENT` **and** its `severity` is 4 or
        more."

        Design: Difficulty/transitive_cascade/complaint_escalation_freezes_production_and_cancels_blocks_depth5
        """
        staged = self._staged_production(
            "Island Trials S7",
            {
                "DUTY_OF_CARE_OFFICER": 4_000_000,
                "ONSET_PSYCH_SUPPORT": 3_000_000,
                "AFTERCARE_PROGRAM": 2_000_000,
            },
        )
        production_id = staged["production"]["id"]

        before = get_production(production_id)
        # A 9,000,000 subtotal takes the 0.07 band and the ENHANCED factor of
        # one and a half, giving a 945,000 surcharge that still fits the budget.
        assert_money(
            before["welfare_committed_cents"], 9_945_000, "committed welfare"
        )
        assert before["casting_posture"] == "OPEN"
        assert before["welfare_incident_count"] == 0

        routed = validate_success(
            api.route_complaint(staged["complaint"]["id"], {"route": "ESCALATION"}, WO2)
        )
        # Links 1 and 2 on the complaint itself.
        assert routed["status"] == "ESCALATED"
        assert routed["duty_of_care_breach"] is True
        # Severity 4 authorises 12 sessions, scaled by the pre-escalation
        # ENHANCED factor of one and a half.
        assert routed["aftercare_sessions_authorized"] == 18

        after = get_production(production_id)
        assert after["welfare_incident_count"] == 1
        assert after["duty_of_care_tier"] == "CRITICAL"
        # Link 3: the same 9,000,000 subtotal and 0.07 band, now at the CRITICAL
        # factor of two, giving a 1,260,000 surcharge.
        assert_money(
            after["welfare_committed_cents"], 10_260_000, "committed welfare"
        )
        # Link 4: the commitment now exceeds the 10,000,000 budget.
        assert after["casting_posture"] == "FROZEN"

        # Link 5, three separate sweeps.
        closed = validate_success(api.get_casting_call(staged["casting_call"]["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "POSTURE_FROZEN"
        cancelled = get_shoot_block(staged["shoot_block"]["id"])
        assert cancelled["status"] == "CANCELLED"
        held = get_agreement(staged["drafted_agreement"]["id"])
        assert held["welfare_hold"] is True, (
            "a DRAFTED agreement is inside the freeze sweep"
        )
        unheld = get_agreement(staged["executed_agreement"]["id"])
        assert unheld["welfare_hold"] is False, (
            "the sweep names DRAFTED, SENT, COUNTERED and REVISED only"
        )
        assert_money(
            after["stipend_committed_cents"], 220_000, "committed stipend"
        )

    def test_the_same_escalation_under_budget_escalates_the_tier_and_nothing_else(
        self, api
    ):
        """PRD §3.7: "Step three multiplies the subtotal by that band rate and
        again by the tier factor for the production's current
        `duty_of_care_tier` — one for `STANDARD`, one and a half for
        `ENHANCED`, two for `CRITICAL` — rounding the product half up to whole
        cents to give the duty-of-care surcharge."
        PRD §2.7: "The posture is `FROZEN` when `welfare_committed_cents` is
        strictly greater than `welfare_budget_cents`, or when
        `welfare_incident_count` has reached 2 or more."
        PRD §3.9: "Resolution is deliberately not a reversal:
        `welfare_incident_count` is never decremented, and `duty_of_care_tier`
        never steps back down, so a production that has sustained an escalated
        breach keeps its escalated tier — and therefore its higher welfare
        surcharge — for the remainder of the season."

        Design: Difficulty/transitive_cascade/complaint_escalation_freezes_production_and_cancels_blocks_depth5
        """
        staged = self._staged_production(
            "Island Trials Under Budget",
            {"DUTY_OF_CARE_OFFICER": 4_000_000, "ONSET_PSYCH_SUPPORT": 3_000_000},
        )
        production_id = staged["production"]["id"]

        before = get_production(production_id)
        # A 7,000,000 subtotal still takes the 0.07 band; the ENHANCED factor
        # gives a 735,000 surcharge.
        assert_money(
            before["welfare_committed_cents"], 7_735_000, "committed welfare"
        )
        assert before["casting_posture"] == "OPEN"

        routed = validate_success(
            api.route_complaint(staged["complaint"]["id"], {"route": "ESCALATION"}, WO2)
        )
        assert routed["duty_of_care_breach"] is True
        assert routed["aftercare_sessions_authorized"] == 18

        after = get_production(production_id)
        # Links 1 to 3 fire exactly as before.
        assert after["welfare_incident_count"] == 1
        assert after["duty_of_care_tier"] == "CRITICAL"
        assert_money(
            after["welfare_committed_cents"], 7_980_000, "committed welfare"
        )
        # Link 4 does not: one incident is below the count clause and 7,980,000
        # does not exceed the 10,000,000 budget.
        assert after["casting_posture"] == "OPEN"

        # And therefore link 5 does not fire either.
        assert validate_success(
            api.get_casting_call(staged["casting_call"]["id"], CD)
        )["status"] == "PUBLISHED"
        assert get_shoot_block(staged["shoot_block"]["id"])["status"] == "SCHEDULED"
        assert get_agreement(staged["drafted_agreement"]["id"])["welfare_hold"] is False
