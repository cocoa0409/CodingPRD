"""Custody transfer creation, dual-variant volume computation, quality gates,
dispute/resolve cycle, loss fields, tank inventory cascades and the
certify-then-void compensating invariant (PRD §2.6, §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_custody_transfer,
    collect_sample,
    make_customer_rep_headers,
    make_manager_headers,
    record_sample_result,
    setup_certified_custody,
    setup_completed_movement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    certify_transfer,
    get_lease,
    get_movement,
    get_movement_custody_transfer,
    get_tank,
    set_clock,
)


class TestProvisionalVsCertifiedVolume:
    def _certified_4069_scenario(self):
        """DIESEL RECEIPT declared 4069; OPENING 1000 @60F, CLOSING 5100 @70F;
        PASSED sample at specific_gravity 0.84 (DIESEL standard is 0.85).

        PRD §3.7 formula: V_corr(t) = v * (1 - 0.0006 * (t - 60)); raw =
        5100*0.994 - 1000 == 4069.4. Provisional: round_half_up(4069.4) ==
        4069. Certified: round_half_up(4069.4 * 0.84/0.85) == 4022, with the
        rounding applied exactly once per variant computation (PRD §2.10)."""
        bundle = setup_completed_movement(
            declared_volume_bbl=4069, opening_volume=1000, closing_volume=5100,
            open_temp=60, close_temp=70,
            capacity_bbl=200000, heel_bbl=100, allocated_bbl=50000,
            window_start="2026-05-10T10:00:00Z", window_end="2026-05-10T20:00:00Z",
            arrive_clock="2026-05-10T10:00:00Z", complete_clock="2026-05-10T16:10:00Z",
            open_observed_at="2026-05-10T10:05:00Z", close_observed_at="2026-05-10T16:05:00Z",
            customer_name="Acme Oil",
            lease_overrides={"committed_capacity_bbl": 100000,
                             "min_monthly_throughput_bbl": 1000})
        return bundle

    def test_provisional_volume_temperature_corrected_only(self, api):
        """PRD §3.7: "The provisional variant rounds this transferred volume
        half-up to whole barrels and stores it as `provisional_volume_bbl` —
        temperature-corrected only, with standard gravity assumed."
        Gauges 1000@60F -> 5100@70F give a corrected transfer of 4069.4, so
        provisional_volume_bbl == 4069 at completion (before certification).

        Design: Difficulty/dual_variant_calc/custody_provisional_vs_certified_volume
        """
        bundle = self._certified_4069_scenario()
        custody = bundle["custody"]
        assert custody["status"] == "PROVISIONAL"
        assert custody["provisional_volume_bbl"] == 4069, (
            f"temperature-only correction must give 4069, got {custody['provisional_volume_bbl']}"
        )

    def test_certified_volume_applies_specific_gravity_ratio(self, api):
        """PRD §3.7: "On certification the certified variant volume is
        computed: the same temperature-corrected transferred volume as above,
        now additionally multiplied by the ratio of the passed sample's
        `specific_gravity` to the standard gravity for the movement's
        `product_grade`, where the standard gravities are 0.74 for `GASOLINE`,
        0.85 for `DIESEL`, 0.80 for `JET`, 0.79 for `ETHANOL`, and 0.87 for
        `CRUDE`; the result is rounded half-up to whole barrels and stored as
        `certified_volume_bbl`. The certified figure diverges from the
        provisional whenever the lab's specific gravity differs from the grade
        standard."
        round_half_up(4069.4 * 0.84/0.85) == 4022 != 4069 (provisional).

        Design: Difficulty/dual_variant_calc/custody_provisional_vs_certified_volume
        """
        bundle = self._certified_4069_scenario()
        sample = collect_sample(bundle["movement"]["id"], sample_type="INLINE", collector_id="qi-1")
        record_sample_result(sample["id"], lab_result="PASSED", specific_gravity=0.84,
                             recorder_id="qi-2")
        certified = certify_transfer(bundle["custody"]["id"], certifier_id="tm-1")
        assert certified["status"] == "CERTIFIED"
        assert certified["provisional_volume_bbl"] == 4069
        assert certified["certified_volume_bbl"] == 4022, (
            f"certified variant must apply the 0.84/0.85 ratio to the unrounded "
            f"transfer (4022), got {certified['certified_volume_bbl']}"
        )
        assert certified["certified_volume_bbl"] != certified["provisional_volume_bbl"]
        assert certified["certified_by_user_id"] == "tm-1"


class TestCertifyQualityGate:
    def _provisional_with_sample(self, record=None):
        bundle = setup_completed_movement(customer_name="Blue Ridge Oil")
        sample = collect_sample(bundle["movement"]["id"], sample_type="FIRST_FOOT",
                                collector_id="qi-1")
        if record is not None:
            record_sample_result(sample["id"], lab_result=record["lab_result"],
                                 specific_gravity=record["specific_gravity"], recorder_id="qi-2")
        return bundle, sample

    def test_pending_sample_blocks_certify(self, api):
        """PRD §3.7: "a `QualitySample` for the movement must exist with
        `lab_result` equal to `PASSED` — a missing sample, a `PENDING` result,
        or a `FAILED` result all reject as `ERR_QUALITY_NOT_PASSED`
        (HTTP 409)". The transfer is PROVISIONAL (correct from-state) yet the
        cross-entity quality gate rejects certification.

        Design: Difficulty/cross_entity_state_dependency/certify_requires_sample_passed
        """
        bundle, _ = self._provisional_with_sample()
        resp = api.certify_custody_transfer(bundle["custody"]["id"], make_manager_headers("tm-1"))
        validate_error(resp, ApiErrorId.ERR_QUALITY_NOT_PASSED)
        assert resp.status_code == 409

    def test_rejected_certify_leaves_transfer_provisional(self, api):
        """PRD §3.7: "a missing sample, a `PENDING` result, or a `FAILED`
        result all reject as `ERR_QUALITY_NOT_PASSED` (HTTP 409)". The rejected
        certification leaves the custody transfer PROVISIONAL.

        Design: Difficulty/cross_entity_state_dependency/certify_requires_sample_passed
        """
        bundle, _ = self._provisional_with_sample()
        api.certify_custody_transfer(bundle["custody"]["id"], make_manager_headers("tm-1"))
        after = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert after["status"] == "PROVISIONAL"

    def test_failed_sample_blocks_certify(self, api):
        """PRD §3.7: "a `QualitySample` for the movement must exist with
        `lab_result` equal to `PASSED` — a missing sample, a `PENDING` result,
        or a `FAILED` result all reject as `ERR_QUALITY_NOT_PASSED`
        (HTTP 409)". A FAILED result (recorded by a different inspector than
        the collector) blocks certification exactly as PENDING does.

        Design: Corner/state_machines/quality_sample_failed_blocks_certify
        """
        bundle, _ = self._provisional_with_sample(
            record={"lab_result": "FAILED", "specific_gravity": 0.91})
        resp = api.certify_custody_transfer(bundle["custody"]["id"], make_manager_headers("tm-1"))
        validate_error(resp, ApiErrorId.ERR_QUALITY_NOT_PASSED)
        assert resp.status_code == 409
        after = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert after["status"] == "PROVISIONAL"


class TestCompleteCreatesProvisionalCustody:
    def test_complete_auto_creates_provisional_transfer(self, api):
        """PRD §3.6: "Completion stamps `actual_complete_at` with the logical
        clock, computes `demurrage_actual_amount` per the actual-settlement
        variant of §3.9, auto-creates the movement's `CustodyTransfer` in
        `PROVISIONAL` status with its `provisional_volume_bbl` computed per the
        provisional variant of §3.7, and recomputes the tank's
        `provisional_inventory_bbl`."
        PRD §3.7: "Every completed movement has exactly one `CustodyTransfer`,
        auto-created `PROVISIONAL` at completion."
        Gauges 0 -> 1000 @60F: provisional 1000; the certified inventory
        remains 0 while the provisional figure reflects the new barrels.

        Design: Corner/endpoints/complete_creates_provisional_custody_transfer
        """
        bundle = setup_completed_movement(declared_volume_bbl=1000, opening_volume=0,
                                          closing_volume=1000, customer_name="Provisional Co")
        custody = bundle["custody"]
        assert custody["status"] == "PROVISIONAL"
        assert custody["provisional_volume_bbl"] == 1000
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 0, "PROVISIONAL transfers contribute 0 to certified inventory"
        assert tank["provisional_inventory_bbl"] == 1000


class TestDisputeResolveCycle:
    def _certified_500(self):
        return setup_certified_custody(
            declared_volume_bbl=500, opening_volume=0, closing_volume=500,
            specific_gravity=0.85, capacity_bbl=100000, heel_bbl=0,
            customer_name="Island Terminal Co",
            lease_overrides={"committed_capacity_bbl": 50000})

    def test_dispute_keeps_inventory_contribution(self, api):
        """PRD §3.7: "a `CustomerRep` whose `X-User-ID` equals the lease's
        `customer_id` may move the transfer from `CERTIFIED` to `DISPUTED`" and
        "A disputed transfer still contributes its `certified_volume_bbl` to
        tank inventory — the physical barrels do not un-move because paperwork
        is contested."

        Design: Difficulty/non_linear_state_machine/custody_dispute_resolve_cycle
        """
        bundle = self._certified_500()
        assert get_tank(bundle["tank"]["id"])["current_inventory_bbl"] == 500
        disputed = validate_success(api.dispute_custody_transfer(
            bundle["custody"]["id"], make_customer_rep_headers(bundle["customer"]["id"])))
        assert disputed["status"] == "DISPUTED"
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 500, "DISPUTED transfers still count at certified volume"

    def test_resolve_returns_to_certified_with_inventory_unchanged(self, api):
        """PRD §3.7: "A `TerminalManager` may resolve the dispute, returning
        the transfer from `DISPUTED` to `CERTIFIED` and recomputing any open
        statement under the same rules as at certification." The cyclic
        CERTIFIED -> DISPUTED -> CERTIFIED loop leaves the tank's certified
        inventory at 500 before, during, and after.

        Design: Difficulty/non_linear_state_machine/custody_dispute_resolve_cycle
        """
        bundle = self._certified_500()
        api.dispute_custody_transfer(bundle["custody"]["id"],
                                     make_customer_rep_headers(bundle["customer"]["id"]))
        resolved = validate_success(api.resolve_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert resolved["status"] == "CERTIFIED"
        assert get_tank(bundle["tank"]["id"])["current_inventory_bbl"] == 500


class TestShrinkageAndAllowance:
    def test_allowed_loss_rounds_half_up(self, api):
        """PRD §3.7: "`shrinkage_bbl` is the movement's `declared_volume_bbl`
        minus `certified_volume_bbl`, signed — a negative value means a gain.
        `allowed_loss_bbl` is the declared volume multiplied by the lease's
        `loss_allowance_pct`, rounded half-up to whole barrels.
        `excess_loss_bbl` is the greater of zero and the shrinkage minus the
        allowance; a gain therefore yields zero excess loss, and unused
        allowance is never banked across transfers."
        Declared 500, certified 498: shrinkage 2; round_half_up(500 * 0.005)
        == round_half_up(2.5) == 3; excess == max(0, 2 - 3) == 0; charge 0.00.

        Design: Corner/calculations/shrinkage_allowance_rounds_half_up
        """
        bundle = setup_certified_custody(
            declared_volume_bbl=500, opening_volume=0, closing_volume=498,
            specific_gravity=0.85, customer_name="Round Half Co")
        custody = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert custody["shrinkage_bbl"] == 2
        assert custody["allowed_loss_bbl"] == 3, (
            f"round_half_up(2.5) must be 3, got {custody['allowed_loss_bbl']}"
        )
        assert custody["excess_loss_bbl"] == 0
        assert custody["excess_loss_charge"] == pytest.approx(0.00, abs=0.01)


class TestTankRestrictedCascade:
    def test_certify_over_working_capacity_restricts_tank(self, api):
        """PRD §2.6: "Whenever a custody certification, dispute resolution, or
        void recomputes these figures and `current_inventory_bbl` lands above
        `working_capacity_bbl` or below `heel_bbl`, the tank automatically
        transitions from `AVAILABLE` to `RESTRICTED`."
        Tank 5000 bbl shell, heel 0: working capacity floor(5000*0.95) == 4750.
        Certifying a 4751-bbl transfer pushes inventory above the bound.

        Design: Corner/state_machines/tank_auto_restricted_when_certified_over_working_capacity
        """
        bundle = setup_certified_custody(
            declared_volume_bbl=4750, opening_volume=0, closing_volume=4751,
            specific_gravity=0.85, capacity_bbl=5000, heel_bbl=0, allocated_bbl=4750,
            customer_name="Overfill Co",
            lease_overrides={"committed_capacity_bbl": 10000})
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 4751
        assert tank["status"] == "RESTRICTED", (
            f"4751 > working capacity 4750 must auto-restrict, got {tank['status']}"
        )


class TestCertifyVoidInvariant:
    def _certified_500(self):
        return setup_certified_custody(
            declared_volume_bbl=500, opening_volume=0, closing_volume=500,
            specific_gravity=0.85, customer_name="Cascade Energy")

    def test_certify_adds_certified_volume_to_inventory(self, api):
        """PRD §2.6: "`current_inventory_bbl` is the read-only certified
        inventory of a tank: the sum over the tank's custody transfers in
        `CERTIFIED` or `DISPUTED` status of the signed certified volume, where
        a `RECEIPT` movement contributes positively and a `DISCHARGE`
        negatively." Certification of the 500-bbl RECEIPT raises the fresh
        tank's certified inventory from 0 to exactly 500.

        Design: Difficulty/compensating_invariant/certify_then_void_leaves_inventory_unchanged
        """
        bundle = self._certified_500()
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 500, (
            f"certify must add exactly the certified volume, got {tank['current_inventory_bbl']}"
        )

    def test_void_restores_pre_certify_inventory(self, api):
        """PRD §2.6: "A certify followed by a void of the same transfer must
        leave `current_inventory_bbl` unchanged — voiding is the compensating
        action that excludes the transfer from the inventory projection."

        Design: Difficulty/compensating_invariant/certify_then_void_leaves_inventory_unchanged
        """
        bundle = self._certified_500()
        voided = validate_success(api.void_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert voided["status"] == "VOID"
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 0, (
            f"certify-then-void must restore the conserved quantity, got {tank['current_inventory_bbl']}"
        )


class TestLossControlSuspensionCascade:
    def _cascade_scenario(self):
        """Declared 10000, certified 9800 (gauges 0 -> 9800 @60F, sg ==
        standard): shrinkage 200, allowed round_half_up(10000*0.002) == 20,
        excess 180 > 100 cap. An OPEN 2026-05 statement exists before
        certification."""
        bundle = setup_completed_movement(
            declared_volume_bbl=10000, opening_volume=0, closing_volume=9800,
            capacity_bbl=200000, heel_bbl=100, allocated_bbl=50000,
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
            arrive_clock="2026-05-10T08:00:00Z", complete_clock="2026-05-10T12:05:00Z",
            open_observed_at="2026-05-10T08:05:00Z", close_observed_at="2026-05-10T12:00:00Z",
            customer_name="Marathon Supply",
            lease_overrides={"committed_capacity_bbl": 100000,
                             "loss_allowance_pct": 0.002,
                             "excess_loss_rate_per_bbl": 10.00},
            statement_period="2026-05")
        bundle["sample"] = collect_sample(bundle["movement"]["id"], collector_id="qi-1")
        record_sample_result(bundle["sample"]["id"], lab_result="PASSED",
                             specific_gravity=0.85, recorder_id="qi-2")
        return bundle

    def test_certify_recomputes_open_statement(self, api):
        """PRD §3.7: "If an `OPEN` monthly statement exists for the lease
        covering the period containing the movement's `actual_complete_at`,
        that statement is recomputed per §3.8." Excess loss of 180 bbl at
        10.00/bbl lands on the statement as total_excess_loss_bbl == 180 and
        excess_loss_amount == 1800.00 once the transfer is CERTIFIED.

        Design: Difficulty/transitive_cascade/certify_triggers_statement_rollup_and_loss_suspension
        """
        bundle = self._cascade_scenario()
        certified = certify_transfer(bundle["custody"]["id"], certifier_id="tm-1")
        assert certified["status"] == "CERTIFIED"
        statement = validate_success(api.get_monthly_statement(bundle["statement"]["id"],
                                                               MANAGER))
        assert statement["total_excess_loss_bbl"] == 180
        assert statement["excess_loss_amount"] == pytest.approx(1800.00, abs=0.01)

    def test_breach_of_loss_cap_suspends_lease(self, api):
        """PRD §3.7: "And if the recomputed statement's `total_excess_loss_bbl`
        exceeds the terminal's loss-control cap of 100 barrels, the lease
        automatically transitions from `ACTIVE` to `SUSPENDED` with
        `suspension_reason` set to `LOSS_CONTROL`."

        Design: Difficulty/transitive_cascade/certify_triggers_statement_rollup_and_loss_suspension
        """
        bundle = self._cascade_scenario()
        certify_transfer(bundle["custody"]["id"], certifier_id="tm-1")
        lease = get_lease(bundle["lease"]["id"])
        assert lease["status"] == "SUSPENDED", "180 > 100 cap must auto-suspend"
        assert lease["suspension_reason"] == "LOSS_CONTROL"
