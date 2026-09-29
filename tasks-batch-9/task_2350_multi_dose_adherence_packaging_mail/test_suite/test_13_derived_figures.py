"""Derived figures of the mail-pharmacy API.

Freight priced from three independent additive components, the pouch roll's
date-by-slot geometry, the input set that feeds the provisional cycle copay, the
per-plan refill-too-soon threshold, half-up rounding at an exact half cent, the
alignment policy selected per cycle, and the half-open rolling adherence window.
"""

from test_helpers import (
    TECHNICIAN_ID,
    albuterol_payload,
    api_client,
    assert_adherence_event_shape,
    assert_cycle_state,
    assert_line_state,
    assert_patient_posture,
    assert_roll_state,
    assert_shipment_state,
    assert_total_count,
    create_cycle,
    do_adjudicate,
    do_dose_events,
    do_generate_roll,
    do_stage_shipment,
    dose_event,
    insulin_payload,
    line_by_prescription,
    metformin_payload,
    ops_headers,
    pouch_by_index,
    read_cycle,
    read_lines,
    read_patient,
    read_pouches,
    read_prescription,
    rivaroxaban_payload,
    set_clock,
    setup_adjudicated_cycle,
    setup_synced_patient,
    shipment_payload,
    sitagliptin_payload,
)

CLOCK = "2026-08-10T00:00:00Z"


# ----------------------------------------------------------------------
# Prescription sets used by the recipes below.
# ----------------------------------------------------------------------
def _pouch_tablet(patient_id):
    """A pouchable generic morning tablet with a 28-day fill dispensed 2026-07-18."""
    return metformin_payload(
        patient_id, last_dispensed_date="2026-07-18", last_dispensed_days_supply=28
    )


def _cold_pen(patient_id):
    """A refrigerated specialty pen dosed at bedtime, which can never enter a pouch."""
    return insulin_payload(patient_id)


def _loose_inhaler(patient_id):
    """A non-refrigerated inhaler, which is not packable and therefore ships loose."""
    return albuterol_payload(
        patient_id, last_dispensed_date="2026-07-18", last_dispensed_days_supply=28
    )


def _three_route_cycle():
    """A clean cycle carrying one pouch, one cold-chain and one loose line."""
    return setup_adjudicated_cycle(
        clock=CLOCK,
        prescriptions=[_pouch_tablet, _cold_pen, _loose_inhaler],
        anchor_fill_day=15,
        sync_mode="BRIDGE_TO_START",
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )


def _morning_and_bedtime_tablet(patient_id):
    """The generic tablet dosed twice a day, at morning and at bedtime."""
    return metformin_payload(patient_id, dose_times=["MORNING", "BEDTIME"])


def _four_prescription_roll_cycle():
    """A clean cycle with three pouch lines spanning three slots plus a cold-chain line."""
    return setup_adjudicated_cycle(
        clock=CLOCK,
        prescriptions=[
            _morning_and_bedtime_tablet,
            rivaroxaban_payload,
            sitagliptin_payload,
            _cold_pen,
        ],
        anchor_fill_day=15,
        sync_mode="BRIDGE_TO_START",
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )


class TestSplitShipmentFreight:
    """Freight for the parcels of one cycle, priced off one additive table."""

    def test_cold_chain_parcel_sums_kind_packaging_and_service(self):
        """An overnight cold-chain parcel in gel packaging is priced at 3445 cents.

        `ship_cost_cents` is stamped at staging as the sum of three independent additive components. The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`. No rounding is involved; every component is already a whole number of cents.
        `covers_line_ids` holds the identifiers of the cycle's lines whose `packable_route` maps to this `shipment_kind` and whose `line_status` is `ADJUDICATED` or `PACKED_OUT`, ordered by ascending line `created_at`.

        Design: Corner/calculations/split_shipment_cost_sums_three_independent_tiers
        """
        scenario = _three_route_cycle()
        lines = read_lines(scenario.cycle_id)
        cold_line = line_by_prescription(lines, scenario.rx_named("Insulin glargine")["id"])
        pouch_line = line_by_prescription(lines, scenario.rx_named("Metformin ER")["id"])

        cold = do_stage_shipment(
            scenario.cycle_id,
            shipment_payload("COLD_CHAIN", "OVERNIGHT", "INSULATED_GEL"),
        )

        assert cold["ship_cost_cents"] == 3445, cold
        assert cold["covers_line_ids"] == [cold_line["id"]], cold
        assert pouch_line["id"] not in cold["covers_line_ids"], cold
        assert_shipment_state(cold, status="STAGED")
        assert cold["staged_at"].startswith("2026-08-10T00:00:00"), cold

    def test_loose_parcel_sums_a_different_row_of_the_same_table(self):
        """A two-day loose parcel in standard packaging is priced at 1095 cents.

        `ship_cost_cents` is stamped at staging as the sum of three independent additive components. The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`. No rounding is involved; every component is already a whole number of cents.
        `covers_line_ids` holds the identifiers of the cycle's lines whose `packable_route` maps to this `shipment_kind` and whose `line_status` is `ADJUDICATED` or `PACKED_OUT`, ordered by ascending line `created_at`.

        Design: Corner/calculations/split_shipment_cost_sums_three_independent_tiers
        """
        scenario = _three_route_cycle()
        lines = read_lines(scenario.cycle_id)
        loose_line = line_by_prescription(lines, scenario.rx_named("Albuterol HFA")["id"])
        pouch_line = line_by_prescription(lines, scenario.rx_named("Metformin ER")["id"])

        loose = do_stage_shipment(
            scenario.cycle_id,
            shipment_payload("NON_PACKABLE_LOOSE", "TWO_DAY", "STANDARD"),
        )

        assert loose["ship_cost_cents"] == 1095, loose
        assert loose["covers_line_ids"] == [loose_line["id"]], loose
        assert pouch_line["id"] not in loose["covers_line_ids"], loose
        assert_shipment_state(loose, status="STAGED")
        assert loose["staged_at"].startswith("2026-08-10T00:00:00"), loose

    def test_freight_never_enters_the_cycle_copay(self):
        """Staging two priced parcels leaves the cycle's adjudicated copay untouched.

        The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. This round-each-line-then-sum discipline is the *provisional* figure; it is deliberately distinct from the final figure computed at dispatch, and the difference between them is later refunded.

        Design: Corner/calculations/split_shipment_cost_sums_three_independent_tiers
        """
        scenario = _three_route_cycle()
        adjudicated_copay = scenario.cycle["total_copay_cents"]

        cold = do_stage_shipment(
            scenario.cycle_id,
            shipment_payload("COLD_CHAIN", "OVERNIGHT", "INSULATED_GEL"),
        )
        loose = do_stage_shipment(
            scenario.cycle_id,
            shipment_payload("NON_PACKABLE_LOOSE", "TWO_DAY", "STANDARD"),
        )

        assert cold["ship_cost_cents"] == 3445, cold
        assert loose["ship_cost_cents"] == 1095, loose
        reread = read_cycle(scenario.cycle_id)
        assert reread["total_copay_cents"] == adjudicated_copay, reread


class TestRollGeometry:
    """The pouch population of a roll is the cross product of dose dates and slots."""

    def test_pouch_count_is_the_pouch_slot_universe_times_the_dose_dates(self):
        """Three pouch-routed slots over 28 dose dates build 84 pouches on one segment.

        The contributing lines are exactly those of the cycle whose `line_status` is `ADJUDICATED` and whose `packable_route` is `POUCH`. Cold-chain and non-packable lines never contribute a pouch — they ship loose — so the roll's shape is a function of the pouch-routed subset alone. The set of slots the roll uses is the union of `dose_times` over the contributing lines' prescriptions. One pouch is produced for each distinct pairing of a calendar date with a slot such that at least one contributing line both covers that date, meaning the date is on or after that line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in its prescription's `dose_times`.
        The roll itself is created with `verification_status` `BUILT`, a stamped human-readable `roll_serial`, `segment_start_date` equal to the earliest `line_start_date` among contributing lines, and `segment_end_date` equal to the latest `line_end_date` among contributing lines moved back by one day — because `segment_end_date` is inclusive, it names the last date for which a pouch exists, whereas `line_end_date` is exclusive.

        Design: Corner/calculations/roll_geometry_counts_one_pouch_per_date_slot_pair
        """
        scenario = _four_prescription_roll_cycle()

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)

        assert roll["pouch_count"] == 84, roll
        assert roll["segment_start_date"] == "2026-08-15", roll
        assert roll["segment_end_date"] == "2026-09-11", roll
        assert_roll_state(roll, verification_status="BUILT")
        assert read_cycle(scenario.cycle_id)["roll_pouch_count"] == 84

    def test_pouch_indexes_run_by_date_then_slot_rank_and_sum_their_contents(self):
        """The first four pouches order by date then slot rank and sum their contents.

        Each pouch records its `roll_id`, its `dose_date`, its `dose_slot`, and a 1-based `pouch_index` assigned by ascending `dose_date` and, within a date, by slot in the order `MORNING`, then `NOON`, then `EVENING`, then `BEDTIME`. `contents` holds one object per contributing line covering that pairing, each carrying that line's `prescription_id` and a `quantity` equal to the prescription's `quantity_per_dose`; the objects are ordered by ascending prescription `created_at`. `expected_pill_count` is the sum of the `quantity` values across `contents` and is the count the verification image must match.

        Design: Corner/calculations/roll_geometry_counts_one_pouch_per_date_slot_pair
        """
        scenario = _four_prescription_roll_cycle()
        tablet_id = scenario.rx_named("Metformin ER")["id"]
        brand_id = scenario.rx_named("Rivaroxaban")["id"]
        specialty_id = scenario.rx_named("Sitagliptin")["id"]

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)

        pouches = read_pouches(roll["id"])
        first = pouch_by_index(pouches, 1)
        assert first["dose_date"] == "2026-08-15", first
        assert first["dose_slot"] == "MORNING", first
        assert first["expected_pill_count"] == 2, first
        assert [item["prescription_id"] for item in first["contents"]] == [
            tablet_id,
            brand_id,
        ], first

        second = pouch_by_index(pouches, 2)
        assert second["dose_date"] == "2026-08-15", second
        assert second["dose_slot"] == "EVENING", second
        assert second["expected_pill_count"] == 1, second
        assert [item["prescription_id"] for item in second["contents"]] == [
            specialty_id
        ], second

        third = pouch_by_index(pouches, 3)
        assert third["dose_date"] == "2026-08-15", third
        assert third["dose_slot"] == "BEDTIME", third
        assert third["expected_pill_count"] == 1, third
        assert [item["prescription_id"] for item in third["contents"]] == [
            tablet_id
        ], third

        fourth = pouch_by_index(pouches, 4)
        assert fourth["dose_date"] == "2026-08-16", fourth
        assert fourth["dose_slot"] == "MORNING", fourth

    def test_a_slot_no_pouch_line_uses_holds_no_pouch_at_all(self):
        """No pouch exists for the noon slot, and every built pouch is still pending.

        The set of slots the roll uses is the union of `dose_times` over the contributing lines' prescriptions. One pouch is produced for each distinct pairing of a calendar date with a slot such that at least one contributing line both covers that date, meaning the date is on or after that line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in its prescription's `dose_times`.
        Each pouch starts with `verification_result` `PENDING` and with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` all null.
        Every filter parameter is optional; when several are supplied they combine conjunctively, and an unrecognised filter value simply matches nothing rather than erroring (an enum-typed filter carrying a value outside its declared set is a schema violation).

        Design: Corner/calculations/roll_geometry_counts_one_pouch_per_date_slot_pair
        """
        scenario = _four_prescription_roll_cycle()

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)

        noon = api_client.list_pouches(
            ops_headers(), {"roll_id": roll["id"], "dose_slot": "NOON"}
        )
        assert_total_count(noon, 0)

        pouches = read_pouches(roll["id"])
        assert len(pouches) == 84, len(pouches)
        assert all(pouch["verification_result"] == "PENDING" for pouch in pouches)
        assert_roll_state(roll, verification_status="BUILT")


class TestCopayInputSet:
    """Only adjudicated lines feed the provisional cycle copay."""

    def test_a_held_line_contributes_nothing_to_the_cycle_copay(self):
        """The refill-held brand line is priced at zero and stays out of the cycle total.

        The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. This round-each-line-then-sum discipline is the *provisional* figure; it is deliberately distinct from the final figure computed at dispatch, and the difference between them is later refunded. Lines that are held, excluded, superseded or credited contribute nothing to `total_copay_cents`.
        A line that fails the edit becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON`.
        The packaging dimension moves from `DRAFT` to `LINES_ADJUDICATED`. The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`.
        A dispatch that does not complete the cycle changes only the shipment and leaves the cycle at `VERIFIED` with `final_copay_cents` and `rounding_delta_cents` still null.

        Design: Corner/calculations/copay_input_set_excludes_held_lines
        """
        scenario = setup_synced_patient(
            clock=CLOCK,
            prescriptions=[
                metformin_payload,
                lambda pid: rivaroxaban_payload(
                    pid,
                    last_dispensed_date="2026-08-04",
                    last_dispensed_days_supply=30,
                ),
            ],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
        )
        keep_id = scenario.rx_named("Metformin ER")["id"]
        hold_id = scenario.rx_named("Rivaroxaban")["id"]
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 28)

        adjudicated = do_adjudicate(cycle["id"])

        assert adjudicated["total_copay_cents"] == 762, adjudicated
        assert_cycle_state(
            adjudicated,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="REJECTED_TOO_SOON",
        )
        assert adjudicated["final_copay_cents"] is None, adjudicated

        lines = read_lines(cycle["id"])
        kept = line_by_prescription(lines, keep_id)
        assert_line_state(kept, line_status="ADJUDICATED", hold_reason=None)
        assert kept["refill_pct_used"] == 75, kept
        assert kept["copay_cents"] == 762, kept

        held = line_by_prescription(lines, hold_id)
        assert_line_state(
            held, line_status="HELD_TOO_SOON", hold_reason="REFILL_TOO_SOON"
        )
        assert held["refill_pct_used"] == 36, held
        # The held line's own `copay_cents` is deliberately not asserted: the PRD fixes
        # only that a held line contributes nothing to `total_copay_cents`, which the
        # 762 total above already pins.

    def test_a_held_line_is_never_dispensed(self):
        """The held prescription keeps its refills and its untouched dispense history.

        Every line that becomes `ADJUDICATED` writes the dispense onto its prescription, and the order of writes matters because the pre-dispense history must survive for a possible reversal. First the current history is preserved: `prior_last_dispensed_date` takes the current value of `last_dispensed_date` and `prior_last_dispensed_days_supply` takes the current value of `last_dispensed_days_supply`. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`. Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1.

        Design: Corner/calculations/copay_input_set_excludes_held_lines
        """
        scenario = setup_synced_patient(
            clock=CLOCK,
            prescriptions=[
                metformin_payload,
                lambda pid: rivaroxaban_payload(
                    pid,
                    last_dispensed_date="2026-08-04",
                    last_dispensed_days_supply=30,
                ),
            ],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
        )
        hold_id = scenario.rx_named("Rivaroxaban")["id"]
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 28)

        do_adjudicate(cycle["id"])

        held_rx = read_prescription(hold_id)
        assert held_rx["refills_remaining"] == 3, held_rx
        assert held_rx["last_dispensed_date"] == "2026-08-04", held_rx


class TestRefillThresholdIsPerPlan:
    """The refill-too-soon threshold is plan configuration, not a hard-coded constant."""

    def test_a_plan_configured_at_sixty_clears_a_seventy_one_percent_line(self):
        """A line at 71 percent clears against a plan whose threshold is set to 60.

        Otherwise, count the elapsed days from `last_dispensed_date` to the cycle's `cycle_start_date`, multiply by one hundred, divide by the prescription's `last_dispensed_days_supply`, and floor the result to a whole percent. The edit clears when `refill_pct_used` is greater than or equal to the plan's `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at the threshold clears — or when the cycle carries a travel exception whose `waives_refill_too_soon` is true.
        Four further fields are optional and take a default when omitted: `refill_too_soon_threshold_pct` defaults to 75 and must lie between 0 and 100; `max_day_supply_days` defaults to 90 and must lie between 1 and 365; `vacation_overrides_per_year` defaults to 1 and must lie between 0 and 12; `coinsurance_pct` defaults to 20 and must lie between 0 and 100.

        Design: Corner/calculations/refill_threshold_is_read_from_the_plan_not_hardcoded
        """
        scenario = setup_synced_patient(
            clock=CLOCK,
            plan_overrides={
                "payer_name": "Cascade Rx Trust",
                "bin_number": "004336",
                "refill_too_soon_threshold_pct": 60,
            },
            prescriptions=[
                lambda pid: metformin_payload(
                    pid,
                    last_dispensed_date="2026-07-26",
                    last_dispensed_days_supply=28,
                )
            ],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
        )
        assert scenario.plan["refill_too_soon_threshold_pct"] == 60, scenario.plan
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 28)

        adjudicated = do_adjudicate(cycle["id"])

        assert_cycle_state(adjudicated, insurance_status="CLEARED")
        assert adjudicated["total_copay_cents"] == 762, adjudicated
        line = line_by_prescription(read_lines(cycle["id"]), scenario.rx_id(0))
        assert line["refill_pct_used"] == 71, line
        assert_line_state(line, line_status="ADJUDICATED")
        assert line["days_supply_filled"] == 28, line

    def test_the_same_history_is_held_under_the_default_threshold(self):
        """The identical 71 percent history is held when the plan takes the 75 default.

        Otherwise, count the elapsed days from `last_dispensed_date` to the cycle's `cycle_start_date`, multiply by one hundred, divide by the prescription's `last_dispensed_days_supply`, and floor the result to a whole percent. The edit clears when `refill_pct_used` is greater than or equal to the plan's `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at the threshold clears — or when the cycle carries a travel exception whose `waives_refill_too_soon` is true. A line that fails the edit becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON`.
        Four further fields are optional and take a default when omitted: `refill_too_soon_threshold_pct` defaults to 75 and must lie between 0 and 100; `max_day_supply_days` defaults to 90 and must lie between 1 and 365; `vacation_overrides_per_year` defaults to 1 and must lie between 0 and 12; `coinsurance_pct` defaults to 20 and must lie between 0 and 100.

        Design: Corner/calculations/refill_threshold_is_read_from_the_plan_not_hardcoded
        """
        scenario = setup_synced_patient(
            clock=CLOCK,
            plan_overrides={"refill_too_soon_threshold_pct": None},
            prescriptions=[
                lambda pid: metformin_payload(
                    pid,
                    last_dispensed_date="2026-07-26",
                    last_dispensed_days_supply=28,
                )
            ],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
        )
        assert scenario.plan["refill_too_soon_threshold_pct"] == 75, scenario.plan
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 28)

        adjudicated = do_adjudicate(cycle["id"])

        assert_cycle_state(adjudicated, insurance_status="REJECTED_TOO_SOON")
        line = line_by_prescription(read_lines(cycle["id"]), scenario.rx_id(0))
        assert line["refill_pct_used"] == 71, line
        assert_line_state(
            line, line_status="HELD_TOO_SOON", hold_reason="REFILL_TOO_SOON"
        )


class TestHalfUpRoundingAtAnExactHalfCent:
    """Two lines land on an exact half cent, where the rounding disciplines diverge."""

    def _scenario(self):
        return setup_synced_patient(
            clock=CLOCK,
            plan_overrides={
                "generic_copay_cents_per_day": 33,
                "specialty_copay_cents_per_day": 45,
                "coinsurance_pct": 50,
            },
            prescriptions=[metformin_payload, sitagliptin_payload],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
        )

    def test_each_line_copay_rounds_half_up(self):
        """412.5 and 562.5 cents round up to 413 and 563, not down and not to even.

        The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`.
        **Half-up rounding to whole cents.** A non-negative amount whose fractional part is exactly one half rounds away from zero; anything below one half rounds down, anything above rounds up. This is the discipline used for a line's copay, for the cycle's final copay, and for each per-line credit in a partial reissue.
        Coinsurance is expressed as the percent the plan withholds, `coinsurance_pct`, so the patient's share factor is one hundred minus `coinsurance_pct`, divided by one hundred.

        Design: Corner/calculations/per_line_copay_rounds_half_up_at_exact_half_cents
        """
        scenario = self._scenario()
        generic_id = scenario.rx_named("Metformin ER")["id"]
        specialty_id = scenario.rx_named("Sitagliptin")["id"]
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 25)

        do_adjudicate(cycle["id"])

        lines = read_lines(cycle["id"])
        generic = line_by_prescription(lines, generic_id)
        specialty = line_by_prescription(lines, specialty_id)
        assert generic["copay_cents"] == 413, generic
        assert specialty["copay_cents"] == 563, specialty
        assert generic["refill_pct_used"] == 75, generic
        assert specialty["refill_pct_used"] == 93, specialty

    def test_the_provisional_total_sums_the_already_rounded_lines(self):
        """The cycle total is 976 cents, the sum of the two rounded line copays.

        The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. This round-each-line-then-sum discipline is the *provisional* figure; it is deliberately distinct from the final figure computed at dispatch, and the difference between them is later refunded.
        For each line the system computes `allowance_days`, the maximum number of days the plan will fund on that line, by folding four independent ceilings together with successive minima. Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`.

        Design: Corner/calculations/per_line_copay_rounds_half_up_at_exact_half_cents
        """
        scenario = self._scenario()
        cycle = create_cycle(scenario.patient_id, "2026-08-15", 25)

        adjudicated = do_adjudicate(cycle["id"])

        assert adjudicated["total_copay_cents"] == 976, adjudicated
        for line in read_lines(cycle["id"]):
            assert_line_state(line, line_status="ADJUDICATED")
            assert line["days_supply_filled"] == 25, line
            assert line["allowance_days"] == 25, line


class TestAlignmentVariantSelection:
    """The alignment policy is inherited from the patient and overridable per cycle."""

    def _scenario(self):
        return setup_synced_patient(
            clock=CLOCK,
            prescriptions=[metformin_payload],
            anchor_fill_day=15,
            sync_mode="TRIM_TO_START",
        )

    def test_a_cycle_omitting_sync_mode_inherits_the_patients_pinned_policy(self):
        """A cycle with no sync_mode in its body trims by the 7 overlap days it inherits.

        The caller supplies `patient_id` and `cycle_start_date`, and may optionally supply `day_supply_days` (default 28, valid from 1 through 90) and `sync_mode` to override the patient's pinned policy for this one cycle. When `sync_mode` is omitted the cycle copies the patient's `sync_mode`.
        Under `TRIM_TO_START`, the fill is **shortened** so the on-hand supply is burned down first and the next cycle lands exactly on the anchor day. `bridge_days_applied` is zero, `trim_days_applied` is the overlap, and `days_supply_filled` is the cycle's `day_supply_days` minus the overlap, floored at zero so it is never negative.

        Design: Corner/calculations/sync_variant_is_selected_by_the_pinned_mode_then_overridden_per_cycle
        """
        scenario = self._scenario()
        assert scenario.patient["sync_mode"] == "TRIM_TO_START", scenario.patient

        first = create_cycle(scenario.patient_id, "2026-08-15", 28)

        assert first["sync_mode"] == "TRIM_TO_START", first
        adjudicated = do_adjudicate(first["id"])
        assert adjudicated["total_copay_cents"] == 571, adjudicated
        line = line_by_prescription(read_lines(first["id"]), scenario.rx_id(0))
        assert line["trim_days_applied"] == 7, line
        assert line["bridge_days_applied"] == 0, line
        assert line["days_supply_filled"] == 21, line

    def test_a_per_cycle_override_does_not_repin_the_patient(self):
        """The second cycle bridges by its own body value while the patient stays trimmed.

        The caller supplies `patient_id` and `cycle_start_date`, and may optionally supply `day_supply_days` (default 28, valid from 1 through 90) and `sync_mode` to override the patient's pinned policy for this one cycle. When `sync_mode` is omitted the cycle copies the patient's `sync_mode`.
        Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle. `bridge_days_applied` is the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's `day_supply_days` plus the gap.
        Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`.

        Design: Corner/calculations/sync_variant_is_selected_by_the_pinned_mode_then_overridden_per_cycle
        """
        scenario = self._scenario()
        first = create_cycle(scenario.patient_id, "2026-08-15", 28)
        do_adjudicate(first["id"])

        second = create_cycle(
            scenario.patient_id, "2026-09-12", 28, sync_mode="BRIDGE_TO_START"
        )

        assert second["sync_mode"] == "BRIDGE_TO_START", second
        assert read_patient(scenario.patient_id)["sync_mode"] == "TRIM_TO_START"
        adjudicated = do_adjudicate(second["id"])
        assert adjudicated["total_copay_cents"] == 952, adjudicated
        line = line_by_prescription(read_lines(second["id"]), scenario.rx_id(0))
        assert line["bridge_days_applied"] == 7, line
        assert line["trim_days_applied"] == 0, line
        assert line["days_supply_filled"] == 35, line
        assert line["allowance_days"] == 35, line


class TestRollingAdherenceWindow:
    """The rolling score is a replay over a half-open 28-day window."""

    def _scenario(self):
        scenario = setup_synced_patient(
            clock="2026-07-10T00:00:00Z",
            prescriptions=[
                lambda pid: metformin_payload(
                    pid,
                    last_dispensed_date="2026-06-20",
                    last_dispensed_days_supply=28,
                )
            ],
            anchor_fill_day=18,
            sync_mode="BRIDGE_TO_START",
        )
        earlier = create_cycle(scenario.patient_id, "2026-07-18", 28)
        current = create_cycle(scenario.patient_id, "2026-08-15", 28)
        set_clock("2026-09-05T00:00:00Z")
        return scenario, earlier, current

    @staticmethod
    def _first_batch():
        return [
            dose_event("POUCH_TAKEN", "2026-08-15T08:00:00Z", "MORNING", 1),
            dose_event("POUCH_TAKEN", "2026-08-16T08:00:00Z", "MORNING", 2),
            dose_event("POUCH_TAKEN", "2026-08-17T08:00:00Z", "MORNING", 3),
            dose_event("POUCH_TAKEN", "2026-08-18T08:00:00Z", "MORNING", 4),
            dose_event("POUCH_TAKEN", "2026-08-19T08:00:00Z", "MORNING", 5),
            dose_event("POUCH_TAKEN", "2026-08-20T08:00:00Z", "MORNING", 6),
            dose_event("POUCH_TAKEN", "2026-08-21T08:00:00Z", "MORNING", 7),
            dose_event("POUCH_TAKEN", "2026-08-22T08:00:00Z", "MORNING", 8),
            dose_event("POUCH_MISSED", "2026-08-23T08:00:00Z", "MORNING", 9),
        ]

    @staticmethod
    def _late_batch():
        return [
            dose_event("POUCH_TAKEN", "2026-08-08T00:00:00Z", "MORNING", 22),
            dose_event("POUCH_MISSED", "2026-08-07T23:59:59Z", "MORNING", 21),
            dose_event("POUCH_MISSED", "2026-07-20T08:00:00Z", "MORNING", 3),
            dose_event("POUCH_MISSED", "2026-07-22T08:00:00Z", "MORNING", 5),
        ]

    def test_score_counts_the_events_inside_the_window(self):
        """Eight taken and one missed inside the window score 88 and leave auto-ship active.

        The window is half-open: it begins at the clock moved back by 28 days, inclusive, and ends at the clock, exclusive. The eligible events are those whose `cycle_id` belongs to a fill cycle of this patient, whose `event_type` is `POUCH_TAKEN` or `POUCH_MISSED`, and whose `occurred_at` falls inside that window; pickup and delivery events never enter the score. Count the taken events and the missed events. When the two counts sum to zero, `adherence_score_pct` is 100. Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent.
        One immutable adherence event is created per element, each carrying only `id` and `created_at` beyond its own payload; `source` is `PATIENT_REPORTED` when `X-User-Role` is `Patient` and `SYSTEM_SCAN` otherwise.
        If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`.

        Design: Corner/calculations/adherence_projection_ignores_events_outside_the_rolling_window
        """
        scenario, _earlier, current = self._scenario()

        created = do_dose_events(
            scenario.patient_id, current["id"], self._first_batch(), as_patient=True
        )

        assert len(created) == 9, created
        for event in created:
            assert_adherence_event_shape(event)
            assert event["source"] == "PATIENT_REPORTED", event
        assert_patient_posture(
            read_patient(scenario.patient_id),
            autoship_status="ACTIVE",
            adherence_score_pct=88,
        )

    def test_a_late_batch_of_older_events_is_replayed_from_scratch(self):
        """Three misses outside the window raise the score to 90 yet are still persisted.

        The window is half-open: it begins at the clock moved back by 28 days, inclusive, and ends at the clock, exclusive. The eligible events are those whose `cycle_id` belongs to a fill cycle of this patient, whose `event_type` is `POUCH_TAKEN` or `POUCH_MISSED`, and whose `occurred_at` falls inside that window; pickup and delivery events never enter the score. Count the taken events and the missed events. When the two counts sum to zero, `adherence_score_pct` is 100. Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent.
        One immutable adherence event is created per element, each carrying only `id` and `created_at` beyond its own payload; `source` is `PATIENT_REPORTED` when `X-User-Role` is `Patient` and `SYSTEM_SCAN` otherwise. Events are never edited or deleted once written.
        A score exactly equal to 80 does not pause.

        Design: Corner/calculations/adherence_projection_ignores_events_outside_the_rolling_window
        """
        scenario, earlier, current = self._scenario()
        do_dose_events(
            scenario.patient_id, current["id"], self._first_batch(), as_patient=True
        )

        do_dose_events(
            scenario.patient_id, earlier["id"], self._late_batch(), as_patient=True
        )

        assert_patient_posture(
            read_patient(scenario.patient_id),
            autoship_status="ACTIVE",
            pause_reason=None,
            adherence_score_pct=90,
        )
        stream = api_client.list_adherence_events(
            ops_headers(), {"cycle_id": earlier["id"], "limit": 100}
        )
        assert_total_count(stream, 4)
