"""Entity creation, declared defaults, computed fields and stored-field reads.

Covers the payer plan, the patient, the prescription, the fill-cycle listing and
the immutable adherence event: what the server mints, what it defaults, what it
computes and what it refuses.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    admin_headers,
    assert_adherence_event_shape,
    assert_cycle_state,
    assert_envelope_shape,
    assert_identity_fields,
    assert_ids_in_order,
    assert_no_pagination_fields,
    assert_patient_posture,
    assert_total_count,
    create_cycle,
    create_patient,
    create_plan,
    create_rx,
    do_synchronize,
    dose_event,
    dose_events_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    metformin_payload,
    ops_headers,
    patient_headers,
    patient_payload,
    prescriber_headers,
    prescription_payload,
    read_patient,
    set_clock,
    setup_adjudicated_cycle,
    synchronize_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_PLAN_BODY = {
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

MANDATORY_ONLY_PLAN_BODY = {
    "payer_name": "Cascade Health",
    "bin_number": "004336",
    "generic_copay_cents_per_day": 30,
    "brand_copay_cents_per_day": 60,
    "specialty_copay_cents_per_day": 90,
}

UNKNOWN_PATIENT_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_CYCLE_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestInsurancePlanCreation:
    """Registering a payer plan: verbatim round-trip and the declared defaults."""

    def test_plan_with_every_field_round_trips_at_version_one(self):
        """A fully specified payer plan is persisted verbatim and returned at version 1.

        The caller supplies `payer_name` (the payer or pharmacy-benefit-manager trade name), `bin_number` (the six-digit routing BIN used on the claim), and the three per-day copay rates `generic_copay_cents_per_day`, `brand_copay_cents_per_day` and `specialty_copay_cents_per_day`, each of which must be zero or greater.
        A plan is created with `version` 1.
        Every resource carries a server-generated `id`: an opaque UUID string with no type prefix.
        `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, both set from the logical clock at creation; `updated_at` is refreshed on every mutation.
        The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.

        Design: Corner/entities/insurance_plan_created_with_every_field_returns_201
        """
        set_clock("2026-08-10T00:00:00Z")

        response = api_client.create_insurance_plan(FULL_PLAN_BODY, admin_headers())

        plan = validate_success(response, expected_status=201)
        assert_envelope_shape(response, "object")
        assert is_valid_uuid(plan["id"]), plan["id"]
        assert plan["version"] == 1, plan
        for field, submitted in FULL_PLAN_BODY.items():
            assert plan[field] == submitted, (field, plan)
        assert plan["created_at"] == "2026-08-10T00:00:00.000Z", plan
        assert plan["updated_at"] == "2026-08-10T00:00:00.000Z", plan

    def test_plan_optional_fields_take_their_declared_defaults(self):
        """A plan created with only the five mandatory fields adopts every declared default.

        Four further fields are optional and take a default when omitted: `refill_too_soon_threshold_pct` defaults to 75 and must lie between 0 and 100; `max_day_supply_days` defaults to 90 and must lie between 1 and 365; `vacation_overrides_per_year` defaults to 1 and must lie between 0 and 12; `coinsurance_pct` defaults to 20 and must lie between 0 and 100. The boolean `allows_payer_vacation_override` defaults to false, and when false the payer refuses payer-level travel overrides entirely, leaving only a pharmacist-level approval possible.

        Design: Corner/entities/insurance_plan_defaults_applied_when_optional_fields_omitted
        """
        set_clock("2026-08-10T00:00:00Z")

        response = api_client.create_insurance_plan(
            MANDATORY_ONLY_PLAN_BODY, admin_headers()
        )

        plan = validate_success(response, expected_status=201)
        assert plan["refill_too_soon_threshold_pct"] == 75, plan
        assert plan["max_day_supply_days"] == 90, plan
        assert plan["vacation_overrides_per_year"] == 1, plan
        assert plan["coinsurance_pct"] == 20, plan
        assert plan["allows_payer_vacation_override"] is False, plan


class TestPatientEnrolment:
    """Enrolling a patient: the deliberately inert start, and server-minted audit fields."""

    def test_new_patient_starts_unsynced_with_active_autoship(self):
        """A freshly enrolled patient is inert on the sync dimension and active on auto-ship.

        The new patient starts deliberately inert: `sync_status` is `UNSYNCED`, `anchor_fill_day`, `sync_mode` and `next_cycle_start_date` are all null, `autoship_status` is `ACTIVE`, `pause_reason` is null, `adherence_score_pct` is 100, `consecutive_missed_pickups` is 0, `credit_balance_cents` is 0, `vacation_exceptions_used_this_year` is 0, and `version` is 1.

        Design: Corner/entities/patient_created_starts_unsynced_with_active_autoship
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()

        response = api_client.create_patient(
            patient_payload(plan["id"]), ops_headers()
        )

        patient = validate_success(response, expected_status=201)
        assert patient["sync_status"] == "UNSYNCED", patient
        assert patient["sync_mode"] is None, patient
        assert patient["next_cycle_start_date"] is None, patient
        assert patient["anchor_fill_day"] is None, patient
        assert_patient_posture(
            patient,
            autoship_status="ACTIVE",
            pause_reason=None,
            adherence_score_pct=100,
            credit_balance_cents=0,
            consecutive_missed_pickups=0,
        )
        assert patient["vacation_exceptions_used_this_year"] == 0, patient
        assert patient["version"] == 1, patient

    def test_patient_audit_fields_advance_on_the_first_mutation(self):
        """Synchronization bumps the patient to version 2 and refreshes updated_at only.

        Every resource carries a server-generated `id`: an opaque UUID string with no type prefix.
        `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, both set from the logical clock at creation; `updated_at` is refreshed on every mutation. `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, including mutations reached through a cascade from another endpoint.
        Second it pins the schedule: `anchor_fill_day` and `sync_mode` are stored, `sync_status` becomes `SYNCED`, and `next_cycle_start_date` is computed as the earliest calendar date on or after the clock date whose day-of-month equals `anchor_fill_day`.

        Design: Corner/entities/patient_identity_and_audit_fields_are_server_minted
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        create_rx(patient["id"], metformin_payload)
        assert_identity_fields(patient, expected_version=1)
        assert patient["created_at"] == "2026-08-10T00:00:00.000Z", patient
        set_clock("2026-08-11T09:30:00Z")

        response = api_client.synchronize_patient(
            patient["id"], synchronize_payload(15, "BRIDGE_TO_START"), ops_headers()
        )

        synced = validate_success(response)
        assert is_valid_uuid(synced["id"]), synced["id"]
        assert synced["id"] == patient["id"], synced
        assert synced["version"] == 2, synced
        assert synced["created_at"] == "2026-08-10T00:00:00.000Z", synced
        assert synced["updated_at"] == "2026-08-11T09:30:00.000Z", synced
        assert synced["sync_status"] == "SYNCED", synced
        assert synced["sync_mode"] == "BRIDGE_TO_START", synced
        assert synced["anchor_fill_day"] == 15, synced
        assert synced["next_cycle_start_date"] == "2026-08-15", synced


class TestPrescriptionRecording:
    """Recording a prescription: stored fields, omitted optionals and computed packability."""

    def test_detail_read_echoes_every_stored_prescription_field(self):
        """The prescription detail read returns the persisted fields and its zeroed counters.

        The new prescription starts with `status` `ACTIVE`, `refills_remaining` equal to `refills_authorized`, `refills_consumed` 0, `days_dispensed_total` 0, `supersedes_rx_id` null, `prior_last_dispensed_date` null, `prior_last_dispensed_days_supply` 0, `sync_bridge_days` 0, `sync_trim_days` 0 and `version` 1.
        Optionally the caller supplies `refrigerated` (default false — true when the item must move through a cold chain and can never enter a pouch), `is_controlled` (default false — true for a scheduled controlled substance, which caps day supply and forbids travel early-supply overrides), and the prior-fill history `last_dispensed_date` (default null for a never-filled prescription) and `last_dispensed_days_supply` (default 0).
        Read operations return HTTP 200.

        Design: Corner/entities/prescription_retrieval_returns_stored_fields
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        created = validate_success(
            api_client.create_prescription(
                metformin_payload(patient["id"]), prescriber_headers()
            ),
            expected_status=201,
        )

        response = api_client.get_prescription(created["id"], ops_headers())

        rx = validate_success(response)
        assert_envelope_shape(response, "object")
        assert_no_pagination_fields(response)
        assert rx["id"] == created["id"], rx
        assert rx["patient_id"] == patient["id"], rx
        assert rx["drug_name"] == "Metformin ER", rx
        assert rx["form"] == "TABLET", rx
        assert rx["copay_tier"] == "GENERIC", rx
        assert rx["dose_times"] == ["MORNING"], rx
        assert rx["quantity_per_dose"] == 1, rx
        assert rx["days_supply_written"] == 30, rx
        assert rx["refills_authorized"] == 3, rx
        assert rx["refills_remaining"] == 3, rx
        assert rx["refills_consumed"] == 0, rx
        assert rx["days_dispensed_total"] == 0, rx
        assert rx["status"] == "ACTIVE", rx
        assert rx["last_dispensed_date"] == "2026-07-25", rx
        assert rx["last_dispensed_days_supply"] == 28, rx
        assert rx["prior_last_dispensed_date"] is None, rx
        assert rx["prior_last_dispensed_days_supply"] == 0, rx

    def test_omitted_optional_prescription_fields_take_their_defaults(self):
        """A prescription recorded without its optional fields defaults them to false, null and zero.

        Optionally the caller supplies `refrigerated` (default false — true when the item must move through a cold chain and can never enter a pouch), `is_controlled` (default false — true for a scheduled controlled substance, which caps day supply and forbids travel early-supply overrides), and the prior-fill history `last_dispensed_date` (default null for a never-filled prescription) and `last_dispensed_days_supply` (default 0).
        The system computes `packable` and the caller may not supply it: `packable` is true exactly when `form` is `TABLET` or `CAPSULE` **and** `refrigerated` is false. The new prescription starts with `status` `ACTIVE`, `refills_remaining` equal to `refills_authorized`, `refills_consumed` 0, `days_dispensed_total` 0, `supersedes_rx_id` null, `prior_last_dispensed_date` null, `prior_last_dispensed_days_supply` 0, `sync_bridge_days` 0, `sync_trim_days` 0 and `version` 1.

        Design: Corner/entities/prescription_optional_flag_defaults_applied_when_omitted
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        body = prescription_payload(
            patient["id"],
            drug_name="Lisinopril",
            ndc="00093-1036-01",
            strength="10mg",
            refills_authorized=2,
        )

        response = api_client.create_prescription(body, prescriber_headers())

        rx = validate_success(response, expected_status=201)
        assert rx["refrigerated"] is False, rx
        assert rx["is_controlled"] is False, rx
        assert rx["last_dispensed_date"] is None, rx
        assert rx["last_dispensed_days_supply"] == 0, rx
        assert rx["packable"] is True, rx
        assert rx["refills_remaining"] == 2, rx
        assert rx["refills_consumed"] == 0, rx
        assert rx["days_dispensed_total"] == 0, rx
        assert rx["status"] == "ACTIVE", rx
        assert rx["sync_bridge_days"] == 0, rx
        assert rx["sync_trim_days"] == 0, rx

    def test_packable_is_the_conjunction_of_form_and_refrigeration(self):
        """Packability is computed: a refrigerated tablet and an inhaler are both unpackable.

        The system computes `packable` and the caller may not supply it: `packable` is true exactly when `form` is `TABLET` or `CAPSULE` **and** `refrigerated` is false.

        Design: Corner/entities/prescription_packable_is_computed_from_form_and_refrigerated
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])

        tablet = validate_success(
            api_client.create_prescription(
                prescription_payload(patient["id"]), prescriber_headers()
            ),
            expected_status=201,
        )
        cold_tablet = validate_success(
            api_client.create_prescription(
                prescription_payload(
                    patient["id"],
                    drug_name="Latanoprost",
                    ndc="00023-3315-05",
                    strength="0.005%",
                    dose_times=["BEDTIME"],
                    refrigerated=True,
                ),
                prescriber_headers(),
            ),
            expected_status=201,
        )
        inhaler = validate_success(
            api_client.create_prescription(
                prescription_payload(
                    patient["id"],
                    drug_name="Albuterol",
                    ndc="00173-0682-20",
                    strength="90mcg",
                    form="INHALER",
                ),
                prescriber_headers(),
            ),
            expected_status=201,
        )

        assert tablet["packable"] is True, tablet
        assert cold_tablet["packable"] is False, cold_tablet
        assert inhaler["packable"] is False, inhaler


class TestPrescriptionSchemaValidation:
    """Schema violations on prescription recording are refused before the row is written."""

    @pytest.mark.parametrize("dose_times", [None, []])
    def test_absent_or_empty_dose_times_is_a_schema_violation(self, dose_times):
        """dose_times is required and non-empty, so omitting or emptying it fails validation.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.
        Every endpoint: a required input field is missing or null; a field has the wrong JSON type; an enum field carries a value outside its declared set; an integer falls outside its declared range; a date or timestamp is not ISO 8601; `limit` is outside 1 through 100 or `offset` is negative; a date-range field pair has its start after its end; `dose_times` is empty or contains a duplicate slot; an array field that must be non-empty is empty.

        Design: Corner/entities/prescription_missing_required_dose_times_returns_invalid_request
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        body = prescription_payload(patient["id"], dose_times=dose_times)

        response = api_client.create_prescription(body, prescriber_headers())

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        assert_total_count(
            api_client.list_prescriptions(ops_headers(), {"patient_id": patient["id"]}),
            0,
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"copay_tier": "NON_PREFERRED_BRAND"},
            {"dose_times": ["MORNING", "MORNING"]},
            {"days_supply_written": 91},
        ],
    )
    def test_out_of_set_or_out_of_range_prescription_fields_are_refused(self, overrides):
        """An enum outside its set, a duplicated dose slot and an out-of-range day supply all fail.

        The caller supplies `patient_id`, `prescriber_npi` (the ten-digit prescriber NPI that becomes the refill-authorization destination), `drug_name`, `ndc`, `strength` as free text such as a milligram figure, `form` (one of `TABLET`, `CAPSULE`, `VIAL`, `INHALER`, `INJECTION_PEN`, `LIQUID`), `copay_tier` (one of `GENERIC`, `PREFERRED_BRAND`, `SPECIALTY`, selecting which plan rate applies), `dose_times` (a non-empty array of distinct slots drawn from `MORNING`, `NOON`, `EVENING`, `BEDTIME`), `quantity_per_dose` (at least 1 — the units placed in each pouch at each of that drug's slots), `days_supply_written` (between 1 and 90), `refills_authorized` (zero or greater), `written_date` and `expiration_date`.
        Every endpoint: a required input field is missing or null; a field has the wrong JSON type; an enum field carries a value outside its declared set; an integer falls outside its declared range; a date or timestamp is not ISO 8601; `limit` is outside 1 through 100 or `offset` is negative; a date-range field pair has its start after its end; `dose_times` is empty or contains a duplicate slot; an array field that must be non-empty is empty.

        Design: Corner/entities/prescription_invalid_copay_tier_enum_rejected
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])

        response = api_client.create_prescription(
            prescription_payload(patient["id"], **overrides), prescriber_headers()
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        assert_total_count(
            api_client.list_prescriptions(ops_headers(), {"patient_id": patient["id"]}),
            0,
        )


class TestAddressedEntityExistence:
    """A well-formed identifier that names no row yields the entity-specific 404."""

    def test_body_foreign_key_naming_no_patient_is_a_patient_not_found(self):
        """A prescription whose patient_id names no row is a 404 on the parent patient.

        Every endpoint accepting a foreign key in its body: any of `insurance_plan_id`, `patient_id`, `prescription_id`, `cycle_id`, `vacation_exception_id`, a member of `replacement_prescription_ids`, or a member of `force_pouch_prescription_ids` names no existing row.
        The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.

        Design: Corner/entities/prescription_with_unknown_patient_id_not_found
        """
        set_clock("2026-08-10T00:00:00Z")
        create_plan()

        response = api_client.create_prescription(
            prescription_payload(UNKNOWN_PATIENT_ID), prescriber_headers()
        )

        validate_error(response, ApiErrorId.PATIENT_NOT_FOUND)
        assert_total_count(
            api_client.list_prescriptions(
                ops_headers(), {"patient_id": UNKNOWN_PATIENT_ID}
            ),
            0,
        )

    def test_unknown_fill_cycle_path_id_returns_the_cycle_specific_not_found(self):
        """Reading a fill cycle that does not exist returns ERR_FILL_CYCLE_NOT_FOUND.

        Every endpoint addressed by a path identifier: no row of the addressed entity has that identifier. The error chosen is the one naming the addressed entity.
        The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
        The `error_id` is a unique, machine-readable string that identifies the specific error.
        The `message` provides a human-readable explanation of what went wrong.

        Design: Corner/entities/fill_cycle_detail_with_unknown_id_not_found
        """
        set_clock("2026-08-10T00:00:00Z")

        response = api_client.get_fill_cycle(UNKNOWN_CYCLE_ID, ops_headers())

        validate_error(response, ApiErrorId.FILL_CYCLE_NOT_FOUND)
        body = response.json()
        assert body["response_type"] == "error", body
        assert set(body["data"].keys()) == {"error_id", "message"}, body["data"]
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, body["meta"]


class TestFillCycleListing:
    """The fill-cycle collection read reports the four pagination fields."""

    def test_three_cycles_paginate_at_limit_two_in_creation_order(self):
        """Two pages over three cycles report total_count 3 with has_more true then false.

        List responses carry `limit`, `offset`, `total_count` and `has_more` in `meta`. `total_count` is the number of rows matching the filters *before* `limit` and `offset` are applied; `has_more` is true when the sum of `offset` and the number of returned rows is less than `total_count`.
        Unless a specific read says otherwise, rows are returned in ascending `created_at` order, with ascending `id` as a deterministic tie-break.
        The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status` `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null; `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false; `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null; `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and `version` 1.

        Design: Corner/entities/fill_cycle_listing_paginates_with_total_count_and_has_more
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        create_rx(patient["id"], metformin_payload)
        do_synchronize(patient["id"], 15, "BRIDGE_TO_START")
        first = create_cycle(patient["id"], "2026-08-15", 28)
        second = create_cycle(patient["id"], "2026-09-12", 28)
        third = create_cycle(patient["id"], "2026-10-10", 28)

        page_one = api_client.list_fill_cycles(
            ops_headers(), {"patient_id": patient["id"], "limit": 2, "offset": 0}
        )
        page_two = api_client.list_fill_cycles(
            ops_headers(), {"patient_id": patient["id"], "limit": 2, "offset": 2}
        )

        rows_one, meta_one = validate_paginated(page_one)
        assert_envelope_shape(page_one, "array")
        assert len(rows_one) == 2, rows_one
        assert meta_one["limit"] == 2, meta_one
        assert meta_one["offset"] == 0, meta_one
        assert meta_one["total_count"] == 3, meta_one
        assert meta_one["has_more"] is True, meta_one
        assert_ids_in_order(rows_one, [first["id"], second["id"]])

        rows_two, meta_two = validate_paginated(page_two)
        assert len(rows_two) == 1, rows_two
        assert meta_two["limit"] == 2, meta_two
        assert meta_two["offset"] == 2, meta_two
        assert meta_two["total_count"] == 3, meta_two
        assert meta_two["has_more"] is False, meta_two
        assert_ids_in_order(rows_two, [third["id"]])

        for row in rows_one + rows_two:
            assert_cycle_state(
                row, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
            )


class TestSynchronizeAnchorDay:
    """The anchor day has a business ceiling of 28 above a wider schema range."""

    def test_anchor_day_29_is_refused_by_the_business_ceiling(self):
        """An anchor day of 29 is refused as a business violation and pins nothing.

        The schema accepts `anchor_fill_day` between 1 and 31, but the business ceiling is 28: a value from 29 through 31 is rejected with `ERR_INVALID_ANCHOR_DAY`, because those days do not exist in every month, while a value outside 1 through 31 is a schema violation caught earlier.
        The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.

        Design: Corner/entities/synchronize_anchor_day_29_rejected
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        create_rx(patient["id"], prescription_payload)

        response = api_client.synchronize_patient(
            patient["id"], synchronize_payload(29, "BRIDGE_TO_START"), ops_headers()
        )

        validate_error(response, ApiErrorId.INVALID_ANCHOR_DAY)
        after = read_patient(patient["id"])
        assert after["sync_status"] == "UNSYNCED", after
        assert after["anchor_fill_day"] is None, after
        assert after["version"] == 1, after

    @pytest.mark.parametrize("anchor_fill_day", [0, 32])
    def test_anchor_day_outside_the_schema_range_is_a_schema_violation(
        self, anchor_fill_day
    ):
        """An anchor day below 1 or above 31 fails schema validation rather than the ceiling rule.

        The schema accepts `anchor_fill_day` between 1 and 31, but the business ceiling is 28: a value from 29 through 31 is rejected with `ERR_INVALID_ANCHOR_DAY`, because those days do not exist in every month, while a value outside 1 through 31 is a schema violation caught earlier.
        Every endpoint: a required input field is missing or null; a field has the wrong JSON type; an enum field carries a value outside its declared set; an integer falls outside its declared range; a date or timestamp is not ISO 8601; `limit` is outside 1 through 100 or `offset` is negative; a date-range field pair has its start after its end; `dose_times` is empty or contains a duplicate slot; an array field that must be non-empty is empty.

        Design: Corner/entities/synchronize_anchor_day_29_rejected
        """
        set_clock("2026-08-10T00:00:00Z")
        plan = create_plan()
        patient = create_patient(plan["id"])
        create_rx(patient["id"], prescription_payload)

        response = api_client.synchronize_patient(
            patient["id"],
            synchronize_payload(anchor_fill_day, "BRIDGE_TO_START"),
            ops_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        after = read_patient(patient["id"])
        assert after["sync_status"] == "UNSYNCED", after
        assert after["anchor_fill_day"] is None, after
        assert after["version"] == 1, after


class TestImmutableAdherenceEvent:
    """The adherence event is the one entity without a version or an updated_at."""

    def test_reported_dose_event_carries_only_id_and_created_at(self):
        """A patient-reported dose event is written with no version and no updated_at.

        The single exception is the adherence event, which is an append-only audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written. Nothing in this API deletes or edits an adherence event.
        One immutable adherence event is created per element, each carrying only `id` and `created_at` beyond its own payload; `source` is `PATIENT_REPORTED` when `X-User-Role` is `Patient` and `SYSTEM_SCAN` otherwise. Events are never edited or deleted once written.

        Design: Corner/entities/adherence_event_is_immutable_with_no_version_field
        """
        scenario = setup_adjudicated_cycle(
            clock="2026-08-10T00:00:00Z",
            plan_overrides={"refill_too_soon_threshold_pct": 75},
            prescriptions=[metformin_payload],
            anchor_fill_day=15,
            sync_mode="BRIDGE_TO_START",
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )
        patient_id = scenario.patient_id
        cycle_id = scenario.cycle_id
        set_clock("2026-08-16T08:00:00Z")

        response = api_client.report_dose_events(
            patient_id,
            dose_events_payload(
                cycle_id,
                [dose_event("POUCH_TAKEN", "2026-08-15T08:00:00Z", "MORNING", 1)],
            ),
            patient_headers(patient_id),
        )

        events = validate_success(response, expected_status=201)
        assert_envelope_shape(response, "array")
        assert len(events) == 1, events
        event = events[0]
        assert_adherence_event_shape(event)
        assert event["event_type"] == "POUCH_TAKEN", event
        assert is_iso8601_timestamp(event["occurred_at"]), event
        assert event["occurred_at"].startswith("2026-08-15T08:00:00"), event
        assert event["dose_slot"] == "MORNING", event
        assert event["pouch_index"] == 1, event
        assert event["cycle_id"] == cycle_id, event
        assert event["source"] == "PATIENT_REPORTED", event

        read_back = validate_success(
            api_client.get_adherence_event(event["id"], ops_headers())
        )
        assert read_back["id"] == event["id"], read_back
        assert "version" not in read_back, read_back
        assert "updated_at" not in read_back, read_back
