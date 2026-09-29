"""What each registry row looks like the moment it is written and read back.

These tests hold the API to the record shapes it declares: the defaults a
registration applies when the client stays silent, the system-managed fields the
server mints for itself, the derived figures that are already current in the
creating response, the reduced property set the append-only event logs carry,
and the not-found codes an unresolvable identifier earns.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_LOT_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_3dp,
    assert_envelope_meta,
    assert_evidence_record,
    assert_listing_ids,
    assert_maneuver_acceptable,
    assert_page,
    assert_response_type,
    assert_version_is,
)
from test_helpers.constants import MORNING_CLOCK, UNKNOWN_UUID
from test_helpers.test_users import LAB_MANAGER


class TestStaffRegistryRecord:
    """A staff row answers with every declared field, defaults included."""

    def test_registration_applies_every_declared_default(self, api):
        """Silence on posture, capacity and control duty is answered by defaults.

        PRD 3.1: "A staff member's `status` is either `ON_DUTY` or `OFF_DUTY`
        and defaults to `ON_DUTY`; only `ON_DUTY` staff enter the interpreter
        candidate pool. `max_concurrent_reports` is that person's declared
        interpreting capacity, an integer of at least 1 defaulting to 1, and it
        is consulted twice — once by the candidate filter and once, summed
        across the roster, by the turnaround load tier."

        Design: Corner/entities/staff_creation_returns_every_declared_field_with_defaults_applied
        """
        fx.set_clock(api, MORNING_CLOCK)

        response = api.create_staff(
            {
                "employee_code": "R-001",
                "full_name": "Rhea Lund",
                "role_type": "INTERPRETING_PHYSICIAN",
                "credential": "MD",
                "competency_expires_on": "2027-06-30",
                "credentialed_modalities": ["SPIROMETRY", "DLCO"],
            },
            LAB_MANAGER,
        )
        staff = validate_success(response, expected_status=201)
        body = response.json()

        assert_envelope_meta(body)
        assert_response_type(body, "object")
        assert staff["employee_code"] == "R-001"
        assert staff["full_name"] == "Rhea Lund"
        assert staff["role_type"] == "INTERPRETING_PHYSICIAN"
        assert staff["credential"] == "MD"
        assert staff["competency_expires_on"] == "2027-06-30"
        assert staff["credentialed_modalities"] == ["SPIROMETRY", "DLCO"]
        assert staff["status"] == "ON_DUTY"
        assert staff["max_concurrent_reports"] == 1
        assert staff["is_biologic_control"] is False
        assert staff["open_report_count"] == 0
        assert_version_is(staff, 1)

    def test_the_system_managed_fields_are_minted_by_the_server(self, api):
        """Two registrations get distinct ids, version 1 and the clock's instant.

        PRD 2.5: "**`id`** (string): a server-minted UUID. It carries no type
        prefix of any kind." and "**`created_at`** (string): an ISO 8601 UTC
        timestamp with three fractional digits (for example
        `2026-08-01T09:15:00.000Z`), recorded from the logical clock at the
        moment the record was created." and "**`version`** (integer): starts at
        1 on creation and increments by exactly 1 on every mutation, again
        including server-initiated ones."

        Design: Corner/entities/staff_system_fields_are_server_minted_not_client_supplied
        """
        fx.set_clock(api, MORNING_CLOCK)

        first = fx.register_technologist(api)
        second = fx.register_ordering_physician(api)

        assert first["id"] != second["id"]
        for row in (first, second):
            assert_version_is(row, 1)
            assert row["created_at"] == "2026-08-03T08:00:00.000Z"
            assert row["updated_at"] == "2026-08-03T08:00:00.000Z"
            assert row["open_report_count"] == 0
            assert not row["id"].startswith("staff")

        reread = validate_success(api.get_staff(first["id"], LAB_MANAGER))
        assert reread["id"] == first["id"]
        assert reread["created_at"] == first["created_at"]
        assert_version_is(reread, 1)


class TestDeviceRegistryRecord:
    """A newly registered instrument has a status but no quality history."""

    def test_a_new_device_reads_back_with_an_empty_quality_dossier(self, api):
        """Every derived quality field is null or zero until an event exists.

        PRD 3.2: "It begins life in `status` `NEW`, with
        `sessions_since_filter_change` at 0 and `version` at 1."

        Design: Corner/entities/device_retrieval_returns_stored_row_with_null_quality_history
        """
        fx.set_clock(api, MORNING_CLOCK)
        registered = fx.register_device(api, "SPIRO-1", "SPIROMETRY")

        device = validate_success(api.get_device(registered["id"], LAB_MANAGER))

        assert device["id"] == registered["id"]
        assert device["device_code"] == "SPIRO-1"
        assert device["modality"] == "SPIROMETRY"
        assert device["status"] == "NEW"
        assert device["sessions_since_filter_change"] == 0
        assert_version_is(device, 1)
        assert device["last_calibration_at"] is None
        assert device["last_calibration_error_pct"] is None
        assert device["last_biologic_control_date"] is None
        assert device["consecutive_biologic_failures"] == 0
        assert device["current_filter_serial"] is None
        assert device["last_session_end_at"] is None
        assert device["quarantined_at"] is None
        assert device["quarantine_reason"] is None
        assert device["quarantine_trigger_staff_id"] is None

    def test_the_device_listing_pages_and_filters_by_modality(self, api):
        """Three instruments read back two at a time, then one by modality.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope described in
        §2.2." and "Unless a specific endpoint says otherwise, list results are
        ordered by `created_at` ascending — which, for the append-only event
        collections in this API, is also their append order."

        Design: Corner/entities/device_listing_paginates_and_filters_by_modality
        """
        fx.set_clock(api, MORNING_CLOCK)
        first = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
        second = fx.register_device(api, "SPIRO-2", "SPIROMETRY")
        third = fx.register_device(api, "DLCO-1", "DLCO")

        page_one, meta_one = validate_paginated(
            api.list_devices(LAB_MANAGER, limit=2, offset=0)
        )
        page_two, meta_two = validate_paginated(
            api.list_devices(LAB_MANAGER, limit=2, offset=2)
        )
        closed_circuit, meta_filtered = validate_paginated(
            api.list_devices(LAB_MANAGER, modality="DLCO")
        )

        assert_page(meta_one, total_count=3, has_more=True, limit=2, offset=0)
        assert_listing_ids(page_one, [first["id"], second["id"]])
        assert_page(meta_two, total_count=3, has_more=False, limit=2, offset=2)
        assert_listing_ids(page_two, [third["id"]])
        assert_page(meta_filtered, total_count=1, has_more=False)
        assert_listing_ids(closed_circuit, [third["id"]])
        assert closed_circuit[0]["device_code"] == "DLCO-1"


class TestUnresolvableIdentifiers:
    """An identifier that names no row earns that collection's own code."""

    def test_reading_an_unknown_study_reports_the_study_not_found_code(self, api):
        """A well-formed identifier with no study behind it is a 404.

        PRD 2.9: "**`{session_id}` resolves** — `ERR_SESSION_NOT_FOUND` (404),
        on every study route and every study sub-resource route."

        Design: Corner/entities/session_get_with_unknown_id_returns_session_not_found
        """
        fx.set_clock(api, MORNING_CLOCK)

        response = api.get_test_session(UNKNOWN_UUID, LAB_MANAGER)
        validate_error(response, ERR_SESSION_NOT_FOUND)
        body = response.json()

        assert_envelope_meta(body)
        assert_response_type(body, "error")

    def test_drafting_an_order_for_an_unknown_patient_reports_patient_not_found(self, api):
        """The body identifier is resolved and nothing is persisted.

        PRD 2.9: "Identifiers arriving in the **request body** are resolved
        after path identifiers, and among themselves in the fixed left-to-right
        order in which they are declared for that operation: `patient_id`, then
        `order_id`, then `device_id`, then `rescue_lot_id`, then
        `subject_staff_id`."

        Design: Corner/entities/order_creation_with_unknown_patient_id_returns_patient_not_found
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)

        validate_error(
            api.create_test_order(f.test_order_payload(UNKNOWN_UUID), roster.doc1),
            ERR_PATIENT_NOT_FOUND,
        )

        _, meta = validate_paginated(api.list_test_orders(LAB_MANAGER))
        assert_page(meta, total_count=0, has_more=False)


class TestPatientRegistryRecord:
    """A patient row is validated on its way in and derived on its way out."""

    def test_a_registration_missing_the_weight_is_refused_and_not_stored(self, api):
        """The medical record number is still free afterwards, so nothing landed.

        PRD 3.1: "A patient carries an `mrn` — the medical record number,
        non-empty and unique across patients, again with
        `ERR_DUPLICATE_IDENTIFIER` on collision — a `full_name`, a `birth_date`
        as a `YYYY-MM-DD` UTC calendar date, a `sex` of either `MALE` or
        `FEMALE`, a `height_cm` between 90.0 and 220.0 centimetres, a
        `weight_kg` between 10.0 and 300.0 kilograms, and a `smoking_status` of
        `NEVER`, `FORMER` or `CURRENT`."

        Design: Corner/entities/patient_creation_missing_weight_kg_is_rejected
        """
        fx.set_clock(api, MORNING_CLOCK)
        incomplete = f.patient_payload()
        del incomplete["weight_kg"]

        validate_error(api.create_patient(incomplete, LAB_MANAGER), ERR_INVALID_REQUEST)

        patient = validate_success(
            api.create_patient(f.patient_payload(), LAB_MANAGER), expected_status=201
        )
        assert patient["mrn"] == "MRN-7001"
        assert patient["weight_kg"] == 80.0

    def test_an_out_of_range_height_and_an_undeclared_smoking_status_are_refused(self, api):
        """Both a numeric bound and an enum membership are enforced on the way in.

        PRD 3.1: "A patient carries an `mrn` — the medical record number,
        non-empty and unique across patients, again with
        `ERR_DUPLICATE_IDENTIFIER` on collision — a `full_name`, a `birth_date`
        as a `YYYY-MM-DD` UTC calendar date, a `sex` of either `MALE` or
        `FEMALE`, a `height_cm` between 90.0 and 220.0 centimetres, a
        `weight_kg` between 10.0 and 300.0 kilograms, and a `smoking_status` of
        `NEVER`, `FORMER` or `CURRENT`."

        Design: Corner/entities/patient_out_of_range_height_and_undeclared_enum_are_rejected
        """
        fx.set_clock(api, "2026-08-03T08:00:00Z")

        validate_error(
            api.create_patient(f.patient_payload(height_cm=250.0), LAB_MANAGER),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_patient(f.patient_payload(smoking_status="VAPING"), LAB_MANAGER),
            ERR_INVALID_REQUEST,
        )

        patient = validate_success(
            api.create_patient(f.patient_payload(), LAB_MANAGER), expected_status=201
        )
        assert patient["mrn"] == "MRN-7001"
        assert patient["height_cm"] == 175.0
        assert patient["smoking_status"] == "FORMER"
        assert patient["age_years"] == 45

    def test_the_age_is_completed_whole_years_against_the_logical_date(self, api):
        """A birthday that has not yet come round does not add a year.

        PRD 3.1: "The server derives `age_years` as the number of completed
        whole years from `birth_date` to the current logical clock date: the
        difference in calendar years, reduced by one when the current
        month-and-day pair falls earlier than the birth month-and-day pair."

        Design: Corner/entities/patient_age_years_is_computed_from_birth_date_and_logical_clock
        """
        fx.set_clock(api, "2026-08-03T08:00:00Z")

        registered = validate_success(
            api.create_patient(
                f.patient_payload(birth_date="1981-03-15"), LAB_MANAGER
            ),
            expected_status=201,
        )
        assert registered["age_years"] == 45
        assert registered["height_cm"] == 175.0
        assert registered["weight_kg"] == 80.0
        assert registered["completed_order_count"] == 0

        fx.set_clock(api, "2027-03-14T08:00:00Z")
        day_before_the_birthday = validate_success(
            api.get_patient(registered["id"], LAB_MANAGER)
        )
        assert day_before_the_birthday["age_years"] == 45, (
            "14 March is earlier than 15 March, so the year is not yet complete"
        )


class TestTestOrderRecord:
    """An order fills in its three optional inputs and its own system fields."""

    def test_the_three_optional_inputs_take_their_declared_defaults(self, api):
        """A four-field request lands as a DRAFT with no reversal, agent or drugs.

        PRD 3.4: "Three optional inputs complete the picture:
        `bronchodilator_requested`, a boolean defaulting to false, states whether
        post-bronchodilator spirometry is wanted; `challenge_type`, defaulting to
        `NONE` and otherwise `METHACHOLINE` or `MANNITOL`, names the
        bronchoprovocation agent; and `current_medication_classes`, defaulting to
        the empty array, lists the respiratory medications the patient is
        currently taking as distinct values from `SABA`, `SAMA`, `LABA`, `LAMA`,
        `ICS_LABA`, `ANTIHISTAMINE` and `CAFFEINE`. The server records
        `ordering_staff_id` from the acting physician's `X-User-ID` header, sets
        `status` to `DRAFT`, `abort_count` to 0, and leaves `rejection_reason`,
        `hold_release_at` and `cancellation_reason` null."

        Design: Corner/entities/order_creation_applies_declared_defaults_for_omitted_optionals
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        patient = fx.register_patient(api)

        order = validate_success(
            api.create_test_order(
                {
                    "patient_id": patient["id"],
                    "indication_code": "DYSPNEA_EVALUATION",
                    "requested_modalities": ["SPIROMETRY"],
                    "test_context": "ROUTINE_CLINICAL",
                },
                roster.doc1,
            ),
            expected_status=201,
        )

        assert order["patient_id"] == patient["id"]
        assert order["bronchodilator_requested"] is False
        assert order["challenge_type"] == "NONE"
        assert order["current_medication_classes"] == []
        assert order["ordering_staff_id"] == roster.doc1_id
        assert order["status"] == "DRAFT"
        assert order["abort_count"] == 0
        assert order["rejection_reason"] is None
        assert order["hold_release_at"] is None
        assert order["cancellation_reason"] is None
        assert_version_is(order, 1)


class TestManeuverEventRecord:
    """An effort is an append-only row: no version, no update channel."""

    def test_an_effort_carries_only_an_id_and_a_creation_stamp(self, api):
        """A later effort in the same study leaves the earlier row untouched.

        PRD 2.5: "Three collections are append-only event logs rather than
        mutable resources, and they deliberately carry a reduced property set:
        `DeviceQualityEvent`, `Maneuver` and `CustodyEvent` each expose only `id`
        and `created_at`. For these three, both `updated_at` and `version` are
        absent from the record entirely — they are never written, never returned,
        and never incremented."

        Design: Corner/entities/maneuver_is_an_immutable_event_row_with_no_version_or_update_channel
        """
        lab = fx.build_lab(api)
        session = fx.build_scheduled_session(api, lab)

        first = fx.append_maneuver(
            api, session["id"], f.maneuver_payload(3.200, 2.400), lab.tech1
        )
        assert first["maneuver_index"] == 1
        assert_maneuver_acceptable(first)

        stored = validate_success(api.get_maneuver(first["id"], LAB_MANAGER))
        assert_evidence_record(stored)
        assert stored["created_at"] == "2026-08-03T08:00:00.000Z"

        fx.append_maneuver(
            api,
            session["id"],
            f.maneuver_payload(3.150, 2.250, pef_l_s=5.80,
                               back_extrapolated_volume_ml=120,
                               expiratory_time_s=16.0),
            lab.tech1,
        )

        unchanged = validate_success(api.get_maneuver(first["id"], LAB_MANAGER))
        assert_evidence_record(unchanged)
        assert_3dp(unchanged["fev1_l"], 2.400)
        assert unchanged["bev_limit_ml"] == 160
        assert_maneuver_acceptable(unchanged)

        closed = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert_3dp(closed["best_fev1_l"], 2.400)
        assert closed["acceptable_maneuver_count"] == 2


class TestChallengeRunLotReference:
    """The lot named in the body is resolved before its readiness is judged."""

    def test_a_body_identifier_that_names_no_lot_is_a_not_found_first(self, api):
        """An identifier belonging to a device does not resolve to a lot at all.

        PRD 2.9: "Each resolves to its own not-found code:
        `ERR_PATIENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
        `ERR_LOT_NOT_FOUND` and `ERR_STAFF_NOT_FOUND` respectively, all HTTP
        404."

        Design: Corner/entities/challenge_run_cross_aggregate_lot_reference_is_resolved_before_lot_readiness
        """
        lab = fx.build_lab(api)
        lot = fx.receive_rescue_lot(api)
        session = fx.build_session_with_maneuvers(
            api,
            lab,
            indication_code="ASTHMA_DIAGNOSIS",
            challenge_type="METHACHOLINE",
        )

        validate_error(
            api.create_challenge_run(
                session["id"], f.challenge_run_payload(lab.device_id), lab.tech1
            ),
            ERR_LOT_NOT_FOUND,
        )
        untouched = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert untouched["doses_reserved"] == 0

        run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)
        assert run["status"] == "ARMED"
        assert run["rescue_lot_id"] == lot["id"]

        reserved = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert reserved["doses_reserved"] == 4
        assert reserved["doses_remaining"] == 10

        _, meta = validate_paginated(
            api.list_challenge_runs(LAB_MANAGER, session_id=session["id"])
        )
        assert_page(meta, total_count=1, has_more=False)
