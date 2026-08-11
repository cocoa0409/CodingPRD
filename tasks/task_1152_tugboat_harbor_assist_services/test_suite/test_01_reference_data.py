"""Reference-data lifecycle: registration, retrieval, listing, immutability.

Each test translates one non-stub design-index instance and cites the PRD sentence
that uniquely derives the asserted outcome.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_gear_inspection,
    assert_tug,
    create_tug_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    create_vessel,
    create_tariff_rate,
    create_job_order,
    create_tug,
    record_passed_inspection,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_gear_inspection_payload


class TestTugRegistration:
    def test_create_tug_initializes_system_fields(self, api, port_admin_headers):
        """PRD §3.1: "A newly registered tug enters service with `operational_status`
        `AVAILABLE`; the other two lifecycle states, `RESTRICTED` and `OUT_OF_SERVICE`,
        are reached only through the safety cascades of §3.6."
        PRD §2.5: "Every resource carries an `id`, a server-minted UUID with no type
        prefix ... and `version`, an integer that increments by one on every mutation
        of the resource."

        Design: Corner/entities/create_tug_initializes_system_fields
        """
        res = api.create_tug(
            create_tug_payload(name="Tug Atlas"), port_admin_headers
        )
        tug = validate_success(res, 201)
        assert_tug(tug)
        assert tug["operational_status"] == "AVAILABLE"
        assert tug["version"] == 1
        assert is_valid_uuid(tug["id"])

        re_read = validate_success(api.get_tug(tug["id"], port_admin_headers), 200)
        assert re_read["operational_status"] == "AVAILABLE"
        assert re_read["version"] == 1

    def test_create_tug_with_id_input_ignored(self, api, port_admin_headers):
        """PRD §2.5: "Every resource carries an `id`, a server-minted UUID with no
        type prefix."

        Design: Corner/entities/create_tug_with_id_input_ignored
        """
        supplied = "11111111-2222-4333-8444-555555555555"
        payload = create_tug_payload(name="Tug Atlas")
        payload["id"] = supplied
        res = api.create_tug(payload, port_admin_headers)
        tug = validate_success(res, 201)
        assert tug["id"] != supplied, (
            "Server must mint its own UUID, not honor the client-supplied id"
        )
        assert is_valid_uuid(tug["id"])

    def test_get_tug_not_found_returns_404(self, api, port_admin_headers):
        """PRD §2.9: "the first missing reference aborts the request with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_tug_not_found_returns_404
        """
        res = api.get_tug(NON_EXISTENT_UUID, port_admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_immediate_read_after_write_consistency(self, api, port_admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        created = validate_success(
            api.create_tug(
                create_tug_payload(
                    name="Tug Atlas",
                    bollard_pull_tons=60.0,
                    horsepower=5000,
                    hourly_rate_cents=120000,
                    insured_value_cents=20000000,
                ),
                port_admin_headers,
            ),
            201,
        )
        read_back = validate_success(
            api.get_tug(created["id"], port_admin_headers), 200
        )
        assert read_back["id"] == created["id"]
        assert read_back["name"] == "Tug Atlas"
        assert read_back["bollard_pull_tons"] == pytest.approx(60.0)
        assert read_back["horsepower"] == 5000


class TestGearInspectionRecord:
    def test_gear_inspection_is_immutable_event_record(
        self, api, port_admin_headers, marine_surveyor_headers
    ):
        """PRD §2.5: "The single exception is the gear inspection record. An
        inspection is an immutable log entry: it carries only `id` and `created_at`,
        and it has neither `updated_at` nor `version`."

        Design: Corner/entities/gear_inspection_is_immutable_event_record
        """
        tug = create_tug(name="Tug Atlas")
        res = api.create_gear_inspection(
            create_gear_inspection_payload(
                tug["id"],
                inspection_item="BITTS",
                outcome="PASSED",
                inspected_at="2026-05-01T00:00:00Z",
                next_due_at="2026-11-01T00:00:00Z",
            ),
            marine_surveyor_headers,
        )
        gi = validate_success(res, 201)
        assert_gear_inspection(gi)

        re_read = validate_success(
            api.get_gear_inspection(gi["id"], port_admin_headers), 200
        )
        assert re_read["outcome"] == "PASSED"
        assert "version" not in re_read
        assert "updated_at" not in re_read


class TestJobOrderListing:
    def test_list_job_orders_pagination_defaults(self, api, port_dispatcher_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 ... The `offset` parameter skips a number of items from the
        front of the result set and defaults to 0. ... The `meta` object of a list
        response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_job_orders_pagination_defaults
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-02T08:00:00Z",
            scheduled_end="2026-06-02T10:00:00Z",
        )
        res = api.list_job_orders(
            port_dispatcher_headers, params={"vessel_id": vessel["id"]}
        )
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(data) == 2
