"""Room booking temporal rules: half-open adjacency, turn gaps, capacity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    create_building_turn_active,
    create_group,
    create_revision_payload,
    get_group,
    get_success_data,
    make_coordinator_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_ga_booked_room(api, name="Quincy Hall"):
    """Building TURN_ACTIVE; group GA holds R1 2026-06-15T15:00Z -> 2026-06-19T11:00Z.

    Returns (building, rooms, gb, gb_participant): a fresh second group GB with one
    participant and no revision yet."""
    building, rooms = create_building_turn_active(name=name, key_pool_size=10,
                                                  rooms=(("R1", 1), ("R2", 1)))
    ga = create_group(building["id"], client_name="GA", arrival_date="2026-06-15",
                      departure_date="2026-06-19", deposit_paid_cents=5000)
    ga_p = add_participant(ga["id"], full_name="GA P1", date_of_birth="1980-01-01")
    ga_headers = make_coordinator_headers(ga["id"])
    ga_ver = get_group(ga["id"])["version"]
    get_success_data(api.create_rooming_list_revision(
        ga["id"], create_revision_payload(ga_ver, [{
            "participant_id": ga_p["id"], "room_id": rooms["R1"]["id"],
            "checkin_at": "2026-06-15T15:00:00Z",
            "checkout_at": "2026-06-19T11:00:00Z",
        }]), ga_headers))
    gb = create_group(building["id"], client_name="GB", arrival_date="2026-06-19",
                      departure_date="2026-06-23", deposit_paid_cents=5000)
    gb_p = add_participant(gb["id"], full_name="GB P1", date_of_birth="1981-01-01")
    return building, rooms, gb, gb_p


def _gb_revision_call(api, gb, gb_p, room_id, checkin_at, checkout_at="2026-06-23T11:00:00Z"):
    version = get_group(gb["id"])["version"]
    return api.create_rooming_list_revision(
        gb["id"],
        create_revision_payload(version, [{
            "participant_id": gb_p["id"], "room_id": room_id,
            "checkin_at": checkin_at, "checkout_at": checkout_at,
        }]),
        make_coordinator_headers(gb["id"]))


class TestHalfOpenAdjacencyVsCapacity:
    def test_touching_intervals_fail_turn_window_not_overlap(self, api):
        """PRD: "two intervals that merely touch, one's checkout equal to the
        other's check-in, do not overlap."
        PRD: "Note that touching intervals, while not an overlap, leave a
        zero-hour gap that the turn rule still evaluates — so back-to-back
        bookings on a room always fail the turn requirement."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_vs_capacity
        """
        _building, rooms, gb, gb_p = _setup_ga_booked_room(api)
        resp = _gb_revision_call(api, gb, gb_p, rooms["R1"]["id"],
                                 "2026-06-19T11:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TURN_WINDOW_TOO_SHORT)
        revisions = get_success_data(api.list_rooming_list_revisions(gb["id"], ADMIN))
        rows = revisions["data"] if isinstance(revisions, dict) else revisions
        assert len(rows) == 0, "a rejected revision attempt leaves nothing behind"

    def test_true_intersection_on_full_room_fails_capacity_and_wide_gap_books(
            self, api):
        """PRD: "Fourth, room capacity: the number of overlapping non-cancelled
        assignments on the room must be fewer than its bed_count to admit one
        more, else ERR_ROOM_CAPACITY_EXCEEDED."
        PRD: "The required gap is 24 hours — one full day — for a STANDARD tier"

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_vs_capacity
        """
        _building, rooms, gb, gb_p = _setup_ga_booked_room(api)
        # True intersection: new check-in one hour before GA's checkout on the
        # 1-bed room that is already fully occupied over that instant.
        resp = _gb_revision_call(api, gb, gb_p, rooms["R1"]["id"],
                                 "2026-06-19T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED)
        # 28-hour gap (>= 24h STANDARD requirement): books cleanly.
        revision = validate_success(
            _gb_revision_call(api, gb, gb_p, rooms["R1"]["id"], "2026-06-20T15:00:00Z"),
            expected_status=201)
        assert revision["status"] == "ACTIVE"
        assert len(revision["assignment_ids"]) == 1
        revisions = get_success_data(api.list_rooming_list_revisions(gb["id"], ADMIN))
        rows = revisions["data"] if isinstance(revisions, dict) else revisions
        assert len(rows) == 1, "only the successful revision persists"


class TestDeluxeTurnWindow:
    def test_turn_window_deluxe_tier_30h(self, api):
        """PRD: "The required gap is 24 hours — one full day — for a STANDARD tier
        and 30 hours for a DELUXE tier."
        PRD: "the gap in hours between the preceding assignment's checkout and
        the new check-in must be at least the required turn hours for the new
        group's own linen_tier"

        Design: Corner/validations/turn_window_deluxe_tier_30h
        """
        building, rooms = create_building_turn_active(name="Vail Hall", key_pool_size=5,
                                                      rooms=(("R1", 1), ("R2", 1)))
        ga = create_group(building["id"], client_name="GA", arrival_date="2026-06-15",
                          departure_date="2026-06-19", deposit_paid_cents=5000)
        ga_p = add_participant(ga["id"], full_name="GA P1", date_of_birth="1980-01-01")
        ga_ver = get_group(ga["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            ga["id"], create_revision_payload(ga_ver, [{
                "participant_id": ga_p["id"], "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-06-15T15:00:00Z",
                "checkout_at": "2026-06-19T11:00:00Z",
            }]), make_coordinator_headers(ga["id"])))
        gb = create_group(building["id"], client_name="GB Deluxe",
                          arrival_date="2026-06-20", departure_date="2026-06-23",
                          linen_tier="DELUXE", deposit_paid_cents=5000)
        gb_p = add_participant(gb["id"], full_name="GB P1", date_of_birth="1981-01-01")

        # 28h gap after the STANDARD departure: fine for STANDARD, short of 30h DELUXE.
        resp = _gb_revision_call(api, gb, gb_p, rooms["R1"]["id"], "2026-06-20T15:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TURN_WINDOW_TOO_SHORT)
        # Same times on a room with no neighboring stays: books cleanly.
        revision = validate_success(
            _gb_revision_call(api, gb, gb_p, rooms["R2"]["id"], "2026-06-20T15:00:00Z"),
            expected_status=201)
        assert revision["status"] == "ACTIVE"
