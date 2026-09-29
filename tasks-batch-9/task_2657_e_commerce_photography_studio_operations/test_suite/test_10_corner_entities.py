"""Entity-surface corners: creation echoes, defaults, computed and system fields.

Retrieval, listing with filters and pagination, the not-found and
invalid-request shapes, the immutable content profile, and foreign-key
discovery across the junction and self-referential edges.
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
    ERR_REFERENCE_NOT_FOUND,
    ERR_STYLE_NOT_FOUND,
)
from test_helpers.test_users import ADMIN, CONTENT_OPS, COORDINATOR, PRODUCER

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_VENDOR_UUID = "00000000-0000-4000-8000-0000000000ff"


def test_vendor_creation_echoes_its_inputs_and_zeroes_the_custody_ledgers(api):
    """All four inputs come back, and the three ledger fields start empty.

    PRD: "A newly registered vendor starts with `outstanding_sample_count` at 0, `late_return_count` at 0 and `coordination_hold` false."

    Design: Corner/entities/vendor_creation_echoes_input_and_zeroes_the_custody_ledgers
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    vendor = validate_success(
        api.create_vendor(
            f.vendor_payload(
                sample_sla_days=21, contact_email="samples@northline.example"
            ),
            ADMIN,
        ),
        201,
    )

    assert vendor["name"] == "Northline Apparel"
    assert vendor["vendor_code"] == "NRTH"
    assert vendor["sample_sla_days"] == 21
    assert vendor["contact_email"] == "samples@northline.example"
    assert vendor["outstanding_sample_count"] == 0
    assert vendor["late_return_count"] == 0
    assert vendor["coordination_hold"] is False
    assert vendor["version"] == 1


def test_style_retrieval_returns_the_stored_row_with_its_derived_counters(api):
    """A style nothing has happened to reads back at its registration baseline.

    PRD: "A freshly registered style begins with `content_state` at `NOT_STARTED`, `required_item_count` at 0, `allocated_cost_cents` at 0 and `delivered_asset_count` at 0."

    Design: Corner/entities/style_retrieval_returns_the_stored_row_with_derived_counters
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    created = fx.create_style(
        api, vendor["id"], profile["id"], priority_tier="A"
    )

    style = validate_success(api.get_style(created["id"], CONTENT_OPS))

    assert style["id"] == created["id"]
    assert style["style_number"] == "TOP1001"
    assert style["vendor_id"] == vendor["id"]
    assert style["asset_profile_id"] == profile["id"]
    assert style["priority_tier"] == "A"
    assert style["content_state"] == "NOT_STARTED"
    assert style["required_item_count"] == 0
    assert style["allocated_cost_cents"] == 0
    assert style["delivered_asset_count"] == 0


def test_style_listing_filters_by_vendor_and_reports_the_full_total(api):
    """Three of four styles match the filter, and the page meta describes them.

    PRD: "For every list response the `meta` object carries `limit` (the effective page size actually applied), `offset` (the effective offset actually applied), `total_count` (the number of rows matching the filters before pagination was applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/style_listing_filters_by_vendor_and_paginates_with_total_count
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor_a = fx.create_vendor(api)
    vendor_b = fx.create_vendor(api, name="Southgate Mills", vendor_code="SOUT")
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    for style_number in ("TOP1001", "TOP1002", "TOP1003"):
        fx.create_style(api, vendor_a["id"], profile["id"], style_number=style_number)
    fx.create_style(api, vendor_b["id"], profile["id"], style_number="TOP2001")

    first_rows, first_meta = validate_paginated(
        api.list_styles(
            CONTENT_OPS, {"vendor_id": vendor_a["id"], "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api.list_styles(
            CONTENT_OPS, {"vendor_id": vendor_a["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert all(
        row["vendor_id"] != vendor_b["id"] for row in first_rows + second_rows
    )


def test_style_lookup_with_an_unknown_identifier_is_a_style_not_found(api):
    """A well-formed identifier that resolves to nothing is a 404, not an empty 200.

    PRD: "A miss returns the code belonging to the resource that failed to resolve: `ERR_STYLE_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SHOT_ITEM_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_RETOUCH_TASK_NOT_FOUND`, or `ERR_REFERENCE_NOT_FOUND` for the configuration resources."

    Design: Corner/entities/style_lookup_with_unknown_id_returns_style_not_found
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.get_style(UNKNOWN_UUID, CONTENT_OPS), ERR_STYLE_NOT_FOUND, 404
    )


def test_station_creation_without_a_station_code_is_an_invalid_request(api):
    """A missing required field is rejected on shape, and nothing is persisted.

    PRD: "On every write endpoint, the body must carry every required field with the declared type; enum-typed fields must hold a declared member; arrays declared non-empty must be non-empty; numeric fields must respect their declared ranges."

    Design: Corner/entities/station_creation_missing_required_station_code_is_invalid_request
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.create_station(
            {"station_type": "MODEL", "daily_capacity_minutes": 1440}, ADMIN
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_station_creation_applies_its_buffer_concurrency_and_calibration_defaults(api):
    """The three omitted optionals fall to 0, 1 and null.

    PRD: "`calibrated_until` is the instant at which the position's colour calibration lapses and defaults to null, meaning the position has never been calibrated."

    Design: Corner/entities/station_creation_applies_buffer_concurrency_and_calibration_defaults
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    station = validate_success(
        api.create_station(
            {
                "station_code": "MAN-1",
                "station_type": "MANNEQUIN",
                "daily_capacity_minutes": 600,
            },
            ADMIN,
        ),
        201,
    )

    assert station["buffer_minutes"] == 0
    assert station["max_concurrent_sessions"] == 1
    assert station["calibrated_until"] is None
    assert station["committed_minutes_today"] == 0
    assert station["daily_capacity_minutes"] == 600


def test_requires_release_is_computed_from_the_talent_type_alone(api):
    """A model requires a release however the body was filled in; a photographer does not.

    PRD: "On registration `booked_minutes_today` is 0, and the system computes `requires_release` as true exactly when `talent_type` is `MODEL` and false for every other talent type; that flag is what drives the usage-rights gate at booking confirmation."

    Design: Corner/entities/talent_requires_release_is_computed_from_type_and_extra_field_input_ignored
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    model = validate_success(
        api.create_talent_profile(
            {
                "full_name": "Ada Vell",
                "talent_type": "MODEL",
                "hourly_rate_cents": 25000,
                "day_rate_cents": 150000,
                "requires_release": False,
            },
            ADMIN,
        ),
        201,
    )
    photographer = validate_success(
        api.create_talent_profile(
            {
                "full_name": "Pia Ren",
                "talent_type": "PHOTOGRAPHER",
                "hourly_rate_cents": 12000,
                "day_rate_cents": 80000,
            },
            ADMIN,
        ),
        201,
    )

    assert model["requires_release"] is True
    assert photographer["requires_release"] is False
    assert model["booked_minutes_today"] == 0
    assert photographer["minimum_call_hours"] == 4
    assert photographer["max_daily_minutes"] == 480


def test_a_pre_advised_sample_has_server_owned_state_fields(api):
    """Nothing about the two custody axes is a client input at pre-advice.

    PRD: "A pre-advised sample starts `EXPECTED` and `UNMATCHED` with `matched_style_id` null."

    Design: Corner/entities/sample_system_fields_are_server_owned_at_creation
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)

    sample = validate_success(
        api.create_sample(f.sample_payload(vendor["id"]), COORDINATOR), 201
    )

    assert sample["custody_state"] == "EXPECTED"
    assert sample["match_state"] == "UNMATCHED"
    assert sample["matched_style_id"] is None
    assert sample["received_at"] is None
    assert sample["due_return_at"] is None
    assert sample["version"] == 1
    assert sample["created_at"] == "2026-08-03T08:00:00.000Z"
    assert validate_success(api.get_vendor(vendor["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 0


def test_station_creation_with_an_undeclared_station_type_is_rejected(api):
    """`TABLETOP` is not one of the three positions the studio knows.

    PRD: "A station type is `MODEL`, `MANNEQUIN` or `STILL_LIFE`."

    Design: Corner/entities/station_creation_with_invalid_station_type_enum_is_rejected
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.create_station(
            {
                "station_code": "TAB-1",
                "station_type": "TABLETOP",
                "daily_capacity_minutes": 600,
            },
            ADMIN,
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_the_asset_profile_payload_carries_neither_version_nor_updated_at(api):
    """The immutable content contract is the one resource without the version pair.

    PRD: "Both `updated_at` and `version` are absent from an `AssetProfile` payload."

    Design: Corner/entities/asset_profile_is_immutable_and_carries_no_version_field
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    created = fx.create_asset_profile(
        api, required_angles=["FRONT", "BACK"], required_detail_shots=1
    )

    profile = validate_success(api.get_asset_profile(created["id"], PRODUCER))

    assert profile["category"] == "APPAREL_TOP"
    assert profile["required_angles"] == ["FRONT", "BACK"]
    assert profile["naming_pattern"] == "{style_number}_{angle_code}_{seq}"
    assert "version" not in profile
    assert "updated_at" not in profile


def test_style_creation_naming_an_unknown_vendor_is_a_reference_not_found(api):
    """A body foreign key that resolves to nothing is a 404, not a 400.

    PRD: "A base style that does not resolve at all is `ERR_STYLE_NOT_FOUND`, while an unresolvable `vendor_id` or `asset_profile_id` is `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/style_creation_with_unknown_vendor_reference_is_not_found
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])

    validate_error(
        api.create_style(
            f.style_payload(UNKNOWN_VENDOR_UUID, profile["id"]), ADMIN
        ),
        ERR_REFERENCE_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_styles(CONTENT_OPS, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0


def test_the_junction_and_colorway_edges_are_reachable_by_filtered_lists(api):
    """No URL nesting: both sides of the booking junction and the colorway parent filter.

    PRD: "There is no URL nesting in this API: every resource is addressed flatly by its own identifier, and relationships are discovered by filtering list endpoints on foreign keys rather than by walking a path hierarchy."

    Design: Corner/entities/junction_and_self_referential_edges_are_discoverable_by_fk_filtered_lists
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    base = fx.create_style(api, vendor["id"], profile["id"])
    child = fx.create_style(
        api,
        vendor["id"],
        profile["id"],
        style_number="TOP1001BLK",
        base_style_id=base["id"],
        colorway_code="BLK",
    )
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    session = fx.create_session(api, station["id"], provider["id"])
    booking = fx.create_booking(api, session["id"], photographer["id"])

    by_session, session_meta = validate_paginated(
        api.list_talent_bookings(
            PRODUCER, {"session_id": session["id"], "limit": 10, "offset": 0}
        )
    )
    by_talent, talent_meta = validate_paginated(
        api.list_talent_bookings(
            PRODUCER, {"talent_id": photographer["id"], "limit": 10, "offset": 0}
        )
    )
    colorways, colorway_meta = validate_paginated(
        api.list_styles(
            CONTENT_OPS, {"base_style_id": base["id"], "limit": 10, "offset": 0}
        )
    )

    assert session_meta["total_count"] == 1
    assert by_session[0]["id"] == booking["id"]
    assert talent_meta["total_count"] == 1
    assert by_talent[0]["id"] == booking["id"]
    assert colorway_meta["total_count"] == 1
    assert colorways[0]["id"] == child["id"]
    assert colorways[0]["colorway_code"] == "BLK"
