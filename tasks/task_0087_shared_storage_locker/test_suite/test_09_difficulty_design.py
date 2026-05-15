"""Difficulty-design priority-queue coverage.

Every instance declared in the difficulty-design index is exercised by
at least TWO dedicated tests. Each test cites the verbatim PRD sentence
that states the rule the instance exercises.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    approve_claim,
    create_active_rental,
    create_pricing_profile,
    create_pricing_profile_payload,
    create_rental_payload,
    deny_claim,
    drive_cabinet_offline,
    drive_claim_to_denied,
    file_insurance_claim,
    iso_utc,
    make_renter_headers,
    open_repair_ticket,
    refund_rental_payload,
    reject_evidence,
    rent_k_compartments,
    request_evidence,
    return_rental_as_owner,
    return_rental_payload,
    run_sweep,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    setup_cabinet_with_n_small_compartments,
    setup_force_cleared_rental,
    setup_overdue_rental,
    setup_returned_rental,
    setup_returned_rental_with_insurance_claim,
    submit_evidence,
    validate_error,
    validate_success,
    walk_repair_to_accepted,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantOverdueFeeLiveVsSettled:
    """difficulty: dual_variant_calc/overdue_fee_live_vs_settled_on_rental"""

    def test_live_estimate_returns_one_started_hour_at_exactly_one_hour_past_grace(
        self, api,
    ):
        """PRD §3.3: "a live-estimate variant used when a reader fetches
        a rental whose status is OVERDUE, which uses the current logical
        clock as the inspection time and is not persisted."

        Claim: at exactly grace_end + 1h00m the live read returns
        overdue_fee_cents == 200 (ceil((3600)/3600)=1 * 200).
        # difficulty: dual_variant_calc/overdue_fee_live_vs_settled_on_rental
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # Bring rental into OVERDUE first.
        advance_clock_to(started_at + timedelta(hours=1, minutes=15, seconds=1))
        run_sweep()
        # Now park at grace_end + 1h00m exactly (= started + 2h15m).
        advance_clock_to(started_at + timedelta(hours=2, minutes=15))
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        # 1 started hour past grace = 1 * 200.
        assert refreshed["status"] == "OVERDUE"
        assert refreshed["overdue_fee_cents"] == 200, (
            f"live_estimate at grace_end+1h00m should give 200 cents "
            f"(ceil(3600/3600)=1 * 200), got {refreshed['overdue_fee_cents']}"
        )

    def test_final_settled_after_one_extra_second_yields_two_hours(self, api):
        """PRD §3.3: "a final-settled variant used at the moment of
        return or force-clearance, which uses the transition's ended_at
        as the inspection time, persists the value into
        overdue_fee_cents."
        PRD §3.3: "Otherwise the overdue elapsed time is the number of
        seconds from the grace-end instant to the inspection time;
        that elapsed time, divided by 3600, is rounded up to the next
        whole hour (any started hour counts as a full hour), and the
        resulting number of hours is multiplied by overdue_rate_snapshot
        to yield overdue_fee_cents."

        Claim: return at grace_end + 1h00m01s gives overdue_fee_cents=400
        (ceil(3601/3600)=2 * 200), demonstrating round-then-multiply.
        # difficulty: dual_variant_calc/overdue_fee_live_vs_settled_on_rental
        # difficulty: combinatorial_formula/overdue_fee_round_then_multiply_order_pinned
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # Advance to grace_end + 1h00m01s = started+1h15m+1h00m01s.
        advance_clock_to(started_at + timedelta(
            hours=2, minutes=15, seconds=1,
        ))
        run_sweep()
        # Now return.
        from test_helpers import return_rental_as_owner
        returned = return_rental_as_owner(rental, ctx["renter_id"])
        assert returned["status"] == "RETURNED"
        # ceil(3601/3600) = 2; 2 * 200 = 400.
        assert returned["overdue_fee_cents"] == 400, (
            f"final_settled overdue_fee_cents at grace_end+1h01s should be 400 "
            f"(ceil(3601/3600)=2 * 200), got {returned['overdue_fee_cents']}"
        )


class TestDualVariantRevenueShareRowVsPeriod:
    """difficulty: dual_variant_calc/revenue_share_per_row_vs_per_period_on_revenuerecord"""

    def test_per_row_partner_share_uses_round_half_up_per_row(
        self, api, operator_headers,
    ):
        """PRD §2.12: "the row-level split rounds the partner share
        half-up and assigns the residual to the platform so that the
        two always sum to gross_cents."

        Claim: 3 rows of gross=15 with partner_share_pct=30 yield
        partner_share_cents=5 each (round_half_up(15*0.30)=
        round_half_up(4.5)=5).
        # difficulty: dual_variant_calc/revenue_share_per_row_vs_per_period_on_revenuerecord
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            3, rental_mode="DAILY",
            cabinet_overrides={"partner_share_pct": 30},
            pricing_overrides={
                "unit_price_cents": 15,
                "deposit_cents": 0,
                "grace_minutes": 15,
                "overdue_rate_cents_per_hour": 0,
                "forced_clearance_hours": 48,
            },
        )
        for i, comp in enumerate(comps):
            r, rid = create_active_rental(
                cabinet["id"], comp["id"],
                renter_id=f"renter-row-{i}",
                rental_mode="DAILY", billing_units=1, unlock_channel="QR",
            )
            return_rental_as_owner(r, rid)
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": cabinet["id"],
            "revenue_kind": "RENTAL_FEE",
        }).json()["data"]
        rows = [r for r in rows if r["cabinet_id"] == cabinet["id"]
                and r["revenue_kind"] == "RENTAL_FEE" and r["gross_cents"] == 15]
        assert len(rows) >= 3
        for r in rows[:3]:
            assert r["partner_share_cents"] == 5, (
                f"per-row round_half_up(4.5)=5, got "
                f"{r['partner_share_cents']}"
            )
            assert r["platform_share_cents"] == 10
        assert sum(r["partner_share_cents"] for r in rows[:3]) == 15

    def test_per_period_aggregate_differs_by_one_cent(self, api,
                                                     operator_headers):
        """PRD §3.6: "the summary first sums gross_cents across the
        period, then computes the aggregate partner share as that sum
        multiplied by partner_share_pct divided by 100 and rounded
        half-up, then derives the aggregate platform share as the
        period total minus the aggregate partner share."

        Claim: with 3 rows of gross=15 + partner_share_pct=30, summary
        returns total_partner_cents=14 (round_half_up(45*0.30)=
        round_half_up(13.5)=14) — 1 cent less than the per-row sum.
        # difficulty: dual_variant_calc/revenue_share_per_row_vs_per_period_on_revenuerecord
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            3, rental_mode="DAILY",
            cabinet_overrides={"partner_share_pct": 30},
            pricing_overrides={
                "unit_price_cents": 15,
                "deposit_cents": 0,
                "grace_minutes": 15,
                "overdue_rate_cents_per_hour": 0,
                "forced_clearance_hours": 48,
            },
        )
        for i, comp in enumerate(comps):
            r, rid = create_active_rental(
                cabinet["id"], comp["id"],
                renter_id=f"renter-period-{i}",
                rental_mode="DAILY", billing_units=1, unlock_channel="QR",
            )
            return_rental_as_owner(r, rid)
        summary = validate_success(api.get_revenue_summary(
            cabinet["id"], operator_headers,
        ))
        assert summary["total_gross_cents"] == 45
        assert summary["total_partner_cents"] == 14, (
            f"per-period round_half_up(13.5)=14, got "
            f"{summary['total_partner_cents']}"
        )
        assert summary["total_platform_cents"] == 31


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialInsurancePremium:
    """difficulty: combinatorial_formula/insurance_premium_three_inputs_nonlinear"""

    def test_basic_tier_2day_500k_premium_equals_1100(self, api):
        """PRD §3.4: "BASIC carries a base rate of 50 cents per day ...
        a value-loading amount is computed as declared_value_cents
        multiplied by the tier loading rate (0.002 for BASIC, 0.005 for
        PREMIUM) and then rounded up to the next whole cent."

        Claim: BASIC + DAILY*2 + declared=500000 → premium = 50*2 +
        ceil(500000*0.002) = 100+1000 = 1100.
        # difficulty: combinatorial_formula/insurance_premium_three_inputs_nonlinear
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="DAILY",
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-comb-basic",
            rental_mode="DAILY", billing_units=2,
            insurance_tier="BASIC", declared_value_cents=500_000,
            unlock_channel="QR",
        )
        assert rental["insurance_premium_cents"] == 1100

    def test_premium_tier_2day_500k_premium_equals_2800(self, api):
        """PRD §3.4: "BASIC carries a base rate of 50 cents per day and
        PREMIUM carries 150 cents per day."
        PRD §3.4: "the tier loading rate (0.002 for BASIC, 0.005 for
        PREMIUM)."

        Claim: PREMIUM + DAILY*2 + declared=500000 → premium = 150*2 +
        ceil(500000*0.005) = 300+2500 = 2800.
        # difficulty: combinatorial_formula/insurance_premium_three_inputs_nonlinear
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="DAILY", slot_count=2,
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-comb-prem",
            rental_mode="DAILY", billing_units=2,
            insurance_tier="PREMIUM", declared_value_cents=500_000,
            unlock_channel="QR",
        )
        assert rental["insurance_premium_cents"] == 2800


class TestCombinatorialOverdueRoundThenMultiply:
    """difficulty: combinatorial_formula/overdue_fee_round_then_multiply_order_pinned"""

    def test_3601_seconds_yields_2_hours_times_rate(self, api):
        """PRD §3.3: "the overdue elapsed time is the number of seconds
        from the grace-end instant to the inspection time; that elapsed
        time, divided by 3600, is rounded up to the next whole hour
        (any started hour counts as a full hour), and the resulting
        number of hours is multiplied by overdue_rate_snapshot to yield
        overdue_fee_cents. The rounding-up happens before the
        multiplication, never after."

        Claim: 3601 overdue seconds → 2 hours * 200 = 400 (NOT
        round(3601*200/3600)=200).
        # difficulty: combinatorial_formula/overdue_fee_round_then_multiply_order_pinned
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # grace_end = started + 1h15m. Land at grace_end + 1h00m01s.
        advance_clock_to(started_at + timedelta(
            hours=2, minutes=15, seconds=1,
        ))
        run_sweep()
        returned = return_rental_as_owner(rental, ctx["renter_id"])
        assert returned["overdue_fee_cents"] == 400

    def test_exactly_at_grace_end_zero_fee(self, api):
        """PRD §3.3: "If the inspection time is at or before the
        grace-end instant the overdue fee is zero."

        Claim: returning exactly at grace_end yields overdue_fee_cents=0
        (no started hours, even one second early would be 0).
        # difficulty: combinatorial_formula/overdue_fee_round_then_multiply_order_pinned
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # Land at grace_end exactly (started + 1h15m).
        advance_clock_to(started_at + timedelta(hours=1, minutes=15))
        returned = return_rental_as_owner(rental, ctx["renter_id"])
        assert returned["overdue_fee_cents"] == 0


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestInsuranceClaimEvidenceCycle:
    """difficulty: non_linear_state_machine/insurance_claim_evidence_rejection_cycle"""

    def test_reject_evidence_returns_to_evidence_rejected(self, api):
        """PRD §3.9: "While UNDER_REVIEW, the agent has three exits:
        reject the current evidence batch by supplying rejection_reason,
        advancing to EVIDENCE_REJECTED."

        Claim: UNDER_REVIEW → EVIDENCE_REJECTED via reject-evidence.
        # difficulty: non_linear_state_machine/insurance_claim_evidence_rejection_cycle
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-cycle-1",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        assert c["status"] == "UNDER_REVIEW"
        c = reject_evidence(c["id"], reason="blurry", version=c["version"])
        assert c["status"] == "EVIDENCE_REJECTED"

    def test_re_request_after_rejection_returns_to_evidence_pending(self, api):
        """PRD §3.9: "After EVIDENCE_REJECTED, the agent may re-request
        evidence, returning the claim to EVIDENCE_PENDING; this is the
        cycle that makes the claim state machine non-linear, and it
        may repeat any number of times."

        Claim: EVIDENCE_REJECTED → EVIDENCE_PENDING via request-evidence;
        a re-submission increments evidence_count to 2 and brings status
        back to UNDER_REVIEW.
        # difficulty: non_linear_state_machine/insurance_claim_evidence_rejection_cycle
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-cycle-2",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        c = reject_evidence(c["id"], reason="blurry", version=c["version"])
        c = request_evidence(c["id"], version=c["version"])
        assert c["status"] == "EVIDENCE_PENDING"
        c = submit_evidence(c["id"], ctx["renter_id"],
                            description="clearer", version=c["version"])
        assert c["status"] == "UNDER_REVIEW"
        assert c["evidence_count"] == 2


class TestRentalBranchingRenewalVsForceClearance:
    """difficulty: non_linear_state_machine/rental_branching_renewal_vs_force_clearance"""

    def test_renew_active_to_active_self_loop(self, api):
        """PRD §3.3: "A Renter who owns a rental may renew it while its
        status is ACTIVE or EXPIRING_SOON. ... A renewal extends
        current_expires_at by renewal_billing_units multiplied by the
        unit-duration for the rental's mode."

        Claim: renew on ACTIVE rental keeps status=ACTIVE and increments
        renewal_count by 1.
        # difficulty: non_linear_state_machine/rental_branching_renewal_vs_force_clearance
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        rental = ctx["rental"]
        from test_helpers import renew_rental_payload
        resp = api.renew_rental(
            rental["id"], renew_rental_payload(renewal_billing_units=1),
            make_renter_headers(ctx["renter_id"]),
        )
        renewed = validate_success(resp)
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewal_count"] == 1

    def test_force_clearance_path_terminates_rental(self, api,
                                                  operator_headers):
        """PRD §3.5: "When the sweep observes that the logical clock has
        reached or passed current_expires_at plus
        forced_clearance_hours_snapshot hours on a rental whose status
        is OVERDUE, force-clearance fires. The rental's status advances
        to FORCE_CLEARED."

        Claim: a rental crossed past forced_clearance becomes
        FORCE_CLEARED with deposit_forfeited_cents=deposit_cents_snapshot,
        an alternative branch to the renewal self-loop above.
        # difficulty: non_linear_state_machine/rental_branching_renewal_vs_force_clearance
        """
        ctx = setup_force_cleared_rental(renter_id="renter-branch-fc")
        r = ctx["rental"]
        assert r["status"] == "FORCE_CLEARED"
        assert r["deposit_forfeited_cents"] == r["deposit_cents_snapshot"]


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestForceClearanceCascade:
    """difficulty: transitive_cascade/force_clearance_three_hop_cascade"""

    def test_force_clearance_cascades_compartment_to_holding(self, api,
                                                            operator_headers):
        """PRD §3.5: "The housing compartment cascades to occupancy_status
        = HOLDING, its active_rental_id is cleared."

        Claim: force-clearance on a single rental causes hop1 (Rental→
        FORCE_CLEARED) and hop2 (Compartment.occupancy_status→HOLDING).
        # difficulty: transitive_cascade/force_clearance_three_hop_cascade
        """
        ctx = setup_force_cleared_rental(renter_id="renter-hop-1")
        comp = validate_success(api.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert ctx["rental"]["status"] == "FORCE_CLEARED"
        assert comp["occupancy_status"] == "HOLDING"
        assert comp.get("active_rental_id") in (None,)

    def test_force_clearance_recomputes_cabinet_capacity_stats(self, api,
                                                              operator_headers):
        """PRD §2.6: "When a Compartment.occupancy_status transitions
        among IDLE, RENTED, OVERDUE, and HOLDING, the parent cabinet's
        per-size-class occupancy percentages (small_occupancy_pct,
        medium_occupancy_pct, large_occupancy_pct) and its
        capacity_alert_level are recomputed in the same request."
        PRD §3.7: "the count of compartments in RENTED or OVERDUE
        becomes the numerator of the corresponding occupancy percentage."

        Claim: after force-clearance, Cabinet.small_occupancy_pct
        reflects HOLDING not counted as occupied (numerator excludes
        HOLDING) — hop3 of the cascade.
        # difficulty: transitive_cascade/force_clearance_three_hop_cascade
        """
        ctx = setup_force_cleared_rental(renter_id="renter-hop-3")
        cabinet = validate_success(api.get_cabinet(
            ctx["cabinet"]["id"], operator_headers,
        ))
        # The single compartment is now HOLDING; numerator is 0 ⇒ pct=0.00.
        assert cabinet["small_occupancy_pct"] == 0.00
        assert cabinet["capacity_alert_level"] == "NONE"


class TestRepairAcceptanceCascade:
    """difficulty: transitive_cascade/repair_acceptance_two_hop_cascade"""

    def test_accept_repair_cascades_compartment_to_ok(self, api,
                                                    operator_headers):
        """PRD §3.8: "An Operator accepts the repair, advancing status
        to ACCEPTED ... cascading the compartment's operational_status
        back to OK, and clearing fault_category."

        Claim: hop1 (ticket→ACCEPTED) + hop2 (Compartment→OK).
        # difficulty: transitive_cascade/repair_acceptance_two_hop_cascade
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = walk_repair_to_accepted(comps[0]["id"])
        assert ticket["status"] == "ACCEPTED"
        comp = validate_success(api.get_compartment(
            cabinet["id"], comps[0]["id"], operator_headers,
        ))
        assert comp["operational_status"] == "OK"
        assert comp.get("fault_category") in (None,)

    def test_rental_creation_succeeds_after_accept(self, api):
        """PRD §3.8: "this makes the compartment rentable again once
        occupancy_status is IDLE."

        Claim: after accept, a new rental on the previously-faulty
        compartment succeeds (was previously blocked by
        ERR_COMPARTMENT_FAULT).
        # difficulty: transitive_cascade/repair_acceptance_two_hop_cascade
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        walk_repair_to_accepted(comps[0]["id"])
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], create_rental_payload(),
            make_renter_headers("renter-after-cascade"),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestForbiddenVsInvalidStateOnRenewal:
    """difficulty: priority_pair_validation_conflict/forbidden_vs_invalid_state_on_renewal"""

    def test_non_owner_on_overdue_returns_forbidden_not_invalid_state(self, api):
        """PRD §2.9: "Renter ownership equality with the owning
        Rental.renter_id or InsuranceClaim.renter_id (ERR_FORBIDDEN) ...
        source-state legality for the requested transition
        (ERR_INVALID_STATE)."

        Claim: a non-owner Renter calling /renew on an OVERDUE rental
        receives ERR_FORBIDDEN (ownership) — not ERR_INVALID_STATE
        (which is later in priority order).
        # difficulty: priority_pair_validation_conflict/forbidden_vs_invalid_state_on_renewal
        """
        ctx = setup_overdue_rental(renter_id="renter-overdue-owner")
        from test_helpers import renew_rental_payload
        resp = api.renew_rental(
            ctx["rental"]["id"], renew_rental_payload(renewal_billing_units=1),
            make_renter_headers("renter-non-owner"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_owner_on_overdue_returns_renewal_not_permitted(self, api):
        """PRD §3.3: "if the rental is already OVERDUE or terminal, the
        renewal is rejected with ERR_RENEWAL_NOT_PERMITTED."

        Claim: owner Renter calling /renew on an OVERDUE rental
        receives ERR_RENEWAL_NOT_PERMITTED (the state-specific error,
        confirming the non-owner test above is the ownership branch).
        # difficulty: priority_pair_validation_conflict/forbidden_vs_invalid_state_on_renewal
        """
        ctx = setup_overdue_rental(renter_id="renter-owner-rnp")
        from test_helpers import renew_rental_payload
        resp = api.renew_rental(
            ctx["rental"]["id"], renew_rental_payload(renewal_billing_units=1),
            make_renter_headers(ctx["renter_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_PERMITTED.value)


class TestCabinetOfflineVsCompartmentUnavailable:
    """difficulty: priority_pair_validation_conflict/cabinet_offline_vs_compartment_unavailable_on_rental_creation"""

    def test_offline_with_qr_returns_offline_not_unavailable(self, api):
        """PRD §2.9: "compartment fault gating (ERR_COMPARTMENT_FAULT),
        cabinet offline gating (ERR_CABINET_OFFLINE), compartment
        occupancy gating (ERR_COMPARTMENT_UNAVAILABLE)."
        PRD §3.1: "while OFFLINE, any IDLE compartment in the cabinet
        remains rentable only via the PASSWORD unlock channel, and
        rental attempts that supply QR or BLUETOOTH are rejected with
        ERR_CABINET_OFFLINE."

        Claim: with cabinet OFFLINE + compartment already RENTED, a new
        QR rental attempt returns ERR_CABINET_OFFLINE (the
        higher-priority business_safety check), not
        ERR_COMPARTMENT_UNAVAILABLE.
        # difficulty: priority_pair_validation_conflict/cabinet_offline_vs_compartment_unavailable_on_rental_creation
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        # First renter occupies it.
        create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-occ-1", unlock_channel="PASSWORD",
        )
        drive_cabinet_offline(cabinet["id"])
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"],
            create_rental_payload(unlock_channel="QR"),
            make_renter_headers("renter-conflict-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CABINET_OFFLINE.value)

    def test_online_occupied_compartment_returns_unavailable(self, api):
        """PRD §3.2: "the compartment's occupancy_status must be IDLE
        (otherwise ERR_COMPARTMENT_UNAVAILABLE)."

        Claim: with cabinet ONLINE + compartment already RENTED, a
        second rental attempt returns ERR_COMPARTMENT_UNAVAILABLE —
        the occupancy-gate fires only when the higher-priority
        offline-gate does not.
        # difficulty: priority_pair_validation_conflict/cabinet_offline_vs_compartment_unavailable_on_rental_creation
        """
        ctx = setup_basic_rental(renter_id="renter-occ-2")
        resp = api.create_rental(
            ctx["cabinet"]["id"], ctx["compartment"]["id"],
            create_rental_payload(unlock_channel="QR"),
            make_renter_headers("renter-conflict-2"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestGracePeriodBoundary:
    """difficulty: boundary_precision_check/grace_period_boundary_inclusive_on_sweep"""

    def test_at_grace_boundary_no_overdue(self, api):
        """PRD §3.3: "If the inspection time is at or before the
        grace-end instant the overdue fee is zero."

        Claim: at exactly current_expires_at + grace_minutes_snapshot,
        overdue_fee_cents = 0 (boundary check on the fee formula).

        NOTE: PRD's "reached or passed current_expires_at plus
        grace_minutes_snapshot minutes" wording is inclusive at the
        boundary, so the status may legitimately flip to OVERDUE at
        exactly grace_end. We only assert the part PRD uniquely
        determines: the overdue fee is zero at the boundary.
        # difficulty: boundary_precision_check/grace_period_boundary_inclusive_on_sweep
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(started_at + timedelta(hours=1, minutes=15))
        run_sweep()
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        assert refreshed["overdue_fee_cents"] == 0

    def test_one_second_past_grace_makes_overdue(self, api):
        """PRD §3.3: "When the sweep observes that the clock has reached
        or passed current_expires_at plus grace_minutes_snapshot
        minutes, an ACTIVE or EXPIRING_SOON rental transitions to
        OVERDUE."

        Claim: at current_expires_at + grace_minutes + 1s,
        status=OVERDUE and overdue_fee_cents = 200 (1 started hour).
        # difficulty: boundary_precision_check/grace_period_boundary_inclusive_on_sweep
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(started_at
                         + timedelta(hours=1, minutes=15, seconds=1))
        run_sweep()
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        assert refreshed["status"] == "OVERDUE"
        assert refreshed["overdue_fee_cents"] == 200


class TestCapacityAlertThresholdBoundary:
    """difficulty: boundary_precision_check/capacity_alert_threshold_exactly_80_pct"""

    def test_60_pct_is_none(self, api, operator_headers):
        """PRD §3.7: "anything below 80.00 is NONE."

        Claim: 3 of 5 SMALL rented = 60.00 → capacity_alert_level=NONE.
        # difficulty: boundary_precision_check/capacity_alert_threshold_exactly_80_pct
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 3, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(cabinet["id"],
                                                 operator_headers))
        assert fresh["small_occupancy_pct"] == 60.00
        assert fresh["capacity_alert_level"] == "NONE"

    def test_exactly_80_pct_trips_warning(self, api, operator_headers):
        """PRD §3.7: "The threshold comparisons are >=, not >, so a
        percentage of exactly 80.00 trips WARNING."

        Claim: 4 of 5 SMALL rented = 80.00 → capacity_alert_level=WARNING.
        # difficulty: boundary_precision_check/capacity_alert_threshold_exactly_80_pct
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 4, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(cabinet["id"],
                                                 operator_headers))
        assert fresh["small_occupancy_pct"] == 80.00
        assert fresh["capacity_alert_level"] == "WARNING"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestRentalRequiresCompartmentOkAndIdle:
    """difficulty: cross_entity_state_dependency/rental_creation_requires_compartment_ok_and_idle"""

    def test_rental_creation_on_faulty_compartment_returns_fault_error(self, api):
        """PRD §3.2: "the compartment's operational_status must be OK
        (otherwise ERR_COMPARTMENT_FAULT)."

        Claim: compartment in FAULT state → ERR_COMPARTMENT_FAULT on
        rental creation.
        # difficulty: cross_entity_state_dependency/rental_creation_requires_compartment_ok_and_idle
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        open_repair_ticket(comps[0]["id"], fault_category="DOOR_NOT_CLOSED")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], create_rental_payload(),
            make_renter_headers("renter-fault-cross"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_FAULT.value)

    def test_rental_creation_succeeds_after_repair_accepted(self, api):
        """PRD §3.8: "this makes the compartment rentable again once
        occupancy_status is IDLE."

        Claim: after dispatch+repair+accept the same POST /rentals
        succeeds with HTTP 201.
        # difficulty: cross_entity_state_dependency/rental_creation_requires_compartment_ok_and_idle
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        walk_repair_to_accepted(comps[0]["id"])
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], create_rental_payload(),
            make_renter_headers("renter-repair-ok"),
        )
        validate_success(resp, expected_status=201)


class TestRefundBlockedByOpenClaim:
    """difficulty: cross_entity_state_dependency/rental_refund_blocked_by_open_insurance_claim"""

    def test_open_claim_blocks_refund(self, api, operator_headers):
        """PRD §3.6: "A refund against a rental with an active or paid
        claim is rejected with ERR_REFUND_BLOCKED_BY_CLAIM."

        Claim: a REPORTED claim on the rental blocks refund.
        # difficulty: cross_entity_state_dependency/rental_refund_blocked_by_open_insurance_claim
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-block-1",
        )
        resp = api.refund_rental(
            ctx["rental"]["id"], refund_rental_payload(),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_BLOCKED_BY_CLAIM.value)

    def test_denied_claim_unblocks_refund(self, api, operator_headers):
        """PRD §3.6: "the only acceptable state of an existing claim is
        DENIED, and the absence of any claim is also acceptable."

        Claim: walking the claim to DENIED unblocks refund.
        # difficulty: cross_entity_state_dependency/rental_refund_blocked_by_open_insurance_claim
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-block-2",
        )
        drive_claim_to_denied(ctx["claim"], ctx["renter_id"])
        resp = api.refund_rental(
            ctx["rental"]["id"], refund_rental_payload(),
            operator_headers,
        )
        refunded = validate_success(resp)
        assert refunded["status"] == "REFUNDED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestCompartmentOccupancyOverlap:
    """difficulty: resource_temporal_overlap/compartment_active_rental_uniqueness_open_interval"""

    def test_second_rental_on_occupied_compartment_rejected(self, api):
        """PRD §3.2: "the compartment's occupancy_status must be IDLE
        (otherwise ERR_COMPARTMENT_UNAVAILABLE)."

        Claim: while R1 is RENTED, R2 on the same compartment →
        ERR_COMPARTMENT_UNAVAILABLE.
        # difficulty: resource_temporal_overlap/compartment_active_rental_uniqueness_open_interval
        """
        ctx = setup_basic_rental(renter_id="renter-overlap-1")
        resp = api.create_rental(
            ctx["cabinet"]["id"], ctx["compartment"]["id"],
            create_rental_payload(),
            make_renter_headers("renter-overlap-2"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE.value)

    def test_new_rental_succeeds_after_return(self, api):
        """PRD §3.6: "On success the rental's status becomes RETURNED,
        ended_at is set to the transition time, the compartment's
        occupancy_status cascades to IDLE, the compartment's
        active_rental_id is cleared, and the cabinet capacity statistics
        are recomputed."
        PRD §3.2: "the compartment's occupancy_status must be IDLE
        (otherwise ERR_COMPARTMENT_UNAVAILABLE)."

        Claim: returning R1 then issuing R3 on the same compartment
        succeeds — adjacency is allowed once R1 has flipped the
        compartment back to IDLE.
        # difficulty: resource_temporal_overlap/compartment_active_rental_uniqueness_open_interval
        """
        ctx = setup_basic_rental(renter_id="renter-overlap-3")
        return_rental_as_owner(ctx["rental"], ctx["renter_id"])
        resp = api.create_rental(
            ctx["cabinet"]["id"], ctx["compartment"]["id"],
            create_rental_payload(),
            make_renter_headers("renter-overlap-4"),
        )
        validate_success(resp, expected_status=201)


class TestCabinetCapacityOverflow:
    """difficulty: resource_temporal_overlap/cabinet_capacity_aggregate_overflow_at_creation"""

    def test_full_cabinet_shows_critical(self, api, operator_headers):
        """PRD §3.7: "A percentage at or above 95.00 is CRITICAL ... so
        ... exactly 95.00 trips CRITICAL."
        PRD §3.7: "When a size class has zero compartments, its
        occupancy percentage is zero."

        Claim: 5 of 5 SMALL rented = 100.00% → CRITICAL.
        # difficulty: resource_temporal_overlap/cabinet_capacity_aggregate_overflow_at_creation
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 5, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert fresh["small_occupancy_pct"] == 100.00
        assert fresh["capacity_alert_level"] == "CRITICAL"

    def test_overflow_attempt_returns_compartment_unavailable(self, api,
                                                             operator_headers):
        """PRD §3.2: "the compartment's occupancy_status must be IDLE
        (otherwise ERR_COMPARTMENT_UNAVAILABLE)."

        Claim: with all 5 SMALL compartments RENTED, attempting a 6th
        rental on any of them → ERR_COMPARTMENT_UNAVAILABLE.
        # difficulty: resource_temporal_overlap/cabinet_capacity_aggregate_overflow_at_creation
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 5, rental_mode="DAILY")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], create_rental_payload(rental_mode="DAILY"),
            make_renter_headers("renter-overflow"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestRefundNetZeroInvariant:
    """difficulty: compensating_invariant/rental_refund_revenue_net_zero_invariant"""

    def test_sum_gross_zero_after_refund(self, api, operator_headers):
        """PRD §3.6: "a REFUND_REVERSAL RevenueRecord row is emitted
        whose gross_cents is the negative of the sum of all prior
        RENTAL_FEE and OVERDUE_FEE gross_cents for this rental."

        Claim: SUM(gross_cents) over all RevenueRecord rows for this
        rental is 0 after refund.
        # difficulty: compensating_invariant/rental_refund_revenue_net_zero_invariant
        """
        ctx = setup_returned_rental(renter_id="renter-net-1")
        api.refund_rental(ctx["rental"]["id"], refund_rental_payload(),
                          operator_headers)
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
        }).json()["data"]
        rows = [r for r in rows if r["rental_id"] == ctx["rental"]["id"]]
        assert sum(r["gross_cents"] for r in rows) == 0

    def test_partner_and_platform_each_sum_zero(self, api, operator_headers):
        """PRD §2.12: "the row-level split rounds the partner share
        half-up and assigns the residual to the platform so that the
        two always sum to gross_cents, including for negative-
        gross_cents refund reversal rows."

        Claim: SUM(partner_share_cents) and SUM(platform_share_cents)
        each equal 0 after refund (per-row residual rule extends to
        the negative reversal row).
        # difficulty: compensating_invariant/rental_refund_revenue_net_zero_invariant
        """
        ctx = setup_returned_rental(renter_id="renter-net-2")
        api.refund_rental(ctx["rental"]["id"], refund_rental_payload(),
                          operator_headers)
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
        }).json()["data"]
        rows = [r for r in rows if r["rental_id"] == ctx["rental"]["id"]]
        assert sum(r["partner_share_cents"] for r in rows) == 0
        assert sum(r["platform_share_cents"] for r in rows) == 0


class TestOccupancyCountConservation:
    """difficulty: compensating_invariant/compartment_occupancy_count_conservation_on_return"""

    def test_capacity_total_invariant_across_cycle(self, api, operator_headers):
        """PRD §3.7: "For each size class, the count of compartments in
        that class becomes small_capacity_total."

        Claim: small_capacity_total is unchanged across rent+return.
        # difficulty: compensating_invariant/compartment_occupancy_count_conservation_on_return
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            4, rental_mode="DAILY",
        )
        s0 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        rental, renter_id = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-cap-cyc-a",
            rental_mode="DAILY", billing_units=1, unlock_channel="QR",
        )
        s1 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        return_rental_as_owner(rental, renter_id)
        s2 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        assert s0["small_capacity_total"] == 4
        assert s1["small_capacity_total"] == 4
        assert s2["small_capacity_total"] == 4

    def test_occupancy_pct_returns_to_pre_value(self, api, operator_headers):
        """PRD §3.7: "the count of compartments in RENTED or OVERDUE
        becomes the numerator of the corresponding occupancy
        percentage."

        Claim: occupancy_pct after return equals occupancy_pct before
        the forward rental action.
        # difficulty: compensating_invariant/compartment_occupancy_count_conservation_on_return
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            4, rental_mode="DAILY",
        )
        s0 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        rental, renter_id = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-cap-cyc-b",
            rental_mode="DAILY", billing_units=1, unlock_channel="QR",
        )
        s1 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        return_rental_as_owner(rental, renter_id)
        s2 = validate_success(api.get_cabinet(cabinet["id"], operator_headers))
        assert s0["small_occupancy_pct"] == 0.00
        assert s1["small_occupancy_pct"] == 25.00
        assert s2["small_occupancy_pct"] == 0.00
