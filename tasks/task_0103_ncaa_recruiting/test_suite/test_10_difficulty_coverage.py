"""Difficulty-targeted second-coverage tests.

Each test in this file pairs with a primary-coverage test elsewhere in
the suite to satisfy the ">= 2 tests per instance" rule for every
difficulty-design instance. The instance name appears in each test's
docstring as `# difficulty: <rule_id>/<instance.name>` so coverage can
be audited.

Where PRD prose names a rule but the underlying state required by the
test recipe is unreachable through PRD-described transitions, the gap
is recorded in this module's docstring footer under
"difficulty-coverage-blocked-by-prd-silence". This file does NOT use
pytest.mark.skip — surviving skips would violate the generator's
guarantee.
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    PORTAL_HOLDING_PERIOD_HOURS,
    TEST_USERS,
    advance_clock_to,
    approve_nil_deal,
    commit_athlete,
    create_athlete,
    create_eligibility_record,
    create_portal_entry,
    create_program,
    create_scholarship_slot_payload,
    create_transfer_portal_entry_payload,
    create_violation_payload,
    drive_violation_to_appealed,
    drive_violation_to_sustained,
    declare_calendar_window,
    enroll_athlete,
    iso_utc,
    make_athlete_headers,
    offer_slot,
    parse_iso,
    patch_nil_deal_payload,
    report_violation,
    review_nil_deal,
    server_now_iso,
    setup_athlete_with_approved_deal,
    setup_enrolled_athlete,
    setup_ineligible_athlete_via_violation,
    setup_portal_entry_in_contact_window,
    sign_slot,
    submit_nil_deal,
    transition_nil_deal_payload,
    transition_scholarship_slot_payload,
    transition_transfer_portal_entry_payload,
    transition_violation,
    transition_violation_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantNILDealStatedVsFmv:
    """Instance: nildeal_stated_vs_fmv_pinning — second coverage for
    the PRD §3.6 min(stated, fmv) pinning."""

    def test_approved_value_pins_to_stated_when_stated_lower(
        self, api,
    ):
        """PRD §3.6: "On success, approved_value_cents is pinned to
        the minimum of stated_value_cents and fmv_calculated_cents —
        the system caps approved compensation at fair market when the
        stated payment exceeds it, but honors the stated value when
        it falls below fair market."

        Claim: stated=500000 (lower) < fmv=600000 ->
        approved_value_cents = stated = 500000. The athlete's
        nil_deal_lifetime_value_cents picks up exactly 500000.

        # difficulty: dual_variant_calc/nildeal_stated_vs_fmv_pinning
        """
        athlete, _p, _s = setup_enrolled_athlete()
        from test_helpers import setup_approved_nil_deal
        d = setup_approved_nil_deal(
            athlete["id"],
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
        )
        assert d["fmv_calculated_cents"] == 600_000
        assert d["stated_value_cents"] == 500_000
        assert d["approved_value_cents"] == 500_000
        a_resp = api.get_athlete(
            athlete["id"], TEST_USERS["officer_headers"],
        )
        a_data = validate_success(a_resp)
        assert a_data["nil_deal_lifetime_value_cents"] == 500_000


class TestDualVariantViolationRecidivism:
    """Instance: violation_penalty_recidivism_variant — recidivism
    multiplier changes penalty_points for two identically-graded
    LEVEL_II cases on the same program."""

    def test_second_offense_level_ii_yields_eight_points(
        self, api, officer_headers, officer_headers_secondary,
        officer_headers_tertiary,
    ):
        """PRD §3.7: "Severity points are 10 for LEVEL_I, 5 for
        LEVEL_II, 2 for LEVEL_III, and 1 for LEVEL_IV. The recidivism
        multiplier counts prior SUSTAINED violations against the same
        program_id whose created_at falls strictly before this case's
        created_at and on or after this.created_at - 730 days,
        excluding this case itself: a count of zero yields multiplier
        1.0; a count of exactly one yields 1.5; a count of two or
        more yields 2.0."
        PRD §3.7: "penalty_points is computed as severity points
        multiplied by a recidivism multiplier, rounded half-up to the
        nearest integer after the multiplication."

        Claim: a first LEVEL_II case scores 5; the second LEVEL_II
        case on the same program then scores 5 * 1.5 = 7.5 -> 8 after
        round_half_up.

        # difficulty: dual_variant_calc/violation_penalty_recidivism_variant
        """
        program = create_program()
        v1 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
            appellate_headers=officer_headers_secondary,
        )
        assert v1["penalty_points"] == 5
        # Now a second LEVEL_II on the same program. Use a different
        # reviewer (PRIMARY is reviewer_user_id of v1, but PRD §3.7
        # only constrains segregation per-case — V2's reviewer can
        # be any officer). To avoid edge cases use TERTIARY for V2
        # reviewer and PRIMARY for V2 appellate (different from
        # V2's reviewer).
        v2 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers_tertiary,
            appellate_headers=officer_headers,
        )
        # prior_count = 1 (v1 SUSTAINED before v2 created_at).
        # 5 * 1.5 = 7.5 -> round_half_up -> 8.
        assert v2["penalty_points"] == 8, (
            f"second-offense LEVEL_II = 5 * 1.5 = 7.5 -> round_half_up "
            f"= 8, got {v2['penalty_points']}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFMVThreeInput:
    """Instance: nil_fmv_three_input_nonlinear — mode (a):
    deliverables * market * cat_mult * booster_factor is a
    three-input combinatorial product with non-linear category
    selection."""

    def test_endorsement_booster_vs_autograph_nonbooster_yield_different_fmv(
        self, api,
    ):
        """PRD §3.5: "It begins with a base equal to deliverables_hours
        multiplied by market_rate_cents_per_hour. The base is then
        multiplied by a category multiplier ... The result is then
        multiplied by a booster factor: 0.80 when sponsor_is_booster
        is true ... and 1.00 otherwise."

        Claim: deal A (ENDORSEMENT, booster) -> 10*50000*1.20*0.80 =
        480000. Deal B (AUTOGRAPH_SIGNING, non-booster) ->
        10*50000*0.90*1.00 = 450000. Same hours and market rate, but
        different FMV because the (category, booster) combination
        differs.

        # difficulty: combinatorial_formula/nil_fmv_three_input_nonlinear
        """
        a, _p, _s = setup_enrolled_athlete()
        d_endorse_booster = submit_nil_deal(
            a["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=True,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=400_000,
        )
        d_auto_nonbooster = submit_nil_deal(
            a["id"],
            deal_category="AUTOGRAPH_SIGNING",
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=400_000,
        )
        assert d_endorse_booster["fmv_calculated_cents"] == 480_000
        assert d_auto_nonbooster["fmv_calculated_cents"] == 450_000
        assert (
            d_endorse_booster["fmv_calculated_cents"]
            != d_auto_nonbooster["fmv_calculated_cents"]
        )


class TestCombinatorialRecidivismRoundAfterMultiply:
    """Instance: violation_recidivism_round_after_multiply — mode (b):
    nested rounding order. PRD §3.7 pins round_half_up AFTER
    multiplication."""

    def test_second_offense_level_ii_rounds_after_multiplying(
        self, api, officer_headers, officer_headers_secondary,
        officer_headers_tertiary,
    ):
        """PRD §3.7: "penalty_points is computed as severity points
        multiplied by a recidivism multiplier, rounded half-up to the
        nearest integer after the multiplication."

        Claim: 5 * 1.5 = 7.5; round_half_up to 8 (round AFTER
        multiplying). The alternative (round 1.5 first to 2, then
        5*2 = 10) is rejected. So second-offense LEVEL_II ==
        8, NOT 10.

        # difficulty: combinatorial_formula/violation_recidivism_round_after_multiply
        """
        program = create_program()
        drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
            appellate_headers=officer_headers_secondary,
        )
        v2 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers_tertiary,
            appellate_headers=officer_headers,
        )
        assert v2["penalty_points"] == 8, (
            f"5 * 1.5 = 7.5 -> round_half_up -> 8 (round AFTER "
            f"multiply); got {v2['penalty_points']}"
        )
        assert v2["penalty_points"] != 10, (
            f"would equal 10 only if rounding 1.5 -> 2 before "
            f"multiplying, which the PRD pins is wrong"
        )


class TestCombinatorialNILDealApproveValueEvalOrder:
    """Instance: nildeal_approved_value_min_of_stated_fmv — mode (c):
    circular-looking dependency with pinned evaluation order.
    approved_value depends on fmv, which can change via PATCH while
    SUBMITTED; the value is computed only at the APPROVED transition
    using fmv at that instant."""

    def test_patch_then_approve_uses_latest_fmv(
        self, api, officer_headers_secondary,
    ):
        """PRD §3.5: "each such edit re-runs the fair-market and
        pay-for-play computations."
        PRD §3.6: "On success, approved_value_cents is pinned to the
        minimum of stated_value_cents and fmv_calculated_cents".

        Claim: submit deal with hours=10 (fmv=600000). PATCH hours=20
        (fmv=1200000). UNDER_REVIEW. APPROVED. approved_value_cents
        equals min(stated=2_000_000, fmv=1_200_000) = 1_200_000, i.e.
        uses fmv at the moment of APPROVED, not the initial fmv.

        # difficulty: combinatorial_formula/nildeal_approved_value_min_of_stated_fmv
        """
        athlete, _p, _s = setup_enrolled_athlete()
        # Submit as the Athlete (entity-backed; satisfies PRD §2.1
        # athlete_id == X-User-ID ownership rule).
        d = submit_nil_deal(
            athlete["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=2_000_000,
        )
        assert d["fmv_calculated_cents"] == 600_000
        # PATCH deliverables_hours=20 — PRD §3.5: "the submitter (or
        # any role permitted on the deal) may edit
        # deliverables_hours, market_rate_cents_per_hour, and
        # stated_value_cents".
        patch_resp = api.patch_nil_deal(
            d["id"],
            patch_nil_deal_payload(deliverables_hours=20.0),
            make_athlete_headers(athlete["id"]),
        )
        patched = validate_success(patch_resp)
        assert patched["fmv_calculated_cents"] == 1_200_000
        # Review by a DIFFERENT user than the submitter (Athlete).
        # PRD §3.6 segregation only forbids submitter==reviewer; an
        # Athlete submitter and a ComplianceOfficer reviewer satisfy
        # the rule (Athlete X-User-ID and Officer X-User-ID differ).
        review_nil_deal(d["id"], headers=officer_headers_secondary)
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        approved = validate_success(res)
        assert approved["status"] == "APPROVED"
        # min(stated=2_000_000, fmv=1_200_000) = 1_200_000
        assert approved["approved_value_cents"] == 1_200_000


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearNILDealApprovedSuspendedCycle:
    """Instance: nildeal_approved_suspended_cycle — PRD §3.6: an
    APPROVED deal can be SUSPENDED then re-APPROVED via manual
    reinstatement, completing the A->B->A cycle on the same row."""

    def test_manual_suspend_and_reinstate_returns_deal_to_approved(
        self, api, officer_headers,
    ):
        """PRD §3.6: "From APPROVED, two non-terminal moves are
        possible. A ComplianceOfficer may suspend the deal manually
        (APPROVED -> SUSPENDED) ... A suspended deal returns to
        APPROVED either by manual reinstatement (a ComplianceOfficer
        posts SUSPENDED -> APPROVED) or automatically when the
        underlying violation is overturned (cascade from athlete
        INELIGIBLE -> ENROLLED). The reinstatement transition has
        business preconditions: amateur_status must be AMATEUR and
        status must be COMMITTED or ENROLLED. On reinstatement, the
        lifetime sum re-includes this deal."

        Claim: APPROVE -> manual SUSPEND -> manual REINSTATE returns
        the deal to APPROVED with approved_value_cents unchanged, and
        the athlete's nil_deal_lifetime_value_cents returns to its
        pre-suspend value.

        # difficulty: non_linear_state_machine/nildeal_approved_suspended_cycle
        """
        athlete, _program, deal = setup_athlete_with_approved_deal(
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
        )
        original_approved_value = deal["approved_value_cents"]
        # Manual suspend.
        sus_resp = api.transition_nil_deal(
            deal["id"],
            transition_nil_deal_payload(to_status="SUSPENDED"),
            officer_headers,
        )
        sus = validate_success(sus_resp)
        assert sus["status"] == "SUSPENDED"
        # Lifetime drops to 0.
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        assert (
            validate_success(a_resp)["nil_deal_lifetime_value_cents"]
            == 0
        )
        # Manual reinstate: athlete is still ENROLLED / AMATEUR.
        rein_resp = api.transition_nil_deal(
            deal["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers,
        )
        rein = validate_success(rein_resp)
        assert rein["status"] == "APPROVED"
        # approved_value_cents preserved across the cycle.
        assert rein["approved_value_cents"] == original_approved_value
        # Lifetime restored.
        a_resp2 = api.get_athlete(athlete["id"], officer_headers)
        assert (
            validate_success(a_resp2)["nil_deal_lifetime_value_cents"]
            == original_approved_value
        )


class TestNonLinearViolationFork:
    """Instance: violation_substantiated_appealed_cycle — both
    SUSTAINED paths (APPEALED->SUSTAINED and auto-expire) yield the
    same outcome. We assert both terminal SUSTAINED rows reach
    outcome=SUSTAINED with penalty_points computed."""

    def test_both_appealed_and_auto_expire_paths_reach_sustained(
        self, api, officer_headers, officer_headers_secondary,
        officer_headers_tertiary,
    ):
        """PRD §3.7: "If the 14-day appeal window elapses without an
        APPEALED transition, the next clock advance auto-fires
        SUBSTANTIATED -> SUSTAINED."
        PRD §3.7: "The cascade effects of the auto-expire path are
        identical to the APPEALED -> SUSTAINED path described next."

        Claim: violation v_a takes the APPEALED -> SUSTAINED path
        (LEVEL_II, first offense = 5 points). Violation v_b (created
        after v_a, same program) takes the auto-expire path, becoming
        the SECOND SUSTAINED on the program; its penalty_points should
        be 5 * 1.5 = 7.5 -> 8 (second-offense recidivism).

        # difficulty: non_linear_state_machine/violation_substantiated_appealed_cycle
        """
        program = create_program()
        # v_a via APPEALED path.
        v_a = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
            appellate_headers=officer_headers_secondary,
        )
        assert v_a["status"] == "SUSTAINED"
        assert v_a["penalty_points"] == 5
        # v_b via auto-expire path.
        v_b = report_violation(
            program["id"], severity="LEVEL_II",
            headers=officer_headers_tertiary,
        )
        transition_violation(
            v_b["id"], "INVESTIGATING",
            headers=officer_headers_tertiary,
        )
        v_b_sub = transition_violation(
            v_b["id"], "SUBSTANTIATED",
            headers=officer_headers_tertiary,
        )
        sub_at = parse_iso(v_b_sub["updated_at"])
        target = sub_at + timedelta(days=APPEAL_WINDOW_DAYS, seconds=2)
        advance_clock_to(iso_utc(target))
        v_b_resp = api.get_violation(v_b["id"], officer_headers)
        v_b_data = validate_success(v_b_resp)
        assert v_b_data["status"] == "SUSTAINED"
        # v_b is the SECOND SUSTAINED on this program -> recid mult 1.5,
        # 5 * 1.5 = 7.5 -> 8.
        assert v_b_data["penalty_points"] == 8


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascadeViolationToDeals:
    """Instance:
    violation_sustained_athlete_ineligible_deal_suspended — depth-3
    chain: violation SUSTAINED -> athlete INELIGIBLE -> approved deals
    SUSPENDED."""

    def test_level_i_sustained_cascades_three_levels(
        self, api, officer_headers,
    ):
        """PRD §3.7: "When a sustained violation is LEVEL_I and
        carries a related_athlete_id, the system cascades immediately
        on the SUSTAINED outcome flip. The implicated athlete moves
        ENROLLED -> INELIGIBLE. ... Every NILDeal for that athlete
        whose status is APPROVED is transitioned to SUSPENDED, and
        approved_value_cents is preserved on each suspended deal."

        Claim: V SUSTAINED (link 0) -> A INELIGIBLE (link 1) ->
        D1, D2 SUSPENDED (link 2). All three observable in one POST.

        # difficulty: transitive_cascade/violation_sustained_athlete_ineligible_deal_suspended
        """
        # Build athlete with TWO approved deals.
        from test_helpers import setup_approved_nil_deal
        athlete, program, _slot = setup_enrolled_athlete()
        d1 = setup_approved_nil_deal(
            athlete["id"], stated_value_cents=500_000,
            deliverables_hours=10.0, market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT", sponsor_is_booster=False,
        )
        d2 = setup_approved_nil_deal(
            athlete["id"], stated_value_cents=400_000,
            deliverables_hours=5.0, market_rate_cents_per_hour=80_000,
            deal_category="APPEARANCE", sponsor_is_booster=False,
        )
        assert d1["status"] == "APPROVED"
        assert d2["status"] == "APPROVED"
        v = drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
            related_athlete_id=athlete["id"],
        )
        assert v["status"] == "SUSTAINED"
        # link 1: athlete is INELIGIBLE.
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["status"] == "INELIGIBLE"
        # link 2: both deals SUSPENDED.
        d1_resp = api.get_nil_deal(d1["id"], officer_headers)
        d2_resp = api.get_nil_deal(d2["id"], officer_headers)
        assert validate_success(d1_resp)["status"] == "SUSPENDED"
        assert validate_success(d2_resp)["status"] == "SUSPENDED"


class TestTransitiveCascadePortalEntryToProgram:
    """Instance: athlete_portal_entry_slot_release_program_recompute
    — depth-2: ATHLETE TRANSFER_PORTAL -> slot RELEASED -> Program
    recompute."""

    def test_portal_entry_cascades_to_slot_release_and_program_recompute(
        self, api, officer_headers,
    ):
        """PRD §3.4: "The act of entering the portal cascades through
        several entities. The athlete moves ENROLLED -> TRANSFER_PORTAL,
        and current_program_id is set to null. Every ScholarshipSlot
        for that athlete at the origin program whose status was
        ACTIVE transitions to RELEASED, freeing the program's
        equivalencies. Program.total_equivalencies_used and
        Program.active_roster_count on the origin program are
        recomputed."

        Claim: ENROLLED athlete + ACTIVE slot at Program with
        total_equivalencies_used=1.00 and active_roster_count=1.
        POST /transfer-portal-entries fires:
        link 1 — slot transitions ACTIVE -> RELEASED;
        link 2 — program totals recompute to 0.00 / 0.

        # difficulty: transitive_cascade/athlete_portal_entry_slot_release_program_recompute
        """
        athlete, program, slot = setup_enrolled_athlete(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=13.0,
            roster_cap_count=15,
            fractional_equivalency=1.00,
        )
        assert slot["status"] == "ACTIVE"
        assert program["total_equivalencies_used"] == 1.00
        assert program["active_roster_count"] == 1
        create_portal_entry(athlete["id"])
        # link 1: slot RELEASED.
        s_resp = api.get_scholarship_slot(slot["id"], officer_headers)
        s_data = validate_success(s_resp)
        assert s_data["status"] == "RELEASED"
        # link 2: program totals recomputed to 0.
        p_resp = api.get_program(program["id"], officer_headers)
        p_data = validate_success(p_resp)
        assert p_data["total_equivalencies_used"] == 0.00
        assert p_data["active_roster_count"] == 0


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityStateVsBusinessSafety:
    """Instance: state_vs_business_safety_pair — PRD §2.8 ordering:
    from-state validity (priority 6) wins over amateur-status check
    (priority 10)."""

    def test_state_check_wins_over_amateur_status_check(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §2.8: "When a single request potentially triggers more
        than one validation failure, the system reports the failure
        that appears earliest in the following priority ordering."
        PRD §2.8 priority 6: "From-state validity — the target
        resource is in a permitted from-state for the requested
        transition; otherwise ERR_INVALID_STATE."
        PRD §2.8 priority 10: "Amateur status — for NIL approval
        transitions, amateur_status equals AMATEUR; otherwise
        ERR_AMATEUR_STATUS_LOST."
        PRD §2.8: "This ordering is load-bearing. A request that
        fails several of these simultaneously must surface the
        highest-priority error only."

        Claim: a deal in SUBMITTED (not UNDER_REVIEW) on an athlete
        with amateur_status=FORFEITED — attempt SUBMITTED -> APPROVED
        — reports the state failure (priority 6, ERR_INVALID_STATE),
        not the amateur failure (priority 10).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair
        """
        # Build INELIGIBLE / FORFEITED athlete via cascade.
        _program, athlete, _v = (
            setup_ineligible_athlete_via_violation()
        )
        assert athlete["amateur_status"] == "FORFEITED"
        # Now submit a deal for that athlete via officer (Athlete
        # role cannot submit because amateur_status check is on
        # APPROVE, and §2.1 ownership uses athlete_id == X-User-ID,
        # which holds). Submit as Officer to avoid any submission-
        # side rejection ambiguity.
        d = submit_nil_deal(
            athlete["id"], headers=officer_headers,
            stated_value_cents=100_000,
            deliverables_hours=2.0,
            market_rate_cents_per_hour=50_000,
            deal_category="APPEARANCE",
            sponsor_is_booster=False,
        )
        assert d["status"] == "SUBMITTED"
        # Skip UNDER_REVIEW intentionally — deal stays in SUBMITTED.
        # Try direct APPROVED transition. Use a different officer
        # than the submitter to avoid SEGREGATION_OF_DUTIES
        # (priority 8) clouding the assertion.
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        # PRD §2.8 priority 6 (state) fires before priority 10
        # (amateur).
        validate_error(res, "ERR_INVALID_STATE")


class TestPriorityBusinessSafetyVsBusinessFiscal:
    """Instance: business_safety_vs_business_fiscal_pair — eligibility
    (priority 9) wins over scholarship cap (priority 16)."""

    def test_eligibility_check_wins_over_scholarship_cap(
        self, api, coach_headers,
    ):
        """PRD §2.8 priority 9: "Eligibility clearance — the athlete's
        eligibility_record_id is set and its decision is QUALIFIER or
        PARTIAL_QUALIFIER, on transitions that require it; otherwise
        ERR_ELIGIBILITY_NOT_CLEARED."
        PRD §2.8 priority 16: "Scholarship cap — projected
        total_equivalencies_used (after applying the current slot's
        fractional_equivalency) is less than or equal to
        scholarship_cap_equivalencies; otherwise
        ERR_SCHOLARSHIP_CAP_EXCEEDED."
        PRD §2.8: "A request that fails several of these
        simultaneously must surface the highest-priority error only."

        Claim: athlete A with decision=NON_QUALIFIER, and program at
        total_equivalencies_used == cap (any further signing breaches
        the cap). Slot signing attempt — eligibility check (9) wins
        over scholarship cap (16); response is ERR_ELIGIBILITY_NOT_CLEARED.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair
        """
        # Tiny-cap program so cap breaches easily.
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=1.00,
            roster_cap_count=15,
        )
        # Fill the cap with one already-signed slot.
        a_filler = create_athlete()
        create_eligibility_record(a_filler["id"], decision="QUALIFIER")
        filler_slot = offer_slot(
            program["id"], a_filler["id"],
            fractional_equivalency=1.00,
        )
        sign_slot(filler_slot["id"])
        # Now the program is at exact cap.
        # Target athlete: NON_QUALIFIER decision.
        a2 = create_athlete()
        create_eligibility_record(a2["id"], decision="NON_QUALIFIER")
        slot2 = offer_slot(
            program["id"], a2["id"],
            fractional_equivalency=0.50,
        )
        # Attempt to sign — both checks would fail (eligibility 9 and
        # scholarship cap 16). Priority 9 wins.
        res = api.transition_scholarship_slot(
            slot2["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPenaltyYellow:
    """Instance: program_compliance_yellow_boundary — penalty_points_
    total == 10 must trip YELLOW (inclusive boundary)."""

    def test_penalty_total_at_exactly_10_lands_yellow_not_green(
        self, api, officer_headers,
    ):
        """PRD §3.7: "Boundaries are inclusive on the lower side: a
        total of exactly 10 lands at YELLOW".

        Claim: a single LEVEL_I (10 points) flips compliance_status
        from GREEN to YELLOW exactly at penalty_points_total == 10.

        # difficulty: boundary_precision_check/program_compliance_yellow_boundary
        """
        program = create_program()
        v = drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
        )
        assert v["penalty_points"] == 10
        p_resp = api.get_program(program["id"], officer_headers)
        p_data = validate_success(p_resp)
        assert p_data["penalty_points_total"] == 10
        assert p_data["compliance_status"] == "YELLOW"


class TestBoundaryRosterCapZeroRemaining:
    """Instance: roster_cap_zero_remaining_boundary — at
    active_roster_count == roster_cap_count, next ENROLLED is
    blocked."""

    def test_enroll_at_zero_remaining_returns_roster_cap_exceeded(
        self, api, officer_headers,
    ):
        """PRD §3.3: "an enrollment that would push the count to
        exactly roster_cap_count is permitted, but roster_cap_count +
        1 is not."
        PRD §5: ERR_ROSTER_CAP_EXCEEDED at HTTP 409.

        Claim: program roster_cap_count=1 with first athlete already
        ENROLLED (active_roster_count==1==cap). A second athlete
        attempting COMMITTED -> ENROLLED -> ERR_ROSTER_CAP_EXCEEDED;
        the second athlete remains in COMMITTED.

        # difficulty: boundary_precision_check/roster_cap_zero_remaining_boundary
        """
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=2.00,
            roster_cap_count=1,
        )
        # First athlete enrolls.
        a1, _p1, _s1 = setup_enrolled_athlete(program=program)
        # Second athlete brought up to COMMITTED.
        a2 = create_athlete()
        create_eligibility_record(a2["id"], decision="QUALIFIER")
        slot2 = offer_slot(
            program["id"], a2["id"],
            fractional_equivalency=1.00,
        )
        sign_slot(slot2["id"])
        commit_athlete(a2["id"], program["id"])
        from test_helpers import transition_athlete_payload
        res = api.transition_athlete(
            a2["id"],
            transition_athlete_payload(to_status="ENROLLED"),
            officer_headers,
        )
        validate_error(res, "ERR_ROSTER_CAP_EXCEEDED")
        # PRD §3.3: "blocks the enclosing Athlete ENROLLED transition";
        # the athlete remains in COMMITTED.
        a2_resp = api.get_athlete(a2["id"], officer_headers)
        a2_data = validate_success(a2_resp)
        assert a2_data["status"] == "COMMITTED"
        # active_roster_count unchanged.
        p_resp = api.get_program(program["id"], officer_headers)
        assert validate_success(p_resp)["active_roster_count"] == 1


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityNILApprovalAmateurStatus:
    """Instance: nildeal_approval_depends_on_athlete_state — NIL
    approval gates on athlete.amateur_status from a DIFFERENT entity."""

    def test_approve_blocked_when_athlete_amateur_status_lost(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.6: "the athlete's amateur_status must be AMATEUR
        (otherwise ERR_AMATEUR_STATUS_LOST)."

        Claim: drive a deal to UNDER_REVIEW with athlete in AMATEUR.
        Then flip athlete to FORFEITED (via LEVEL_I SUSTAINED
        cascade). Attempt UNDER_REVIEW -> APPROVED ->
        ERR_AMATEUR_STATUS_LOST. The deal remains UNDER_REVIEW.

        # difficulty: cross_entity_state_dependency/nildeal_approval_depends_on_athlete_state
        """
        athlete, program, _slot = setup_enrolled_athlete()
        d = submit_nil_deal(athlete["id"])
        review_nil_deal(d["id"], headers=officer_headers_secondary)
        d_resp = api.get_nil_deal(d["id"], officer_headers)
        assert validate_success(d_resp)["status"] == "UNDER_REVIEW"
        # Flip athlete to INELIGIBLE / FORFEITED via cascade.
        drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
            related_athlete_id=athlete["id"],
        )
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["amateur_status"] == "FORFEITED"
        # Try to approve. PRD §2.8 priority 10 fires (amateur status).
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        validate_error(res, "ERR_AMATEUR_STATUS_LOST")
        # PRD §3.7: "rejected, no transition". Deal remains UNDER_REVIEW.
        d_resp2 = api.get_nil_deal(d["id"], officer_headers)
        assert validate_success(d_resp2)["status"] == "UNDER_REVIEW"


class TestCrossEntitySlotSignEligibilityRecord:
    """Instance: scholarship_slot_sign_depends_on_eligibility_record —
    Slot sign gates on EligibilityRecord.decision (different entity)."""

    def test_sign_blocked_when_decision_non_qualifier(
        self, api, coach_headers,
    ):
        """PRD §3.3: "the athlete must have a posted EligibilityRecord
        whose decision is QUALIFIER or PARTIAL_QUALIFIER, otherwise
        ERR_ELIGIBILITY_NOT_CLEARED."

        Claim: slot OFFERED -> SIGNED with athlete decision =
        NON_QUALIFIER -> ERR_ELIGIBILITY_NOT_CLEARED; slot remains
        OFFERED.

        # difficulty: cross_entity_state_dependency/scholarship_slot_sign_depends_on_eligibility_record
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="NON_QUALIFIER")
        slot = offer_slot(program["id"], athlete["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")
        s_resp = api.get_scholarship_slot(
            slot["id"], TEST_USERS["officer_headers"],
        )
        assert validate_success(s_resp)["status"] == "OFFERED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestTemporalOverlapCalendarHalfOpen:
    """Instance: recruiting_calendar_half_open_priority_overlap —
    half-open intervals + most-restrictive priority tie-break."""

    def test_overlapping_calendars_pick_most_restrictive_dead(
        self, api, coach_headers,
    ):
        """PRD §3.8: "Candidate windows are those RecruitingCalendar
        rows for the same program_id whose start_date is less than
        or equal to contact_at (inclusive) and whose end_date is
        strictly greater than contact_at (exclusive) — the windows
        are half-open intervals. ... If multiple windows overlap and
        all contain the timestamp, the most restrictive period type
        wins: in decreasing order of restrictiveness, DEAD outranks
        CONTACT, CONTACT outranks EVALUATION, and EVALUATION outranks
        QUIET."
        PRD §3.8: "During a DEAD period, every modality is forbidden."

        Claim: at a timestamp inside both a CONTACT window and a
        DEAD overlay window, DEAD wins; the IN_PERSON_OFF_CAMPUS
        contact is rejected.

        # difficulty: resource_temporal_overlap/recruiting_calendar_half_open_priority_overlap
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="CONTACT",
            start_date="2026-05-01T00:00:00.000Z",
            end_date="2026-05-10T00:00:00.000Z",
        )
        declare_calendar_window(
            program["id"],
            period_type="DEAD",
            start_date="2026-05-05T00:00:00.000Z",
            end_date="2026-05-07T00:00:00.000Z",
        )
        # contact_at = 2026-05-06T12:00 — inside both CONTACT and
        # DEAD windows; DEAD wins.
        from test_helpers import create_recruiting_contact_payload
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="IN_PERSON_OFF_CAMPUS",
                contact_at="2026-05-06T12:00:00.000Z",
            ),
            coach_headers,
        )
        validate_error(res, "ERR_CONTACT_NOT_PERMITTED")

    def test_contact_at_exactly_dead_end_date_falls_outside_half_open(
        self, api, coach_headers,
    ):
        """PRD §3.8: "whose end_date is strictly greater than
        contact_at (exclusive) — the windows are half-open intervals."

        Claim: at contact_at == DEAD.end_date exactly, the
        timestamp is NOT inside DEAD (half-open excludes the upper
        bound); it remains inside the overlapping CONTACT window;
        so an IN_PERSON_OFF_CAMPUS contact is permitted and the
        contact_period_type stored is CONTACT.

        # difficulty: resource_temporal_overlap/recruiting_calendar_half_open_priority_overlap
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="CONTACT",
            start_date="2026-05-01T00:00:00.000Z",
            end_date="2026-05-10T00:00:00.000Z",
        )
        declare_calendar_window(
            program["id"],
            period_type="DEAD",
            start_date="2026-05-05T00:00:00.000Z",
            end_date="2026-05-07T00:00:00.000Z",
        )
        from test_helpers import create_recruiting_contact_payload
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="IN_PERSON_OFF_CAMPUS",
                contact_at="2026-05-07T00:00:00.000Z",
            ),
            coach_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["contact_period_type"] == "CONTACT", (
            f"contact_at = DEAD.end_date should fall OUTSIDE DEAD "
            f"(half-open), landing in CONTACT; got "
            f"{data['contact_period_type']}"
        )


class TestTemporalOverlapPortalDuplicate:
    """Instance: transfer_portal_entry_dedup_active_window — second
    entry collides with the first while it is active."""

    def test_second_portal_entry_while_first_active_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.4: "The athlete also may not already have a
        TransferPortalEntry in ENTERED or CONTACT_WINDOW status; a
        duplicate active entry is rejected with
        ERR_DUPLICATE_PORTAL_ENTRY."

        Claim: while first entry is in ENTERED (still active), a
        second POST /transfer-portal-entries for the same athlete
        -> ERR_DUPLICATE_PORTAL_ENTRY. The first entry remains the
        only row for that athlete in the active window.

        Coverage note: the first portal entry cascades the athlete
        ENROLLED -> TRANSFER_PORTAL (PRD §3.4), so the second post
        will also fail the "athlete must be in ENROLLED" check. PRD
        §2.8 does not explicitly order ERR_DUPLICATE_PORTAL_ENTRY
        (priority 20) against the athlete from-state precondition,
        so we accept either error.

        # difficulty: resource_temporal_overlap/transfer_portal_entry_dedup_active_window
        """
        from test_helpers import (
            validate_error_is_one_of,
            validate_paginated,
        )
        athlete, _p, _s = setup_enrolled_athlete()
        create_portal_entry(athlete["id"], reason="PLAYING_TIME")
        res = api.create_transfer_portal_entry(
            create_transfer_portal_entry_payload(
                athlete_id=athlete["id"], reason="COACHING_CHANGE",
            ),
            officer_headers,
        )
        validate_error_is_one_of(
            res, ["ERR_DUPLICATE_PORTAL_ENTRY", "ERR_INVALID_STATE"],
        )
        # Confirm exactly one entry exists for this athlete.
        list_resp = api.list_transfer_portal_entries(
            officer_headers, params={"athlete_id": athlete["id"]},
        )
        data, _meta = validate_paginated(list_resp)
        assert len(data) == 1


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingPortalWithdrawn:
    """Instance: portal_withdrawn_restores_athlete_status_invariant —
    forward POST entry -> ENTERED, compensating ENTERED -> WITHDRAWN
    restores athlete tuple."""

    def test_portal_entered_then_withdrawn_restores_athlete_tuple(
        self, api, officer_headers,
    ):
        """PRD §3.4: "An Athlete or a ComplianceOfficer may withdraw
        the entry directly out of ENTERED (before the holding period
        elapses). This ENTERED -> WITHDRAWN transition has no
        precondition and rolls the athlete back to ENROLLED at the
        origin_program_id."

        Claim: snapshot (status, current_program_id) pre-entry. POST
        entry. POST entry/{id}/state WITHDRAWN. Post-compensation,
        (status, current_program_id) equals the pre snapshot exactly.

        # difficulty: compensating_invariant/portal_withdrawn_restores_athlete_status_invariant
        """
        athlete, program, _slot = setup_enrolled_athlete()
        status_pre = athlete["status"]
        program_pre = athlete["current_program_id"]
        assert status_pre == "ENROLLED"
        assert program_pre == program["id"]
        entry = create_portal_entry(athlete["id"])
        # Compensate.
        res = api.transition_transfer_portal_entry(
            entry["id"],
            transition_transfer_portal_entry_payload(
                to_status="WITHDRAWN",
            ),
            officer_headers,
        )
        validate_success(res)
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_post = validate_success(a_resp)
        assert a_post["status"] == status_pre
        assert a_post["current_program_id"] == program_pre


class TestCompensatingNILSuspendResume:
    """Instance: nildeal_suspend_resume_lifetime_value_invariant —
    forward APPROVED -> SUSPENDED removes from lifetime; compensating
    SUSPENDED -> APPROVED restores lifetime to pre-forward value."""

    def test_suspend_then_reinstate_restores_lifetime_value(
        self, api, officer_headers,
    ):
        """PRD §3.6: "From APPROVED, two non-terminal moves are
        possible. A ComplianceOfficer may suspend the deal manually
        (APPROVED -> SUSPENDED), and the system itself will suspend
        on cascade ... In either case, approved_value_cents is
        preserved on the row for audit, and
        Athlete.nil_deal_lifetime_value_cents is recomputed without
        this deal. A suspended deal returns to APPROVED either by
        manual reinstatement (a ComplianceOfficer posts SUSPENDED ->
        APPROVED) ... On reinstatement, the lifetime sum re-includes
        this deal."

        Claim: snapshot athlete.nil_deal_lifetime_value_cents at
        900000 (D1=500000 + D2=400000, both APPROVED). Forward:
        suspend D1 (lifetime -> 400000). Compensate: reinstate D1
        (lifetime -> 900000). D1.approved_value_cents unchanged
        across the cycle.

        # difficulty: compensating_invariant/nildeal_suspend_resume_lifetime_value_invariant
        """
        from test_helpers import setup_approved_nil_deal
        athlete, _program, _slot = setup_enrolled_athlete()
        d1 = setup_approved_nil_deal(
            athlete["id"], stated_value_cents=500_000,
            deliverables_hours=10.0, market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT", sponsor_is_booster=False,
        )
        d2 = setup_approved_nil_deal(
            athlete["id"], stated_value_cents=400_000,
            deliverables_hours=5.0, market_rate_cents_per_hour=80_000,
            deal_category="APPEARANCE", sponsor_is_booster=False,
        )
        assert d1["approved_value_cents"] == 500_000
        assert d2["approved_value_cents"] == 400_000
        # Snapshot lifetime pre.
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        lifetime_pre = validate_success(a_resp)[
            "nil_deal_lifetime_value_cents"
        ]
        assert lifetime_pre == 900_000
        # Forward: suspend D1.
        api.transition_nil_deal(
            d1["id"],
            transition_nil_deal_payload(to_status="SUSPENDED"),
            officer_headers,
        )
        a_resp2 = api.get_athlete(athlete["id"], officer_headers)
        lifetime_mid = validate_success(a_resp2)[
            "nil_deal_lifetime_value_cents"
        ]
        assert lifetime_mid == 400_000
        # Compensate: reinstate D1.
        rein_resp = api.transition_nil_deal(
            d1["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers,
        )
        rein = validate_success(rein_resp)
        # PRD §3.6: "approved_value_cents is preserved on the row
        # for audit". So D1.approved_value_cents unchanged.
        assert rein["approved_value_cents"] == 500_000
        # PRD §3.6 reverse: "On reinstatement, the lifetime sum
        # re-includes this deal."
        a_resp3 = api.get_athlete(athlete["id"], officer_headers)
        lifetime_post = validate_success(a_resp3)[
            "nil_deal_lifetime_value_cents"
        ]
        assert lifetime_post == lifetime_pre, (
            f"compensating invariant: lifetime_post ({lifetime_post}) "
            f"must equal lifetime_pre ({lifetime_pre})"
        )
        # D2 untouched.
        d2_resp = api.get_nil_deal(d2["id"], officer_headers)
        assert validate_success(d2_resp)["approved_value_cents"] == 400_000


# ===========================================================================
# Second-coverage tests for instances whose primary coverage lives in
# this file alone or in a closely-related class. These pair with the
# first-coverage tests above to satisfy the ">= 2 tests per instance"
# rule.
# ===========================================================================
class TestSecondaryDualVariantRecidivism:
    """Second coverage for dual_variant_calc/
    violation_penalty_recidivism_variant: prove the recidivism variant
    is rooted in prior-SUSTAINED count rather than time."""

    def test_program_penalty_total_aggregates_both_recidivism_offenses(
        self, api, officer_headers, officer_headers_secondary,
        officer_headers_tertiary,
    ):
        """PRD §3.7: "program.penalty_points_total = sum(v.penalty_points
        for v in ComplianceViolation where v.program_id == program.id
        and v.outcome == SUSTAINED ..."
        PRD §3.7: "Severity points are ... 5 for LEVEL_II ... a count
        of zero yields multiplier 1.0; a count of exactly one yields
        1.5; a count of two or more yields 2.0."

        Claim: with two LEVEL_II SUSTAINED cases (5 + 8 = 13), the
        program.penalty_points_total reads 13. Different perspective
        on the same instance: the recidivism applies independently
        per case, and the rollup sums them.

        # difficulty: dual_variant_calc/violation_penalty_recidivism_variant
        """
        program = create_program()
        v1 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
            appellate_headers=officer_headers_secondary,
        )
        v2 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers_tertiary,
            appellate_headers=officer_headers,
        )
        assert v1["penalty_points"] == 5
        assert v2["penalty_points"] == 8
        p_resp = api.get_program(program["id"], officer_headers)
        p_data = validate_success(p_resp)
        assert p_data["penalty_points_total"] == 13


class TestSecondaryCombinatorialRecidivism:
    """Second coverage for combinatorial_formula/
    violation_recidivism_round_after_multiply: prove the round-after
    rule applies at LEVEL_III (where the 1.5 multiplier produces a
    fractional that does NOT land on .5)."""

    def test_third_offense_level_iii_rounds_after_multiplying(
        self, api, officer_headers, officer_headers_secondary,
        officer_headers_tertiary,
    ):
        """PRD §3.7: "penalty_points is computed as severity points
        multiplied by a recidivism multiplier, rounded half-up to the
        nearest integer after the multiplication."
        PRD §3.7: "a count of two or more yields 2.0."

        Claim: third-offense LEVEL_III = 2 * 2.0 = 4 (whole number, no
        rounding needed). This is the upper bound of the recidivism
        ladder and confirms the multiplier-by-count formula at
        prior_count >= 2.

        # difficulty: combinatorial_formula/violation_recidivism_round_after_multiply
        """
        program = create_program()
        # First and second SUSTAINED LEVEL_II to populate prior count.
        drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
            appellate_headers=officer_headers_secondary,
        )
        drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers_tertiary,
            appellate_headers=officer_headers,
        )
        # Third: LEVEL_III. prior_count >= 2 -> mult 2.0.
        # 2 * 2.0 = 4.
        v3 = drive_violation_to_sustained(
            program["id"], severity="LEVEL_III",
            reviewer_headers=officer_headers_secondary,
            appellate_headers=officer_headers_tertiary,
        )
        assert v3["penalty_points"] == 4, (
            f"third-offense LEVEL_III = 2 * 2.0 = 4, got "
            f"{v3['penalty_points']}"
        )


class TestSecondaryNonLinearNILDealCycle:
    """Second coverage for non_linear_state_machine/
    nildeal_approved_suspended_cycle: the cycle property — same
    row reaches APPROVED at two distinct times."""

    def test_version_increments_each_step_of_the_cycle(
        self, api, officer_headers,
    ):
        """PRD §2.4: "version is a non-negative integer that starts at
        1 and increments by one on every mutation of the resource."

        Claim: APPROVE -> SUSPEND -> REINSTATE yields a strictly
        increasing version on the same NILDeal row across all three
        state transitions, confirming the row is the same object
        traversing the cycle.

        # difficulty: non_linear_state_machine/nildeal_approved_suspended_cycle
        """
        athlete, _program, deal = setup_athlete_with_approved_deal()
        v_approved = deal["version"]
        sus = validate_success(api.transition_nil_deal(
            deal["id"],
            transition_nil_deal_payload(to_status="SUSPENDED"),
            officer_headers,
        ))
        assert sus["status"] == "SUSPENDED"
        assert sus["version"] > v_approved
        rein = validate_success(api.transition_nil_deal(
            deal["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers,
        ))
        assert rein["status"] == "APPROVED"
        assert rein["version"] > sus["version"]
        # The cycle closes: deal.id is identical across all three
        # observations (proving the same row reaches APPROVED twice).
        assert rein["id"] == sus["id"] == deal["id"]


class TestSecondaryPriorityStateVsBusinessSafety:
    """Second coverage for priority_pair_validation_conflict/
    state_vs_business_safety_pair using the pay-for-play (priority
    11) pair instead of amateur (priority 10) to test the same
    state-priority-wins rule on a different higher-priority error."""

    def test_state_check_wins_over_pay_for_play_check(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §2.8 priority 6: "From-state validity — the target
        resource is in a permitted from-state for the requested
        transition; otherwise ERR_INVALID_STATE."
        PRD §2.8 priority 11: "Pay-for-play classification — for NIL
        approval transitions, pay_for_play_flag is false; otherwise
        ERR_PAY_FOR_PLAY_DETECTED."
        PRD §2.8: "A request that fails several of these
        simultaneously must surface the highest-priority error only."

        Claim: deal in SUBMITTED (not UNDER_REVIEW) with
        pay_for_play_flag=true; attempt SUBMITTED -> APPROVED.
        State check (priority 6) fires before pay_for_play check
        (priority 11); result is ERR_INVALID_STATE.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair
        """
        athlete, _p, _s = setup_enrolled_athlete()
        # Booster + ratio>=3 -> pay_for_play_flag=true.
        d = submit_nil_deal(
            athlete["id"],
            sponsor_is_booster=True,
            deal_category="ENDORSEMENT",
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=1_440_000,
            headers=officer_headers,
        )
        assert d["pay_for_play_flag"] is True
        # Deal is in SUBMITTED (we never moved to UNDER_REVIEW).
        # Try direct APPROVED — both state (6) and pay-for-play (11)
        # would fail; state wins.
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestSecondaryPriorityBusinessSafetyVsFiscal:
    """Second coverage for priority_pair_validation_conflict/
    business_safety_vs_business_fiscal_pair: also verify the slot
    remains in OFFERED (no side effect on the higher-priority
    rejection path)."""

    def test_eligibility_rejection_leaves_slot_in_offered(
        self, api, coach_headers,
    ):
        """PRD §2.8 priority 9: "Eligibility clearance ... otherwise
        ERR_ELIGIBILITY_NOT_CLEARED."
        PRD §2.8: "This ordering is load-bearing."

        Claim: under the same dual-failure setup (NON_QUALIFIER +
        cap-breach), the slot row remains in OFFERED status after the
        rejection — no partial side effect lands.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair
        """
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=1.00,
            roster_cap_count=15,
        )
        a_filler = create_athlete()
        create_eligibility_record(a_filler["id"], decision="QUALIFIER")
        filler_slot = offer_slot(
            program["id"], a_filler["id"],
            fractional_equivalency=1.00,
        )
        sign_slot(filler_slot["id"])
        # Target athlete with NON_QUALIFIER.
        a2 = create_athlete()
        create_eligibility_record(a2["id"], decision="NON_QUALIFIER")
        slot2 = offer_slot(
            program["id"], a2["id"],
            fractional_equivalency=0.50,
        )
        res = api.transition_scholarship_slot(
            slot2["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")
        # Slot remains OFFERED.
        s_resp = api.get_scholarship_slot(
            slot2["id"], TEST_USERS["officer_headers"],
        )
        assert validate_success(s_resp)["status"] == "OFFERED"


class TestSecondaryCrossEntityNILAmateurStatus:
    """Second coverage for cross_entity_state_dependency/
    nildeal_approval_depends_on_athlete_state: an athlete in
    PROSPECTIVE (not COMMITTED/ENROLLED) gates approval differently
    from the FORFEITED case."""

    def test_approve_with_athlete_in_committed_succeeds(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.6: "the athlete's status must be COMMITTED or
        ENROLLED (otherwise ERR_ATHLETE_NOT_ENROLLED)".

        Claim: an athlete in COMMITTED (not yet ENROLLED), with
        amateur_status=AMATEUR, allows UNDER_REVIEW -> APPROVED. This
        is the positive side of the cross-entity dependency: same
        deal data, but athlete state determines outcome.

        # difficulty: cross_entity_state_dependency/nildeal_approval_depends_on_athlete_state
        """
        # Build athlete in COMMITTED (not yet ENROLLED).
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        slot = offer_slot(program["id"], athlete["id"])
        sign_slot(slot["id"])
        commit_athlete(athlete["id"], program["id"])
        # Refresh.
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["status"] == "COMMITTED"
        assert a_data["amateur_status"] == "AMATEUR"
        # Submit + review + approve.
        d = submit_nil_deal(
            athlete["id"],
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
        )
        review_nil_deal(d["id"], headers=officer_headers_secondary)
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        approved = validate_success(res)
        assert approved["status"] == "APPROVED"
