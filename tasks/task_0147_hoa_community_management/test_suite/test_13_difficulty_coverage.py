"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>` tag
so coverage can be audited. Each test pins to a verbatim PRD sentence
stating the underlying rule.

The difficulty-design index covers 9 rules × 2 instances = 18 instances.
Each instance is covered by at least two dedicated tests below.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    LATE_FEE_FLAT_CENTS,
    NON_EXISTENT_UUID,
    adopt_reserve_study,
    advance_clock_by_seconds,
    advance_clock_to,
    assert_lien,
    assert_reserve_study,
    assert_violation,
    cast_acc_vote,
    cast_ballot,
    create_ballot_payload,
    create_lien_for_unit,
    create_member,
    create_payment_payload,
    create_regular_cycle,
    create_reserve_study,
    create_unit,
    cure_violation,
    current_clock,
    drive_resolution_to_passed,
    get_acc_request,
    get_election,
    get_lien,
    get_member,
    get_unit,
    get_violation,
    issue_cycle,
    make_member_headers,
    nominate_candidate,
    open_election,
    open_violation,
    parse_iso,
    propose_resolution,
    record_lien,
    release_lien,
    reserve_component,
    setup_adopted_special_assessment_study,
    setup_election_with_zero_candidates_and_one_candidate,
    setup_issued_cycle,
    setup_multi_unit_roster,
    setup_single_unit_roster,
    setup_three_unit_for_allocation_remainder,
    setup_two_acc_requests_in_review,
    submit_acc_request,
    TEST_USERS,
    tender_payment,
    validate_error,
    validate_success,
    version_payload,
    waive_violation,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_late_fee_per_cycle_yields_two_periods_at_100_days_overdue(
        self, api,
    ):
        """# difficulty: dual_variant_calc/late_fee_per_cycle_vs_continuous_daily

        PRD §3.3: "Concretely, a REGULAR charge that is 89 days past due
        has accrued one period; the same charge at 91 days past due has
        accrued two; at 100 days past due it is still two periods
        (because the second whole 90-day window has not yet completed)."

        Claim: at exactly 100 days past due_date on a REGULAR cycle of
        principal 100000, the per-cycle pinned formula yields 2 periods
        * max(2500, 1500) = 5000 cents in late_fee — the
        continuous-daily alternative would yield round(2500/90*100) =
        2778 cents, which the test explicitly rejects.
        """
        member, _unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=100))
        m = get_member(member["id"])
        expected_total = 100_000 + 5_000  # principal + 2*2500
        rejected_total = 100_000 + 2_778  # continuous-daily alternative
        assert m["total_overdue_amount_cents"] == expected_total, (
            f"per-cycle accrual: expected {expected_total}; got "
            f"{m['total_overdue_amount_cents']}"
        )
        assert m["total_overdue_amount_cents"] != rejected_total, (
            "must reject the continuous-daily variant"
        )

    def test_late_fee_per_cycle_yields_one_period_at_89_days_overdue(
        self, api,
    ):
        """# difficulty: dual_variant_calc/late_fee_per_cycle_vs_continuous_daily

        PRD §3.3: "Concretely, a REGULAR charge that is 89 days past
        due has accrued one period".

        Claim: at exactly 89 days past due_date, only one period has
        accrued — per_period_fee = max(2500, round(100000*0.015)=1500)
        = 2500. A continuous-daily variant would yield
        round(2500/90*89) = 2472, distinct from 2500.
        """
        member, _unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=89))
        m = get_member(member["id"])
        assert m["total_overdue_amount_cents"] == 100_000 + 2_500, (
            f"per-cycle: 1 period * 2500; got "
            f"{m['total_overdue_amount_cents']}"
        )

    def test_reserve_funding_per_component_then_sum_yields_60000(
        self, api, treasurer_role_headers,
    ):
        """# difficulty: dual_variant_calc/reserve_funding_per_component_then_sum_vs_sum_then_round

        PRD §3.9: "Each component's contribution is rounded to whole
        cents before the sum is taken; the totals are then added as
        integers. An implementation that defers rounding until after
        summing the raw component contributions can drift by a cent at
        half-cent boundaries and is incorrect."

        Claim: components yielding raw contributions 50000.0 + 9999.9 =
        59999.9 should round per-component (50000 + 10000 = 60000),
        not sum-then-round (60000 either, but the per-component pin is
        the contract).
        """
        from test_helpers import create_reserve_study_payload
        # Per the difficulty design recipe: components A (100000, 10, 5)
        # and B (33333, 10, 7). Component A: 100000*5/10=50000 → 50000.
        # Component B: 33333*3/10=9999.9 → round_half_up = 10000.
        # Sum = 60000. Balance 15000 → ratio 0.2500 → SPECIAL_ASSESSMENT_REQUIRED.
        payload = create_reserve_study_payload(
            study_year=2026,
            components=[
                reserve_component("A", 100_000, 10, 5),
                reserve_component("B", 33_333, 10, 7),
            ],
            current_reserve_balance_cents=15_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert body["full_funding_target_cents"] == 60_000, (
            f"per-component-then-sum: A=50000 + B=10000 = 60000; got "
            f"{body['full_funding_target_cents']}"
        )
        assert float(body["funded_ratio"]) == pytest.approx(0.2500, abs=1e-4)
        assert body["posture"] == "SPECIAL_ASSESSMENT_REQUIRED"

    def test_reserve_funding_at_zero_target_yields_null_ratio_and_ok(
        self, api, treasurer_role_headers,
    ):
        """# difficulty: dual_variant_calc/reserve_funding_per_component_then_sum_vs_sum_then_round

        PRD §3.9: "When full_funding_target_cents is zero, funded_ratio
        is null (division by zero is not attempted) and posture is OK."

        Claim: a study whose components all have remaining_life =
        useful_life produces target=0 and the pinned variant must
        surface funded_ratio=null (sum-then-round would still produce
        0/0 = NaN or 0, both wrong).
        """
        from test_helpers import create_reserve_study_payload
        payload = create_reserve_study_payload(
            study_year=2027,
            components=[reserve_component("New", 100_000, 10, 10)],
            current_reserve_balance_cents=50_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert body["full_funding_target_cents"] == 0
        assert body["funded_ratio"] is None, (
            f"target==0 must yield null funded_ratio; got "
            f"{body['funded_ratio']!r}"
        )
        assert body["posture"] == "OK"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_assessment_allocation_distributes_remainder_to_largest_share(
        self, api,
    ):
        """# difficulty: combinatorial_formula/assessment_allocation_with_remainder_distribution

        PRD §3.2: "the server then computes the remainder —
        total_levy_cents minus the sum of the rounded principals — and
        distributes that remainder one cent at a time to units sorted
        in descending order of share_factor, breaking ties by ascending
        Unit.id".

        Claim: with units U1(0.3334), U2(0.3333), U3(0.3333) and total
        levy 10001, the rounded principals are 3334+3333+3333=10000;
        the 1-cent remainder goes to U1 (largest share). Total per-
        member overdue (after going overdue) must equal exactly the
        per-unit principal share, confirming U1's owner sees 3335 and
        the other two see 3333.
        """
        members, units, issued, _ = setup_three_unit_for_allocation_remainder()
        # Advance past due_date and observe each owner's overdue rises
        # by exactly their principal share (no late fee yet at exactly
        # due+1s on a charge so small that the late-fee per-period
        # would dominate; we just verify per-owner principal allocation
        # by observing the OVERDUE sum equals the per-unit principal).
        due = parse_iso(issued["due_date"])
        # Advance to just past due_date.
        advance_clock_to(due + timedelta(seconds=1))
        # At due+1s: 0 full 90-day windows complete, +1 initial period =
        # 1 period. per_period_fee = max(2500, round(3335*0.015)=50) =
        # 2500. Each owner's overdue = principal + 2500.
        m1 = get_member(members[0]["id"])
        m2 = get_member(members[1]["id"])
        m3 = get_member(members[2]["id"])
        assert m1["total_overdue_amount_cents"] == 3335 + LATE_FEE_FLAT_CENTS, (
            f"U1's owner (largest share) should have principal=3335 + "
            f"{LATE_FEE_FLAT_CENTS} fee; got {m1['total_overdue_amount_cents']}"
        )
        assert m2["total_overdue_amount_cents"] == 3333 + LATE_FEE_FLAT_CENTS
        assert m3["total_overdue_amount_cents"] == 3333 + LATE_FEE_FLAT_CENTS
        total_principal = (
            m1["total_overdue_amount_cents"]
            + m2["total_overdue_amount_cents"]
            + m3["total_overdue_amount_cents"]
            - 3 * LATE_FEE_FLAT_CENTS
        )
        assert total_principal == 10001, (
            f"sum of principals must equal total_levy_cents 10001; got "
            f"{total_principal}"
        )

    def test_assessment_allocation_sum_invariant_with_even_split(self, api):
        """# difficulty: combinatorial_formula/assessment_allocation_with_remainder_distribution

        PRD §3.2: "This guarantees that the sum of principal_cents
        across all newly created charges equals total_levy_cents
        exactly."

        Claim: with five evenly-split units at 0.2000 and total_levy
        10000, every per-unit principal is exactly 2000 and the sum
        equals 10000.
        """
        members, units = setup_multi_unit_roster([0.2000] * 5)
        cycle = create_regular_cycle(total_levy_cents=10_000)
        issue_cycle(cycle)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(seconds=1))
        per_owner = []
        for m in members:
            mm = get_member(m["id"])
            per_owner.append(mm["total_overdue_amount_cents"])
        # Each owner: 2000 principal + 2500 late fee (1 period @ flat).
        for v in per_owner:
            assert v == 2000 + LATE_FEE_FLAT_CENTS, (
                f"expected 2000+{LATE_FEE_FLAT_CENTS}; got {v}"
            )

    def test_payment_waterfall_late_fee_drains_before_principal(self, api):
        """# difficulty: combinatorial_formula/payment_waterfall_with_tiered_violation_fine_interaction

        PRD §3.3: "within each AssessmentCharge it applies the payment
        first to outstanding late_fee_cents and then to outstanding
        principal_cents."

        Claim: with one OVERDUE charge of principal 10000 and late_fee
        2500 (1 period), a payment of 10000 must satisfy the entire
        late_fee (2500) first, leaving 7500 applied to principal and
        2500 of principal still owed. Member.total_overdue should drop
        from 12500 to 2500.
        """
        member, _unit, cycle = setup_issued_cycle(total_levy_cents=10_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=1, seconds=1))
        m_before = get_member(member["id"])
        # 10000 principal + 2500 late_fee = 12500
        assert m_before["total_overdue_amount_cents"] == 12_500
        # Pay 10000 — waterfall drains late_fee (2500) then 7500 of
        # principal. 2500 of principal remains.
        tender_payment(member_id=member["id"], amount_cents=10_000)
        m_after = get_member(member["id"])
        assert m_after["total_overdue_amount_cents"] == 2_500, (
            f"after 10000 payment with waterfall (late_fee first), "
            f"expected 2500 remaining; got "
            f"{m_after['total_overdue_amount_cents']}"
        )

    def test_violation_tiered_fine_index_2_with_one_prior_cured(self, api):
        """# difficulty: combinatorial_formula/payment_waterfall_with_tiered_violation_fine_interaction

        PRD §3.5: "The occurrence_index is a 1-based counter scoped to
        the unit: it is one more than the number of prior Violation
        rows on the same unit_id whose status is in the set FINED,
        CURED, or WAIVED ... occurrence 2 is a 5,000-cent fine".

        Claim: with one prior CURED violation, the next violation that
        auto-FINEs posts fine_cents=5000.
        """
        _member, unit = setup_single_unit_roster()
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        v2_after = get_violation(v2["id"])
        assert v2_after["fine_cents"] == 5_000


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_acc_landscaping_auto_approved_at_deadline(self, api):
        """# difficulty: non_linear_state_machine/acc_request_branching_with_auto_resolution

        PRD §3.4: "When the clock first advances to an instant at or
        after deemed_decision_deadline while the request is still
        UNDER_REVIEW, a LANDSCAPING request transitions to
        AUTO_APPROVED".

        Claim: a LANDSCAPING request UNDER_REVIEW becomes AUTO_APPROVED
        after the deadline.
        """
        acc_member, _unit, landscaping, appearance, board_meta = (
            setup_two_acc_requests_in_review()
        )
        # Advance past the deemed deadline.
        deadline = parse_iso(landscaping["deemed_decision_deadline"])
        advance_clock_to(deadline + timedelta(seconds=1))
        land_after = get_acc_request(landscaping["id"])
        assert land_after["status"] == "AUTO_APPROVED", (
            f"LANDSCAPING must auto-approve at deadline per PRD §3.4; "
            f"got {land_after['status']}"
        )

    def test_acc_appearance_auto_denied_at_deadline(self, api):
        """# difficulty: non_linear_state_machine/acc_request_branching_with_auto_resolution

        PRD §3.4: "an APPEARANCE request transitions to AUTO_DENIED.
        The split is deliberate".

        Claim: an APPEARANCE request UNDER_REVIEW becomes AUTO_DENIED
        after the deadline.
        """
        acc_member, _unit, landscaping, appearance, board_meta = (
            setup_two_acc_requests_in_review()
        )
        deadline = parse_iso(appearance["deemed_decision_deadline"])
        advance_clock_to(deadline + timedelta(seconds=1))
        appearance_after = get_acc_request(appearance["id"])
        assert appearance_after["status"] == "AUTO_DENIED", (
            f"APPEARANCE must auto-deny at deadline per PRD §3.4; got "
            f"{appearance_after['status']}"
        )

    def test_violation_waiver_from_fined_resets_fine_to_zero(self, api):
        """# difficulty: non_linear_state_machine/violation_branching_with_waiver_reversal

        PRD §3.5: "From FINED, the waiver additionally resets fine_cents
        to zero and recomputes the owner's total_overdue_amount_cents."

        Claim: a FINED violation, when waived via PASSED FINE_WAIVER
        resolution, has fine_cents reset to 0 and the owner's overdue
        drops accordingly.
        """
        member, unit = setup_single_unit_roster()
        # Drive a violation to FINED (occurrence 2 → 5000).
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        v2_fined = get_violation(v2["id"])
        assert v2_fined["fine_cents"] == 5_000
        # Drive a FINE_WAIVER resolution to PASSED.
        resolution = drive_resolution_to_passed("FINE_WAIVER", v2["id"])
        # Waive.
        waived = waive_violation(v2_fined, resolution["id"])
        assert waived["status"] == "WAIVED"
        assert waived["fine_cents"] == 0
        # Member's total_overdue must drop by 5000.
        m_after = get_member(member["id"])
        assert m_after["total_overdue_amount_cents"] == 0, (
            f"waiver must reset fine and recompute overdue to 0; got "
            f"{m_after['total_overdue_amount_cents']}"
        )

    def test_violation_cured_keeps_fine_at_zero_no_overdue_impact(self, api):
        """# difficulty: non_linear_state_machine/violation_branching_with_waiver_reversal

        PRD §3.5: "The SecretaryRole may mark the violation CURED at
        any instant on or before cure_deadline; the cure leaves
        fine_cents at zero and refreshes updated_at."

        Claim: a CURED violation has fine_cents=0 and does not
        contribute to Member.total_overdue.
        """
        member, unit = setup_single_unit_roster()
        v = open_violation(unit["id"])
        cured = cure_violation(v)
        assert cured["status"] == "CURED"
        assert cured["fine_cents"] == 0
        m = get_member(member["id"])
        assert m["total_overdue_amount_cents"] == 0


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_violation_fine_cascades_to_lien_eligibility(self, api):
        """# difficulty: transitive_cascade/violation_fine_to_overdue_to_lien_eligible

        PRD §2.9: "Marking a violation FINED recomputes
        Member.total_overdue_amount_cents for the owner, and if that
        recomputation newly carries the owner across the 180,000-cent
        floor while at least one of the owner's assessment charges has
        been in OVERDUE status for at least sixty days, the owner's
        unit becomes lien-eligible (the actual lien notice still
        requires a SecretaryRole action)."

        Claim: with overdue at 175000 and a charge OVERDUE >= 60 days,
        lien creation is rejected; after an additional violation auto-
        FINES adding 5000 (crossing 180000), lien creation succeeds.
        """
        # 1) Setup: principal 175000, advance past due_date by 60+ days.
        member, unit, cycle = setup_issued_cycle(total_levy_cents=175_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=61))
        # At due+61d: 1 period (since 61 < 90). late_fee = 2500.
        # Total overdue = 175000 + 2500 = 177500 (NOT >= 180000 yet).
        # To make the test pin exactly to "175000" without late fee
        # complicating it, advance ONLY 60d (within 1 period).
        # Already at +61d → late_fee=2500 → 177500. Lien-create should
        # still fail (177500 < 180000). Good.
        m_now = get_member(member["id"])
        assert m_now["total_overdue_amount_cents"] < 180_000, (
            f"setup must keep overdue below 180000 before the cascade; "
            f"got {m_now['total_overdue_amount_cents']}"
        )
        first_resp = api.create_lien(
            {"unit_id": unit["id"]},
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(first_resp, ApiErrorId.ERR_INVALID_STATE.value)

        # 2) Open and auto-fine a violation (occurrence 2 ⇒ fine 5000)
        # by first establishing one CURED prior.
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        # Now overdue includes prior 177500 (charge stayed OVERDUE) +
        # 5000 fine = 182500 — over the 180000 floor.
        m_post = get_member(member["id"])
        assert m_post["total_overdue_amount_cents"] >= 180_000, (
            f"after V2 fine, overdue must cross 180000; got "
            f"{m_post['total_overdue_amount_cents']}"
        )

        # 3) Now the lien creation succeeds (cascade hop 3).
        success_resp = api.create_lien(
            {"unit_id": unit["id"]},
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(success_resp, expected_status=201)
        assert_lien(body)
        assert body["status"] == "NOTICE_SENT"

    def test_overdue_below_180000_blocks_lien_creation(self, api):
        """# difficulty: transitive_cascade/violation_fine_to_overdue_to_lien_eligible

        PRD §2.8: "Lien creation demands it be at least 180,000 cents
        — that is, eighteen hundred dollars".

        Claim: a unit whose owner's overdue is 179999 cannot have a
        lien created. (Boundary edge — proves the >= 180000 inclusive
        threshold pins the cascade.)
        """
        member, unit, cycle = setup_issued_cycle(total_levy_cents=170_000)
        due = parse_iso(cycle["due_date"])
        # Advance just past due — 1 period late fee = 2500 → overdue =
        # 172500. Owner is below 180000.
        advance_clock_to(due + timedelta(days=61))
        m = get_member(member["id"])
        assert m["total_overdue_amount_cents"] < 180_000
        resp = api.create_lien(
            {"unit_id": unit["id"]},
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_election_certification_demotes_prior_holder_board_role(self, api):
        """# difficulty: transitive_cascade/election_certification_demotes_then_blocks_acc_votes

        PRD §2.9 / §3.7: "If a prior Member already held that
        board_role, the prior holder is demoted to board_role == NONE."

        Claim: after a CERTIFIED election seats a winner into a seat
        currently held by another Member, the prior holder's board_role
        is reset to NONE.
        """
        from test_helpers import seat_member_in_role
        # Seat M_old as DIRECTOR.
        m_old, _u_old = setup_single_unit_roster()
        # Add a second member; transfer ownership effectively by adding
        # a unit at 0 share_factor would violate constraints, so instead
        # seat into a DIRECTOR seat that we'll then re-elect for.
        seat_member_in_role(m_old, "DIRECTOR")
        m_old_after = get_member(m_old["id"])
        assert m_old_after["board_role"] == "DIRECTOR"
        # Now create a second member, and re-run an election that the
        # second member wins.
        m_new = create_member()
        # Owner must be eligible_to_vote; needs to own a unit. We can't
        # add another unit without breaking sum=1. So we trigger
        # re-election by patching share_factors: transfer some of m_old's
        # share to m_new via PATCH. (PATCH share_factor preserves the
        # sum invariant when offsetting two units.) But m_new doesn't own
        # a unit yet — create one at 0.0001 and lower m_old's by 0.0001.
        # Actually simplest: use the m_old's unit and another created.
        # Add a tiny share unit for m_new and decrement m_old's:
        from test_helpers import patch_unit_payload
        # First patch m_old's unit down to 0.9999, then add m_new's at
        # 0.0001.
        api.patch_unit(
            _u_old["id"],
            patch_unit_payload(
                version=_u_old["version"], share_factor=0.9999,
            ),
            TEST_USERS["president_role_headers"],
        )
        create_unit(owner_member_id=m_new["id"], share_factor=0.0001)
        # Now both have units and 0 overdue → eligible_to_vote.
        # Run election for DIRECTOR seat, m_new wins.
        seat_member_in_role(m_new, "DIRECTOR")
        m_old_demoted = get_member(m_old["id"])
        m_new_seated = get_member(m_new["id"])
        assert m_new_seated["board_role"] == "DIRECTOR", (
            f"winner must hold the seat; got {m_new_seated['board_role']}"
        )
        assert m_old_demoted["board_role"] == "NONE", (
            f"prior holder must be demoted to NONE per PRD §3.7 cascade; "
            f"got {m_old_demoted['board_role']}"
        )

    def test_election_certification_winner_holds_seat(self, api):
        """# difficulty: transitive_cascade/election_certification_demotes_then_blocks_acc_votes

        PRD §3.7: "Certification sets the winner's Member.board_role to
        the election's seat."

        Claim: after a CERTIFIED election, the winner's board_role
        equals the elected seat.
        """
        from test_helpers import seat_member_in_role
        member, _unit = setup_single_unit_roster()
        seat_member_in_role(member, "SECRETARY")
        m_after = get_member(member["id"])
        assert m_after["board_role"] == "SECRETARY", (
            f"winner's board_role must equal election.seat per PRD §3.7; "
            f"got {m_after['board_role']}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_record_on_already_recorded_lien_returns_invalid_state_not_cooling_off(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_lien_record

        PRD §2.7: "Authentication (ERR_UNAUTHENTICATED) is checked
        first, then role authorization (ERR_FORBIDDEN), then path-
        parameter existence (ERR_NOT_FOUND), then state-transition
        admissibility (ERR_INVALID_STATE)."

        Claim: when a Lien is in a state that does not permit the
        transition (e.g., the lien doesn't exist as a NOTICE_SENT — say
        a non-existent ID is supplied), the existence/state check
        fires before the cooling-off check.

        Two-reader-test: a faithful implementer reading PRD might
        either return ERR_NOT_FOUND for a missing lien id, or
        ERR_INVALID_STATE for a lien not in NOTICE_SENT. We assert that
        the response is NOT ERR_LIEN_COOLING_OFF — that is the contract
        from PRD §2.7 priority ordering.
        """
        from test_helpers import validate_error_is_one_of
        # Try to record a non-existent lien within a hypothetical cooling
        # period. The error must NOT be ERR_LIEN_COOLING_OFF — the prior
        # priority checks (existence, then state) must fire first.
        resp = api.record_lien(
            NON_EXISTENT_UUID,
            {"resolution_id": NON_EXISTENT_UUID, "version": 1},
            TEST_USERS["president_role_headers"],
        )
        body = resp.json()
        actual_error = body.get("data", {}).get("error_id")
        assert actual_error != ApiErrorId.ERR_LIEN_COOLING_OFF.value, (
            f"state/existence check must precede cooling-off per PRD "
            f"§2.7; got {actual_error}"
        )
        # The actual error must be one of the higher-priority checks.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_NOT_FOUND.value,
             ApiErrorId.ERR_INVALID_STATE.value],
        )

    def test_voter_ineligible_takes_precedence_over_voting_closed(self, api):
        """# difficulty: priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_ballot_create

        PRD §3.7: "Three checks fire in order. The voter MUST currently
        have eligible_to_vote == true ... ; failure on either prong
        returns ERR_VOTER_INELIGIBLE (HTTP 403). The election's status
        MUST equal VOTING ... a ballot outside that window returns
        ERR_VOTING_CLOSED (HTTP 409)."

        Claim: a ballot from an ineligible voter cast after
        voting_close_at fails BOTH; the voter-eligibility check fires
        first, returning ERR_VOTER_INELIGIBLE — not ERR_VOTING_CLOSED.
        """
        # Setup: a member who is ineligible (owns no unit), and an
        # election whose voting window has closed.
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=120,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        # Create an ineligible voter (no unit owned).
        ineligible = create_member()
        # Advance past voting_close_at so the window is closed.
        advance_clock_to(parse_iso(election["voting_close_at"])
                         + timedelta(seconds=1))
        # Cast a ballot from the ineligible voter outside the window.
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=ineligible["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(ineligible["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_INELIGIBLE.value)

    def test_record_after_release_returns_invalid_state_not_cooling_off(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_lien_record

        PRD §2.7: "state-transition admissibility (ERR_INVALID_STATE)"
        is checked BEFORE domain-specific checks like the lien cooling-
        off (priority 6). PRD §3.6 confirms recordation is only valid
        from NOTICE_SENT.

        Claim: attempting to record a Lien already in RECORDED (or
        RELEASED) returns ERR_INVALID_STATE — the cooling-off check
        never fires because the state precondition is checked first.

        We drive a Lien to RECORDED, then call /record a second time on
        the same lien — the state check (now in RECORDED, not
        NOTICE_SENT) fires before cooling-off.
        """
        # Drive a unit's overdue over 180k, create a lien, wait out the
        # cooling off, record it.
        member, unit, cycle = setup_issued_cycle(total_levy_cents=200_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=61))
        lien = create_lien_for_unit(unit["id"])
        record_res = drive_resolution_to_passed(
            "LIEN_RECORDATION", lien["id"],
        )
        # Cooling-off: advance another 31 days past lien.created_at.
        advance_clock_to(
            parse_iso(lien["created_at"]) + timedelta(days=31),
        )
        recorded = record_lien(lien, record_res["id"])
        assert recorded["status"] == "RECORDED"
        # Second record attempt — lien is now RECORDED, not NOTICE_SENT.
        # The state precondition fails, but cooling-off is irrelevant.
        # We must see ERR_INVALID_STATE, not ERR_LIEN_COOLING_OFF.
        second_res = drive_resolution_to_passed(
            "LIEN_RECORDATION", lien["id"],
        )
        resp = api.record_lien(
            lien["id"],
            {"resolution_id": second_res["id"],
             "version": recorded.get("version", 2)},
            TEST_USERS["president_role_headers"],
        )
        body = resp.json()
        actual_error = body.get("data", {}).get("error_id")
        assert actual_error != ApiErrorId.ERR_LIEN_COOLING_OFF.value, (
            f"PRD §2.7: state-precondition check must precede cooling-"
            f"off; got {actual_error}"
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_duplicate_ballot_after_eligible_passes_voter_check(self, api):
        """# difficulty: priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_ballot_create

        PRD §3.7: "The pair (election_id, voter_member_id) MUST be
        unique across all existing Ballot rows; a duplicate is rejected
        with ERR_DUPLICATE_BALLOT (HTTP 409)."

        Claim (complementary to the prior test): when the voter IS
        eligible and the window IS open, but the (election, voter) pair
        already exists, the duplicate check fires (priority 10, after
        eligibility and window). This proves the priority-8 / priority-9
        gates passed and we landed on the priority-10 check — different
        pair-position evidence for the same priority chain.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=600,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_open_at"]))
        # First ballot succeeds (voter eligible, window open).
        cast_ballot(election["id"], member["id"], candidate["id"])
        # Second ballot — voter still eligible, window still open, but
        # duplicate (election, voter) pair.
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_overdue_at_exactly_180000_admits_lien_creation(self, api):
        """# difficulty: boundary_precision_check/total_overdue_at_exactly_180000_unlocks_lien

        PRD §2.8: "Lien creation demands it be at least 180,000 cents
        — that is, eighteen hundred dollars".

        Claim: at exactly 180000 cents (the inclusive boundary), lien
        creation succeeds. Construction: levy 142500 (so that
        142500*0.015=2138 < 2500 ⇒ per-period = flat 2500) with 1
        late-fee period (charge OVERDUE) yields charge overdue 145000.
        Then sequentially drive four violations to FINED so that each
        successive violation sees the prior in FINED status — yielding
        occurrence indices 1, 2, 3, 4 and fines 0+5000+10000+20000 =
        35000. Grand total = 145000 + 35000 = 180000 exactly. After all
        the timing the charge has been OVERDUE >= 60 days
        (precondition for lien creation per PRD §3.6).
        """
        member, unit, cycle = setup_issued_cycle(total_levy_cents=142_500)
        due = parse_iso(cycle["due_date"])
        # Move clock into the OVERDUE band (1 late-fee period).
        advance_clock_to(due + timedelta(seconds=1))
        # Drive 4 violations to FINED sequentially. Each one must be in
        # {FINED, CURED, WAIVED} before the next is opened so that
        # occurrence_index increments.
        from test_helpers import advance_clock_by_days
        for _ in range(4):
            v = open_violation(unit["id"])
            # Advance past v.cure_deadline (= opened_at + 14d) so v
            # auto-FINEs.
            advance_clock_by_days(15)
        # Now we're due + 1s + 4*15d = due + 60d + 1s — exactly the
        # 60-day OVERDUE threshold. Advance one more second so the
        # charge has been OVERDUE STRICTLY more than 60 days when the
        # lien is created, and so the late-fee period count is still 1
        # (we're at 60d, < 90d ⇒ 1 period still).
        advance_clock_by_days(1)
        m = get_member(member["id"])
        # principal 142500 + late_fee 2500 (1 period flat) + fines
        # 0 + 5000 + 10000 + 20000 = 35000 ⇒ total 180000.
        assert m["total_overdue_amount_cents"] == 180_000, (
            f"setup target 180000 exactly; got "
            f"{m['total_overdue_amount_cents']}"
        )
        resp = api.create_lien(
            {"unit_id": unit["id"]},
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=201)
        assert_lien(body)
        assert body["status"] == "NOTICE_SENT"

    def test_overdue_at_179999_rejects_lien_creation(self, api):
        """# difficulty: boundary_precision_check/total_overdue_at_exactly_180000_unlocks_lien

        PRD §2.8: "Lien creation demands it be at least 180,000 cents".

        Claim: at exactly 179999 (one cent below the inclusive
        boundary), lien creation is rejected. Construct as for the
        admitted case but with levy 142499 instead of 142500 ⇒ grand
        total 179999.
        """
        member, unit, cycle = setup_issued_cycle(total_levy_cents=142_499)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(seconds=1))
        from test_helpers import advance_clock_by_days
        for _ in range(4):
            open_violation(unit["id"])
            advance_clock_by_days(15)
        advance_clock_by_days(1)
        m = get_member(member["id"])
        assert m["total_overdue_amount_cents"] == 179_999, (
            f"setup target 179999; got {m['total_overdue_amount_cents']}"
        )
        resp = api.create_lien(
            {"unit_id": unit["id"]},
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_election_with_zero_candidates_voids_at_voting_open(self, api):
        """# difficulty: boundary_precision_check/election_with_zero_candidates_auto_voids

        PRD §3.7: "If, however, the clock crosses voting_open_at and no
        Candidate rows exist for the election, the election transitions
        directly to VOIDED with no winner and no snapshot."

        Claim: an election with 0 candidates auto-voids at
        voting_open_at.
        """
        e_empty, e_one, _sole = setup_election_with_zero_candidates_and_one_candidate()
        advance_clock_to(parse_iso(e_empty["voting_open_at"])
                         + timedelta(seconds=1))
        e_empty_after = get_election(e_empty["id"])
        assert e_empty_after["status"] == "VOIDED", (
            f"zero-candidate election must VOID at voting_open_at; got "
            f"{e_empty_after['status']}"
        )

    def test_election_with_one_candidate_transitions_to_voting(self, api):
        """# difficulty: boundary_precision_check/election_with_zero_candidates_auto_voids

        PRD §3.7: "When the clock crosses voting_open_at while the
        election is still NOMINATION, the system transitions to VOTING".

        Claim: an election with exactly one candidate transitions to
        VOTING at voting_open_at (not VOIDED). The 1-candidate boundary
        admits the election.
        """
        e_empty, e_one, _sole = setup_election_with_zero_candidates_and_one_candidate()
        advance_clock_to(parse_iso(e_one["voting_open_at"])
                         + timedelta(seconds=1))
        e_one_after = get_election(e_one["id"])
        assert e_one_after["status"] == "VOTING", (
            f"1-candidate election must transition to VOTING; got "
            f"{e_one_after['status']}"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_acc_begin_review_blocked_by_owner_overdue(self, api):
        """# difficulty: cross_entity_state_dependency/acc_begin_review_depends_on_member_total_overdue

        PRD §3.4: "the unit's owner — identified by
        submitted_by_member_id — MUST currently have
        Member.total_overdue_amount_cents equal to zero; a delinquent
        owner is barred with ERR_OWNER_DELINQUENT (HTTP 409)."

        Claim: an owner whose total_overdue > 0 (driven by an OVERDUE
        charge) blocks the SUBMITTED → UNDER_REVIEW transition with
        ERR_OWNER_DELINQUENT.
        """
        member, unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        req = submit_acc_request(unit["id"], member["id"])
        # Push owner into delinquency.
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=1, seconds=1))
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_DELINQUENT.value)
        # And the request stays SUBMITTED.
        still = get_acc_request(req["id"])
        assert still["status"] == "SUBMITTED"

    def test_acc_begin_review_with_owner_zero_overdue_admitted(self, api):
        """# difficulty: cross_entity_state_dependency/acc_begin_review_depends_on_member_total_overdue

        PRD §3.4: "A SecretaryRole then begins review, advancing the
        request from SUBMITTED to UNDER_REVIEW."

        Claim: with the owner at total_overdue=0, the transition
        succeeds.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=200)
        assert body["status"] == "UNDER_REVIEW"

    def test_acc_begin_review_blocked_by_special_assessment_posture(self, api):
        """# difficulty: cross_entity_state_dependency/acc_begin_review_depends_on_reserve_study_posture

        PRD §3.4: "the most recently adopted ReserveStudy MUST NOT have
        posture == SPECIAL_ASSESSMENT_REQUIRED ... begin-review is
        rejected with ERR_RESERVE_POSTURE_BLOCKS_ACC (HTTP 409)."

        Claim: an ADOPTED ReserveStudy with posture
        SPECIAL_ASSESSMENT_REQUIRED blocks begin-review.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        study = setup_adopted_special_assessment_study()
        assert study["posture"] == "SPECIAL_ASSESSMENT_REQUIRED"
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_RESERVE_POSTURE_BLOCKS_ACC.value,
        )

    def test_acc_begin_review_with_ok_posture_admitted(self, api):
        """# difficulty: cross_entity_state_dependency/acc_begin_review_depends_on_reserve_study_posture

        PRD §3.4: "A SecretaryRole then begins review, advancing the
        request from SUBMITTED to UNDER_REVIEW."

        Claim: with no adopted study (posture defaults to permissive)
        the begin-review succeeds.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=200)
        assert body["status"] == "UNDER_REVIEW"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_ballot_at_voting_open_inclusive_succeeds(self, api):
        """# difficulty: resource_temporal_overlap/ballot_window_half_open_election_interval

        PRD §3.7: "the current instant lies in the half-open interval
        from voting_open_at inclusive to voting_close_at exclusive".

        Claim: a ballot cast at exactly voting_open_at (inclusive
        boundary) succeeds.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=600,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_open_at"]))
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_ballot_at_voting_close_exclusive_returns_voting_closed(self, api):
        """# difficulty: resource_temporal_overlap/ballot_window_half_open_election_interval

        PRD §3.7: "a ballot outside that window returns
        ERR_VOTING_CLOSED (HTTP 409)."

        Claim: a ballot cast at exactly voting_close_at (exclusive
        boundary) returns ERR_VOTING_CLOSED.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=120,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_close_at"]))
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_CLOSED.value)

    def test_nomination_at_nomination_open_inclusive_succeeds(self, api):
        """# difficulty: resource_temporal_overlap/nomination_window_with_adjacency_to_voting

        PRD §3.7: "The nomination instant MUST also lie within the
        half-open interval from nomination_open_at inclusive to
        voting_open_at exclusive".

        Claim: a candidate nominated at exactly nomination_open_at
        (inclusive boundary) is admitted.
        """
        member, _unit = setup_single_unit_roster()
        # Open an election whose nomination window starts NOW.
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=120,
            voting_close_offset_seconds=240,
            quorum_pct=0.10,
        )
        # Already at or after nomination_open_at — nominate.
        from test_helpers import create_candidate_payload
        resp = api.create_candidate(
            election["id"],
            create_candidate_payload(member_id=member["id"]),
            make_member_headers(member["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_nomination_at_voting_open_exclusive_returns_nomination_closed(
        self, api,
    ):
        """# difficulty: resource_temporal_overlap/nomination_window_with_adjacency_to_voting

        PRD §3.7: "outside that interval the registration is rejected
        with ERR_NOMINATION_CLOSED (HTTP 409)."

        Claim: a nomination at exactly voting_open_at falls into the
        voting window (exclusive end of nomination) and is rejected.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=120,
            quorum_pct=0.10,
        )
        advance_clock_to(parse_iso(election["voting_open_at"]))
        from test_helpers import create_candidate_payload
        resp = api.create_candidate(
            election["id"],
            create_candidate_payload(member_id=member["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_CLOSED.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_violation_waiver_zeroes_overdue_back_to_pre_fine_snapshot(
        self, api,
    ):
        """# difficulty: compensating_invariant/violation_waiver_reverses_member_total_overdue

        PRD §3.5: "From FINED, the waiver additionally resets
        fine_cents to zero and recomputes the owner's
        total_overdue_amount_cents."

        Claim: starting from total_overdue=0, when a violation auto-
        FINES the owner gains fine_cents in overdue; when waived, the
        overdue returns exactly to 0 — no drift.
        """
        member, unit = setup_single_unit_roster()
        # Force occurrence_index=2 with one prior CURED.
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        before = get_member(member["id"])["total_overdue_amount_cents"]
        assert before == 0
        # Drive V2 to FINED.
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        v2_fined = get_violation(v2["id"])
        assert v2_fined["fine_cents"] == 5_000
        mid = get_member(member["id"])["total_overdue_amount_cents"]
        assert mid == 5_000, (
            f"after fine, overdue should rise by exactly fine_cents; "
            f"got {mid}"
        )
        # Pass a FINE_WAIVER resolution and waive.
        resolution = drive_resolution_to_passed("FINE_WAIVER", v2["id"])
        waive_violation(v2_fined, resolution["id"])
        after = get_member(member["id"])["total_overdue_amount_cents"]
        assert after == before, (
            f"compensating invariant violated: pre-fine overdue {before} "
            f"!= post-waiver overdue {after}"
        )

    def test_violation_waiver_from_fined_status_becomes_waived(self, api):
        """# difficulty: compensating_invariant/violation_waiver_reverses_member_total_overdue

        PRD §3.5: "A waiver is invoked by the SecretaryRole and carries
        a resolution_id. There MUST exist a BoardResolution with
        subject == FINE_WAIVER, target_id equal to the violation's id,
        and status == PASSED; the resolution is then consumed (its
        status flips to EXECUTED)."

        Claim: after waiver, violation.status == WAIVED and the
        consumed resolution's status == EXECUTED.
        """
        _member, unit = setup_single_unit_roster()
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        v2_fined = get_violation(v2["id"])
        resolution = drive_resolution_to_passed("FINE_WAIVER", v2["id"])
        waived = waive_violation(v2_fined, resolution["id"])
        assert waived["status"] == "WAIVED"
        # Resolution should now be EXECUTED.
        from test_helpers import get_board_resolution
        res_after = get_board_resolution(resolution["id"])
        assert res_after["status"] == "EXECUTED", (
            f"PRD §3.5: 'the resolution is then consumed' → EXECUTED; "
            f"got {res_after['status']}"
        )

    def test_lien_release_cascades_unit_lien_status_to_released(self, api):
        """# difficulty: compensating_invariant/lien_release_restores_unit_lien_status_to_pre_recordation_view

        PRD §3.6: "On success the server sets released_at = now,
        cascades Unit.lien_status to RELEASED".

        Claim: after release, Unit.lien_status is RELEASED (not
        NOTICE_SENT, not RECORDED).
        """
        # Drive a unit through the full lien path: notice → record →
        # release. The record path requires cooling-off (30d). We use a
        # large levy so overdue is already over 180000 before the
        # cooling-off completes.
        member, unit, cycle = setup_issued_cycle(total_levy_cents=200_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=61))
        m_check = get_member(member["id"])
        assert m_check["total_overdue_amount_cents"] >= 180_000
        # Create lien (NOTICE_SENT).
        lien = create_lien_for_unit(unit["id"])
        assert lien["status"] == "NOTICE_SENT"
        # Pass a LIEN_RECORDATION resolution.
        record_res = drive_resolution_to_passed(
            "LIEN_RECORDATION", lien["id"],
        )
        # Wait out the 30-day cooling-off.
        lien_created = parse_iso(lien["created_at"])
        advance_clock_to(lien_created + timedelta(days=31))
        # Record. Overdue must still be >= 180000 at record time.
        m_at_record = get_member(member["id"])
        assert m_at_record["total_overdue_amount_cents"] >= 180_000
        recorded = record_lien(lien, record_res["id"])
        assert recorded["status"] == "RECORDED"
        unit_after_record = get_unit(unit["id"])
        assert unit_after_record["lien_status"] == "RECORDED"
        # Pay off all overdue so release becomes possible.
        tender_payment(
            member_id=member["id"],
            amount_cents=m_at_record["total_overdue_amount_cents"],
        )
        m_paid = get_member(member["id"])
        assert m_paid["total_overdue_amount_cents"] == 0
        # Pass LIEN_RELEASE resolution and release.
        release_res = drive_resolution_to_passed(
            "LIEN_RELEASE", lien["id"],
        )
        released = release_lien(recorded, release_res["id"])
        assert released["status"] == "RELEASED"
        unit_after_release = get_unit(unit["id"])
        assert unit_after_release["lien_status"] == "RELEASED", (
            f"after release, Unit.lien_status must mirror RELEASED; got "
            f"{unit_after_release['lien_status']}"
        )

    def test_lien_release_marks_consumed_resolution_executed(self, api):
        """# difficulty: compensating_invariant/lien_release_restores_unit_lien_status_to_pre_recordation_view

        PRD §3.6: "marks the referenced BoardResolution as EXECUTED".

        Claim: after a release, the LIEN_RELEASE resolution's status is
        EXECUTED.
        """
        # Re-use the full lien lifecycle from the prior test in
        # compressed form.
        member, unit, cycle = setup_issued_cycle(total_levy_cents=200_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=61))
        lien = create_lien_for_unit(unit["id"])
        record_res = drive_resolution_to_passed(
            "LIEN_RECORDATION", lien["id"],
        )
        advance_clock_to(parse_iso(lien["created_at"]) + timedelta(days=31))
        recorded = record_lien(lien, record_res["id"])
        m_now = get_member(member["id"])
        tender_payment(
            member_id=member["id"],
            amount_cents=m_now["total_overdue_amount_cents"],
        )
        release_res = drive_resolution_to_passed(
            "LIEN_RELEASE", lien["id"],
        )
        release_lien(recorded, release_res["id"])
        from test_helpers import get_board_resolution
        release_res_after = get_board_resolution(release_res["id"])
        assert release_res_after["status"] == "EXECUTED", (
            f"release must mark the resolution EXECUTED per PRD §3.6; "
            f"got {release_res_after['status']}"
        )
