"""Multi-level cascades of the multi-dose adherence mail pharmacy API.

Two chains are exercised here. The prescriber's authorization answer unblocks a
request, then its prescription, then the held claim line, then the cycle's money
and payer dimension, and finally lets the bench build the roll. The operations
adherence sweep runs the other way: it writes off two uncollected parcels, pauses
the patient on the pickup counter, cancels the next draft cycle and excludes that
cycle's lines.

Every test builds its whole world through the API, because each one starts
against an empty database.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_patient_posture,
    assert_shipment_state,
    assert_total_count,
    cold_chain_shipment_payload,
    create_cycle,
    do_adherence_review,
    do_adjudicate,
    do_deliver,
    do_generate_roll,
    do_respond,
    fill_cycle_payload,
    insulin_payload,
    line_by_prescription,
    metformin_payload,
    open_authorization,
    ops_headers,
    pouch_by_index,
    pouch_roll_shipment_payload,
    prescription_payload,
    read_cycle,
    read_lines,
    read_patient,
    read_pouches,
    read_prescription,
    read_shipments,
    rivaroxaban_payload,
    set_clock,
    setup_draft_cycle,
    setup_shipped_cycle,
    sitagliptin_payload,
    technician_headers,
    validate_error,
    TECHNICIAN_ID,
)

CLOCK = "2026-08-10T00:00:00Z"


def _levothyroxine_no_refills(patient_id):
    """A morning tablet written with no refills left, last filled 2026-07-18 for 30 days."""
    return prescription_payload(
        patient_id,
        drug_name="Levothyroxine",
        ndc="00074-4341-90",
        strength="75mcg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["MORNING"],
        quantity_per_dose=1,
        days_supply_written=30,
        refills_authorized=0,
        last_dispensed_date="2026-07-18",
        last_dispensed_days_supply=30,
    )


def _held_authorization_scenario():
    """A cycle whose Levothyroxine line is on an authorization hold, chase already open.

    The Metformin line clears every edit; the Levothyroxine prescription has no
    refills left, so adjudication holds its line and leaves the cycle waiting on
    the prescriber.
    """
    scenario = setup_draft_cycle(
        clock=CLOCK,
        prescriptions=[
            lambda patient_id: metformin_payload(
                patient_id, dose_times=["MORNING", "BEDTIME"]
            ),
            _levothyroxine_no_refills,
        ],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    scenario.cycle = do_adjudicate(scenario.cycle_id)
    scenario.authorization = open_authorization(
        scenario.rx_named("Levothyroxine")["id"], 2
    )
    return scenario


def _two_missed_parcels_and_a_draft_next_cycle():
    """A shipped cycle whose two parcels were delivered and never collected.

    The pouch roll and the cold-chain parcel are both delivered on 2026-08-14, a
    second cycle is opened for 2026-09-15 and left in draft, and the clock is then
    moved to 2026-08-20 so the five-day pickup grace has expired.
    """
    scenario = setup_shipped_cycle(
        clock=CLOCK,
        prescriptions=[
            lambda patient_id: metformin_payload(
                patient_id, dose_times=["MORNING", "BEDTIME"]
            ),
            rivaroxaban_payload,
            sitagliptin_payload,
            insulin_payload,
        ],
        image_confidence_pct=96,
        shipments=[pouch_roll_shipment_payload(), cold_chain_shipment_payload()],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    set_clock("2026-08-14T00:00:00Z")
    for shipment in scenario.shipments:
        excursion = 30 if shipment["shipment_kind"] == "COLD_CHAIN" else None
        do_deliver(shipment["id"], excursion)
    next_cycle = create_cycle(scenario.patient_id, "2026-09-15", 28)
    set_clock("2026-08-20T00:00:00Z")
    return scenario, next_cycle


class TestPrescriberApprovalCascade:
    """The prescriber's answer walks request, prescription, line, cycle and bench."""

    def test_approval_revives_the_held_line_and_clears_the_cycle(self):
        """An approval restores refills, revives the held line and clears the payer dimension.

        An approval sets `status` `APPROVED` and stores `approved_refills`. Because the request was approved, the prescription moves from `PENDING_AUTHORIZATION` back to `ACTIVE` with both `refills_authorized` and `refills_remaining` raised by `approved_refills`. Because refills exist again, every line of that prescription whose `line_status` is `HELD_AUTH` becomes `ADJUDICATED`: its `copay_cents` is computed exactly as a first-pass adjudication would compute it, and the dispense is stamped onto the prescription in the same order — `prior_last_dispensed_date` and `prior_last_dispensed_days_supply` preserved first, then `last_dispensed_date` and `last_dispensed_days_supply` advanced, `days_dispensed_total` raised by `days_supply_filled`, `refills_remaining` reduced by 1 and `refills_consumed` raised by 1. Because a held line resolved, each affected cycle recomputes `total_copay_cents` and, when no `HELD_AUTH` or `HELD_TOO_SOON` line remains and at least one line is `ADJUDICATED`, moves `insurance_status` from `EDITS_PENDING` to `CLEARED`.

        Design: Difficulty/transitive_cascade/prescriber_approval_cascades_four_levels_to_the_cycle
        """
        scenario = _held_authorization_scenario()
        held_rx = scenario.rx_named("Levothyroxine")
        assert_cycle_state(
            scenario.cycle,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="EDITS_PENDING",
        )
        assert scenario.cycle["total_copay_cents"] == 762

        authorization = do_respond(
            scenario.authorization["id"], "APPROVE", approved_refills=2
        )

        assert authorization["status"] == "APPROVED"
        assert authorization["approved_refills"] == 2

        revived = read_prescription(held_rx["id"])
        assert revived["status"] == "ACTIVE"
        assert revived["refills_authorized"] == 2
        assert revived["refills_remaining"] == 1
        assert revived["refills_consumed"] == 1
        assert revived["days_dispensed_total"] == 28
        assert revived["last_dispensed_date"] == "2026-08-15"
        assert revived["last_dispensed_days_supply"] == 28

        line = line_by_prescription(read_lines(scenario.cycle_id), held_rx["id"])
        assert_line_state(line, line_status="ADJUDICATED", hold_reason=None)
        assert line["days_supply_filled"] == 28
        assert line["refill_pct_used"] == 93
        assert line["copay_cents"] == 762

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
        )
        assert cycle["total_copay_cents"] == 1524

    def test_approval_leaves_the_sibling_prescription_alone(self):
        """Only the answered prescription's own lines are revived by the approval.

        Because refills exist again, every line of that prescription whose `line_status` is `HELD_AUTH` becomes `ADJUDICATED`: its `copay_cents` is computed exactly as a first-pass adjudication would compute it, and the dispense is stamped onto the prescription in the same order — `prior_last_dispensed_date` and `prior_last_dispensed_days_supply` preserved first, then `last_dispensed_date` and `last_dispensed_days_supply` advanced, `days_dispensed_total` raised by `days_supply_filled`, `refills_remaining` reduced by 1 and `refills_consumed` raised by 1. The invariant that `refills_remaining` plus `refills_consumed` equals `refills_authorized` holds after every mutation of the prescription, including every dispense, every reversal and every re-authorization.

        Design: Difficulty/transitive_cascade/prescriber_approval_cascades_four_levels_to_the_cycle
        """
        scenario = _held_authorization_scenario()
        sibling = scenario.rx_named("Metformin ER")

        do_respond(scenario.authorization["id"], "APPROVE", approved_refills=2)

        after = read_prescription(sibling["id"])
        assert after["refills_remaining"] == 2
        assert after["days_dispensed_total"] == 28
        assert (
            after["refills_remaining"] + after["refills_consumed"]
            == after["refills_authorized"]
        )

    def test_cleared_cycle_can_finally_build_its_fifty_six_pouch_roll(self):
        """Roll generation is refused while edits are open and succeeds once the approval clears them.

        Its gates are evaluated in this order: the cycle's `packaging_status` must be `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the segment the new roll would occupy must not collide with a live roll of the same patient under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then, if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with `ERR_REFILL_TOO_SOON`. One pouch is produced for each distinct pairing of a calendar date with a slot such that at least one contributing line both covers that date, meaning the date is on or after that line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in its prescription's `dose_times`. `expected_pill_count` is the sum of the `quantity` values across `contents` and is the count the verification image must match.

        Design: Difficulty/transitive_cascade/prescriber_approval_cascades_four_levels_to_the_cycle
        """
        scenario = _held_authorization_scenario()

        blocked = api_client.generate_roll(
            scenario.cycle_id, technician_headers(TECHNICIAN_ID)
        )
        validate_error(blocked, ApiErrorId.CYCLE_NOT_CLEARED)

        do_respond(scenario.authorization["id"], "APPROVE", approved_refills=2)

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)
        assert roll["pouch_count"] == 56

        first_pouch = pouch_by_index(read_pouches(roll["id"]), 1)
        assert first_pouch["dose_date"] == "2026-08-15"
        assert first_pouch["dose_slot"] == "MORNING"
        assert first_pouch["expected_pill_count"] == 2


class TestMissedPickupSweepCascade:
    """The adherence sweep walks parcels, patient posture, draft cycle and its lines."""

    def test_sweep_writes_off_both_parcels_and_pauses_on_the_pickup_counter(self):
        """Two parcels past their pickup grace pause auto-ship on the counter, not on the score.

        It sweeps the patient's parcels for an expired pickup grace period: every shipment of the patient whose `status` is `DELIVERED` and whose `delivered_at` advanced by 5 days is at or before the clock becomes `PICKUP_MISSED`, and each such sweep appends an adherence event with `event_type` `PICKUP_MISSED` and `source` `SYSTEM_SCAN`. The patient's `consecutive_missed_pickups` rises by the number of parcels swept in this run. When the two counts sum to zero, `adherence_score_pct` is 100. Otherwise, if `consecutive_missed_pickups` is greater than or equal to 2, `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `MISSED_PICKUPS`.

        Design: Difficulty/transitive_cascade/missed_pickup_sweep_cascades_to_cancelled_draft_cycle_lines
        """
        scenario, _ = _two_missed_parcels_and_a_draft_next_cycle()

        do_adherence_review(scenario.patient_id)

        shipments = read_shipments(scenario.cycle_id)
        assert len(shipments) == 2
        for shipment in shipments:
            assert_shipment_state(shipment, status="PICKUP_MISSED")

        events = assert_total_count(
            api_client.list_adherence_events(
                ops_headers(), {"event_type": "PICKUP_MISSED", "limit": 100}
            ),
            2,
        )
        for event in events:
            assert event["source"] == "SYSTEM_SCAN"

        patient = read_patient(scenario.patient_id)
        assert_patient_posture(
            patient,
            autoship_status="PAUSED_ADHERENCE",
            pause_reason="MISSED_PICKUPS",
            adherence_score_pct=100,
            consecutive_missed_pickups=2,
        )

    def test_pause_cancels_the_next_draft_cycle_and_excludes_its_lines(self):
        """The pause cascades into the draft cycle, cancelling it and excluding every line.

        When auto-ship pauses this way, every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED` and every cycle line of those cancelled cycles becomes `EXCLUDED_HELD`, with `hold_reason` left null because no per-line edit failed.

        Design: Difficulty/transitive_cascade/missed_pickup_sweep_cascades_to_cancelled_draft_cycle_lines
        """
        scenario, next_cycle = _two_missed_parcels_and_a_draft_next_cycle()
        assert_cycle_state(next_cycle, packaging_status="DRAFT")

        do_adherence_review(scenario.patient_id)

        cancelled = read_cycle(next_cycle["id"])
        assert_cycle_state(cancelled, packaging_status="CANCELLED")

        lines = read_lines(next_cycle["id"])
        assert len(lines) == 4
        for line in lines:
            assert_line_state(line, line_status="EXCLUDED_HELD", hold_reason=None)

    def test_paused_patient_can_no_longer_open_a_fill_cycle(self):
        """A patient paused by the sweep is refused a fresh fill cycle.

        The patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED` — a paused or cancelled auto-ship blocks cycle creation outright. Note the asymmetry between the two pause postures: `PAUSED_PATIENT` and `PAUSED_ADHERENCE` both block cycle creation, adjudication and reissue through `ERR_AUTOSHIP_PAUSED`, but only `PAUSED_PATIENT` is reachable by the patient's own request, and only `PAUSED_ADHERENCE` is reachable by a breached gate.

        Design: Difficulty/transitive_cascade/missed_pickup_sweep_cascades_to_cancelled_draft_cycle_lines
        """
        scenario, _ = _two_missed_parcels_and_a_draft_next_cycle()

        do_adherence_review(scenario.patient_id)

        response = api_client.create_fill_cycle(
            fill_cycle_payload(scenario.patient_id, "2026-10-15", 28), ops_headers()
        )
        validate_error(response, ApiErrorId.AUTOSHIP_PAUSED)
