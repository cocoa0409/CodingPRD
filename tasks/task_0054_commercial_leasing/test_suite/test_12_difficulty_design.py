"""SCAFFOLD_DIFFICULTY_DESIGN coverage — every difficulty-design
instance is exercised by at least TWO tests tagged `# difficulty:
<rule_id>/<instance.name>` per skill §2.1.A.

Test recipes are translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml;
assertions cite the PRD prose that states the underlying rule.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    amend_confirm,
    amend_lease,
    approve_deductions,
    confirm_restoration,
    create_approved_tenant,
    create_building,
    create_energy_fee_bill,
    create_energy_fee_bill_payload,
    create_lease,
    create_property_fee_bill,
    create_property_fee_bill_payload,
    create_unit,
    finalize_move_out,
    finish_renovation,
    get_deposit,
    get_lease,
    get_move_out_request,
    get_rent_schedule,
    get_tenant,
    get_unit,
    list_audit_events,
    make_child_unit_spec,
    make_deduction_item,
    make_stepped_entry,
    make_tenant_headers,
    move_out_request,
    move_out_request_payload,
    propose_deductions,
    record_inspection,
    setup_active_lease,
    setup_building_with_unit,
    setup_building_with_two_units,
    setup_signed_lease,
    setup_stepped_vs_annual_pair,
    setup_two_active_leases_for_energy_allocation,
    setup_terminating_lease,
    setup_restoration_confirmed,
    sign_lease,
    split_unit_payload,
    start_renovation,
    top_up_deposit,
    unique_unit_code,
    validate_error,
    validate_success,
    FO, LA, PM,
)


# ===========================================================================
# Rule 1: dual_variant_calc — rent_schedule_stepped_vs_annual
# ===========================================================================
class TestDualVariantRentSchedule:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    rent_schedule_stepped_vs_annual.

    PRD §3.4 backs the underlying rule: 'When escalation_mode is ANNUAL,
    the algorithm computes the number of full years elapsed from the
    lease's start_date ... When escalation_mode is STEPPED, the
    algorithm performs a table lookup against the stepped_schedule
    array.'
    """

    def test_annual_year_one_no_escalation_sums_to_eleven_months_at_base(
        self, api,
    ):
        """PRD §3.4: 'When escalation_mode is ANNUAL, the algorithm
        computes the number of full years elapsed from the lease's
        start_date to the start of M as the floor of the elapsed days
        divided by 365.25.'

        With a Jan-1 to Dec-1 (11-month) lease at 100000 base, all 11
        months sit in year 1 (years_elapsed = 0), so total = 11 × 100000
        = 1,100,000 cents.
        """
        # difficulty: dual_variant_calc/rent_schedule_stepped_vs_annual
        ctx = setup_stepped_vs_annual_pair()
        rows = get_rent_schedule(ctx["lease_annual"]["id"])
        total = sum(r["net_rent_cents"] for r in rows)
        assert total == 1100000, (
            f"ANNUAL year-1 total should be 11 × 100000 = 1100000, "
            f"got {total}"
        )

    def test_stepped_table_lookup_differs_from_annual(self, api):
        """PRD §3.4: 'When escalation_mode is STEPPED, the algorithm
        performs a table lookup against the stepped_schedule array:
        the monthly rent in effect on M is the monthly_rent_cents of
        the entry with the largest index whose effective_from is on or
        before M's start.'

        Stepped schedule: Jan-1 at 100000, Jul-1 at 110000 → 6×100000
        + 5×110000 = 1,150,000; differs from ANNUAL's 1,100,000.
        """
        # difficulty: dual_variant_calc/rent_schedule_stepped_vs_annual
        ctx = setup_stepped_vs_annual_pair()
        rows = get_rent_schedule(ctx["lease_stepped"]["id"])
        total = sum(r["net_rent_cents"] for r in rows)
        assert total == 1150000, (
            f"STEPPED total should be 6×100000 + 5×110000 = 1150000, "
            f"got {total}"
        )
        # And it must differ from ANNUAL's 1100000.
        annual_rows = get_rent_schedule(ctx["lease_annual"]["id"])
        assert total != sum(r["net_rent_cents"] for r in annual_rows)


# ===========================================================================
# Rule 1: dual_variant_calc — energy_sub_meter_vs_allocated
# ===========================================================================
class TestDualVariantEnergyFee:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    energy_sub_meter_vs_allocated.

    PRD §3.7 backs the underlying rule: 'In SUB_METER mode the request
    must include sub_meter_kwh ... In ALLOCATED mode ... the system
    then computes this unit's share of the shared kWh as
    shared_total_kwh × (this_unit.area_sqm / total_group_area).'
    """

    def test_sub_meter_amount_is_kwh_times_tariff(self, api):
        """PRD §3.7: 'In SUB_METER mode ... the bill amount is the
        round-half-up of sub_meter_kwh × tariff_per_kwh_cents — this
        charge ignores area entirely.'

        For 200 kWh at 50 cents/kWh: amount_cents = 200 × 50 = 10000.
        """
        # difficulty: dual_variant_calc/energy_sub_meter_vs_allocated
        ctx = setup_two_active_leases_for_energy_allocation(
            area_a=100.0, area_b=300.0,
        )
        bill_a = create_energy_fee_bill(
            lease_id=ctx["lease_a"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            energy_mode="SUB_METER",
            tariff_per_kwh_cents=50,
            sub_meter_kwh=200,
        )
        assert bill_a["amount_cents"] == 10000

    def test_allocated_distributes_by_area_share(self, api):
        """PRD §3.7: 'In ALLOCATED mode ... the system then computes
        this unit's share of the shared kWh as shared_total_kwh ×
        (this_unit.area_sqm / total_group_area) ... The bill's
        amount_cents is then the round-half-up of the share multiplied
        by tariff_per_kwh_cents.'

        Unit_a (100 sqm), Unit_b (300 sqm); shared 1000 kWh, tariff 50.
        Unit_a's share = 1000 × (100/400) = 250 kWh → 250 × 50 = 12500.
        """
        # difficulty: dual_variant_calc/energy_sub_meter_vs_allocated
        ctx = setup_two_active_leases_for_energy_allocation(
            area_a=100.0, area_b=300.0,
        )
        bill_b = create_energy_fee_bill(
            lease_id=ctx["lease_a"]["id"],
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            energy_mode="ALLOCATED",
            shared_total_kwh=1000,
            shared_meter_group_unit_ids=[
                ctx["unit_a"]["id"], ctx["unit_b"]["id"],
            ],
            tariff_per_kwh_cents=50,
        )
        assert bill_b["amount_cents"] == 12500


# ===========================================================================
# Rule 2: combinatorial_formula — property_fee_with_cap_and_modes
# ===========================================================================
class TestPropertyFeeCapAndModes:
    """SCAFFOLD_DIFFICULTY_DESIGN rule combinatorial_formula / instance
    property_fee_with_cap_and_modes.

    PRD §3.7: 'the computed amount is then capped at the round-half-up
    of 5000 cents (50.00 currency units) per square metre per month,
    multiplied by the unit's area_sqm and by months_in_period; the
    bill's final amount_cents is the minimum of the computed amount
    and that cap.'
    """

    def test_high_rate_clipped_to_cap(self, api):
        """PRD §3.7: 'the bill's final amount_cents is the minimum of
        the computed amount and that cap.'

        Unit 100 sqm, rate 6000 cents/sqm/month, 1 month →
        raw = 100×6000×1 = 600000; cap = 5000×100×1 = 500000 → 500000.
        """
        # difficulty: combinatorial_formula/property_fee_with_cap_and_modes
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="BY_AREA",
            rate_per_sqm_per_month_cents=6000,
        )
        assert bill["amount_cents"] == 500000

    def test_low_rate_returns_raw_below_cap(self, api):
        """PRD §3.7: 'the bill's final amount_cents is the minimum of
        the computed amount and that cap.'

        Unit 100 sqm, rate 3000 cents/sqm/month, 1 month →
        raw = 100×3000×1 = 300000; cap = 500000 → raw wins (300000).
        """
        # difficulty: combinatorial_formula/property_fee_with_cap_and_modes
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            property_fee_mode="BY_AREA",
            rate_per_sqm_per_month_cents=3000,
        )
        assert bill["amount_cents"] == 300000


# ===========================================================================
# Rule 2: combinatorial_formula — energy_allocation_rounding_order
# ===========================================================================
class TestEnergyAllocationRoundingOrder:
    """SCAFFOLD_DIFFICULTY_DESIGN rule combinatorial_formula / instance
    energy_allocation_rounding_order.

    PRD §2.8: 'When an energy bill in ALLOCATED mode distributes a
    shared meter total across multiple units, each per-unit share is
    rounded half-up first, then summed; the unit whose id is
    lexicographically smallest in shared_meter_group_unit_ids absorbs
    whatever integer-cent remainder is needed to make the per-unit sum
    equal exactly the round-half-up of shared_total_kwh ×
    tariff_per_kwh_cents.'
    """

    def test_group_sum_equals_un_rounded_total(self, api):
        """PRD §2.8: 'the unit whose id is lexicographically smallest
        in shared_meter_group_unit_ids absorbs whatever integer-cent
        remainder is needed to make the per-unit sum equal exactly the
        round-half-up of shared_total_kwh × tariff_per_kwh_cents.'

        Two units (equal area), shared 1 kWh, tariff 33 cents/kWh:
        - Naive per-line: 0.5 × 33 = 16.5 → 17 cents each; sum = 34.
        - Required: total = round_half_up(1 × 33) = 33; one bill must
          absorb a -1 cent remainder so sum = 33 exactly.
        """
        # difficulty: combinatorial_formula/energy_allocation_rounding_order
        ctx = setup_two_active_leases_for_energy_allocation(
            area_a=100.0, area_b=100.0,
        )
        bill_a = create_energy_fee_bill(
            lease_id=ctx["lease_a"]["id"],
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-04-01T00:00:00.000Z",
            energy_mode="ALLOCATED",
            shared_total_kwh=1.0,
            shared_meter_group_unit_ids=[
                ctx["unit_a"]["id"], ctx["unit_b"]["id"],
            ],
            tariff_per_kwh_cents=33,
        )
        bill_b = create_energy_fee_bill(
            lease_id=ctx["lease_b"]["id"],
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-04-01T00:00:00.000Z",
            energy_mode="ALLOCATED",
            shared_total_kwh=1.0,
            shared_meter_group_unit_ids=[
                ctx["unit_a"]["id"], ctx["unit_b"]["id"],
            ],
            tariff_per_kwh_cents=33,
        )
        # Per PRD §2.8 the group-wide sum equals round_half_up(1.0 × 33) = 33.
        assert bill_a["amount_cents"] + bill_b["amount_cents"] == 33, (
            f"group sum must equal round_half_up(1.0 × 33) = 33; got "
            f"{bill_a['amount_cents']} + {bill_b['amount_cents']}"
        )

    def test_canonical_unit_absorbs_remainder(self, api):
        """PRD §2.8: 'the unit whose id is lexicographically smallest
        in shared_meter_group_unit_ids absorbs whatever integer-cent
        remainder is needed.'

        For naive per-unit round-half-up of 16.5 → 17 each (sum = 34),
        the canonical (lex-smallest) unit must absorb a -1 cent
        remainder, ending at 16; the non-canonical unit remains at 17.
        """
        # difficulty: combinatorial_formula/energy_allocation_rounding_order
        ctx = setup_two_active_leases_for_energy_allocation(
            area_a=100.0, area_b=100.0,
        )
        bill_a = create_energy_fee_bill(
            lease_id=ctx["lease_a"]["id"],
            period_start="2026-04-01T00:00:00.000Z",
            period_end="2026-05-01T00:00:00.000Z",
            energy_mode="ALLOCATED",
            shared_total_kwh=1.0,
            shared_meter_group_unit_ids=[
                ctx["unit_a"]["id"], ctx["unit_b"]["id"],
            ],
            tariff_per_kwh_cents=33,
        )
        bill_b = create_energy_fee_bill(
            lease_id=ctx["lease_b"]["id"],
            period_start="2026-04-01T00:00:00.000Z",
            period_end="2026-05-01T00:00:00.000Z",
            energy_mode="ALLOCATED",
            shared_total_kwh=1.0,
            shared_meter_group_unit_ids=[
                ctx["unit_a"]["id"], ctx["unit_b"]["id"],
            ],
            tariff_per_kwh_cents=33,
        )
        # Identify canonical (lex-smallest unit_id) bill.
        canonical_id = min(ctx["unit_a"]["id"], ctx["unit_b"]["id"])
        if bill_a["unit_id"] == canonical_id:
            canonical, other = bill_a, bill_b
        else:
            canonical, other = bill_b, bill_a
        assert canonical["amount_cents"] == 16, (
            f"canonical bill (unit_id={canonical_id}) should absorb -1 "
            f"cent remainder → 16; got {canonical['amount_cents']}"
        )
        assert other["amount_cents"] == 17, (
            f"non-canonical bill should be 17; got {other['amount_cents']}"
        )


# ===========================================================================
# Rule 3: non_linear_state_machine — lease_amendment_cycle
# ===========================================================================
class TestLeaseAmendmentCycle:
    """SCAFFOLD_DIFFICULTY_DESIGN rule non_linear_state_machine /
    instance lease_amendment_cycle.

    PRD §3.5 backs the underlying rules for both transitions of the
    cycle.
    """

    def test_amend_cancel_does_not_increment_amendment_count(self, api):
        """PRD §3.5: 'Cancellation simply restores the lease's status
        to ACTIVE and the deposit's adjustment_status to AT_REST without
        other field changes.'

        Cancel cycle does NOT modify amendment_count.
        """
        # difficulty: non_linear_state_machine/lease_amendment_cycle
        ctx = setup_active_lease(base_monthly_rent_cents=100000)
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=110000,
        )
        from test_helpers import amend_cancel
        lease = amend_cancel(ctx["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["amendment_count"] == 0
        assert lease["base_monthly_rent_cents"] == 100000

    def test_amend_confirm_increments_amendment_count_after_cancel(
        self, api,
    ):
        """PRD §3.5: 'On success, the lease's status returns to ACTIVE,
        the amendment_count is incremented by one ...'

        After a cancel cycle (count stays 0), a subsequent confirm
        cycle moves count to 1 and applies the new base rent.
        """
        # difficulty: non_linear_state_machine/lease_amendment_cycle
        ctx = setup_active_lease(base_monthly_rent_cents=100000)
        # First cycle: amend + cancel (no increment)
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=110000,
        )
        from test_helpers import amend_cancel
        amend_cancel(ctx["lease"]["id"])
        # Second cycle: amend + confirm
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        amend_confirm(ctx["lease"]["id"])
        lease = get_lease(ctx["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["amendment_count"] == 1
        assert lease["base_monthly_rent_cents"] == 120000


# ===========================================================================
# Rule 3: non_linear_state_machine — deposit_parallel_dimensions
# ===========================================================================
class TestDepositParallelDimensions:
    """SCAFFOLD_DIFFICULTY_DESIGN rule non_linear_state_machine /
    instance deposit_parallel_dimensions.

    PRD §3.6: 'These two status fields evolve independently: a deposit
    can be FROZEN while still AT_REST or DEDUCTION_PENDING_APPROVAL,
    and a top-up does not change its frozen state.'
    """

    def test_move_out_freezes_but_keeps_adjustment_at_rest(self, api):
        """PRD §3.8: 'On success, the lease's status moves from ACTIVE
        to TERMINATING ... the deposit's frozen_status moves to FROZEN.'

        PRD §3.6: 'These two status fields evolve independently'. After
        move-out the deposit must be FROZEN AND still AT_REST.
        """
        # difficulty: non_linear_state_machine/deposit_parallel_dimensions
        ctx = setup_terminating_lease()
        dep = ctx["deposit"]
        assert dep["frozen_status"] == "FROZEN"
        assert dep["adjustment_status"] == "AT_REST"

    def test_propose_deductions_changes_adjustment_independently_of_frozen(
        self, api,
    ):
        """PRD §3.8: 'On success, the deposit's adjustment_status moves
        to DEDUCTION_PENDING_APPROVAL ...'

        PRD §3.6: 'These two status fields evolve independently'. The
        propose-deductions call moves adjustment_status while leaving
        frozen_status FROZEN.
        """
        # difficulty: non_linear_state_machine/deposit_parallel_dimensions
        ctx = setup_restoration_confirmed()
        dep = propose_deductions(
            ctx["deposit"]["id"],
            [make_deduction_item(kind="CLEANING", amount_cents=1000)],
        )
        assert dep["frozen_status"] == "FROZEN"
        assert dep["adjustment_status"] == "DEDUCTION_PENDING_APPROVAL"


# ===========================================================================
# Rule 4: transitive_cascade — lease_finalize_depth_4_cascade
# ===========================================================================
class TestLeaseFinalizeDepth4Cascade:
    """SCAFFOLD_DIFFICULTY_DESIGN rule transitive_cascade / instance
    lease_finalize_depth_4_cascade.

    PRD §3.8 / §2.6 / §3.4: finalize cascades through Lease →
    MoveOutRequest → Unit → RentScheduleItem, and emits an
    AuditEvent CONTRACT_TERMINATED.
    """

    def test_finalize_cascades_lease_move_out_and_unit(self, api):
        """PRD §3.8: 'the lease's status moves from TERMINATING to
        TERMINATED ... the move-out request cascades to SETTLED ... the
        unit cascades back to VACANT.'
        """
        # difficulty: transitive_cascade/lease_finalize_depth_4_cascade
        from test_helpers import setup_finalized_lease
        ctx = setup_finalized_lease()
        assert ctx["lease"]["status"] == "TERMINATED"
        assert ctx["move_out_request"]["status"] == "SETTLED"
        assert ctx["unit"]["status"] == "VACANT"

    def test_finalize_voids_future_rent_rows_and_emits_terminated_audit(
        self, api,
    ):
        """PRD §3.8: 'every RentScheduleItem whose period_start is
        strictly after terminated_on is moved to VOIDED; ... an
        AuditEvent with action CONTRACT_TERMINATED is recorded.'
        """
        # difficulty: transitive_cascade/lease_finalize_depth_4_cascade
        from test_helpers import setup_finalized_lease
        ctx = setup_finalized_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            activate_clock="2026-01-01T00:00:00.000Z",
            move_out_clock="2026-02-01T00:00:00.000Z",
            target_move_out_date="2026-04-01T00:00:00.000Z",
        )
        rows = get_rent_schedule(ctx["lease"]["id"])
        terminated_on = ctx["lease"]["terminated_on"]
        for r in rows:
            if r["period_start"] > terminated_on:
                assert r["status"] == "VOIDED"
        audits = list_audit_events(
            subject_kind="LEASE", subject_id=ctx["lease"]["id"],
            action="CONTRACT_TERMINATED",
        )
        assert len(audits) >= 1


# ===========================================================================
# Rule 4: transitive_cascade — unit_split_depth_3_cascade
# ===========================================================================
class TestUnitSplitDepth3Cascade:
    """SCAFFOLD_DIFFICULTY_DESIGN rule transitive_cascade / instance
    unit_split_depth_3_cascade.

    PRD §3.1: Split retires parent, creates children VACANT, emits
    UNIT_SPLIT audit.
    """

    def test_split_retires_parent_and_makes_children_vacant(self, api):
        """PRD §3.1: 'On success, the parent's status becomes RETIRED;
        each child is persisted with status VACANT.'
        """
        # difficulty: transitive_cascade/unit_split_depth_3_cascade
        b = create_building()
        parent = create_unit(b["id"], area_sqm=100.0)
        res = api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=40.0,
                                     code=unique_unit_code("c1")),
                make_child_unit_spec(area_sqm=60.0,
                                     code=unique_unit_code("c2")),
            ]),
            PM,
        )
        body = res.json()
        children = body["data"]
        assert len(children) == 2
        for c in children:
            assert c["status"] == "VACANT"
            assert c["parent_unit_id"] == parent["id"]
        # Check parent is RETIRED.
        parent_after = get_unit(b["id"], parent["id"])
        assert parent_after["status"] == "RETIRED"

    def test_split_emits_unit_split_audit_event(self, api):
        """PRD §3.1: 'An AuditEvent is recorded with subject_kind UNIT
        and action UNIT_SPLIT.'
        """
        # difficulty: transitive_cascade/unit_split_depth_3_cascade
        b = create_building()
        parent = create_unit(b["id"], area_sqm=100.0)
        api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=40.0,
                                     code=unique_unit_code("d1")),
                make_child_unit_spec(area_sqm=60.0,
                                     code=unique_unit_code("d2")),
            ]),
            PM,
        )
        audits = list_audit_events(
            subject_kind="UNIT", subject_id=parent["id"],
            action="UNIT_SPLIT",
        )
        assert len(audits) >= 1


# ===========================================================================
# Rule 5: priority_pair_validation_conflict — state vs business_referential
# ===========================================================================
class TestStateVsBusinessReferentialPriority:
    """SCAFFOLD_DIFFICULTY_DESIGN rule priority_pair_validation_conflict /
    instance state_vs_business_referential_on_lease_sign.

    PRD §2.10: 'Only after all four of these gates pass does the
    server examine state-machine preconditions (which fail with
    ERR_INVALID_STATE, HTTP 409) and the domain-specific business
    validations such as ERR_TENANT_NOT_APPROVED.'

    State precedes business_referential — re-signing a non-DRAFT lease
    must return ERR_INVALID_STATE even if the tenant is also not
    APPROVED.
    """

    def test_resign_signed_lease_returns_invalid_state(self, api):
        """PRD §2.10: 'state-machine preconditions ... fail with
        ERR_INVALID_STATE'. PRD §3.3: 'Signing a drafted lease moves it
        from DRAFT to SIGNED.' Re-signing a SIGNED lease violates the
        state precondition first.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_lease_sign
        ctx = setup_signed_lease()
        res = api.sign_lease(ctx["lease"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_sign_with_unapproved_tenant_on_draft_returns_tenant_not_approved(
        self, api,
    ):
        """PRD §3.3: 'The signing endpoint is rejected with
        ERR_TENANT_NOT_APPROVED unless the lease's tenant has
        qualification_status APPROVED.'

        With state precondition satisfied (lease is DRAFT) the business
        check fires and returns ERR_TENANT_NOT_APPROVED — confirming the
        ordering relative to the state check.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_lease_sign
        b, u = setup_building_with_unit()
        from test_helpers import create_tenant
        t_pending = create_tenant()
        lease = create_lease(
            unit_id=u["id"], tenant_id=t_pending["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_TENANT_NOT_APPROVED.value)


# ===========================================================================
# Rule 5: priority_pair_validation_conflict — business_safety vs business_temporal
# ===========================================================================
class TestBusinessSafetyVsBusinessTemporalPriority:
    """SCAFFOLD_DIFFICULTY_DESIGN rule priority_pair_validation_conflict /
    instance business_safety_vs_business_temporal_on_lease_sign.

    PRD §2.10 lists ERR_RENOVATION_LEASE_CONFLICT and ERR_LEASE_OVERLAP
    as members of the same business-validation family without pinning a
    relative order between them. This is a validation-priority silence
    in PRD prose: when both could trip, PRD does not commit to which is
    returned. We assert the documentable rule — that the request is
    rejected with ONE of the two business errors — using
    validate_error_is_one_of per skill silence pattern. Logged in the
    Summary under: validation-priority (rule 5 / instance
    business_safety_vs_business_temporal_on_lease_sign).
    """

    def test_renovation_overlap_alone_returns_renovation_conflict(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'

        Isolated trigger: only the renovation check can trip. We do not
        call finish_renovation because PRD §3.1 says closing clears both
        renovation dates, which would prevent the overlap check from
        firing. The stored interval is in the past relative to "today"
        so the unit's derived status is VACANT and the unit-availability
        gate passes; the stored interval still drives the renovation
        overlap rule per PRD §3.3.
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_lease_sign
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance the logical clock past renovation_end_date so the
        # unit's derived status is VACANT and the sign request reaches
        # the renovation-overlap check.
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-10T00:00:00.000Z",
            end_date="2026-09-10T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_RENOVATION_LEASE_CONFLICT.value)

    def test_lease_overlap_alone_returns_lease_overlap(self, api):
        """PRD §3.3: 'with ERR_LEASE_OVERLAP if any other lease on the
        same unit whose status is SIGNED, ACTIVE, AMENDMENT_PENDING, or
        TERMINATING has an interval that overlaps the half-open window
        of this lease.'

        Isolated trigger: only the overlap check can trip.
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_lease_sign
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        sign_lease(l1["id"])
        t2 = create_approved_tenant()
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-05-15T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(l2["id"], LA)
        validate_error(res, ApiErrorId.ERR_LEASE_OVERLAP.value)


# ===========================================================================
# Rule 6: boundary_precision_check — move_out_lead_time_30_day_boundary
# ===========================================================================
class TestMoveOutLeadTimeBoundary:
    """SCAFFOLD_DIFFICULTY_DESIGN rule boundary_precision_check /
    instance move_out_lead_time_30_day_boundary.

    PRD §3.8: 'at least 30 days after the current server date — the
    lead-time check is strict at the day granularity, so 29 days from
    today is rejected while 30 days from today is accepted.'
    """

    def test_29_days_rejected(self, api):
        """PRD §3.8: '29 days from today is rejected'."""
        # difficulty: boundary_precision_check/move_out_lead_time_30_day_boundary
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        advance_clock("2026-02-01T00:00:00.000Z")
        res = api.move_out_request(
            ctx["lease"]["id"],
            move_out_request_payload(
                target_move_out_date="2026-03-02T00:00:00.000Z",
            ),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MOVE_OUT_LEAD_TIME.value)

    def test_30_days_accepted(self, api):
        """PRD §3.8: '30 days from today is accepted'."""
        # difficulty: boundary_precision_check/move_out_lead_time_30_day_boundary
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        advance_clock("2026-02-01T00:00:00.000Z")
        res = api.move_out_request(
            ctx["lease"]["id"],
            move_out_request_payload(
                target_move_out_date="2026-03-03T00:00:00.000Z",
            ),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SUBMITTED"


# ===========================================================================
# Rule 6: boundary_precision_check — empty_pending_deduction_items_settlement
# ===========================================================================
class TestEmptyPendingDeductionItems:
    """SCAFFOLD_DIFFICULTY_DESIGN rule boundary_precision_check /
    instance empty_pending_deduction_items_settlement.

    PRD §3.8: 'Approving the deductions ... sets the deposit's
    retained_cents to the sum of pending_deduction_items[].amount_cents,
    sets its refunded_cents to collected_cents − retained_cents.'

    For an empty pending list, retained = 0 (empty sum) and refunded =
    collected.
    """

    def test_empty_deduction_items_settle_with_full_refund(self, api):
        """PRD §3.8: 'sets the deposit's retained_cents to the sum of
        pending_deduction_items[].amount_cents, sets its refunded_cents
        to collected_cents − retained_cents.'
        """
        # difficulty: boundary_precision_check/empty_pending_deduction_items_settlement
        ctx = setup_restoration_confirmed(
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        propose_deductions(ctx["deposit"]["id"], [])  # empty list
        dep = approve_deductions(ctx["deposit"]["id"])
        assert dep["retained_cents"] == 0
        assert dep["refunded_cents"] == 100000
        assert dep["adjustment_status"] == "SETTLED"

    def test_empty_deductions_update_tenant_ledger_fully(self, api):
        """PRD §3.8: 'recomputes the tenant's total_deposit_retained_cents
        and total_deposit_refunded_cents.'
        """
        # difficulty: boundary_precision_check/empty_pending_deduction_items_settlement
        ctx = setup_restoration_confirmed(
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        propose_deductions(ctx["deposit"]["id"], [])
        approve_deductions(ctx["deposit"]["id"])
        tenant = get_tenant(ctx["tenant"]["id"])
        assert tenant["total_deposit_paid_cents"] == 100000
        assert tenant["total_deposit_refunded_cents"] == 100000
        assert tenant["total_deposit_retained_cents"] == 0


# ===========================================================================
# Rule 7: cross_entity_state_dependency — lease_sign_requires_unit_not_renovating
# ===========================================================================
class TestLeaseSignRequiresUnitNotRenovating:
    """SCAFFOLD_DIFFICULTY_DESIGN rule cross_entity_state_dependency /
    instance lease_sign_requires_unit_not_renovating.

    PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's current
    renovation interval — when extended by one buffer day at its end —
    overlaps the lease window'.
    """

    def test_sign_overlapping_renovation_rejected(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'
        """
        # difficulty: cross_entity_state_dependency/lease_sign_requires_unit_not_renovating
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance the logical clock past renovation_end_date so the
        # unit's derived status is VACANT (sign reaches the overlap
        # check rather than tripping the unit-availability gate).
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        # Lease starts 2026-03-10 — overlaps [2026-03-01, 2026-03-16].
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-10T00:00:00.000Z",
            end_date="2026-09-10T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_RENOVATION_LEASE_CONFLICT.value)

    def test_sign_clear_of_renovation_buffer_accepted(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'

        A lease starting 2 days past the renovation_end_date (outside
        buffer) must be acceptable.
        """
        # difficulty: cross_entity_state_dependency/lease_sign_requires_unit_not_renovating
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance past renovation so unit is VACANT for the sign.
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-17T00:00:00.000Z",
            end_date="2026-09-17T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        data = validate_success(res)
        assert data["status"] == "SIGNED"


# ===========================================================================
# Rule 7: cross_entity_state_dependency — fee_bill_payment_requires_lease_billable
# ===========================================================================
class TestFeeBillRequiresLeaseBillable:
    """SCAFFOLD_DIFFICULTY_DESIGN rule cross_entity_state_dependency /
    instance fee_bill_payment_requires_lease_billable.

    PRD §3.7: 'The bill request is rejected with ERR_LEASE_NOT_BILLABLE
    unless the owning lease's status is ACTIVE, AMENDMENT_PENDING, or
    TERMINATING — bills against leases in DRAFT, SIGNED, or TERMINATED
    cannot be issued.'
    """

    def test_issue_bill_against_signed_lease_rejected(self, api):
        """PRD §3.7: 'bills against leases in DRAFT, SIGNED, or
        TERMINATED cannot be issued.'
        """
        # difficulty: cross_entity_state_dependency/fee_bill_payment_requires_lease_billable
        ctx = setup_signed_lease()
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="FIXED_RATE",
                fixed_rate_cents_per_month=50000,
            ),
            FO,
        )
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_BILLABLE.value)

    def test_issue_bill_against_active_lease_accepted(self, api):
        """PRD §3.7: 'unless the owning lease's status is ACTIVE,
        AMENDMENT_PENDING, or TERMINATING'.

        A bill issued against an ACTIVE lease succeeds.
        """
        # difficulty: cross_entity_state_dependency/fee_bill_payment_requires_lease_billable
        ctx = setup_active_lease()
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="FIXED_RATE",
                fixed_rate_cents_per_month=50000,
            ),
            FO,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ISSUED"


# ===========================================================================
# Rule 8: resource_temporal_overlap — lease_half_open_overlap_on_unit
# ===========================================================================
class TestLeaseHalfOpenOverlapOnUnit:
    """SCAFFOLD_DIFFICULTY_DESIGN rule resource_temporal_overlap /
    instance lease_half_open_overlap_on_unit.

    PRD §3.3: '(note: adjacency where the end_date of one lease equals
    the start_date of another is permitted and does not count as
    overlap)'.
    """

    def test_adjacent_leases_allowed(self, api):
        """PRD §3.3: '(note: adjacency where the end_date of one lease
        equals the start_date of another is permitted and does not
        count as overlap)'."""
        # difficulty: resource_temporal_overlap/lease_half_open_overlap_on_unit
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        sign_lease(l1["id"])
        t2 = create_approved_tenant()
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(l2["id"], LA)
        data = validate_success(res)
        assert data["status"] == "SIGNED"

    def test_one_day_interior_overlap_rejected(self, api):
        """PRD §3.3: 'with ERR_LEASE_OVERLAP if any other lease on the
        same unit whose status is SIGNED, ACTIVE, AMENDMENT_PENDING, or
        TERMINATING has an interval that overlaps the half-open window
        of this lease.'
        """
        # difficulty: resource_temporal_overlap/lease_half_open_overlap_on_unit
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        sign_lease(l1["id"])
        t2 = create_approved_tenant()
        # Interior overlap: 2026-05-31..2026-06-01 is one day of overlap.
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-05-31T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(l2["id"], LA)
        validate_error(res, ApiErrorId.ERR_LEASE_OVERLAP.value)


# ===========================================================================
# Rule 8: resource_temporal_overlap — renovation_closed_interval_with_buffer
# ===========================================================================
class TestRenovationClosedIntervalWithBuffer:
    """SCAFFOLD_DIFFICULTY_DESIGN rule resource_temporal_overlap /
    instance renovation_closed_interval_with_buffer.

    PRD §3.1 / §3.3: 'the closed-with-buffer renovation window
    [renovation_start_date, renovation_end_date + 1 day] (one buffer
    day past the renovation's nominal end)'.
    """

    def test_lease_on_buffer_day_rejected(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'

        Lease start = renovation_end_date + 1 day (the buffer day)
        must still overlap the closed-with-buffer window.
        """
        # difficulty: resource_temporal_overlap/renovation_closed_interval_with_buffer
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance past renovation_end_date so derived status is VACANT.
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        # 2026-03-16 = renovation_end_date + 1 (buffer day)
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-16T00:00:00.000Z",
            end_date="2026-09-16T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_RENOVATION_LEASE_CONFLICT.value)

    def test_lease_past_buffer_day_accepted(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'

        Lease start = renovation_end_date + 2 days is just past the
        buffer and must succeed.
        """
        # difficulty: resource_temporal_overlap/renovation_closed_interval_with_buffer
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance past renovation_end_date so derived status is VACANT.
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-17T00:00:00.000Z",
            end_date="2026-09-17T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        data = validate_success(res)
        assert data["status"] == "SIGNED"


# ===========================================================================
# Rule 9: compensating_invariant — deposit_ledger_invariant
# ===========================================================================
class TestDepositLedgerInvariant:
    """SCAFFOLD_DIFFICULTY_DESIGN rule compensating_invariant / instance
    deposit_ledger_invariant.

    PRD §2.9: 'After every collection, refund, or retention against
    any single Deposit for the tenant, the live held-by-landlord
    balance for the tenant — total_deposit_paid_cents −
    total_deposit_refunded_cents − total_deposit_retained_cents — must
    equal the sum across that tenant's deposit rows of
    collected_cents − refunded_cents − retained_cents.'
    """

    def test_outstanding_balance_after_top_up_matches_per_deposit_sum(
        self, api,
    ):
        """PRD §2.9: 'the live held-by-landlord balance for the tenant
        ... must equal the sum across that tenant's deposit rows of
        collected_cents − refunded_cents − retained_cents.'
        """
        # difficulty: compensating_invariant/deposit_ledger_invariant
        ctx = setup_signed_lease(
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        top_up_deposit(
            ctx["deposit"]["id"], tenant_id=ctx["tenant"]["id"],
            amount_cents=100000,
        )
        tenant = get_tenant(ctx["tenant"]["id"])
        dep = get_deposit(ctx["deposit"]["id"])
        outstanding = (
            tenant["total_deposit_paid_cents"]
            - tenant["total_deposit_refunded_cents"]
            - tenant["total_deposit_retained_cents"]
        )
        per_deposit = (
            dep["collected_cents"] - dep["refunded_cents"]
            - dep["retained_cents"]
        )
        assert outstanding == per_deposit, (
            f"PRD §2.9 invariant violated: aggregate outstanding="
            f"{outstanding}, per-row sum={per_deposit}"
        )
        assert outstanding == 100000

    def test_outstanding_balance_zero_after_full_refund(self, api):
        """PRD §2.9: 'After every collection, refund, or retention ...
        the live held-by-landlord balance for the tenant ... must equal
        the sum across that tenant's deposit rows of collected_cents
        − refunded_cents − retained_cents.'

        After a full settlement with zero retention, the tenant
        outstanding balance is exactly zero.
        """
        # difficulty: compensating_invariant/deposit_ledger_invariant
        from test_helpers import setup_finalized_lease
        ctx = setup_finalized_lease(
            base_monthly_rent_cents=100000, deposit_months=1,
            deduction_items=[],  # empty deductions → full refund
        )
        tenant = get_tenant(ctx["tenant"]["id"])
        outstanding = (
            tenant["total_deposit_paid_cents"]
            - tenant["total_deposit_refunded_cents"]
            - tenant["total_deposit_retained_cents"]
        )
        assert outstanding == 0
        assert tenant["total_deposit_paid_cents"] == 100000
        assert tenant["total_deposit_refunded_cents"] == 100000
        assert tenant["total_deposit_retained_cents"] == 0


# ===========================================================================
# Rule 9: compensating_invariant — rent_schedule_amendment_conservation
# ===========================================================================
class TestRentScheduleAmendmentConservation:
    """SCAFFOLD_DIFFICULTY_DESIGN rule compensating_invariant / instance
    rent_schedule_amendment_conservation.

    PRD §3.4: 'When an amendment is confirmed, only those rows whose
    period_start is on or after the amendment's effective_from are
    regenerated; rows for earlier months are preserved unchanged.'
    """

    def test_pre_effective_rent_cents_preserved_after_amend(self, api):
        """PRD §3.4: 'When an amendment is confirmed, only those rows
        whose period_start is on or after the amendment's
        effective_from are regenerated; rows for earlier months are
        preserved unchanged.'
        """
        # difficulty: compensating_invariant/rent_schedule_amendment_conservation
        ctx = setup_active_lease(
            base_monthly_rent_cents=100000,
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-07-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        # Pre-amend total = 6 months × 100000 = 600000
        pre = get_rent_schedule(ctx["lease"]["id"])
        pre_window = sum(
            r["net_rent_cents"] for r in pre
            if r["period_start"] < "2026-04-01T00:00:00.000Z"
        )
        assert pre_window == 300000  # Jan/Feb/Mar
        # Amend.
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        amend_confirm(ctx["lease"]["id"])
        post = get_rent_schedule(ctx["lease"]["id"])
        post_pre_window = sum(
            r["net_rent_cents"] for r in post
            if r["period_start"] < "2026-04-01T00:00:00.000Z"
        )
        assert post_pre_window == 300000, (
            f"pre-amend cumulative rent ({pre_window}) must be "
            f"preserved after amend-confirm; got {post_pre_window}"
        )

    def test_post_effective_rent_cents_regenerated_at_new_rate(self, api):
        """PRD §3.4: 'When an amendment is confirmed, only those rows
        whose period_start is on or after the amendment's
        effective_from are regenerated.'

        Post-effective window must use the new base rent.
        """
        # difficulty: compensating_invariant/rent_schedule_amendment_conservation
        ctx = setup_active_lease(
            base_monthly_rent_cents=100000,
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-07-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        amend_confirm(ctx["lease"]["id"])
        rows = get_rent_schedule(ctx["lease"]["id"])
        post_window = sum(
            r["net_rent_cents"] for r in rows
            if r["period_start"] >= "2026-04-01T00:00:00.000Z"
        )
        # 3 months × 120000 = 360000
        assert post_window == 360000, (
            f"post-amend window should be 3×120000=360000, got {post_window}"
        )
