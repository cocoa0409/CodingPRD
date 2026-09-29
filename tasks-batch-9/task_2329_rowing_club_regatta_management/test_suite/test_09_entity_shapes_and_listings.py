"""Row shapes as stored and served: enrolment echoes and computed standing,
omitted-input defaults, server-minted system fields, derived hull figures, the
paginated fleet roster, entity-specific misses, payload-shape refusals and the
immutable river reading.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    api_client,
    assert_member,
    assert_regatta_entry,
    assert_shell,
    assert_water_condition_reading,
    is_valid_uuid,
    make_coach_headers,
    make_safety_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    declare_single_lineup,
    enrol_athlete,
    enrol_coach,
    enrol_officer,
    open_entry,
    open_regatta,
    read_member,
)


class TestEnrolmentRowShape:
    def test_enrolment_echoes_every_declared_input(self):
        """Everything the payload declares comes back on the stored row.

        PRD: "The payload carries the member's `full_name`, their `tier` — one of
        `COMPETITIVE`, `RECREATIONAL` or `LEARN_TO_ROW`, which drives dues,
        boathouse access and hull eligibility — and their self-declared
        `body_weight_kg` at one decimal place, which the club treats as the
        expectation a weigh-in is measured against."

        Design: Corner/entities/corner_member_creation_returns_full_row_with_computed_access_level
        """
        payload = {
            "full_name": "Cora Coach",
            "tier": "COMPETITIVE",
            "body_weight_kg": 78.0,
            "club_roles": ["COACH", "ATHLETE"],
            "swim_test_passed_on": "2026-04-01T00:00:00Z",
            "coxswain_cert_expires_at": "2027-01-01T00:00:00Z",
            "coach_cert_expires_at": "2027-01-01T00:00:00Z",
            "safety_launch_cert_expires_at": "2027-01-01T00:00:00Z",
            "launch_supervision_limit": 3,
        }
        created = assert_member(
            validate_success(
                api_client.create_member(payload, CLUB_ADMIN_HEADERS), expected_status=201
            )
        )
        assert created["full_name"] == "Cora Coach", (
            f"the painted name is echoed, got {created['full_name']}"
        )
        assert created["tier"] == "COMPETITIVE", f"the tier is echoed, got {created['tier']}"
        assert created["body_weight_kg"] == pytest.approx(78.0, abs=0.01), (
            f"the self-declared weight is echoed, got {created['body_weight_kg']}"
        )
        assert created["launch_supervision_limit"] == 3, (
            f"the declared supervision limit is echoed, got {created['launch_supervision_limit']}"
        )
        assert created["club_roles"] == ["COACH", "ATHLETE"], (
            f"both declared club roles are stored, got {created['club_roles']}"
        )

        fetched = assert_member(read_member(created["id"]))
        for field in payload:
            assert fetched[field] == created[field], (
                f"the read-back row differs on {field}: stored {created[field]}, "
                f"read {fetched[field]}"
            )

    def test_computed_standing_is_server_set_at_enrolment(self):
        """Standing, arrears, usage and access are never client inputs.

        PRD: "A newly enrolled member begins with `membership_status` `ACTIVE`,
        `dues_balance_cents` 0, `logged_session_count` 0 and
        `boathouse_access_level` `FULL`."

        Design: Corner/entities/corner_member_creation_returns_full_row_with_computed_access_level
        """
        created = assert_member(
            validate_success(
                api_client.create_member(
                    {
                        "full_name": "Cora Coach",
                        "tier": "COMPETITIVE",
                        "body_weight_kg": 78.0,
                        "club_roles": ["COACH", "ATHLETE"],
                        "swim_test_passed_on": "2026-04-01T00:00:00Z",
                        "coxswain_cert_expires_at": "2027-01-01T00:00:00Z",
                        "coach_cert_expires_at": "2027-01-01T00:00:00Z",
                        "safety_launch_cert_expires_at": "2027-01-01T00:00:00Z",
                        "launch_supervision_limit": 3,
                    },
                    CLUB_ADMIN_HEADERS,
                ),
                expected_status=201,
            )
        )
        assert created["membership_status"] == "ACTIVE", (
            f"a new member is ACTIVE, got {created['membership_status']}"
        )
        assert created["dues_balance_cents"] == 0, (
            f"nobody owes anything before an invoice, got {created['dues_balance_cents']}"
        )
        assert created["logged_session_count"] == 0, (
            f"no outing has been returned yet, got {created['logged_session_count']}"
        )
        assert created["boathouse_access_level"] == "FULL", (
            "ACTIVE with a zero balance is FULL access, got "
            f"{created['boathouse_access_level']}"
        )

    def test_omitted_optional_inputs_take_their_declared_defaults(self):
        """A bare payload still yields a fully populated row.

        PRD: "Optionally the payload declares `club_roles`, an array drawn from
        `ATHLETE`, `COXSWAIN`, `COACH`, `LAUNCH_DRIVER`, `JURY` and
        `EQUIPMENT_MANAGER` and defaulting to the empty array; the four credential
        instants `swim_test_passed_on`, `coxswain_cert_expires_at`,
        `coach_cert_expires_at` and `safety_launch_cert_expires_at`, each
        defaulting to null meaning "never passed" or "uncertified"; and
        `launch_supervision_limit`, an integer between 1 and 4 inclusive
        defaulting to 2, capping how many overlapping outings the member may cover
        from a safety launch."

        Design: Corner/entities/corner_member_defaults_applied_when_optional_inputs_omitted
        """
        created = assert_member(
            validate_success(
                api_client.create_member(
                    {
                        "full_name": "Plain Member",
                        "tier": "RECREATIONAL",
                        "body_weight_kg": 70.0,
                    },
                    CLUB_ADMIN_HEADERS,
                ),
                expected_status=201,
            )
        )
        assert created["club_roles"] == [], (
            f"club_roles defaults to the empty array, got {created['club_roles']}"
        )
        assert created["launch_supervision_limit"] == 2, (
            f"the supervision limit defaults to 2, got {created['launch_supervision_limit']}"
        )
        for field in (
            "swim_test_passed_on",
            "coxswain_cert_expires_at",
            "coach_cert_expires_at",
            "safety_launch_cert_expires_at",
        ):
            assert created[field] is None, (
                f"{field} defaults to null for an uncertified member, got {created[field]}"
            )
        assert created["membership_status"] == "ACTIVE", (
            f"an undeclared member is still ACTIVE, got {created['membership_status']}"
        )

    def test_system_fields_are_minted_by_the_server(self):
        """id, created_at, updated_at and version are not client-supplied.

        PRD: "All resources except river-condition readings additionally carry
        `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and
        `version`, an integer that starts at 1 on creation and increments by one on
        every mutation of that resource, including mutations the server performs on
        its own initiative when a cascade reaches the resource."

        Design: Corner/entities/corner_member_system_fields_generated_at_creation
        """
        response = api_client.create_member(
            {"full_name": "Sys Fields", "tier": "LEARN_TO_ROW", "body_weight_kg": 64.0},
            CLUB_ADMIN_HEADERS,
        )
        created = assert_member(validate_success(response, expected_status=201))
        assert is_valid_uuid(created["id"]), (
            f"the id is a server-minted UUID with no type prefix, got {created['id']}"
        )
        assert created["version"] == 1, (
            f"version starts at 1 on creation, got {created['version']}"
        )
        assert created["created_at"] == created["updated_at"], (
            "an unmutated row has never been refreshed, so created_at and "
            f"updated_at agree, got {created['created_at']} and {created['updated_at']}"
        )

        body = response.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "every envelope carries a server-generated request id starting with "
            f"req_, got {body['meta']['api_request_id']}"
        )
        assert body["meta"]["api_request_timestamp"], (
            "the envelope carries an api_request_timestamp"
        )

    def test_creation_instants_come_from_the_logical_clock(self):
        """Stamped instants read the logical clock, never wall-clock time.

        PRD: "Before that capability is ever called, the logical clock reads
        exactly `2026-08-01T00:00:00Z`; it must never fall back to real time."

        Design: Corner/entities/corner_member_system_fields_generated_at_creation
        """
        created = assert_member(
            validate_success(
                api_client.create_member(
                    {"full_name": "Sys Fields", "tier": "LEARN_TO_ROW", "body_weight_kg": 64.0},
                    CLUB_ADMIN_HEADERS,
                ),
                expected_status=201,
            )
        )
        assert created["created_at"].startswith("2026-08-01T00:00:00"), (
            "the row is stamped from the untouched logical clock, got "
            f"{created['created_at']}"
        )
        assert created["updated_at"].startswith("2026-08-01T00:00:00"), (
            f"updated_at is stamped from the same clock, got {created['updated_at']}"
        )
        assert read_member(created["id"])["version"] == 1, (
            "a plain read is not a mutation, so the version is untouched"
        )


class TestHullRowShape:
    def test_a_new_four_derives_its_rack_footprint_and_indices(self):
        """slot_units and both indices are computed, never supplied.

        PRD: "A new hull is `AVAILABLE`, its `slot_units` derived from
        `boat_class` as the trailer rack units it occupies (a single or a double
        occupies 1 unit, a four occupies 2, an eight occupies 3), and both
        condition indices — `condition_index_conservative` and
        `condition_index_optimistic` — initialised to 100."

        Design: Corner/entities/corner_shell_condition_indices_and_slot_units_are_computed
        """
        created = assert_shell(
            validate_success(
                api_client.create_shell(
                    {
                        "hull_name": "Quad Star",
                        "boat_class": "4+",
                        "hull_weight_kg": 51.0,
                        "home_bay": "BAY-1",
                    },
                    CLUB_ADMIN_HEADERS,
                ),
                expected_status=201,
            )
        )
        assert created["condition_index_conservative"] == 100, (
            "an undamaged hull starts at 100 conservatively, got "
            f"{created['condition_index_conservative']}"
        )
        assert created["condition_index_optimistic"] == 100, (
            "an undamaged hull starts at 100 optimistically, got "
            f"{created['condition_index_optimistic']}"
        )
        assert created["slot_units"] == 2, (
            f"a coxed four occupies two rack units, got {created['slot_units']}"
        )

    def test_a_new_hull_is_available_and_open_to_every_tier(self):
        """tier_restriction defaults to ANY and the hull is in service.

        PRD: "Optionally the hull declares a `tier_restriction` of
        `COMPETITIVE_ONLY` or `ANY`, defaulting to `ANY`, and a `last_serviced_at`
        instant defaulting to null for a hull never yet serviced."

        Design: Corner/entities/corner_shell_condition_indices_and_slot_units_are_computed
        """
        created = assert_shell(
            validate_success(
                api_client.create_shell(
                    {
                        "hull_name": "Quad Star",
                        "boat_class": "4+",
                        "hull_weight_kg": 51.0,
                        "home_bay": "BAY-1",
                    },
                    CLUB_ADMIN_HEADERS,
                ),
                expected_status=201,
            )
        )
        assert created["status"] == "AVAILABLE", (
            f"a new hull is racked and ready, got {created['status']}"
        )
        assert created["tier_restriction"] == "ANY", (
            f"tier_restriction defaults to ANY, got {created['tier_restriction']}"
        )
        assert created["last_serviced_at"] is None, (
            f"a hull never yet serviced carries null, got {created['last_serviced_at']}"
        )


class TestFleetRosterPagination:
    def test_a_capped_page_reports_the_full_match_count(self):
        """total_count counts matches before the page is cut.

        PRD: "`limit` caps the number of items returned; it defaults to 10, may
        not be smaller than 1, and may not be larger than 100. `offset` is the
        number of items to skip and defaults to 0. Both are echoed in the `meta`
        object of the envelope alongside `total_count` (the number of items
        matching the filter before pagination is applied) and `has_more` (whether
        any matching item remains beyond the current page)."

        Design: Corner/entities/corner_shell_listing_paginates_with_total_count_and_has_more
        """
        hull_a = add_single(hull_name="Hull A", hull_weight_kg=14.0)
        add_single(hull_name="Hull B", hull_weight_kg=14.2)
        add_coxed_four(hull_name="Quad Star", home_bay="BAY-2")

        rows, meta = validate_paginated(
            api_client.list_shells(CLUB_ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(rows) == 2, f"the page is capped at two hulls, got {len(rows)} rows"
        assert meta["total_count"] == 3, (
            f"three hulls match before the cap, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            f"a third hull remains beyond this page, got {meta['has_more']}"
        )
        assert meta["limit"] == 2, f"the cap is echoed, got {meta['limit']}"
        assert meta["offset"] == 0, f"the skip is echoed, got {meta['offset']}"
        assert rows[0]["id"] == hull_a["id"], (
            "the roster is ordered by creation, so the first hull added leads, got "
            f"{rows[0]['hull_name']}"
        )

    def test_the_last_page_and_a_class_filter_both_close_the_roster(self):
        """Walking off the end clears has_more, and a filter narrows total_count.

        PRD: "The fleet roster accepts `status` and `boat_class`."

        Design: Corner/entities/corner_shell_listing_paginates_with_total_count_and_has_more
        """
        hull_a = add_single(hull_name="Hull A", hull_weight_kg=14.0)
        hull_b = add_single(hull_name="Hull B", hull_weight_kg=14.2)
        quad = add_coxed_four(hull_name="Quad Star", home_bay="BAY-2")

        rows, meta = validate_paginated(
            api_client.list_shells(CLUB_ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(rows) == 1, f"one hull is left on the second page, got {len(rows)} rows"
        assert rows[0]["id"] == quad["id"], (
            f"the trailing hull is the last one added, got {rows[0]['hull_name']}"
        )
        assert meta["total_count"] == 3, (
            f"the match count is unaffected by the offset, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            f"nothing remains beyond the last page, got {meta['has_more']}"
        )

        singles, singles_meta = validate_paginated(
            api_client.list_shells(CLUB_ADMIN_HEADERS, {"boat_class": "1X"})
        )
        assert singles_meta["total_count"] == 2, (
            f"only two hulls are singles, got {singles_meta['total_count']}"
        )
        assert {row["id"] for row in singles} == {hull_a["id"], hull_b["id"]}, (
            "the filter returns exactly the two singles and excludes the four"
        )
        assert singles_meta["has_more"] is False, (
            f"both singles fit on the default page, got {singles_meta['has_more']}"
        )


class TestEntitySpecificMisses:
    def test_an_absent_member_id_reports_the_member_code(self):
        """A path miss is a typed 404, not an empty success.

        PRD: "Identifiers in a request path are resolved left to right, and the
        first identifier that does not resolve ends the request with that entity's
        own 404 error rather than a generic one."

        Design: Corner/entities/corner_member_get_unknown_id_returns_404_member_not_found
        """
        enrolled = enrol_athlete("Plain Member", "RECREATIONAL", 70.0)

        response = api_client.get_member(NON_EXISTENT_UUID, CLUB_ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)
        assert response.json()["data"]["message"], (
            "the refusal carries a human-readable explanation of what went wrong"
        )

        assert_member(
            validate_success(api_client.get_member(enrolled["id"], CLUB_ADMIN_HEADERS))
        )

    def test_an_absent_body_foreign_key_reports_the_parent_code(self):
        """A body FK miss reports the parent's own 404, not a shape error.

        PRD: "Once every path identifier resolves, the same treatment is applied
        to foreign keys supplied in the request body: each is resolved to an
        existing row, and a miss returns that entity's own 404 code."

        Design: Corner/entities/corner_dues_invoice_unknown_member_fk_returns_404
        """
        response = api_client.create_dues_invoice(
            {
                "member_id": NON_EXISTENT_UUID,
                "season_year": 2026,
                "billable_months": 12,
                "due_at": "2026-09-01T00:00:00Z",
            },
            CLUB_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


class TestPayloadShapeRefusals:
    def test_a_missing_required_input_is_refused_and_writes_nothing(self):
        """body_weight_kg has no default, so omitting it is a shape error.

        PRD: "Payload shape: required fields present, enum values inside their
        declared sets, integers inside their declared ranges, datetimes parsing as
        ISO 8601 UTC — `ERR_INVALID_REQUEST` (HTTP 422). Applies to every write
        endpoint."

        Design: Corner/entities/corner_member_create_missing_body_weight_returns_422
        """
        response = api_client.create_member(
            {"full_name": "No Weight", "tier": "RECREATIONAL"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _rows, meta = validate_paginated(api_client.list_members(CLUB_ADMIN_HEADERS))
        assert meta["total_count"] == 0, (
            f"the refused enrolment stored no member row, got {meta['total_count']}"
        )

    def test_an_enum_value_outside_its_declared_set_is_refused(self):
        """3X is not a boat class the club races.

        PRD: "An `EquipmentManager` or a `ClubAdmin` adds a hull with a
        `hull_name` painted on it, a `boat_class` of `1X`, `2X`, `4+` or `8+`, a
        `hull_weight_kg` at one decimal place, and a `home_bay` label naming the
        boathouse bay it is racked in."

        Design: Corner/entities/corner_shell_create_unknown_boat_class_enum_returns_422
        """
        response = api_client.create_shell(
            {
                "hull_name": "Odd Boat",
                "boat_class": "3X",
                "hull_weight_kg": 20.0,
                "home_bay": "BAY-1",
            },
            CLUB_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _rows, meta = validate_paginated(api_client.list_shells(CLUB_ADMIN_HEADERS))
        assert meta["total_count"] == 0, (
            f"the refused hull was never racked, got {meta['total_count']}"
        )

    def test_an_integer_outside_its_declared_range_is_refused(self):
        """Thirteen billable months does not fit a twelve-month season.

        PRD: "A dues invoice is issued by a `ClubAdmin` against a `member_id` for
        a `season_year`, prorated over `billable_months` (an integer from 1 to 12
        inclusive) of the twelve-month season, with `locker_requested` declaring
        whether a boathouse locker is billed (defaulting to false), and `due_at`
        fixing the instant after which non-payment becomes delinquency."

        Design: Corner/entities/corner_dues_invoice_billable_months_out_of_range_returns_422
        """
        member = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)

        response = api_client.create_dues_invoice(
            {
                "member_id": member["id"],
                "season_year": 2026,
                "billable_months": 13,
                "due_at": "2026-09-01T00:00:00Z",
            },
            CLUB_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _rows, meta = validate_paginated(
            api_client.list_member_dues_invoices(member["id"], CLUB_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"no invoice was raised against the member, got {meta['total_count']}"
        )
        assert read_member(member["id"])["dues_balance_cents"] == 0, (
            "the member owes nothing after a refused assessment"
        )


class TestImmutableRiverReading:
    def test_a_reading_computes_its_flag_and_posture_at_creation(self):
        """The observation is judged once, when it is posted.

        PRD: "A `SafetyOfficer` posts a river-condition reading as an immutable
        observation: `observed_at`, `air_temp_c`, `water_temp_c` and
        `wind_speed_kt` each at one decimal place, `visibility_m` as whole metres
        of horizontal visibility, and the `traffic_pattern` in force, which is
        `STANDARD_COUNTERCLOCKWISE`, `REVERSED_CLOCKWISE` or `NARROW_CHANNEL`."

        Design: Corner/entities/corner_water_condition_reading_immutable_row_with_computed_posture
        """
        officer = enrol_officer("Sam Officer")
        headers = make_safety_officer_headers(officer["id"])

        created = assert_water_condition_reading(
            validate_success(
                api_client.create_water_condition_reading(
                    {
                        "observed_at": "2026-08-01T05:00:00Z",
                        "air_temp_c": 20.0,
                        "water_temp_c": 18.0,
                        "wind_speed_kt": 5.0,
                        "visibility_m": 3000,
                        "traffic_pattern": "STANDARD_COUNTERCLOCKWISE",
                    },
                    headers,
                ),
                expected_status=201,
            )
        )
        assert created["cold_water_flag"] is False, (
            "18.0-degree water with a combined sum of 38.0 is not cold, got "
            f"{created['cold_water_flag']}"
        )
        assert created["posture"] == "OPEN", (
            f"a benign river is OPEN, got {created['posture']}"
        )

    def test_a_reading_carries_neither_updated_at_nor_version_and_reads_back_identically(self):
        """Nothing amends a reading, so it needs no mutation bookkeeping.

        PRD: "`WaterConditionReading` is the one exception. A reading is an
        immutable observation of the river at an instant, so it carries only `id`
        and `created_at`; it has neither `updated_at` nor `version`, and no
        operation ever amends one."

        Design: Corner/entities/corner_water_condition_reading_immutable_row_with_computed_posture
        """
        officer = enrol_officer("Sam Officer")
        headers = make_safety_officer_headers(officer["id"])
        created = assert_water_condition_reading(
            validate_success(
                api_client.create_water_condition_reading(
                    {
                        "observed_at": "2026-08-01T05:00:00Z",
                        "air_temp_c": 20.0,
                        "water_temp_c": 18.0,
                        "wind_speed_kt": 5.0,
                        "visibility_m": 3000,
                        "traffic_pattern": "STANDARD_COUNTERCLOCKWISE",
                    },
                    headers,
                ),
                expected_status=201,
            )
        )
        assert "updated_at" not in created, (
            "a reading is never refreshed, so it carries no updated_at"
        )
        assert "version" not in created, (
            "a reading is never mutated, so it carries no version"
        )

        fetched = assert_water_condition_reading(
            validate_success(api_client.get_water_condition_reading(created["id"], headers))
        )
        assert fetched == created, (
            "an immutable row reads back byte-identical, got a divergence between "
            f"{created} and {fetched}"
        )


class TestEntryListingFilters:
    def test_the_entry_list_narrows_to_one_regatta(self):
        """regatta_id is the reverse-reachability path from a regatta to its entries.

        PRD: "Entries accept `regatta_id`, `shell_id`, `trailer_load_id`,
        `event_code` and `status`."

        Design: Corner/entities/corner_regatta_entries_list_filters_by_regatta_and_status
        """
        home = open_regatta(name="Club Head Race")
        away = open_regatta(
            name="Autumn Sprints",
            race_date_at="2026-09-12T08:00:00Z",
            entry_deadline_at="2026-09-10T00:00:00Z",
            scratch_deadline_at="2026-09-11T00:00:00Z",
            weigh_in_opens_at="2026-09-12T06:00:00Z",
            weigh_in_closes_at="2026-09-12T07:00:00Z",
        )
        coach = enrol_coach("Cora Coach")
        coach_headers = make_coach_headers(coach["id"])
        hull_a = add_single(hull_name="Hull A", hull_weight_kg=14.0)
        hull_b = add_single(hull_name="Hull B", hull_weight_kg=14.2)

        first = open_entry(home["id"], hull_a["id"], coach_headers, seed_time_seconds=380.0)
        second = open_entry(home["id"], hull_b["id"], coach_headers, seed_time_seconds=385.0)
        other = open_entry(away["id"], hull_a["id"], coach_headers, seed_time_seconds=390.0)

        rows, meta = validate_paginated(
            api_client.list_regatta_entries(coach_headers, {"regatta_id": home["id"]})
        )
        assert meta["total_count"] == 2, (
            f"the home regatta holds two entries, got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {first["id"], second["id"]}, (
            "only the home regatta's entries are listed"
        )
        assert other["id"] not in {row["id"] for row in rows}, (
            "the other regatta's entry is excluded by the filter"
        )

    def test_adding_a_status_filter_narrows_to_the_undeclared_entry(self):
        """Declaring a lineup moves one entry out of the DRAFT slice.

        PRD: "A member's invoice list and every other lifecycle-bearing listing
        accept `status`."

        Design: Corner/entities/corner_regatta_entries_list_filters_by_regatta_and_status
        """
        home = open_regatta(name="Club Head Race")
        coach = enrol_coach("Cora Coach")
        coach_headers = make_coach_headers(coach["id"])
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        hull_a = add_single(hull_name="Hull A", hull_weight_kg=14.0)
        hull_b = add_single(hull_name="Hull B", hull_weight_kg=14.2)

        declared = open_entry(home["id"], hull_a["id"], coach_headers, seed_time_seconds=380.0)
        undeclared = open_entry(home["id"], hull_b["id"], coach_headers, seed_time_seconds=385.0)
        declared = declare_single_lineup(declared, rower["id"], coach_headers)

        rows, meta = validate_paginated(
            api_client.list_regatta_entries(
                coach_headers, {"regatta_id": home["id"], "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 1, (
            f"only one entry is still undeclared, got {meta['total_count']}"
        )
        assert rows[0]["id"] == undeclared["id"], (
            f"the DRAFT slice holds the undeclared entry, got {rows[0]['id']}"
        )
        assert assert_regatta_entry(declared)["status"] == "LINEUP_DECLARED", (
            f"the declared entry has advanced out of DRAFT, got {declared['status']}"
        )
