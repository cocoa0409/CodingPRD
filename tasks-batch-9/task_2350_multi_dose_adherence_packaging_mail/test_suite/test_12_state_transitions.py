"""State transitions of the fill cycle, the pouch roll, the parcel, the travel
exception, the prescriber chase and the auto-ship posture.

Each test builds its own preconditions through the API, because every test starts
against an empty database.
"""

from test_helpers import (
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_3,
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_memo,
    assert_patient_posture,
    assert_roll_state,
    assert_shipment_state,
    assert_total_count,
    cold_chain_shipment_payload,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    decide_vacation,
    do_autoship,
    do_confirm_pickup,
    do_deliver,
    do_dispatch,
    do_respond,
    do_stage_shipment,
    do_synchronize,
    do_verify,
    get_success_data,
    insulin_payload,
    memo_by_reason,
    metformin_payload,
    open_authorization,
    ops_headers,
    patient_headers,
    pharmacist_headers,
    pouch_roll_shipment_payload,
    prescription_payload,
    read_cycle,
    read_cycle_events,
    read_lines,
    read_memos,
    read_patient,
    read_prescription,
    read_roll,
    set_clock,
    setup_adjudicated_cycle,
    setup_imaged_cycle,
    setup_packed_cycle,
    setup_quarantined_roll,
    setup_synced_patient,
    setup_verified_cycle,
    sitagliptin_payload,
    technician_headers,
    vacation_exception_payload,
    validate_error,
)


def _cold_chain_only(patient_id):
    """A single refrigerated pen, so the cycle never builds a pouch roll."""
    return insulin_payload(patient_id, days_supply_written=30)


def _amoxicillin_expired(patient_id):
    """A short antibiotic course whose paper expired before the clock date."""
    return prescription_payload(
        patient_id,
        drug_name="Amoxicillin",
        ndc="00093-4155-73",
        strength="500mg",
        form="CAPSULE",
        copay_tier="GENERIC",
        dose_times=["NOON"],
        quantity_per_dose=1,
        days_supply_written=10,
        refills_authorized=0,
        written_date="2026-05-01",
        expiration_date="2026-08-01",
        last_dispensed_date="2026-07-20",
        last_dispensed_days_supply=10,
    )


class TestFillCycleDimensions:
    """The two independent dimensions a fill cycle carries on one row."""

    def test_new_cycle_starts_at_draft_and_not_adjudicated(self):
        """A freshly opened cycle sits at both dimensions' initial states with one PLANNED line per active prescription.

        The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status` `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null; `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false; `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null; `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and `version` 1. When `sync_mode` is omitted the cycle copies the patient's `sync_mode`. Creation also stages the claim: one cycle line is created per prescription of the patient whose `status` is `ACTIVE`, in ascending prescription `created_at` order. Each staged line records its `cycle_id` and `prescription_id` and starts with `line_status` `PLANNED`, `hold_reason` null, and every computed figure at its zero default — `days_supply_filled`, `bridge_days_applied`, `trim_days_applied`, `quantity_dispensed`, `refill_pct_used`, `allowance_days` and `copay_cents` all 0, with `packable_route`, `line_start_date` and `line_end_date` not yet determined.

        Design: Corner/state_machines/new_fill_cycle_starts_draft_and_not_adjudicated
        """
        scenario = setup_synced_patient(
            prescriptions=[metformin_payload, sitagliptin_payload]
        )

        cycle = create_cycle(scenario.patient_id, "2026-08-15", 28)

        assert_cycle_state(
            cycle,
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
            version=1,
        )
        assert cycle["cycle_end_date"] == "2026-09-12"
        assert cycle["sync_mode"] == "BRIDGE_TO_START"
        assert cycle["is_partial_reissue"] is False
        assert cycle["reissue_of_cycle_id"] is None
        assert cycle["reissue_required"] is False
        assert cycle["total_copay_cents"] == 0
        assert cycle["final_copay_cents"] is None
        assert cycle["roll_pouch_count"] == 0
        assert cycle["reissue_fee_cents"] == 0
        assert cycle["credit_applied_cents"] == 0
        assert cycle["rounding_delta_cents"] is None

        lines = read_lines(cycle["id"])
        assert len(lines) == 2
        for line in lines:
            assert_line_state(line, line_status="PLANNED", hold_reason=None)
            assert line["days_supply_filled"] == 0
            assert line["copay_cents"] == 0
            assert line["packable_route"] is None

    def test_second_adjudicate_on_a_cleared_cycle_is_refused(self):
        """A cycle whose payer dimension is already CLEARED refuses a replay of adjudication and keeps its single dispense stamp.

        The cycle's `packaging_status` must be `DRAFT` or `LINES_ADJUDICATED` and its `insurance_status` must be `NOT_ADJUDICATED` or `REJECTED_TOO_SOON`, otherwise `ERR_INVALID_CYCLE_STATE`; a cycle already `CLEARED` can never re-adjudicate. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`. Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1.

        Design: Corner/state_machines/second_adjudicate_on_a_cleared_cycle_rejected
        """
        scenario = setup_adjudicated_cycle()
        assert_cycle_state(
            scenario.cycle,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
        )
        assert scenario.cycle["total_copay_cents"] == 762
        first_version = scenario.cycle["version"]

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id, pharmacist_headers(), {}
        )

        validate_error(response, ApiErrorId.INVALID_CYCLE_STATE, expected_status=409)
        cycle = read_cycle(scenario.cycle_id)
        assert cycle["total_copay_cents"] == 762
        assert cycle["version"] == first_version

        prescription = read_prescription(scenario.rx_id())
        assert prescription["refills_remaining"] == 2
        assert prescription["refills_consumed"] == 1
        assert prescription["days_dispensed_total"] == 28
        assert prescription["last_dispensed_date"] == "2026-08-15"


class TestPouchBenchStates:
    """Packing, verification and the terminal PASSED state of a roll."""

    def test_pack_on_an_already_packed_roll_is_refused(self):
        """A second pack attempt on a PACKED roll is refused and does not re-stamp the packer identity.

        The roll's `verification_status` must be `BUILT`, otherwise `ERR_INVALID_ROLL_STATE`, and the roll must hold at least one pouch. On success `verification_status` becomes `PACKED`, `packed_by_user_id` is set to the caller's `X-User-ID` and `packed_at` to the clock; the cycle's `packaging_status` moves from `ROLL_GENERATED` to `PACKED`. Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/state_machines/pack_on_an_already_packed_roll_rejected
        """
        scenario = setup_packed_cycle(packer=TECHNICIAN_ID)
        assert_roll_state(scenario.roll, verification_status="PACKED")
        packed_version = scenario.roll["version"]

        response = api_client.pack_roll(
            scenario.roll_id, technician_headers(TECHNICIAN_ID_3)
        )

        validate_error(response, ApiErrorId.INVALID_ROLL_STATE, expected_status=409)
        roll = read_roll(scenario.roll_id)
        assert_roll_state(roll, verification_status="PACKED")
        assert roll["packed_by_user_id"] == TECHNICIAN_ID
        assert roll["packed_at"].startswith("2026-08-10T00:00:00")
        assert roll["version"] == packed_version
        assert_cycle_state(read_cycle(scenario.cycle_id), packaging_status="PACKED")

    def test_verify_of_a_fully_matching_roll_advances_roll_and_cycle(self):
        """Verifying a roll with no mismatch passes the roll, advances the cycle to VERIFIED and issues no goodwill credit.

        Both branches stamp `verified_by_user_id` with the caller's `X-User-ID` and `verified_at` with the clock, and increment the roll's `version` and the cycle's `version`. When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`. When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`, `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's `credit_balance_cents` rises by that amount as a goodwill gesture.

        Design: Corner/state_machines/verify_of_a_fully_matching_roll_advances_roll_and_cycle
        """
        scenario = setup_imaged_cycle()
        assert_roll_state(
            scenario.roll, verification_status="PACKED", mismatch_pouch_count=0
        )

        roll = do_verify(scenario.roll_id, PHARMACIST_ID)

        assert_roll_state(roll, verification_status="PASSED", rework_count=0)
        assert roll["verified_by_user_id"] == PHARMACIST_ID
        assert roll["verified_at"].startswith("2026-08-10T00:00:00")

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle, packaging_status="VERIFIED", insurance_status="CLEARED"
        )
        assert cycle["total_copay_cents"] == 762

        assert_total_count(
            api_client.list_credit_memos(
                ops_headers(), {"patient_id": scenario.patient_id}
            ),
            0,
        )

    def test_passed_roll_refuses_a_second_verify_and_a_rework(self):
        """PASSED is terminal for the roll: neither a second verification nor a rework is accepted.

        Its gates, in order: the roll's `verification_status` must be `PACKED` and no pouch of the roll may still have `verification_result` `PENDING`, otherwise `ERR_INVALID_ROLL_STATE`; and the caller's `X-User-ID` must not equal `packed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`. The roll's `verification_status` must be `FAILED_QUARANTINED`, otherwise `ERR_INVALID_ROLL_STATE`, and `rework_count` must be below 2, otherwise `ERR_REWORK_LIMIT_REACHED` — a roll may return to the bench at most twice.

        Design: Corner/state_machines/verify_of_a_fully_matching_roll_advances_roll_and_cycle
        """
        scenario = setup_verified_cycle()
        assert_roll_state(scenario.roll, verification_status="PASSED")
        version_after_verify = scenario.roll["version"]

        second_verify = api_client.verify_roll(scenario.roll_id, pharmacist_headers())
        validate_error(
            second_verify, ApiErrorId.INVALID_ROLL_STATE, expected_status=409
        )

        rework = api_client.rework_roll(scenario.roll_id, pharmacist_headers())
        validate_error(rework, ApiErrorId.INVALID_ROLL_STATE, expected_status=409)

        roll = read_roll(scenario.roll_id)
        assert_roll_state(roll, verification_status="PASSED", rework_count=0)
        assert roll["version"] == version_after_verify


class TestParcelStates:
    """Staging, dispatch, delivery and pickup of the cycle's parcels."""

    def test_dispatch_moves_cold_chain_parcel_staged_to_in_transit(self):
        """Dispatching a cold-chain parcel stamps tracking and dispatch time while the packaging dimension stays put.

        The shipment's `status` must be `STAGED`, otherwise `ERR_INVALID_SHIPMENT_STATE`. On success `status` becomes `IN_TRANSIT`, a `tracking_number` is stamped and `dispatched_at` is set to the clock. `covers_line_ids` holds the identifiers of the cycle's lines whose `packable_route` maps to this `shipment_kind` and whose `line_status` is `ADJUDICATED` or `PACKED_OUT`, ordered by ascending line `created_at`. The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`. When, after this dispatch, every required kind has a shipment whose `status` is `IN_TRANSIT`, `DELIVERED` or `PICKED_UP`, the cycle's `packaging_status` moves from `VERIFIED` to `SHIPPED` and the copay is finalised: `final_copay_cents` is computed by summing the **unrounded** per-line amounts over the lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT` — each amount being the tier's per-day rate multiplied by the line's `days_supply_filled`, multiplied by one hundred minus `coinsurance_pct`, divided by one hundred — and rounding that single sum half-up to whole cents.

        Design: Corner/state_machines/dispatch_moves_cold_chain_shipment_staged_to_in_transit
        """
        scenario = setup_adjudicated_cycle(prescriptions=[_cold_chain_only])
        lines = read_lines(scenario.cycle_id)
        assert len(lines) == 1
        assert_line_state(
            lines[0], line_status="ADJUDICATED", packable_route="COLD_CHAIN"
        )
        shipment = do_stage_shipment(scenario.cycle_id, cold_chain_shipment_payload())
        assert_shipment_state(shipment, status="STAGED", ship_cost_cents=3445)
        staged_at = shipment["staged_at"]
        set_clock("2026-08-14T10:00:00Z")

        dispatched = do_dispatch(shipment["id"])

        assert_shipment_state(
            dispatched, status="IN_TRANSIT", ship_cost_cents=3445
        )
        assert dispatched["tracking_number"] is not None
        assert dispatched["dispatched_at"].startswith("2026-08-14T10:00:00")
        assert dispatched["version"] == 2
        assert dispatched["staged_at"] == staged_at
        assert dispatched["staged_at"].startswith("2026-08-10T00:00:00")
        assert dispatched["delivered_at"] is None
        assert dispatched["covers_line_ids"] == [lines[0]["id"]]

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle, packaging_status="LINES_ADJUDICATED", insurance_status="CLEARED"
        )
        assert cycle["final_copay_cents"] is None

    def test_confirm_pickup_on_a_staged_parcel_is_refused(self):
        """The owning patient cannot confirm pickup of a parcel that has never left the pharmacy.

        The shipment's `status` must be `DELIVERED`, otherwise `ERR_INVALID_SHIPMENT_STATE`, and the caller's `X-User-ID` must be the patient who owns the shipment's cycle. On success `status` becomes `PICKED_UP`, `pickup_confirmed_at` is set to the clock, and an adherence event is appended with `event_type` `PICKUP_CONFIRMED` and `source` `PATIENT_REPORTED`.

        Design: Corner/state_machines/confirm_pickup_on_a_staged_shipment_rejected
        """
        scenario = setup_adjudicated_cycle(prescriptions=[_cold_chain_only])
        shipment = do_stage_shipment(scenario.cycle_id, cold_chain_shipment_payload())
        assert_shipment_state(shipment, status="STAGED")

        response = api_client.confirm_pickup(
            shipment["id"], patient_headers(scenario.patient_id)
        )

        validate_error(response, ApiErrorId.INVALID_SHIPMENT_STATE, expected_status=409)
        after = get_success_data(
            api_client.get_shipment(shipment["id"], ops_headers())
        )
        assert_shipment_state(after, status="STAGED")
        assert after["pickup_confirmed_at"] is None
        assert after["version"] == 1
        events = read_cycle_events(scenario.cycle_id)
        assert [e for e in events if e["event_type"] == "PICKUP_CONFIRMED"] == []

    def test_completing_dispatch_ships_the_cycle_and_finalises_the_copay(self):
        """The dispatch that completes the cycle moves it to SHIPPED, finalises the copay and packs the lines out.

        When, after this dispatch, every required kind has a shipment whose `status` is `IN_TRANSIT`, `DELIVERED` or `PICKED_UP`, the cycle's `packaging_status` moves from `VERIFIED` to `SHIPPED` and the copay is finalised: `rounding_delta_cents` is `total_copay_cents` minus `final_copay_cents`. When `rounding_delta_cents` is zero or negative, no memo is issued and no additional charge is raised — the patient is never billed for a rounding difference in the pharmacy's favour. Every line of the cycle whose `line_status` is `ADJUDICATED` becomes `PACKED_OUT`.

        Design: Corner/state_machines/pickup_confirmation_bubbles_the_cycle_to_closed
        """
        scenario = setup_verified_cycle()
        shipment = do_stage_shipment(scenario.cycle_id, pouch_roll_shipment_payload())
        assert_shipment_state(shipment, status="STAGED", ship_cost_cents=0)
        set_clock("2026-08-14T10:00:00Z")

        dispatched = do_dispatch(shipment["id"])

        assert_shipment_state(dispatched, status="IN_TRANSIT")
        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle, packaging_status="SHIPPED", insurance_status="CLEARED"
        )
        assert cycle["final_copay_cents"] == 762
        assert cycle["rounding_delta_cents"] == 0
        assert_line_state(read_lines(scenario.cycle_id)[0], line_status="PACKED_OUT")
        memos = read_memos(scenario.patient_id)
        assert [m for m in memos if m["reason"] == "ROUNDING_TRUEUP"] == []

    def test_pickup_confirmation_bubbles_the_cycle_to_closed(self):
        """Confirming the cycle's only parcel closes the cycle and clears the missed-pickup streak.

        On success `status` becomes `PICKED_UP`, `pickup_confirmed_at` is set to the clock, and an adherence event is appended with `event_type` `PICKUP_CONFIRMED` and `source` `PATIENT_REPORTED`. The patient's `consecutive_missed_pickups` is reset to 0 — a confirmed collection breaks the streak entirely rather than decrementing it. When every shipment of the cycle has reached a terminal `status` — `PICKED_UP`, `PICKUP_MISSED`, `EXCEPTION_RETURNED` or `CANCELLED` — the cycle's `packaging_status` moves from `SHIPPED` to `CLOSED`.

        Design: Corner/state_machines/pickup_confirmation_bubbles_the_cycle_to_closed
        """
        scenario = setup_verified_cycle()
        shipment = do_stage_shipment(scenario.cycle_id, pouch_roll_shipment_payload())
        set_clock("2026-08-14T10:00:00Z")
        do_dispatch(shipment["id"])
        set_clock("2026-08-16T12:00:00Z")
        do_deliver(shipment["id"])
        set_clock("2026-08-17T09:00:00Z")

        picked_up = do_confirm_pickup(shipment["id"], scenario.patient_id)

        assert_shipment_state(picked_up, status="PICKED_UP")
        assert picked_up["pickup_confirmed_at"].startswith("2026-08-17T09:00:00")
        assert_cycle_state(read_cycle(scenario.cycle_id), packaging_status="CLOSED")
        assert_patient_posture(
            read_patient(scenario.patient_id), consecutive_missed_pickups=0
        )
        pickup_events = [
            e
            for e in read_cycle_events(scenario.cycle_id)
            if e["event_type"] == "PICKUP_CONFIRMED"
        ]
        assert len(pickup_events) == 1
        assert pickup_events[0]["source"] == "PATIENT_REPORTED"


class TestTravelExceptionDecision:
    """The pharmacist decision on a travel early-supply request."""

    def test_pharmacist_approval_stores_days_without_waiving_the_refill_edit(self):
        """A pharmacist approval stores the approved days, leaves the refill-too-soon edit in force and consumes the yearly allowance.

        `APPROVE_PHARMACIST` sets `status` `PHARMACIST_APPROVED`, stores `approved_extra_days` and leaves `waives_refill_too_soon` false: the exception extends the day-supply allowance but does **not** waive the payer's refill-too-soon edit. Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`. All three branches stamp `decided_by_user_id` with the caller's `X-User-ID` and `decided_at` with the clock, and increment the request's `version`. The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.

        Design: Corner/state_machines/vacation_exception_pharmacist_approval_consumes_yearly_allowance
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan(
            vacation_overrides_per_year=1, allows_payer_vacation_override=True
        )
        patient = create_patient(plan["id"])
        create_rx(patient["id"], metformin_payload)
        request = get_success_data(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    patient["id"],
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                patient_headers(patient["id"]),
            ),
            expected_status=201,
        )
        assert request["status"] == "SUBMITTED"
        assert request["requested_extra_days"] == 5

        decided = decide_vacation(request["id"], "APPROVE_PHARMACIST", 5)

        assert decided["status"] == "PHARMACIST_APPROVED"
        assert decided["approved_extra_days"] == 5
        assert decided["waives_refill_too_soon"] is False
        assert decided["decided_by_user_id"] == PHARMACIST_ID
        assert decided["decided_at"].startswith("2026-08-10T00:00:00")
        assert decided["version"] == 2
        assert read_patient(patient["id"])["vacation_exceptions_used_this_year"] == 1

    def test_consumed_allowance_blocks_a_second_travel_request(self):
        """Once the pharmacist approval has consumed the single yearly override, another request is refused.

        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`. The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`.

        Design: Corner/state_machines/vacation_exception_pharmacist_approval_consumes_yearly_allowance
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan(
            vacation_overrides_per_year=1, allows_payer_vacation_override=True
        )
        patient = create_patient(plan["id"])
        create_rx(patient["id"], metformin_payload)
        first = get_success_data(
            api_client.create_vacation_exception(
                vacation_exception_payload(
                    patient["id"],
                    travel_start_date="2026-08-20",
                    travel_end_date="2026-08-27",
                    requested_extra_days=5,
                ),
                patient_headers(patient["id"]),
            ),
            expected_status=201,
        )
        decide_vacation(first["id"], "APPROVE_PHARMACIST", 5)
        assert read_patient(patient["id"])["vacation_exceptions_used_this_year"] == 1

        response = api_client.create_vacation_exception(
            vacation_exception_payload(
                patient["id"],
                travel_start_date="2026-08-20",
                travel_end_date="2026-08-27",
                requested_extra_days=5,
            ),
            patient_headers(patient["id"]),
        )

        validate_error(response, ApiErrorId.VACATION_LIMIT_EXCEEDED)


class TestPrescriberChaseTerminalStates:
    """The terminal states of the refill-authorization machine."""

    def test_denied_authorization_cannot_be_chased_or_escalated(self):
        """A denied authorization request refuses both a chase and an escalation, and its denial cascade stands.

        A denial sets `status` `DENIED` and stores `denial_reason`. The prescription moves from `PENDING_AUTHORIZATION` to `DISCONTINUED`, and every line of that prescription whose `line_status` is `HELD_AUTH` becomes `EXCLUDED_HELD` with `hold_reason` `AUTH_DENIED`. `APPROVED` and `DENIED` are terminal: neither may be chased, escalated or answered again. It is available only from `SENT` or `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`. Escalation is available only from `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`, and only once `chase_round` has reached 3, otherwise `ERR_ESCALATION_PREMATURE`.

        Design: Corner/state_machines/denied_authorization_cannot_be_chased
        """
        scenario = setup_adjudicated_cycle(
            prescriptions=[lambda pid: metformin_payload(pid, refills_authorized=0)]
        )
        held_line = read_lines(scenario.cycle_id)[0]
        assert_line_state(
            held_line, line_status="HELD_AUTH", hold_reason="NO_REFILLS_REMAINING"
        )
        authorization = open_authorization(scenario.rx_id(), 3)
        denied = do_respond(
            authorization["id"],
            "DENY",
            denial_reason="Therapy discontinued at last visit",
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Therapy discontinued at last visit"
        assert denied["version"] == 2

        chase = api_client.chase_refill_authorization(
            authorization["id"], ops_headers()
        )

        validate_error(chase, ApiErrorId.INVALID_AUTH_STATE, expected_status=409)
        escalation = api_client.escalate_refill_authorization(
            authorization["id"], ops_headers()
        )
        validate_error(escalation, ApiErrorId.INVALID_AUTH_STATE, expected_status=409)

        after = get_success_data(
            api_client.get_refill_authorization(authorization["id"], ops_headers())
        )
        assert after["status"] == "DENIED"
        assert after["chase_round"] == 0
        assert after["last_sent_at"].startswith("2026-08-10T00:00:00")
        assert read_prescription(scenario.rx_id())["status"] == "DISCONTINUED"
        assert_line_state(
            read_lines(scenario.cycle_id)[0],
            line_status="EXCLUDED_HELD",
            hold_reason="AUTH_DENIED",
        )


class TestPrescriptionExpirySweep:
    """The expiry sweep that synchronization runs before it pins the schedule."""

    def test_synchronize_expires_only_the_lapsed_prescription(self):
        """Synchronization retires the prescription whose paper lapsed before the clock date and leaves the live one active.

        First it sweeps expiry: every prescription of the patient whose `status` is `ACTIVE` and whose `expiration_date` is strictly before the clock date moves to `status` `EXPIRED`, is excluded from the synchronization set and will never appear on a future cycle's lines; each swept prescription's `version` increments. Second it pins the schedule: `anchor_fill_day` and `sync_mode` are stored, `sync_status` becomes `SYNCED`, and `next_cycle_start_date` is computed as the earliest calendar date on or after the clock date whose day-of-month equals `anchor_fill_day`. The patient's `version` increments by 1. Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle.

        Design: Corner/state_machines/synchronize_sweeps_expired_prescriptions_only
        """
        scenario = setup_synced_patient(
            synchronize=False,
            prescriptions=[_amoxicillin_expired, metformin_payload],
        )

        patient = do_synchronize(scenario.patient_id, 15, "BRIDGE_TO_START")

        assert patient["sync_status"] == "SYNCED"
        assert patient["sync_mode"] == "BRIDGE_TO_START"
        assert patient["next_cycle_start_date"] == "2026-08-15"
        assert patient["version"] == 2

        expired = read_prescription(scenario.rx_id(0))
        assert expired["status"] == "EXPIRED"
        assert expired["sync_bridge_days"] == 0
        assert expired["sync_trim_days"] == 0

        live = read_prescription(scenario.rx_id(1))
        assert live["status"] == "ACTIVE"
        assert live["sync_bridge_days"] == 0


class TestAutoShipPosture:
    """The auto-ship posture actions and their reach into the credit ledger."""

    def test_cancel_voids_every_unredeemed_credit_memo(self):
        """Cancelling auto-ship voids the patient's unredeemed goodwill credit and zeroes the balance.

        `CANCEL` moves `autoship_status` to `CANCELLED`, the terminal posture, with `pause_reason` `PATIENT_REQUEST`. Every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`, and — uniquely to this action — every credit memo of the patient whose `status` is `ISSUED` becomes `VOIDED` and `credit_balance_cents` is set to 0, because an unredeemed credit has no future fill to land on. When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`, `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's `credit_balance_cents` rises by that amount as a goodwill gesture.

        Design: Corner/state_machines/autoship_cancel_voids_every_unredeemed_credit_memo
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        memo = memo_by_reason(read_memos(scenario.patient_id), "FAILED_VERIFICATION")
        assert_memo(
            memo,
            reason="FAILED_VERIFICATION",
            amount_cents=500,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
            applied_to_cycle_id=None,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=500
        )

        patient = do_autoship(scenario.patient_id, "CANCEL")

        assert_patient_posture(
            patient,
            autoship_status="CANCELLED",
            pause_reason="PATIENT_REQUEST",
            credit_balance_cents=0,
        )
        voided = get_success_data(
            api_client.get_credit_memo(memo["id"], ops_headers())
        )
        assert_memo(voided, status="VOIDED")
        assert_roll_state(
            read_roll(scenario.roll_id), verification_status="FAILED_QUARANTINED"
        )

    def test_pause_leaves_the_unredeemed_credit_memo_untouched(self):
        """Pausing auto-ship changes only the posture: the issued goodwill credit and the balance survive.

        `PAUSE` moves `autoship_status` from `ACTIVE` to `PAUSED_PATIENT` with `pause_reason` `PATIENT_REQUEST`, and every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`. `CANCEL` moves `autoship_status` to `CANCELLED`, the terminal posture, with `pause_reason` `PATIENT_REQUEST`. Every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`, and — uniquely to this action — every credit memo of the patient whose `status` is `ISSUED` becomes `VOIDED` and `credit_balance_cents` is set to 0, because an unredeemed credit has no future fill to land on.

        Design: Corner/state_machines/autoship_cancel_voids_every_unredeemed_credit_memo
        """
        scenario = setup_quarantined_roll(mismatch_pouch_index=7)
        memo = memo_by_reason(read_memos(scenario.patient_id), "FAILED_VERIFICATION")
        assert_memo(memo, status="ISSUED", amount_cents=500)

        patient = do_autoship(scenario.patient_id, "PAUSE")

        assert_patient_posture(
            patient,
            autoship_status="PAUSED_PATIENT",
            pause_reason="PATIENT_REQUEST",
            credit_balance_cents=500,
        )
        still_issued = get_success_data(
            api_client.get_credit_memo(memo["id"], ops_headers())
        )
        assert_memo(still_issued, status="ISSUED", amount_cents=500)
