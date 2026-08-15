"""Reference data creation, envelope shape, and clock epoch (PRD §2.2, §2.5, §3.1)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    CLOCK_EPOCH, CLOCK_EPOCH_DATE,
    create_station_payload, create_carrier_payload, create_passenger_payload,
    create_bag_tag_payload, create_report_payload, create_tracing_event_payload,
    create_station, create_carrier, create_passenger, create_bag_tag, create_report,
    set_clock,
    assert_station, assert_bag_tag, assert_tracing_event, assert_report,
    TEST_USERS, make_passenger_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestStationCreation:

    def test_create_station_computed_counters_zero(self, api):
        """PRD §3.1: "Three computed counters begin at zero on every new station:
        `open_report_count`, `recovered_bag_count`, and `mishandled_report_count`,
        maintained thereafter per §2.6."
        PRD §2.4: "`version` (integer): A system-managed integer that increments
        with every modification to the resource"

        Design: Corner/entities/create_station_success_and_computed_counters_zero
        """
        set_clock(CLOCK_EPOCH)
        resp = api.create_station(
            create_station_payload(station_code="JFK", name="New York JFK",
                                   bags_handled_total=1000000), ADMIN)
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
        data = validate_success(resp, 201)
        assert_station(data)
        assert data["station_code"] == "JFK"
        assert data["open_report_count"] == 0
        assert data["recovered_bag_count"] == 0
        assert data["mishandled_report_count"] == 0
        assert data["version"] == 1

    def test_get_report_nonexistent_returns_404(self, api):
        """PRD §2.7: "the system validates each identifier in sequential,
        left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not correspond to an existing resource."

        Design: Corner/entities/get_report_nonexistent_returns_404
        """
        set_clock(CLOCK_EPOCH)
        resp = api.get_report(NON_EXISTENT_UUID, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_clock_default_is_fixed_epoch(self, api):
        """PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §2.4: "`created_at` (string): An ISO 8601 timestamp in UTC with three
        fractional digits ... indicating when the resource was first created."

        Design: Corner/complexity_layers/clock_default_is_fixed_epoch
        """
        # Clock never set: the very first entity created must be stamped at the epoch.
        # PRD §2.4 requires created_at to carry three fractional digits, so the
        # epoch instant serializes as "2026-08-01T00:00:00.000Z".
        resp = api.create_station(
            create_station_payload(station_code="JFK", name="New York JFK",
                                   bags_handled_total=1000000), ADMIN)
        data = validate_success(resp, 201)
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            f"created_at must equal the fixed startup epoch, got {data['created_at']}"
        )


class TestResponseEnvelope:

    def test_envelope_shape_success_and_error(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" carrying
        `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`, `data`.
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        set_clock(CLOCK_EPOCH)
        ok = api.create_station(
            create_station_payload(station_code="JFK", name="New York JFK",
                                   bags_handled_total=1000000), ADMIN)
        ok_body = ok.json()
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
        assert isinstance(ok_body["data"], dict) and ok_body["data"]["id"]

        err = api.get_station(NON_EXISTENT_UUID, ADMIN)
        err_body = err.json()
        assert err.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"]


class TestBagTagCreation:

    def test_bag_tag_default_declared_value(self, api):
        """PRD §3.2: "A passenger may declare excess value at check-in through
        `declared_value_cents`, which defaults to zero and may not exceed 500000
        cents"
        PRD §3.2: "A bag tag's `status` begins at `CHECKED`"

        Design: Corner/entities/create_bag_tag_default_declared_value
        """
        set_clock(CLOCK_EPOCH)
        carrier = create_carrier()
        passenger = create_passenger()
        payload = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                         is_international=False, weight_kg=20)
        payload.pop("declared_value_cents")  # omit to exercise the default
        resp = api.create_bag_tag(payload, AGENT)
        data = validate_success(resp, 201)
        assert_bag_tag(data)
        assert data["declared_value_cents"] == 0
        assert data["status"] == "CHECKED"

    def test_bag_tag_system_fields_rejected(self, api):
        """PRD §2.10: "Required fields must be present, types must be correct, enum
        values must be valid, amounts must be non-negative, `tag_number` must match
        the ten-digit format, receipt arrays must be non-empty, and unknown or
        system-supplied fields must not appear in the payload; violations are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_bag_tag_with_system_fields_rejected
        """
        set_clock(CLOCK_EPOCH)
        carrier = create_carrier()
        passenger = create_passenger()
        payload = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                         is_international=False, weight_kg=20)
        payload["id"] = NON_EXISTENT_UUID
        payload["version"] = 1
        resp = api.create_bag_tag(payload, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_tag_number_must_be_ten_digits(self, api):
        """PRD §3.2: "Tag numbers are unique across all bag tags — a duplicate is
        rejected with `ERR_DUPLICATE_TAG_NUMBER` — and a malformed tag number is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/tag_number_must_be_ten_digits
        """
        set_clock(CLOCK_EPOCH)
        carrier = create_carrier()
        passenger = create_passenger()
        payload = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                         is_international=False, weight_kg=20,
                                         tag_number="123")
        resp = api.create_bag_tag(payload, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestReportCreation:

    def test_report_creation_computes_liability_fields(self, api):
        """PRD §3.3: "The `liability_regime` is `MONTREAL` when the bag tag's
        `is_international` is true and `DOMESTIC` otherwise. The `liable_carrier_id`
        is the last element of the bag tag's `routing_carrier_ids` — the delivering
        carrier carries the liability. The `effective_cap_cents` is the greater of a
        regime base cap and the bag's `declared_value_cents`: under the Montreal
        regime the base cap is a flat 170016 cents regardless of weight"
        PRD §3.3: "The `opened_on` field takes the date portion of the report's
        `created_at` and marks the start of the interim expense eligibility window."

        Design: Corner/entities/create_report_computes_liability_fields
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier_own = create_carrier(carrier_code="AA", name="Air Alpha")
        carrier_partner = create_carrier(carrier_code="BA", name="Air Beta",
                                         is_interline_partner=True)
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"],
                             [carrier_own["id"], carrier_partner["id"]],
                             is_international=True, weight_kg=20, declared_value_cents=0)
        resp = api.create_report(
            create_report_payload(passenger["id"], bag["id"], station["id"],
                                  type="DELAYED"), AGENT)
        data = validate_success(resp, 201)
        assert_report(data)
        assert data["liable_carrier_id"] == carrier_partner["id"]
        assert data["liability_regime"] == "MONTREAL"
        assert data["effective_cap_cents"] == 170016
        assert data["opened_on"] == CLOCK_EPOCH_DATE

    def test_report_unknown_bag_tag_returns_404(self, api):
        """PRD §2.7: "The same `ERR_NOT_FOUND` rejection applies to body-supplied
        references — `passenger_id`, `bag_tag_id`, `station_id`, the carrier ids
        inside `routing_carrier_ids`, `courier_service_id`, `vendor_id`,
        `report_id`, and `root_cause_station_id` — when they name resources that do
        not exist."

        Design: Corner/entities/report_fk_integrity_unknown_bag_returns_not_found
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        passenger = create_passenger()
        resp = api.create_report(
            create_report_payload(passenger["id"], NON_EXISTENT_UUID, station["id"],
                                  type="DELAYED"), AGENT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestTracingEventShape:

    def test_tracing_event_append_only_no_version(self, api):
        """PRD §2.4: "The single exception to this convention is the Tracing Event,
        an append-only message record: it carries only `id` and `created_at`, and
        both `updated_at` and `version` are absent from it."

        Design: Corner/entities/tracing_event_immutable_common_fields_false
        """
        set_clock(CLOCK_EPOCH)
        ctx_station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"], [carrier["id"]])
        report = create_report(passenger["id"], bag["id"], ctx_station["id"],
                               report_type="DELAYED")
        resp = api.record_tracing_event(
            report["id"],
            create_tracing_event_payload(carrier["id"], ctx_station["id"], "FORWARDED"),
            AGENT)
        data = validate_success(resp, 201)
        assert_tracing_event(data)
        assert "id" in data and "created_at" in data
        assert "version" not in data and "updated_at" not in data
        # FORWARDED does not change report state.
        current = get_success_data(api.get_report(report["id"], AGENT))
        assert current["status"] == "TRACING"


class TestReportListing:

    def test_reports_list_pagination_with_filter(self, api):
        """PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to skip
        and defaults to 0."

        Design: Corner/entities/reports_list_pagination_interacts_with_filters
        """
        from test_helpers import validate_paginated
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        for _ in range(3):
            bag = create_bag_tag(passenger["id"], [carrier["id"]])
            create_report(passenger["id"], bag["id"], station["id"],
                          report_type="DELAYED")

        page1_resp = api.list_reports(ADJUSTER, params={
            "station_id": station["id"], "limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2_resp = api.list_reports(ADJUSTER, params={
            "station_id": station["id"], "limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["has_more"] is False
