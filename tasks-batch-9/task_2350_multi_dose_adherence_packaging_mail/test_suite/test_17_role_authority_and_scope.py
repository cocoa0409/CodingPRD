"""Role authority, patient scoping and the identity-free clock setter.

Every request except the clock setter carries an identity header pair, and the
role in that pair decides which pharmacy step the caller may take. These tests
walk one fill through its five owning roles, then probe the refusals: another
role's exclusive operation, a read the bench may not perform, and a patient
reaching across the membership boundary.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from test_helpers import (
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    ApiErrorId,
    adjudicate_payload,
    admin_headers,
    api_client,
    assert_cycle_state,
    assert_envelope_shape,
    assert_patient_posture,
    assert_roll_state,
    assert_shipment_state,
    assert_total_count,
    authorization_response_payload,
    autoship_payload,
    create_cycle,
    deliver_payload,
    do_adjudicate,
    do_generate_roll,
    do_image_roll,
    do_pack,
    do_stage_shipment,
    do_verify,
    fill_cycle_payload,
    insurance_plan_payload,
    metformin_payload,
    ops_headers,
    patient_headers,
    patient_payload,
    pharmacist_headers,
    pouch_by_index,
    pouch_image_payload,
    pouch_roll_shipment_payload,
    prescriber_headers,
    read_cycle,
    read_patient,
    read_roll,
    refill_authorization_payload,
    regimen_change_payload,
    roll_images_payload,
    setup_packed_cycle,
    setup_rolled_cycle,
    setup_two_synced_patients,
    synchronize_payload,
    technician_headers,
    vacation_exception_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing ``Z`` and any precision."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestExclusiveOperations:
    """The positive half of the authority matrix: every step accepts its owner."""

    def test_one_fill_is_handed_off_through_every_owning_role(self):
        """One end-to-end fill accepts each step's owning role and reaches CLOSED.

        **`PlatformAdmin`** — configures payer plans (the only role that may register one) and enrols patients alongside `PharmacyOperations`.
        **`PharmacyOperations`** — the operational owner. Exclusively performs regimen synchronization, the adherence review sweep, fill-cycle creation, shipment staging, dispatch, delivery recording, refill-authorization creation, chasing and escalation, and partial reissue.
        **`VerifyingPharmacist`** — professional judgement. Exclusively adjudicates a fill cycle, verifies a pouch roll, sends a quarantined roll back for rework, and decides a travel exception. Shares pouch imaging (single-pouch and whole-roll) with `PackagingTechnician`.
        **`PackagingTechnician`** — the bench. Exclusively generates a pouch roll for a cycle and claims a roll as packed.
        `Prescriber` and `PharmacyOperations` may record a prescription.
        Confirming pickup is the patient's exclusive act: no staff role may perform it.
        No role is a superset of another; each role is a distinct band of authority.
        Second it pins the schedule: `anchor_fill_day` and `sync_mode` are stored, `sync_status` becomes `SYNCED`, and `next_cycle_start_date` is computed as the earliest calendar date on or after the clock date whose day-of-month equals `anchor_fill_day`.
        The packaging dimension moves from `DRAFT` to `LINES_ADJUDICATED`.
        On success `verification_status` becomes `PACKED`, `packed_by_user_id` is set to the caller's `X-User-ID` and `packed_at` to the clock; the cycle's `packaging_status` moves from `ROLL_GENERATED` to `PACKED`.
        When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`.
        On success `status` becomes `IN_TRANSIT`, a `tracking_number` is stamped and `dispatched_at` is set to the clock.
        The ordinary branch applies to any parcel whose `shipment_kind` is not `COLD_CHAIN`, and to a cold-chain parcel whose `cold_chain_excursion_minutes` is at most 120: `status` becomes `DELIVERED` and nothing else changes.
        On success `status` becomes `PICKED_UP`, `pickup_confirmed_at` is set to the clock, and an adherence event is appended with `event_type` `PICKUP_CONFIRMED` and `source` `PATIENT_REPORTED`.
        When every shipment of the cycle has reached a terminal `status` — `PICKED_UP`, `PICKUP_MISSED`, `EXCEPTION_RETURNED` or `CANCELLED` — the cycle's `packaging_status` moves from `SHIPPED` to `CLOSED`.
        The patient's `consecutive_missed_pickups` is reset to 0 — a confirmed collection breaks the streak entirely rather than decrementing it.

        Design: Corner/rbac/every_pharmacy_role_performs_its_own_exclusive_operations
        """
        validate_success(
            api_client.set_clock("2026-08-10T00:00:00Z", admin_headers()),
            expected_status=200,
        )

        # PlatformAdmin registers the plan and enrols the patient.
        plan = validate_success(
            api_client.create_insurance_plan(insurance_plan_payload(), admin_headers()),
            expected_status=201,
        )
        patient = validate_success(
            api_client.create_patient(patient_payload(plan["id"]), admin_headers()),
            expected_status=201,
        )

        # The prescriber records the regimen.
        validate_success(
            api_client.create_prescription(
                metformin_payload(patient["id"]), prescriber_headers()
            ),
            expected_status=201,
        )

        # PharmacyOperations synchronizes and opens the cycle.
        synced = validate_success(
            api_client.synchronize_patient(
                patient["id"],
                synchronize_payload(anchor_fill_day=15, sync_mode="BRIDGE_TO_START"),
                ops_headers(),
            )
        )
        assert synced["sync_status"] == "SYNCED", synced
        cycle = validate_success(
            api_client.create_fill_cycle(
                fill_cycle_payload(patient["id"], "2026-08-15", 28), ops_headers()
            ),
            expected_status=201,
        )

        # The pharmacist adjudicates.
        adjudicated = validate_success(
            api_client.adjudicate_fill_cycle(
                cycle["id"], pharmacist_headers(), adjudicate_payload()
            )
        )
        assert_cycle_state(adjudicated, packaging_status="LINES_ADJUDICATED")

        # The bench generates and packs.
        roll = validate_success(
            api_client.generate_roll(cycle["id"], technician_headers(TECHNICIAN_ID)),
            expected_status=201,
        )
        packed = validate_success(
            api_client.pack_roll(roll["id"], technician_headers(TECHNICIAN_ID))
        )
        assert_roll_state(packed, verification_status="PACKED")
        assert packed["packed_by_user_id"] == TECHNICIAN_ID, packed
        assert_cycle_state(read_cycle(cycle["id"]), packaging_status="PACKED")

        # Imaging is shared; a second technician runs the scanner pass.
        imaged = validate_success(
            api_client.capture_roll_images(
                roll["id"],
                roll_images_payload(image_confidence_pct=97),
                technician_headers(TECHNICIAN_ID_2),
            )
        )
        assert_roll_state(imaged, verification_status="PACKED", mismatch_pouch_count=0)

        # Verification belongs to the pharmacist alone.
        verified = validate_success(
            api_client.verify_roll(roll["id"], pharmacist_headers(PHARMACIST_ID))
        )
        assert_roll_state(verified, verification_status="PASSED")
        assert_cycle_state(read_cycle(cycle["id"]), packaging_status="VERIFIED")

        # PharmacyOperations stages, dispatches and records delivery.
        shipment = validate_success(
            api_client.stage_shipment(
                cycle["id"], pouch_roll_shipment_payload(), ops_headers()
            ),
            expected_status=201,
        )
        dispatched = validate_success(
            api_client.dispatch_shipment(shipment["id"], ops_headers())
        )
        assert_shipment_state(dispatched, status="IN_TRANSIT")
        delivered = validate_success(
            api_client.deliver_shipment(
                shipment["id"], ops_headers(), deliver_payload()
            )
        )
        assert_shipment_state(delivered, status="DELIVERED")

        # Only the owning patient may confirm collection.
        picked_up = validate_success(
            api_client.confirm_pickup(
                shipment["id"], patient_headers(patient["id"])
            )
        )
        assert_shipment_state(picked_up, status="PICKED_UP")

        assert_cycle_state(read_cycle(cycle["id"]), packaging_status="CLOSED")
        assert_patient_posture(
            read_patient(patient["id"]), consecutive_missed_pickups=0
        )

    def test_prescriber_answers_the_chase_and_issues_the_regimen_change(self):
        """The prescriber answers an authorization and supersedes the prescription, while the pharmacy-side chase route refuses that role.

        Opening the chase is exclusive to `PharmacyOperations`; answering it is exclusive to `Prescriber`.
        The division is deliberate: the pharmacy chases, the prescriber answers, and neither may do the other's act.
        If both headers are present but the role in `X-User-Role` is not listed for the addressed endpoint in section 4, the request fails with `ERR_UNAUTHORIZED` and HTTP 403.
        An approval sets `status` `APPROVED` and stores `approved_refills`.
        Because the request was approved, the prescription moves from `PENDING_AUTHORIZATION` back to `ACTIVE` with both `refills_authorized` and `refills_remaining` raised by `approved_refills`.
        A regimen change is exclusive to `Prescriber` and is the disruption this whole subsystem exists to absorb: the prescriber changes a drug while a roll built on the old regimen is already on the bench or in the building.
        The addressed prescription moves from `ACTIVE` to the terminal `SUPERSEDED`, and a successor prescription is created with `status` `ACTIVE` and `supersedes_rx_id` pointing at the addressed prescription's `id`.
        **The response body is the new successor prescription, not the superseded one.**

        Design: Corner/rbac/prescriber_owns_the_authorization_answer_and_the_regimen_change
        """
        validate_success(
            api_client.set_clock("2026-08-10T00:00:00Z", admin_headers()),
            expected_status=200,
        )
        plan = validate_success(
            api_client.create_insurance_plan(insurance_plan_payload(), admin_headers()),
            expected_status=201,
        )
        patient = validate_success(
            api_client.create_patient(patient_payload(plan["id"]), ops_headers()),
            expected_status=201,
        )
        prescription = validate_success(
            api_client.create_prescription(
                metformin_payload(patient["id"], refills_authorized=0),
                prescriber_headers(),
            ),
            expected_status=201,
        )
        authorization = validate_success(
            api_client.create_refill_authorization(
                refill_authorization_payload(prescription["id"], requested_refills=3),
                ops_headers(),
            ),
            expected_status=201,
        )
        assert authorization["status"] == "SENT", authorization

        # The pharmacy may not answer, and the prescriber may not chase.
        validate_error(
            api_client.respond_refill_authorization(
                authorization["id"],
                authorization_response_payload("APPROVE", approved_refills=3),
                ops_headers(),
            ),
            ApiErrorId.UNAUTHORIZED,
        )
        validate_error(
            api_client.chase_refill_authorization(
                authorization["id"], prescriber_headers()
            ),
            ApiErrorId.UNAUTHORIZED,
        )

        answered = validate_success(
            api_client.respond_refill_authorization(
                authorization["id"],
                authorization_response_payload("APPROVE", approved_refills=3),
                prescriber_headers(),
            )
        )
        assert answered["status"] == "APPROVED", answered
        assert answered["approved_refills"] == 3, answered

        after_approval = validate_success(
            api_client.get_prescription(prescription["id"], prescriber_headers())
        )
        assert after_approval["refills_remaining"] == 3, after_approval

        successor = validate_success(
            api_client.regimen_change(
                prescription["id"],
                regimen_change_payload(
                    expected_prescription_version=after_approval["version"],
                    new_drug_name="Metformin ER",
                    new_form="TABLET",
                    new_copay_tier="GENERIC",
                    new_dose_times=["MORNING", "EVENING"],
                    new_quantity_per_dose=1,
                    change_reason="Split to twice daily",
                ),
                prescriber_headers(),
            ),
            expected_status=201,
        )
        assert successor["id"] != prescription["id"], successor
        assert successor["supersedes_rx_id"] == prescription["id"], successor
        assert successor["dose_times"] == ["MORNING", "EVENING"], successor
        assert successor["refills_remaining"] == 3, successor


class TestUnauthorizedRoleRefusals:
    """The negative half: a role reaching for authority it does not hold."""

    def test_each_role_is_refused_another_roles_exclusive_operation(self):
        """Seven probes against existing ids with otherwise valid payloads are each refused with ERR_UNAUTHORIZED and change nothing.

        If both headers are present but the role in `X-User-Role` is not listed for the addressed endpoint in section 4, the request fails with `ERR_UNAUTHORIZED` and HTTP 403.
        The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.
        May read every collection in the system but performs no pharmacy step: no adjudication, no bench work, no verification, no prescriber act, no pickup confirmation.
        May not configure plans, may not adjudicate, may not pack, may not verify or rework, may not decide travel exceptions, may not answer an authorization or issue a regimen change, and may not confirm pickup.
        May not create cycles, stage shipments or reissue; may not generate or pack a roll; may not touch the authorization chase; may not synchronize, change auto-ship posture, report dose events or run the adherence review.
        May never verify or rework a roll, never adjudicate, never create plans, patients, prescriptions or cycles, and never write to a shipment.
        Reads prescriptions and refill authorizations only.
        May not touch cycles, rolls, pouches, shipments, patients, cycle lines or credit memos, and may not decide a travel exception.
        May not read insurance plans, the patient collection, cycle lines, pouch rolls, pouches or refill authorizations, and performs no pharmacy step.
        Synchronization is exclusive to `PharmacyOperations` and is the act that makes a patient fillable.
        Second it pins the schedule: `anchor_fill_day` and `sync_mode` are stored, `sync_status` becomes `SYNCED`, and `next_cycle_start_date` is computed as the earliest calendar date on or after the clock date whose day-of-month equals `anchor_fill_day`.

        Design: Corner/rbac/every_role_is_refused_another_roles_exclusive_operation
        """
        scenario = setup_packed_cycle(packer=TECHNICIAN_ID)
        patient_id = scenario.patient_id
        cycle_id = scenario.cycle_id
        roll_id = scenario.roll_id

        # PlatformAdmin performs no pharmacy step.
        validate_error(
            api_client.adjudicate_fill_cycle(
                cycle_id, admin_headers(), adjudicate_payload()
            ),
            ApiErrorId.UNAUTHORIZED,
        )
        # PharmacyOperations may not verify.
        validate_error(
            api_client.verify_roll(roll_id, ops_headers()),
            ApiErrorId.UNAUTHORIZED,
        )
        # The pharmacist may not generate a roll.
        validate_error(
            api_client.generate_roll(cycle_id, pharmacist_headers()),
            ApiErrorId.UNAUTHORIZED,
        )
        # The bench may not adjudicate.
        validate_error(
            api_client.adjudicate_fill_cycle(
                cycle_id, technician_headers(TECHNICIAN_ID), adjudicate_payload()
            ),
            ApiErrorId.UNAUTHORIZED,
        )
        # The prescriber may not open a cycle, even with a valid payload.
        validate_error(
            api_client.create_fill_cycle(
                fill_cycle_payload(patient_id, "2026-09-12", 28), prescriber_headers()
            ),
            ApiErrorId.UNAUTHORIZED,
        )
        # The patient may not synchronize their own regimen.
        validate_error(
            api_client.synchronize_patient(
                patient_id,
                synchronize_payload(anchor_fill_day=20, sync_mode="TRIM_TO_START"),
                patient_headers(patient_id),
            ),
            ApiErrorId.UNAUTHORIZED,
        )
        # Reads are role-gated too: the prescriber has no patient roster.
        validate_error(
            api_client.list_patients(prescriber_headers()),
            ApiErrorId.UNAUTHORIZED,
        )

        # Nothing moved.
        assert_roll_state(read_roll(roll_id), verification_status="PACKED")
        patient = read_patient(patient_id)
        assert patient["anchor_fill_day"] == 15, patient
        assert patient["sync_mode"] == "BRIDGE_TO_START", patient
        assert_total_count(
            api_client.list_fill_cycles(ops_headers(), {"patient_id": patient_id}), 1
        )

    def test_bench_role_is_refused_the_financial_and_clinical_collections(self):
        """The packing technician reads rolls and cycle lines but is refused plan pricing, credit memos, authorizations, adherence events and the patient roster.

        Reads are narrower than the other staff roles: this role may read patients by identifier, prescriptions, fill cycles, cycle lines, pouch rolls, pouches and shipments, but not insurance plans, the patient collection, credit memos, travel exceptions, refill authorizations or adherence events.
        If both headers are present but the role in `X-User-Role` is not listed for the addressed endpoint in section 4, the request fails with `ERR_UNAUTHORIZED` and HTTP 403.
        May read everything.

        Design: Corner/rbac/technician_cannot_read_the_financial_or_clinical_ledgers
        """
        scenario = setup_rolled_cycle(packer=TECHNICIAN_ID)
        bench = technician_headers(TECHNICIAN_ID)

        # The two shared reads are permitted.
        roll = validate_success(api_client.get_pouch_roll(scenario.roll_id, bench))
        assert roll["id"] == scenario.roll_id, roll
        lines, _ = validate_paginated(
            api_client.list_cycle_lines(bench, {"cycle_id": scenario.cycle_id})
        )
        assert lines, lines
        assert all(line["cycle_id"] == scenario.cycle_id for line in lines), lines

        # The addressed patient read is permitted while the roster list is not.
        addressed = validate_success(
            api_client.get_patient(scenario.patient_id, bench)
        )
        assert addressed["id"] == scenario.patient_id, addressed

        # The five forbidden reads.
        validate_error(
            api_client.get_insurance_plan(scenario.plan_id, bench),
            ApiErrorId.UNAUTHORIZED,
        )
        validate_error(api_client.list_credit_memos(bench), ApiErrorId.UNAUTHORIZED)
        validate_error(
            api_client.list_refill_authorizations(bench), ApiErrorId.UNAUTHORIZED
        )
        validate_error(api_client.list_adherence_events(bench), ApiErrorId.UNAUTHORIZED)
        validate_error(api_client.list_patients(bench), ApiErrorId.UNAUTHORIZED)

        # The same five routes answer PharmacyOperations, so the refusal is the role's.
        ops = ops_headers()
        validate_success(api_client.get_insurance_plan(scenario.plan_id, ops))
        validate_paginated(api_client.list_credit_memos(ops))
        validate_paginated(api_client.list_refill_authorizations(ops))
        validate_paginated(api_client.list_adherence_events(ops))
        validate_paginated(api_client.list_patients(ops))


class TestPatientScoping:
    """A patient caller may only reach rows that resolve to their own id."""

    def test_patient_scope_blocks_reads_and_writes_across_the_boundary(self):
        """Five probes by a second patient against the first patient's rows are refused with ERR_PATIENT_SCOPE_VIOLATION, while the list read is filtered instead.

        When `X-User-Role` is `Patient`, the addressed resource must resolve to the caller.
        For a route addressed by patient identifier, that identifier must equal `X-User-ID`.
        For any other resource, the owning patient is resolved by walking the ownership edges — a shipment resolves through its fill cycle to that cycle's `patient_id`, a prescription resolves directly through its `patient_id`, a cycle line resolves through its cycle, a pouch through its roll and that roll's cycle — and the resulting patient identifier must equal `X-User-ID`.
        A mismatch fails with `ERR_PATIENT_SCOPE_VIOLATION` and HTTP 403.
        The same rule applies to list reads: a patient sees only their own rows.
        The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.
        `PAUSE` moves `autoship_status` from `ACTIVE` to `PAUSED_PATIENT` with `pause_reason` `PATIENT_REQUEST`, and every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`.

        Design: Corner/rbac/patient_scope_blocks_reads_and_writes_across_the_membership_boundary
        """
        both = setup_two_synced_patients()
        owner = both["first"]
        stranger = both["second"]

        # Drive the owner's cycle to a staged pouch-roll parcel.
        cycle = create_cycle(owner.patient_id, "2026-08-15", 28)
        do_adjudicate(cycle["id"])
        roll = do_generate_roll(cycle["id"], TECHNICIAN_ID)
        do_pack(roll["id"], TECHNICIAN_ID)
        do_image_roll(roll["id"], 97, None, TECHNICIAN_ID_2)
        do_verify(roll["id"], PHARMACIST_ID)
        shipment = do_stage_shipment(cycle["id"], pouch_roll_shipment_payload())

        intruder = patient_headers(stranger.patient_id)
        before = read_patient(owner.patient_id)

        # Three addressed reads, the last resolved through the shipment's cycle.
        validate_error(
            api_client.get_patient(owner.patient_id, intruder),
            ApiErrorId.PATIENT_SCOPE_VIOLATION,
        )
        validate_error(
            api_client.get_fill_cycle(cycle["id"], intruder),
            ApiErrorId.PATIENT_SCOPE_VIOLATION,
        )
        validate_error(
            api_client.get_shipment(shipment["id"], intruder),
            ApiErrorId.PATIENT_SCOPE_VIOLATION,
        )
        # Two writes.
        validate_error(
            api_client.set_autoship(
                owner.patient_id, autoship_payload("PAUSE"), intruder
            ),
            ApiErrorId.PATIENT_SCOPE_VIOLATION,
        )
        validate_error(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    owner.patient_id,
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                intruder,
            ),
            ApiErrorId.PATIENT_SCOPE_VIOLATION,
        )

        # No state changed for the owner.
        after = read_patient(owner.patient_id)
        assert after["autoship_status"] == before["autoship_status"], after
        assert after["autoship_status"] == "ACTIVE", after
        assert_total_count(
            api_client.list_vacation_exceptions(
                ops_headers(), {"patient_id": owner.patient_id}
            ),
            0,
        )

        # A list read is filtered rather than refused.
        assert_total_count(api_client.list_fill_cycles(intruder), 0)

        # The identical five calls succeed for the owning patient.
        owner_headers = patient_headers(owner.patient_id)
        validate_success(api_client.get_patient(owner.patient_id, owner_headers))
        validate_success(api_client.get_fill_cycle(cycle["id"], owner_headers))
        validate_success(api_client.get_shipment(shipment["id"], owner_headers))
        paused = validate_success(
            api_client.set_autoship(
                owner.patient_id, autoship_payload("PAUSE"), owner_headers
            )
        )
        assert_patient_posture(
            paused, autoship_status="PAUSED_PATIENT", pause_reason="PATIENT_REQUEST"
        )
        validate_success(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    owner.patient_id,
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                owner_headers,
            ),
            expected_status=201,
        )


class TestSharedOperations:
    """Routes that accept more than one role, and the one route that needs no identity."""

    def test_pouch_imaging_accepts_both_the_bench_and_the_pharmacist(self):
        """Two pouches of one roll are imaged by a technician and by a pharmacist, both recorded as MATCH.

        Both `PackagingTechnician` and `VerifyingPharmacist` may image.
        The single-pouch route takes `detected_pill_count` and `image_confidence_pct` (0 through 100) and applies three gates in order: the pouch's roll must have `verification_status` `PACKED`, otherwise `ERR_INVALID_ROLL_STATE`; the pouch's `verification_result` must still be `PENDING`, otherwise `ERR_IMAGE_ALREADY_CAPTURED`; and the caller's `X-User-ID` must not equal the roll's `packed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.
        If `image_confidence_pct` is strictly below 90, `verification_result` becomes `UNREADABLE` regardless of the pill count — a low-confidence read is never accepted as a match even when the count happens to agree.
        Otherwise, if `detected_pill_count` equals `expected_pill_count`, `verification_result` becomes `MATCH`.
        The submitted `detected_pill_count` and `image_confidence_pct` are stored, `imaged_by_user_id` is set to the caller's `X-User-ID` and `imaged_at` to the clock.
        The roll's `mismatch_pouch_count` is then recomputed as the number of its pouches whose `verification_result` is `MISMATCH_COUNT` or `UNREADABLE`.
        Each pouch starts with `verification_result` `PENDING` and with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` all null.
        Each pouch records its `roll_id`, its `dose_date`, its `dose_slot`, and a 1-based `pouch_index` assigned by ascending `dose_date` and, within a date, by slot in the order `MORNING`, then `NOON`, then `EVENING`, then `BEDTIME`.
        `expected_pill_count` is the sum of the `quantity` values across `contents` and is the count the verification image must match.

        Design: Corner/rbac/pack_verification_imaging_is_shared_between_the_bench_and_the_pharmacist
        """
        scenario = setup_packed_cycle(packer=TECHNICIAN_ID)
        bench = technician_headers(TECHNICIAN_ID)

        rows, _ = validate_paginated(
            api_client.list_pouches(bench, {"roll_id": scenario.roll_id, "limit": 100})
        )
        first = pouch_by_index(rows, 1)
        second = pouch_by_index(rows, 2)
        assert first["expected_pill_count"] == 1, first
        assert second["expected_pill_count"] == 1, second
        assert first["dose_slot"] == "MORNING", first
        assert second["dose_slot"] == "MORNING", second
        assert first["dose_date"] < second["dose_date"], (first, second)

        # A technician who did not pack images the first pouch.
        imaged_by_bench = validate_success(
            api_client.capture_pouch_image(
                first["id"],
                pouch_image_payload(detected_pill_count=1, image_confidence_pct=97),
                technician_headers(TECHNICIAN_ID_2),
            )
        )
        assert imaged_by_bench["verification_result"] == "MATCH", imaged_by_bench
        assert imaged_by_bench["imaged_by_user_id"] == TECHNICIAN_ID_2, imaged_by_bench

        # The pharmacist images the second pouch on the very same roll.
        imaged_by_rph = validate_success(
            api_client.capture_pouch_image(
                second["id"],
                pouch_image_payload(detected_pill_count=1, image_confidence_pct=96),
                pharmacist_headers(PHARMACIST_ID),
            )
        )
        assert imaged_by_rph["verification_result"] == "MATCH", imaged_by_rph
        assert imaged_by_rph["imaged_by_user_id"] == PHARMACIST_ID, imaged_by_rph

        roll = validate_success(
            api_client.get_pouch_roll(scenario.roll_id, pharmacist_headers())
        )
        assert_roll_state(roll, verification_status="PACKED", mismatch_pouch_count=0)

        after, _ = validate_paginated(
            api_client.list_pouches(
                pharmacist_headers(), {"roll_id": scenario.roll_id, "limit": 100}
            )
        )
        matched = [p for p in after if p["verification_result"] == "MATCH"]
        assert {p["id"] for p in matched} == {first["id"], second["id"]}, matched
        untouched = [p for p in after if p["id"] not in {first["id"], second["id"]}]
        assert all(p["verification_result"] == "PENDING" for p in untouched), untouched
        assert all(p["imaged_by_user_id"] is None for p in untouched), untouched

    @pytest.mark.parametrize(
        "role, instant",
        [
            ("Patient", "2026-08-10T00:00:00Z"),
            ("PackagingTechnician", "2026-09-05T09:30:00Z"),
        ],
    )
    def test_clock_setter_accepts_a_bare_role_with_no_identity(self, role, instant):
        """The clock setter answers a request carrying only X-User-Role, for any role, without ERR_UNAUTHENTICATED.

        The clock setter is the one endpoint exempt from authentication: it may be called by any of the six roles and does not require `X-User-ID` or `X-User-Role` to be present.
        If either header is absent or empty on any endpoint other than the logical-clock setter, the request fails with `ERR_UNAUTHENTICATED` and HTTP 401.
        Setting the clock mutates no business entity; its response body is an object carrying the new `current_utc` value.

        Design: Corner/rbac/clock_write_is_open_to_every_role_and_needs_no_identity
        """
        headers = {"Content-Type": "application/json", "X-User-Role": role}
        assert "X-User-ID" not in headers

        response = api_client.set_clock(instant, headers)
        data = validate_success(response, expected_status=200)
        assert_envelope_shape(response, "object")
        # The PRD fixes that the body carries the new `current_utc` value but never
        # pins its wire spelling, so the instant is compared rather than the string.
        assert "current_utc" in data, data
        assert _as_instant(data["current_utc"]) == _as_instant(instant), data
