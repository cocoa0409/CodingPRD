"""The persisted surface of the estate rows: what a creation echoes, what a read
returns, what a list orders, and which fields the server mints for itself."""

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    ChairStatus,
    ChairType,
    LabResultStatus,
    LotStatus,
    NON_EXISTENT_UUID,
    PHARMACIST,
    PreparationStatus,
    SCHEDULER,
    assert_chair,
    assert_drug_lot,
    assert_infusion_center,
    assert_instant_equals,
    book_appointment,
    create_biosimilar,
    create_center,
    create_chair,
    create_drug,
    create_lot,
    create_patient,
    file_lab_result,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_center_payload,
    make_lab_result_payload,
    make_minimal_center_payload,
    make_nurse_payload,
    make_patient_payload,
    make_treatment_plan_payload,
    read_center,
    read_chair,
    read_lab_result,
    read_lot,
    request_dose,
    set_clock,
    setup_booked_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCentreCreationSurface:
    """Registering a centre answers with every declared dial and both counters."""

    def _register(self, api: ApiClient):
        set_clock(api, "2026-08-03T06:00:00Z")
        return api.create_center(make_center_payload(), SCHEDULER)

    def test_the_created_centre_echoes_all_nine_declared_inputs(self, api):
        """Every policy dial supplied on the request comes back on the 201 body.

        Design: Corner/entities/create_infusion_center_returns_every_declared_field_with_zeroed_chair_counters
        """
        response = self._register(api)

        center = validate_success(response, 201)
        assert center["name"] == "Riverside Infusion Suite"
        assert center["open_minute"] == 480
        assert center["close_minute"] == 1140
        assert center["turnover_buffer_minutes"] == 15
        assert center["urgent_reserve_chair_count"] == 1
        assert center["addon_cutoff_minute"] == 900
        assert center["lab_validity_hours"] == 72
        assert center["stagger_grid_minutes"] == 15
        assert center["acuity_slot_minutes"] == 30

    def test_both_chair_counters_read_zero_before_any_chair_exists(self, api):
        """The two derived figures are reported as zero the moment the centre is
        registered, as keys carrying zero rather than absent keys.

        Design: Corner/entities/create_infusion_center_returns_every_declared_field_with_zeroed_chair_counters
        """
        center = validate_success(self._register(api), 201)

        assert "available_chair_count" in center
        assert "reserved_chair_count" in center
        assert center["available_chair_count"] == 0
        assert center["reserved_chair_count"] == 0
        assert_infusion_center(center)

    def test_the_creation_is_stamped_from_the_logical_clock_at_version_one(self, api):
        """id, both instants and version are server-minted, and a fresh row starts at
        version 1 with its two instants equal.

        Design: Corner/entities/create_infusion_center_returns_every_declared_field_with_zeroed_chair_counters
        """
        response = self._register(api)
        center = validate_success(response, 201)

        assert is_valid_uuid(center["id"])
        assert center["version"] == 1
        # PRD 2.5 states created_at is "an ISO 8601 UTC instant with three fractional
        # digits" and that updated_at is "refreshed on every mutation of the row"; at
        # version 1 no mutation has happened, so the two instants agree. The PRD never
        # says the audit instants are stamped from the logical clock -- it binds that
        # clock to temporal comparisons and derivations only -- so the source of the
        # stamp is not asserted here.
        assert is_iso8601_timestamp(center["created_at"])
        assert center["updated_at"] == center["created_at"]

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestChairReadCarriesItsDerivedLoad:
    """A chair read is not a thin echo of the creation payload."""

    def _booked_chair(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
        )
        return suite, appointment

    def test_the_read_returns_the_stored_input_fields_unchanged(self, api):
        """The five supplied fields survive the booking untouched.

        Design: Corner/entities/get_chair_by_id_returns_the_stored_row_and_its_committed_minutes
        """
        suite, _appointment = self._booked_chair(api)
        chair_id = suite.chair_id("A1")

        row = validate_success(api.get_chair(chair_id, suite.nurse_headers), 200)

        assert row["id"] == chair_id
        assert row["center_id"] == suite.center_id
        assert row["label"] == "A1"
        assert row["chair_type"] == ChairType.STANDARD
        assert row["status"] == ChairStatus.AVAILABLE
        assert row["reserved_for_urgent"] is False
        assert_chair(row)

    def test_the_same_payload_reports_the_derived_committed_minutes(self, api):
        """The one 240-minute visit holding the chair is visible on the chair itself.

        Design: Corner/entities/get_chair_by_id_returns_the_stored_row_and_its_committed_minutes
        """
        suite, appointment = self._booked_chair(api)

        row = validate_success(
            api.get_chair(suite.chair_id("A1"), suite.nurse_headers), 200
        )

        assert appointment["chair_minutes"] == 240
        assert appointment["chair_id"] == suite.chair_id("A1")
        assert row["committed_minutes"] == 240


class TestAppointmentListingOrderAndFilters:
    """The declared ordering beats insertion order, and filters compose."""

    def _two_visits_on_one_chair(self, api: ApiClient):
        suite, late = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-14",
            requested_start_minute=540,
            appointment_overrides={"cycle_number": 2},
        )
        early = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        return suite, late, early

    def test_the_chair_filter_returns_both_visits_in_service_date_order(self, api):
        """The later date was booked first, yet the list comes back oldest service date
        first.

        Design: Corner/entities/list_appointments_filtered_by_chair_returns_the_declared_service_date_order
        """
        suite, late, early = self._two_visits_on_one_chair(api)

        response = api.list_appointments(
            SCHEDULER, {"chair_id": suite.chair_id("A1")}
        )

        rows, _meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert rows[0]["id"] == early["id"]
        assert rows[1]["id"] == late["id"]
        assert all(row["chair_id"] == suite.chair_id("A1") for row in rows)

    def test_adding_the_service_date_filter_narrows_the_same_list_to_one_row(self, api):
        """Two filters compose rather than replacing one another.

        Design: Corner/entities/list_appointments_filtered_by_chair_returns_the_declared_service_date_order
        """
        suite, late, _early = self._two_visits_on_one_chair(api)

        rows, _meta = validate_paginated(
            api.list_appointments(
                SCHEDULER,
                {"chair_id": suite.chair_id("A1"), "service_date": "2026-08-14"},
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == late["id"]

    def test_both_listed_rows_carry_the_same_window_arithmetic(self, api):
        """Same template, same start minute, different dates: identical windows.

        Design: Corner/entities/list_appointments_filtered_by_chair_returns_the_declared_service_date_order
        """
        suite, _late, _early = self._two_visits_on_one_chair(api)

        rows, _meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"chair_id": suite.chair_id("A1")})
        )

        for row in rows:
            assert row["chair_minutes"] == 240
            assert row["start_minute"] == 540
            assert row["end_minute"] == 780


class TestUnknownLotIdIsResolvedPerId:
    """A populated collection still answers 404 for an id it does not hold."""

    def _one_real_lot(self, api: ApiClient):
        drug = create_drug(api)
        return create_lot(
            api,
            drug["id"],
            lot_number="LOT-A",
            units_received=10,
            expires_on="2026-12-31T00:00:00Z",
        )

    def test_reading_an_id_the_collection_does_not_hold_names_the_lot_catalogue(self, api):
        """The 404 is the lot-specific member of the not-found catalogue.

        Design: Corner/entities/get_unknown_drug_lot_id_returns_lot_not_found
        """
        self._one_real_lot(api)

        response = api.get_drug_lot(NON_EXISTENT_UUID, PHARMACIST)

        validate_error(response, ApiErrorId.ERR_LOT_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"

    def test_the_real_lot_is_untouched_by_the_missed_lookup(self, api):
        """The refusal is per-id, not an empty-table shortcut.

        Design: Corner/entities/get_unknown_drug_lot_id_returns_lot_not_found
        """
        lot = self._one_real_lot(api)
        api.get_drug_lot(NON_EXISTENT_UUID, PHARMACIST)

        row = validate_success(api.get_drug_lot(lot["id"], PHARMACIST), 200)
        assert row["units_available"] == 10
        assert row["status"] == LotStatus.AVAILABLE


class TestPatientRegistrationRequiresAnMrn:
    """The one Patient input with no declared default."""

    def _without_mrn(self):
        payload = make_patient_payload()
        payload.pop("mrn")
        return payload

    def test_omitting_the_mrn_is_a_malformed_request(self, api):
        """A missing mandatory field is a request-shape failure, not a uniqueness one.

        Design: Corner/entities/create_patient_missing_required_mrn_returns_invalid_request
        """
        response = api.create_patient(self._without_mrn(), SCHEDULER)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_the_refused_registration_leaves_the_collection_empty(self, api):
        """Nothing is persisted by a rejected request.

        Design: Corner/entities/create_patient_missing_required_mrn_returns_invalid_request
        """
        api.create_patient(self._without_mrn(), SCHEDULER)

        rows, _meta = validate_paginated(api.list_patients(SCHEDULER))
        assert rows == []


class TestOmittedInputsTakeTheirDeclaredDefaults:
    """Defaults are applied server-side rather than left null."""

    def _minimal_estate(self, api: ApiClient):
        center = validate_success(
            api.create_center(make_minimal_center_payload(), SCHEDULER), 201
        )
        chair = validate_success(
            api.create_chair({"center_id": center["id"], "label": "A1"}, SCHEDULER), 201
        )
        return center, chair

    def test_a_centre_created_with_three_fields_carries_all_six_policy_dials(self, api):
        """Every dial the request omitted comes back at its declared default.

        Design: Corner/entities/omitting_optional_center_and_chair_inputs_applies_the_declared_defaults
        """
        center, _chair = self._minimal_estate(api)

        assert center["turnover_buffer_minutes"] == 15
        assert center["urgent_reserve_chair_count"] == 1
        assert center["addon_cutoff_minute"] == 900
        assert center["lab_validity_hours"] == 72
        assert center["stagger_grid_minutes"] == 15
        assert center["acuity_slot_minutes"] == 30

    def test_a_chair_created_with_two_fields_is_standard_available_and_unreserved(self, api):
        """The chair's three optional fields default and its load starts at zero.

        Design: Corner/entities/omitting_optional_center_and_chair_inputs_applies_the_declared_defaults
        """
        _center, chair = self._minimal_estate(api)

        assert chair["chair_type"] == ChairType.STANDARD
        assert chair["status"] == ChairStatus.AVAILABLE
        assert chair["reserved_for_urgent"] is False
        assert chair["committed_minutes"] == 0

    def test_adding_the_defaulted_chair_re_derives_the_centre_counters(self, api):
        """An unreserved AVAILABLE chair counts in the wider figure only.

        Design: Corner/entities/omitting_optional_center_and_chair_inputs_applies_the_declared_defaults
        """
        center, _chair = self._minimal_estate(api)

        row = read_center(api, center["id"])
        assert row["available_chair_count"] == 1
        assert row["reserved_chair_count"] == 0


class TestLotUnitCountersAreServerComputed:
    """The client supplies units_received and nothing else."""

    def _visit_and_lot(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-A",
            units_received=10,
            expires_on="2026-12-31T00:00:00Z",
        )
        return suite, appointment, lot

    def test_a_fresh_lot_already_carries_its_whole_computed_ledger(self, api):
        """Four counters at zero, availability equal to the receipt, status AVAILABLE.

        Design: Corner/entities/drug_lot_unit_counters_are_computed_and_never_accepted_from_the_client
        """
        _suite, _appointment, lot = self._visit_and_lot(api)

        assert lot["units_received"] == 10
        assert lot["units_committed"] == 0
        assert lot["units_administered"] == 0
        assert lot["units_wasted"] == 0
        assert lot["units_returned"] == 0
        assert lot["units_available"] == 10
        assert lot["status"] == LotStatus.AVAILABLE
        assert_drug_lot(lot)

    def test_committing_the_whole_holding_moves_the_counters_and_flips_the_status(self, api):
        """A dose request the client never binds to a lot commits every unit and depletes
        the row.

        Design: Corner/entities/drug_lot_unit_counters_are_computed_and_never_accepted_from_the_client
        """
        _suite, appointment, lot = self._visit_and_lot(api)

        prep = request_dose(api, appointment["id"], 10)

        assert prep["drug_lot_id"] == lot["id"]
        row = read_lot(api, lot["id"])
        assert row["units_committed"] == 10
        assert row["units_available"] == 0
        assert row["status"] == LotStatus.DEPLETED

    def test_the_new_dose_starts_unmixed_and_uncharged(self, api):
        """A dose is born in REQUESTED with nothing stamped on it yet.

        Design: Corner/entities/drug_lot_unit_counters_are_computed_and_never_accepted_from_the_client
        """
        _suite, appointment, _lot = self._visit_and_lot(api)

        prep = request_dose(api, appointment["id"], 10)

        assert prep["status"] == PreparationStatus.REQUESTED
        assert prep["waste_cost_cents"] == 0
        assert prep["prepared_at"] is None


class TestSystemStampedFieldsComeFromTheLogicalClock:
    """id, both instants and version are minted by the server."""

    def _chair_created_then_patched(self, api: ApiClient):
        set_clock(api, "2026-08-05T09:00:00Z")
        center = create_center(api)
        chair = create_chair(api, center["id"], "A1")
        set_clock(api, "2026-08-05T10:30:00Z")
        patched = validate_success(
            api.update_chair(chair["id"], {"status": ChairStatus.OUT_OF_SERVICE}, SCHEDULER),
            200,
        )
        return center, chair, patched

    def test_creation_stamps_both_instants_from_the_clock_at_version_one(self, api):
        """Insert-time created_at and updated_at are the same instant.

        Design: Corner/entities/system_stamped_timestamps_and_version_come_from_the_logical_clock
        """
        set_clock(api, "2026-08-05T09:00:00Z")
        center = create_center(api)

        chair = create_chair(api, center["id"], "A1")

        assert is_valid_uuid(chair["id"])
        # PRD 2.5 fixes the format of the audit instants and says updated_at is
        # "refreshed on every mutation of the row"; it never states which clock mints
        # them, so only the insert-time equality is asserted.
        assert is_iso8601_timestamp(chair["created_at"])
        assert chair["updated_at"] == chair["created_at"]
        assert chair["version"] == 1

    def test_a_later_patch_moves_updated_at_and_version_but_not_created_at(self, api):
        """The mutation reads the clock again; the birth instant is immutable.

        Design: Corner/entities/system_stamped_timestamps_and_version_come_from_the_logical_clock
        """
        _center, chair, patched = self._chair_created_then_patched(api)

        # PRD 2.5: updated_at is "refreshed on every mutation of the row" while
        # created_at is the row's birth instant and is never rewritten.
        assert patched["created_at"] == chair["created_at"]
        assert patched["updated_at"] != patched["created_at"]
        assert patched["version"] == 2

        row = read_chair(api, patched["id"])
        assert row["created_at"] == chair["created_at"]

    def test_taking_the_chair_out_of_service_re_derives_the_centre_counter(self, api):
        """The chair leaves the AVAILABLE set, so the centre's wider count falls back.

        Design: Corner/entities/system_stamped_timestamps_and_version_come_from_the_logical_clock
        """
        center, _chair, patched = self._chair_created_then_patched(api)

        assert patched["status"] == ChairStatus.OUT_OF_SERVICE
        assert read_center(api, center["id"])["available_chair_count"] == 0


class TestShapeViolationsAreRefusedBeforeAnyRowIsWritten:
    """Two shapes of the same request-shape rule."""

    def _center(self, api: ApiClient):
        return create_center(api)

    def test_a_chair_status_outside_the_declared_pair_is_malformed(self, api):
        """Serviceability is one of exactly two members.

        Design: Corner/entities/chair_enum_and_nurse_shift_range_violations_return_invalid_request
        """
        center = self._center(api)

        response = api.create_chair(
            {"center_id": center["id"], "label": "A1", "status": "BROKEN"}, SCHEDULER
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_a_shift_whose_start_is_not_before_its_end_is_malformed(self, api):
        """The shift bounds carry an ordering, and 900 through 480 breaks it.

        Design: Corner/entities/chair_enum_and_nurse_shift_range_violations_return_invalid_request
        """
        center = self._center(api)

        response = api.create_nurse(
            make_nurse_payload(center["id"], shift_start_minute=900, shift_end_minute=480),
            SCHEDULER,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_neither_refused_row_reaches_its_collection(self, api):
        """Both collections stay empty and the centre's counter never moves.

        Design: Corner/entities/chair_enum_and_nurse_shift_range_violations_return_invalid_request
        """
        center = self._center(api)
        api.create_chair(
            {"center_id": center["id"], "label": "A1", "status": "BROKEN"}, SCHEDULER
        )
        api.create_nurse(
            make_nurse_payload(center["id"], shift_start_minute=900, shift_end_minute=480),
            SCHEDULER,
        )

        chairs, _cm = validate_paginated(
            api.list_chairs(SCHEDULER, {"center_id": center["id"]})
        )
        nurses, _nm = validate_paginated(
            api.list_nurses(SCHEDULER, {"center_id": center["id"]})
        )
        assert chairs == []
        assert nurses == []
        assert read_center(api, center["id"])["available_chair_count"] == 0


class TestFiledLabDrawIsImmutable:
    """A correction is a new row, never a rewrite of the old one."""

    def _patient_with_a_first_draw(self, api: ApiClient):
        patient = create_patient(api)
        first = file_lab_result(
            api,
            patient["id"],
            collected_at="2026-07-30T08:00:00Z",
            anc_value=1.2,
            platelet_value=90,
        )
        return patient, first

    def _file_the_correction(self, api: ApiClient, patient_id: str):
        return validate_success(
            api.create_lab_result(
                make_lab_result_payload(
                    patient_id,
                    collected_at="2026-07-31T08:00:00Z",
                    anc_value=2.0,
                    platelet_value=150,
                ),
                PHARMACIST,
            ),
            201,
        )

    def test_the_correction_lands_as_a_distinct_later_row(self, api):
        """Both values present, so the new draw is filed RESULTED under its own id.

        Design: Corner/entities/lab_result_is_immutable_with_no_update_endpoint_and_no_version_field
        """
        patient, first = self._patient_with_a_first_draw(api)

        second = self._file_the_correction(api, patient["id"])

        assert second["id"] != first["id"]
        assert second["anc_value"] == pytest.approx(2.0, abs=0.005)
        assert second["platelet_value"] == pytest.approx(150, abs=0.005)
        assert second["status"] == LabResultStatus.RESULTED

    def test_the_original_draw_is_untouched_by_the_correction(self, api):
        """There is no update path onto a filed draw, so the first row still reads as
        filed.

        Design: Corner/entities/lab_result_is_immutable_with_no_update_endpoint_and_no_version_field
        """
        patient, first = self._patient_with_a_first_draw(api)
        self._file_the_correction(api, patient["id"])

        row = read_lab_result(api, first["id"])
        assert row["anc_value"] == pytest.approx(1.2, abs=0.005)
        assert row["platelet_value"] == pytest.approx(90, abs=0.005)
        assert row["status"] == LabResultStatus.RESULTED

    def test_a_draw_carries_neither_a_version_nor_an_updated_at(self, api):
        """This is the one resource kind that is never mutated, so it has no mutation
        bookkeeping at all.

        Design: Corner/entities/lab_result_is_immutable_with_no_update_endpoint_and_no_version_field
        """
        patient, first = self._patient_with_a_first_draw(api)
        second = self._file_the_correction(api, patient["id"])

        for row in (first, second, read_lab_result(api, first["id"])):
            assert "version" not in row
            assert "updated_at" not in row
            assert is_iso8601_timestamp(row["created_at"])

    def test_both_draws_remain_on_file_for_the_patient(self, api):
        """The correction adds to the history rather than replacing it.

        Design: Corner/entities/lab_result_is_immutable_with_no_update_endpoint_and_no_version_field
        """
        patient, first = self._patient_with_a_first_draw(api)
        second = self._file_the_correction(api, patient["id"])

        rows, _meta = validate_paginated(
            api.list_lab_results(PHARMACIST, {"patient_id": patient["id"]})
        )
        assert len(rows) == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


class TestBiosimilarLineageIsReachableThroughTheDrugFilter:
    """The self-reference is navigable only through the collection filter."""

    def _family(self, api: ApiClient):
        originator = create_drug(api)
        biosimilar = create_biosimilar(api, originator["id"])
        return originator, biosimilar

    def test_filtering_by_reference_product_returns_exactly_the_child(self, api):
        """One originator, one child, and the filter walks the self-reference forward.

        Design: Corner/entities/self_referential_reference_drug_id_is_discoverable_through_the_drug_filter
        """
        originator, biosimilar = self._family(api)

        rows, _meta = validate_paginated(
            api.list_drugs(PHARMACIST, {"reference_drug_id": originator["id"]})
        )

        assert len(rows) == 1
        assert rows[0]["id"] == biosimilar["id"]
        assert rows[0]["is_biosimilar"] is True
        assert rows[0]["reference_drug_id"] == originator["id"]

    def test_filtering_out_the_biosimilars_returns_exactly_the_originator(self, api):
        """The complementary filter selects the reference product on its own.

        Design: Corner/entities/self_referential_reference_drug_id_is_discoverable_through_the_drug_filter
        """
        originator, _biosimilar = self._family(api)

        rows, _meta = validate_paginated(
            api.list_drugs(PHARMACIST, {"is_biosimilar": "false"})
        )

        assert len(rows) == 1
        assert rows[0]["id"] == originator["id"]

    def test_the_originator_points_at_nothing(self, api):
        """A reference product carries no reference of its own.

        Design: Corner/entities/self_referential_reference_drug_id_is_discoverable_through_the_drug_filter
        """
        originator, _biosimilar = self._family(api)

        row = validate_success(api.get_drug(originator["id"], PHARMACIST), 200)
        assert row["is_biosimilar"] is False
        assert row["reference_drug_id"] is None


class TestBodyForeignKeysResolveInTheDeclaredInputOrder:
    """In a flat topology the owning row arrives as a body field."""

    UNKNOWN_DRUG_ID = "00000000-0000-0000-0000-0000000000dd"

    def test_an_unknown_owning_centre_on_a_chair_names_the_centre_catalogue(self, api):
        """A body foreign key answers with the 404 of the missing row's own collection.

        Design: Corner/entities/foreign_keys_in_the_request_body_are_validated_in_the_declared_input_order
        """
        create_drug(api)

        response = api.create_chair(
            {"center_id": NON_EXISTENT_UUID, "label": "A1"}, SCHEDULER
        )

        validate_error(response, ApiErrorId.ERR_CENTER_NOT_FOUND, 404)

    def test_two_unresolvable_keys_are_decided_by_the_input_order(self, api):
        """patient_id is declared before drug_id, so the patient catalogue answers first.

        Design: Corner/entities/foreign_keys_in_the_request_body_are_validated_in_the_declared_input_order
        """
        create_drug(api)

        response = api.create_treatment_plan(
            make_treatment_plan_payload(NON_EXISTENT_UUID, self.UNKNOWN_DRUG_ID),
            SCHEDULER,
        )

        body = validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)
        assert body["error_id"] != ApiErrorId.ERR_DRUG_NOT_FOUND

    def test_the_refused_regimen_was_never_opened(self, api):
        """Nothing is written by a request that failed on a foreign key.

        Design: Corner/entities/foreign_keys_in_the_request_body_are_validated_in_the_declared_input_order
        """
        create_drug(api)
        api.create_treatment_plan(
            make_treatment_plan_payload(NON_EXISTENT_UUID, self.UNKNOWN_DRUG_ID),
            SCHEDULER,
        )

        rows, _meta = validate_paginated(api.list_treatment_plans(SCHEDULER))
        assert rows == []
