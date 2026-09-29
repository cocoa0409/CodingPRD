"""Declared defaults, parent scoping, immutability and per-aggregate 404s."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_counters,
    assert_immutable_record,
    assert_version_is,
)


class TestPracticeDefaults:
    def test_a_bare_practice_create_fills_in_every_declared_default(self, world):
        """PRD §3.1: "`weekend_is_after_hours`, which defaults to true and, when
        true, makes ISO weekday six (Saturday) and seven (Sunday) after-hours
        regardless of the time of day; `consent_recording_required`, which defaults
        to false; and `variance_review_threshold`, which defaults to 2 and must be at
        least one."

        Design: Corner/entities/create_practice_applies_every_declared_default_and_system_field
        """
        response = world.api.create_practice(
            f.practice_payload(
                name="Bare Minimum Clinic",
                weekend_is_after_hours=f.OMIT,
                consent_recording_required=f.OMIT,
                variance_review_threshold=f.OMIT,
                audit_period_start_utc=f.OMIT,
            ),
            world.admin,
        )

        practice = validate_success(response, 201)
        assert practice["weekend_is_after_hours"] is True
        assert practice["consent_recording_required"] is False
        assert practice["variance_review_threshold"] == 2

    def test_the_system_owned_fields_open_at_their_declared_values(self, world):
        """PRD §3.1: "A newly registered practice opens with `status` `ACTIVE`,
        `compliance_posture` `NORMAL`, and all five of `open_callback_count`,
        `open_variance_count`, `escalated_callback_count`,
        `billed_advice_minutes_total` and `advice_fee_accrued_cents` at zero."

        Design: Corner/entities/create_practice_applies_every_declared_default_and_system_field
        """
        practice = get_success_data(
            world.api.create_practice(
                f.practice_payload(
                    name="Bare Minimum Clinic",
                    weekend_is_after_hours=f.OMIT,
                    consent_recording_required=f.OMIT,
                    variance_review_threshold=f.OMIT,
                    audit_period_start_utc=f.OMIT,
                ),
                world.admin,
            )
        )

        assert practice["status"] == "ACTIVE"
        assert practice["compliance_posture"] == "NORMAL"
        assert_counters(
            practice,
            open_callback_count=0,
            open_variance_count=0,
            escalated_callback_count=0,
            billed_advice_minutes_total=0,
            advice_fee_accrued_cents=0,
        )
        assert_common_fields(practice)
        assert_version_is(practice, 1)


class TestPatientPanelScoping:
    def test_a_patient_takes_its_practice_from_the_panel_and_defaults_its_pregnancy_status(
        self, world
    ):
        """PRD §3.1: "`pregnancy_status`, one of `NOT_APPLICABLE`, `NOT_PREGNANT`,
        `PREGNANT` or `POSTPARTUM_6W`, defaulting to `NOT_APPLICABLE`".

        Design: Corner/entities/patient_creation_is_scoped_to_its_parent_practice_and_reads_back_unchanged
        """
        practice_a = world.create_practice(name="Northside Family Health")

        response = world.api.create_patient(
            practice_a["id"],
            f.patient_payload(pregnancy_status=f.OMIT),
            world.intake,
        )

        patient = validate_success(response, 201)
        assert patient["practice_id"] == practice_a["id"], (
            "the practice_id comes from the panel, never from the body"
        )
        assert patient["pregnancy_status"] == "NOT_APPLICABLE"

    def test_the_patient_reads_back_field_for_field(self, world):
        """PRD §3.1: "Adding one requires the patient's `full_name` (one to one
        hundred twenty characters) and `dob`, a calendar date in year-month-day form,
        which is the authoritative age source whenever a nurse chooses the confirmed
        scoring path."

        Design: Corner/entities/patient_creation_is_scoped_to_its_parent_practice_and_reads_back_unchanged
        """
        practice_a = world.create_practice(name="Northside Family Health")
        created = get_success_data(
            world.api.create_patient(
                practice_a["id"], f.patient_payload(), world.intake
            )
        )

        read_back = get_success_data(world.api.get_patient(created["id"], world.intake))

        assert read_back["full_name"] == "Dana Reyes"
        assert read_back["dob"] == "1990-03-15"
        assert read_back["mrn"] == "MRN-0001"
        assert read_back["practice_id"] == practice_a["id"]

    def test_another_practices_patient_is_invisible_to_the_first_panel(self, world):
        """PRD §3.1: "A panel read may be narrowed by `phone` or by `mrn`."

        Design: Corner/entities/patient_creation_is_scoped_to_its_parent_practice_and_reads_back_unchanged
        """
        practice_a = world.create_practice(name="Northside Family Health")
        practice_b = world.create_practice(
            name="Southside Pediatrics", per_minute_rate_millicents=3000
        )
        foreign = get_success_data(
            world.api.create_patient(
                practice_b["id"],
                f.patient_payload(
                    full_name="Other Practice Patient",
                    dob="1980-01-01",
                    sex="MALE",
                    phone="+14155559999",
                    mrn="MRN-9999",
                ),
                world.admin,
            )
        )
        assert foreign["practice_id"] == practice_b["id"]

        _, meta = validate_paginated(
            world.api.list_patients(practice_a["id"], world.intake, {"mrn": "MRN-9999"})
        )

        assert meta["total_count"] == 0


class TestProtocolListingPagination:
    @pytest.fixture
    def three_protocols(self, world):
        rows = []
        for code, title, severity in (
            ("PROTO_A", "Protocol Alpha", 20),
            ("PROTO_B", "Protocol Bravo", 40),
            ("PROTO_C", "Protocol Charlie", 60),
        ):
            rows.append(
                world.create_protocol(
                    code,
                    code=code,
                    title=title,
                    base_severity=severity,
                    infant_modifier_points=f.OMIT,
                )
            )
        return rows

    def test_total_count_spans_the_whole_set_while_has_more_tracks_the_page(
        self, world, three_protocols
    ):
        """PRD §2.3: "The `meta` object of a list response carries `limit` and `offset`
        as they were resolved for the request, `total_count` as the number of records
        matching the filters before paging, and `has_more` as a boolean that is true
        exactly when `offset` plus the number of records returned is still less than
        `total_count`."

        Design: Corner/entities/symptom_protocol_listing_reports_total_count_and_has_more_across_pages
        """
        alpha, _, _ = three_protocols

        page_one_rows, page_one_meta = validate_paginated(
            world.api.list_protocols(world.admin, {"limit": 2, "offset": 0})
        )
        page_two_rows, page_two_meta = validate_paginated(
            world.api.list_protocols(world.admin, {"limit": 2, "offset": 2})
        )

        assert page_one_meta["total_count"] == 3
        assert page_one_meta["has_more"] is True
        assert len(page_one_rows) == 2
        assert page_one_rows[0]["id"] == alpha["id"], (
            "ordering is created_at ascending"
        )
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False
        assert len(page_two_rows) == 1

    def test_the_code_filter_narrows_the_counted_set(self, world, three_protocols):
        """PRD §3.1: "Protocol listings may be narrowed by `status` and by `code`."

        Design: Corner/entities/symptom_protocol_listing_reports_total_count_and_has_more_across_pages
        """
        _, bravo, charlie = three_protocols

        rows, meta = validate_paginated(
            world.api.list_protocols(world.admin, {"code": "PROTO_B"})
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == bravo["id"]
        assert charlie["infant_modifier_points"] == 20, (
            "the omitted infant modifier takes its declared default"
        )
        assert charlie["status"] == "ACTIVE"


NOT_FOUND_CASES = [
    ("practices", ApiErrorId.ERR_PRACTICE_NOT_FOUND),
    ("nurses", ApiErrorId.ERR_NURSE_NOT_FOUND),
    ("patients", ApiErrorId.ERR_PATIENT_NOT_FOUND),
    ("symptom-protocols", ApiErrorId.ERR_PROTOCOL_NOT_FOUND),
    ("triage-calls", ApiErrorId.ERR_TRIAGE_CALL_NOT_FOUND),
    ("protocol-assessments", ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
    ("dispositions", ApiErrorId.ERR_DISPOSITION_NOT_FOUND),
    ("callback-tasks", ApiErrorId.ERR_CALLBACK_TASK_NOT_FOUND),
    ("warm-transfers", ApiErrorId.ERR_WARM_TRANSFER_NOT_FOUND),
    ("coverage-windows", ApiErrorId.ERR_COVERAGE_WINDOW_NOT_FOUND),
]


class TestAggregateSpecificNotFound:
    @pytest.mark.parametrize("collection,error_id", NOT_FOUND_CASES)
    def test_each_aggregate_answers_with_its_own_not_found_error(
        self, world, collection, error_id
    ):
        """PRD §2.12: "4. `ERR_PRACTICE_NOT_FOUND` — no practice with that identifier
        exists. Guards any endpoint carrying a practice identifier in its path or
        body."

        Design: Corner/entities/unknown_ids_return_the_aggregate_specific_not_found_error
        """
        unknown = "00000000-0000-0000-0000-0000000000ff"

        response = world.api._request(
            "GET", f"/{collection}/{unknown}", None, world.admin
        )

        validate_error(response, error_id, 404)


class TestPracticeRequiredFieldsAndEnums:
    def test_a_missing_required_field_is_an_invalid_request(self, world):
        """PRD §2.12: "3. `ERR_INVALID_REQUEST` — the request is malformed. Guards
        every write endpoint. It fires when a required input field is missing; when an
        enum field carries a value outside its declared set".

        Design: Corner/entities/create_practice_without_required_fields_and_with_a_bad_enum_is_rejected
        """
        response = world.api.create_practice(
            f.practice_payload(
                name="No Rate Clinic", per_minute_rate_millicents=f.OMIT
            ),
            world.admin,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_a_non_member_status_enum_is_rejected_without_persisting(self, world):
        """PRD §3.1: "A practice's contract state is a two-value enumeration,
        `ACTIVE` or `SUSPENDED`, and operations can flip it either way by supplying a
        new `status`; the flip bumps the practice's `version`."

        Design: Corner/entities/create_practice_without_required_fields_and_with_a_bad_enum_is_rejected
        """
        practice = world.create_practice()

        response = world.api.patch_practice_status(
            practice["id"], f.practice_status_payload("PAUSED"), world.admin
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        after = world.practice(practice["id"])
        assert after["status"] == "ACTIVE"
        assert_version_is(after, 1)
        assert after["per_minute_rate_millicents"] == 4225


class TestNurseLicenceImmutability:
    def test_a_licence_carries_no_version_or_updated_at(self, world):
        """PRD §2.5: "Three resources are immutable once written and therefore carry
        only `id` and `created_at` — they have no `updated_at` field and no `version`
        field at all: `NurseLicense`, `NurseShift`, and `ComplianceAuditRecord`."

        Design: Corner/entities/nurse_license_is_immutable_and_exposes_no_version_field
        """
        world.set_clock("2026-08-03T14:30:00Z")
        world.create_nurse("nurse_a", max_concurrent_calls=f.OMIT, high_risk_cap=f.OMIT)

        response = world.api.create_license(
            world.nurse_id("nurse_a"), f.license_payload(), world.admin
        )

        licence = validate_success(response, 201)
        assert_immutable_record(licence)

    def test_licence_status_is_derived_per_licence_and_filterable(self, world):
        """PRD §3.2: "A licence's `status` is never stored: it is computed at every
        read and at every eligibility evaluation as `ACTIVE` when `expires_on` is on
        or after the calendar date of the logical clock, and `EXPIRED` otherwise."

        Design: Corner/entities/nurse_license_is_immutable_and_exposes_no_version_field
        """
        world.set_clock("2026-08-03T14:30:00Z")
        world.create_nurse("nurse_a")
        california = world.add_license(
            "nurse_a", state_code="CA", license_number="CA-11111", expires_on="2027-01-31"
        )
        nevada = world.add_license(
            "nurse_a", state_code="NV", license_number="NV-22222", expires_on="2026-07-31"
        )

        rows, meta = validate_paginated(
            world.api.list_licenses(
                world.nurse_id("nurse_a"), world.admin, {"state_code": "CA"}
            )
        )

        assert california["status"] == "ACTIVE"
        assert nevada["status"] == "EXPIRED"
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "ACTIVE"


class TestNurseComputedCounters:
    def test_a_bare_nurse_starts_at_the_declared_counter_values(self, world):
        """PRD §3.2: "A fresh nurse starts with `active_call_load` at zero,
        `pending_high_risk_count` at zero, and `intake_eligibility` at
        `ON_ROTATION`."

        Design: Corner/entities/nurse_defaults_and_computed_counters_start_at_their_declared_values
        """
        response = world.api.create_nurse(
            f.nurse_payload(
                full_name="Nora Vance",
                seniority_level=3,
                max_concurrent_calls=f.OMIT,
                high_risk_cap=f.OMIT,
            ),
            world.admin,
        )

        nurse = validate_success(response, 201)
        assert nurse["active_call_load"] == 0
        assert nurse["pending_high_risk_count"] == 0
        assert nurse["intake_eligibility"] == "ON_ROTATION"
        assert nurse["seniority_level"] == 3
        assert_version_is(nurse, 1)
