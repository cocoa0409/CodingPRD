"""Entity creation defaults, response envelope, retrieval, pagination,
not-found, input shape, and immediate read-after-write consistency.

PRD 2.2 (envelope), 2.3 (pagination), 2.4 (common fields), 2.8 (path
validation), 2.10 (immediate consistency), 3.1 (agency/home), 3.2
(individuals).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    create_agency_payload,
    create_incident_payload,
    create_individual_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_enrolled_individual,
    setup_home,
    setup_staff,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestAgencyCreationDefaults:
    """Agency defaults and server-minted fields (PRD 3.1, 2.4)."""

    def test_optional_ratio_fields_default(self, api):
        """PRD 3.1: "An `AgencyAdmin` creates the agency by supplying the
        agency's legal `name` and, optionally, three tuning parameters:
        `day_staff_ratio` ... (default 4), `night_staff_ratio` ... (default 8),
        and `evv_grace_minutes` ... (default 15)."

        Design: Corner/entities/agency_creation_applies_defaults_and_system_fields
        """
        agency = get_success_data(api.create_agency(create_agency_payload(), ADMIN))
        assert agency["day_staff_ratio"] == 4
        assert agency["night_staff_ratio"] == 8
        assert agency["evv_grace_minutes"] == 15

    def test_computed_counters_initialized_to_zero(self, api):
        """PRD 3.1: "On creation the agency's three computed counters are
        initialized to zero: `cash_collected_cents`,
        `recoupment_balance_cents`, and `held_claims_count`."

        Design: Corner/entities/agency_creation_applies_defaults_and_system_fields
        """
        agency = get_success_data(api.create_agency(create_agency_payload(), ADMIN))
        assert agency["cash_collected_cents"] == 0
        assert agency["recoupment_balance_cents"] == 0
        assert agency["held_claims_count"] == 0
        assert agency["version"] == 1

    def test_id_and_timestamps_are_server_minted(self, api):
        """PRD 2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with
        three fractional digits."

        Design: Corner/entities/agency_creation_applies_defaults_and_system_fields
        """
        agency = get_success_data(api.create_agency(create_agency_payload(), ADMIN))
        assert is_valid_uuid(agency["id"])
        assert is_iso8601_timestamp(agency["created_at"])


class TestAgencyMissingName:
    """Required field omission rejected (PRD 3.1)."""

    def test_create_agency_without_name_rejected(self, api):
        """PRD 3.1: "An `AgencyAdmin` creates the agency by supplying the
        agency's legal `name`" — omitting it fails input shape validation with
        `ERR_INVALID_REQUEST` (PRD 2.6 input-shape checks: "required fields").

        Design: Corner/entities/agency_create_missing_required_name_rejected
        """
        resp = api.create_agency({"day_staff_ratio": 4}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUnknownRequestFieldRejected:
    """Client-supplied computed fields rejected as unknown (PRD 2.6)."""

    def test_computed_field_in_create_body_rejected(self, api):
        """PRD 2.6: input-shape checks reject "unknown fields".
        `cash_collected_cents` is a server-computed counter (PRD 3.1), so a
        client supplying it sends an unknown field.

        Design: Corner/entities/unknown_request_field_input_ignored_rejected
        """
        resp = api.create_agency(
            {"name": "Agency A", "cash_collected_cents": 999999}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestIndividualRetrieval:
    """GET individual returns stored fields and initial state (PRD 3.2)."""

    def test_get_returns_supplied_fields(self, api):
        """PRD 3.2: "A `CaseManager` registers a new individual by supplying
        `agency_id`, `legal_name`, `medicaid_id`, `date_of_birth`, and
        `mobility_level`."

        Design: Corner/entities/individual_retrieval_returns_stored_fields
        """
        agency = setup_agency()
        cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
        ind = get_success_data(api.create_individual(
            create_individual_payload(
                agency["id"], legal_name="Ind One", medicaid_id="MCD-001",
                mobility_level="WHEELCHAIR",
            ),
            make_case_manager_headers(cm["id"]),
        ))
        fetched = validate_success(api.get_individual(ind["id"], ANY))
        assert fetched["legal_name"] == "Ind One"
        assert fetched["medicaid_id"] == "MCD-001"
        assert fetched["mobility_level"] == "WHEELCHAIR"

    def test_initial_state_applicant_with_null_enrolled_at(self, api):
        """PRD 3.2: "A newly registered individual starts in `APPLICANT`
        status." `enrolled_at` is set only "on enroll" (PRD 3.2), so it is
        absent before enrollment.

        Design: Corner/entities/individual_retrieval_returns_stored_fields
        """
        agency = setup_agency()
        cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
        ind = get_success_data(api.create_individual(
            create_individual_payload(agency["id"]),
            make_case_manager_headers(cm["id"]),
        ))
        fetched = validate_success(api.get_individual(ind["id"], ANY))
        assert fetched["status"] == "APPLICANT"
        assert fetched.get("enrolled_at") is None


class TestIndividualNotFound:
    """Unknown id yields ERR_NOT_FOUND (PRD 2.8)."""

    def test_get_nonexistent_individual_404(self, api):
        """PRD 2.8: "Any id that fails to resolve (or any body foreign-key id
        that does not reference an existing resource) yields `ERR_NOT_FOUND`
        (HTTP 404), or a resource-specific variant where one is named for the
        endpoint.".

        Design: Corner/entities/individual_get_nonexistent_id_not_found
        """
        setup_agency()
        resp = api.get_individual(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_nonexistent_individual_404_second_probe(self, api):
        """PRD 2.8: "Any id that fails to resolve (or any body foreign-key id
        that does not reference an existing resource) yields `ERR_NOT_FOUND`
        (HTTP 404)". A fresh database per test means the well-formed unknown
        UUID never resolves.

        Design: Corner/entities/individual_get_nonexistent_id_not_found
        """
        resp = api.get_individual(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ANY,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestIndividualInvalidEnum:
    """mobility_level enum validity (PRD 3.2)."""

    def test_invalid_mobility_level_rejected(self, api):
        """PRD 3.2: "The `mobility_level` is one of `AMBULATORY`, `ASSIST`, or
        `WHEELCHAIR`" — other values fail enum validity (PRD 2.6 input-shape
        checks: "enum validity") with `ERR_INVALID_REQUEST`.

        Design: Corner/entities/individual_create_invalid_enum_rejected
        """
        agency = setup_agency()
        cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
        resp = api.create_individual(
            create_individual_payload(agency["id"], mobility_level="FLOATING"),
            make_case_manager_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestIndividualsListPagination:
    """Pagination envelope behavior (PRD 2.3)."""

    def _setup_three_individuals(self, api):
        agency = setup_agency()
        cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
        cm_h = make_case_manager_headers(cm["id"])
        for name, mob, mcd in [
            ("Ind A", "AMBULATORY", "MCD-101"),
            ("Ind B", "ASSIST", "MCD-102"),
            ("Ind C", "WHEELCHAIR", "MCD-103"),
        ]:
            get_success_data(api.create_individual(
                create_individual_payload(
                    agency["id"], legal_name=name, medicaid_id=mcd, mobility_level=mob,
                ), cm_h,
            ))
        return agency

    def test_first_page_carries_pagination_meta(self, api):
        """PRD 2.3: "List responses populate the `meta` block with the fields
        `limit`, `offset`, `total_count`, and `has_more`".

        Design: Corner/entities/individuals_list_pagination_envelope
        """
        agency = self._setup_three_individuals(api)
        data, meta = validate_paginated(api.list_individuals(
            ANY, params={"agency_id": agency["id"], "limit": 2, "offset": 0},
        ))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_second_page_marks_end_of_results(self, api):
        """PRD 2.3: "a client can page deterministically through a result set"
        with limit/offset.

        Design: Corner/entities/individuals_list_pagination_envelope
        """
        agency = self._setup_three_individuals(api)
        data, meta = validate_paginated(api.list_individuals(
            ANY, params={"agency_id": agency["id"], "limit": 2, "offset": 2},
        ))
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestEnrollEndpointEnvelope:
    """Action endpoints return the mutated resource in the envelope (PRD 2.2)."""

    def test_enroll_response_envelope_and_mutated_fields(self, api):
        """PRD 2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD 3.2: "Successful enrollment sets `enrolled_at` to the
        current server clock and increments the individual's `version`."

        Design: Corner/endpoints/action_endpoint_returns_mutated_entity_in_envelope
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        ind = get_success_data(api.create_individual(
            create_individual_payload(agency["id"]),
            make_case_manager_headers(cm["id"]),
        ))
        enrolled = validate_success(api.enroll_individual(
            ind["id"], make_qidp_headers(q["id"]),
        ))
        assert enrolled["status"] == "ENROLLED"
        assert enrolled["enrolled_at"] is not None
        assert enrolled["version"] == ind["version"] + 1


class TestImmediateReadAfterWrite:
    """Computed fields visible in the same response; cross-entity writes
    visible on the next read (PRD 2.10).
    """

    def test_submit_response_carries_computed_fields(self, api):
        """PRD 2.10: "These recomputations are immediate and transactional with
        the triggering mutation". PRD 3.7: "On submission the server stamps
        `submitted_at` to now and computes `report_due_at`".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        base = setup_agency_with_clinical_staff()
        home = setup_home(base["agency"], certified_bed_count=2)
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-02T09:00:00Z")
        inc = get_success_data(api.create_incident(
            create_incident_payload(
                ind["id"], home["id"], category="ABUSE_ALLEGATION",
                description="Allegation reported by family member",
            ),
            make_dsp_headers(base["d1"]["id"]),
        ))
        submitted = get_success_data(api.submit_incident(
            inc["id"], make_dsp_headers(base["d1"]["id"]),
        ))
        assert_same_instant(
            submitted["report_due_at"], "2026-06-03T08:30:00Z", "report_due_at",
        )
        assert submitted["is_late"] is False

    def test_next_get_shows_critical_posture(self, api):
        """PRD 2.10: "readers never observe an intermediate state in which a
        counter is stale relative to its underlying records." PRD 2.11: "The
        posture is recomputed immediately on incident submission".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        base = setup_agency_with_clinical_staff()
        home = setup_home(base["agency"], certified_bed_count=2)
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-02T09:00:00Z")
        inc = get_success_data(api.create_incident(
            create_incident_payload(
                ind["id"], home["id"], category="ABUSE_ALLEGATION",
                description="Allegation reported by family member",
            ),
            make_dsp_headers(base["d1"]["id"]),
        ))
        get_success_data(api.submit_incident(inc["id"], make_dsp_headers(base["d1"]["id"])))
        home_after = get_success_data(api.get_home(home["id"], ANY))
        assert home_after["compliance_posture"] == "CRITICAL"
