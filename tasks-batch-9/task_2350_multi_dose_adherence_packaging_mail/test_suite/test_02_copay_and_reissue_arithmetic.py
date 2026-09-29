"""Cycle copay arithmetic and the money a partial reissue moves.

The same four-prescription cycle is priced twice — once per line at adjudication and
once as a single sum at the dispatch that completes the cycle — and is then split by a
mid-cycle reissue whose fee tier is read off the value the cycle retains.
"""

from test_helpers import (
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_memo,
    assert_patient_posture,
    assert_shipment_state,
    assert_total_count,
    cold_chain_shipment_payload,
    do_dispatch,
    do_regimen_change,
    do_reissue,
    do_stage_shipment,
    insulin_payload,
    line_by_prescription,
    memo_by_reason,
    metformin_payload,
    ops_headers,
    pouch_roll_shipment_payload,
    read_cycle,
    read_lines,
    read_memos,
    read_patient,
    read_prescription,
    rivaroxaban_payload,
    setup_adjudicated_cycle,
    setup_rolled_cycle,
    setup_verified_cycle,
    sitagliptin_payload,
)

CLOCK = "2026-08-10T00:00:00Z"

# Three per-day rates, a 20 percent withhold and a 75 percent refill threshold, all
# stated rather than defaulted so every cent below is attributable to this plan.
NORTHWIND_PLAN = {
    "payer_name": "Northwind PBM",
    "bin_number": "610502",
    "generic_copay_cents_per_day": 34,
    "brand_copay_cents_per_day": 74,
    "specialty_copay_cents_per_day": 44,
    "refill_too_soon_threshold_pct": 75,
    "max_day_supply_days": 90,
    "vacation_overrides_per_year": 1,
    "coinsurance_pct": 20,
    "allows_payer_vacation_override": True,
}


def _metformin_two_slots(patient_id):
    """The generic tablet taken morning and bedtime, last dispensed 2026-07-25 for 28 days."""
    return metformin_payload(patient_id, dose_times=["MORNING", "BEDTIME"])


def _canonical_four(insulin_days_supply_written=None):
    """One prescription per tier plus a refrigerated pen, all clearing the refill edit.

    Prior fills are staggered so that the four lines report 75, 86, 93 and 100 percent
    of the previous day supply consumed at the 2026-08-15 cycle start, and every line
    fills the whole 28 days.
    """
    def pen(patient_id):
        if insulin_days_supply_written is None:
            return insulin_payload(patient_id)
        return insulin_payload(
            patient_id, days_supply_written=insulin_days_supply_written
        )

    return [_metformin_two_slots, rivaroxaban_payload, sitagliptin_payload, pen]


def _canonical_kwargs(**extra):
    """The shared recipe: this plan, these four prescriptions, a bridged 28-day cycle."""
    kwargs = dict(
        clock=CLOCK,
        plan_overrides=NORTHWIND_PLAN,
        prescriptions=_canonical_four(),
        anchor_fill_day=15,
        sync_mode="BRIDGE_TO_START",
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    kwargs.update(extra)
    return kwargs


class TestCycleCopayTierRateCoinsuranceAndFinalRounding:
    """The provisional per-line rounding and the single final rounding at dispatch."""

    def test_provisional_total_rounds_each_line_before_summing(self):
        """Four tier-selected products rounded per line sum to a provisional 4392 cents.

        The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. This round-each-line-then-sum discipline is the *provisional* figure; it is deliberately distinct from the final figure computed at dispatch, and the difference between them is later refunded.

        Design: Difficulty/combinatorial_formula/cycle_copay_tier_rate_coinsurance_and_final_rounding
        """
        scenario = setup_adjudicated_cycle(**_canonical_kwargs())

        lines = read_lines(scenario.cycle_id)
        metformin = line_by_prescription(lines, scenario.rx_named("Metformin ER")["id"])
        rivaroxaban = line_by_prescription(lines, scenario.rx_named("Rivaroxaban")["id"])
        sitagliptin = line_by_prescription(lines, scenario.rx_named("Sitagliptin")["id"])
        insulin = line_by_prescription(lines, scenario.rx_named("Insulin glargine")["id"])

        for line in (metformin, rivaroxaban, sitagliptin, insulin):
            assert line["days_supply_filled"] == 28, line

        assert metformin["copay_cents"] == 762, metformin
        assert rivaroxaban["copay_cents"] == 1658, rivaroxaban
        assert sitagliptin["copay_cents"] == 986, sitagliptin
        assert insulin["copay_cents"] == 986, insulin

        cycle = read_cycle(scenario.cycle_id)
        assert cycle["total_copay_cents"] == 4392, cycle
        assert cycle["final_copay_cents"] is None, cycle
        assert cycle["rounding_delta_cents"] is None, cycle

    def test_completing_dispatch_rounds_the_sum_once_and_refunds_the_delta(self):
        """The dispatch that leaves no required kind unshipped finalises 4390 and refunds 2 cents.

        When, after this dispatch, every required kind has a shipment whose `status` is `IN_TRANSIT`, `DELIVERED` or `PICKED_UP`, the cycle's `packaging_status` moves from `VERIFIED` to `SHIPPED` and the copay is finalised: `final_copay_cents` is computed by summing the **unrounded** per-line amounts over the lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT` — each amount being the tier's per-day rate multiplied by the line's `days_supply_filled`, multiplied by one hundred minus `coinsurance_pct`, divided by one hundred — and rounding that single sum half-up to whole cents. This sum-then-round-once discipline is what distinguishes the final figure from the provisional `total_copay_cents`, which rounded each line first. `rounding_delta_cents` is `total_copay_cents` minus `final_copay_cents`. When `rounding_delta_cents` is at least 1 cent, a credit memo is issued with `reason` `ROUNDING_TRUEUP`, `amount_cents` equal to `rounding_delta_cents` and `status` `ISSUED`, and the patient's `credit_balance_cents` rises by that amount.

        Design: Difficulty/combinatorial_formula/cycle_copay_tier_rate_coinsurance_and_final_rounding
        """
        scenario = setup_verified_cycle(**_canonical_kwargs(image_confidence_pct=96))
        pouch_parcel = do_stage_shipment(scenario.cycle_id, pouch_roll_shipment_payload())
        cold_parcel = do_stage_shipment(scenario.cycle_id, cold_chain_shipment_payload())
        do_dispatch(pouch_parcel["id"])

        do_dispatch(cold_parcel["id"])

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(cycle, packaging_status="SHIPPED")
        assert cycle["total_copay_cents"] == 4392, cycle
        # round_half_up(761.6 + 1657.6 + 985.6 + 985.6) over the unrounded amounts.
        assert cycle["final_copay_cents"] == 4390, cycle
        assert cycle["rounding_delta_cents"] == 2, cycle

        memos = read_memos(scenario.patient_id)
        trueup = memo_by_reason(memos, "ROUNDING_TRUEUP")
        assert_memo(
            trueup,
            reason="ROUNDING_TRUEUP",
            amount_cents=2,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
        )
        assert_total_count(
            api_client.list_credit_memos(ops_headers(), {"cycle_id": scenario.cycle_id}), 1
        )
        assert_patient_posture(read_patient(scenario.patient_id), credit_balance_cents=2)

    def test_dispatch_that_leaves_a_required_kind_unshipped_finalises_nothing(self):
        """With the cold-chain parcel still staged, the pouch dispatch finalises no copay at all.

        A dispatch that does not complete the cycle changes only the shipment and leaves the cycle at `VERIFIED` with `final_copay_cents` and `rounding_delta_cents` still null. The cycle's required kinds are derived from its lines whose `line_status` is `ADJUDICATED`: `POUCH_ROLL` is required if any such line has `packable_route` `POUCH`, `COLD_CHAIN` if any has `COLD_CHAIN`, and `NON_PACKABLE_LOOSE` if any has `LOOSE_SPLIT`.

        Design: Difficulty/combinatorial_formula/cycle_copay_tier_rate_coinsurance_and_final_rounding
        """
        scenario = setup_verified_cycle(**_canonical_kwargs(image_confidence_pct=96))
        pouch_parcel = do_stage_shipment(scenario.cycle_id, pouch_roll_shipment_payload())
        do_stage_shipment(scenario.cycle_id, cold_chain_shipment_payload())

        dispatched = do_dispatch(pouch_parcel["id"])

        assert_shipment_state(dispatched, status="IN_TRANSIT")
        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(cycle, packaging_status="VERIFIED")
        assert cycle["final_copay_cents"] is None, cycle
        assert cycle["rounding_delta_cents"] is None, cycle


class TestPartialReissueFeeTierReadOffRetainedBasis:
    """The fee tier is selected by the retained basis, which the credit itself reduces."""

    def _rolled_canonical_cycle(self):
        """The canonical four-line cycle adjudicated and rolled, so reissue is permitted."""
        return setup_rolled_cycle(**_canonical_kwargs())

    def test_fee_tier_follows_the_retained_basis_not_the_original_total(self):
        """A gross credit of 2190 leaves 2202 retained, which takes the 250-cent reduced fee.

        The consumed portion of the cycle is `used_days`, the number of days from the cycle's `cycle_start_date` to `effective_date`. For each line being reissued, its unused portion is that line's `days_supply_filled` minus `used_days`. The line's credit is the line's `copay_cents` multiplied by its unused days, divided by its `days_supply_filled`, rounded half-up to whole cents. The gross credit is the sum of those per-line credits over the lines being reissued — the lines whose `line_status` is `SUPERSEDED_PENDING_REISSUE`, together with the `ADJUDICATED` lines whose prescription is named in `replacement_prescription_ids`. Subtract the gross credit from the cycle's `total_copay_cents`. The result is the value the cycle retains, and it is this number, not `total_copay_cents`, that selects the fee tier. If the retained basis is at least 5000 cents, `reissue_fee_cents` is 0 — the fee is waived on a large retained cycle. Otherwise, if the retained basis is at least 2000 cents, `reissue_fee_cents` is 250. Otherwise `reissue_fee_cents` is 500. The credit memo's `amount_cents` is the gross credit minus `reissue_fee_cents`, floored at zero so it is never negative. `reissue_fee_cents` is stamped on the **original** cycle, and the memo is issued with `reason` `PARTIAL_REISSUE`, `cycle_id` naming the original cycle, `status` `ISSUED` and `issued_at` at the clock; the patient's `credit_balance_cents` rises by `amount_cents`.

        Design: Difficulty/combinatorial_formula/partial_reissue_fee_tier_read_off_retained_basis
        """
        scenario = self._rolled_canonical_cycle()
        before = read_cycle(scenario.cycle_id)
        assert before["total_copay_cents"] == 4392, before
        pouch_routed = [
            scenario.rx_named("Metformin ER")["id"],
            scenario.rx_named("Rivaroxaban")["id"],
            scenario.rx_named("Sitagliptin")["id"],
        ]

        do_reissue(scenario.cycle_id, "2026-08-25", pouch_routed, before["version"])

        original = read_cycle(scenario.cycle_id)
        # 4392 - (490 + 1066 + 634) == 2202, recomputed over 272 + 592 + 352 + 986.
        assert original["total_copay_cents"] == 2202, original
        # 2202 is at least 2000 and below 5000.
        assert original["reissue_fee_cents"] == 250, original

        memos = read_memos(scenario.patient_id)
        assert len(memos) == 1, memos
        assert_memo(
            memos[0],
            reason="PARTIAL_REISSUE",
            amount_cents=1940,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=1940
        )

    def test_reissued_line_and_its_prescription_keep_only_the_consumed_ten_days(self):
        """The brand line is trimmed to 592 cents over 10 days ending on the effective date.

        Each reissued line becomes `REISSUED`, retains only the consumed portion — its `copay_cents` reduced by its own line credit, its `days_supply_filled` set to `used_days`, and its `line_end_date` set to `effective_date` — and the original cycle's `total_copay_cents` is recomputed over the lines it retains. Each reissued line's prescription is adjusted to reflect what was actually consumed rather than what was dispensed: `last_dispensed_days_supply` is reset to `used_days` and `days_dispensed_total` is reduced by that line's unused days, so the successor cycle's refill-too-soon and day-supply edits measure against real consumption.

        Design: Difficulty/combinatorial_formula/partial_reissue_fee_tier_read_off_retained_basis
        """
        scenario = self._rolled_canonical_cycle()
        before = read_cycle(scenario.cycle_id)
        metformin_id = scenario.rx_named("Metformin ER")["id"]
        rivaroxaban_id = scenario.rx_named("Rivaroxaban")["id"]
        sitagliptin_id = scenario.rx_named("Sitagliptin")["id"]

        do_reissue(
            scenario.cycle_id,
            "2026-08-25",
            [metformin_id, rivaroxaban_id, sitagliptin_id],
            before["version"],
        )

        line = line_by_prescription(read_lines(scenario.cycle_id), rivaroxaban_id)
        assert_line_state(line, line_status="REISSUED")
        assert line["copay_cents"] == 592, line
        assert line["days_supply_filled"] == 10, line
        assert line["line_end_date"] == "2026-08-25", line

        metformin = read_prescription(metformin_id)
        assert metformin["last_dispensed_days_supply"] == 10, metformin
        assert metformin["days_dispensed_total"] == 10, metformin

    def test_successor_cycle_covers_the_eighteen_untaken_days(self):
        """The reissue returns a DRAFT child cycle of 18 days holding three planned lines.

        A new fill cycle is created with `is_partial_reissue` true, `reissue_of_cycle_id` naming the original cycle, `cycle_start_date` equal to `effective_date`, `day_supply_days` equal to the number of days from `effective_date` to the original cycle's `cycle_end_date`, `packaging_status` `DRAFT`, `insurance_status` `NOT_ADJUDICATED`, and one `PLANNED` cycle line per prescription named in `replacement_prescription_ids`. **The response body is the new partial-reissue fill cycle, not the original.**

        Design: Difficulty/combinatorial_formula/partial_reissue_fee_tier_read_off_retained_basis
        """
        scenario = self._rolled_canonical_cycle()
        before = read_cycle(scenario.cycle_id)
        pouch_routed = [
            scenario.rx_named("Metformin ER")["id"],
            scenario.rx_named("Rivaroxaban")["id"],
            scenario.rx_named("Sitagliptin")["id"],
        ]

        child = do_reissue(scenario.cycle_id, "2026-08-25", pouch_routed, before["version"])

        assert child["id"] != scenario.cycle_id, child
        assert child["is_partial_reissue"] is True, child
        assert child["reissue_of_cycle_id"] == scenario.cycle_id, child
        assert child["cycle_start_date"] == "2026-08-25", child
        assert child["day_supply_days"] == 18, child
        assert_cycle_state(
            child, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )

        child_lines = read_lines(child["id"])
        assert len(child_lines) == 3, child_lines
        for line in child_lines:
            assert_line_state(line, line_status="PLANNED")


class TestPartialReissueConservesEveryBilledCent:
    """Retained plus net credit plus fee must reproduce the originally billed total."""

    def _reissue_after_regimen_change(self):
        """Roll the canonical cycle, supersede its specialty tablet, then reissue the tail.

        Returns the scenario, the copays the four lines carried before the reissue, the
        original cycle total and the identifier of the reissued specialty line's
        prescription.
        """
        scenario = setup_rolled_cycle(
            **_canonical_kwargs(prescriptions=_canonical_four(30))
        )
        original_total = read_cycle(scenario.cycle_id)["total_copay_cents"]
        copays_before = {
            line["prescription_id"]: line["copay_cents"]
            for line in read_lines(scenario.cycle_id)
        }
        superseded = read_prescription(scenario.rx_named("Sitagliptin")["id"])
        successor = do_regimen_change(
            superseded["id"],
            superseded["version"],
            new_drug_name="Empagliflozin",
            new_form="TABLET",
            new_copay_tier="SPECIALTY",
            new_dose_times=["EVENING"],
            new_quantity_per_dose=1,
            change_reason="eGFR decline",
        )
        cycle = read_cycle(scenario.cycle_id)
        child = do_reissue(
            scenario.cycle_id,
            "2026-08-25",
            [
                scenario.rx_named("Metformin ER")["id"],
                scenario.rx_named("Rivaroxaban")["id"],
                successor["id"],
            ],
            cycle["version"],
        )
        return scenario, copays_before, original_total, superseded["id"], child

    def test_retained_plus_net_credit_plus_fee_equals_the_original_total(self):
        """2202 retained, 1940 credited and 250 kept as the fee reproduce the billed 4392.

        The credit is computed in exactly four ordered steps, and the order matters because the fee tier is read off the value the cycle *retains*, which the credit itself reduces. Subtract the gross credit from the cycle's `total_copay_cents`. The result is the value the cycle retains, and it is this number, not `total_copay_cents`, that selects the fee tier. Otherwise, if the retained basis is at least 2000 cents, `reissue_fee_cents` is 250. The credit memo's `amount_cents` is the gross credit minus `reissue_fee_cents`, floored at zero so it is never negative. Money is conserved: the original `total_copay_cents` equals the retained basis plus the net credit plus the fee.

        Design: Difficulty/compensating_invariant/partial_reissue_conserves_every_billed_cent
        """
        scenario, _, original_total, _, _ = self._reissue_after_regimen_change()

        assert original_total == 4392

        after = read_cycle(scenario.cycle_id)
        assert after["total_copay_cents"] == 2202, after
        assert after["reissue_fee_cents"] == 250, after

        memo = memo_by_reason(read_memos(scenario.patient_id), "PARTIAL_REISSUE")
        assert memo["amount_cents"] == 1940, memo

        assert (
            after["total_copay_cents"] + memo["amount_cents"] + after["reissue_fee_cents"]
            == original_total
        )

    def test_each_reissued_line_conserves_its_own_copay(self):
        """Every reissued line's retained cents plus its own line credit reproduce its original copay.

        For each line being reissued, its unused portion is that line's `days_supply_filled` minus `used_days`. The line's credit is the line's `copay_cents` multiplied by its unused days, divided by its `days_supply_filled`, rounded half-up to whole cents. Each reissued line becomes `REISSUED`, retains only the consumed portion — its `copay_cents` reduced by its own line credit, its `days_supply_filled` set to `used_days`, and its `line_end_date` set to `effective_date` — and the original cycle's `total_copay_cents` is recomputed over the lines it retains.

        Design: Difficulty/compensating_invariant/partial_reissue_conserves_every_billed_cent
        """
        scenario, copays_before, _, superseded_id, _ = self._reissue_after_regimen_change()

        lines = read_lines(scenario.cycle_id)
        metformin = line_by_prescription(lines, scenario.rx_named("Metformin ER")["id"])
        rivaroxaban = line_by_prescription(lines, scenario.rx_named("Rivaroxaban")["id"])
        specialty = line_by_prescription(lines, superseded_id)
        untouched = line_by_prescription(
            lines, scenario.rx_named("Insulin glargine")["id"]
        )

        # retained cents, line credit  ->  272 + 490, 592 + 1066, 352 + 634
        expected = ((metformin, 272, 490), (rivaroxaban, 592, 1066), (specialty, 352, 634))
        for line, retained, credit in expected:
            assert_line_state(line, line_status="REISSUED")
            assert line["copay_cents"] == retained, line
            assert line["days_supply_filled"] == 10, line
            assert line["line_end_date"] == "2026-08-25", line
            assert retained + credit == copays_before[line["prescription_id"]], line

        # The pen was never named as a replacement, so its 986 cents are untouched.
        assert_line_state(untouched, line_status="ADJUDICATED")
        assert untouched["copay_cents"] == 986, untouched
        assert untouched["days_supply_filled"] == 28, untouched

    def test_the_gross_credit_reappears_in_exactly_one_memo_and_the_balance(self):
        """The 2190 gross credit surfaces once, as a single 1940-cent memo plus the 250-cent fee.

        `reissue_fee_cents` is stamped on the **original** cycle, and the memo is issued with `reason` `PARTIAL_REISSUE`, `cycle_id` naming the original cycle, `status` `ISSUED` and `issued_at` at the clock; the patient's `credit_balance_cents` rises by `amount_cents`. The patient's `credit_balance_cents` is always the sum of `amount_cents` over that patient's memos whose `status` is `ISSUED`; issuing a memo raises it by the memo's `amount_cents`. A new fill cycle is created with `is_partial_reissue` true, `reissue_of_cycle_id` naming the original cycle, `cycle_start_date` equal to `effective_date`, `day_supply_days` equal to the number of days from `effective_date` to the original cycle's `cycle_end_date`, `packaging_status` `DRAFT`, `insurance_status` `NOT_ADJUDICATED`, and one `PLANNED` cycle line per prescription named in `replacement_prescription_ids`.

        Design: Difficulty/compensating_invariant/partial_reissue_conserves_every_billed_cent
        """
        scenario, _, _, _, child = self._reissue_after_regimen_change()

        memos = read_memos(scenario.patient_id)
        assert len(memos) == 1, memos
        assert_memo(
            memos[0],
            reason="PARTIAL_REISSUE",
            amount_cents=1940,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=1940
        )

        assert child["is_partial_reissue"] is True, child
        assert child["cycle_start_date"] == "2026-08-25", child
        assert child["day_supply_days"] == 18, child
        assert_cycle_state(
            child, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )
        assert len(read_lines(child["id"])) == 3
