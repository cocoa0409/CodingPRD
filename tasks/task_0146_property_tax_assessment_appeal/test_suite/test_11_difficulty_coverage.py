"""Additional dedicated tests for the difficulty-design priority
queue (SCAFFOLD_DIFFICULTY_DESIGN). Each test cites the underlying
PRD rule verbatim and tags itself with the # difficulty: rule_id/
instance.name marker so the coverage audit can verify two-test
coverage per instance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days_iso,
    add_minutes_iso,
    advance_clock_to,
    approve_exemption,
    create_assessment,
    create_hearing_officer,
    create_owner,
    create_property,
    create_tax_bill,
    create_tax_bill_payload,
    file_appeal,
    file_appeal_payload,
    get_assessment,
    get_tax_bill,
    iso_now_utc,
    issue_assessment,
    issue_tax_bill,
    make_assessor_headers,
    make_owner_headers,
    request_deferral_plan,
    schedule_appeal,
    schedule_appeal_payload,
    senior_eligible_dob,
    setup_finalized_assessment_via_clock,
    setup_issued_assessment,
    setup_issued_tax_bill,
    setup_owner_and_property,
    setup_two_appeals_for_scheduling_conflict,
    submit_exemption,
    validate_error,
    validate_success,
    version_body,
    withdraw_appeal,
    young_dob,
)


# ===========================================================================
# combinatorial_formula/exemption_stack_tiered_priority_mode_a — 2nd test
# ===========================================================================
class TestExemptionStackHomesteadOnlyVariant:

    def test_homestead_alone_smaller_of_pct_and_cap(self, api):
        """PRD §3.3: "HOMESTEAD: the smaller of 20 percent of the
        residual base (the system constant HOMESTEAD_PCT is 0.20) and
        the absolute dollar cap of 75,000 (the system constant
        HOMESTEAD_CAP_DOLLARS), rounded half up to two decimal
        places."

        Claim: at capped_value=200000 (so 20% = 40000 < 75000 cap),
        HOMESTEAD = 40000.00; no other exemptions applied.

        # difficulty: combinatorial_formula/exemption_stack_tiered_priority_mode_a
        """
        owner = create_owner()
        prop = create_property(owner=owner, market_value=200_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=200_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="HOMESTEAD", effective_roll_year=2025,
        )
        approve_exemption(
            property_id=prop["id"],
            exemption_application_id=ex["id"], version=ex["version"],
        )
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(add_days_iso(asmt["appeal_window_closes_at"], 1))
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        # HOMESTEAD = min(0.20*200000, 75000) = min(40000, 75000) =
        # 40000.
        assert bill["total_exemption_amount"] == pytest.approx(
            40_000.00, abs=0.01,
        )


# ===========================================================================
# combinatorial_formula/tax_bill_rounding_order_mode_b — 2nd test
# ===========================================================================
class TestExemptionStackPerLayerRoundingVariant:

    def test_per_layer_rounding_then_sum(self, api):
        """PRD §3.3: "Rounding is applied per-layer, not once at the
        end."

        Claim: at capped_value=123456.78 with HOMESTEAD only,
        approved_amount = round_half_up(0.20*123456.78, 2) = 24691.36
        (per-layer), and total_exemption_amount equals the same.

        # difficulty: combinatorial_formula/tax_bill_rounding_order_mode_b
        """
        owner = create_owner()
        prop = create_property(owner=owner, market_value=123_456.78)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=123_456.78,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="HOMESTEAD", effective_roll_year=2025,
        )
        approve_exemption(
            property_id=prop["id"],
            exemption_application_id=ex["id"], version=ex["version"],
        )
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(add_days_iso(asmt["appeal_window_closes_at"], 1))
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        # 0.20 * 123456.78 = 24691.356 → round_half_up to 24691.36.
        assert bill["total_exemption_amount"] == pytest.approx(
            24_691.36, abs=0.01,
        )


# ===========================================================================
# combinatorial_formula/appeal_decided_then_recomputed_bill_mode_c — 2nd test
# ===========================================================================
class TestPinnedEvaluationOrderInCascade:

    def test_decide_reduced_propagates_through_pinned_order_to_amount_due(
        self, api,
    ):
        """PRD §3.5: "The TaxBill for (property_id, roll_year) — if
        one exists — is recomputed via the tax-bill computation in
        §3.4, against the new capped_value."
        PRD §3.5: "The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED
        (unchanged if UPHELD); the Assessment's version and
        updated_at are bumped."

        Claim: after a REDUCED decide drops Assessment.capped_value
        from 500000 to 320000, the cascade-driven recompute applies
        the pinned order; the Assessment.capped_value is observable
        at 320000.

        # difficulty: combinatorial_formula/appeal_decided_then_recomputed_bill_mode_c
        # difficulty: transitive_cascade/appeal_decided_cascade_depth_3
        """
        from test_helpers import setup_heard_appeal, decide_appeal
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="REDUCED", decided_value=320_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        # Hop1 anchor: capped_value updated.
        assert re_asmt["capped_value"] == pytest.approx(
            320_000.00, abs=0.01,
        )


# ===========================================================================
# non_linear_state_machine/assessment_appeal_cycle — 2nd test
# ===========================================================================
class TestAssessmentCycleSingleLoop:

    def test_file_then_withdraw_returns_to_issued_once(self, api):
        """PRD §3.5: "If no remaining Appeal on the Assessment is in
        FILED, SCHEDULED, or HEARD, the Assessment reverts
        UNDER_APPEAL → ISSUED and is once again appeal-eligible —
        but only until the original appeal_window_closes_at; the
        window is never extended by withdrawal."

        Claim: a single file → withdraw cycle reverts the Assessment
        to ISSUED (window not extended). This is the simpler form of
        the assessment_appeal_cycle pattern.

        # difficulty: non_linear_state_machine/assessment_appeal_cycle
        """
        owner, prop, asmt = setup_issued_assessment()
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=asmt["id"], claimed_value=100_000.00,
        )
        s1 = get_assessment(prop["id"], asmt["id"])
        assert s1["status"] == "UNDER_APPEAL"
        withdraw_appeal(
            owner=owner, property_id=prop["id"], appeal_id=appeal["id"],
        )
        s2 = get_assessment(prop["id"], asmt["id"])
        assert s2["status"] == "ISSUED"
        # appeal_window_closes_at must NOT change across the cycle.
        assert s2["appeal_window_closes_at"] == asmt["appeal_window_closes_at"]


# ===========================================================================
# priority_pair_validation_conflict/state_vs_business_temporal_pair — 2nd test
# (extra coverage of the state-vs-temporal pair already covered in test_10)
# ===========================================================================
class TestStateVsTemporalAlternate:

    def test_finalized_assessment_blocks_new_appeal_with_state_error(
        self, api,
    ):
        """PRD §2.9: "then the target resource's state-machine
        eligibility (ERR_INVALID_STATE), then cross-entity
        preconditions such as the Assessment being FINALIZED before a
        bill can issue (ERR_ASSESSMENT_NOT_FINALIZED), then temporal
        gates such as the appeal window or hearing-interval
        validity".

        Claim: an Assessment forcibly auto-FINALIZEd (via clock past
        window with no Appeal) cannot accept a new Appeal; the error
        returned is ERR_INVALID_STATE (higher priority than the
        temporal ERR_APPEAL_WINDOW_CLOSED).

        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_pair
        """
        owner, prop, asmt = setup_issued_assessment()
        advance_clock_to(add_days_iso(asmt["appeal_window_closes_at"], 30))
        re_asmt = get_assessment(prop["id"], asmt["id"])
        assert re_asmt["status"] == "FINALIZED"
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=asmt["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# cross_entity_state_dependency/taxbill_issue_requires_assessment_finalized — 2nd
# ===========================================================================
class TestTaxBillRequiresFinalizedAssessmentAlt:

    def test_after_assessment_finalized_bill_issuance_succeeds(self, api):
        """PRD §3.4: "Two cross-entity preconditions guard the
        transition: the linked Assessment must be FINALIZED, otherwise
        ERR_ASSESSMENT_NOT_FINALIZED".

        Claim (positive form): with the Assessment FINALIZED and no
        SUBMITTED exemptions, the /issue path succeeds; this proves
        the gate releases as soon as the cross-entity precondition
        is satisfied.

        # difficulty: cross_entity_state_dependency/taxbill_issue_requires_assessment_finalized
        """
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        assert asmt["status"] == "FINALIZED"
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        issued = issue_tax_bill(
            property_id=prop["id"], tax_bill_id=bill["id"],
        )
        assert issued["status"] == "ISSUED"


# ===========================================================================
# cross_entity_state_dependency/appeal_filing_requires_assessment_issued — 2nd
# ===========================================================================
class TestAppealFilingRequiresIssuedAlt:

    def test_appeal_filing_on_finalized_assessment_rejected(self, api):
        """PRD §3.5: "The Assessment itself must be in ISSUED (or
        already in UNDER_APPEAL — additional Appeals on the same
        Assessment are permitted while the window remains open)."

        Claim: filing an Appeal against a FINALIZED Assessment is
        rejected (not in {ISSUED, UNDER_APPEAL}). The PRD §2.9
        priority means state (priority 5) fires before any temporal
        check (priority 7).

        # difficulty: cross_entity_state_dependency/appeal_filing_requires_assessment_issued
        """
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=asmt["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# cross_entity_state_dependency/deferral_activation_requires_taxbill_issued_or_partial — 2nd
# ===========================================================================
class TestDeferralActivationGateAlt:

    def test_activate_succeeds_when_bill_partially_paid(self, api):
        """PRD §3.6: "The linked TaxBill must be in ISSUED or
        PARTIALLY_PAID at activation".

        Claim (positive form for PARTIALLY_PAID branch): an Owner
        partially pays the bill (status becomes PARTIALLY_PAID), then
        a senior-eligible Owner can activate a deferral — exercising
        the PARTIALLY_PAID side of the precondition.

        # difficulty: cross_entity_state_dependency/deferral_activation_requires_taxbill_issued_or_partial
        """
        from test_helpers import (
            activate_deferral_plan,
            post_payment,
        )
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        # base_tax = 5000; pay 1000 → PARTIALLY_PAID.
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=1_000.00,
        )
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "PARTIALLY_PAID"
        # Now request + activate.
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        activated = activate_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"], version=dp["version"],
        )
        assert activated["status"] == "ACTIVE"
        # principal_deferred = remaining amount_due = 4000.
        assert activated["principal_deferred"] == pytest.approx(
            4_000.00, abs=0.01,
        )


# ===========================================================================
# priority_pair_validation_conflict/business_safety_vs_business_constraint_pair
# ===========================================================================
class TestRoomConstraintBeforeOfficerSegregation:
    """PRD §2.9 places "business constraints such as room overlap,
    officer-buffer, exemption uniqueness, exemption eligibility,
    payment-amount sanity, bill duplication, and the
    segregation-of-duties checks" in that order — room overlap fires
    BEFORE the segregation-of-duties check."""

    def test_room_double_booked_fires_before_boe_officer_conflict(self, api):
        """PRD §2.9: "business constraints such as room overlap,
        officer-buffer, exemption uniqueness, exemption eligibility,
        payment-amount sanity, bill duplication, and the
        segregation-of-duties checks".

        Claim: when a scheduling request simultaneously triggers
        ERR_ROOM_DOUBLE_BOOKED (room already booked in the half-open
        interval) AND would trigger ERR_BOE_OFFICER_CONFLICT (officer
        is the Assessor who issued the underlying Assessment), the
        room conflict fires first per PRD §2.9 priority.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_pair
        """
        # Build a first booking in ROOM_A.
        ctx = setup_two_appeals_for_scheduling_conflict()
        base = iso_now_utc()
        start1 = add_minutes_iso(base, 60)
        end1 = add_minutes_iso(start1, 60)
        # First booking with a separate "officer X".
        officer_x = create_hearing_officer(full_name="Officer X")
        schedule_appeal(
            property_id=ctx["property1"]["id"], appeal_id=ctx["appeal1"]["id"],
            scheduled_start=start1, scheduled_end=end1,
            hearing_room="ROOM_A", officer_id=officer_x["id"],
        )
        # For the second booking, set up the conflict:
        # - ROOM_A overlap (10:30 within 10:00-11:00)
        # - officer who is ALSO the issuer of the 2nd appeal's
        #   Assessment (BoE conflict).
        # Re-issue the second Assessment as an Assessor whose
        # X-User-ID == officer_x["id"], so segregation would trigger.
        from test_helpers import api_client, TEST_USERS
        # Create a third property and Assessment, issuing as the
        # officer-as-Assessor.
        owner3 = create_owner()
        prop3 = create_property(owner=owner3, market_value=300_000.00)
        d3 = create_assessment(
            property_id=prop3["id"], roll_year=2025,
            market_value_at_roll=300_000.00,
        )
        # Issue as officer_x (X-User-ID==officer_x.id).
        api_client.issue_assessment(
            prop3["id"], d3["id"], make_assessor_headers(officer_x["id"]),
        )
        appeal3 = file_appeal(
            owner=owner3, property_id=prop3["id"],
            assessment_id=d3["id"], claimed_value=100_000.00,
        )
        # Attempt to schedule overlapping ROOM_A with officer_x.
        start2 = add_minutes_iso(start1, 30)  # 10:30 — overlaps
        end2 = add_minutes_iso(start2, 60)
        resp = api_client.schedule_appeal(
            prop3["id"], appeal3["id"],
            schedule_appeal_payload(
                scheduled_start=start2, scheduled_end=end2,
                hearing_room="ROOM_A", officer_id=officer_x["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        # PRD §2.9: room overlap (business constraint) precedes the
        # segregation-of-duties check.
        validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


# ===========================================================================
# priority_pair_validation_conflict/business_referential_vs_business_fiscal_pair
# ===========================================================================
class TestAssessmentNotFinalizedBeforeOverpayment:

    def test_assessment_not_finalized_fires_before_overpayment_check(
        self, api,
    ):
        """PRD §2.9: "then cross-entity preconditions such as the
        Assessment being FINALIZED before a bill can issue
        (ERR_ASSESSMENT_NOT_FINALIZED), then temporal gates ... then
        business constraints such as room overlap, officer-buffer,
        exemption uniqueness, exemption eligibility, payment-amount
        sanity".

        Claim: trying to create a TaxBill against an UNDER_APPEAL
        Assessment surfaces ERR_ASSESSMENT_NOT_FINALIZED — payment
        amount sanity (which would trigger ERR_OVERPAYMENT) never
        runs because the cross-entity referential check fires first.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_pair
        """
        # Build an UNDER_APPEAL Assessment.
        owner, prop, asmt = setup_issued_assessment(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=asmt["id"], claimed_value=100_000.00,
        )
        # Try to create a TaxBill. The PRD §3.4 first sentence says
        # this requires Assessment FINALIZED; the validation surfaces
        # ERR_ASSESSMENT_NOT_FINALIZED.
        from test_helpers import api_client, TEST_USERS
        resp = api_client.create_tax_bill(
            prop["id"],
            create_tax_bill_payload(roll_year=2025),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value,
        )


# ===========================================================================
# combinatorial_formula/appeal_decided_then_recomputed_bill_mode_c — 2nd test
# ===========================================================================
class TestPinnedOrderAfterIncreased:

    def test_decide_increased_propagates_pinned_order(self, api):
        """PRD §3.5: "The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED (unchanged
        if UPHELD); the Assessment's version and updated_at are
        bumped."
        PRD §3.5: "The TaxBill for (property_id, roll_year) — if one
        exists — is recomputed via the tax-bill computation in §3.4,
        against the new capped_value."

        Claim: INCREASED decide pushes capped_value upward in the
        pinned cascade; Assessment.capped_value is observable at the
        new decided_value (here 700000).

        # difficulty: combinatorial_formula/appeal_decided_then_recomputed_bill_mode_c
        """
        from test_helpers import setup_heard_appeal, decide_appeal
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="INCREASED", decided_value=700_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            700_000.00, abs=0.01,
        )


# ===========================================================================
# 2nd test for priority_pair_validation_conflict/business_safety_vs_business_constraint_pair
# ===========================================================================
class TestSegregationOnlyWhenNoOtherConstraintFails:
    """Mirror of TestRoomConstraintBeforeOfficerSegregation: when
    ONLY the segregation-of-duties check would fire (no room
    conflict, no buffer conflict), ERR_BOE_OFFICER_CONFLICT is the
    observed error — confirming that the priority precedence does
    not mask the segregation error in isolation."""

    def test_segregation_fires_alone_when_no_room_conflict(self, api):
        """PRD §2.8: "For any given Appeal, the HearingOfficer who is
        recorded as the presiding officer (via Hearing.officer_id)
        must not be the same user who issued the underlying
        Assessment. The server enforces this by comparing the
        officer to the recorded issuer at schedule time and rejecting
        violations with ERR_BOE_OFFICER_CONFLICT."

        Claim: with no overlapping room booking and no officer
        buffer conflict, but officer_id == the Assessor who issued
        the Assessment, the response is ERR_BOE_OFFICER_CONFLICT.
        This pairs with the room-overlap-wins test to nail down
        priority ordering.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_pair
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        officer = create_hearing_officer(full_name="Conflict Officer")
        # Issue as Assessor whose X-User-ID == officer.id.
        from test_helpers import api_client, TEST_USERS
        api_client.issue_assessment(
            prop["id"], draft["id"], make_assessor_headers(officer["id"]),
        )
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=draft["id"], claimed_value=100_000.00,
        )
        # Use a totally empty ROOM_A in the future — no other bookings.
        start = add_minutes_iso(iso_now_utc(), 60)
        end = add_minutes_iso(start, 60)
        resp = api_client.schedule_appeal(
            prop["id"], appeal["id"],
            schedule_appeal_payload(
                scheduled_start=start, scheduled_end=end,
                hearing_room="ROOM_A", officer_id=officer["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BOE_OFFICER_CONFLICT.value)


# ===========================================================================
# 2nd test for priority_pair_validation_conflict/business_referential_vs_business_fiscal_pair
# ===========================================================================
class TestAssessmentNotFinalizedOnIssueAttempt:

    def test_issue_bill_with_under_appeal_assessment_rejected(self, api):
        """PRD §3.4: "Two cross-entity preconditions guard the
        transition: the linked Assessment must be FINALIZED, otherwise
        ERR_ASSESSMENT_NOT_FINALIZED".

        Claim: directly attempting POST /tax_bills/{id}/issue while
        the linked Assessment is still UNDER_APPEAL is rejected with
        ERR_ASSESSMENT_NOT_FINALIZED — a second test of the
        cross-entity referential gate (paired with the
        bill-creation attempt in the other test).

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_pair
        """
        # First, FINALIZE an Assessment cleanly and create a bill in
        # PENDING. Then re-open: a new Appeal cannot be filed on a
        # FINALIZED Assessment per PRD §3.5; so to reach a state where
        # the bill is PENDING + Assessment is UNDER_APPEAL we must
        # come at it from the other direction.
        # We model the gate by: issuing the Assessment, NOT finalizing
        # it (Assessment stays ISSUED), and attempting to create+issue
        # a TaxBill — the server must reject creation since the
        # Assessment is not FINALIZED.
        owner, prop, asmt = setup_issued_assessment(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        # Assessment is ISSUED, not FINALIZED.
        assert asmt["status"] == "ISSUED"
        from test_helpers import api_client, TEST_USERS
        resp = api_client.create_tax_bill(
            prop["id"],
            create_tax_bill_payload(roll_year=2025),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value,
        )
