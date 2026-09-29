"""Error catalogue: which identifier each rejected request reports, and in which order."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    albuterol_payload,
    assert_cycle_state,
    assert_line_state,
    assert_patient_posture,
    assert_roll_state,
    assert_shipment_state,
    assert_total_count,
    atorvastatin_payload,
    authorization_response_payload,
    cold_chain_shipment_payload,
    create_rx,
    decide_vacation,
    do_regimen_change,
    do_stage_shipment,
    do_synchronize,
    create_cycle,
    fill_cycle_payload,
    get_success_data,
    insulin_payload,
    line_by_prescription,
    loose_shipment_payload,
    metformin_payload,
    open_authorization,
    ops_headers,
    patient_headers,
    pharmacist_headers,
    pouch_roll_shipment_payload,
    prescriber_headers,
    read_cycle,
    read_lines,
    read_patient,
    read_prescription,
    read_roll,
    read_shipments,
    regimen_change_payload,
    reissue_payload,
    rivaroxaban_payload,
    setup_adjudicated_cycle,
    setup_rolled_cycle,
    setup_synced_patient,
    setup_verified_cycle,
    shipment_payload,
    sitagliptin_payload,
    synchronize_payload,
    technician_headers,
    vacation_decision_payload,
    vacation_exception_payload,
    validate_error,
)


class TestDetailReadNotFoundIdentifiers:
    """Each addressed entity reports its own not-found identifier."""

    def test_each_entity_detail_read_reports_its_own_not_found_identifier(self):
        """Twelve detail reads against an empty store each report the not-found identifier naming the addressed entity.

        Every endpoint addressed by a path identifier: no row of the addressed entity has that identifier. The error chosen is the one naming the addressed entity.
        Two ordering consequences deserve emphasis. First, existence (priorities 4 and 5) precedes patient scoping (priority 6): a patient addressing a nonexistent row gets the not-found error, not a scope violation.

        Design: Corner/errors/every_entity_detail_read_has_its_own_not_found_error_id
        """
        probes = [
            (api_client.get_insurance_plan, "aaaaaaaa-0000-4000-8000-000000000001",
             ApiErrorId.INSURANCE_PLAN_NOT_FOUND),
            (api_client.get_patient, "aaaaaaaa-0000-4000-8000-000000000002",
             ApiErrorId.PATIENT_NOT_FOUND),
            (api_client.get_prescription, "aaaaaaaa-0000-4000-8000-000000000003",
             ApiErrorId.PRESCRIPTION_NOT_FOUND),
            (api_client.get_fill_cycle, "aaaaaaaa-0000-4000-8000-000000000004",
             ApiErrorId.FILL_CYCLE_NOT_FOUND),
            (api_client.get_cycle_line, "aaaaaaaa-0000-4000-8000-000000000005",
             ApiErrorId.CYCLE_LINE_NOT_FOUND),
            (api_client.get_pouch_roll, "aaaaaaaa-0000-4000-8000-000000000006",
             ApiErrorId.POUCH_ROLL_NOT_FOUND),
            (api_client.get_pouch, "aaaaaaaa-0000-4000-8000-000000000007",
             ApiErrorId.POUCH_NOT_FOUND),
            (api_client.get_shipment, "aaaaaaaa-0000-4000-8000-000000000008",
             ApiErrorId.SHIPMENT_NOT_FOUND),
            (api_client.get_refill_authorization, "aaaaaaaa-0000-4000-8000-000000000009",
             ApiErrorId.REFILL_AUTHORIZATION_NOT_FOUND),
            (api_client.get_vacation_exception, "aaaaaaaa-0000-4000-8000-00000000000a",
             ApiErrorId.VACATION_EXCEPTION_NOT_FOUND),
            (api_client.get_credit_memo, "aaaaaaaa-0000-4000-8000-00000000000b",
             ApiErrorId.CREDIT_MEMO_NOT_FOUND),
            (api_client.get_adherence_event, "aaaaaaaa-0000-4000-8000-00000000000c",
             ApiErrorId.ADHERENCE_EVENT_NOT_FOUND),
        ]

        reported = []
        for read, identifier, expected_error_id in probes:
            response = read(identifier, ops_headers())
            validate_error(response, expected_error_id)
            reported.append(response.json()["data"]["error_id"])

        assert len(reported) == 12
        assert len(set(reported)) == 12


class TestCycleCreationEntryGates:
    """The gates guarding the opening of a fill cycle."""

    def test_cycle_creation_for_an_unsynchronized_patient_is_rejected(self):
        """A patient who was never synchronized cannot have a cycle opened, and the identical request succeeds once synchronized.

        The new patient starts deliberately inert: `sync_status` is `UNSYNCED`, `anchor_fill_day`, `sync_mode` and `next_cycle_start_date` are all null, `autoship_status` is `ACTIVE`, `pause_reason` is null, `adherence_score_pct` is 100, `consecutive_missed_pickups` is 0, `credit_balance_cents` is 0, `vacation_exceptions_used_this_year` is 0, and `version` is 1. Because `sync_status` is `UNSYNCED`, no fill cycle can yet be opened for this patient.
        Four gates are checked in this order, and the first one that holds returns. The patient's `sync_status` must be `SYNCED`, otherwise `ERR_PATIENT_NOT_SYNCHRONIZED`.

        Design: Corner/errors/cycle_creation_for_an_unsynchronized_patient_rejected
        """
        scenario = setup_synced_patient(synchronize=False)
        patient_id = scenario.patient_id

        unsynced = read_patient(patient_id)
        assert unsynced["sync_status"] == "UNSYNCED"
        assert unsynced["anchor_fill_day"] is None
        assert unsynced["sync_mode"] is None

        rejected = api_client.create_fill_cycle(
            fill_cycle_payload(patient_id, cycle_start_date="2026-08-15", day_supply_days=28),
            ops_headers(),
        )
        validate_error(rejected, ApiErrorId.PATIENT_NOT_SYNCHRONIZED)
        assert_total_count(
            api_client.list_fill_cycles(ops_headers(), {"patient_id": patient_id}), 0
        )

        do_synchronize(patient_id, anchor_fill_day=15, sync_mode="BRIDGE_TO_START")
        cycle = create_cycle(patient_id, cycle_start_date="2026-08-15", day_supply_days=28)
        assert_cycle_state(cycle, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED")

    def test_synchronizing_a_patient_without_any_active_prescription_is_rejected(self):
        """Synchronization of a patient carrying no prescription at all reports the missing active prescriptions.

        Synchronization requires the patient's `autoship_status` to be `ACTIVE` or `PAUSED_PATIENT`, and requires at least one prescription of the patient to survive the expiry sweep described next; if none does, the request fails with `ERR_NO_ACTIVE_PRESCRIPTIONS`.

        Design: Corner/errors/cycle_creation_for_an_unsynchronized_patient_rejected
        """
        scenario = setup_synced_patient(prescriptions=[], synchronize=False)
        patient_id = scenario.patient_id

        rejected = api_client.synchronize_patient(
            patient_id, synchronize_payload(15, "BRIDGE_TO_START"), ops_headers()
        )
        validate_error(rejected, ApiErrorId.NO_ACTIVE_PRESCRIPTIONS)
        assert read_patient(patient_id)["sync_status"] == "UNSYNCED"


class TestRollGenerationGateOrder:
    """Which payer condition roll generation reports first."""

    def test_open_authorization_edits_block_roll_generation_as_not_cleared(self):
        """A cycle holding a line for missing refills reports the uncleared payer edits rather than any later gate.

        Otherwise it becomes `HELD_AUTH` with `hold_reason` `NO_REFILLS_REMAINING` when the prescription's `refills_remaining` is zero, and that prescription simultaneously moves from `status` `ACTIVE` to `PENDING_AUTHORIZATION` with its `version` incremented.
        The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the segment the new roll would occupy must not collide with a live roll of the same patient under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then, if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with `ERR_REFILL_TOO_SOON`.

        Design: Corner/errors/roll_generation_blocked_by_open_edits_then_by_the_refill_edit
        """
        scenario = setup_adjudicated_cycle(
            prescriptions=[
                metformin_payload,
                lambda patient_id: sitagliptin_payload(patient_id, refills_authorized=0),
            ]
        )
        cycle_id = scenario.cycle_id
        assert_cycle_state(
            read_cycle(cycle_id),
            packaging_status="LINES_ADJUDICATED",
            insurance_status="EDITS_PENDING",
        )

        rejected = api_client.generate_roll(cycle_id, technician_headers("tech-01"))
        validate_error(rejected, ApiErrorId.CYCLE_NOT_CLEARED)

        assert_total_count(
            api_client.list_pouch_rolls(ops_headers(), {"cycle_id": cycle_id}), 0
        )
        cycle = read_cycle(cycle_id)
        assert_cycle_state(cycle, packaging_status="LINES_ADJUDICATED")
        assert cycle["roll_pouch_count"] == 0

        pouch_line = line_by_prescription(read_lines(cycle_id), scenario.rx_id(0))
        assert_line_state(pouch_line, line_status="ADJUDICATED", packable_route="POUCH")

    def test_a_payer_refill_rejection_blocks_roll_generation_as_too_soon(self):
        """A cycle holding a line rejected as too soon reports the payer refill rejection once every earlier gate passes.

        A line that fails the edit becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON`.
        The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the segment the new roll would occupy must not collide with a live roll of the same patient under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then, if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with `ERR_REFILL_TOO_SOON`.

        Design: Corner/errors/roll_generation_blocked_by_open_edits_then_by_the_refill_edit
        """
        scenario = setup_adjudicated_cycle(
            prescriptions=[
                metformin_payload,
                lambda patient_id: rivaroxaban_payload(
                    patient_id,
                    last_dispensed_date="2026-08-04",
                    last_dispensed_days_supply=30,
                ),
            ]
        )
        cycle_id = scenario.cycle_id
        assert_cycle_state(
            read_cycle(cycle_id),
            packaging_status="LINES_ADJUDICATED",
            insurance_status="REJECTED_TOO_SOON",
        )

        rejected = api_client.generate_roll(cycle_id, technician_headers("tech-01"))
        validate_error(rejected, ApiErrorId.REFILL_TOO_SOON)

        assert_total_count(
            api_client.list_pouch_rolls(ops_headers(), {"cycle_id": cycle_id}), 0
        )
        cycle = read_cycle(cycle_id)
        assert_cycle_state(cycle, packaging_status="LINES_ADJUDICATED")
        assert cycle["roll_pouch_count"] == 0

        pouch_line = line_by_prescription(read_lines(cycle_id), scenario.rx_id(0))
        assert_line_state(pouch_line, line_status="ADJUDICATED", packable_route="POUCH")

    def test_roll_generation_on_a_cold_chain_only_cycle_reports_no_packable_lines(self):
        """A cycle whose only line is refrigerated has nothing to pouch, so roll generation reports the absent packable lines.

        Each line's `packable_route` is determined by the prescription: `COLD_CHAIN` when `refrigerated` is true, `POUCH` when `refrigerated` is false and `packable` is true, and `LOOSE_SPLIT` otherwise — that is, a non-refrigerated item whose `form` is not `TABLET` or `CAPSULE`. Refrigerated items never enter a pouch roll under any circumstance.
        That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the segment the new roll would occupy must not collide with a live roll of the same patient under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then, if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with `ERR_REFILL_TOO_SOON`. Because the refill-too-soon block sits last in that order, a cold-chain-only cycle that was also rejected as too soon reports the absence of packable lines rather than the payer rejection.

        Design: Corner/errors/roll_generation_on_a_cold_only_cycle_rejected
        """
        scenario = setup_adjudicated_cycle(prescriptions=[insulin_payload])
        cycle_id = scenario.cycle_id
        adjudicated = read_cycle(cycle_id)
        assert_cycle_state(
            adjudicated, packaging_status="LINES_ADJUDICATED", insurance_status="CLEARED"
        )
        assert adjudicated["total_copay_cents"] == 986
        version_before = adjudicated["version"]

        cold_line = line_by_prescription(read_lines(cycle_id), scenario.rx_id(0))
        assert_line_state(cold_line, line_status="ADJUDICATED", packable_route="COLD_CHAIN")

        rejected = api_client.generate_roll(cycle_id, technician_headers("tech-01"))
        validate_error(rejected, ApiErrorId.NO_PACKABLE_LINES)

        cycle = read_cycle(cycle_id)
        assert_cycle_state(cycle, packaging_status="LINES_ADJUDICATED", version=version_before)
        assert cycle["roll_pouch_count"] == 0
        assert_total_count(
            api_client.list_pouch_rolls(ops_headers(), {"cycle_id": cycle_id}), 0
        )


class TestShipmentStagingGates:
    """The packaging pairing and the kind-to-line mapping at staging."""

    def test_cold_chain_packaging_pairing_is_rejected_in_both_directions(self):
        """A cold parcel in standard packaging and a loose parcel in gel packaging are both rejected, and no parcel is created.

        `packaging` must suit the kind, otherwise `ERR_COLD_CHAIN_PACKAGING_INVALID`: a `COLD_CHAIN` parcel may not use `STANDARD` packaging, and a parcel of any other kind may not use `INSULATED_GEL` or `INSULATED_DRY_ICE`.
        Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/errors/cold_chain_packaging_pairing_rejects_both_directions
        """
        scenario = setup_adjudicated_cycle(prescriptions=[insulin_payload, albuterol_payload])
        cycle_id = scenario.cycle_id
        version_before = read_cycle(cycle_id)["version"]

        cold_in_standard = api_client.stage_shipment(
            cycle_id,
            shipment_payload("COLD_CHAIN", carrier_service="OVERNIGHT", packaging="STANDARD"),
            ops_headers(),
        )
        validate_error(cold_in_standard, ApiErrorId.COLD_CHAIN_PACKAGING_INVALID)

        loose_in_gel = api_client.stage_shipment(
            cycle_id,
            shipment_payload(
                "NON_PACKABLE_LOOSE", carrier_service="TWO_DAY", packaging="INSULATED_GEL"
            ),
            ops_headers(),
        )
        validate_error(loose_in_gel, ApiErrorId.COLD_CHAIN_PACKAGING_INVALID)

        assert_total_count(api_client.list_shipments(ops_headers(), {"cycle_id": cycle_id}), 0)
        assert_cycle_state(read_cycle(cycle_id), version=version_before)

    def test_swapping_the_packaging_makes_both_parcels_stageable(self):
        """With the packaging swapped, the cold parcel and the loose parcel both stage at their component freight.

        `packaging` must suit the kind, otherwise `ERR_COLD_CHAIN_PACKAGING_INVALID`: a `COLD_CHAIN` parcel may not use `STANDARD` packaging, and a parcel of any other kind may not use `INSULATED_GEL` or `INSULATED_DRY_ICE`.
        The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`.

        Design: Corner/errors/cold_chain_packaging_pairing_rejects_both_directions
        """
        scenario = setup_adjudicated_cycle(prescriptions=[insulin_payload, albuterol_payload])
        cycle_id = scenario.cycle_id

        cold = do_stage_shipment(cycle_id, cold_chain_shipment_payload())
        assert_shipment_state(cold, status="STAGED", ship_cost_cents=3445)

        loose = do_stage_shipment(cycle_id, loose_shipment_payload())
        assert_shipment_state(loose, status="STAGED", ship_cost_cents=1095)

        assert_total_count(api_client.list_shipments(ops_headers(), {"cycle_id": cycle_id}), 2)

    def test_staging_a_cold_or_loose_parcel_on_a_pouch_only_cycle_is_rejected(self):
        """A cycle whose only line is pouch-routed has no cold or loose freight, so both parcels report the missing lines for that kind.

        The cycle must actually have freight of that kind and must not already have such a parcel in flight, otherwise `ERR_NO_LINES_FOR_SHIPMENT_KIND`. At least one line with `line_status` `ADJUDICATED` or `PACKED_OUT` must map to the requested kind — `POUCH_ROLL` requires a line whose `packable_route` is `POUCH`, `COLD_CHAIN` requires a `COLD_CHAIN` line, `NON_PACKABLE_LOOSE` requires a `LOOSE_SPLIT` line — and no shipment of that kind may already exist for the cycle with a `status` other than `CANCELLED` or `EXCEPTION_RETURNED`.
        Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/errors/staging_a_cold_parcel_on_a_pouch_only_cycle_rejected
        """
        scenario = setup_adjudicated_cycle()
        cycle_id = scenario.cycle_id
        version_before = read_cycle(cycle_id)["version"]

        pouch_line = line_by_prescription(read_lines(cycle_id), scenario.rx_id(0))
        assert_line_state(pouch_line, line_status="ADJUDICATED", packable_route="POUCH")

        no_cold_freight = api_client.stage_shipment(
            cycle_id,
            shipment_payload("COLD_CHAIN", carrier_service="OVERNIGHT", packaging="INSULATED_GEL"),
            ops_headers(),
        )
        validate_error(no_cold_freight, ApiErrorId.NO_LINES_FOR_SHIPMENT_KIND)

        no_loose_freight = api_client.stage_shipment(
            cycle_id,
            shipment_payload("NON_PACKABLE_LOOSE", carrier_service="TWO_DAY", packaging="STANDARD"),
            ops_headers(),
        )
        validate_error(no_loose_freight, ApiErrorId.NO_LINES_FOR_SHIPMENT_KIND)

        assert_total_count(api_client.list_shipments(ops_headers(), {"cycle_id": cycle_id}), 0)
        assert_cycle_state(read_cycle(cycle_id), version=version_before)


class TestRegimenChangeStateGate:
    """A prescription may only be superseded once."""

    def test_regimen_change_on_an_already_superseded_prescription_is_rejected(self):
        """A second regimen change on the superseded prescription reports the prescription state even though the expected version matches.

        The stale-version check comes first: if `expected_prescription_version` does not equal the prescription's current `version`, the request fails with `ERR_STALE_PRESCRIPTION_VERSION`. Only then is state checked: the prescription's `status` must be `ACTIVE`, otherwise `ERR_INVALID_PRESCRIPTION_STATE`.
        The addressed prescription moves from `ACTIVE` to the terminal `SUPERSEDED`, and a successor prescription is created with `status` `ACTIVE` and `supersedes_rx_id` pointing at the addressed prescription's `id`.

        Design: Corner/errors/regimen_change_on_a_superseded_prescription_rejected
        """
        scenario = setup_synced_patient(synchronize=False)
        patient_id = scenario.patient_id
        original_id = scenario.rx_id(0)

        successor = do_regimen_change(
            original_id,
            1,
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
            new_strength="1000mg",
        )
        assert successor["supersedes_rx_id"] == original_id

        superseded = read_prescription(original_id)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == 2

        rejected = api_client.regimen_change(
            original_id,
            regimen_change_payload(2, new_drug_name="Glipizide", new_dose_times=["MORNING"]),
            prescriber_headers(),
        )
        validate_error(rejected, ApiErrorId.INVALID_PRESCRIPTION_STATE)
        assert_total_count(
            api_client.list_prescriptions(ops_headers(), {"patient_id": patient_id}), 2
        )

        third = do_regimen_change(
            successor["id"],
            1,
            new_drug_name="Glipizide",
            new_dose_times=["MORNING"],
        )
        assert third["supersedes_rx_id"] == successor["id"]
        assert third["status"] == "ACTIVE"
        assert_total_count(
            api_client.list_prescriptions(ops_headers(), {"patient_id": patient_id}), 3
        )


class TestApprovedDaysValidation:
    """The approving payload the travel-exception decision refuses."""

    @pytest.mark.parametrize(
        "decision,approved_extra_days,denial_reason",
        [
            ("APPROVE_PHARMACIST", 9, None),
            ("APPROVE_PHARMACIST", 0, None),
            ("APPROVE_PHARMACIST", None, None),
            ("DENY", None, None),
        ],
    )
    def test_decision_payload_outside_the_request_is_rejected(
        self, decision, approved_extra_days, denial_reason
    ):
        """Approving more days than were requested, approving zero days, approving with no figure at all and denying with no reason are all refused.

        If the decision is either approving kind and `approved_extra_days` is absent, below 1 or greater than `requested_extra_days`, or if the decision is `DENY` and `denial_reason` is absent, the decision fails with `ERR_INVALID_APPROVED_DAYS`.
        The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.
        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.

        Design: Corner/errors/approved_extra_days_above_the_request_rejected
        """
        scenario = setup_synced_patient(
            plan_overrides={"vacation_overrides_per_year": 1}, synchronize=False
        )
        patient_id = scenario.patient_id
        request = get_success_data(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    patient_id,
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                patient_headers(patient_id),
            ),
            201,
        )
        assert request["status"] == "SUBMITTED"
        assert request["requested_extra_days"] == 5

        rejected = api_client.decide_vacation_exception(
            request["id"],
            vacation_decision_payload(
                decision, approved_extra_days=approved_extra_days, denial_reason=denial_reason
            ),
            pharmacist_headers("rph-01"),
        )
        validate_error(rejected, ApiErrorId.INVALID_APPROVED_DAYS)

        unchanged = get_success_data(
            api_client.get_vacation_exception(request["id"], ops_headers())
        )
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["approved_extra_days"] is None
        assert unchanged["version"] == 1
        assert read_patient(patient_id)["vacation_exceptions_used_this_year"] == 0

    def test_approving_fewer_days_than_requested_succeeds(self):
        """Approving three of the five requested days is accepted and consumes the yearly allowance.

        If the decision is either approving kind and `approved_extra_days` is absent, below 1 or greater than `requested_extra_days`, or if the decision is `DENY` and `denial_reason` is absent, the decision fails with `ERR_INVALID_APPROVED_DAYS`.
        `APPROVE_PHARMACIST` sets `status` `PHARMACIST_APPROVED`, stores `approved_extra_days` and leaves `waives_refill_too_soon` false: the exception extends the day-supply allowance but does **not** waive the payer's refill-too-soon edit.
        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.

        Design: Corner/errors/approved_extra_days_above_the_request_rejected
        """
        scenario = setup_synced_patient(
            plan_overrides={"vacation_overrides_per_year": 1}, synchronize=False
        )
        patient_id = scenario.patient_id
        request = get_success_data(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    patient_id,
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                patient_headers(patient_id),
            ),
            201,
        )

        decided = decide_vacation(request["id"], "APPROVE_PHARMACIST", approved_extra_days=3)
        assert decided["status"] == "PHARMACIST_APPROVED"
        assert decided["approved_extra_days"] == 3
        assert decided["waives_refill_too_soon"] is False
        assert read_patient(patient_id)["vacation_exceptions_used_this_year"] == 1

    def test_approving_more_refills_than_the_chase_requested_is_rejected(self):
        """A prescriber approving four refills against a request for three is refused by the same identifier.

        On an approving decision, `approved_refills` must be present, at least 1, at most 12 and no greater than `requested_refills`; on a denying decision `denial_reason` must be present. A violation of either is `ERR_INVALID_APPROVED_DAYS`.
        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.

        Design: Corner/errors/approved_extra_days_above_the_request_rejected
        """
        scenario = setup_synced_patient(synchronize=False)
        authorization = open_authorization(scenario.rx_id(0), requested_refills=3)
        assert authorization["status"] == "SENT"
        assert authorization["requested_refills"] == 3

        rejected = api_client.respond_refill_authorization(
            authorization["id"],
            authorization_response_payload("APPROVE", approved_refills=4),
            prescriber_headers(),
        )
        validate_error(rejected, ApiErrorId.INVALID_APPROVED_DAYS)

        unchanged = get_success_data(
            api_client.get_refill_authorization(authorization["id"], ops_headers())
        )
        assert unchanged["status"] == "SENT"
        assert unchanged["approved_refills"] is None
        assert unchanged["version"] == 1


class TestDispatchGateOrder:
    """Which dispatch gate speaks first when the parcel is cancelled and the roll intact."""

    def test_cancelled_pouch_parcel_reports_the_parcel_state_not_the_roll_guard(self):
        """Dispatching the parcel that a regimen change cancelled reports the parcel state, even though the roll guard would also have something to say.

        The shipment's `status` must be `STAGED`, otherwise `ERR_INVALID_SHIPMENT_STATE`. When `shipment_kind` is `POUCH_ROLL`, the cycle's pouch roll must have `verification_status` `PASSED`, otherwise `ERR_ROLL_NOT_VERIFIED`.
        Because the cycle reverted, every shipment of that cycle whose `status` is `STAGED` and whose `shipment_kind` is `POUCH_ROLL` becomes `CANCELLED`; cold-chain and loose parcels are untouched, since they never carried the changed drug's pouches.
        When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`.

        Design: Corner/errors/pouch_dispatch_roll_guard_is_shadowed_by_the_parcel_state_check
        """
        scenario = setup_verified_cycle()
        cycle_id = scenario.cycle_id
        parcel = do_stage_shipment(cycle_id, pouch_roll_shipment_payload())
        assert_shipment_state(parcel, status="STAGED")

        original_id = scenario.rx_id(0)
        do_regimen_change(
            original_id,
            read_prescription(original_id)["version"],
            new_drug_name="Metformin ER",
            new_dose_times=["MORNING", "EVENING"],
            new_strength="1000mg",
        )

        cycle = read_cycle(cycle_id)
        assert_cycle_state(cycle, packaging_status="ROLL_GENERATED")
        assert cycle["reissue_required"] is True
        cancelled = read_shipments(cycle_id)[0]
        assert_shipment_state(cancelled, status="CANCELLED")
        assert_roll_state(read_roll(scenario.roll_id), verification_status="PASSED")

        rejected = api_client.dispatch_shipment(parcel["id"], ops_headers())
        validate_error(rejected, ApiErrorId.INVALID_SHIPMENT_STATE)

        after = get_success_data(api_client.get_shipment(parcel["id"], ops_headers()))
        assert_shipment_state(after, status="CANCELLED")
        assert after["dispatched_at"] is None
        assert after["tracking_number"] is None
        assert_roll_state(read_roll(scenario.roll_id), verification_status="PASSED")


class TestVacationDecisionIsOnce:
    """A decided travel exception is terminal."""

    def test_deciding_an_already_approved_travel_request_is_rejected(self):
        """Re-approving and then denying an approved travel exception both report the vacation state rather than any payload complaint.

        Deciding is exclusive to `VerifyingPharmacist` and may happen exactly once: `status` must be `SUBMITTED`, otherwise `ERR_INVALID_VACATION_STATE`.
        `APPROVE_PHARMACIST` sets `status` `PHARMACIST_APPROVED`, stores `approved_extra_days` and leaves `waives_refill_too_soon` false: the exception extends the day-supply allowance but does **not** waive the payer's refill-too-soon edit.
        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.
        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.

        Design: Corner/errors/deciding_an_already_approved_travel_request_rejected
        """
        scenario = setup_synced_patient(
            plan_overrides={"vacation_overrides_per_year": 1}, synchronize=False
        )
        patient_id = scenario.patient_id
        request = get_success_data(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    patient_id,
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                patient_headers(patient_id),
            ),
            201,
        )

        decided = decide_vacation(request["id"], "APPROVE_PHARMACIST", approved_extra_days=3)
        assert decided["status"] == "PHARMACIST_APPROVED"
        assert decided["approved_extra_days"] == 3
        assert read_patient(patient_id)["vacation_exceptions_used_this_year"] == 1

        re_approved = api_client.decide_vacation_exception(
            request["id"],
            vacation_decision_payload("APPROVE_PHARMACIST", approved_extra_days=5),
            pharmacist_headers("rph-01"),
        )
        validate_error(re_approved, ApiErrorId.INVALID_VACATION_STATE)

        denied = api_client.decide_vacation_exception(
            request["id"],
            vacation_decision_payload("DENY", denial_reason="Trip cancelled"),
            pharmacist_headers("rph-01"),
        )
        validate_error(denied, ApiErrorId.INVALID_VACATION_STATE)

        unchanged = get_success_data(
            api_client.get_vacation_exception(request["id"], ops_headers())
        )
        assert unchanged["status"] == "PHARMACIST_APPROVED"
        assert unchanged["approved_extra_days"] == 3
        assert read_patient(patient_id)["vacation_exceptions_used_this_year"] == 1


class TestReissueHasSomethingToReissue:
    """The last reissue gate, reached with every earlier one satisfied."""

    def test_reissue_naming_a_prescription_with_no_line_is_rejected(self):
        """A reissue naming a prescription the cycle never filled has nothing to reissue, and neither credit nor successor cycle appears.

        Its gates are evaluated in this order: the stale-version check on `expected_cycle_version`, otherwise `ERR_STALE_CYCLE_VERSION`; the patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED`; the cycle's `packaging_status` must be `ROLL_GENERATED`, `PACKED` or `VERIFIED`, otherwise `ERR_INVALID_CYCLE_STATE`; `effective_date` must be strictly after the cycle's `cycle_start_date` and strictly before its `cycle_end_date`, otherwise `ERR_REISSUE_DATE_OUT_OF_WINDOW`; and the cycle must have something to reissue — at least one line with `line_status` `SUPERSEDED_PENDING_REISSUE`, or at least one `ADJUDICATED` line whose prescription is named in `replacement_prescription_ids` — otherwise `ERR_NOTHING_TO_REISSUE`.
        That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`.
        Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/errors/reissue_of_a_cycle_with_nothing_superseded_rejected
        """
        scenario = setup_rolled_cycle()
        cycle_id = scenario.cycle_id
        patient_id = scenario.patient_id

        unrelated = create_rx(patient_id, atorvastatin_payload)

        before = read_cycle(cycle_id)
        assert_cycle_state(before, packaging_status="ROLL_GENERATED")
        assert before["reissue_required"] is False
        assert before["total_copay_cents"] == 762

        rejected = api_client.reissue_fill_cycle(
            cycle_id,
            reissue_payload("2026-08-25", [unrelated["id"]], before["version"]),
            ops_headers(),
        )
        validate_error(rejected, ApiErrorId.NOTHING_TO_REISSUE)

        assert_total_count(api_client.list_credit_memos(ops_headers(), {"patient_id": patient_id}), 0)
        assert_patient_posture(read_patient(patient_id), credit_balance_cents=0)
        assert_total_count(
            api_client.list_fill_cycles(ops_headers(), {"patient_id": patient_id}), 1
        )

        after = read_cycle(cycle_id)
        assert_cycle_state(after, packaging_status="ROLL_GENERATED", version=before["version"])
        assert after["total_copay_cents"] == 762
        assert after["reissue_fee_cents"] == 0
        assert after["reissue_required"] is False
