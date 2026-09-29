"""Endpoint behaviour: writes, computed reads and the filtered collections."""

from test_helpers import (
    ApiErrorId,
    api_client,
    albuterol_payload,
    assert_cycle_state,
    assert_line_state,
    assert_roll_state,
    assert_shipment_state,
    assert_total_count,
    cold_chain_shipment_payload,
    create_patient,
    create_plan,
    create_cycle,
    do_autoship,
    do_dose_events,
    do_generate_roll,
    do_image_pouch,
    do_image_roll,
    do_pack,
    do_regimen_change,
    do_stage_shipment,
    do_verify,
    dose_event,
    fill_cycle_payload,
    get_success_data,
    insulin_payload,
    line_by_prescription,
    metformin_payload,
    ops_headers,
    patient_headers,
    pouch_by_index,
    pouch_roll_shipment_payload,
    prescriber_headers,
    read_cycle,
    read_lines,
    read_patient,
    read_pouches,
    read_prescription,
    read_roll,
    set_clock,
    setup_adjudicated_cycle,
    setup_draft_cycle,
    setup_packed_cycle,
    setup_rolled_cycle,
    validate_error,
    validate_paginated,
)


class TestPrescriptionWritesAndReads:
    """Recording a prescription, reading it back and listing the patient's set."""

    def test_recorded_prescriptions_carry_the_computed_starting_field_values(self):
        """A recorded prescription is created with computed packable and the fixed starting counters.

        Read operations return HTTP 200. Write operations that bring a new resource into existence return HTTP 201 with that resource in `data`; write operations that only advance an existing resource return HTTP 200 with the updated resource in `data`.
        Optionally the caller supplies `refrigerated` (default false — true when the item must move through a cold chain and can never enter a pouch), `is_controlled` (default false — true for a scheduled controlled substance, which caps day supply and forbids travel early-supply overrides), and the prior-fill history `last_dispensed_date` (default null for a never-filled prescription) and `last_dispensed_days_supply` (default 0).
        The system computes `packable` and the caller may not supply it: `packable` is true exactly when `form` is `TABLET` or `CAPSULE` **and** `refrigerated` is false. The new prescription starts with `status` `ACTIVE`, `refills_remaining` equal to `refills_authorized`, `refills_consumed` 0, `days_dispensed_total` 0, `supersedes_rx_id` null, `prior_last_dispensed_date` null, `prior_last_dispensed_days_supply` 0, `sync_bridge_days` 0, `sync_trim_days` 0 and `version` 1.

        Design: Corner/endpoints/prescription_crud_create_read_and_filtered_list
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        patient_id = patient["id"]

        rx1 = get_success_data(
            api_client.create_prescription(metformin_payload(patient_id), prescriber_headers()),
            201,
        )
        rx2 = get_success_data(
            api_client.create_prescription(
                albuterol_payload(patient_id, refills_authorized=2), ops_headers()
            ),
            201,
        )

        assert rx1["status"] == "ACTIVE"
        assert rx1["refills_remaining"] == 3
        assert rx1["refills_consumed"] == 0
        assert rx1["days_dispensed_total"] == 0
        assert rx1["supersedes_rx_id"] is None
        assert rx1["version"] == 1
        assert rx1["packable"] is True

        assert rx2["status"] == "ACTIVE"
        assert rx2["refills_remaining"] == 2
        assert rx2["refills_consumed"] == 0
        assert rx2["days_dispensed_total"] == 0
        assert rx2["version"] == 1
        assert rx2["packable"] is False
        assert rx2["last_dispensed_date"] is None

        detail = get_success_data(
            api_client.get_prescription(rx1["id"], patient_headers(patient_id))
        )
        assert detail["id"] == rx1["id"]
        assert detail["drug_name"] == "Metformin ER"
        assert detail["last_dispensed_date"] == "2026-07-25"
        assert detail["last_dispensed_days_supply"] == 28
        assert detail["packable"] is True

    def test_prescription_list_filters_conjunctively_and_orders_by_creation(self):
        """The patient-and-status filter pair returns both active prescriptions oldest first, and a status matching nothing returns an empty page.

        List responses carry `limit`, `offset`, `total_count` and `has_more` in `meta`. `total_count` is the number of rows matching the filters *before* `limit` and `offset` are applied; `has_more` is true when the sum of `offset` and the number of returned rows is less than `total_count`.
        Unless a specific read says otherwise, rows are returned in ascending `created_at` order, with ascending `id` as a deterministic tie-break.
        Every filter parameter is optional; when several are supplied they combine conjunctively, and an unrecognised filter value simply matches nothing rather than erroring (an enum-typed filter carrying a value outside its declared set is a schema violation).

        Design: Corner/endpoints/prescription_crud_create_read_and_filtered_list
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient_id = create_patient(plan["id"])["id"]

        rx1 = get_success_data(
            api_client.create_prescription(metformin_payload(patient_id), prescriber_headers()),
            201,
        )
        rx2 = get_success_data(
            api_client.create_prescription(
                albuterol_payload(patient_id, refills_authorized=2), ops_headers()
            ),
            201,
        )

        active = api_client.list_prescriptions(
            ops_headers(),
            {"patient_id": patient_id, "status": "ACTIVE", "limit": 10, "offset": 0},
        )
        rows, meta = validate_paginated(active)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [rx1["id"], rx2["id"]]

        superseded = api_client.list_prescriptions(
            ops_headers(), {"patient_id": patient_id, "status": "SUPERSEDED"}
        )
        empty = assert_total_count(superseded, 0)
        assert empty == []


class TestPouchParcelStaging:
    """The pouch parcel waits for the bench while the cold parcel leaves early."""

    def test_pouch_parcel_is_refused_at_lines_adjudicated_while_the_cold_parcel_stages(self):
        """A pouch parcel cannot be staged before verification, but a cold-chain parcel can ship straight from the adjudicated cycle.

        The cycle's `packaging_status` must permit the requested kind, otherwise `ERR_INVALID_CYCLE_STATE`. A `POUCH_ROLL` parcel may be staged only when `packaging_status` is `VERIFIED` or `SHIPPED`, because the roll must have cleared the bench. A `COLD_CHAIN` or `NON_PACKABLE_LOOSE` parcel may be staged from `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED`, `VERIFIED` or `SHIPPED`, because a loose or cold-chain parcel leaves the building independently of the pouch bench and need not wait for verification.
        The new shipment starts with `status` `STAGED`, `staged_at` at the clock, `tracking_number` null, `dispatched_at`, `delivered_at` and `pickup_confirmed_at` null, `cold_chain_excursion_minutes` 0 and `version` 1. `covers_line_ids` holds the identifiers of the cycle's lines whose `packable_route` maps to this `shipment_kind` and whose `line_status` is `ADJUDICATED` or `PACKED_OUT`, ordered by ascending line `created_at`.
        The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`.

        Design: Corner/endpoints/pouch_parcel_is_only_stageable_once_the_roll_is_verified
        """
        scenario = setup_adjudicated_cycle(prescriptions=[metformin_payload, insulin_payload])
        cycle_id = scenario.cycle_id
        assert_cycle_state(read_cycle(cycle_id), packaging_status="LINES_ADJUDICATED")

        too_early = api_client.stage_shipment(
            cycle_id, pouch_roll_shipment_payload(), ops_headers()
        )
        validate_error(too_early, ApiErrorId.INVALID_CYCLE_STATE)

        cold = do_stage_shipment(cycle_id, cold_chain_shipment_payload())
        assert_shipment_state(cold, status="STAGED", ship_cost_cents=3445)
        assert cold["shipment_kind"] == "COLD_CHAIN"

        lines = read_lines(cycle_id)
        cold_line = line_by_prescription(lines, scenario.rx_named("Insulin glargine")["id"])
        assert_line_state(cold_line, packable_route="COLD_CHAIN")
        assert cold["covers_line_ids"] == [cold_line["id"]]

    def test_pouch_parcel_stages_once_the_roll_has_passed_verification(self):
        """After the roll passes verification the pouch parcel stages at zero freight, and a second pouch parcel is refused.

        A `POUCH_ROLL` parcel may be staged only when `packaging_status` is `VERIFIED` or `SHIPPED`, because the roll must have cleared the bench.
        When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`.
        The cycle must actually have freight of that kind and must not already have such a parcel in flight, otherwise `ERR_NO_LINES_FOR_SHIPMENT_KIND`. At least one line with `line_status` `ADJUDICATED` or `PACKED_OUT` must map to the requested kind — `POUCH_ROLL` requires a line whose `packable_route` is `POUCH`, `COLD_CHAIN` requires a `COLD_CHAIN` line, `NON_PACKABLE_LOOSE` requires a `LOOSE_SPLIT` line — and no shipment of that kind may already exist for the cycle with a `status` other than `CANCELLED` or `EXCEPTION_RETURNED`.
        The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`.

        Design: Corner/endpoints/pouch_parcel_is_only_stageable_once_the_roll_is_verified
        """
        scenario = setup_adjudicated_cycle(prescriptions=[metformin_payload, insulin_payload])
        cycle_id = scenario.cycle_id

        roll = do_generate_roll(cycle_id, "tech-01")
        do_pack(roll["id"], "tech-01")
        do_image_roll(roll["id"], 97, None, "tech-02")
        verified = do_verify(roll["id"], "rph-01")
        assert_roll_state(verified, verification_status="PASSED", mismatch_pouch_count=0)
        assert_cycle_state(read_cycle(cycle_id), packaging_status="VERIFIED")

        parcel = get_success_data(
            api_client.stage_shipment(cycle_id, pouch_roll_shipment_payload(), ops_headers()),
            201,
        )
        assert_shipment_state(parcel, status="STAGED", ship_cost_cents=0)
        pouch_line = line_by_prescription(read_lines(cycle_id), scenario.rx_id(0))
        assert_line_state(pouch_line, packable_route="POUCH")
        assert parcel["covers_line_ids"] == [pouch_line["id"]]

        duplicate = api_client.stage_shipment(
            cycle_id, pouch_roll_shipment_payload(), ops_headers()
        )
        validate_error(duplicate, ApiErrorId.NO_LINES_FOR_SHIPMENT_KIND)


class TestWholeRollImagingPass:
    """The bulk imaging pass and the pouch it must not touch."""

    def test_bulk_pass_skips_the_already_imaged_pouch_and_applies_its_override(self):
        """The whole-roll pass leaves the pouch imaged earlier exactly as it was, mismatches the overridden pouch and matches the rest.

        The pass walks every pouch of the roll whose `verification_result` is still `PENDING`, in ascending `pouch_index` order.
        If an element of `overrides` names that pouch's `pouch_index`, that element's `detected_pill_count` is used instead, and its `image_confidence_pct` replaces the body value for that pouch alone when supplied.
        Every pouch touched by the pass has `imaged_by_user_id` set to the caller's `X-User-ID` and `imaged_at` set to the clock; pouches that were already imaged are left completely untouched, including any override element naming them.
        Otherwise, if `detected_pill_count` equals `expected_pill_count`, `verification_result` becomes `MATCH`. Otherwise it becomes `MISMATCH_COUNT`.
        The roll's `mismatch_pouch_count` is then recomputed as the number of its pouches whose `verification_result` is `MISMATCH_COUNT` or `UNREADABLE`.
        The roll's `mismatch_pouch_count` is recomputed as before.

        Design: Corner/endpoints/whole_roll_imaging_pass_leaves_already_imaged_pouches_untouched
        """
        scenario = setup_packed_cycle(packer="tech-01")
        roll_id = scenario.roll_id

        first_pouch = pouch_by_index(read_pouches(roll_id), 1)
        imaged_first = do_image_pouch(first_pouch["id"], 1, 95, "tech-02")
        assert imaged_first["verification_result"] == "MATCH"
        assert imaged_first["image_confidence_pct"] == 95
        first_imaged_at = imaged_first["imaged_at"]

        set_clock("2026-08-10T02:00:00Z")
        do_image_roll(roll_id, 99, [{"pouch_index": 5, "detected_pill_count": 0}], "tech-02")

        pouches = read_pouches(roll_id)
        untouched = pouch_by_index(pouches, 1)
        assert untouched["verification_result"] == "MATCH"
        assert untouched["image_confidence_pct"] == 95
        assert untouched["detected_pill_count"] == 1
        assert untouched["imaged_at"] == first_imaged_at

        overridden = pouch_by_index(pouches, 5)
        assert overridden["verification_result"] == "MISMATCH_COUNT"
        assert overridden["detected_pill_count"] == 0
        assert overridden["image_confidence_pct"] == 99

        for index in (2, 3, 4, 6, 28):
            pouch = pouch_by_index(pouches, index)
            assert pouch["verification_result"] == "MATCH"
            assert pouch["detected_pill_count"] == pouch["expected_pill_count"]
            assert pouch["image_confidence_pct"] == 99
            assert pouch["imaged_at"] != first_imaged_at

        assert_roll_state(read_roll(roll_id), mismatch_pouch_count=1)
        still_pending = api_client.list_pouches(
            ops_headers(), {"roll_id": roll_id, "verification_result": "PENDING"}
        )
        assert_total_count(still_pending, 0)

        do_image_roll(roll_id, 99, [{"pouch_index": 5, "detected_pill_count": 0}], "tech-02")
        assert_roll_state(read_roll(roll_id), mismatch_pouch_count=1)
        assert pouch_by_index(read_pouches(roll_id), 1)["image_confidence_pct"] == 95
        assert pouch_by_index(read_pouches(roll_id), 1)["imaged_at"] == first_imaged_at


class TestRegimenChangeSuccessorLink:
    """The successor prescription and the cascade it drives onto the packed cycle."""

    def test_regimen_change_returns_the_successor_pointing_at_the_superseded_row(self):
        """The regimen change answers with the newly minted successor, which names the superseded prescription and carries its refill counters forward.

        The addressed prescription moves from `ACTIVE` to the terminal `SUPERSEDED`, and a successor prescription is created with `status` `ACTIVE` and `supersedes_rx_id` pointing at the addressed prescription's `id`. The successor takes `drug_name`, `form`, `copay_tier`, `dose_times` and `quantity_per_dose` from the `new_` fields, takes `ndc`, `strength` and `days_supply_written` from the corresponding `new_` fields when supplied and from the superseded prescription otherwise, carries `refills_remaining` and `refills_consumed` forward unchanged, and recomputes `packable` from `new_form` together with the inherited `refrigerated` flag. **The response body is the new successor prescription, not the superseded one.**
        Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1. The prescription's `version` increments.
        Prescriptions: `patient_id`, `supersedes_rx_id`, `status`. Filtering by `supersedes_rx_id` resolves the successor chain minted by regimen changes.

        Design: Corner/endpoints/regimen_change_links_the_successor_to_the_superseded_prescription
        """
        scenario = setup_packed_cycle(packer="tech-01")
        original_id = scenario.rx_id(0)
        # The absolute counter is read rather than asserted: the PRD names a version
        # increment for the expiry sweep and for the patient during synchronization but
        # not for the alignment projection, so the count reached here is not pinned.
        original_version = read_prescription(original_id)["version"]

        successor = do_regimen_change(
            original_id,
            original_version,
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
            new_strength="1000mg",
            new_ndc="00093-1050-01",
            new_days_supply_written=30,
            change_reason="Dose escalation for A1c control",
        )

        assert successor["id"] != original_id
        assert successor["supersedes_rx_id"] == original_id
        assert successor["status"] == "ACTIVE"
        assert successor["strength"] == "1000mg"
        assert successor["ndc"] == "00093-1050-01"
        assert successor["dose_times"] == ["MORNING", "EVENING"]
        assert successor["days_supply_written"] == 30
        assert successor["packable"] is True
        assert successor["version"] == 1
        assert successor["refills_remaining"] == 2
        assert successor["refills_consumed"] == 1

        superseded = read_prescription(original_id)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == original_version + 1
        assert superseded["supersedes_rx_id"] is None

        forward = api_client.list_prescriptions(
            ops_headers(), {"supersedes_rx_id": original_id}
        )
        rows = assert_total_count(forward, 1)
        assert rows[0]["id"] == successor["id"]

        backward = api_client.list_prescriptions(
            ops_headers(), {"supersedes_rx_id": successor["id"]}
        )
        assert_total_count(backward, 0)

    def test_regimen_change_holds_the_line_and_reverts_the_packed_cycle(self):
        """The superseded prescription's line goes on hold for reissue and the packed cycle falls back to roll generation.

        Because the prescription was superseded, every cycle line referencing it on a cycle whose `packaging_status` is `DRAFT`, `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED` or `VERIFIED` becomes `SUPERSEDED_PENDING_REISSUE` with `hold_reason` `REGIMEN_CHANGE`; lines on a cycle that has already reached `SHIPPED`, `CLOSED` or `CANCELLED` are left alone, because that medication has already left the building. Because at least one line was superseded, each affected cycle sets `reissue_required` to true, and a cycle whose `packaging_status` is `PACKED` or `VERIFIED` reverts to `ROLL_GENERATED` — the roll must be rebuilt, and a reverted roll is re-generated rather than re-verified.

        Design: Corner/endpoints/regimen_change_links_the_successor_to_the_superseded_prescription
        """
        scenario = setup_packed_cycle(packer="tech-01")
        original_id = scenario.rx_id(0)
        assert_cycle_state(read_cycle(scenario.cycle_id), packaging_status="PACKED")

        do_regimen_change(
            original_id,
            read_prescription(original_id)["version"],
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
            new_strength="1000mg",
            new_ndc="00093-1050-01",
            new_days_supply_written=30,
            change_reason="Dose escalation for A1c control",
        )

        held_line = line_by_prescription(read_lines(scenario.cycle_id), original_id)
        assert_line_state(
            held_line, line_status="SUPERSEDED_PENDING_REISSUE", hold_reason="REGIMEN_CHANGE"
        )

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(cycle, packaging_status="ROLL_GENERATED")
        assert cycle["reissue_required"] is True


class TestAdherenceSummaryRead:
    """The computed summary exposing both scores side by side."""

    def test_summary_reports_both_scores_and_changes_nothing(self):
        """The summary read returns the rolling and cycle-scoped scores together and leaves the patient untouched.

        The window is half-open: it begins at the clock moved back by 28 days, inclusive, and ends at the clock, exclusive.
        Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent.
        Its denominator is the number of pouches across the patient's rolls whose `dose_date` is strictly before the clock date and whose `verification_result` is not `VOID` — that is, every pouch whose dose date has already passed, whether or not the patient reported anything about it. When that count is zero the cycle-scoped score is 100; otherwise it is one hundred multiplied by the same taken count, divided by that expected count, floored to a whole percent.
        Only the rolling score is written to `adherence_score_pct` and only the rolling score can pause auto-ship.
        `taken_count` and `missed_count` are the two window counts, and `expected_pouch_count` is the cycle-scoped denominator. This read mutates nothing.

        Design: Corner/endpoints/adherence_summary_is_a_non_mutating_computed_read
        """
        scenario = setup_rolled_cycle()
        patient_id = scenario.patient_id
        set_clock("2026-08-25T00:00:00Z")

        events = [
            dose_event("POUCH_TAKEN", "2026-08-%02dT08:00:00Z" % (15 + offset), "MORNING", 1 + offset)
            for offset in range(8)
        ]
        events.append(dose_event("POUCH_MISSED", "2026-08-23T08:00:00Z", "MORNING", 9))
        do_dose_events(patient_id, scenario.cycle_id, events, as_patient=True)

        before = read_patient(patient_id)
        assert before["adherence_score_pct"] == 88
        assert before["autoship_status"] == "ACTIVE"

        summary = get_success_data(
            api_client.get_adherence_summary(patient_id, patient_headers(patient_id))
        )
        assert summary["patient_id"] == patient_id
        assert summary["rolling_28_day_score_pct"] == 88
        assert summary["rolling_28_day_score_pct"] == before["adherence_score_pct"]
        assert summary["cycle_scoped_score_pct"] == 80
        assert summary["expected_pouch_count"] == 10
        assert summary["taken_count"] == 8
        assert summary["missed_count"] == 1
        assert summary["consecutive_missed_pickups"] == 0
        assert summary["autoship_status"] == "ACTIVE"

        after = read_patient(patient_id)
        assert after["version"] == before["version"]
        assert after["autoship_status"] == "ACTIVE"
        assert after["pause_reason"] is None
        assert after["adherence_score_pct"] == 88

        repeated = get_success_data(
            api_client.get_adherence_summary(patient_id, patient_headers(patient_id))
        )
        assert repeated == summary


class TestAutoshipPosture:
    """Pausing auto-ship closes the cycle gate and resuming reopens it."""

    def test_pause_cancels_the_draft_cycle_and_blocks_creation_until_resume(self):
        """A patient pause cancels the draft cycle and blocks new ones, and the resume restores creation.

        `PAUSE` moves `autoship_status` from `ACTIVE` to `PAUSED_PATIENT` with `pause_reason` `PATIENT_REQUEST`, and every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`.
        `RESUME` moves `autoship_status` from `PAUSED_ADHERENCE` or `PAUSED_PATIENT` back to `ACTIVE`, sets `pause_reason` to null and resets `consecutive_missed_pickups` to 0.
        Every action increments the patient's `version`, plus the `version` of every cascaded cycle, line and memo.
        The patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED` — a paused or cancelled auto-ship blocks cycle creation outright. The new cycle's half-open window must not collide with any live cycle of the same patient, otherwise `ERR_CYCLE_WINDOW_OVERLAP`; only cycles whose `packaging_status` is neither `CANCELLED` nor `CLOSED` and whose `is_partial_reissue` is false participate in that test, so a partial-reissue child never blocks a later cycle and a closed or cancelled cycle never blocks anything.

        Design: Corner/endpoints/autoship_pause_blocks_new_cycles_and_resume_restores_them
        """
        scenario = setup_draft_cycle()
        patient_id = scenario.patient_id
        first_cycle_id = scenario.cycle_id
        version_before = read_patient(patient_id)["version"]

        paused = do_autoship(patient_id, "PAUSE", as_patient=True)
        assert paused["autoship_status"] == "PAUSED_PATIENT"
        assert paused["pause_reason"] == "PATIENT_REQUEST"
        assert paused["version"] == version_before + 1
        assert_cycle_state(read_cycle(first_cycle_id), packaging_status="CANCELLED")

        blocked = api_client.create_fill_cycle(
            fill_cycle_payload(patient_id, cycle_start_date="2026-08-15", day_supply_days=28),
            ops_headers(),
        )
        validate_error(blocked, ApiErrorId.AUTOSHIP_PAUSED)
        assert_total_count(
            api_client.list_fill_cycles(ops_headers(), {"patient_id": patient_id}), 1
        )

        resumed = do_autoship(patient_id, "RESUME")
        assert resumed["autoship_status"] == "ACTIVE"
        assert resumed["pause_reason"] is None
        assert resumed["consecutive_missed_pickups"] == 0
        assert resumed["version"] == version_before + 2

        second = create_cycle(patient_id, cycle_start_date="2026-08-15", day_supply_days=28)
        assert second["id"] != first_cycle_id
        assert_cycle_state(second, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED")
        assert_total_count(
            api_client.list_fill_cycles(ops_headers(), {"patient_id": patient_id}), 2
        )
