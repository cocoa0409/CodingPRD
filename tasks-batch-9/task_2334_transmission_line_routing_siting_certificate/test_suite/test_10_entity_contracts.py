"""Creation, retrieval, defaults, shape rules and listing on the core entities.

What a client sees the moment a row is written, and what the server refuses to
let a client dictate.
"""

from test_helpers import (
    DEFAULT_CLOCK_UTC,
    DEV_NORA,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_common_fields,
    assert_is_null,
    assert_score,
    assert_timestamp_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestProjectRecord:
    """The project is the root of the whole arc."""

    def test_project_creation_returns_the_whole_declared_row(self, api):
        """PRD §3.1: "A new project opens in `stage` `PLANNING`, with
        `schedule_posture` `ON_TRACK`, `right_of_way_hold` false and all four
        escrow figures at zero."

        Design: Corner/entities/project_creation_returns_full_response_envelope
        """
        project = validate_success(
            api.create_project(f.project_payload(), fx.DEVELOPER_HEADERS),
            expected_status=201,
        )

        assert_common_fields(project, "Project")
        assert project["name"] == "Harlan-Boone 345kV Rebuild", (
            f"The supplied name is stored verbatim, got {project['name']!r}"
        )
        assert project["voltage_class"] == "KV_345", (
            f"The supplied voltage class is stored verbatim, got "
            f"{project['voltage_class']!r}"
        )
        assert project["jurisdiction_state"] == "KY", (
            f"The two-letter state is stored verbatim, got "
            f"{project['jurisdiction_state']!r}"
        )
        assert_timestamp_equals(
            project["target_energization_at"], "2028-04-01T00:00:00Z",
            "target_energization_at",
        )
        assert project["stage"] == "PLANNING", (
            f"A new project opens in PLANNING, got {project['stage']}"
        )
        assert project["schedule_posture"] == "ON_TRACK", (
            f"A project with no application is ON_TRACK, got "
            f"{project['schedule_posture']}"
        )
        assert project["right_of_way_hold"] is False, (
            f"An ON_TRACK project carries no hold, got {project['right_of_way_hold']}"
        )
        assert project["version"] == 1, (
            f"version begins at 1 when the row is created, got {project['version']}"
        )
        assert_timestamp_equals(project["created_at"], DEFAULT_CLOCK_UTC, "created_at")
        for field in (
            "escrow_funded_cents", "escrow_balance_cents", "escrow_disbursed_cents",
            "easement_committed_cents",
        ):
            assert project[field] == 0, (
                f"All four escrow figures start at zero, got {field}={project[field]}"
            )

    def test_project_read_back_reports_the_same_values(self, api):
        """PRD §2.4: "`version` is an integer that begins at 1 when the row is
        created and is incremented by exactly 1 on every mutation of that row,
        with `updated_at` refreshed at the same moment."

        Design: Corner/entities/project_retrieval_returns_stored_entity
        """
        ctx = {}
        created = fx.create_project(api, ctx)

        project = validate_success(
            api.get_project(ctx["proj"], fx.COMMISSION_STAFF_HEADERS)
        )

        assert project["id"] == ctx["proj"], (
            f"The read returns the row that was asked for, got {project['id']!r}"
        )
        assert project["stage"] == "PLANNING", (
            f"A read is not a mutation, so the stage is unchanged, got {project['stage']}"
        )
        assert project["schedule_posture"] == "ON_TRACK", (
            f"The posture is unchanged by the read, got {project['schedule_posture']}"
        )
        assert project["version"] == 1, (
            f"The read does not advance the version, got {project['version']}"
        )
        assert project["name"] == created["name"], (
            "The read reports the same name the create response reported"
        )
        assert project["escrow_funded_cents"] == 0, (
            f"The escrow counters do not drift on read, got "
            f"{project['escrow_funded_cents']}"
        )

    def test_client_supplied_system_fields_are_discarded(self, api):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients
        never supply it."

        Design: Corner/entities/project_system_fields_input_ignored
        """
        spoofed_id = "00000000-0000-4000-8000-000000000001"

        project = validate_success(
            api.create_project(
                f.project_payload(
                    name="Spoofed Project", voltage_class="KV_138",
                    id=spoofed_id, created_at="2000-01-01T00:00:00.000Z",
                    version=99, stage="ENERGIZED",
                ),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert project["id"] != spoofed_id, (
            f"The server mints its own identifier, got {project['id']!r}"
        )
        assert_timestamp_equals(project["created_at"], DEFAULT_CLOCK_UTC, "created_at")
        assert project["version"] == 1, (
            f"A supplied version is ignored and the row starts at 1, got "
            f"{project['version']}"
        )
        assert project["stage"] == "PLANNING", (
            f"A supplied stage is ignored and the row opens in PLANNING, got "
            f"{project['stage']}"
        )


class TestPlanningStudyAndAlternativeRecords:
    """The need case rows and the figures the server owns."""

    def test_new_study_defaults_to_a_draft_with_no_arithmetic_yet(self, api):
        """PRD §3.1: "The study opens in `status` `DRAFT` and the acting user is
        recorded as its `authored_by_user_id`. Its four computed figures —
        `transmission_levelized_cents_per_mw`, `benefit_ratio`,
        `need_margin_ratio` and `selected_nta_alternative_id` — are all null until
        sufficiency certification runs, as is `certified_by_user_id`."

        Design: Corner/entities/planning_study_defaults_applied_on_creation
        """
        ctx = {}
        fx.create_project(api, ctx)

        study = validate_success(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            ),
            expected_status=201,
        )

        assert_common_fields(study, "PlanningStudy")
        assert study["status"] == "DRAFT", (
            f"A study opens in DRAFT, got {study['status']}"
        )
        assert study["alternatives_screened_in_count"] == 0, (
            f"No alternative has been screened in yet, got "
            f"{study['alternatives_screened_in_count']}"
        )
        assert study["authored_by_user_id"] == DEV_NORA, (
            f"The acting developer is the author, got {study['authored_by_user_id']!r}"
        )
        for field in (
            "transmission_levelized_cents_per_mw", "benefit_ratio", "need_margin_ratio",
            "selected_nta_alternative_id", "certified_by_user_id",
        ):
            assert_is_null(study, field, "PlanningStudy")

    def test_alternative_without_a_deliverable_capability_is_malformed(self, api):
        """PRD §2.11: "Payload shape: required fields present, enum values inside
        their declared domains, numeric ranges honoured, conditional-field pairings
        satisfied — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/alternative_missing_required_deliverable_mw_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        study = validate_success(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            ),
            expected_status=201,
        )

        payload = f.alternative_payload(study["id"])
        payload.pop("deliverable_mw")

        response = api.create_alternative(payload, fx.ROUTE_ANALYST_HEADERS)
        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

        assert fx.read_study(api, study["id"])["alternatives_screened_in_count"] == 0, (
            "No alternative row was written, so the screened-in count is still zero"
        )
        _, meta = validate_paginated(
            api.list_alternatives(fx.ROUTE_ANALYST_HEADERS, {"study_id": study["id"]})
        )
        assert meta["total_count"] == 0, (
            f"The malformed request created nothing, got {meta['total_count']}"
        )

    def test_supplied_levelized_cost_is_replaced_by_the_frozen_quotient(self, api):
        """PRD §3.1: "At creation the server freezes `levelized_cost_cents_per_mw`
        as the capital cost divided by the delivered capability, rounded half up to
        two decimal places; that figure is never recomputed afterwards."

        Design: Corner/entities/alternative_levelized_cost_computed_input_ignored
        """
        ctx = {}
        fx.create_project(api, ctx)
        study = validate_success(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            ),
            expected_status=201,
        )

        alternative = validate_success(
            api.create_alternative(
                f.alternative_payload(
                    study["id"], capex_cents=80_000_000_000, deliverable_mw=400,
                    levelized_cost_cents_per_mw=1.00,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            alternative["levelized_cost_cents_per_mw"], 200000000.00,
            "levelized_cost_cents_per_mw",
        )
        assert alternative["screening_status"] == "SUBMITTED", (
            f"Alternatives open at SUBMITTED, got {alternative['screening_status']}"
        )
        assert_is_null(alternative, "screen_reason", "Alternative")


class TestRouteSegmentRecords:
    """Segment shape rules and the counters a segment refreshes."""

    def test_rating_above_the_declared_range_is_refused(self, api):
        """PRD §3.2: "four constraint criteria ratings — `land_use_rating`,
        `environmental_rating`, `cultural_rating` and `engineering_rating` — each an
        integer from 0 through 5 inclusive."

        Design: Corner/entities/route_segment_rating_above_range_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")

        response = api.create_route_segment(
            f.route_segment_payload(ctx["routeA"], land_use_rating=6),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

        route = fx.read_route(api, ctx["routeA"])
        assert route["segment_count"] == 0, (
            f"The refused segment was not written, got {route['segment_count']}"
        )
        assert route["status"] == "DRAFT", (
            f"The route is untouched by the malformed segment, got {route['status']}"
        )

    def test_segment_listing_filters_by_route_and_pages_in_sequence_order(self, api):
        """PRD §2.3: "The four pagination fields reported in `meta` are `limit`,
        `offset`, `total_count` (the number of rows matching the filters before the
        window is applied) and `has_more` (true when rows remain beyond the current
        window)."

        Design: Corner/entities/route_segments_listing_filtered_and_paginated
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")
        for index, spec in enumerate(fx.ROUTE_A_SEGMENTS, start=1):
            fx.add_segment(api, ctx, "routeA", f"seg{index}", **dict(spec))

        segments, meta = validate_paginated(
            api.list_route_segments(
                fx.ROUTE_ANALYST_HEADERS,
                {"route_id": ctx["routeA"], "limit": 2, "offset": 0},
            )
        )

        assert meta["total_count"] == 3, (
            f"total_count reports the filtered size before the window, got "
            f"{meta['total_count']}"
        )
        assert len(segments) == 2, (
            f"The window holds two rows, got {len(segments)}"
        )
        assert meta["has_more"] is True, (
            f"A third row remains beyond the window, got {meta['has_more']}"
        )
        assert [row["sequence_index"] for row in segments] == [1, 2], (
            "A route's segments are returned in sequence_index order, got "
            f"{[row['sequence_index'] for row in segments]}"
        )
        route = fx.read_route(api, ctx["routeA"])
        assert route["segment_count"] == 3, (
            f"Three segments now sit on the route, got {route['segment_count']}"
        )
        assert_score(route["total_miles"], 20.0, "total_miles")
        assert route["unsurveyed_segment_count"] == 1, (
            f"Only the third segment is still DESKTOP, got "
            f"{route['unsurveyed_segment_count']}"
        )


class TestEasementTractRecord:
    """Tract lookup and the family check that guards its creation."""

    def test_tract_lookup_by_an_unused_identifier_is_not_found(self, api):
        """PRD §2.5: "URL path identifiers are resolved strictly left to right. On a
        nested read such as a project's routes, the project is resolved first; if it
        does not exist the response is `ERR_RESOURCE_NOT_FOUND` (HTTP 404) and the
        rest of the path is never examined."

        Design: Corner/entities/easement_tract_get_with_unknown_id_not_found
        """
        fx.create_project(api, {})

        response = api.get_easement_tract(NON_EXISTENT_UUID, fx.DEVELOPER_HEADERS)
        validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND, expected_status=404)

    def test_tract_naming_a_segment_of_another_project_is_refused(self, api):
        """PRD §3.8: "The tract's segment must belong to a route on the tract's own
        project, or the creation is refused with `ERR_TRACT_SEGMENT_MISMATCH` (HTTP
        422)."

        Design: Corner/entities/easement_tract_on_segment_of_other_project_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")
        for index, spec in enumerate(fx.ROUTE_A_SEGMENTS, start=1):
            fx.add_segment(api, ctx, "routeA", f"seg{index}", **dict(spec))
        fx.build_unrelated_project(api, ctx, key="proj_other")
        fx.create_landowner(api, ctx, "lo1")

        response = api.create_easement_tract(
            f.easement_tract_payload(ctx["proj_other"], ctx["seg1"], ctx["lo1"]),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.TRACT_SEGMENT_MISMATCH, expected_status=422)

        _, meta = validate_paginated(
            api.list_easement_tracts(
                fx.DEVELOPER_HEADERS, {"project_id": ctx["proj_other"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No tract was written on the unrelated project, got {meta['total_count']}"
        )
