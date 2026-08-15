"""Creation defaults, response envelope, pagination, derived posture (PRD §2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_display_event,
    assert_operator,
    assert_site_plan,
    create_crew_member_payload,
    create_display_payload,
    create_magazine_payload,
    create_operator_payload,
    create_site_plan_payload,
    create_weather_reading_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    checkout_product,
    create_magazine_with_batch,
    create_operator,
    set_clock,
    setup_event_approved,
    setup_event_draft,
)

ADMIN = TEST_USERS["admin_headers"]


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with meta
        carrying api_request_id and api_request_timestamp, and response_type
        "object" for a single resource.

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_operator(create_operator_payload(), ADMIN)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", ""))
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with data carrying error_id and message, and
        response_type "error".

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_display(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0


class TestCreationDefaults:
    def test_operator_create_defaults(self, api, admin_headers):
        """PRD §3.1: "New operators begin in `ACTIVE` status with `version` 1."
        PRD §2.5: "while `ACTIVE`, `suspended_reason` is null."

        Design: Corner/entities/operator_create_defaults
        """
        resp = api.create_operator(create_operator_payload(), admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_operator(data)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["suspended_reason"] is None

    def test_display_create_initial_state(self, api):
        """PRD §3.2: "The new event begins in `DRAFT` with `weather_decision` `PENDING`, `dud_count` and `fired_count` at zero, and `cancellation_reason`, `termination_reason`, `standby_confirmed_at`, `standby_confirmed_by`, `show_completed_at`, `closed_at`, `final_fallout_radius_ft`, and `final_standby_fee_cents` all null."

        Design: Corner/entities/display_create_initial_state
        """
        op, op_headers = create_operator()
        resp = api.create_display(create_display_payload(), op_headers)
        data = validate_success(resp, expected_status=201)
        assert_display_event(data)
        assert data["status"] == "DRAFT"
        assert data["weather_decision"] == "PENDING"
        assert data["dud_count"] == 0
        assert data["fired_count"] == 0
        assert data["version"] == 1
        assert data["cancellation_reason"] is None
        assert data["final_fallout_radius_ft"] is None
        assert data["final_standby_fee_cents"] is None

    def test_get_display_not_found(self, api, admin_headers):
        """PRD §2.8: "path identifiers are resolved left-to-right and
        body-referenced identifiers (`site_plan_id`, `product_batch_id`,
        `display_event_id`) must exist, otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/get_display_not_found_returns_404
        """
        resp = api.get_display(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404

    def test_create_display_missing_required_venue_id(self, api):
        """PRD §2.8: "failures here return `ERR_VALIDATION`, or `ERR_INVALID_QUANTITY` when a movement quantity or count is not positive."
        PRD §3.2: "An operator opens a new show by creating a display event with `venue_id`, `venue_name`, `scheduled_start_at`, `scheduled_end_at`, and `declared_max_shell_diameter_in`".

        Design: Corner/entities/create_display_missing_required_returns_validation
        """
        op, op_headers = create_operator()
        payload = create_display_payload()
        del payload["venue_id"]
        resp = api.create_display(payload, op_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_license_class_enum_rejected(self, api, admin_headers):
        """PRD §2.8: "Request-schema validation runs third: required fields present (including the conditional transport-manifest fields whenever a movement's `movement_type` is `CHECK_OUT`), types and enum members valid, quantities and diameters greater than zero, `scheduled_end_at` strictly after `scheduled_start_at`, the scheduled start in the future, and no undeclared payload fields; failures here return `ERR_VALIDATION`, or `ERR_INVALID_QUANTITY` when a movement quantity or count is not positive."
        PRD §2.5: "a `license_class` of either `DISPLAY_1_3G` or `PROXIMATE_1_4G`".

        Design: Corner/entities/invalid_enum_rejected_returns_validation
        """
        resp = api.create_operator(
            create_operator_payload(license_class="CLASS_X"), admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_immediate_consistency_on_site_plan_create(self, api):
        """PRD §3.2: "At creation the server computes the plan's
        `required_spectator_distance_ft` as 70 feet per inch of the parent
        event's `declared_max_shell_diameter_in`" and filing a plan
        "increments the event's `version` by one". PRD §2.9: "consistency is
        immediate, never deferred."

        Design: Corner/consistency_model/immediate_consistency_on_create
        """
        op, op_headers, ev = setup_event_draft()
        sp_resp = api.create_site_plan(
            ev["id"], create_site_plan_payload(ev["version"]), op_headers
        )
        sp = validate_success(sp_resp, expected_status=201)
        assert_site_plan(sp)
        assert sp["required_spectator_distance_ft"] == 280  # 70 x 4 in
        assert sp["status"] == "CURRENT"
        fresh = get_success_data(api.get_display(ev["id"], op_headers))
        assert fresh["version"] == 2, "site-plan creation must bump event version immediately"


class TestCrewListingPagination:
    def test_crew_list_pagination(self, api):
        """PRD §2.3: "The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/crew_list_pagination
        """
        op, op_headers = create_operator()
        for name, level in (("A", "TRAINEE"), ("B", "SHOOTER"), ("C", "LEAD_OPERATOR")):
            resp = api.create_crew_member(
                op["id"],
                create_crew_member_payload(full_name=name, cert_level=level),
                op_headers,
            )
            validate_success(resp, expected_status=201)
        page1 = api.list_crew_members(op["id"], op_headers, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(data1) == 2
        page2 = api.list_crew_members(op["id"], op_headers, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert meta2["has_more"] is False
        assert len(data2) == 1


class TestMagazinePosture:
    def test_magazine_posture_derived_lapsed(self, api):
        """PRD §2.5: "Its `posture` is derived, never stored directly:
        `ACTIVE` while the clock is at or before `inspection_due_at`, flipping
        to `LAPSED` the instant the clock passes it."

        Design: Corner/entities/magazine_posture_derived_lapsed
        """
        op, op_headers = create_operator()
        mag = get_success_data(api.create_magazine(
            create_magazine_payload(inspection_due_at="2026-09-01T00:00:00Z"),
            op_headers,
        ))
        set_clock("2026-09-01T00:00:00Z")
        at_due = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert at_due["posture"] == "ACTIVE", "clock at exactly inspection_due_at must be ACTIVE"
        set_clock("2026-09-01T00:00:01Z")
        past_due = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert past_due["posture"] == "LAPSED", "clock one second past inspection_due_at must be LAPSED"


class TestReverseReachability:
    def test_weather_and_movements_reachable_from_parent(self, api):
        """PRD §3.4: "Movements are listable per batch, or per display with an
        optional `movement_type` filter". PRD §4 lists GET
        /pyro/displays/{id}/weather-readings ("List weather readings of a
        display") returning the display's readings.

        Design: Corner/endpoints/fk_reverse_reachability_weather_and_movements
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        get_success_data(api.create_weather_reading(
            ev["id"], create_weather_reading_payload(), op_headers
        ))
        readings, meta = validate_paginated(api.list_weather_readings(ev["id"], op_headers))
        assert meta["total_count"] == 1
        assert readings[0]["wind_speed_mph"] == 5.0
        moves, mmeta = validate_paginated(
            api.list_display_movements(ev["id"], op_headers, params={"movement_type": "CHECK_OUT"})
        )
        assert mmeta["total_count"] == 1
        assert moves[0]["quantity"] == 10
        bmoves, bmeta = validate_paginated(api.list_batch_movements(batch["id"], op_headers))
        assert bmeta["total_count"] == 1
        assert bmoves[0]["id"] == moves[0]["id"]
