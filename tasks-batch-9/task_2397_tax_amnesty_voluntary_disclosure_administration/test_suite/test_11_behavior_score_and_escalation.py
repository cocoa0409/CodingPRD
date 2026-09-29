"""The two behavior score variants and the post-program penalty composition.

PRD §3.2 computes one score two ways from identical facts, and PRD §3.9 layers
an additive rate, a multiplicative escalation, a cap and a floor on top of a
snapshot of the taxpayer's posture taken at drafting time.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    AUDITOR_TWO_HEADERS,
    AUDITOR_ONE_USER_ID,
    AUDITOR_TWO_USER_ID,
    OFFICER_ALPHA_HEADERS,
    abate_action_payload,
    assert_fields,
    assert_list_total,
    close_window,
    disclose_identity_payload,
    draft_and_file_return,
    enforcement_action_payload,
    make_representative_headers,
    offer_terms_payload,
    open_enforcement_case,
    pre_clearance_payload,
    read_compliance_behavior,
    read_enforcement_action,
    read_pre_clearance,
    read_taxpayer,
    register_representative,
    register_taxpayer,
    set_clock,
    setup_executed_agreement,
    setup_open_program,
    setup_program_with_taxpayer,
    validate_success,
)

QUARTER_2_2025 = {
    "period_start_date": "2025-04-01",
    "period_end_date": "2025-06-30",
}


def _participant_with_two_nonfiler_periods(api):
    """An executed walk-in carrying two surfaced non-filer periods, plus an
    open audit on a tax type the agreement does not cover."""
    ctx = setup_executed_agreement(
        api,
        taxpayer_overrides={
            "legal_name": "Foxglove Interiors Inc",
            "tin_last4": "2231",
        },
    )
    open_enforcement_case(
        api,
        ctx["taxpayer"]["id"],
        case_type="FIELD_AUDIT",
        tax_type="CORPORATE_INCOME",
        opened_at="2026-04-10",
    )
    ctx["first_return"] = draft_and_file_return(
        api, ctx, reported_tax_cents=200000, is_nonfiler_period=True
    )
    ctx["second_return"] = draft_and_file_return(
        api, ctx, reported_tax_cents=200000, is_nonfiler_period=True, **QUARTER_2_2025
    )
    return ctx


def _flagged_nonparticipant_with_an_open_case(api):
    """A taxpayer whose representative disclosed but never accepted, holding an
    open collection case, after the program's closing cascade has run."""
    ctx = setup_program_with_taxpayer(
        api,
        taxpayer_overrides={
            "legal_name": "Harbor Line Trading Co",
            "tin_last4": "7714",
        },
    )
    open_enforcement_case(
        api,
        ctx["taxpayer"]["id"],
        case_type="COLLECTION",
        tax_type="PERSONAL_INCOME",
        opened_at="2026-05-04",
    )

    representative = register_representative(api)
    rep_headers = make_representative_headers(representative["id"])
    pre_clearance = validate_success(
        api.create_pre_clearance(
            pre_clearance_payload(
                ctx["program"]["id"],
                anonymous_alias="CLIENT-31",
                estimated_liability_cents=800000,
                earliest_unfiled_period_start="2024-01-01",
            ),
            rep_headers,
        ),
        201,
    )
    pre_clearance = validate_success(
        api.begin_pre_clearance_review(pre_clearance["id"], OFFICER_ALPHA_HEADERS)
    )
    pre_clearance = validate_success(
        api.offer_terms(
            pre_clearance["id"],
            offer_terms_payload(
                pre_clearance["version"],
                offered_lookback_months=24,
                offered_penalty_waiver_pct=1.00,
                offered_interest_waiver_pct=0.50,
            ),
            OFFICER_ALPHA_HEADERS,
        )
    )
    pre_clearance = validate_success(
        api.disclose_identity(
            pre_clearance["id"],
            disclose_identity_payload(ctx["taxpayer"]["id"]),
            rep_headers,
        )
    )
    ctx["program"] = close_window(api, ctx["program"]["id"])
    # the closing cascade is what expires the pre-clearance, so read it back
    # after the close rather than holding the pre-close snapshot
    ctx["pre_clearance"] = read_pre_clearance(api, pre_clearance["id"])
    return ctx


class TestScoreVariants:
    """One set of facts, two answers: what happened and what the program saw."""

    def test_the_historical_variant_is_the_one_persisted_on_the_taxpayer(self, api):
        """An open case and two surfaced non-filer periods cost 30 points.

        PRD §3.2: "The `HISTORICAL` variant is the one persisted in
        `compliance_behavior_score`. It starts from a base of 100 and then
        subtracts 20 points for each enforcement case of that taxpayer whose
        status is `OPEN`, subtracts 30 points for each case whose status is
        `REFERRED`, subtracts 5 points for each period counted in
        `nonfiler_period_count`, subtracts a flat 25 points if
        `nonparticipant_flag` is true, subtracts 8 points for each action counted
        in `open_enforcement_action_count`, and finally adds 15 points for each
        agreement of that taxpayer whose status is `FULFILLED`."

        PRD §3.5: "A non-filer period adds a further 5 percentage points on top
        of the tier rate, and the sum is stored in `penalty_rate_applied`."

        Design: Difficulty/dual_variant_calc/historical_vs_program_adjusted_behavior_score_divergence
        """
        ctx = _participant_with_two_nonfiler_periods(api)

        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            open_case_count=1,
            nonfiler_period_count=2,
            nonparticipant_flag=False,
            escalation_tier="T0",
            compliance_behavior_score=70,
        )
        assert_fields(
            ctx["first_return"],
            penalty_rate_applied=0.30,
            gross_penalty_cents=60000,
            gross_interest_cents=20000,
        )

    def test_the_program_adjusted_variant_forgives_and_credits(self, api):
        """The same facts read 98 once the program takes credit for them.

        PRD §3.2: "It begins from the `HISTORICAL` value and then forgives the
        non-filer penalty on the periods the program brought in — for each return
        whose `is_nonfiler_period` is true, whose agreement belongs to the program
        in question with a status of `EXECUTED`, `FULFILLED` or `SUPERSEDED`, and
        whose `period_start_date` falls on or after that agreement's
        `lookback_start_date`, 5 points are added back. If the taxpayer holds at
        least one such agreement, a further 18 points of participation credit are
        added."

        PRD §3.2: "The persisted field always holds the `HISTORICAL` value; the
        adjusted value is reported, never stored."

        Design: Difficulty/dual_variant_calc/historical_vs_program_adjusted_behavior_score_divergence
        """
        ctx = _participant_with_two_nonfiler_periods(api)

        assert_fields(
            read_compliance_behavior(api, ctx["taxpayer"]["id"]),
            taxpayer_id=ctx["taxpayer"]["id"],
            open_case_count=1,
            referred_case_count=0,
            nonfiler_period_count=2,
            forgiven_nonfiler_period_count=2,
            open_enforcement_action_count=0,
            nonparticipant_flag=False,
            escalation_tier="T0",
            historical_score=70,
            program_adjusted_score=98,
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]), compliance_behavior_score=70
        )


class TestCaseReferral:
    """Referral swaps the open-case penalty for the heavier referred one."""

    def test_referring_a_case_leaves_it_open_dated_but_costs_ten_more_points(
        self, api
    ):
        """The case leaves `OPEN` without a `closed_at`, and the score drops.

        PRD §3.2: "Referring it moves the case `OPEN → REFERRED`, leaves
        `closed_at` null, and recomputes the same three taxpayer fields, but a
        referred case carries the heavier referred-case penalty in place of the
        open-case penalty."

        PRD §3.2: "The case is created with `status` `OPEN`, `closed_at` null, and
        `opened_by_user_id` set from the acting auditor's `X-User-ID`; creating it
        immediately recomputes that taxpayer's `open_case_count`,
        `escalation_tier` and `compliance_behavior_score`."

        Design: Corner/Table 2 State Machines/referring_a_case_moves_state_and_deepens_the_score_penalty
        """
        setup_open_program(api)
        taxpayer = register_taxpayer(
            api, legal_name="Thistle Bay Hospitality LLC", tin_last4="6640"
        )
        case = open_enforcement_case(
            api,
            taxpayer["id"],
            case_type="DESK_AUDIT",
            tax_type="WITHHOLDING",
            opened_at="2026-02-11",
        )
        assert_fields(case, status="OPEN", closed_at=None)
        assert_fields(
            read_taxpayer(api, taxpayer["id"]),
            open_case_count=1,
            compliance_behavior_score=80,
        )

        referred = validate_success(
            api.refer_enforcement_case(case["id"], AUDITOR_ONE_HEADERS)
        )
        assert_fields(
            referred,
            status="REFERRED",
            closed_at=None,
            opened_by_user_id=AUDITOR_ONE_USER_ID,
        )

        assert_fields(
            read_taxpayer(api, taxpayer["id"]),
            open_case_count=0,
            compliance_behavior_score=70,
            escalation_tier="T0",
        )
        assert_fields(
            read_compliance_behavior(api, taxpayer["id"]),
            open_case_count=0,
            referred_case_count=1,
            historical_score=70,
            program_adjusted_score=70,
        )
        assert_list_total(
            api.list_taxpayer_enforcement_cases(
                taxpayer["id"], AUDITOR_ONE_HEADERS, {"status": "REFERRED", "limit": 100}
            ),
            1,
        )


class TestPostProgramPenaltyComposition:
    """Rate, escalation, cap and floor compose in a fixed order."""

    def test_the_snapshot_records_the_posture_at_drafting_time(self, api):
        """A flagged taxpayer with an open case is drafted against at `T2`.

        PRD §3.2: "A taxpayer's `escalation_tier` is resolved from just two facts,
        evaluated in this order: the tier is `T2` when `nonparticipant_flag` is
        true and `open_case_count` is at least 1; otherwise it is `T1` when
        `nonparticipant_flag` is true; otherwise it is `T0`."

        PRD §3.9: "`escalation_tier_applied` captures the taxpayer's
        `escalation_tier` at that instant. `multiplier_applied` is the program's
        `post_program_penalty_multiplier` when the taxpayer's
        `nonparticipant_flag` is true, and 1.00 otherwise — the escalation is
        reserved for people who could have come forward and did not.
        `behavior_adjustment_applied` is 0.05 when the snapshotted
        `compliance_behavior_score` is strictly below 60, and 0.00 otherwise."

        PRD §3.9: "The action is created with `status` `DRAFT`, `origin` `MANUAL`,
        `created_by_user_id` set from the drafting auditor, `issued_by_user_id`,
        `issued_at` and `abatement_reason` null."

        Design: Difficulty/combinatorial_formula/post_program_penalty_nested_cap_beats_escalated_rate
        """
        ctx = _flagged_nonparticipant_with_an_open_case(api)
        assert_fields(ctx["pre_clearance"], status="EXPIRED")
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            nonparticipant_flag=True,
            escalation_tier="T2",
            compliance_behavior_score=55,
        )

        action = validate_success(
            api.create_enforcement_action(
                enforcement_action_payload(
                    ctx["taxpayer"]["id"], ctx["program"]["id"], 400000
                ),
                AUDITOR_ONE_HEADERS,
            ),
            201,
        )
        assert_fields(
            action,
            status="DRAFT",
            origin="MANUAL",
            created_by_user_id=AUDITOR_ONE_USER_ID,
            issued_by_user_id=None,
            issued_at=None,
            abatement_reason=None,
            escalation_tier_applied="T2",
            multiplier_applied=2.00,
            behavior_adjustment_applied=0.05,
        )

    def test_the_cap_binds_before_the_floor_and_beats_the_escalated_rate(self, api):
        """0.40 escalated twice would take 320,000; the cap holds it at 200,000.

        PRD §3.9: "A raw amount is computed as `base_tax_cents` multiplied by the
        sum of the tier rate and `behavior_adjustment_applied`, then multiplied by
        `multiplier_applied`, and rounded half up to whole cents. A cap amount is
        computed as `base_tax_cents` multiplied by 0.50 and rounded half up to
        whole cents. The `assessed_penalty_cents` is then the greater of a floor of
        10,000 cents and the lesser of the raw amount and the cap amount — the cap
        is applied first and the floor last, on already-rounded integers, so on a
        small base the floor legitimately beats the cap and the assessed penalty
        may exceed half the base tax."

        PRD §3.9: "The tier rate is 0.10 for tier `T0`, 0.20 for tier `T1` and
        0.35 for tier `T2`."

        Design: Difficulty/combinatorial_formula/post_program_penalty_nested_cap_beats_escalated_rate
        """
        ctx = _flagged_nonparticipant_with_an_open_case(api)

        action = validate_success(
            api.create_enforcement_action(
                enforcement_action_payload(
                    ctx["taxpayer"]["id"], ctx["program"]["id"], 400000
                ),
                AUDITOR_ONE_HEADERS,
            ),
            201,
        )
        assert_fields(
            action,
            base_tax_cents=400000,
            assessed_penalty_cents=200000,
        )
        assert_fields(
            read_enforcement_action(api, action["id"]),
            assessed_penalty_cents=200000,
            status="DRAFT",
        )


class TestActionAbatement:
    """Abatement gives the eight points back and leaves the figures alone."""

    def test_abatement_restores_the_points_that_issuance_took(self, api):
        """Issuance docks 8 points; abatement removes that penalty again.

        PRD §3.9: "Issuing records `issued_by_user_id` and stamps `issued_at`
        with the current instant, then recomputes the taxpayer's
        `open_enforcement_action_count` and `compliance_behavior_score`, which now
        absorbs the 8-point issued-action penalty. Abatement advances the action
        `ISSUED → ABATED`, its terminal state, records the supplied
        `abatement_reason`, and recomputes the same two taxpayer fields with the
        issued-action penalty removed."

        Design: Difficulty/compensating_invariant/action_abatement_restores_the_behavior_ledger_but_not_the_assessment
        """
        ctx = setup_open_program(api)
        taxpayer = register_taxpayer(
            api, legal_name="Ash Prairie Grain LLC", tin_last4="9013"
        )
        close_window(api, ctx["program"]["id"])

        action = validate_success(
            api.create_enforcement_action(
                enforcement_action_payload(taxpayer["id"], ctx["program"]["id"], 50000),
                AUDITOR_ONE_HEADERS,
            ),
            201,
        )
        validate_success(
            api.issue_enforcement_action(action["id"], AUDITOR_TWO_HEADERS)
        )
        assert_fields(
            read_taxpayer(api, taxpayer["id"]),
            open_enforcement_action_count=1,
            compliance_behavior_score=92,
        )

        abated = validate_success(
            api.abate_enforcement_action(
                action["id"], abate_action_payload(), AUDITOR_ONE_HEADERS
            )
        )
        assert_fields(
            abated,
            status="ABATED",
            abatement_reason="TAXPAYER_PRODUCED_FILED_RETURNS",
        )
        assert_fields(
            read_taxpayer(api, taxpayer["id"]),
            open_enforcement_action_count=0,
            compliance_behavior_score=100,
            escalation_tier="T0",
        )

    def test_abatement_does_not_disturb_the_snapshotted_assessment(self, api):
        """The floor beat the cap at drafting time, and it still stands.

        PRD §3.9: "Drafting immediately snapshots the taxpayer's posture and
        computes the penalty, so that later changes to the taxpayer's record
        cannot retroactively move an assessment."

        PRD §3.9: "The `assessed_penalty_cents` is then the greater of a floor of
        10,000 cents and the lesser of the raw amount and the cap amount — the cap
        is applied first and the floor last, on already-rounded integers, so on a
        small base the floor legitimately beats the cap and the assessed penalty
        may exceed half the base tax."

        Design: Difficulty/compensating_invariant/action_abatement_restores_the_behavior_ledger_but_not_the_assessment
        """
        ctx = setup_open_program(api)
        taxpayer = register_taxpayer(
            api, legal_name="Ash Prairie Grain LLC", tin_last4="9013"
        )
        set_clock(api, "2026-12-01T00:00:00Z")
        validate_success(api.close_program(ctx["program"]["id"], ADMIN_HEADERS))

        action = validate_success(
            api.create_enforcement_action(
                enforcement_action_payload(taxpayer["id"], ctx["program"]["id"], 50000),
                AUDITOR_ONE_HEADERS,
            ),
            201,
        )
        validate_success(
            api.issue_enforcement_action(action["id"], AUDITOR_TWO_HEADERS)
        )
        validate_success(
            api.abate_enforcement_action(
                action["id"], abate_action_payload(), AUDITOR_ONE_HEADERS
            )
        )

        assert_fields(
            read_enforcement_action(api, action["id"]),
            status="ABATED",
            base_tax_cents=50000,
            escalation_tier_applied="T0",
            multiplier_applied=1.00,
            behavior_adjustment_applied=0.00,
            assessed_penalty_cents=10000,
            created_by_user_id=AUDITOR_ONE_USER_ID,
            issued_by_user_id=AUDITOR_TWO_USER_ID,
        )
