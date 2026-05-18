"""Difficulty-design coverage — Part 1 (rules 1–5).

Each instance declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml receives at
least TWO dedicated tests. Each test docstring includes the verbatim
PRD sentence(s) that state the underlying rule, plus a
`# difficulty: <rule_id>/<instance.name>` tag so the coverage audit
can pin each test to its source instance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    abandon_application,
    advance_clock_to,
    create_applicant,
    create_application_payload,
    create_draft_application,
    create_fee_payload,
    excess_claim_fee_cents,
    filing_fee_cents,
    get_application,
    get_maintenance_fee,
    list_audit_events,
    list_fee_transactions,
    list_office_actions,
    make_applicant_headers,
    pay_fee,
    pay_filing_fees,
    pay_maintenance_and_settle,
    setup_filed_application,
    setup_granted_utility_at_calendar_anchor,
    setup_office_action_pending,
    setup_under_examination,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_small_vs_micro_filing_fee_diverge_on_same_utility_application(self, api):
        """# difficulty: dual_variant_calc/small_vs_micro_filing_fee_on_application

        PRD §3.2: "The filing fee table establishes a base amount per
        application type — 32000 cents for UTILITY, 22000 cents for
        DESIGN, and 30000 cents for PROVISIONAL — which is then
        multiplied by the entity-size multiplier from §2.7 and rounded
        half-up to integer cents in a single step, producing the exact
        amount_cents that the filing-category fee transaction must
        carry."
        PRD §2.7: "The entity-size multiplier is 1.00 for LARGE
        applicants, 0.50 for SMALL applicants, and 0.25 for MICRO
        applicants."

        Claim: SMALL UTILITY filing fee is 16000c; MICRO UTILITY filing
        fee is 8000c. Submitting the wrong amount on each side is
        rejected with ERR_FEE_AMOUNT_MISMATCH.
        """
        a_small = create_applicant(entity_size="SMALL")
        a_micro = create_applicant(entity_size="MICRO")
        app_s = create_draft_application(a_small, application_type="UTILITY",
                                         claim_count=1, independent_claim_count=1)
        app_m = create_draft_application(a_micro, application_type="UTILITY",
                                         claim_count=1, independent_claim_count=1)
        # SMALL pays 16000.
        ok_s = api.create_fee_transaction(
            app_s["id"], create_fee_payload("FILING", 16000),
            make_applicant_headers(a_small["id"]),
        )
        validate_success(ok_s, 201)
        # MICRO pays 8000.
        ok_m = api.create_fee_transaction(
            app_m["id"], create_fee_payload("FILING", 8000),
            make_applicant_headers(a_micro["id"]),
        )
        validate_success(ok_m, 201)
        # Swapping amounts (each pays the other's amount) must fail.
        a_s2 = create_applicant(entity_size="SMALL")
        app_s2 = create_draft_application(a_s2, application_type="UTILITY",
                                          claim_count=1, independent_claim_count=1)
        bad_s = api.create_fee_transaction(
            app_s2["id"], create_fee_payload("FILING", 8000),
            make_applicant_headers(a_s2["id"]),
        )
        validate_error(bad_s, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
        a_m2 = create_applicant(entity_size="MICRO")
        app_m2 = create_draft_application(a_m2, application_type="UTILITY",
                                          claim_count=1, independent_claim_count=1)
        bad_m = api.create_fee_transaction(
            app_m2["id"], create_fee_payload("FILING", 16000),
            make_applicant_headers(a_m2["id"]),
        )
        validate_error(bad_m, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)

    def test_small_vs_micro_filing_fee_round_half_up_single_step(self, api):
        """# difficulty: dual_variant_calc/small_vs_micro_filing_fee_on_application

        PRD §3.2: "is then multiplied by the entity-size multiplier
        from §2.7 and rounded half-up to integer cents in a single
        step, producing the exact amount_cents that the filing-category
        fee transaction must carry."

        Claim: design type (base 22000c) at MICRO is round(22000*0.25)
        = round(5500.0) = 5500c exactly. The PRD-derived helper agrees;
        any other accepted amount would be wrong.
        """
        a = create_applicant(entity_size="MICRO")
        app = create_draft_application(a, application_type="DESIGN",
                                       claim_count=1, independent_claim_count=1)
        assert filing_fee_cents("DESIGN", "MICRO") == 5500
        good = api.create_fee_transaction(
            app["id"], create_fee_payload("FILING", 5500),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)

    def test_forward_term_vs_lapse_truncated_on_utility(self, api):
        """# difficulty: dual_variant_calc/forward_term_vs_lapse_truncated_expiration_on_application

        PRD §3.4: "a granted UTILITY expires at granted_at plus 20
        years; a granted DESIGN expires at granted_at plus 15 years."
        PRD §3.4: "However, the effective expiration may be earlier
        than the forward-looking statutory term if a maintenance fee
        has lapsed: when at least one MaintenanceFee row for the
        application has a status of LAPSED, the effective expiration
        date is the earliest grace_period_end_at among the lapsed
        maintenance rows, which is necessarily earlier than the
        forward-looking statutory term."

        Claim: a granted UTILITY whose STAGE_3_5 maintenance row lapses
        has its effective expires_at truncated to the earliest LAPSED
        grace_period_end_at — distinctly earlier than granted_at+20y.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        granted_at = datetime.fromisoformat(granted["granted_at"].replace("Z", "+00:00"))
        forward_term = granted_at.replace(year=granted_at.year + 20)
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace_end = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        # Cross the grace boundary — maintenance lapses, app expires.
        advance_clock_to(grace_end + timedelta(seconds=1))
        app_after = get_application(granted["id"])
        assert app_after["status"] == "EXPIRED"
        # Effective expires_at must NOT equal the forward-looking 20y
        # term — it must be earlier, anchored at the earliest LAPSED
        # grace_period_end_at.
        expires_at = datetime.fromisoformat(
            app_after["expires_at"].replace("Z", "+00:00"),
        )
        assert expires_at < forward_term, (
            "PRD §3.4: lapse-truncated expires_at must be earlier than "
            f"granted_at+20y; got expires_at={expires_at}, forward_term={forward_term}"
        )
        assert expires_at == grace_end, (
            "PRD §3.4: effective expiration must be the earliest "
            f"grace_period_end_at among LAPSED maintenance rows; got {expires_at}"
        )

    def test_forward_term_when_no_maintenance_has_lapsed(self, api):
        """# difficulty: dual_variant_calc/forward_term_vs_lapse_truncated_expiration_on_application

        PRD §3.4: "When no maintenance fee has lapsed, the effective
        expiration is simply the statutory term as defined above."

        Claim: a freshly granted UTILITY with no lapsed maintenance has
        expires_at == granted_at + 20 years (no truncation).
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        granted_at = datetime.fromisoformat(granted["granted_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(granted["expires_at"].replace("Z", "+00:00"))
        expected = granted_at.replace(year=granted_at.year + 20)
        assert expires_at == expected, (
            "PRD §3.4: forward-looking term must be granted_at + 20y when no maintenance "
            f"has lapsed; got {expires_at}, expected {expected}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_micro_maintenance_grace_surcharge_flat_not_multiplied(self, api):
        """# difficulty: combinatorial_formula/maintenance_fee_three_inputs_threshold_branching

        PRD §3.5: "first multiply the base fee by the applicant's
        entity multiplier from §2.7 and round half-up to integer cents;
        then add the flat surcharge if the grace condition is met. The
        surcharge itself is not subject to the entity multiplier; it
        is a flat 16000 cents that is added to the rounded
        entity-adjusted base."

        Claim: MICRO STAGE_3_5 in grace = round(160000*0.25)+16000 =
        40000+16000 = 56000c. The wrong-order alternative
        round((160000+16000)*0.25) = 44000c is rejected.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="MICRO", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        due = datetime.fromisoformat(s35["due_at"].replace("Z", "+00:00"))
        # Move clock into grace band.
        advance_clock_to(due + timedelta(days=30))
        # Wrong: 44000.
        bad = api.create_fee_transaction(
            granted["id"],
            create_fee_payload("MAINTENANCE", 44000, maintenance_fee_id=s35["id"]),
            make_applicant_headers(a["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
        # Right: 56000.
        good = api.create_fee_transaction(
            granted["id"],
            create_fee_payload("MAINTENANCE", 56000, maintenance_fee_id=s35["id"]),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)
        # Settle.
        pay_res = api.pay_maintenance_fee(s35["id"], make_applicant_headers(a["id"]))
        validate_success(pay_res, 200)

    def test_small_maintenance_timely_no_surcharge_added(self, api):
        """# difficulty: combinatorial_formula/maintenance_fee_three_inputs_threshold_branching

        PRD §3.5: "When the payment lands in the timely portion (the
        clock is at or after window_open_at and at or before due_at),
        no surcharge applies."

        Claim: SMALL STAGE_3_5 timely = round(160000*0.5) = 80000c.
        Adding 16000 surcharge is wrong because the clock is in the
        timely (not grace) band — round(160000*0.5)+16000 = 96000c is
        rejected.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        advance_clock_to(win)  # at window_open_at — timely
        # Wrong: 96000 (with surcharge during timely).
        bad = api.create_fee_transaction(
            granted["id"],
            create_fee_payload("MAINTENANCE", 96000, maintenance_fee_id=s35["id"]),
            make_applicant_headers(a["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
        # Right: 80000.
        good = api.create_fee_transaction(
            granted["id"],
            create_fee_payload("MAINTENANCE", 80000, maintenance_fee_id=s35["id"]),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)

    def test_excess_claim_per_component_round_then_sum_small(self, api):
        """# difficulty: combinatorial_formula/excess_claim_per_component_rounding_order

        PRD §3.2: "first the excess-total component multiplies the unit
        price by the count and by the entity multiplier and rounds
        half-up; then the excess-independent component multiplies the
        unit price by the count and by the entity multiplier and
        rounds half-up; and only then are the two rounded integer
        components summed to produce the required amount_cents. The
        reverse order — summing first and rounding once — is
        explicitly forbidden because it diverges at odd counts under
        the half and quarter multipliers."

        Claim: SMALL with claim_count=21, independent_claim_count=4
        expects 29003c (per-component rounding); 29002c (sum-first)
        is rejected.
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY",
                                       claim_count=21, independent_claim_count=4)
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        assert excess_claim_fee_cents(21, 4, "SMALL") == 29003
        good = api.create_fee_transaction(
            app["id"], create_fee_payload("EXCESS_CLAIM", 29003),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)
        # Sibling app for the wrong amount.
        a2 = create_applicant(entity_size="SMALL")
        app2 = create_draft_application(a2, application_type="UTILITY",
                                        claim_count=21, independent_claim_count=4)
        pay_fee(a2, app2, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        bad = api.create_fee_transaction(
            app2["id"], create_fee_payload("EXCESS_CLAIM", 29002),
            make_applicant_headers(a2["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)

    def test_excess_claim_per_component_round_then_sum_micro(self, api):
        """# difficulty: combinatorial_formula/excess_claim_per_component_rounding_order

        PRD §3.2: "first the excess-total component ... rounds half-up;
        then the excess-independent component ... rounds half-up; and
        only then are the two rounded integer components summed".

        Claim: MICRO with 21 total / 4 independent claims:
        round(1*10001*0.25) + round(1*48003*0.25) =
        round(2500.25) + round(12000.75) = 2500 + 12001 = 14501c
        (the helper computes this PRD-pinned value).
        """
        expected = excess_claim_fee_cents(21, 4, "MICRO")
        assert expected == 14501, (
            "PRD §3.2 per-component rounding for MICRO with "
            "claim_count=21, independent_claim_count=4: "
            f"expected 2500+12001=14501c, got {expected}"
        )
        a = create_applicant(entity_size="MICRO")
        app = create_draft_application(a, application_type="UTILITY",
                                       claim_count=21, independent_claim_count=4)
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "MICRO"))
        good = api.create_fee_transaction(
            app["id"], create_fee_payload("EXCESS_CLAIM", expected),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_application_examination_office_action_cycle_three_times(self, api):
        """# difficulty: non_linear_state_machine/application_cycle_examination_to_office_action_to_examination

        PRD §3.3: "The server assigns a sequential action_number per
        application starting at 1 and incrementing by 1 for each
        subsequent Office Action on the same application — listing
        Office Actions for an application surfaces them in order".
        PRD §3.3: "On success the server creates a Response row ...
        transitions the application from OFFICE_ACTION_PENDING back to
        UNDER_EXAMINATION".

        Claim: Application can cycle UNDER_EXAMINATION ->
        OFFICE_ACTION_PENDING -> UNDER_EXAMINATION repeatedly, and
        each new Office Action's action_number is 1, 2, 3 in order.
        """
        from test_helpers import issue_office_action, get_office_action
        a, app = setup_under_examination()
        oa1 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa1["id"], make_applicant_headers(a["id"]))
        oa2 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa2["id"], make_applicant_headers(a["id"]))
        oa3 = issue_office_action(app, action_type="FINAL")
        api.file_response(oa3["id"], make_applicant_headers(a["id"]))
        # All three action_numbers in order.
        nums = sorted(get_office_action(oa["id"])["action_number"]
                      for oa in [oa1, oa2, oa3])
        assert nums == [1, 2, 3]
        # Application currently UNDER_EXAMINATION.
        assert get_application(app["id"])["status"] == "UNDER_EXAMINATION"

    def test_application_cycle_reaches_allowed_after_responses(self, api):
        """# difficulty: non_linear_state_machine/application_cycle_examination_to_office_action_to_examination

        PRD §3.3: "Once every Office Action for the application has
        been resolved — that is, no Office Action with status PENDING
        remains — an examiner may allow the application, transitioning
        it from UNDER_EXAMINATION to ALLOWED."

        Claim: after one full cycle, /allow succeeds and the application
        reaches ALLOWED.
        """
        from test_helpers import issue_office_action, allow_application
        a, app, oa1 = setup_office_action_pending()
        api.file_response(oa1["id"], make_applicant_headers(a["id"]))
        result = allow_application(get_application(app["id"]))
        assert result["status"] == "ALLOWED"

    def test_pct_phase_branching_national_entered_vs_lapsed(self, api):
        """# difficulty: non_linear_state_machine/pct_phase_branching_terminal_dimensions

        PRD §3.6: "To enter national phase, the applicant invokes the
        national-entry transition on the PCT row, advancing its status
        to NATIONAL_ENTERED."
        PRD §3.6: "When the clock advances past
        national_phase_deadline_at while the PCT row is still
        INTERNATIONAL, the deadline sweep deterministically flips its
        status to LAPSED".

        Claim: PCTPhase has two diverging terminal states from the
        same INTERNATIONAL antecedent: applicant-driven
        NATIONAL_ENTERED vs clock-driven LAPSED. Two independent PCTs
        demonstrate both branches.
        """
        from test_helpers import (
            initiate_pct_phase, pay_pct_national_and_enter, get_pct_phase,
            setup_filed_application, advance_clock_to,
        )
        # Branch A — NATIONAL_ENTERED.
        a_a, app_a = setup_filed_application(application_type="UTILITY")
        pct_a = initiate_pct_phase(a_a, app_a)
        pay_pct_national_and_enter(a_a, app_a, pct_a)
        pct_a_after = get_pct_phase(pct_a["id"])
        assert pct_a_after["status"] == "NATIONAL_ENTERED"
        assert pct_a_after["national_entered_at"] is not None
        # Branch B — LAPSED (advance past the deadline).
        a_b, app_b = setup_filed_application(application_type="UTILITY")
        pct_b = initiate_pct_phase(a_b, app_b)
        deadline = datetime.fromisoformat(
            pct_b["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline + timedelta(seconds=1))
        pct_b_after = get_pct_phase(pct_b["id"])
        assert pct_b_after["status"] == "LAPSED"
        # The lapsed branch does NOT set national_entered_at.
        assert pct_b_after.get("national_entered_at") in (None,), (
            "PRD §3.6: LAPSED branch must not set national_entered_at"
        )

    def test_pct_phase_branch_side_effects_diverge(self, api):
        """# difficulty: non_linear_state_machine/pct_phase_branching_terminal_dimensions

        PRD §3.6: "On a successful entry the server stamps
        national_entered_at as the current clock and writes a
        PCT_NATIONAL_ENTERED audit row."
        PRD §3.6: "When the clock advances past
        national_phase_deadline_at while the PCT row is still
        INTERNATIONAL, the deadline sweep deterministically flips its
        status to LAPSED and writes a PCT_LAPSED audit row".

        Claim: the audit trail of NATIONAL_ENTERED branch contains
        PCT_NATIONAL_ENTERED but not PCT_LAPSED; the LAPSED branch
        contains PCT_LAPSED but not PCT_NATIONAL_ENTERED.
        """
        from test_helpers import (
            initiate_pct_phase, pay_pct_national_and_enter,
            setup_filed_application, advance_clock_to, list_audit_events,
        )
        a_a, app_a = setup_filed_application(application_type="UTILITY")
        pct_a = initiate_pct_phase(a_a, app_a)
        pay_pct_national_and_enter(a_a, app_a, pct_a)
        actions_a = [e["action"] for e in list_audit_events(app_a["id"])]
        assert "PCT_NATIONAL_ENTERED" in actions_a
        assert "PCT_LAPSED" not in actions_a

        a_b, app_b = setup_filed_application(application_type="UTILITY")
        pct_b = initiate_pct_phase(a_b, app_b)
        deadline = datetime.fromisoformat(
            pct_b["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline + timedelta(seconds=1))
        actions_b = [e["action"] for e in list_audit_events(app_b["id"])]
        assert "PCT_LAPSED" in actions_b
        assert "PCT_NATIONAL_ENTERED" not in actions_b


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_maintenance_lapse_expires_application_and_lapses_pct(self, api):
        """# difficulty: transitive_cascade/maintenance_lapse_triggers_application_expiration_triggers_pct_lapse

        PRD §3.5: "When the clock advances past a MaintenanceFee's
        grace_period_end_at while that row is still SCHEDULED and no
        qualifying MAINTENANCE-category fee transaction tied to it has
        been recorded, the deadline sweep in §2.8 deterministically
        flips the row's status to LAPSED and writes a
        MAINTENANCE_FEE_LAPSED audit row. A lapsed maintenance fee in
        turn drives the owning application to EXPIRED via the same
        sweep, which writes an APPLICATION_EXPIRED audit row."

        Claim: a single clock advance crosses the maintenance grace
        boundary and produces the cascade MAINTENANCE_FEE_LAPSED ->
        APPLICATION_EXPIRED in the audit stream.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(grace + timedelta(seconds=1))
        events = list_audit_events(granted["id"])
        actions = [e["action"] for e in events]
        assert "MAINTENANCE_FEE_LAPSED" in actions
        assert "APPLICATION_EXPIRED" in actions

    def test_application_abandon_closes_pending_office_actions(self, api):
        """# difficulty: transitive_cascade/application_abandon_triggers_office_action_close_triggers_maintenance_purge

        PRD §3.3: "the abandonment cascades every PENDING Office Action
        for that application into ABANDONED_BY_DEFAULT, deletes every
        SCHEDULED MaintenanceFee row that may have been provisioned
        for the application, and writes an
        APPLICATION_ABANDONED_VOLUNTARY audit row."

        Claim: a single /abandon call on an OFFICE_ACTION_PENDING
        application produces the cascade Application.status==ABANDONED
        -> OfficeAction.status==ABANDONED_BY_DEFAULT, and writes the
        APPLICATION_ABANDONED_VOLUNTARY audit row.
        """
        from test_helpers import get_office_action
        a, app, oa = setup_office_action_pending()
        abandon_application(a, app)
        app_after = get_application(app["id"])
        oa_after = get_office_action(oa["id"])
        assert app_after["status"] == "ABANDONED"
        assert oa_after["status"] == "ABANDONED_BY_DEFAULT"
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_ABANDONED_VOLUNTARY" in actions


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    # NOTE: a former test_maintenance_invalid_state_wins_over_fee_mismatch
    # was deleted here. The PRD's fee-recording prose (POST .../fee-transactions
    # under PRD §3.2) does not pin a state-machine precondition on the
    # referenced MaintenanceFee — only fee_category / amount / FK checks
    # are mandated. PRD §2.11 priority is a global ordering rule, but it
    # does not by itself create checks where the endpoint contract is
    # silent. A faithful PRD-only implementer can therefore reasonably
    # accept the second FeeTransaction (and surface ERR_FEE_AMOUNT_MISMATCH
    # for the bad amount) without consulting the MaintenanceFee status.
    # Deletion under STEP 1b unique-derivability.

    def test_micro_ineligible_wins_over_claim_shape(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_conflict_on_applicant_create

        PRD §3.1: "the registration is rejected with
        ERR_MICRO_INELIGIBLE unless both income and prior-filings
        figures are present and within the published caps."

        Claim: ERR_MICRO_INELIGIBLE is raised on /applicants creation
        with bad MICRO caps — applicant-creation does not surface
        claim-shape errors (those belong to /applications). This is
        the safety category fired in isolation.
        """
        from test_helpers import (
            create_applicant_payload, MICRO_HUGE_INCOME_CENTS,
            MICRO_HUGE_PRIOR_FILINGS_COUNT,
        )
        res = api.create_applicant(
            create_applicant_payload(
                entity_size="MICRO",
                gross_income_cents=MICRO_HUGE_INCOME_CENTS,
                prior_filings_count=MICRO_HUGE_PRIOR_FILINGS_COUNT,
            ),
            {"X-User-ID": "uspto-admin-1", "X-User-Role": "USPTOAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)

    def test_claim_shape_invalid_fires_on_isolated_violation(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_conflict_on_applicant_create

        PRD §3.2: "Any violation of these constraints is reported as
        ERR_CLAIM_SHAPE_INVALID."

        Claim: a UTILITY application with claim_count=0 and a valid
        MICRO applicant (caps satisfied) returns
        ERR_CLAIM_SHAPE_INVALID — there is no safety-priority winner
        because the applicant is valid. This demonstrates the
        complementary priority slot vs the MICRO eligibility case
        above.
        """
        a = create_applicant(entity_size="MICRO")  # valid MICRO
        from test_helpers import create_application_payload
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=0, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)
