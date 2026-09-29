"""Layered scenarios where several controls stack on one another.

The optimistic-concurrency parents are exercised end to end: the fill cycle whose
version the regimen change itself bumps, the prescription whose version the change
bumps, and the exactness of version movement across writes, cascades and reads.
The last group drives the pickup counter across a pause, a resume and a fresh miss,
to show the cumulative gate is a re-armable counter rather than a lifetime history.
"""

from test_helpers import (
    ApiErrorId,
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    albuterol_payload,
    api_client,
    assert_memo,
    assert_patient_posture,
    assert_total_count,
    cold_chain_shipment_payload,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    do_adherence_review,
    do_adjudicate,
    do_autoship,
    do_deliver,
    do_dispatch,
    do_generate_roll,
    do_image_roll,
    do_pack,
    do_regimen_change,
    do_reissue,
    do_stage_shipment,
    do_synchronize,
    do_verify,
    get_success_data,
    insulin_payload,
    loose_shipment_payload,
    memo_by_reason,
    metformin_payload,
    ops_headers,
    pouch_roll_shipment_payload,
    prescriber_headers,
    prescription_payload,
    read_cycle,
    read_memos,
    read_patient,
    read_prescription,
    read_shipments,
    regimen_change_payload,
    reissue_payload,
    rivaroxaban_payload,
    set_clock,
    sitagliptin_payload,
    validate_error,
)


def _two_tablet_cycle_rolled_then_regimen_changed():
    """A rolled two-tablet cycle whose specialty tablet has just been superseded."""
    set_clock("2026-08-10T00:00:00Z")
    plan = create_plan()
    patient = create_patient(plan["id"])
    rx1 = create_rx(
        patient["id"], lambda pid: sitagliptin_payload(pid, dose_times=["MORNING"])
    )
    rx2 = create_rx(patient["id"], rivaroxaban_payload)
    do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
    cycle = create_cycle(patient["id"], "2026-08-15", 28)
    adjudicated = do_adjudicate(cycle["id"])
    do_generate_roll(cycle["id"], TECHNICIAN_ID)
    target = read_prescription(rx1["id"])
    successor = do_regimen_change(
        rx1["id"],
        target["version"],
        new_drug_name="Linagliptin",
        new_copay_tier="SPECIALTY",
        new_dose_times=["MORNING"],
    )
    return patient, rx1, rx2, adjudicated, successor


def _attempt_reissue(cycle_id, expected_cycle_version, replacement_prescription_ids):
    """Ask for a partial reissue effective 2026-08-25 at the given expected version."""
    return api_client.reissue_fill_cycle(
        cycle_id,
        reissue_payload(
            "2026-08-25", replacement_prescription_ids, expected_cycle_version
        ),
        ops_headers(),
    )


class TestReissueFromAPreRegimenChangeCycleView:
    """The regimen change that creates the reissue work also invalidates the caller's view."""

    def test_the_stale_reissue_is_refused_and_writes_nothing(self):
        """A reissue quoting the pre-change cycle version is refused with 412 and no side effect.

        Creating a partial reissue against a fill cycle requires `expected_cycle_version` in the request body. If that value does not equal the addressed fill cycle's current `version`, the request fails with `ERR_STALE_CYCLE_VERSION` and HTTP 412. Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/cross_cutting_complexity_layers/reissue_from_a_pre_regimen_change_cycle_view_is_rejected_as_stale
        """
        patient, _, _, adjudicated, successor = (
            _two_tablet_cycle_rolled_then_regimen_changed()
        )
        assert adjudicated["total_copay_cents"] == 2644, adjudicated
        version_before = read_cycle(adjudicated["id"])["version"]
        assert version_before == adjudicated["version"] + 2, version_before

        validate_error(
            _attempt_reissue(
                adjudicated["id"], adjudicated["version"], [successor["id"]]
            ),
            ApiErrorId.STALE_CYCLE_VERSION,
        )

        assert read_memos(patient["id"]) == []
        assert_patient_posture(read_patient(patient["id"]), credit_balance_cents=0)
        cycle_after = read_cycle(adjudicated["id"])
        assert cycle_after["version"] == version_before, cycle_after
        assert cycle_after["reissue_required"] is True, cycle_after

    def test_the_retry_with_the_re_read_version_succeeds_and_credits_once(self):
        """Re-reading the cycle version lets the same reissue through and issues one 384-cent memo.

        A new fill cycle is created with `is_partial_reissue` true, `reissue_of_cycle_id` naming the original cycle, `cycle_start_date` equal to `effective_date`, `day_supply_days` equal to the number of days from `effective_date` to the original cycle's `cycle_end_date`, `packaging_status` `DRAFT`, `insurance_status` `NOT_ADJUDICATED`, and one `PLANNED` cycle line per prescription named in `replacement_prescription_ids`. The credit memo's `amount_cents` is the gross credit minus `reissue_fee_cents`, floored at zero so it is never negative.

        Design: Corner/cross_cutting_complexity_layers/reissue_from_a_pre_regimen_change_cycle_view_is_rejected_as_stale
        """
        patient, _, _, adjudicated, successor = (
            _two_tablet_cycle_rolled_then_regimen_changed()
        )
        validate_error(
            _attempt_reissue(
                adjudicated["id"], adjudicated["version"], [successor["id"]]
            ),
            ApiErrorId.STALE_CYCLE_VERSION,
        )

        current_version = read_cycle(adjudicated["id"])["version"]
        child = get_success_data(
            _attempt_reissue(adjudicated["id"], current_version, [successor["id"]]),
            expected_status=201,
        )

        assert child["cycle_start_date"] == "2026-08-25", child
        assert child["day_supply_days"] == 18, child
        assert child["is_partial_reissue"] is True, child
        assert child["reissue_of_cycle_id"] == adjudicated["id"], child

        memos = read_memos(patient["id"])
        assert len(memos) == 1, memos
        assert_memo(
            memo_by_reason(memos, "PARTIAL_REISSUE"),
            reason="PARTIAL_REISSUE",
            amount_cents=384,
            status="ISSUED",
            cycle_id=adjudicated["id"],
        )
        original = read_cycle(adjudicated["id"])
        assert original["reissue_fee_cents"] == 250, original
        assert original["total_copay_cents"] == 2010, original

    def test_replaying_the_successful_reissue_cannot_double_issue_the_credit(self):
        """Repeating the accepted reissue body is refused, so the 384-cent credit lands once.

        Creating a partial reissue against a fill cycle requires `expected_cycle_version` in the request body. If that value does not equal the addressed fill cycle's current `version`, the request fails with `ERR_STALE_CYCLE_VERSION` and HTTP 412. A reissue legitimately supersedes the tail of a cycle — trimming lines, truncating the roll segment and issuing a credit — so a second reissue derived from a pre-trim view of the cycle would credit days the first reissue already credited.

        Design: Corner/cross_cutting_complexity_layers/reissue_from_a_pre_regimen_change_cycle_view_is_rejected_as_stale
        """
        patient, _, _, adjudicated, successor = (
            _two_tablet_cycle_rolled_then_regimen_changed()
        )
        accepted_version = read_cycle(adjudicated["id"])["version"]
        do_reissue(
            adjudicated["id"], "2026-08-25", [successor["id"]], accepted_version
        )

        validate_error(
            _attempt_reissue(adjudicated["id"], accepted_version, [successor["id"]]),
            ApiErrorId.STALE_CYCLE_VERSION,
        )

        memos = read_memos(patient["id"])
        assert len(memos) == 1, memos
        assert memos[0]["amount_cents"] == 384, memos[0]
        assert_patient_posture(read_patient(patient["id"]), credit_balance_cents=384)


class TestRegimenChangeReplayedFromTheSameVersion:
    """The prescription's own version is bumped by the change, so a replay is stale."""

    def test_the_replay_is_refused_at_the_version_check_not_the_state_check(self):
        """Re-sending the change with the original version returns the stale-prescription error.

        Issuing a mid-cycle regimen change against a prescription requires `expected_prescription_version` in the request body. If that value does not equal the addressed prescription's current `version`, the request fails with `ERR_STALE_PRESCRIPTION_VERSION` and HTTP 412. A regimen change supersedes the prescription and mints a successor, so a change written from a stale view would branch a second successor off an already-superseded prescription. A regimen-change request that is both stale and aimed at a non-active prescription returns the stale-version error.

        Design: Corner/cross_cutting_complexity_layers/regimen_change_replayed_from_the_same_version_is_rejected_as_stale
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        original = create_rx(patient["id"], prescription_payload)
        assert original["version"] == 1, original

        successor = do_regimen_change(
            original["id"],
            original["version"],
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
        )
        assert successor["id"] != original["id"], successor
        assert successor["version"] == 1, successor

        superseded = read_prescription(original["id"])
        assert superseded["version"] == 2, superseded
        assert superseded["status"] == "SUPERSEDED", superseded

        validate_error(
            api_client.regimen_change(
                original["id"],
                regimen_change_payload(
                    original["version"],
                    new_drug_name="Glipizide",
                    new_dose_times=["MORNING"],
                ),
                prescriber_headers(),
            ),
            ApiErrorId.STALE_PRESCRIPTION_VERSION,
        )

    def test_no_second_successor_branches_off_the_superseded_row(self):
        """After the refused replay the successor chain still holds exactly one successor.

        The addressed prescription moves from `ACTIVE` to the terminal `SUPERSEDED`, and a successor prescription is created with `status` `ACTIVE` and `supersedes_rx_id` pointing at the addressed prescription's `id`. Filtering by `supersedes_rx_id` resolves the successor chain minted by regimen changes.

        Design: Corner/cross_cutting_complexity_layers/regimen_change_replayed_from_the_same_version_is_rejected_as_stale
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        original = create_rx(patient["id"], prescription_payload)
        successor = do_regimen_change(
            original["id"],
            original["version"],
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
        )
        validate_error(
            api_client.regimen_change(
                original["id"],
                regimen_change_payload(
                    original["version"],
                    new_drug_name="Glipizide",
                    new_dose_times=["MORNING"],
                ),
                prescriber_headers(),
            ),
            ApiErrorId.STALE_PRESCRIPTION_VERSION,
        )

        assert_total_count(
            api_client.list_prescriptions(
                ops_headers(), {"patient_id": patient["id"], "limit": 100}
            ),
            2,
        )
        chain = assert_total_count(
            api_client.list_prescriptions(
                ops_headers(), {"supersedes_rx_id": original["id"], "limit": 100}
            ),
            1,
        )
        assert chain[0]["id"] == successor["id"], chain


class TestVersionMovementIsExact:
    """Each write moves its own parent by one, leaves siblings alone and reads move nothing."""

    def test_each_write_increments_only_the_row_it_owns(self):
        """Adjudicate, generate-roll and an auto-ship pause each bump one row by exactly one.

        `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, including mutations reached through a cascade from another endpoint. Every action increments the patient's `version`, plus the `version` of every cascaded cycle, line and memo.

        Design: Corner/cross_cutting_complexity_layers/every_write_bumps_the_version_of_the_row_it_owns_and_only_that_row
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient_a = create_patient(plan["id"], which=1)
        patient_b = create_patient(plan["id"], which=2)
        assert patient_a["version"] == 1, patient_a
        assert patient_b["version"] == 1, patient_b

        create_rx(patient_a["id"], metformin_payload)
        synced = do_synchronize(patient_a["id"], 15, "BRIDGE_TO_START")
        assert synced["version"] == 2, synced

        cycle = create_cycle(patient_a["id"], "2026-08-15", 28)
        assert cycle["version"] == 1, cycle

        adjudicated = do_adjudicate(cycle["id"])
        assert adjudicated["version"] == 2, adjudicated

        do_generate_roll(cycle["id"], TECHNICIAN_ID)
        after_roll = read_cycle(cycle["id"])
        assert after_roll["version"] == 3, after_roll
        assert after_roll["packaging_status"] == "ROLL_GENERATED", after_roll

        before_pause = read_patient(patient_a["id"])
        paused = do_autoship(patient_a["id"], "PAUSE", as_patient=True)
        assert paused["version"] == before_pause["version"] + 1, paused
        assert_patient_posture(
            paused, autoship_status="PAUSED_PATIENT", pause_reason="PATIENT_REQUEST"
        )

        assert read_patient(patient_b["id"])["version"] == 1
        assert read_cycle(cycle["id"])["packaging_status"] == "ROLL_GENERATED"

    def test_reads_never_increment_a_version(self):
        """Two consecutive reads of the same fill cycle report the same version.

        `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, including mutations reached through a cascade from another endpoint.

        Design: Corner/cross_cutting_complexity_layers/every_write_bumps_the_version_of_the_row_it_owns_and_only_that_row
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient_a = create_patient(plan["id"], which=1)
        patient_b = create_patient(plan["id"], which=2)
        create_rx(patient_a["id"], metformin_payload)
        do_synchronize(patient_a["id"], 15, "BRIDGE_TO_START")
        cycle = create_cycle(patient_a["id"], "2026-08-15", 28)
        do_adjudicate(cycle["id"])
        do_generate_roll(cycle["id"], TECHNICIAN_ID)

        first = read_cycle(cycle["id"])
        second = read_cycle(cycle["id"])
        assert first["version"] == 3, first
        assert second["version"] == first["version"], second
        assert read_patient(patient_b["id"])["version"] == 1


class TestMissedPickupThresholdReArms:
    """The cumulative pickup gate is a counter that a resume zeroes and a fresh miss restarts."""

    @staticmethod
    def _cycle_with_two_grace_expired_parcels():
        """A three-route cycle whose cold and loose parcels are five days past delivery."""
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"], which=3)
        create_rx(patient["id"], insulin_payload)
        create_rx(
            patient["id"],
            lambda pid: albuterol_payload(
                pid, last_dispensed_date="2026-07-18", last_dispensed_days_supply=28
            ),
        )
        create_rx(patient["id"], metformin_payload)
        do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
        cycle = create_cycle(patient["id"], "2026-08-15", 28)
        do_adjudicate(cycle["id"])
        cold = do_stage_shipment(cycle["id"], cold_chain_shipment_payload())
        loose = do_stage_shipment(cycle["id"], loose_shipment_payload())
        do_dispatch(cold["id"])
        do_dispatch(loose["id"])
        set_clock("2026-08-16T10:00:00Z")
        do_deliver(cold["id"])
        do_deliver(loose["id"])
        set_clock("2026-08-21T10:00:00Z")
        return patient, cycle, cold, loose

    def test_two_swept_parcels_trip_the_counter_gate_at_exactly_two(self):
        """The first review sweeps both parcels, reaches 2 and pauses on the counter, not the score.

        It sweeps the patient's parcels for an expired pickup grace period: every shipment of the patient whose `status` is `DELIVERED` and whose `delivered_at` advanced by 5 days is at or before the clock becomes `PICKUP_MISSED`, and each such sweep appends an adherence event with `event_type` `PICKUP_MISSED` and `source` `SYSTEM_SCAN`. The patient's `consecutive_missed_pickups` rises by the number of parcels swept in this run. If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`. Otherwise, if `consecutive_missed_pickups` is greater than or equal to 2, `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `MISSED_PICKUPS`. When the two counts sum to zero, `adherence_score_pct` is 100.

        Design: Corner/cross_cutting_complexity_layers/missed_pickup_threshold_re_arms_after_a_resume
        """
        patient, cycle, cold, loose = self._cycle_with_two_grace_expired_parcels()

        reviewed = do_adherence_review(patient["id"])

        assert_patient_posture(
            reviewed,
            autoship_status="PAUSED_ADHERENCE",
            pause_reason="MISSED_PICKUPS",
            adherence_score_pct=100,
            consecutive_missed_pickups=2,
        )

        shipments = {row["id"]: row for row in read_shipments(cycle["id"])}
        assert shipments[cold["id"]]["status"] == "PICKUP_MISSED", shipments
        assert shipments[loose["id"]]["status"] == "PICKUP_MISSED", shipments

        assert_total_count(
            api_client.list_adherence_events(
                ops_headers(),
                {
                    "event_type": "PICKUP_MISSED",
                    "source": "SYSTEM_SCAN",
                    "limit": 100,
                },
            ),
            2,
        )

    def test_a_resume_zeroes_the_counter_and_the_next_miss_restarts_from_zero(self):
        """After the resume a third missed parcel leaves the counter at 1 and auto-ship ACTIVE.

        `RESUME` moves `autoship_status` from `PAUSED_ADHERENCE` or `PAUSED_PATIENT` back to `ACTIVE`, sets `pause_reason` to null and resets `consecutive_missed_pickups` to 0. Otherwise, if `consecutive_missed_pickups` is greater than or equal to 2, `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `MISSED_PICKUPS`.

        Design: Corner/cross_cutting_complexity_layers/missed_pickup_threshold_re_arms_after_a_resume
        """
        patient, cycle, _, _ = self._cycle_with_two_grace_expired_parcels()
        do_adherence_review(patient["id"])

        resumed = do_autoship(patient["id"], "RESUME")
        assert_patient_posture(
            resumed,
            autoship_status="ACTIVE",
            pause_reason=None,
            consecutive_missed_pickups=0,
        )

        roll = do_generate_roll(cycle["id"], TECHNICIAN_ID)
        do_pack(roll["id"], TECHNICIAN_ID)
        do_image_roll(roll["id"], 97, None, TECHNICIAN_ID_2)
        do_verify(roll["id"], PHARMACIST_ID)
        pouch_parcel = do_stage_shipment(cycle["id"], pouch_roll_shipment_payload())
        do_dispatch(pouch_parcel["id"])
        set_clock("2026-08-22T10:00:00Z")
        do_deliver(pouch_parcel["id"])
        set_clock("2026-08-27T10:00:00Z")

        third = do_adherence_review(patient["id"])

        assert_patient_posture(
            third,
            autoship_status="ACTIVE",
            pause_reason=None,
            consecutive_missed_pickups=1,
        )
        swept = {row["id"]: row for row in read_shipments(cycle["id"])}
        assert swept[pouch_parcel["id"]]["status"] == "PICKUP_MISSED", swept
