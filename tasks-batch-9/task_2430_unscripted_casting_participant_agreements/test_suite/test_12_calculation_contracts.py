"""Derived figures read one formula at a time: which rows enter a rollup and
which are filtered out, which constants and tier factors are applied, where a
tier boundary sits, how a tie on the half cent is broken, how the decay ladder
weights an ordered history, which variant a transition writes, and which clause
of a pinned precedence wins when two of them hold at once.
"""

from test_helpers import (
    FULL_PASS_SCREENING,
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    assert_score,
    collect_release,
    create_screening_item_payload,
    get_agreement,
    get_applicant,
    get_production,
    get_shoot_block,
    record_screening_items,
    route_payload,
    run_welfare_epoch,
    set_clock,
    setup_active_welfare_protocol,
    setup_applicant,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_executed_agreement,
    setup_minor_applicant,
    setup_minor_protection,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_sent_agreement,
    setup_shoot_block,
    setup_triaged_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]
WO2 = TEST_USERS["welfare_officer_2_headers"]

# A coverage span wide enough to hold the whole photography window.
WIDE_COVERAGE = {
    "coverage_start_utc": "2026-09-01T00:00:00Z",
    "coverage_end_utc": "2026-12-31T00:00:00Z",
}

# A two-episode per-episode deal at a 100,000-cent episode rate, with no
# exclusivity, no press and no reunion beyond what a test adds.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

# A venue registered without a municipal filming permit, so it may host studio
# work only.
PIER_NINE_STAGE = {
    "name": "Pier 9 Stage",
    "state_code": "GA",
    "capacity": 400,
    "turnaround_buffer_minutes": 60,
}


def _harbour_nights(**overrides):
    """A nine-episode DOCUSOAP in GA: STANDARD tier, no hazard uplift."""
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


def _island_trials(**overrides):
    """A nine-episode COMPETITION_HIGH_STRESS show in CA: ENHANCED tier."""
    return setup_production(
        title="Island Trials S2", season_number=2, episode_order=9, **overrides
    )


def _referral_call(production_id, **overrides):
    kwargs = {
        "channel": "REFERRAL",
        "min_age": 13,
        "max_age": 60,
        "exclusivity_window_days": 0,
    }
    kwargs.update(overrides)
    return setup_published_casting_call(production_id, **kwargs)


def _adult_on(call_id, legal_name, date_of_birth, state_code="GA", items=None):
    applicant = setup_applicant(
        call_id,
        legal_name=legal_name,
        date_of_birth=date_of_birth,
        residency_state_code=state_code,
    )
    record_screening_items(
        applicant["id"], NO_PSYCH_SCREENING if items is None else items
    )
    return applicant


class TestPostObligationLadder:
    """Execution derives every obligation's kind, ordinal, fee and due date from
    the production's wrap date and the agreement's own contracted counts."""

    def test_two_junkets_and_a_reunion_land_thirty_sixty_and_a_hundred_eighty_days_out(
        self, api
    ):
        """PRD §3.9: "For each ordinal from 1 up to
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
        PRD §3.9: "All press rows are created first in ascending ordinal order,
        and the reunion row last."
        PRD §3.9: "Every obligation records the `agreement_id` that owes the
        appearance and opens at `status` `SCHEDULED` with `fulfilled_at` absent."

        Design: Corner/calculations/post_obligation_due_dates_and_fees_derived_from_photography_end
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        applicant = _adult_on(call["id"], "Ada Reyes", "1994-04-02")

        executed = setup_executed_agreement(
            applicant["id"],
            production["id"],
            press_appearance_obligation_count=2,
            reunion_obligation=True,
            **BASE_TERMS,
        )
        # 100,000 x 2 episodes at the 1.00 tier, no hazard on a docusoap, two
        # junkets at 25,000 and a 150,000 reunion.
        assert_money(
            executed["total_stipend_commitment_cents"], 400_000, "final stipend"
        )

        rows, meta = validate_paginated(api.list_post_obligations(executed["id"], BA1))
        assert meta["total_count"] == 3
        assert [row["kind"] for row in rows] == [
            "PRESS_JUNKET",
            "PRESS_JUNKET",
            "REUNION_TAPING",
        ]
        # Ordinals are per kind, so the reunion row restarts at 1.
        assert [row["sequence_ordinal"] for row in rows] == [1, 2, 1]
        # Photography ends 2026-12-15: +30, +60 and +180 days.
        assert rows[0]["due_utc"].startswith("2027-01-14T00:00:00")
        assert rows[1]["due_utc"].startswith("2027-02-13T00:00:00")
        assert rows[2]["due_utc"].startswith("2027-06-13T00:00:00")
        assert_money(rows[0]["fee_cents"], 25_000, "first junket fee")
        assert_money(rows[1]["fee_cents"], 25_000, "second junket fee")
        assert_money(rows[2]["fee_cents"], 150_000, "reunion fee")
        assert [row["status"] for row in rows] == ["SCHEDULED"] * 3
        assert all(row["fulfilled_at"] is None for row in rows)
        assert all(row["agreement_id"] == executed["id"] for row in rows)

        assert get_production(production["id"])["breached_obligation_count"] == 0


class TestCommittedStipendInputSet:
    """The committed-stipend rollup sums the final variant over executed rows and
    nothing else, however large a sent row's provisional figure is."""

    def test_a_sent_rows_provisional_figure_never_reaches_the_rollup(self, api):
        """PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."
        PRD §2.11: "Agreements in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED`
        status contribute nothing, and `VOIDED` agreements both fall outside the
        summed set and carry a zeroed `total_stipend_commitment_cents`, so
        voiding is an exact reversal of executing."
        PRD §3.6: "The final variant is the only one that enters the production's
        committed-stipend rollup; the provisional figure never does."

        Design: Corner/calculations/production_stipend_rollup_excludes_non_executed_agreements
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _adult_on(call["id"], "Ada Reyes", "1994-04-02")
        ben = _adult_on(call["id"], "Ben Okafor", "1990-01-10")

        executed = setup_executed_agreement(ada["id"], production["id"], **BASE_TERMS)
        assert_money(
            executed["total_stipend_commitment_cents"], 200_000, "executed final"
        )

        sent = setup_sent_agreement(ben["id"], production["id"], **BASE_TERMS)
        # The provisional variant assumes the full nine-episode season, a
        # two-appearance press reserve and a reunion, so it stands at nearly
        # seven times the executed row's final figure.
        assert_money(sent["provisional_stipend_cents"], 1_370_000, "sent provisional")
        assert_money(sent["total_stipend_commitment_cents"], 0, "sent final")
        assert sent["status"] == "SENT"

        after = get_production(production["id"])
        assert_money(after["stipend_committed_cents"], 200_000, "committed stipend")
        assert after["casting_posture"] == "OPEN"
        assert get_applicant(ada["id"])["screening_status"] == "CAST"
        assert get_applicant(ben["id"])["screening_status"] == "CLEARED"


class TestCommittedWelfareInputSet:
    """Planned and active protocols both count; only the sweep's expiry
    transition takes a row out of the subtotal."""

    def test_activation_moves_nothing_and_only_the_sweep_removes_a_row(self, api):
        """PRD §3.7: "Step one sums `cost_cents` over the production's protocols
        whose `status` is `PLANNED` or `ACTIVE`, excluding both `EXPIRED` and
        `CANCELLED` rows, to give the protocol subtotal; coverage dates play no
        part in membership, only the sweep's expiry transition does."
        PRD §3.7: "Notably, because `PLANNED` and `ACTIVE` rows both count,
        activating a protocol leaves the subtotal unchanged, and because
        cancelled rows drop out, cancelling one removes its cost exactly."
        PRD §3.7: "Every `ACTIVE` welfare protocol whose `coverage_end_utc` is at
        or before the logical clock becomes `EXPIRED`."

        Design: Corner/calculations/welfare_rollup_excludes_expired_protocols_and_counts_planned
        """
        production = _island_trials(minor_participant_cap=2)
        assert production["duty_of_care_tier"] == "ENHANCED"

        long_coverage = setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=3_000_000,
            **WIDE_COVERAGE,
        )
        # 3,000,000 is below the 5,000,000 band floor, so the rate is 0.04, and
        # the ENHANCED factor of 1.5 lifts the surcharge to 180,000.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            3_180_000,
            "committed welfare while planned",
        )

        activated = validate_success(
            api.activate_welfare_protocol(long_coverage["id"], WO1)
        )
        assert activated["status"] == "ACTIVE"
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            3_180_000,
            "committed welfare after activation",
        )

        short_coverage = setup_planned_welfare_protocol(
            production["id"],
            kind="ONSET_PSYCH_SUPPORT",
            cost_cents=1_000_000,
            coverage_start_utc="2026-08-05T00:00:00Z",
            coverage_end_utc="2026-08-20T00:00:00Z",
        )
        validate_success(api.activate_welfare_protocol(short_coverage["id"], WO1))
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            4_240_000,
            "committed welfare with both rows",
        )

        set_clock("2026-09-01T00:00:00Z")
        swept = run_welfare_epoch(production["id"])
        assert_money(
            swept["welfare_committed_cents"], 3_180_000, "committed welfare after sweep"
        )
        assert swept["casting_posture"] == "OPEN"
        # The sweep is idempotent: the expired row is already out of the set.
        again = run_welfare_epoch(production["id"])
        assert_money(
            again["welfare_committed_cents"], 3_180_000, "committed welfare re-swept"
        )

        rows, meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1)
        )
        assert meta["total_count"] == 2
        statuses = {row["id"]: row["status"] for row in rows}
        assert statuses[long_coverage["id"]] == "ACTIVE"
        assert statuses[short_coverage["id"]] == "EXPIRED"


class TestAftercareSessionAuthorisation:
    """Session counts read the severity ladder and the pre-transition tier, and
    the twenty-four-session ceiling is applied after the rounding."""

    def test_the_second_escalation_hits_the_ceiling_without_counting_an_incident(
        self, api
    ):
        """PRD §3.9: "The base session count is 2 sessions at severity 1, 4 at
        severity 2, 8 at severity 3, 12 at severity 4 and 16 at severity 5."
        PRD §3.9: "That base is multiplied by the tier factor — one for
        `STANDARD`, one and a half for `ENHANCED`, two for `CRITICAL` — and the
        product is rounded half up to a whole number of sessions."
        PRD §3.9: "The authorised figure is then the smaller of that rounded
        number and a hard ceiling of 24 sessions."
        PRD §3.9: "The escalation branch moves the complaint `TRIAGED →
        ESCALATED`, stamps `routed_by_user_id`, writes
        `aftercare_sessions_authorized` from the pre-escalation tier, and derives
        `duty_of_care_breach` as true exactly when the complaint's `category` is
        `WELFARE` or `HARASSMENT` **and** its `severity` is 4 or more."
        PRD §3.9: "An escalation that is *not* a duty-of-care breach stops after
        the first link: the complaint is `ESCALATED`, sessions are authorised,
        and nothing on the production changes."

        Design: Corner/calculations/aftercare_sessions_capped_at_twenty_four_under_critical_tier
        """
        production = _island_trials(minor_participant_cap=2)
        call = _referral_call(production["id"], min_age=18)
        applicant = _adult_on(
            call["id"], "Ada Reyes", "1994-04-02", state_code="CA",
            items=FULL_PASS_SCREENING,
        )

        sent = setup_sent_agreement(applicant["id"], production["id"], **BASE_TERMS)
        # A high-stress format carries the tenth-part hazard uplift on the base.
        assert_money(sent["provisional_stipend_cents"], 1_487_000, "provisional")
        executed = validate_success(api.execute_agreement(sent["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 220_000, "final stipend"
        )

        welfare = setup_triaged_complaint(
            executed["id"],
            applicant["id"],
            category="WELFARE",
            severity=4,
            narrative="No welfare officer present during a night shoot.",
        )
        payment = setup_triaged_complaint(
            executed["id"],
            applicant["id"],
            category="PAYMENT",
            severity=5,
            narrative="Stipend has not been paid for any episode.",
        )

        first = validate_success(
            api.route_complaint(welfare["id"], route_payload("ESCALATION"), WO2)
        )
        # Severity 4 gives a base of 12, and the tier is read as ENHANCED
        # because the escalation this very request performs comes afterwards.
        assert first["aftercare_sessions_authorized"] == 18
        assert first["duty_of_care_breach"] is True
        assert first["status"] == "ESCALATED"

        mid = get_production(production["id"])
        assert mid["duty_of_care_tier"] == "CRITICAL"
        assert mid["welfare_incident_count"] == 1
        assert mid["casting_posture"] == "OPEN"

        second = validate_success(
            api.route_complaint(payment["id"], route_payload("ESCALATION"), WO2)
        )
        # Severity 5 gives a base of 16, which the CRITICAL factor doubles to 32
        # before the ceiling cuts it back to 24.
        assert second["aftercare_sessions_authorized"] == 24
        assert second["duty_of_care_breach"] is False

        end = get_production(production["id"])
        assert end["duty_of_care_tier"] == "CRITICAL"
        assert end["welfare_incident_count"] == 1
        assert end["casting_posture"] == "OPEN"
        assert_money(end["welfare_committed_cents"], 0, "committed welfare")


class TestRiskDecayLadder:
    """The decayed variant walks an ordered history down a fixed ladder whose
    tail holds at one half, while the ceiling variant applies no decay at all."""

    def test_the_fifth_recorded_item_is_still_weighted_at_one_half(self, api):
        """PRD §3.4: "Its recorded items are ordered by `recorded_at`
        descending, with ties broken by `created_at` descending, and each item is
        then multiplied by a decay factor determined by its one-based position in
        that ordering: the first item keeps its full points, the second is
        multiplied by eight tenths, the third by six tenths, the fourth by one
        half, and every item from the fifth onward is also multiplied by one
        half."
        PRD §3.4: "The decayed products are summed and the sum is rounded half up
        to two decimal places once."
        PRD §3.4: "The **provisional ceiling** variant is written to
        `provisional_risk_score` on every screening-item write, and it charges
        every item that has not yet been recorded — every item whose
        `recorded_at` is still absent — at the pessimistic ceiling: 5 severity
        flags multiplied by that item's kind weight multiplied by a factor of
        one."
        PRD §3.4: "The **final decayed** variant is written to `final_risk_score`
        only once every required kind has an item whose `recorded_at` is present;
        pending items contribute nothing at all to it."

        Design: Corner/calculations/risk_decay_ladder_weights_the_fifth_item_at_half
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        applicant = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )

        validate_success(
            api.create_screening_item(
                applicant["id"],
                create_screening_item_payload(
                    "INTERVIEW",
                    outcome="CONDITIONAL",
                    severity_flags=1,
                    conditional_conditions="Follow-up interview requested.",
                ),
                CO1,
            ),
            201,
        )
        after_one = get_applicant(applicant["id"], CO1)
        # One conditional interview: 1 flag x 1.5 weight x one half.
        assert_score(after_one["provisional_risk_score"], 0.75, "provisional ceiling")
        # The medical exam is still missing, so the decayed variant stays silent.
        assert_score(after_one["final_risk_score"], 0.0, "final decayed")

        # The medical exam is recorded last, so the required set completes only
        # on the final write; the psych evaluation goes to the second officer.
        remainder = (
            ("BACKGROUND_CHECK", CO1, "Minor traffic matter disclosed."),
            ("PSYCH_EVAL", CO2, "Weekly check-in advised."),
            ("INTERVIEW", CO1, "Second panel confirmed the first."),
            ("MEDICAL_EXAM", CO1, "Cardiology sign-off pending."),
        )
        for kind, headers, note in remainder:
            validate_success(
                api.create_screening_item(
                    applicant["id"],
                    create_screening_item_payload(
                        kind,
                        outcome="CONDITIONAL",
                        severity_flags=1,
                        conditional_conditions=note,
                    ),
                    headers,
                ),
                201,
            )

        final = get_applicant(applicant["id"], CO1)
        # Undecayed points: 0.75 + 1.5 + 2.0 + 0.75 + 1.0.
        assert_score(final["provisional_risk_score"], 6.00, "provisional ceiling")
        # All five share the logical clock's recorded_at, so the created_at
        # tie-break reverses the write order: 1.0 + 0.6 + 1.2 + 0.75 + 0.375.
        assert_score(final["final_risk_score"], 3.93, "final decayed")
        assert final["screening_status"] == "CLEARED"
        # A conditional medical exam defers its own dimension without holding up
        # the screening dimension.
        assert final["medical_status"] == "DEFERRED"
        assert final["enhanced_support_required"] is False

        assert validate_success(api.get_casting_call(call["id"], CD))[
            "screened_pass_count"
        ] == 1


class TestStipendTierBoundary:
    """The tier multiplier is selected by the episode count each variant uses, so
    the boundary between eight and nine episodes shows only in the final."""

    def test_one_extra_episode_crosses_the_band_and_adds_a_quarter_million(self, api):
        """PRD §3.6: "The tier multiplier is selected by the episode count used:
        a count of 4 or fewer takes a multiplier of 1.00, a count from 5 to 8
        inclusive takes 1.15, and a count of 9 or more takes 1.30."
        PRD §3.6: "The **base component** is `base_stipend_cents` multiplied by
        the episode count used, multiplied by that tier multiplier, rounded half
        up to whole cents."
        PRD §3.6: "It uses as its episode count the larger of `episodes_committed`
        and the production's `episode_order`, on the assumption that the
        participant is retained for the full season — and because that larger
        count can cross a tier boundary, the tier multiplier itself may differ
        from the final variant's."

        Design: Corner/calculations/stipend_tier_multiplier_boundary_between_eight_and_nine_episodes
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _adult_on(call["id"], "Ada Reyes", "1994-04-02")
        ben = _adult_on(call["id"], "Ben Okafor", "1990-01-10")

        eight_terms = dict(BASE_TERMS, stipend_structure="TIERED", episodes_committed=8)
        nine_terms = dict(BASE_TERMS, stipend_structure="TIERED", episodes_committed=9)

        eight_sent = setup_sent_agreement(ada["id"], production["id"], **eight_terms)
        eight = validate_success(api.execute_agreement(eight_sent["id"], BA2))
        nine_sent = setup_sent_agreement(ben["id"], production["id"], **nine_terms)
        nine = validate_success(api.execute_agreement(nine_sent["id"], BA2))

        # Both provisional figures use max(episodes, episode_order 9) = 9, so the
        # forward-looking variant cannot tell the two deals apart at all.
        assert_money(eight_sent["provisional_stipend_cents"], 1_370_000, "provisional")
        assert_money(nine_sent["provisional_stipend_cents"], 1_370_000, "provisional")
        assert (
            eight_sent["provisional_stipend_cents"]
            == nine_sent["provisional_stipend_cents"]
        )

        # 100,000 x 8 x 1.15 against 100,000 x 9 x 1.30.
        assert_money(eight["total_stipend_commitment_cents"], 920_000, "eight episodes")
        assert_money(nine["total_stipend_commitment_cents"], 1_170_000, "nine episodes")
        assert (
            nine["total_stipend_commitment_cents"]
            - eight["total_stipend_commitment_cents"]
            == 250_000
        )

        after = get_production(production["id"])
        assert_money(after["stipend_committed_cents"], 2_090_000, "committed stipend")
        assert after["casting_posture"] == "OPEN"


class TestWelfareSurchargeRounding:
    """The duty-of-care surcharge is whole cents rounded half up, so the two
    inputs that land exactly on a half cent settle the tie-breaking rule."""

    def test_a_half_cent_surcharge_rounds_away_from_zero_twice_over(self, api):
        """PRD §3.7: "Step three multiplies the subtotal by that band rate and
        again by the tier factor for the production's current
        `duty_of_care_tier` — one for `STANDARD`, one and a half for `ENHANCED`,
        two for `CRITICAL` — rounding the product half up to whole cents to give
        the duty-of-care surcharge."
        PRD §3.7: "Step four sets `welfare_committed_cents` to the protocol
        subtotal plus that surcharge."
        PRD §2.8: "Wherever an intermediate product or quotient is not a whole
        number of cents it is rounded half up — a value exactly on the half-cent
        rounds away from zero, upward."
        PRD §2.8: "The welfare surcharge is whole cents, rounded half up."

        Design: Corner/calculations/welfare_surcharge_rounds_half_up_at_exactly_half_a_cent
        """
        production = _island_trials(minor_participant_cap=2)
        assert production["duty_of_care_tier"] == "ENHANCED"
        assert_money(production["welfare_committed_cents"], 0, "opening commitment")

        # An ENHANCED production below the band floor charges 0.04 x 1.5 = 0.06,
        # so 25 cents yields exactly 1.5 and must round up to 2.
        first = setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=25,
            **WIDE_COVERAGE,
        )
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            27,
            "committed welfare on a 25-cent subtotal",
        )

        # A 75-cent subtotal yields exactly 4.5, which round half up sends to 5
        # where banker's rounding would send it to 4.
        second = setup_planned_welfare_protocol(
            production["id"],
            kind="ONSET_PSYCH_SUPPORT",
            cost_cents=50,
            **WIDE_COVERAGE,
        )
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            80,
            "committed welfare on a 75-cent subtotal",
        )

        rows, meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1)
        )
        assert meta["total_count"] == 2
        statuses = {row["id"]: row["status"] for row in rows}
        assert statuses[first["id"]] == "PLANNED"
        assert statuses[second["id"]] == "PLANNED"


class TestReleaseCoverageAggregation:
    """Coverage sums head counts, not rows, and it counts a blurred waiver while
    ignoring a refusal outright."""

    def test_a_refused_release_covers_nobody_and_a_blurred_waiver_covers_everyone(
        self, api
    ):
        """PRD §3.8: "`covered_head_count` is the sum of `head_count` over the
        block's releases whose `disposition` is `COLLECTED` or `BLURRED_WAIVER`;
        a `REFUSED` release contributes nothing."
        PRD §3.8: "`release_coverage_complete` is true when `covered_head_count`
        is greater than or equal to `expected_crowd_headcount` **and** every
        release of the block whose `subject_kind` is `MINOR_INCIDENTAL` carries
        `guardian_signature` true."
        PRD §3.8: "Wrapping moves a block `ROLLING → WRAPPED`, is admitted only
        from `ROLLING`, and re-evaluates coverage at wrap time; incomplete
        coverage is refused with `ERR_RELEASE_COVERAGE_INCOMPLETE`."

        Design: Corner/calculations/release_coverage_counts_blurred_waiver_and_ignores_refused_at_wrap
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)
        setup_active_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=1_000_000,
            **WIDE_COVERAGE,
        )
        block = setup_shoot_block(
            production["id"],
            venue["id"],
            block_kind="STUDIO",
            start_utc="2026-09-20T08:00:00Z",
            end_utc="2026-09-20T12:00:00Z",
            participant_agreement_ids=[],
            expected_crowd_headcount=10,
        )
        rolled = validate_success(api.roll_shoot_block(block["id"], PA))
        assert rolled["status"] == "ROLLING"

        collect_release(
            block["id"],
            subject_kind="INCIDENTAL_CROWD",
            head_count=4,
            disposition="COLLECTED",
        )
        collect_release(
            block["id"],
            subject_kind="INCIDENTAL_CROWD",
            head_count=5,
            disposition="REFUSED",
        )
        mid = get_shoot_block(block["id"])
        # Nine heads have paper on them, but five of them refused.
        assert mid["covered_head_count"] == 4
        assert mid["release_coverage_complete"] is False

        validate_error(
            api.wrap_shoot_block(block["id"], PA),
            ApiErrorId.ERR_RELEASE_COVERAGE_INCOMPLETE.value,
            422,
        )
        assert get_shoot_block(block["id"])["status"] == "ROLLING"

        collect_release(
            block["id"],
            subject_kind="INCIDENTAL_CROWD",
            head_count=6,
            disposition="BLURRED_WAIVER",
        )
        end = get_shoot_block(block["id"])
        assert end["covered_head_count"] == 10
        assert end["release_coverage_complete"] is True

        wrapped = validate_success(api.wrap_shoot_block(block["id"], PA))
        assert wrapped["status"] == "WRAPPED"
        # One million at the STANDARD tier's 0.04 band rate.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_040_000,
            "committed welfare",
        )


class TestStipendVariantSelection:
    """Which variant a caller sees is decided by the transition, not by the row:
    send writes only the provisional column, execute only the final one."""

    def test_send_writes_the_ceiling_and_execute_writes_the_contracted_figure(
        self, api
    ):
        """PRD §3.6: "Drafting opens the agreement at `status` `DRAFTED` with
        `round_number` at 0, both stipend figures at 0, `welfare_hold` false, and
        it increments the applicant's `version` by one."
        PRD §3.6: "On success the provisional stipend variant is written to
        `provisional_stipend_cents` — recomputed from the revised terms when the
        send follows a revision — and the status becomes `SENT`."
        PRD §3.6: "First, the final stipend variant is written to
        `total_stipend_commitment_cents`, the status becomes `EXECUTED`,
        `executed_by_user_id` is stamped with the caller's `X-User-ID`,
        `executed_at` is stamped with the logical clock, and the applicant's
        `screening_status` moves to `CAST`."
        PRD §3.6: "The **final** variant, written to
        `total_stipend_commitment_cents` on execution and zeroed on voiding, uses
        `episodes_committed` exactly as agreed, the contracted press count
        without any reserve, the actual `reunion_obligation` flag, and it does
        apply the depiction adjustment."

        Design: Corner/calculations/variant_selection_provisional_at_send_and_final_at_execute
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        applicant = _adult_on(call["id"], "Ada Reyes", "1994-04-02")

        drafted = setup_drafted_agreement(
            applicant["id"], production["id"], **BASE_TERMS
        )
        assert_money(drafted["provisional_stipend_cents"], 0, "provisional at draft")
        assert_money(drafted["total_stipend_commitment_cents"], 0, "final at draft")

        sent = validate_success(api.send_agreement(drafted["id"], BA1))
        assert_money(sent["provisional_stipend_cents"], 1_370_000, "provisional at send")
        assert_money(sent["total_stipend_commitment_cents"], 0, "final at send")
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            0,
            "committed stipend at send",
        )

        executed = validate_success(api.execute_agreement(drafted["id"], BA2))
        # The provisional column is preserved for audit rather than cleared.
        assert_money(
            executed["provisional_stipend_cents"], 1_370_000, "provisional at execute"
        )
        assert_money(
            executed["total_stipend_commitment_cents"], 200_000, "final at execute"
        )
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            200_000,
            "committed stipend at execute",
        )


class TestPosturePrecedence:
    """The posture clauses are evaluated in a pinned order, so the frozen clause
    wins outright over a restricted clause that is still true."""

    def test_a_budget_breach_freezes_a_production_already_restricted_by_its_cap(
        self, api
    ):
        """PRD §2.7: "The derivation reads only the production's own computed
        figures — no child scan beyond the rollups that have already written them
        — and its clauses are evaluated in a pinned precedence where the first
        matching clause wins and no lower clause is considered:"
        PRD §2.7: "The posture is `FROZEN` when `welfare_committed_cents` is
        strictly greater than `welfare_budget_cents`, or when
        `welfare_incident_count` has reached 2 or more."
        PRD §2.7: "The minor clause reads: `minor_participant_cap` is strictly
        greater than 0 and `minor_participant_count` is greater than or equal to
        `minor_participant_cap`."
        PRD §3.9: "Because the tier changed, the production's
        `welfare_committed_cents` is recomputed with the higher tier factor."

        Design: Corner/calculations/casting_posture_frozen_takes_precedence_over_restricted
        """
        production = _island_trials(minor_participant_cap=1)
        call = _referral_call(production["id"])
        applicant = setup_minor_applicant(
            call["id"],
            legal_name="Mika Vance",
            date_of_birth="2011-05-20",
            residency_state_code="CA",
            guardian_name="Dana Vance",
        )
        record_screening_items(applicant["id"], FULL_PASS_SCREENING)
        setup_minor_protection(
            applicant["id"],
            work_permit_number="CA-2026-77120",
            permit_expires_on="2026-12-31",
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )

        sent = setup_sent_agreement(applicant["id"], production["id"], **BASE_TERMS)
        assert_money(sent["provisional_stipend_cents"], 1_487_000, "provisional")
        executed = validate_success(api.execute_agreement(sent["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 220_000, "final stipend"
        )

        seated = get_production(production["id"])
        # The single minor fills a cap of one, so the lower clause already holds
        # while the pool is barely touched.
        assert seated["minor_participant_count"] == 1
        assert seated["casting_posture"] == "RESTRICTED"

        for kind in ("DUTY_OF_CARE_OFFICER", "ONSET_PSYCH_SUPPORT", "AFTERCARE_PROGRAM"):
            setup_planned_welfare_protocol(
                production["id"], kind=kind, cost_cents=3_000_000, **WIDE_COVERAGE
            )
        before = get_production(production["id"])
        assert before["duty_of_care_tier"] == "ENHANCED"
        # A 9,000,000 subtotal sits in the 0.07 band, and the ENHANCED factor
        # leaves 9,945,000 just inside a 10,000,000 budget.
        assert_money(before["welfare_committed_cents"], 9_945_000, "committed welfare")
        assert before["casting_posture"] == "RESTRICTED"

        complaint = setup_triaged_complaint(
            executed["id"],
            applicant["id"],
            category="WELFARE",
            severity=4,
            narrative="Minor left unsupervised between blocks.",
        )
        routed = validate_success(
            api.route_complaint(complaint["id"], route_payload("ESCALATION"), WO2)
        )
        assert routed["aftercare_sessions_authorized"] == 18
        assert routed["duty_of_care_breach"] is True

        after = get_production(production["id"])
        assert after["duty_of_care_tier"] == "CRITICAL"
        # The same 9,000,000 subtotal re-rated at 0.07 x 2.0 overshoots.
        assert_money(after["welfare_committed_cents"], 10_260_000, "committed welfare")
        assert after["welfare_incident_count"] == 1
        assert after["casting_posture"] == "FROZEN"
        assert_money(after["stipend_committed_cents"], 220_000, "committed stipend")

        # The frozen cascade is channel-blind, so even a referral call closes,
        # and it names the frozen posture rather than the restricted one.
        closed = validate_success(api.get_casting_call(call["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "POSTURE_FROZEN"
        # The welfare-hold cascade reaches agreements still in negotiation only.
        assert get_agreement(executed["id"])["welfare_hold"] is False
