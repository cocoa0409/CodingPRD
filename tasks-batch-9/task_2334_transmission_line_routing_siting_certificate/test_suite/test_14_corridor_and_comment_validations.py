"""Rules that guard corridors, comment intake, refinement and nomination.

The four nomination gates fire in a declared order, so each test here arranges
a state in which exactly one of them is the binding one.
"""

from test_helpers import (
    ApiErrorId,
    assert_is_null,
    assert_score,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _draft_corridor(api, segment_count=2):
    """A project and a DRAFT Route A carrying the first few Route A segments."""
    ctx = {}
    fx.create_project(api, ctx)
    fx.create_route(api, ctx, key="routeA")
    for index, spec in enumerate(fx.ROUTE_A_SEGMENTS[:segment_count], start=1):
        fx.add_segment(api, ctx, "routeA", f"seg{index}", **dict(spec))
    return ctx


def _published_corridor(api, seg1_survey="FIELD_VERIFIED", comment_window_days=30):
    """Route A mapped and published for comment on a project with no certified study."""
    ctx = {}
    fx.create_project(api, ctx)
    fx.build_route_a(api, ctx, seg1_survey=seg1_survey)
    fx.publish_route_a(api, ctx, comment_window_days=comment_window_days)
    return ctx


def _comment_count(api, route_id):
    _, meta = validate_paginated(
        api.list_public_comments(fx.COMMISSION_STAFF_HEADERS, {"route_id": route_id})
    )
    return meta["total_count"]


class TestCommentIntakeBounds:
    """Intake is bounded by the route's status, the window and the commenter."""

    def test_comment_on_a_draft_corridor_is_refused(self, api):
        """PRD §3.4: "The route must be published for comment or in refinement —
        intake against a route in any other status is refused with
        `ERR_ROUTE_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/validations/comment_on_unpublished_route_rejected
        """
        ctx = _draft_corridor(api)

        response = api.create_public_comment(
            f.public_comment_payload(
                ctx["routeA"], commenter_kind="PUBLIC", commenter_name="Nell Ford",
                body="Please avoid the school road", materiality="GENERAL",
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ROUTE_NOT_PUBLISHED, expected_status=409)

        assert _comment_count(api, ctx["routeA"]) == 0, (
            "No comment row is written against an unpublished corridor"
        )
        assert fx.read_route(api, ctx["routeA"])["status"] == "DRAFT", (
            "The refused intake leaves the route in DRAFT"
        )

    def test_comment_at_the_closing_instant_itself_is_refused(self, api):
        """PRD §3.4: "and the window must still be open: once the logical clock
        reaches or passes `comment_window_closes_at`, intake is refused with
        `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/validations/comment_at_window_close_instant_rejected
        """
        ctx = _published_corridor(api)
        fx.set_clock(api, "2026-08-31T00:00:00Z")

        response = api.create_public_comment(
            f.public_comment_payload(
                ctx["routeA"], commenter_kind="AGENCY",
                commenter_name="KY Heritage Council",
                body="Late filing on the cultural survey", materiality="GENERAL",
            ),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.COMMENT_WINDOW_CLOSED, expected_status=422)

        route = fx.read_route(api, ctx["routeA"])
        assert str(route["comment_window_closes_at"]).startswith("2026-08-31T00:00:00"), (
            "A 30-day window opened at the default clock closes on 2026-08-31, got "
            f"{route['comment_window_closes_at']}"
        )
        assert _comment_count(api, ctx["routeA"]) == 0, (
            "The refused intake at the closing instant writes nothing"
        )

    def test_a_landowner_may_not_file_on_a_neighbours_behalf(self, api):
        """PRD §2.1: "a landowner filing a public comment must supply their own
        identifier as `commenter_landowner_id`. A mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403); that ownership rule guards exactly two
        write operations — the easement offer response and public comment intake."

        Design: Corner/validations/comment_by_a_landowner_for_another_landowner_rejected
        """
        ctx = _published_corridor(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.create_landowner(
            api, ctx, "lo2", name="Ivor Nance", email="ivor@example.com",
            mailing_address="44 Boone Pike, Boone KY",
        )

        response = api.create_public_comment(
            f.public_comment_payload(
                ctx["routeA"], commenter_kind="LANDOWNER", commenter_name="Ada Wren",
                body="Filed by a neighbour", materiality="MATERIAL",
                segment_id=ctx["seg1"], commenter_landowner_id=ctx["lo1"],
            ),
            fx.make_landowner_headers(ctx["lo2"]),
        )
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER, expected_status=403)

        assert _comment_count(api, ctx["routeA"]) == 0, (
            "The ownership check runs before anything is written"
        )
        assert fx.read_segment(api, ctx["seg1"])["material_comment_count"] == 0, (
            "The named segment's material comment counter is untouched"
        )


class TestNominationGates:
    """The four proposed-route gates, one binding failure at a time."""

    def test_nomination_while_the_window_is_still_open_is_refused(self, api):
        """PRD §3.5: "First, the comment window must have closed: while the logical
        clock is still short of `comment_window_closes_at`, nomination is refused with
        `ERR_COMMENT_WINDOW_OPEN` (HTTP 422)."

        Design: Corner/validations/nomination_before_window_close_rejected
        """
        ctx = _published_corridor(api)
        fx.record_two_open_houses(api, ctx)

        response = api.nominate_route(
            ctx["routeA"], f.nomination_payload(nomination_note="Filing early"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.COMMENT_WINDOW_OPEN, expected_status=422)

        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The corridor stays published, got {route['status']}"
        )
        assert route["open_house_held_count"] == 2, (
            f"Both open houses are on the record already, got "
            f"{route['open_house_held_count']}"
        )

    def test_density_above_the_ceiling_blocks_nomination(self, api):
        """PRD §3.5: "Second, `constraint_density_certified` must be no greater than
        4.00, or the request is refused with `ERR_CONSTRAINT_DENSITY_EXCEEDED` (HTTP
        422)."

        Design: Corner/validations/nomination_with_density_above_limit_rejected
        """
        ctx = _published_corridor(api, seg1_survey="DESKTOP")
        fx.record_two_open_houses(api, ctx)
        fx.set_clock(api, "2026-08-31T00:00:00Z")

        response = api.nominate_route(
            ctx["routeA"],
            f.nomination_payload(nomination_note="Nominating on desktop data"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.CONSTRAINT_DENSITY_EXCEEDED, expected_status=422
        )

        route = fx.read_route(api, ctx["routeA"])
        assert_score(
            route["constraint_score_preliminary"], 67.28, "constraint_score_preliminary"
        )
        assert_score(
            route["constraint_score_certified"], 82.23, "constraint_score_certified"
        )
        assert_score(
            route["constraint_density_certified"], 4.11, "constraint_density_certified"
        )
        assert route["unsurveyed_segment_count"] == 2, (
            f"Segments 1 and 3 are both desk studies, got "
            f"{route['unsurveyed_segment_count']}"
        )
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The corridor stays published, got {route['status']}"
        )

    def test_one_open_house_in_one_county_blocks_nomination(self, api):
        """PRD §3.5: "Third, the route must have at least two recorded open houses
        spanning at least two distinct counties, or the request is refused with
        `ERR_OPEN_HOUSE_COVERAGE_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/nomination_with_single_county_open_house_rejected
        """
        ctx = _published_corridor(api)
        get_success_data(
            api.record_open_house(
                ctx["routeA"], f.open_house_payload(county="Harlan", attendee_count=40),
                fx.DEVELOPER_HEADERS,
            )
        )
        fx.set_clock(api, "2026-08-31T00:00:00Z")

        response = api.nominate_route(
            ctx["routeA"], f.nomination_payload(nomination_note="One meeting held"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.OPEN_HOUSE_COVERAGE_INSUFFICIENT, expected_status=422
        )

        route = fx.read_route(api, ctx["routeA"])
        assert route["open_house_held_count"] == 1, (
            f"Exactly one open house was recorded, got {route['open_house_held_count']}"
        )
        assert route["open_house_counties"] == ["Harlan"], (
            f"The county list holds the one county visited, got "
            f"{route['open_house_counties']}"
        )
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The corridor stays published, got {route['status']}"
        )

    def test_an_unanswered_material_comment_blocks_nomination(self, api):
        """PRD §3.5: "Fourth, no material comment may still be sitting at `RECEIVED`;
        any that are refuse the nomination with `ERR_MATERIAL_COMMENTS_OPEN` (HTTP
        422)."

        Design: Corner/validations/nomination_with_open_material_comment_rejected
        """
        ctx = _published_corridor(api)
        fx.record_two_open_houses(api, ctx)
        comment = get_success_data(
            api.create_public_comment(
                f.public_comment_payload(
                    ctx["routeA"], commenter_kind="PUBLIC", commenter_name="Nell Ford",
                    body="Shift the alignment off the ridge above the school",
                    materiality="MATERIAL", segment_id=ctx["seg1"],
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        fx.set_clock(api, "2026-08-31T00:00:00Z")

        response = api.nominate_route(
            ctx["routeA"],
            f.nomination_payload(
                nomination_note="Nominating with comments outstanding"
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.MATERIAL_COMMENTS_OPEN, expected_status=422)

        assert fx.read_route(api, ctx["routeA"])["status"] == "PUBLISHED_FOR_COMMENT", (
            "The corridor stays published while the comment is unanswered"
        )
        stored = get_success_data(
            api.get_public_comment(comment["id"], fx.COMMISSION_STAFF_HEADERS)
        )
        assert stored["status"] == "RECEIVED", (
            f"The comment is still awaiting a disposition, got {stored['status']}"
        )
        assert fx.read_segment(api, ctx["seg1"])["material_comment_count"] == 1, (
            "The segment still carries the one open material comment"
        )


class TestRefinementSelectorAndCap:
    """The selector needs a target, and the cycle is capped at three rounds."""

    def test_refinement_with_only_a_general_comment_has_no_target(self, api):
        """PRD §3.4: "If no segment carries a material comment, the refinement is
        refused with `ERR_NO_REFINEMENT_TARGET` (HTTP 409), the route stays at
        `PUBLISHED_FOR_COMMENT` and `refinement_round` is not incremented."

        Design: Corner/validations/refinement_without_a_material_comment_rejected
        """
        ctx = _published_corridor(api)
        get_success_data(
            api.create_public_comment(
                f.public_comment_payload(
                    ctx["routeA"], commenter_kind="PUBLIC", commenter_name="Odis Bray",
                    body="General support for the rebuild", materiality="GENERAL",
                    segment_id=ctx["seg2"],
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        response = api.refine_route(
            ctx["routeA"],
            f.refinement_payload(refinement_note="Refine on the general comment"),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.NO_REFINEMENT_TARGET, expected_status=409)

        route = fx.read_route(api, ctx["routeA"])
        assert route["refinement_round"] == 0, (
            f"A refused refinement does not advance the round, got "
            f"{route['refinement_round']}"
        )
        assert_is_null(route, "refinement_target_segment_id", "Route")
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The corridor stays published, got {route['status']}"
        )
        assert fx.read_segment(api, ctx["seg2"])["survey_status"] == "FIELD_VERIFIED", (
            "No segment was upgraded, because no segment was selected"
        )

    def test_a_fourth_refinement_round_is_refused_by_the_cap(self, api):
        """PRD §3.4: "It carries the route `PUBLISHED_FOR_COMMENT → REFINING` and is
        bounded by a hard cap of three completed cycles: a route whose
        `refinement_round` has already reached 3 is refused with
        `ERR_REFINEMENT_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/validations/fourth_refinement_round_rejected
        """
        ctx = _published_corridor(api)
        for round_number in range(1, 4):
            fx.file_material_comment(
                api, ctx, key=f"cmt_r{round_number}", segment_key="seg3"
            )
            get_success_data(
                api.refine_route(
                    ctx["routeA"],
                    f.refinement_payload(
                        refinement_note=f"Round {round_number} shift"
                    ),
                    fx.ROUTE_ANALYST_HEADERS,
                )
            )
            fx.run_mapping(api, ctx, "routeA")
            fx.publish_route_a(api, ctx)
        fx.file_material_comment(api, ctx, key="cmt_r4", segment_key="seg3")

        response = api.refine_route(
            ctx["routeA"], f.refinement_payload(refinement_note="Round 4 shift"),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.REFINEMENT_LIMIT_REACHED, expected_status=409)

        route = fx.read_route(api, ctx["routeA"])
        assert route["refinement_round"] == 3, (
            f"Three cycles were completed and no more, got {route['refinement_round']}"
        )
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The refused refinement leaves the route published, got {route['status']}"
        )
        segment = fx.read_segment(api, ctx["seg3"])
        assert segment["refinement_count"] == 3, (
            f"The same segment was the target three times, got "
            f"{segment['refinement_count']}"
        )
        assert segment["material_comment_count"] == 1, (
            "The fourth comment is still open on the segment, got "
            f"{segment['material_comment_count']}"
        )


class TestSegmentAndPermitShape:
    """Sequence uniqueness is per route, and permit agencies must fit the crossing."""

    def test_reusing_a_sequence_index_on_the_same_route_is_refused(self, api):
        """PRD §3.2: "A `sequence_index` already used on the same route is refused
        with `ERR_SEGMENT_SEQUENCE_DUPLICATE` (HTTP 409)."

        Design: Corner/validations/duplicate_sequence_index_on_a_route_rejected
        """
        ctx = _draft_corridor(api)
        fx.create_route(api, ctx, key="routeB", label="Route B - ridge line",
                        kind="ALTERNATE")
        fx.add_segment(api, ctx, "routeB", "segB1", **dict(fx.ROUTE_B_SEGMENTS[0]))

        response = api.create_route_segment(
            f.route_segment_payload(
                ctx["routeA"], sequence_index=1, miles=3.0, land_use_rating=1,
                environmental_rating=1, cultural_rating=1, engineering_rating=1,
                county="Harlan", crew_capacity=8, survey_status="FIELD_VERIFIED",
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(
            response, ApiErrorId.SEGMENT_SEQUENCE_DUPLICATE, expected_status=409
        )

        assert fx.read_route(api, ctx["routeA"])["segment_count"] == 2, (
            "The duplicate index adds nothing to the proposed corridor"
        )
        assert fx.read_route(api, ctx["routeB"])["segment_count"] == 1, (
            "Sequence index 1 on the alternate corridor was accepted in its own right"
        )

    def test_a_waterway_crossing_admits_only_the_waterway_agency(self, api):
        """PRD §3.3: "The agency must fit the crossing: a `PUBLIC_LAND` crossing may
        be handled by either `BLM` or `USFS`, a `NAVIGABLE_WATERWAY` crossing only by
        `USACE`, and a `WETLAND` crossing only by `USACE`. A mismatched agency, or any
        permit action against a segment whose `federal_crossing_kind` is `NONE`, is
        refused with `ERR_FEDERAL_AGENCY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/federal_permit_agency_mismatch_rejected
        """
        ctx = _draft_corridor(api)

        response = api.record_federal_permit_action(
            ctx["seg2"],
            f.federal_permit_action_payload(action="APPLY", agency="BLM"),
            fx.FEDERAL_PERMIT_OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.FEDERAL_AGENCY_MISMATCH, expected_status=422
        )

        segment = fx.read_segment(api, ctx["seg2"])
        assert segment["federal_permit_status"] == "REQUIRED", (
            f"The waterway crossing still needs a permit, got "
            f"{segment['federal_permit_status']}"
        )
        assert_is_null(segment, "federal_permit_agency", "RouteSegment")
