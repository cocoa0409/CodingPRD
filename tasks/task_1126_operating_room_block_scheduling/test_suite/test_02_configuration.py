"""Configuration surface: service lines, surgeons, rooms, blocks basics, OCC."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_RELEASE_DEADLINE_HOURS,
    assert_block_allocation,
    assert_operating_room,
    assert_service_line,
    assert_version_incremented,
    create_block_payload,
    create_operating_room_payload,
    create_service_line_payload,
    create_surgeon_payload,
    is_valid_uuid,
    make_block,
    make_line,
    make_room,
    make_surgeon,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestServiceLineDefaults:
    def test_default_release_deadline_and_computed_block_deadline(self, api, admin_headers):
        """PRD §3.1: "An optional `release_deadline_hours` sets how many hours before
        a block's start its unfilled time auto-releases to the open pool; when omitted
        it defaults to 72."
        PRD §3.2: "Creation freezes `original_minutes` and projects
        `release_deadline_at`: midnight UTC of the block's `date`, plus `start_minute`
        minutes, minus the owning line's `release_deadline_hours` hours."

        Design: Corner/entities/service_line_default_release_deadline_and_computed_block_deadline
        """
        line = validate_success(
            api.create_service_line(
                create_service_line_payload(name="ORTHO", target_utilization_pct=80),
                admin_headers,
            ),
            201,
        )
        assert_service_line(line)
        assert line["release_deadline_hours"] == DEFAULT_RELEASE_DEADLINE_HOURS

        room = validate_success(
            api.create_operating_room(
                create_operating_room_payload(room_name="OR1"), admin_headers
            ),
            201,
        )
        block = validate_success(
            api.create_block(
                create_block_payload(
                    line["id"], room["id"],
                    date="2026-05-04", start_minute=420, end_minute=720,
                ),
                admin_headers,
            ),
            201,
        )
        assert_block_allocation(block)
        # 2026-05-04T07:00:00Z (start_minute 420) minus 72 hours.
        assert block["release_deadline_at"] == "2026-05-01T07:00:00Z"
        assert block["original_minutes"] == 300
        assert block["status"] == "DRAFT"


class TestSurgeonCreation:
    def test_missing_service_line_id_rejected(self, api, admin_headers):
        """PRD §2.5: "Any minute field outside the range 0 to 1440, any missing
        required field, any type mismatch, and any invalid enum member is a
        request-shape failure rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/surgeon_missing_required_service_line_id_returns_invalid_request
        """
        res = api.create_surgeon({"full_name": "Dr. NoLine"}, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert res.status_code == 400


class TestRoomCreation:
    def test_injected_system_fields_ignored(self, api, admin_headers):
        """PRD §2.4: "Every primary resource carries a standard set of system-managed
        fields: **`id`** (string): a server-minted UUID with no type prefix.
        **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional
        digits, set at creation."

        Design: Corner/entities/create_room_with_injected_system_fields_input_ignored
        """
        res = api.create_operating_room(
            {
                "room_name": "OR9",
                "id": "99999999-8888-7777-6666-555555555555",
                "version": 42,
                "created_at": "2020-01-01T00:00:00.000Z",
            },
            admin_headers,
        )
        room = validate_success(res, 201)
        assert_operating_room(room)
        assert room["id"] != "99999999-8888-7777-6666-555555555555"
        assert is_valid_uuid(room["id"])
        assert room["created_at"] != "2020-01-01T00:00:00.000Z"


class TestBlockTimeRange:
    def test_inverted_range_rejected(self, api, admin_headers):
        """PRD §2.5: "A window whose end is not strictly after its start is rejected
        with `ERR_INVALID_TIME_RANGE`; this time-range rule is enforced at block
        creation, at anesthesia-coverage publication, and at case-completion
        recording (where `actual_end_minute` must be strictly greater than
        `actual_start_minute`)."

        Design: Corner/entities/create_block_inverted_range_rejected
        """
        line = make_line()
        room = make_room()

        res_equal = api.create_block(
            create_block_payload(line["id"], room["id"], start_minute=600, end_minute=600),
            admin_headers,
        )
        validate_error(res_equal, ApiErrorId.ERR_INVALID_TIME_RANGE)
        assert res_equal.status_code == 400

        res_inverted = api.create_block(
            create_block_payload(line["id"], room["id"], start_minute=700, end_minute=600),
            admin_headers,
        )
        validate_error(res_inverted, ApiErrorId.ERR_INVALID_TIME_RANGE)
        assert res_inverted.status_code == 400

        _, meta = validate_paginated(
            api.list_blocks(admin_headers, params={"or_id": room["id"]})
        )
        assert meta["total_count"] == 0


class TestBlockListFilters:
    def test_status_filter_returns_only_matching(self, api, admin_headers):
        """PRD §2.3: "Most list endpoints also accept equality filters matching their
        foreign keys and statuses: surgeons filter by `service_line_id`; blocks by
        `service_line_id`, `surgeon_id`, `or_id`, `date`, and `status`; cases by
        `surgeon_id`, `block_id`, `or_id`, `date`, `status`, and `priority`".

        Design: Corner/entities/block_list_status_filter_returns_only_matching
        """
        line = make_line()
        room = make_room()
        draft = make_block(line["id"], room["id"], date="2026-05-04")
        active = make_block(line["id"], room["id"], date="2026-05-05", activate=True)

        active_rows, active_meta = validate_paginated(
            api.list_blocks(admin_headers, params={"status": "ACTIVE", "or_id": room["id"]})
        )
        assert active_meta["total_count"] == 1
        assert active_rows[0]["id"] == active["id"]
        assert active_rows[0]["status"] == "ACTIVE"

        draft_rows, draft_meta = validate_paginated(
            api.list_blocks(admin_headers, params={"status": "DRAFT", "or_id": room["id"]})
        )
        assert draft_meta["total_count"] == 1
        assert draft_rows[0]["id"] == draft["id"]
        assert draft_rows[0]["status"] == "DRAFT"


class TestServiceLineOcc:
    def test_patch_with_stale_version_rejected(self, api, admin_headers):
        """PRD §2.8: "The service-line configuration update
        (`PATCH /service-lines/{lineId}`) requires a non-optional
        `expected_service_line_version` field carrying the client's last observed
        `version` of the service line. If the line's version has advanced since the
        client last read it — because another writer changed `release_deadline_hours`
        or `target_utilization_pct` in the meantime — the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a
        configuration it has not observed."
        PRD §3.1: "A successful update increments the line's `version` by 1".

        Design: Corner/cross_cutting_complexity_layers/patch_service_line_with_stale_version_returns_412
        """
        line = make_line(name="GS", target=75)
        observed = line["version"]

        first = validate_success(
            api.patch_service_line(
                line["id"],
                {"target_utilization_pct": 80, "expected_service_line_version": observed},
                admin_headers,
            ),
            200,
        )
        assert_version_incremented(first["version"], observed)
        assert first["version"] == observed + 1
        assert first["target_utilization_pct"] == 80

        stale = api.patch_service_line(
            line["id"],
            {"target_utilization_pct": 85, "expected_service_line_version": observed},
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        after_stale = validate_success(api.get_service_line(line["id"], admin_headers), 200)
        assert after_stale["target_utilization_pct"] == 80

        third = validate_success(
            api.patch_service_line(
                line["id"],
                {"target_utilization_pct": 85,
                 "expected_service_line_version": first["version"]},
                admin_headers,
            ),
            200,
        )
        assert third["target_utilization_pct"] == 85
        assert third["version"] == first["version"] + 1
