"""Conserved quantities across compensating reversals.

Two non-monetary ledgers are pinned here. The cold-chain excursion branch unwinds
a dispense that a different endpoint stamped several steps earlier, so the
prescription's refill units and dispensed days must return to their exact
pre-dispense values. Rework unwinds a failed verification, so the pouch
population and its verification partition must survive with no pouch minted and
none destroyed.
"""

from test_helpers import (
    ApiErrorId,
    PHARMACIST_ID,
    TECHNICIAN_ID,
    api_client,
    assert_line_state,
    assert_memo,
    assert_patient_posture,
    assert_roll_state,
    cold_chain_shipment_payload,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    deliver_payload,
    do_adjudicate,
    do_dispatch,
    do_pack,
    do_rework,
    do_stage_shipment,
    do_synchronize,
    get_success_data,
    insulin_payload,
    memo_by_reason,
    ops_headers,
    pouch_by_index,
    read_cycle,
    read_cycle_events,
    read_lines,
    read_memos,
    read_patient,
    read_pouches,
    read_prescription,
    read_roll,
    read_shipments,
    set_clock,
    setup_quarantined_roll,
    validate_error,
    validate_success,
)

VERIFICATION_RESULTS = ("MATCH", "MISMATCH_COUNT", "UNREADABLE", "PENDING", "VOID")


def _cold_chain_dispense_in_transit():
    """A refrigerated-only cycle adjudicated and dispatched as a cold-chain parcel."""
    set_clock("2026-08-10T00:00:00Z")
    plan = create_plan(
        max_day_supply_days=90,
        vacation_overrides_per_year=1,
        allows_payer_vacation_override=True,
    )
    patient = create_patient(plan["id"])
    prescription = create_rx(
        patient["id"], lambda pid: insulin_payload(pid, days_supply_written=30)
    )
    do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
    cycle = create_cycle(patient["id"], "2026-08-15", 28)
    cycle = do_adjudicate(cycle["id"])
    shipment = do_stage_shipment(
        cycle["id"], cold_chain_shipment_payload(packaging="INSULATED_DRY_ICE")
    )
    do_dispatch(shipment["id"])
    return patient, prescription, cycle, shipment


def _deliver_with_excursion(shipment_id, minutes):
    """Record delivery reporting a temperature excursion of that many minutes."""
    return api_client.deliver_shipment(
        shipment_id, ops_headers(), deliver_payload(minutes)
    )


def _partition(pouches):
    """The pouch population grouped by verification result."""
    counts = {result: 0 for result in VERIFICATION_RESULTS}
    for pouch in pouches:
        counts[pouch["verification_result"]] += 1
    return counts


class TestColdChainReversalConservesTheDispenseLedger:
    """The excursion reversal restores the prescription ledger it did not write."""

    def test_refill_units_are_conserved_before_and_after_the_reversal(self):
        """The refill invariant holds both after the dispense and after its reversal.

        Because those lines were credited, each one's prescription reverses its dispense exactly: `days_dispensed_total` falls by that line's `days_supply_filled`, `refills_remaining` rises by 1, `refills_consumed` falls by 1, and `last_dispensed_date` and `last_dispensed_days_supply` are restored verbatim from `prior_last_dispensed_date` and `prior_last_dispensed_days_supply`. The invariant that `refills_remaining` plus `refills_consumed` equals `refills_authorized` holds after every mutation of the prescription, including every dispense, every reversal and every re-authorization.

        Design: Difficulty/compensating_invariant/cold_chain_reversal_conserves_refill_units_and_dispensed_days
        """
        _, prescription, _, shipment = _cold_chain_dispense_in_transit()

        before = read_prescription(prescription["id"])
        assert before["refills_remaining"] == 2, before
        assert before["refills_consumed"] == 1, before
        assert before["refills_authorized"] == 3, before
        assert (
            before["refills_remaining"] + before["refills_consumed"]
            == before["refills_authorized"]
        ), before

        validate_success(_deliver_with_excursion(shipment["id"], 240))

        after = read_prescription(prescription["id"])
        assert after["refills_remaining"] == 3, after
        assert after["refills_consumed"] == 0, after
        assert after["refills_authorized"] == 3, after
        assert (
            after["refills_remaining"] + after["refills_consumed"]
            == after["refills_authorized"]
        ), after

    def test_dispensed_days_and_the_dispense_stamp_return_to_their_pre_dispense_values(
        self,
    ):
        """The 28 days the adjudication added come back off, and the shadow stamp is restored.

        Because those lines were credited, each one's prescription reverses its dispense exactly: `days_dispensed_total` falls by that line's `days_supply_filled`, `refills_remaining` rises by 1, `refills_consumed` falls by 1, and `last_dispensed_date` and `last_dispensed_days_supply` are restored verbatim from `prior_last_dispensed_date` and `prior_last_dispensed_days_supply`. The refills invariant therefore holds again, and a subsequent cycle adjudicates against the pre-dispense history rather than against a fill the patient never received.

        Design: Difficulty/compensating_invariant/cold_chain_reversal_conserves_refill_units_and_dispensed_days
        """
        _, prescription, _, shipment = _cold_chain_dispense_in_transit()

        before = read_prescription(prescription["id"])
        assert before["days_dispensed_total"] == 28, before
        assert before["last_dispensed_date"] == "2026-08-15", before
        assert before["last_dispensed_days_supply"] == 28, before
        assert before["prior_last_dispensed_date"] == "2026-07-18", before
        assert before["prior_last_dispensed_days_supply"] == 28, before

        validate_success(_deliver_with_excursion(shipment["id"], 240))

        after = read_prescription(prescription["id"])
        assert after["days_dispensed_total"] == 0, after
        assert after["last_dispensed_date"] == "2026-07-18", after
        assert after["last_dispensed_days_supply"] == 28, after

    def test_the_money_side_of_the_same_reversal_lands_on_the_credited_line(self):
        """The returned parcel credits its line, mints a 986-cent memo and empties the cycle total.

        The exception branch applies only to a `COLD_CHAIN` parcel whose `cold_chain_excursion_minutes` is strictly greater than 120 — the drug is no longer safe, so the parcel is returned and the entire dispense is unwound: A credit memo is issued with `reason` `COLD_CHAIN_EXCURSION`, `amount_cents` equal to the sum of `copay_cents` over the credited lines and `status` `ISSUED`, and the patient's `credit_balance_cents` rises by that amount. The cycle's `total_copay_cents` is recomputed over its remaining lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`; credited lines no longer contribute.

        Design: Difficulty/compensating_invariant/cold_chain_reversal_conserves_refill_units_and_dispensed_days
        """
        patient, prescription, cycle, shipment = _cold_chain_dispense_in_transit()
        assert cycle["total_copay_cents"] == 986, cycle

        returned = get_success_data(_deliver_with_excursion(shipment["id"], 240))
        assert returned["status"] == "EXCEPTION_RETURNED", returned

        lines = read_lines(cycle["id"])
        assert len(lines) == 1, lines
        assert_line_state(lines[0], line_status="CREDITED", packable_route="COLD_CHAIN")
        assert lines[0]["id"] in returned["covers_line_ids"], returned

        memos = read_memos(patient["id"])
        assert len(memos) == 1, memos
        assert_memo(
            memo_by_reason(memos, "COLD_CHAIN_EXCURSION"),
            reason="COLD_CHAIN_EXCURSION",
            amount_cents=986,
            status="ISSUED",
            cycle_id=cycle["id"],
        )
        assert_patient_posture(read_patient(patient["id"]), credit_balance_cents=986)
        assert read_cycle(cycle["id"])["total_copay_cents"] == 0
        assert read_prescription(prescription["id"])["days_dispensed_total"] == 0

    def test_an_exception_event_is_appended_for_the_returned_parcel(self):
        """The reversal appends one DELIVERY_EXCEPTION event attributed to the cycle.

        An adherence event is appended with `event_type` `DELIVERY_EXCEPTION` and `source` `SYSTEM_SCAN`, attributed to the cycle through `cycle_id`.

        Design: Difficulty/compensating_invariant/cold_chain_reversal_conserves_refill_units_and_dispensed_days
        """
        _, _, cycle, shipment = _cold_chain_dispense_in_transit()

        validate_success(_deliver_with_excursion(shipment["id"], 240))

        events = [
            event
            for event in read_cycle_events(cycle["id"])
            if event["event_type"] == "DELIVERY_EXCEPTION"
        ]
        assert len(events) == 1, events
        assert events[0]["source"] == "SYSTEM_SCAN", events[0]

    def test_a_second_delivery_is_refused_and_the_ledger_does_not_move_again(self):
        """Redelivering the returned parcel is refused, so the reversal cannot double-apply.

        The shipment's `status` must be `IN_TRANSIT`, otherwise `ERR_INVALID_SHIPMENT_STATE`. `EXCEPTION_RETURNED` is terminal, and it frees the `COLD_CHAIN` kind for a fresh parcel — subject again to the 48-hour separation buffer.

        Design: Difficulty/compensating_invariant/cold_chain_reversal_conserves_refill_units_and_dispensed_days
        """
        patient, prescription, cycle, shipment = _cold_chain_dispense_in_transit()
        validate_success(_deliver_with_excursion(shipment["id"], 240))

        validate_error(
            _deliver_with_excursion(shipment["id"], 240),
            ApiErrorId.INVALID_SHIPMENT_STATE,
        )

        after = read_prescription(prescription["id"])
        assert after["refills_remaining"] == 3, after
        assert after["refills_consumed"] == 0, after
        assert after["days_dispensed_total"] == 0, after
        assert after["last_dispensed_date"] == "2026-07-18", after
        assert_patient_posture(read_patient(patient["id"]), credit_balance_cents=986)
        assert len(read_memos(patient["id"])) == 1
        assert read_cycle(cycle["id"])["total_copay_cents"] == 0
        shipments = read_shipments(cycle["id"])
        assert len(shipments) == 1, shipments
        assert shipments[0]["status"] == "EXCEPTION_RETURNED", shipments[0]


class TestReworkConservesThePouchPopulation:
    """Rework resets every pouch of a quarantined roll without minting or deleting one."""

    def test_the_pouch_population_partitions_to_twenty_eight_at_both_instants(self):
        """A failed verification and the rework that undoes it both leave 28 pouches.

        `PouchRoll.pouch_count` is the number of such pairs, counting only pouches whose `verification_result` is not `VOID`, and the cycle's `roll_pouch_count` is set to that same figure. Every pouch of the roll whose `verification_result` is not `VOID` resets to `PENDING` with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` cleared to null; a `VOID` pouch is left as it is.

        Design: Difficulty/compensating_invariant/rework_conserves_pouch_population_and_mismatch_ledger
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        assert scenario.roll["pouch_count"] == 28, scenario.roll

        before = _partition(scenario.pouches)
        assert before == {
            "MATCH": 27,
            "MISMATCH_COUNT": 1,
            "UNREADABLE": 0,
            "PENDING": 0,
            "VOID": 0,
        }, before
        assert sum(before.values()) == 28, before

        reworked = do_rework(scenario.roll_id, PHARMACIST_ID)
        assert reworked["pouch_count"] == 28, reworked

        after_pouches = read_pouches(scenario.roll_id)
        after = _partition(after_pouches)
        assert after == {
            "MATCH": 0,
            "MISMATCH_COUNT": 0,
            "UNREADABLE": 0,
            "PENDING": 28,
            "VOID": 0,
        }, after
        assert sum(after.values()) == 28, after
        assert [pouch["pouch_index"] for pouch in after_pouches] == list(range(1, 29))

    def test_the_mismatch_ledger_matches_the_live_pouch_count_at_both_instants(self):
        """mismatch_pouch_count equals the live mismatch-or-unreadable population, before and after.

        The roll's `mismatch_pouch_count` is then recomputed as the number of its pouches whose `verification_result` is `MISMATCH_COUNT` or `UNREADABLE`. `mismatch_pouch_count` returns to 0 and the roll's `version` increments.

        Design: Difficulty/compensating_invariant/rework_conserves_pouch_population_and_mismatch_ledger
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)

        live_before = [
            pouch
            for pouch in scenario.pouches
            if pouch["verification_result"] in ("MISMATCH_COUNT", "UNREADABLE")
        ]
        assert len(live_before) == 1, live_before
        assert_roll_state(
            scenario.roll,
            verification_status="FAILED_QUARANTINED",
            mismatch_pouch_count=1,
            rework_count=0,
        )
        assert read_cycle(scenario.cycle_id)["packaging_status"] == "ROLL_GENERATED"

        reworked = do_rework(scenario.roll_id, PHARMACIST_ID)

        assert_roll_state(
            reworked,
            verification_status="BUILT",
            mismatch_pouch_count=0,
            rework_count=1,
        )
        live_after = [
            pouch
            for pouch in read_pouches(scenario.roll_id)
            if pouch["verification_result"] in ("MISMATCH_COUNT", "UNREADABLE")
        ]
        assert live_after == [], live_after

    def test_every_pouch_is_reset_while_its_expected_count_survives(self):
        """Rework clears the imaging fields of all 28 pouches and keeps expected_pill_count 1.

        Every pouch of the roll whose `verification_result` is not `VOID` resets to `PENDING` with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` cleared to null; a `VOID` pouch is left as it is. `expected_pill_count` is the sum of the `quantity` values across `contents` and is the count the verification image must match.

        Design: Difficulty/compensating_invariant/rework_conserves_pouch_population_and_mismatch_ledger
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        mismatched = pouch_by_index(scenario.pouches, 7)
        assert mismatched["verification_result"] == "MISMATCH_COUNT", mismatched
        assert mismatched["detected_pill_count"] == 0, mismatched

        do_rework(scenario.roll_id, PHARMACIST_ID)

        pouches = read_pouches(scenario.roll_id)
        assert len(pouches) == 28, pouches
        for pouch in pouches:
            assert pouch["verification_result"] == "PENDING", pouch
            assert pouch["detected_pill_count"] is None, pouch
            assert pouch["image_confidence_pct"] is None, pouch
            assert pouch["imaged_by_user_id"] is None, pouch
            assert pouch["imaged_at"] is None, pouch
            assert pouch["expected_pill_count"] == 1, pouch

    def test_the_goodwill_credit_is_not_reversed_by_the_rework(self):
        """The 500-cent failed-verification memo survives the rework unchanged.

        When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`, `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's `credit_balance_cents` rises by that amount as a goodwill gesture. A memo leaves `ISSUED` in one of two ways. It reaches `APPLIED` when a **later** cycle of the same patient adjudicates: outstanding memos are consumed in ascending `created_at` order while the adjudicating cycle still has copay left to offset, and a memo whose `cycle_id` is the adjudicating cycle itself is never applied to that cycle.

        Design: Difficulty/compensating_invariant/rework_conserves_pouch_population_and_mismatch_ledger
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=500
        )

        do_rework(scenario.roll_id, PHARMACIST_ID)

        memos = read_memos(scenario.patient_id)
        assert len(memos) == 1, memos
        assert_memo(
            memo_by_reason(memos, "FAILED_VERIFICATION"),
            reason="FAILED_VERIFICATION",
            amount_cents=500,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=500
        )

    def test_the_pack_identity_is_cleared_so_the_original_packer_may_pack_again(self):
        """Rework releases the pack identity, and tech-01 repacks the same 28 pouches.

        Sending a quarantined roll back for rework clears `packed_by_user_id`, `packed_at`, `verified_by_user_id` and `verified_at`, which means the identity constraint is released: after rework, any technician — including the original packer — may pack the roll again, and the constraint re-arms against whoever packs it that time.

        Design: Difficulty/compensating_invariant/rework_conserves_pouch_population_and_mismatch_ledger
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        assert scenario.roll["packed_by_user_id"] == TECHNICIAN_ID, scenario.roll

        reworked = do_rework(scenario.roll_id, PHARMACIST_ID)
        assert reworked["packed_by_user_id"] is None, reworked
        assert reworked["packed_at"] is None, reworked
        assert reworked["verified_by_user_id"] is None, reworked
        assert reworked["verified_at"] is None, reworked

        repacked = do_pack(scenario.roll_id, TECHNICIAN_ID)
        assert_roll_state(repacked, verification_status="PACKED", rework_count=1)
        assert repacked["packed_by_user_id"] == TECHNICIAN_ID, repacked
        assert read_roll(scenario.roll_id)["pouch_count"] == 28
