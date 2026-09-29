"""Field registration, retrieval, listing and payload rejection."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field,
    assert_instant_equals,
    assert_two_decimals,
    assert_version,
    factories,
    fixtures,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC

UNUSED_UUID = "11111111-2222-3333-4444-555555555555"

GRASS_MAIN_1 = {
    "name": "Grass Main 1",
    "surface_type": "NATURAL_GRASS",
    "installed_on_date": "2018-04-15",
    "expected_life_years": 12,
    "area_sq_ft": 80000,
    "sanctioned_level": "STATE",
    "warranty_expires_on": "2026-04-15",
}


class TestFieldRegistration:
    def test_registration_derives_age_warranty_and_zeroed_counters(self, client, roster):
        """Registration immediately derives everything time-dependent.

        "`age_years` is the number of whole and fractional days between
        `installed_on_date` and the current logical instant, divided by 365.25,
        rounded half up to two decimal places."

        "`warranty_status` follows a three-way rule: it is `NONE` when
        `warranty_expires_on` is null, `ACTIVE` when the current instant is
        strictly earlier than `warranty_expires_on`, and `EXPIRED` otherwise —
        the boundary belongs to expiry, so at exactly `warranty_expires_on` the
        warranty already reads `EXPIRED`."

        "`play_status` resolves to `OPEN`, `certification_status` to
        `NOT_CERTIFIED`, `certified_until_utc` and `admin_closure_reason_code`
        and `retired_at` to null, `admin_closure_active` to false, every integer
        counter to 0, and `cumulative_wear_units`, `usage_hours_ytd`,
        `rest_debt_hours` and `nitrogen_applied_ytd_lb_per_1000_sq_ft` to 0.00."

        "The agronomic condition index is computed at once, and because a
        brand-new field has no impact test yet, its `latest_gmax_mean_value` is
        null and the safety term falls back to the no-data value of 50.00
        described in §3.7."

        Design: Corner/entities/field_creation_returns_derived_age_warranty_and_zeroed_counters
        """
        field = validate_success(
            client.create_field(dict(GRASS_MAIN_1), roster.director_headers), 201
        )
        assert_field(field)

        # 3030 elapsed days over 365.25 is 8.2957, which rounds half up to 8.30.
        assert_two_decimals(field["age_years"], 8.30, "Field.age_years")
        assert field["warranty_status"] == "EXPIRED"
        assert field["play_status"] == "OPEN"
        assert field["certification_status"] == "NOT_CERTIFIED"

        for key in (
            "cumulative_wear_units",
            "rest_debt_hours",
            "usage_hours_ytd",
            "nitrogen_applied_ytd_lb_per_1000_sq_ft",
        ):
            assert_two_decimals(field[key], 0.00, f"Field.{key}")
        for key in (
            "open_mandatory_remediation_count",
            "open_advisory_remediation_count",
            "open_certification_packet_count",
            "open_replacement_plan_count",
            "unsafe_cancellation_count",
        ):
            assert field[key] == 0, f"Field.{key} must default to 0, got {field[key]}"

        # 100.00 x 0.50 + 30.83 x 0.20 + 50.00 x 0.30 = 71.166, rounded to 71.17.
        assert_two_decimals(
            field["condition_index_agronomic"], 71.17, "Field.condition_index_agronomic"
        )
        assert field.get("latest_gmax_mean_value") is None

        assert is_valid_uuid(field["id"])
        assert_version(field, 1, "Field")
        # `created_at`/`updated_at` are described only as "recording creation" and
        # "refreshed on every mutation"; the PRD never names the logical clock as
        # their source (unlike `effective_at_utc`, `opened_at_utc`,
        # `started_at_utc`, ... which it does), so their clock source is not
        # uniquely derivable and is not asserted here.

        assert field.get("retired_at") is None
        assert field["admin_closure_active"] is False
        assert field.get("certified_until_utc") is None

    def test_retrieval_by_id_returns_the_stored_representation(self, client, roster):
        """A read returns the derived representation without mutating it.

        "`age_years` is the number of whole and fractional days between
        `installed_on_date` and the current logical instant, divided by 365.25,
        rounded half up to two decimal places."

        "The age component is 100.00 minus the ratio of `age_years` to
        `expected_life_years` expressed as a percentage, likewise floored at 0.00
        and rounded half up to two decimals, so a surface exactly at its nominal
        life scores 0.00 on age and one past it is floored rather than negative."

        "`version`, an integer that starts at 1 and increases by exactly 1 on
        every mutation of that resource."

        Design: Corner/entities/field_retrieval_by_id_returns_the_stored_representation
        """
        created = fixtures.register_synthetic_stadium_1(client, roster)
        field = validate_success(
            client.get_field(created["id"], roster.director_headers), 200
        )
        assert_field(field)
        assert field["id"] == created["id"]

        # 3713 elapsed days over 365.25 is 10.1656, which rounds to 10.17.
        assert_two_decimals(field["age_years"], 10.17, "Field.age_years")
        assert field["warranty_status"] == "EXPIRED"
        assert field["infill_depth_mm"] == pytest.approx(34.0, abs=0.05)
        assert field["area_sq_ft"] == 70000
        assert field["sanctioned_level"] == "REGIONAL"

        # Age is past the nominal ten years, so the age component floors at 0.00:
        # 100.00 x 0.50 + 0.00 x 0.20 + 50.00 x 0.30 = 65.00.
        assert_two_decimals(
            field["condition_index_agronomic"], 65.00, "Field.condition_index_agronomic"
        )
        assert_version(field, 1, "Field")

    def test_field_list_paginates_with_total_count_and_has_more(self, client, roster):
        """Paging the field list is deterministic and the meta block is complete.

        "Results on every list endpoint are ordered by `created_at` ascending."

        "The `meta` block of a list response carries `limit` and `offset` as they
        were applied, `total_count` giving the number of records matching the
        filters before pagination, and `has_more` indicating whether any matching
        record remains beyond the current page."

        "Filter parameters are additive: supplying several narrows the result set,
        and an unrecognised value for an enumerated filter simply matches nothing
        rather than erroring."

        Design: Corner/entities/field_list_paginates_with_total_count_and_has_more
        """
        f1 = fixtures.register_grass_main_1(client, roster)
        f2 = fixtures.register_synthetic_stadium_1(client, roster)
        f3 = fixtures.register_grass_practice_3(client, roster)

        page1, meta1 = validate_paginated(
            client.list_fields(roster.director_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert [item["id"] for item in page1] == [f1["id"], f2["id"]]

        page2, meta2 = validate_paginated(
            client.list_fields(roster.director_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page2[0]["id"] == f3["id"]

        grass, grass_meta = validate_paginated(
            client.list_fields(
                roster.director_headers,
                params={"limit": 100, "surface_type": "NATURAL_GRASS"},
            )
        )
        assert grass_meta["total_count"] == 2
        assert [item["id"] for item in grass] == [f1["id"], f3["id"]]

    def test_unknown_uuid_on_a_path_route_returns_the_collection_s_own_code(
        self, client, roster
    ):
        """Each path collection carries its own resolution failure code.

        "An unresolvable id in a field route yields `ERR_FIELD_NOT_FOUND`
        (HTTP 404) — this applies to reading one field and to placing a closure
        order on it. An unresolvable staff-member route id yields
        `ERR_STAFF_MEMBER_NOT_FOUND`. An unresolvable maintenance-task id yields
        `ERR_MAINTENANCE_TASK_NOT_FOUND`, on both the single read and the
        transition route."

        "An unresolvable budget id yields `ERR_CAPITAL_BUDGET_NOT_FOUND`."

        Design: Corner/entities/get_field_with_unknown_uuid_returns_field_not_found
        """
        response = client.get_field(UNUSED_UUID, roster.director_headers)
        validate_error(response, ApiErrorId.FIELD_NOT_FOUND, 404)
        body = response.json()
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

        validate_error(
            client.get_staff_member(UNUSED_UUID, roster.director_headers),
            ApiErrorId.STAFF_MEMBER_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_maintenance_task(UNUSED_UUID, roster.director_headers),
            ApiErrorId.MAINTENANCE_TASK_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_capital_budget(UNUSED_UUID, roster.director_headers),
            ApiErrorId.CAPITAL_BUDGET_NOT_FOUND,
            404,
        )

    @pytest.mark.parametrize(
        "omitted",
        [
            "surface_type",
            "name",
            "installed_on_date",
            "expected_life_years",
            "area_sq_ft",
            "sanctioned_level",
        ],
    )
    def test_missing_required_input_returns_invalid_request(
        self, client, roster, omitted
    ):
        """Each of the six required registration inputs is genuinely required.

        "Every POST endpoint requires that the body contain each of its
        required fields, contain no unknown field, use the correct JSON type for
        each value, and use only declared members for every enumerated value; a
        breach yields `ERR_INVALID_REQUEST` (HTTP 400)."

        "The director supplies a `name` of between 1 and 120 characters that will
        appear on certification paperwork, the `surface_type` — either
        `NATURAL_GRASS` or `SYNTHETIC_TURF` — the `installed_on_date` recording
        the instant the surface went into service, an `expected_life_years` of
        between 1 and 30 whole years representing the manufacturer's or
        agronomist's nominal service life, the playing surface `area_sq_ft`
        between 1 and 400000 square feet, and a `sanctioned_level` drawn from
        `NONE`, `LOCAL`, `REGIONAL` and `STATE` describing the highest sanctioning
        body the field is presented to."

        Design: Corner/entities/field_create_missing_required_surface_type_returns_invalid_request
        """
        payload = {k: v for k, v in GRASS_MAIN_1.items() if k != omitted}
        validate_error(
            client.create_field(payload, roster.director_headers),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _items, meta = validate_paginated(
            client.list_fields(roster.director_headers, params={"limit": 100})
        )
        assert meta["total_count"] == 0, "a rejected registration persists nothing"

    def test_client_supplied_system_fields_are_rejected(self, client, roster):
        """System-owned and computed values may not be supplied by the client.

        "Every resource is addressed by an `id` that the server mints as a
        UUID. Identifiers carry no type prefix — a field id and a booking id are
        indistinguishable by inspection, so path parameters must be resolved
        against the collection the route names rather than parsed. Clients never
        supply `id`."

        "Every POST endpoint requires that the body contain each of its required
        fields, contain no unknown field, use the correct JSON type for each
        value, and use only declared members for every enumerated value; a breach
        yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/field_create_with_client_supplied_system_fields_is_rejected
        """
        payload = dict(GRASS_MAIN_1)
        payload.update(
            {
                "id": UNUSED_UUID,
                "version": 9,
                "age_years": 1.00,
                "cumulative_wear_units": 500.00,
            }
        )
        validate_error(
            client.create_field(payload, roster.director_headers),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _items, meta = validate_paginated(
            client.list_fields(roster.director_headers, params={"limit": 100})
        )
        assert meta["total_count"] == 0
        validate_error(
            client.get_field(UNUSED_UUID, roster.director_headers),
            ApiErrorId.FIELD_NOT_FOUND,
            404,
        )

    def test_unknown_enum_member_is_rejected_across_endpoints(self, client, roster):
        """Every enumerated body value is drawn from a closed set of members.

        "Every POST endpoint requires that the body contain each of its
        required fields, contain no unknown field, use the correct JSON type for
        each value, and use only declared members for every enumerated value; a
        breach yields `ERR_INVALID_REQUEST` (HTTP 400)."

        "`AERATION`, `OVERSEEDING`, `FERTILITY` and `IRRIGATION` are agronomic
        operations and may only be scheduled on a field whose `surface_type` is
        `NATURAL_GRASS`; `GROOMING`, `INFILL_REDISTRIBUTION` and
        `SEAM_INSPECTION` are synthetic operations and may only be scheduled on a
        field whose `surface_type` is `SYNTHETIC_TURF`."

        "an `activity_type` drawn from `PRACTICE`, `GAME`, `TOURNAMENT` and
        `COMMUNITY`"

        Design: Corner/entities/field_create_with_unknown_enum_member_is_rejected
        """
        bad_surface = dict(GRASS_MAIN_1)
        bad_surface["name"] = "Hybrid Field 9"
        bad_surface["surface_type"] = "HYBRID_BERMUDA"
        bad_surface.pop("warranty_expires_on")
        validate_error(
            client.create_field(bad_surface, roster.director_headers),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        bad_level = dict(GRASS_MAIN_1)
        bad_level["sanctioned_level"] = "OLYMPIC"
        validate_error(
            client.create_field(bad_level, roster.director_headers),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _items, meta = validate_paginated(
            client.list_fields(roster.director_headers, params={"limit": 100})
        )
        assert meta["total_count"] == 0

        field = fixtures.register_grass_practice_3(client, roster)
        budget = fixtures.authorize_budget(client, roster)

        validate_error(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=field["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="SCRIMMAGE",
                    window_start_utc="2026-08-05T19:00:00Z",
                    window_end_utc="2026-08-05T21:00:00Z",
                    expected_participant_count=30,
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            client.create_maintenance_task(
                factories.make_maintenance_task_payload(
                    field_id=field["id"],
                    assigned_staff_member_id=roster.id_of("agronomist"),
                    task_type="MOWING",
                ),
                roster.agronomist_headers,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        current = validate_success(
            client.get_field(field["id"], roster.director_headers), 200
        )
        validate_error(
            client.create_replacement_plan(
                factories.make_replacement_plan_payload(
                    field_id=field["id"],
                    capital_budget_id=budget["id"],
                    expected_field_version=current["version"],
                    target_surface_type="NATURAL_GRASS",
                    area_sq_ft=60000,
                    priority_basis="GUT_FEEL",
                    planned_install_year=2027,
                ),
                roster.director_headers,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
