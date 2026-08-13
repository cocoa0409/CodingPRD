"""Entity shape, immutability, defaults, existence, and list envelope claims."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_crew_entry,
    add_delivery,
    add_weather_observation,
    create_crew_entry_payload,
    create_daily_report_payload,
    create_weather_observation_payload,
    make_active_project,
    make_delivery_zone,
    make_report,
    make_work_area,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SUPT = TEST_USERS["superintendent_headers"]
_PM = TEST_USERS["project_manager_headers"]


class TestEntityShapes:
    def test_weather_observation_is_append_only_without_version(self, api):
        """PRD section 2.4: "A weather observation is an immutable, append-only
        log entry: it carries `id` and `created_at` only, and both `updated_at`
        and `version` are absent from it, because a weather observation is never
        edited, voided, or transitioned after it is recorded."

        Design: Corner/entities/weather_observation_immutable_no_version_field
        """
        project = make_active_project()
        report = make_report(project["id"])

        created = validate_success(api.create_weather_observation(
            create_weather_observation_payload(
                report["id"], observed_at="2026-08-05T08:00:00Z", condition="RAIN",
                work_impact="PARTIAL", temperature_f=45.5),
            _SUPT), 201)
        assert "id" in created and "created_at" in created
        assert "version" not in created, "WeatherObservation must not carry version"
        assert "updated_at" not in created, "WeatherObservation must not carry updated_at"

        fetched = validate_success(
            api.get_weather_observation(created["id"], _ADMIN))
        assert fetched["condition"] == "RAIN"
        assert fetched["temperature_f"] == pytest.approx(45.5)
        assert fetched["work_impact"] == "PARTIAL"
        assert "version" not in fetched and "updated_at" not in fetched

    def test_crew_entry_missing_worker_count_rejected(self, api):
        """PRD section 2.9: "Required fields must be present, types must match,
        enum members must be valid, and numeric ranges must be honored";
        violations yield `ERR_INVALID_REQUEST`. PRD section 3.3: "Each crew entry
        names its `report_id` and `work_area_id`, the `subcontractor` and `trade`,
        a `worker_count` of at least one".

        Design: Corner/entities/crew_entry_required_field_missing_returns_invalid_request
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        payload = create_crew_entry_payload(report["id"], area["id"])
        del payload["worker_count"]
        resp = api.create_crew_entry(payload, _SUPT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

        rows, meta = validate_paginated(
            api.list_crew_entries(_SUPT, params={"report_id": report["id"]}))
        assert rows == [] and meta["total_count"] == 0

    def test_delivery_partition_defaults_and_zone_buffer_default(self, api):
        """PRD section 3.6: "a new delivery starts in `DELIVERED` status with
        `accepted_qty` and `rejected_qty` at zero and `pending_recount_qty`
        initialized to the full `delivered_qty`." PRD section 3.1: "a
        `buffer_minutes` value defaulting to 30 and never negative".

        Design: Corner/entities/delivery_pending_recount_defaults_to_delivered_qty
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"])  # no buffer_minutes supplied
        report = make_report(project["id"])

        delivery = add_delivery(report["id"], zone["id"], delivered_qty=40,
                                unit="LF", material_description="Pipe")
        assert delivery["status"] == "DELIVERED"
        assert delivery["accepted_qty"] == pytest.approx(0)
        assert delivery["rejected_qty"] == pytest.approx(0)
        assert delivery["pending_recount_qty"] == pytest.approx(40)

        fetched_zone = validate_success(api.get_delivery_zone(zone["id"], _ADMIN))
        assert fetched_zone["buffer_minutes"] == 30, \
            "buffer_minutes must default to 30 when omitted"

    def test_get_nonexistent_report_returns_report_not_found(self, api):
        """PRD section 2.10: "a missing daily report `ERR_REPORT_NOT_FOUND`";
        "All of these are HTTP 404."

        Design: Corner/entities/get_nonexistent_report_returns_not_found
        """
        resp = api.get_daily_report(NON_EXISTENT_UUID, _SUPT)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)
        assert resp.status_code == 404


class TestListEnvelope:
    def test_daily_report_list_pagination_envelope(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10, and accepts values from a minimum of 1 to
        a maximum of 100." and "Paginated list responses carry four fields in
        the `meta` object of the envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/daily_report_list_pagination_envelope
        """
        project = make_active_project()
        for date in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_report(project["id"], report_date=date)

        page1, meta1 = validate_paginated(api.list_daily_reports(
            _PM, params={"project_id": project["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_daily_reports(
            _PM, params={"project_id": project["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestReportInitialState:
    def test_report_born_draft_editable(self, api):
        """PRD section 3.2: "A new report is born in `DRAFT` status with
        `content_posture` `EDITABLE`, a `revision_count` of zero, and empty
        computed totals." PRD section 3.9: "A report's `retention_class` is
        `STANDARD` by default".

        Design: Corner/state_machines/report_initial_state_is_draft
        """
        project = make_active_project()
        report = make_report(project["id"], report_date="2026-08-05")

        assert report["status"] == "DRAFT"
        assert report["content_posture"] == "EDITABLE"
        assert report["revision_count"] == 0
        assert report["retention_class"] == "STANDARD"
        assert report["distribution_hold"] is False
        assert report["has_open_incident"] is False
