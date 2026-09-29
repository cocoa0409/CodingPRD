"""
Specialised transportation: window exclusivity with its turnaround buffer, the
fuel-indexed commitment, seat conservation, release and waitlist promotion.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_PLACEMENT_NOT_FOUND,
    ERR_ROUTE_NOT_FOUND,
    ERR_TRANSPORT_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger,
    assert_placement_encumbrance_mirror,
    assert_route_seats,
)
from test_helpers.fixtures import (
    assign_transport,
    build_reference_data,
    build_route_pair_world,
    list_rows,
    make_contracted_placement,
    make_transport_route,
    read_account,
    read_assignment,
    read_placement,
    read_route,
    release_transport,
    set_clock,
)
from test_helpers.test_users import COORDINATOR_HEADERS

FULL_SEAT_COMMITMENT_CENTS = 1152270
DAY_CONTRACT_ENCUMBRANCE_CENTS = 5760000
RELEASE_INSTANT = "2026-10-01T08:00:00Z"
MISSING_ROUTE_ID = "00000000-0000-0000-0000-0000000000bb"
MISSING_PLACEMENT_ID = "00000000-0000-0000-0000-0000000000cc"

NARROW_ROUTE = {
    "seat_capacity": 3,
    "daily_rate_cents": 6200,
    "service_window_start_min": 360,
    "service_window_end_min": 600,
}

SINGLE_SEAT_ROUTE = {
    "seat_capacity": 1,
    "daily_rate_cents": 6200,
    "service_window_start_min": 360,
    "service_window_end_min": 600,
}


class TestTransportWindowBuffer:
    def test_a_gap_of_exactly_ten_minutes_is_admitted(self, api):
        """
        The turnaround buffer expands only the end side of an occupancy, so a second
        rider starting exactly ten minutes after the first rider's window ends is
        seated and books the full commitment.

        PRD: "The buffer expands only the end side, so two riders separated by a gap of exactly ten minutes are permitted while nine minutes is not."

        Design: Difficulty/resource_temporal_overlap/transport_window_half_open_buffer_admits_a_gap_of_exactly_ten_minutes
        """
        world = build_route_pair_world(api, route_overrides=dict(NARROW_ROUTE))
        route_id = world["route"]["id"]
        first = assign_transport(
            api,
            world["placement_a"]["id"],
            route_id,
            pickup_window_start_min=420,
            pickup_window_end_min=450,
        )
        assert first["status"] == "ACTIVE"
        assert first["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS

        second = validate_success(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    world["placement_b"]["id"],
                    route_id,
                    pickup_window_start_min=460,
                    pickup_window_end_min=490,
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert second["status"] == "ACTIVE"
        assert second["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS

        assert_route_seats(read_route(api, route_id), committed=2, available=1)
        placement_b = read_placement(api, world["placement_b"]["id"])
        assert placement_b["transport_status"] == "ASSIGNED"
        assert placement_b["transport_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert (
            read_placement(api, world["placement_a"]["id"])["transport_encumbrance_cents"]
            == FULL_SEAT_COMMITMENT_CENTS
        )
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=86175460,
            encumbered=13824540,
            disbursed=0,
        )

    def test_a_gap_of_five_minutes_collides_and_persists_nothing(self, api):
        """
        A window starting inside the first rider's buffered occupancy is a hard
        refusal, and the refused request leaves no assignment row behind.

        PRD: "A collision or an out-of-window request is a hard refusal with `ERR_TRANSPORT_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/transport_window_half_open_buffer_admits_a_gap_of_exactly_ten_minutes
        """
        world = build_route_pair_world(api, route_overrides=dict(NARROW_ROUTE))
        route_id = world["route"]["id"]
        assign_transport(
            api,
            world["placement_a"]["id"],
            route_id,
            pickup_window_start_min=420,
            pickup_window_end_min=450,
        )
        assign_transport(
            api,
            world["placement_b"]["id"],
            route_id,
            pickup_window_start_min=460,
            pickup_window_end_min=490,
        )

        validate_error(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    world["placement_b"]["id"],
                    route_id,
                    pickup_window_start_min=455,
                    pickup_window_end_min=485,
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_TRANSPORT_WINDOW_OVERLAP,
            409,
        )

        rows, meta = list_rows(
            api.list_transportation_assignments(
                COORDINATOR_HEADERS, {"route_id": route_id}
            )
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE"]
        assert_route_seats(read_route(api, route_id), committed=2, available=1)


def _single_seat_world(api):
    """A one-seat route with a seated rider and a waitlisted rider behind them."""
    world = build_route_pair_world(api, route_overrides=dict(SINGLE_SEAT_ROUTE))
    world["assignment_a"] = assign_transport(
        api,
        world["placement_a"]["id"],
        world["route"]["id"],
        pickup_window_start_min=420,
        pickup_window_end_min=450,
    )
    world["assignment_b"] = assign_transport(
        api,
        world["placement_b"]["id"],
        world["route"]["id"],
        pickup_window_start_min=470,
        pickup_window_end_min=500,
    )
    return world


class TestRouteSeatIdentityAcrossPromotion:
    def test_promotion_moves_the_seat_and_the_money_to_the_other_placement(self, api):
        """
        Releasing the seated rider promotes the waitlisted one on the spot: the seat
        count is conserved, the released commitment is rebooked against the promoted
        rider's own placement, and the account totals do not move.

        PRD: "Promotion moves the winner `WAITLISTED → ACTIVE`, stamps its `promoted_at` from the logical clock, and books the full transport commitment for it using the same fuel-indexed formula above."

        Design: Difficulty/compensating_invariant/route_seat_identity_survives_waitlist_promotion_and_double_release
        """
        world = _single_seat_world(api)
        assert world["assignment_a"]["status"] == "ACTIVE"
        assert world["assignment_a"]["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert world["assignment_b"]["status"] == "WAITLISTED"
        assert world["assignment_b"]["encumbrance_cents"] == 0
        assert world["assignment_b"]["promoted_at"] is None
        assert (
            read_placement(api, world["placement_b"]["id"])["transport_status"]
            == "WAITLISTED"
        )
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=87327730,
            encumbered=12672270,
            disbursed=0,
        )

        set_clock(api, RELEASE_INSTANT)
        released = release_transport(api, world["assignment_a"]["id"])
        assert released["status"] == "RELEASED"
        assert released["encumbrance_cents"] == 0

        route = read_route(api, world["route"]["id"])
        assert_route_seats(route, committed=1, available=0)

        promoted = read_assignment(api, world["assignment_b"]["id"])
        assert promoted["status"] == "ACTIVE"
        assert promoted["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert_instant_equals(promoted["promoted_at"], RELEASE_INSTANT)

        placement_a = read_placement(api, world["placement_a"]["id"])
        assert placement_a["transport_status"] == "RELEASED"
        assert placement_a["transport_encumbrance_cents"] == 0
        assert placement_a["released_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert_placement_encumbrance_mirror(placement_a)

        placement_b = read_placement(api, world["placement_b"]["id"])
        assert placement_b["transport_status"] == "ASSIGNED"
        assert placement_b["transport_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert_placement_encumbrance_mirror(placement_b)

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=87327730,
            encumbered=12672270,
            disbursed=0,
        )

    def test_releasing_the_promoted_rider_frees_the_seat_without_a_second_promotion(
        self, api
    ):
        """
        The second release empties the route: the seat identity still holds, both
        assignments are terminal, and the transport money is fully unwound.

        PRD: "On every `TransportRoute`, `seat_capacity` always equals `seats_available` plus `seats_committed`, from the moment the route is created (where `seats_committed` starts at zero) through every assignment, release and waitlist promotion."

        Design: Difficulty/compensating_invariant/route_seat_identity_survives_waitlist_promotion_and_double_release
        """
        world = _single_seat_world(api)
        set_clock(api, RELEASE_INSTANT)
        release_transport(api, world["assignment_a"]["id"])

        final = release_transport(api, world["assignment_b"]["id"])
        assert final["status"] == "RELEASED"
        assert final["encumbrance_cents"] == 0

        assert_route_seats(read_route(api, world["route"]["id"]), committed=0, available=1)

        placement_b = read_placement(api, world["placement_b"]["id"])
        assert placement_b["transport_status"] == "RELEASED"
        assert placement_b["transport_encumbrance_cents"] == 0
        assert placement_b["released_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS

        rows, meta = list_rows(
            api.list_transportation_assignments(
                COORDINATOR_HEADERS, {"route_id": world["route"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["RELEASED", "RELEASED"]

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=88480000,
            encumbered=2 * DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )


def _transport_placement(api, **route_overrides):
    """One CONTRACTED placement that requires transportation, plus one route."""
    ref = build_reference_data(api)
    ref["placement"] = make_contracted_placement(api, ref, transportation_required=True)
    ref["route"] = make_transport_route(api, **route_overrides)
    return ref


class TestTransportCommitment:
    def test_the_seat_commitment_carries_the_fuel_index(self, api):
        """
        The commitment is days per week times contract weeks times the route's daily
        rate lifted by the fuel index, not the unindexed product.

        PRD: "An assignment that resolves to `ACTIVE` books a **transport commitment** equal to `days_per_week` multiplied by `contract_weeks` multiplied by the route's `daily_rate_cents` multiplied by a fuel index of 1.0325, rounded half up to whole cents."

        Design: Corner/calculations/transport_encumbrance_applies_fuel_index_constant
        """
        ref = _transport_placement(
            api,
            seat_capacity=4,
            daily_rate_cents=6200,
            service_window_start_min=360,
            service_window_end_min=660,
        )

        assignment = validate_success(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    ref["placement"]["id"],
                    ref["route"]["id"],
                    pickup_window_start_min=400,
                    pickup_window_end_min=520,
                    days_per_week=5,
                    contract_weeks=36,
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert assignment["status"] == "ACTIVE"
        assert assignment["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert assignment["encumbrance_cents"] != 5 * 36 * 6200

        assert_route_seats(read_route(api, ref["route"]["id"]), committed=1, available=3)
        placement = read_placement(api, ref["placement"]["id"])
        assert placement["transport_status"] == "ASSIGNED"
        assert placement["transport_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS
        assert placement["encumbrance_cents"] == 6912270
        assert_placement_encumbrance_mirror(placement)
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=93087730,
            encumbered=6912270,
            disbursed=0,
        )

    def test_a_half_cent_commitment_rounds_away_from_zero(self, api):
        """
        A commitment whose indexed product lands on exactly half a cent rounds up to
        the next whole cent rather than down or to even.

        PRD: "Where a computation involves a non-integer factor — a fuel index, a travel differential, a fee percentage, a reduction percentage, a Medicaid participation rate — the intermediate product is rounded to a whole number of cents using **round half up**, meaning a fractional part of exactly one half rounds away from zero."

        Design: Corner/calculations/transport_encumbrance_rounds_a_half_cent_exactly_up
        """
        ref = _transport_placement(
            api,
            seat_capacity=4,
            daily_rate_cents=6010,
            service_window_start_min=360,
            service_window_end_min=660,
        )

        assignment = validate_success(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    ref["placement"]["id"],
                    ref["route"]["id"],
                    pickup_window_start_min=400,
                    pickup_window_end_min=520,
                    days_per_week=4,
                    contract_weeks=5,
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert assignment["status"] == "ACTIVE"
        assert assignment["encumbrance_cents"] == 124107

        placement = read_placement(api, ref["placement"]["id"])
        assert placement["transport_encumbrance_cents"] == 124107
        assert_placement_encumbrance_mirror(placement)
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=94115893,
            encumbered=5884107,
            disbursed=0,
        )


class TestSeatReleaseWithoutCandidates:
    def test_release_with_an_empty_waitlist_still_succeeds(self, api):
        """
        Releasing the only rider on a route with nobody waiting returns successfully,
        leaves the freed seat available and creates no phantom assignment row.

        PRD: "When the candidate set is empty, no promotion occurs, `seats_available` simply stays incremented, and the release still returns 200 — an empty waitlist is not an error condition."

        Design: Corner/calculations/waitlist_promotion_with_empty_candidate_set_returns_200_without_promotion
        """
        ref = _transport_placement(
            api,
            seat_capacity=2,
            daily_rate_cents=6200,
            service_window_start_min=360,
            service_window_end_min=660,
        )
        assignment = assign_transport(
            api,
            ref["placement"]["id"],
            ref["route"]["id"],
            days_per_week=5,
            contract_weeks=36,
        )
        assert assignment["encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS

        released = validate_success(
            api.release_transportation_assignment(
                assignment["id"], COORDINATOR_HEADERS
            )
        )
        assert released["status"] == "RELEASED"
        assert released["encumbrance_cents"] == 0

        assert_route_seats(read_route(api, ref["route"]["id"]), committed=0, available=2)
        placement = read_placement(api, ref["placement"]["id"])
        assert placement["transport_status"] == "RELEASED"
        assert placement["transport_encumbrance_cents"] == 0
        assert placement["encumbrance_cents"] == DAY_CONTRACT_ENCUMBRANCE_CENTS
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=94240000,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )

        _, meta = list_rows(
            api.list_transportation_assignments(
                COORDINATOR_HEADERS, {"route_id": ref["route"]["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestAssignmentLinkage:
    def test_both_body_references_report_their_own_entity_when_missing(self, api):
        """
        An unresolvable route identifier and an unresolvable placement identifier each
        report their own entity's not-found code before any seat is considered.

        PRD: "Every identifier-bearing field in the body resolves to an existing row — `student_id`, `school_id`, `rate_schedule_id`, `decision_id`, `placement_id`, `route_id`, `attendance_record_id`, `fiscal_account_id`, `prior_placement_id`, `superseding_placement_id`, and every `service_addendum_id` inside a service-delivery line — each yielding its entity's not-found code (404)."

        Design: Corner/endpoints/transportation_assignment_link_requires_both_placement_and_route_and_not_found_is_specific
        """
        ref = _transport_placement(
            api,
            seat_capacity=3,
            daily_rate_cents=6200,
            service_window_start_min=360,
            service_window_end_min=660,
        )

        validate_error(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    ref["placement"]["id"], MISSING_ROUTE_ID
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_ROUTE_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    MISSING_PLACEMENT_ID, ref["route"]["id"]
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_PLACEMENT_NOT_FOUND,
            404,
        )

        assignment = validate_success(
            api.create_transportation_assignment(
                f.transportation_assignment_payload(
                    ref["placement"]["id"],
                    ref["route"]["id"],
                    pickup_window_start_min=400,
                    pickup_window_end_min=520,
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert assignment["status"] == "ACTIVE"
        assert_route_seats(read_route(api, ref["route"]["id"]), committed=1, available=2)
        placement = read_placement(api, ref["placement"]["id"])
        assert placement["transport_status"] == "ASSIGNED"
        assert placement["transport_encumbrance_cents"] == FULL_SEAT_COMMITMENT_CENTS

        _, meta = list_rows(
            api.list_transportation_assignments(
                COORDINATOR_HEADERS, {"placement_id": ref["placement"]["id"]}
            )
        )
        assert meta["total_count"] == 1
