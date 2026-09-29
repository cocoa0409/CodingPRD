"""Immediate consistency: a write response already carries what a later read reports.

There is no settle step anywhere in this domain. The adjudication response holds the
recomputed cycle totals, its lines' copays and the dispense stamps it pushed onto the
prescriptions, and the very next read agrees field for field. The same holds across
entity boundaries: the parcels a regimen change cancels, the lines it supersedes, the
memo a reissue mints and the patient balance it moves are all readable at once.
"""

from test_helpers import (
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    assert_cycle_state,
    assert_line_state,
    assert_memo,
    assert_patient_posture,
    assert_shipment_state,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    do_adjudicate,
    do_generate_roll,
    do_image_roll,
    do_pack,
    do_regimen_change,
    do_reissue,
    do_stage_shipment,
    do_synchronize,
    do_verify,
    line_by_prescription,
    memo_by_reason,
    pouch_roll_shipment_payload,
    read_cycle,
    read_lines,
    read_memos,
    read_patient,
    read_prescription,
    read_shipments,
    rivaroxaban_payload,
    set_clock,
    sitagliptin_payload,
)

COPAY_SPECIALTY_CENTS = 986
COPAY_PREFERRED_BRAND_CENTS = 1658


def _two_tablet_draft_cycle():
    """A synchronized patient on two MORNING tablets with a DRAFT cycle awaiting the payer."""
    set_clock("2026-08-10T00:00:00Z")
    plan = create_plan()
    patient = create_patient(plan["id"])
    specialty = create_rx(
        patient["id"], lambda pid: sitagliptin_payload(pid, dose_times=["MORNING"])
    )
    brand = create_rx(patient["id"], rivaroxaban_payload)
    do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
    cycle = create_cycle(patient["id"], "2026-08-15", 28)
    return patient, specialty, brand, cycle


class TestAdjudicationReturnsEveryDerivedNumber:
    """The adjudicate response is the settled cycle, not a promise of one."""

    def test_the_write_response_and_the_next_read_agree_field_for_field(self):
        """Adjudication returns total 2644, CLEARED, LINES_ADJUDICATED, version 2, and the read matches.

        Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. The packaging dimension moves from `DRAFT` to `LINES_ADJUDICATED`. The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`. The cycle's `version` increments by 1.

        Design: Corner/consistency_model/adjudication_returns_every_derived_number_in_the_same_response
        """
        _, _, _, cycle = _two_tablet_draft_cycle()
        assert_cycle_state(
            cycle,
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
            version=1,
        )

        written = do_adjudicate(cycle["id"])

        assert written["total_copay_cents"] == (
            COPAY_SPECIALTY_CENTS + COPAY_PREFERRED_BRAND_CENTS
        ), written
        assert written["total_copay_cents"] == 2644, written
        assert_cycle_state(
            written,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
            version=2,
        )

        read_back = read_cycle(cycle["id"])
        assert read_back["total_copay_cents"] == written["total_copay_cents"], read_back
        assert read_back["insurance_status"] == written["insurance_status"], read_back
        assert read_back["packaging_status"] == written["packaging_status"], read_back
        assert read_back["version"] == written["version"], read_back

    def test_the_line_copays_are_readable_in_the_same_instant(self):
        """Both lines come back ADJUDICATED at 986 and 1658 with no second adjudication call.

        Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. Otherwise it becomes `ADJUDICATED`.

        Design: Corner/consistency_model/adjudication_returns_every_derived_number_in_the_same_response
        """
        _, specialty, brand, cycle = _two_tablet_draft_cycle()

        do_adjudicate(cycle["id"])

        lines = read_lines(cycle["id"])
        assert len(lines) == 2, lines
        specialty_line = line_by_prescription(lines, specialty["id"])
        brand_line = line_by_prescription(lines, brand["id"])
        assert_line_state(
            specialty_line, line_status="ADJUDICATED", packable_route="POUCH"
        )
        assert specialty_line["copay_cents"] == COPAY_SPECIALTY_CENTS, specialty_line
        assert_line_state(brand_line, line_status="ADJUDICATED", packable_route="POUCH")
        assert brand_line["copay_cents"] == COPAY_PREFERRED_BRAND_CENTS, brand_line

    def test_the_dispense_stamp_is_visible_without_a_clock_advance(self):
        """The specialty prescription already reports two refills left and a 2026-08-15 stamp.

        Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`. Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1.

        Design: Corner/consistency_model/adjudication_returns_every_derived_number_in_the_same_response
        """
        _, specialty, _, cycle = _two_tablet_draft_cycle()
        assert specialty["refills_remaining"] == 3, specialty

        do_adjudicate(cycle["id"])

        dispensed = read_prescription(specialty["id"])
        assert dispensed["refills_remaining"] == 2, dispensed
        assert dispensed["last_dispensed_date"] == "2026-08-15", dispensed


class TestCascadedRowsAreReadableImmediately:
    """A regimen change and a reissue expose every row they touch to the very next read."""

    @staticmethod
    def _verified_cycle_with_a_staged_pouch_parcel():
        """The two-tablet cycle driven to VERIFIED with a STAGED POUCH_ROLL parcel."""
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        specialty = create_rx(
            patient["id"], lambda pid: sitagliptin_payload(pid, dose_times=["MORNING"])
        )
        brand = create_rx(patient["id"], rivaroxaban_payload)
        do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
        cycle = create_cycle(patient["id"], "2026-08-15", 28)
        adjudicated = do_adjudicate(cycle["id"])
        roll = do_generate_roll(cycle["id"], TECHNICIAN_ID)
        do_pack(roll["id"], TECHNICIAN_ID)
        do_image_roll(roll["id"], 97, None, TECHNICIAN_ID_2)
        do_verify(roll["id"], PHARMACIST_ID)
        parcel = do_stage_shipment(cycle["id"], pouch_roll_shipment_payload())
        return patient, specialty, brand, adjudicated, parcel

    def test_the_regimen_change_cascade_is_readable_with_no_intervening_write(self):
        """The staged parcel, the cycle and the superseded line all report the cascade at once.

        Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned. Because the prescription was superseded, every cycle line referencing it on a cycle whose `packaging_status` is `DRAFT`, `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED` or `VERIFIED` becomes `SUPERSEDED_PENDING_REISSUE` with `hold_reason` `REGIMEN_CHANGE`; lines on a cycle that has already reached `SHIPPED`, `CLOSED` or `CANCELLED` are left alone, because that medication has already left the building. Because at least one line was superseded, each affected cycle sets `reissue_required` to true, and a cycle whose `packaging_status` is `PACKED` or `VERIFIED` reverts to `ROLL_GENERATED` — the roll must be rebuilt, and a reverted roll is re-generated rather than re-verified. Because the cycle reverted, every shipment of that cycle whose `status` is `STAGED` and whose `shipment_kind` is `POUCH_ROLL` becomes `CANCELLED`; cold-chain and loose parcels are untouched, since they never carried the changed drug's pouches.

        Design: Corner/consistency_model/cascaded_rows_are_readable_in_the_instant_the_cascade_runs
        """
        _, specialty, brand, cycle, parcel = (
            self._verified_cycle_with_a_staged_pouch_parcel()
        )
        assert_shipment_state(parcel, status="STAGED")
        assert read_cycle(cycle["id"])["packaging_status"] == "VERIFIED"

        target = read_prescription(specialty["id"])
        do_regimen_change(
            specialty["id"],
            target["version"],
            new_drug_name="Linagliptin",
            new_copay_tier="SPECIALTY",
            new_dose_times=["MORNING"],
        )

        parcels = read_shipments(cycle["id"])
        assert len(parcels) == 1, parcels
        assert_shipment_state(parcels[0], status="CANCELLED")

        after = read_cycle(cycle["id"])
        assert after["packaging_status"] == "ROLL_GENERATED", after
        assert after["reissue_required"] is True, after

        lines = read_lines(cycle["id"])
        assert_line_state(
            line_by_prescription(lines, specialty["id"]),
            line_status="SUPERSEDED_PENDING_REISSUE",
            hold_reason="REGIMEN_CHANGE",
        )
        assert_line_state(
            line_by_prescription(lines, brand["id"]), line_status="ADJUDICATED"
        )

    def test_the_reissue_memo_and_the_patient_balance_land_inside_the_same_request(self):
        """The reissue returns the successor cycle while the 384-cent memo and balance already read back.

        Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned. `reissue_fee_cents` is stamped on the **original** cycle, and the memo is issued with `reason` `PARTIAL_REISSUE`, `cycle_id` naming the original cycle, `status` `ISSUED` and `issued_at` at the clock; the patient's `credit_balance_cents` rises by `amount_cents`. Money is conserved: the original `total_copay_cents` equals the retained basis plus the net credit plus the fee.

        Design: Corner/consistency_model/cascaded_rows_are_readable_in_the_instant_the_cascade_runs
        """
        patient, specialty, _, cycle, _ = (
            self._verified_cycle_with_a_staged_pouch_parcel()
        )
        assert cycle["total_copay_cents"] == 2644, cycle
        successor_rx = do_regimen_change(
            specialty["id"],
            read_prescription(specialty["id"])["version"],
            new_drug_name="Linagliptin",
            new_copay_tier="SPECIALTY",
            new_dose_times=["MORNING"],
        )

        child = do_reissue(
            cycle["id"],
            "2026-08-25",
            [successor_rx["id"]],
            read_cycle(cycle["id"])["version"],
        )

        assert child["is_partial_reissue"] is True, child
        assert child["reissue_of_cycle_id"] == cycle["id"], child

        memos = read_memos(patient["id"])
        assert len(memos) == 1, memos
        assert_memo(
            memo_by_reason(memos, "PARTIAL_REISSUE"),
            reason="PARTIAL_REISSUE",
            amount_cents=384,
            status="ISSUED",
            cycle_id=cycle["id"],
        )
        assert_patient_posture(read_patient(patient["id"]), credit_balance_cents=384)

        original = read_cycle(cycle["id"])
        assert original["reissue_fee_cents"] == 250, original
        assert original["total_copay_cents"] == 2010, original
        assert 2644 == original["total_copay_cents"] + 384 + original["reissue_fee_cents"]
