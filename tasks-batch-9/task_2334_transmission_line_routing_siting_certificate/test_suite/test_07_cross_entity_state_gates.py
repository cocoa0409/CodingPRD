"""Writes refused because of the state of a row the request never names.

A filing blocked by the study it relies on, and an activity start blocked by a
sibling tract on the same segment.
"""

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _nominated_routes_without_certification(api):
    """The whole corridor arc, but with the need case left uncertified."""
    ctx = fx.build_need_case(api)
    fx.screen_in_both_alternatives(api, ctx)
    fx.build_route_a(api, ctx)
    fx.build_route_b(api, ctx)
    fx.publish_route_a(api, ctx)
    fx.record_two_open_houses(api, ctx)
    fx.set_clock(api, "2026-08-31T00:00:00Z")
    fx.nominate_route(api, ctx, "routeA")
    return ctx


class TestFilingGatedOnStudyState:
    """The application is refused for the state of a study it merely references."""

    def test_analysed_but_uncertified_study_blocks_the_filing(self, api):
        """PRD §3.5: "The filing's checks run in the order §2.11 lays down, and for
        this endpoint that order matters a great deal: the study must be
        `CERTIFIED_SUFFICIENT` (`ERR_STUDY_NOT_SUFFICIENT`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/application_filing_blocked_by_uncertified_study_state
        """
        ctx = _nominated_routes_without_certification(api)

        response = api.create_application(
            f.application_payload(ctx["proj"], ctx["study"], ctx["routeA"]),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.STUDY_NOT_SUFFICIENT, expected_status=409)

        study = fx.read_study(api, ctx["study"])
        assert study["status"] == "ALTERNATIVES_ANALYZED", (
            f"The refused filing leaves the study where it was, got {study['status']}"
        )
        assert study["alternatives_screened_in_count"] == 2, (
            "The study already carries two screened-in alternatives, got "
            f"{study['alternatives_screened_in_count']}"
        )
        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "NOMINATED", (
            "The corridor was already nominated, so the refusal is entirely about the "
            f"study, got {route['status']}"
        )

    def test_certifying_the_study_lets_the_identical_filing_through(self, api):
        """PRD §3.5: "A successful filing snapshots `alternate_route_ids` as the
        identifiers of the routes on that project whose `kind` is `ALTERNATE` and
        whose `status` is `NOMINATED` — a frozen list, not a live query."

        Design: Difficulty/cross_entity_state_dependency/application_filing_blocked_by_uncertified_study_state
        """
        ctx = _nominated_routes_without_certification(api)
        fx.certify_study(api, ctx)

        application = validate_success(
            api.create_application(
                f.application_payload(ctx["proj"], ctx["study"], ctx["routeA"]),
                fx.DEVELOPER_FILER_HEADERS,
            ),
            expected_status=201,
        )

        assert application["review_status"] == "FILED", (
            f"The filing opens on the merits dimension at FILED, got "
            f"{application['review_status']}"
        )
        assert application["record_status"] == "NOT_OPENED", (
            f"The evidentiary dimension opens at NOT_OPENED, got "
            f"{application['record_status']}"
        )
        assert application["alternate_route_ids"] == [ctx["routeB"]], (
            "The one nominated alternate corridor is snapshotted, got "
            f"{application['alternate_route_ids']}"
        )
        assert fx.read_study(api, ctx["study"])["status"] == "CERTIFIED_SUFFICIENT", (
            "Nothing but the study's state changed between the two attempts"
        )


class TestActivityStartGatedOnSiblingTractState:
    """The start is refused for a tract the start request never names."""

    def test_one_unaccepted_tract_on_the_segment_blocks_the_start(self, api):
        """PRD §3.9: "a segment with no tract at all, or with any tract short of
        acquisition, refuses the start with `ERR_EASEMENT_NOT_ACQUIRED` (HTTP
        422)."

        Design: Difficulty/cross_entity_state_dependency/activity_start_blocked_by_unacquired_sibling_tract_state
        """
        ctx = fx.setup_construction_ready(api)
        fx.create_landowner(
            api, ctx, "lo3", name="Cyrus Bell", email="cyrus@example.com",
            mailing_address="221 Gap Rd, Harlan KY",
        )
        fx.create_tract(
            api, ctx, key="tract3", segment_key="seg1", landowner_key="lo3",
            parcel_number="H-104-23", acres=4.80, per_acre_value_cents=312_500,
            easement_factor=0.50, structure_damages_cents=0,
        )
        tract3 = fx.extend_offer(api, ctx, "tract3")
        fx.schedule_activity(api, ctx, key="act1")
        fx.set_clock(api, "2027-08-02T00:00:00Z")

        response = api.start_activity(
            ctx["act1"], f.activity_start_payload(), fx.DEVELOPER_HEADERS
        )
        validate_error(response, ApiErrorId.EASEMENT_NOT_ACQUIRED, expected_status=422)

        assert tract3["offered_compensation_cents"] == 750000, (
            "4.80 acres at 312500 cents an acre taken at 0.50 is 750000 cents, got "
            f"{tract3['offered_compensation_cents']}"
        )
        assert tract3["acquisition_status"] == "OFFERED", (
            f"The sibling tract is still only OFFERED, got {tract3['acquisition_status']}"
        )
        assert fx.read_activity(api, ctx["act1"])["status"] == "SCHEDULED", (
            "The refused start leaves the activity at SCHEDULED"
        )
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "PENDING", (
            "The refused start leaves the segment at PENDING"
        )

    def test_accepting_the_sibling_offer_lets_the_identical_start_through(self, api):
        """PRD §3.9: "A successful start moves the activity `SCHEDULED →
        IN_PROGRESS`, stamping `started_at` from the logical clock on the first
        start, and carries the segment `PENDING → ACTIVE` on its construction
        dimension."

        Design: Difficulty/cross_entity_state_dependency/activity_start_blocked_by_unacquired_sibling_tract_state
        """
        ctx = fx.setup_construction_ready(api)
        fx.create_landowner(
            api, ctx, "lo3", name="Cyrus Bell", email="cyrus@example.com",
            mailing_address="221 Gap Rd, Harlan KY",
        )
        fx.create_tract(
            api, ctx, key="tract3", segment_key="seg1", landowner_key="lo3",
            parcel_number="H-104-23", acres=4.80, per_acre_value_cents=312_500,
            easement_factor=0.50, structure_damages_cents=0,
        )
        fx.extend_offer(api, ctx, "tract3")
        fx.schedule_activity(api, ctx, key="act1")
        fx.set_clock(api, "2027-08-02T00:00:00Z")
        fx.respond_to_offer(api, ctx, "tract3", response="ACCEPT", landowner_key="lo3")

        activity = validate_success(
            api.start_activity(ctx["act1"], f.activity_start_payload(), fx.DEVELOPER_HEADERS),
            expected_status=201,
        )

        assert activity["status"] == "IN_PROGRESS", (
            f"With every tract acquired the start succeeds, got {activity['status']}"
        )
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "ACTIVE", (
            "The start carries the segment PENDING -> ACTIVE"
        )
        assert fx.read_project(api, ctx)["stage"] == "CONSTRUCTION", (
            "The first activity started on the project carries it CERTIFICATED -> "
            "CONSTRUCTION"
        )
