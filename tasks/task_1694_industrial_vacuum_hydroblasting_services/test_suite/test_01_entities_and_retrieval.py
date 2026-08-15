"""Entity creation defaults, system fields, retrieval and listing behavior."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_site,
    create_disposal_facility_payload,
    create_equipment_unit_payload,
    create_job_payload,
    create_site_payload,
    create_waste_profile_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteCreationDefaults:
    def test_site_creation_applies_credit_default(self, api, account_manager_headers):
        """PRD §3.1: "When omitted, `credit_status` defaults to `GOOD_STANDING`".

        Design: Corner/entities/site_creation_applies_defaults
        """
        data = get_success_data(api.create_site(create_site_payload(), account_manager_headers))
        assert data["credit_status"] == "GOOD_STANDING"
        assert data["active_rate_schedule_id"] is None
        assert_site(data)

    def test_site_creation_null_schedule_and_version_one(self, api, account_manager_headers,
                                                         project_manager_headers):
        """PRD §3.1: "A new site's `active_rate_schedule_id` stays empty until the
        first schedule activation."
        PRD §2.4: "`version`: an integer that increments by one on every mutation
        of the resource."

        Design: Corner/entities/site_creation_applies_defaults
        """
        created = get_success_data(api.create_site(create_site_payload(), account_manager_headers))
        assert created["version"] == 1
        fetched = get_success_data(api.get_site(created["id"], project_manager_headers))
        assert fetched["credit_status"] == "GOOD_STANDING"
        assert fetched["active_rate_schedule_id"] is None
        assert fetched["version"] == 1


class TestSystemFields:
    def test_server_minted_id_version_and_logical_clock_timestamp(
        self, api, platform_admin_headers
    ):
        """PRD §2.5: "Before it has ever been set, the logical clock reads exactly
        2026-08-01T00:00:00Z".
        PRD §2.4: "`created_at`: an ISO 8601 UTC timestamp with three fractional
        digits, fixed at creation." "`version`: an integer that increments by one
        on every mutation of the resource."

        Design: Corner/entities/system_fields_minted_by_server_at_logical_clock
        """
        data = get_success_data(
            api.create_equipment_unit(
                create_equipment_unit_payload(unit_code="VAC-09"), platform_admin_headers
            )
        )
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00.000Z"
        assert is_iso8601_timestamp(data["created_at"])


class TestJobPinsRateSchedule:
    def test_job_pins_active_schedule_at_creation(self, api, account_manager_headers,
                                                  project_manager_headers):
        """PRD §3.2: "Creation pins the site's currently active schedule into the
        job's `pinned_rate_schedule_id`."

        Design: Corner/entities/job_pins_rate_schedule_at_creation
        """
        from test_helpers import create_site_with_active_schedule, create_job
        site, sched = create_site_with_active_schedule()
        job = create_job(site["id"])
        assert job["pinned_rate_schedule_id"] == sched["id"]

    def test_later_schedule_activation_does_not_retarget_existing_job(
        self, api, account_manager_headers, project_manager_headers
    ):
        """PRD §3.2: "a mid-flight schedule amendment at the site never reprices
        an existing job."
        PRD §3.1: "whichever schedule of that site was previously `ACTIVE` moves
        to `SUPERSEDED`".

        Design: Corner/entities/job_pins_rate_schedule_at_creation
        """
        from test_helpers import (
            create_rate_schedule_payload,
            create_site_with_active_schedule,
            create_job,
        )
        site, sched1 = create_site_with_active_schedule()
        job = create_job(site["id"])
        assert job["pinned_rate_schedule_id"] == sched1["id"]

        sched2 = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(
                    site["id"], label="S2", vacuum_per_gallon_cents=999,
                    minimum_invoice_cents=1,
                ),
                account_manager_headers,
            )
        )
        site_now = get_success_data(api.get_site(site["id"], account_manager_headers))
        get_success_data(
            api.activate_rate_schedule(
                sched2["id"], {"expected_site_version": site_now["version"]},
                account_manager_headers,
            )
        )
        job_after = get_success_data(api.get_job(job["id"], project_manager_headers))
        assert job_after["pinned_rate_schedule_id"] == sched1["id"]
        sched1_after = get_success_data(
            api.get_rate_schedule(sched1["id"], account_manager_headers)
        )
        assert sched1_after["status"] == "SUPERSEDED"


class TestRequestShapeValidation:
    def test_missing_required_field_returns_invalid_request(
        self, api, project_manager_headers
    ):
        """PRD §2.8: "Request shape — required fields are present, types are
        valid, enum membership is valid ... else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_missing_required_field_returns_invalid_request
        """
        from test_helpers import create_site_with_active_schedule
        site, _ = create_site_with_active_schedule()
        resp = api.create_job(
            {"site_id": site["id"], "job_type": "VACUUM", "description": "no pricing mode"},
            project_manager_headers,
        )
        assert resp.status_code == 400
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_invalid_enum_value_rejected(self, api, project_manager_headers):
        """PRD §2.8: "enum membership is valid ... else `ERR_INVALID_REQUEST`."
        PRD §3.2: "the `job_type` (`VACUUM`, `HYDROBLAST` or `COMBINED`)".

        Design: Corner/entities/entity_invalid_enum_value_rejected
        """
        from test_helpers import create_site_with_active_schedule
        site, _ = create_site_with_active_schedule()
        resp = api.create_job(
            create_job_payload(site["id"], job_type="SANDBLAST"),
            project_manager_headers,
        )
        assert resp.status_code == 400
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestNotFound:
    def test_get_job_with_unknown_id_not_found(self, api, project_manager_headers):
        """PRD §2.8: "Existence — path identifiers and body foreign keys reference
        existing resources, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_get_with_unknown_id_not_found
        """
        resp = api.get_job(NON_EXISTENT_UUID, project_manager_headers)
        assert resp.status_code == 404
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestWasteProfileRetrieval:
    def test_profile_get_echoes_stored_fields(self, api, account_manager_headers,
                                              platform_admin_headers,
                                              compliance_officer_headers,
                                              project_manager_headers):
        """PRD §3.6: "A `ComplianceOfficer` drafts a profile naming the generator
        `site_id`, the contracted `facility_id`, a `waste_code`, the
        `hazard_class` ..., the characterized `density_lbs_per_gal` ..., the
        contracted `disposal_rate_per_ton_cents`, and the `variance_basis`."

        Design: Corner/entities/waste_profile_retrieval_echoes_stored_fields
        """
        site = get_success_data(api.create_site(create_site_payload(), account_manager_headers))
        facility = get_success_data(
            api.create_disposal_facility(create_disposal_facility_payload(), platform_admin_headers)
        )
        profile = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(
                    site["id"], facility["id"],
                    density_lbs_per_gal=8.345, variance_basis="VOLUME",
                ),
                compliance_officer_headers,
            )
        )
        fetched = get_success_data(api.get_waste_profile(profile["id"], project_manager_headers))
        assert fetched["density_lbs_per_gal"] == pytest.approx(8.345)
        assert fetched["variance_basis"] == "VOLUME"
        assert fetched["disposal_rate_per_ton_cents"] == 35000
        assert fetched["status"] == "DRAFT"


class TestJobsPagination:
    def test_jobs_list_paginates_with_envelope(self, api, project_manager_headers):
        """PRD §2.3: "`limit` controls the page size ... `offset` controls how
        many items are skipped before the page begins and defaults to 0. ... The
        `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/jobs_list_paginates_with_envelope
        """
        from test_helpers import create_site_with_active_schedule, create_job
        site, _ = create_site_with_active_schedule()
        for i in range(3):
            create_job(site["id"], description=f"J{i+1}",
                       job_type="HYDROBLAST" if i == 2 else "VACUUM",
                       pricing_mode="TIME_AND_MATERIALS" if i == 2 else "UNIT_RATE")

        page1_resp = api.list_jobs(
            project_manager_headers,
            params={"site_id": site["id"], "limit": 2, "offset": 0},
        )
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2_resp = api.list_jobs(
            project_manager_headers,
            params={"site_id": site["id"], "limit": 2, "offset": 2},
        )
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
