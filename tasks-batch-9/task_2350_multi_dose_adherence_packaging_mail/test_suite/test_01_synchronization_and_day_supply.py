"""Alignment policy and the day-supply allowance fold.

Two patients whose prescriptions and cycle windows are byte-identical part company
only on the alignment policy pinned at synchronization, and one cycle's four lines
each have their allowance decided by a different term of the same successive-minima
fold.
"""

from test_helpers import (
    assert_line_state,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    do_adjudicate,
    do_synchronize,
    line_by_prescription,
    metformin_payload,
    prescription_payload,
    read_cycle,
    read_lines,
    read_prescription,
    set_clock,
    setup_adjudicated_cycle,
)

CLOCK = "2026-08-10T00:00:00Z"

# A payer whose per-day rates and thresholds are all stated rather than defaulted,
# so every copay below is attributable to the plan on the row.
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

# The same payer, but with a deliberately tight funding ceiling of 34 days.
CASCADE_PLAN = dict(NORTHWIND_PLAN, payer_name="Cascade Health PBM",
                    bin_number="004336", max_day_supply_days=34)


def _metformin_two_slots(patient_id):
    """One generic tablet taken morning and bedtime, last dispensed 2026-07-25 for 28 days.

    On-hand supply therefore runs through 2026-08-22, seven days past a 2026-08-15
    cycle start.
    """
    return metformin_payload(
        patient_id,
        dose_times=["MORNING", "BEDTIME"],
        days_supply_written=30,
        refills_authorized=3,
        last_dispensed_date="2026-07-25",
        last_dispensed_days_supply=28,
    )


def _prior_fill_of_twenty_days(patient_id, **overrides):
    """A prescription last dispensed 2026-07-31 for 20 days, i.e. on hand through 2026-08-20."""
    return prescription_payload(
        patient_id,
        quantity_per_dose=1,
        refills_authorized=3,
        last_dispensed_date="2026-07-31",
        last_dispensed_days_supply=20,
        **overrides,
    )


def _plain_tablet_long_written(patient_id):
    """Atorvastatin: nothing flagged, 40 days written with 3 refills left."""
    return _prior_fill_of_twenty_days(
        patient_id,
        drug_name="Atorvastatin",
        ndc="00093-5058-98",
        strength="20mg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["BEDTIME"],
        days_supply_written=40,
    )


def _plain_capsule_short_written(patient_id):
    """Gabapentin: nothing flagged, but only 8 days written with 3 refills left."""
    return _prior_fill_of_twenty_days(
        patient_id,
        drug_name="Gabapentin",
        ndc="00093-1028-01",
        strength="300mg",
        form="CAPSULE",
        copay_tier="GENERIC",
        dose_times=["MORNING"],
        days_supply_written=8,
    )


def _controlled_tablet(patient_id):
    """Lorazepam: a scheduled controlled substance, 40 days written."""
    return _prior_fill_of_twenty_days(
        patient_id,
        drug_name="Lorazepam",
        ndc="00591-0240-01",
        strength="0.5mg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["EVENING"],
        days_supply_written=40,
        is_controlled=True,
    )


def _refrigerated_pen(patient_id):
    """Insulin glargine: refrigerated, 40 days written."""
    return _prior_fill_of_twenty_days(
        patient_id,
        drug_name="Insulin glargine",
        ndc="00088-2220-33",
        strength="100 units/mL",
        form="INJECTION_PEN",
        copay_tier="SPECIALTY",
        dose_times=["BEDTIME"],
        days_supply_written=40,
        refrigerated=True,
    )


class TestSyncModeDecidesTheLineDaySupply:
    """One prescription, one cycle window, two irreconcilable alignment policies."""

    def test_bridge_to_start_fills_the_whole_cycle_day_supply(self):
        """A bridged line fills the cycle's full day supply and prices 28 days at the generic rate.

        Begin by locating the date through which the patient is already covered: it is `last_dispensed_date` advanced by `last_dispensed_days_supply` days. The gap is the number of days by which the cycle start date falls after the covered-through date, or zero if it does not. Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle. `bridge_days_applied` is the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's `day_supply_days` plus the gap. The line's own window follows from that: `line_start_date` is the cycle's `cycle_start_date` moved **earlier** by `bridge_days_applied` days and is inclusive, and `line_end_date` is `line_start_date` advanced by `days_supply_filled` days and is exclusive. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`.

        Design: Difficulty/dual_variant_calc/sync_bridge_vs_trim_day_supply_on_cycle_line
        """
        scenario = setup_adjudicated_cycle(
            clock=CLOCK,
            plan_overrides=NORTHWIND_PLAN,
            prescriptions=[_metformin_two_slots],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )

        line = read_lines(scenario.cycle_id)[0]
        assert line["days_supply_filled"] == 28, line
        assert line["bridge_days_applied"] == 0, line
        assert line["trim_days_applied"] == 0, line
        assert line["line_start_date"] == "2026-08-15", line
        assert line["line_end_date"] == "2026-09-12", line
        assert line["copay_cents"] == 762, line

        assert read_cycle(scenario.cycle_id)["total_copay_cents"] == 762
        assert read_prescription(scenario.rx_id(0))["last_dispensed_days_supply"] == 28

    def test_trim_to_start_shortens_the_line_by_the_on_hand_overlap(self):
        """A trimmed line burns the seven on-hand days down first and prices only 21 days.

        Begin by locating the date through which the patient is already covered: it is `last_dispensed_date` advanced by `last_dispensed_days_supply` days. The overlap is the number of days by which the covered-through date falls after the cycle start date, or zero if it does not. Under `TRIM_TO_START`, the fill is **shortened** so the on-hand supply is burned down first and the next cycle lands exactly on the anchor day. `bridge_days_applied` is zero, `trim_days_applied` is the overlap, and `days_supply_filled` is the cycle's `day_supply_days` minus the overlap, floored at zero so it is never negative. Under `TRIM_TO_START` there are no bridge days, so `line_start_date` always equals `cycle_start_date`. The line's own window follows from that: `line_start_date` is the cycle's `cycle_start_date` moved **earlier** by `bridge_days_applied` days and is inclusive, and `line_end_date` is `line_start_date` advanced by `days_supply_filled` days and is exclusive. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`.

        Design: Difficulty/dual_variant_calc/sync_bridge_vs_trim_day_supply_on_cycle_line
        """
        scenario = setup_adjudicated_cycle(
            clock=CLOCK,
            plan_overrides=NORTHWIND_PLAN,
            prescriptions=[_metformin_two_slots],
            anchor_fill_day=15,
            sync_mode="TRIM_TO_START",
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )

        line = read_lines(scenario.cycle_id)[0]
        assert line["days_supply_filled"] == 21, line
        assert line["trim_days_applied"] == 7, line
        assert line["bridge_days_applied"] == 0, line
        assert line["line_start_date"] == "2026-08-15", line
        assert line["line_end_date"] == "2026-09-05", line
        assert line["copay_cents"] == 571, line

        assert read_cycle(scenario.cycle_id)["total_copay_cents"] == 571
        assert read_prescription(scenario.rx_id(0))["last_dispensed_days_supply"] == 21

    def test_identical_regimens_diverge_by_seven_days_and_191_cents(self):
        """Two patients identical but for their pinned policy differ by exactly 7 days of supply.

        A patient is pinned to exactly one of two irreconcilable policies, and the policy is never re-chosen at cycle creation: Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle. `bridge_days_applied` is the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's `day_supply_days` plus the gap. Under `TRIM_TO_START`, the fill is **shortened** so the on-hand supply is burned down first and the next cycle lands exactly on the anchor day. `bridge_days_applied` is zero, `trim_days_applied` is the overlap, and `days_supply_filled` is the cycle's `day_supply_days` minus the overlap, floored at zero so it is never negative. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`.

        Design: Difficulty/dual_variant_calc/sync_bridge_vs_trim_day_supply_on_cycle_line
        """
        set_clock(CLOCK)
        plan = create_plan(**NORTHWIND_PLAN)
        patient_a = create_patient(plan["id"], which=1)
        patient_b = create_patient(plan["id"], which=2)
        rx_a = create_rx(patient_a["id"], _metformin_two_slots)
        rx_b = create_rx(patient_b["id"], _metformin_two_slots)
        do_synchronize(patient_a["id"], 15, "BRIDGE_TO_START")
        do_synchronize(patient_b["id"], 15, "TRIM_TO_START")
        cycle_a = create_cycle(patient_a["id"], "2026-08-15", 28)
        cycle_b = create_cycle(patient_b["id"], "2026-08-15", 28)
        do_adjudicate(cycle_a["id"])

        do_adjudicate(cycle_b["id"])

        line_a = read_lines(cycle_a["id"])[0]
        line_b = read_lines(cycle_b["id"])[0]
        assert line_a["days_supply_filled"] == 28, line_a
        assert line_b["days_supply_filled"] == 21, line_b
        assert line_a["days_supply_filled"] - line_b["days_supply_filled"] == 7
        assert line_a["copay_cents"] == 762, line_a
        assert line_b["copay_cents"] == 571, line_b
        assert line_a["copay_cents"] - line_b["copay_cents"] == 191

        assert read_cycle(cycle_a["id"])["total_copay_cents"] == 762
        assert read_cycle(cycle_b["id"])["total_copay_cents"] == 571
        assert read_prescription(rx_a["id"])["last_dispensed_days_supply"] == 28
        assert read_prescription(rx_b["id"])["last_dispensed_days_supply"] == 21


class TestDaySupplyAllowanceFourWayMinChain:
    """Four lines of one cycle, each capped by a different term of the same fold."""

    def _adjudicated_four_way_cycle(self):
        """One TRIM_TO_START cycle of 35 days over the four flag-contrasting prescriptions."""
        return setup_adjudicated_cycle(
            clock=CLOCK,
            plan_overrides=CASCADE_PLAN,
            prescriptions=[
                _plain_tablet_long_written,
                _plain_capsule_short_written,
                _controlled_tablet,
                _refrigerated_pen,
            ],
            anchor_fill_day=15,
            sync_mode="TRIM_TO_START",
            cycle_start_date="2026-08-15",
            day_supply_days=35,
        )

    def test_payer_ceiling_and_remaining_written_supply_cap_their_own_lines(self):
        """The 34-day payer ceiling caps one line while 8 x 4 written days caps another.

        For each line the system computes `allowance_days`, the maximum number of days the plan will fund on that line, by folding four independent ceilings together with successive minima. Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`. Then, if the prescription has `is_controlled` true, take the smaller of that result and 30. Then, if the prescription has `refrigerated` true, take the smaller of that result and 30. The final value is `allowance_days`.

        Design: Difficulty/combinatorial_formula/day_supply_allowance_four_way_min_chain
        """
        scenario = self._adjudicated_four_way_cycle()

        lines = read_lines(scenario.cycle_id)
        line_a = line_by_prescription(lines, scenario.rx_named("Atorvastatin")["id"])
        line_b = line_by_prescription(lines, scenario.rx_named("Gabapentin")["id"])

        # min(34 payer, 40 x 4 written, 35 window) -> the payer ceiling.
        assert line_a["allowance_days"] == 34, line_a
        # min(34 payer, 8 x 4 written, 35 window) -> the prescriber's remaining supply.
        assert line_b["allowance_days"] == 32, line_b

    def test_controlled_and_refrigerated_flags_cap_their_lines_at_thirty(self):
        """The controlled and cold-chain flags each pull an otherwise 34-day allowance down to 30.

        For each line the system computes `allowance_days`, the maximum number of days the plan will fund on that line, by folding four independent ceilings together with successive minima. Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`. Then, if the prescription has `is_controlled` true, take the smaller of that result and 30. Then, if the prescription has `refrigerated` true, take the smaller of that result and 30. The final value is `allowance_days`. Each line's `packable_route` is determined by the prescription: `COLD_CHAIN` when `refrigerated` is true, `POUCH` when `refrigerated` is false and `packable` is true, and `LOOSE_SPLIT` otherwise — that is, a non-refrigerated item whose `form` is not `TABLET` or `CAPSULE`.

        Design: Difficulty/combinatorial_formula/day_supply_allowance_four_way_min_chain
        """
        scenario = self._adjudicated_four_way_cycle()

        lines = read_lines(scenario.cycle_id)
        line_c = line_by_prescription(lines, scenario.rx_named("Lorazepam")["id"])
        line_d = line_by_prescription(lines, scenario.rx_named("Insulin glargine")["id"])

        # min(min(34, 160, 35), 30) -> the controlled-substance cap.
        assert line_c["allowance_days"] == 30, line_c
        # min(min(34, 160, 35), 30) -> the cold-chain cap.
        assert line_d["allowance_days"] == 30, line_d
        assert_line_state(line_c, packable_route="POUCH")
        assert_line_state(line_d, packable_route="COLD_CHAIN")

    def test_thirty_filled_days_clear_every_allowance_and_price_all_four_lines(self):
        """Thirty filled days sit inside all four allowances, so the cycle clears at 3504 cents.

        A fill cycle covers `cycle_start_date` inclusive through `cycle_end_date` exclusive, where `cycle_end_date` is `cycle_start_date` advanced by `day_supply_days` calendar days. Under `TRIM_TO_START`, the fill is **shortened** so the on-hand supply is burned down first and the next cycle lands exactly on the anchor day. `bridge_days_applied` is zero, `trim_days_applied` is the overlap, and `days_supply_filled` is the cycle's `day_supply_days` minus the overlap, floored at zero so it is never negative. Lastly, once every line's figures have been computed, no line may have `days_supply_filled` greater than its `allowance_days`, otherwise `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE`; this check is evaluated across all lines before any line's state or any prescription is committed, so a single over-supplied line aborts the entire adjudication with nothing written. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`.

        Design: Difficulty/combinatorial_formula/day_supply_allowance_four_way_min_chain
        """
        scenario = self._adjudicated_four_way_cycle()

        cycle = read_cycle(scenario.cycle_id)
        assert cycle["cycle_end_date"] == "2026-09-19", cycle
        assert cycle["insurance_status"] == "CLEARED", cycle
        # 816 + 816 + 816 + 1056, each line rounded before the sum.
        assert cycle["total_copay_cents"] == 3504, cycle

        lines = read_lines(scenario.cycle_id)
        assert len(lines) == 4, lines
        for line in lines:
            assert_line_state(line, line_status="ADJUDICATED")
            assert line["days_supply_filled"] == 30, line
            assert line["trim_days_applied"] == 5, line
