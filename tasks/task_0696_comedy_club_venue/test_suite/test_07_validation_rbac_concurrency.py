"""Validation priority ordering, room/table overlap, OCC on table assignment,
auth/RBAC denials, posture gating, cross-show integrity, timing, and pagination.

Translates the priority_pair, resource_temporal_overlap difficulty instances and
the rbac/errors/validations/OCC corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_venue, create_draft_show,
    setup_ga_show_on_sale, setup_table_show_on_sale,
    setup_ga_show_settlement_open,
    create_ga_reservation, create_table_reservation, create_table_reservation_assigned,
    setup_listed_guest_entry,
    set_clock,
    TEST_USERS, make_patron_headers, build_user_headers,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]
NONEXISTENT_SHOW = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Difficulty A — priority_pair_validation_conflict / role_forbidden_beats_not_found
# ---------------------------------------------------------------------------
def test_role_forbidden_beats_not_found(api):
    """PRD §2.6: "The order is: first, that both authentication headers are
    present (`ERR_MISSING_AUTH`); then, that the declared role is permitted for
    the operation (`ERR_ROLE_FORBIDDEN`); then, that every referenced resource
    exists (`ERR_NOT_FOUND`) ... A check earlier in this order always masks a
    violation that would be caught later."

    Design: Difficulty/priority_pair_validation_conflict/role_forbidden_beats_not_found
    """
    venue = create_venue(name="Prio Venue")
    # Patron is never permitted to publish; the show id does not exist.
    resp = api.publish_show(venue["id"], NONEXISTENT_SHOW, make_patron_headers("patron-zz"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_role_forbidden_beats_not_found_on_section_create(api):
    """PRD §2.6: "then, that the declared role is permitted for the operation
    (`ERR_ROLE_FORBIDDEN`); then, that every referenced resource exists
    (`ERR_NOT_FOUND`)".
    PRD §2.6: "A check earlier in this order always masks a violation that would
    be caught later."

    Design: Difficulty/priority_pair_validation_conflict/role_forbidden_beats_not_found
    """
    venue = create_venue(name="Prio1b Venue")
    # BoxOffice is not permitted to create a section (Booker-only); the show id is
    # non-existent. Role denial (priority 2) must mask the not-found (priority 3).
    resp = api.create_section(
        venue["id"], NONEXISTENT_SHOW,
        {"kind": "GA", "label": "Nope", "ga_capacity": 10}, BOX_OFFICE,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


# ---------------------------------------------------------------------------
# Difficulty A — priority_pair_validation_conflict / invalid_state_beats_section_sold_out
# ---------------------------------------------------------------------------
def test_invalid_state_beats_section_sold_out(api):
    """PRD §2.9: "the sellable-state check itself rejects a reservation against a
    `DRAFT`, `PRIVATE_HELD`, `CANCELLED`, `SETTLING`, or `SETTLED` show with
    `ERR_INVALID_STATE`."
    PRD §2.6: "then, that the target resource is in a legal state for the
    operation (`ERR_INVALID_STATE`); ... and finally the operation-specific
    business rules described throughout §3. A check earlier in this order always
    masks a violation that would be caught later."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_section_sold_out
    """
    sc = setup_ga_show_on_sale(
        ga_capacity=1,
        show_overrides={"title": "Prio2 Night", "starts_at": "2026-04-09T03:00:00Z",
                        "ends_at": "2026-04-09T05:00:00Z"},
    )
    # Fill the single GA seat, then cancel the show.
    create_ga_reservation(sc, patron_id="patron-f1", party_size=1)
    validate_success(api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER))
    # New reservation both violates show state (CANCELLED) and GA capacity.
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-f2", "party_size": 5,
    }
    resp = api.create_reservation(payload, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_invalid_state_beats_section_sold_out_on_settling_show(api):
    """PRD §2.9: "A show in `DRAFT`, `PRIVATE_HELD`, `CANCELLED`, `SETTLING`, or
    `SETTLED` is not sellable: the sellable-state check itself rejects a
    reservation against a `DRAFT`, `PRIVATE_HELD`, `CANCELLED`, `SETTLING`, or
    `SETTLED` show with `ERR_INVALID_STATE`."
    PRD §3.5: "a `party_size` strictly greater than the remaining capacity is
    rejected with `ERR_SECTION_SOLD_OUT`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_section_sold_out
    """
    # Capacity 1; the show is moved to SETTLING (non-sellable). A party of 5 both
    # violates the sellable-state check and exceeds capacity; the state check
    # (priority 6) masks the capacity check (priority 14).
    sc = setup_ga_show_settlement_open(
        ga_capacity=1, price_cents=4500,
        show_overrides={"title": "Prio2b Night", "starts_at": "2026-04-23T03:00:00Z",
                        "ends_at": "2026-04-23T05:00:00Z"},
        ends_after_iso="2026-04-23T06:00:00Z",
    )
    assert sc["show"]["status"] == "SETTLING", "precondition: show is SETTLING"
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-f3", "party_size": 5,
    }
    resp = api.create_reservation(payload, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty A — resource_temporal_overlap / show_room_window_overlap_with_doors_buffer
# ---------------------------------------------------------------------------
def test_show_room_window_overlap_rejected(api):
    """PRD §3.1: "Before the show is persisted, the system checks for room
    conflicts: the window running from `doors_buffer_minutes` before `starts_at`
    through `ends_at` must not overlap the equivalent window of any other
    non-`CANCELLED` show at the same venue, or the creation is rejected with
    `ERR_SHOW_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/show_room_window_overlap_with_doors_buffer
    """
    venue = create_venue(name="Overlap Venue")
    validate_success(
        api.create_show(venue["id"], {
            "title": "Early Show", "starts_at": "2026-04-14T03:00:00Z",
            "ends_at": "2026-04-14T05:00:00Z", "doors_buffer_minutes": 30,
        }, BOOKER),
        expected_status=201,
    )
    # Second show opens its window at 04:45Z (05:15 - 30), before the first ends 05:00Z.
    resp = api.create_show(venue["id"], {
        "title": "Late Show", "starts_at": "2026-04-14T05:15:00Z",
        "ends_at": "2026-04-14T07:00:00Z", "doors_buffer_minutes": 30,
    }, BOOKER)
    validate_error(resp, ApiErrorId.ERR_SHOW_TIME_CONFLICT)


def test_show_window_overlap_via_doors_buffer_of_earlier_show(api):
    """PRD §3.1: "the window running from `doors_buffer_minutes` before
    `starts_at` through `ends_at` must not overlap the equivalent window of any
    other non-`CANCELLED` show at the same venue, or the creation is rejected with
    `ERR_SHOW_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/show_room_window_overlap_with_doors_buffer
    """
    venue = create_venue(name="Overlap2 Venue")
    # First show occupies [02:00Z (02:30 - 30 buffer) .. 04:30Z].
    validate_success(
        api.create_show(venue["id"], {
            "title": "First Show", "starts_at": "2026-04-25T02:30:00Z",
            "ends_at": "2026-04-25T04:30:00Z", "doors_buffer_minutes": 30,
        }, BOOKER),
        expected_status=201,
    )
    # Second show starts 04:00Z (inside the first show's 02:00..04:30 window).
    resp = api.create_show(venue["id"], {
        "title": "Second Show", "starts_at": "2026-04-25T04:00:00Z",
        "ends_at": "2026-04-25T06:00:00Z", "doors_buffer_minutes": 30,
    }, BOOKER)
    validate_error(resp, ApiErrorId.ERR_SHOW_TIME_CONFLICT)


# ---------------------------------------------------------------------------
# Difficulty A — resource_temporal_overlap / table_double_hold_overlap
# ---------------------------------------------------------------------------
def test_table_double_hold_rejected(api):
    """PRD §3.6: "a table that is not currently `AVAILABLE` — already `HELD`,
    `OCCUPIED`, or `RETIRED`, including the case where another reservation of the
    same show already holds it — is rejected with `ERR_TABLE_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/table_double_hold_overlap
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "Table Night", "starts_at": "2026-04-15T03:00:00Z",
                        "ends_at": "2026-04-15T05:00:00Z"},
        server_overrides={"name": "Hal", "max_tables": 4},
    )
    # Reservation A takes the table (HELD); the assign bumps the table version.
    res_a = create_table_reservation(sc, patron_id="patron-iA", party_size=2)
    after_a = validate_success(
        api.assign_table(
            res_a["id"],
            {"table_id": sc["table"]["id"], "expected_table_version": sc["table_version"]},
            FLOOR,
        )
    )
    table = validate_success(api.get_table(sc["table"]["id"], FLOOR))
    res_b = create_table_reservation(sc, patron_id="patron-iB", party_size=2)
    resp = api.assign_table(
        res_b["id"],
        {"table_id": sc["table"]["id"], "expected_table_version": table["version"]},
        FLOOR,
    )
    validate_error(resp, ApiErrorId.ERR_TABLE_UNAVAILABLE)


def test_assign_occupied_table_rejected(api):
    """PRD §3.6: "a table that is not currently `AVAILABLE` — already `HELD`,
    `OCCUPIED`, or `RETIRED`, including the case where another reservation of the
    same show already holds it — is rejected with `ERR_TABLE_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/table_double_hold_overlap
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "Occupied Night", "starts_at": "2026-04-26T03:00:00Z",
                        "ends_at": "2026-04-26T05:00:00Z"},
        server_overrides={"name": "Otto", "max_tables": 4},
    )
    res_a = create_table_reservation_assigned(sc, patron_id="patron-oA", party_size=2)
    # Seat reservation A so the table advances HELD -> OCCUPIED.
    seated = validate_success(api.seat_reservation(res_a["id"], FLOOR))
    assert seated["booking_status"] == "SEATED"
    table = validate_success(api.get_table(sc["table"]["id"], FLOOR))
    assert table["status"] == "OCCUPIED", "precondition: table is OCCUPIED after seating"
    res_b = create_table_reservation(sc, patron_id="patron-oB", party_size=2)
    resp = api.assign_table(
        res_b["id"],
        {"table_id": sc["table"]["id"], "expected_table_version": table["version"]},
        FLOOR,
    )
    validate_error(resp, ApiErrorId.ERR_TABLE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Corner B — cross_cutting_complexity_layers / occ_stale_table_version_on_assign
# ---------------------------------------------------------------------------
def test_assign_table_stale_version_rejected(api):
    """PRD §2.8: "A request to assign a `SeatTable` to a reservation must carry
    `expected_table_version`, holding the `version` of the target `SeatTable` that
    the client last observed. If another writer has advanced that table's
    `version` since the client read it ... the assignment is rejected with
    `ERR_STALE_VERSION` and HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_table_version_on_assign
    """
    sc = setup_table_show_on_sale(seats=4, price_cents=4500,
                                  server_overrides={"name": "Mae", "max_tables": 4})
    res = create_table_reservation(sc, patron_id="patron-oc", party_size=2)
    stale = sc["table_version"] - 1
    resp = api.assign_table(
        res["id"], {"table_id": sc["table"]["id"], "expected_table_version": stale}, FLOOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner B — errors / posture / auth / guest-list
# ---------------------------------------------------------------------------
def test_closed_venue_blocks_show_create(api):
    """PRD §2.9: "When a venue's `posture` is `CLOSED`, no new show and no new
    reservation may be created at that venue; such an attempt is rejected with
    `ERR_POSTURE_BLOCKED`."

    Design: Corner/errors/closed_venue_blocks_show_create
    """
    venue = create_venue(name="Closed Venue")
    validate_success(api.close_venue(venue["id"], BOOKER))
    resp = api.create_show(venue["id"], {
        "title": "Blocked Night", "starts_at": "2026-06-04T03:00:00Z",
        "ends_at": "2026-06-04T05:00:00Z",
    }, BOOKER)
    validate_error(resp, ApiErrorId.ERR_POSTURE_BLOCKED)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the capacity they are acting in. A request missing either
    header is rejected with `ERR_MISSING_AUTH`."

    Design: Corner/errors/missing_auth_header_rejected
    """
    resp = api.create_venue({"name": "Anon Venue", "settlement_currency": "USD"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


def test_guest_list_convert_when_not_listed(api):
    """PRD §3.10: "Converting or revoking an entry that is not `LISTED` (for
    convert) is rejected with `ERR_GUEST_LIST_NOT_LISTED`."

    Design: Corner/errors/guest_list_convert_when_not_listed
    """
    ctx = setup_listed_guest_entry(party_size=2)
    sc = ctx["scenario"]
    gle_id = ctx["guest_entry"]["id"]
    validate_success(api.revoke_guest_list_entry(gle_id, BOOKER))
    resp = api.convert_guest_list_entry(
        gle_id, {"section_id": sc["section"]["id"], "tier_id": sc["tier"]["id"]}, BOX_OFFICE
    )
    validate_error(resp, ApiErrorId.ERR_GUEST_LIST_NOT_LISTED)


# ---------------------------------------------------------------------------
# Corner B — validations: cross-show / no-show timing / pagination
# ---------------------------------------------------------------------------
def test_cross_show_tier_section_mismatch(api):
    """PRD §3.5: "Its `tier_id` and `section_id` must belong to the same
    `show_id`, or the creation is rejected with `ERR_CROSS_SHOW_REFERENCE`."

    Design: Corner/validations/cross_show_tier_section_mismatch
    """
    venue = create_venue(name="XShow Venue")
    # Show A with its own section + tier.
    sc_a = setup_ga_show_on_sale(
        venue_overrides=None, ga_capacity=50,
        show_overrides={"title": "Show A", "starts_at": "2026-05-15T03:00:00Z",
                        "ends_at": "2026-05-15T05:00:00Z"},
    )
    # Show B with its own section + tier (different show).
    sc_b = setup_ga_show_on_sale(
        ga_capacity=50,
        show_overrides={"title": "Show B", "starts_at": "2026-05-16T03:00:00Z",
                        "ends_at": "2026-05-16T05:00:00Z"},
    )
    # Reservation on show A's section but show B's tier -> cross-show reference.
    payload = {
        "show_id": sc_a["show"]["id"], "section_id": sc_a["section"]["id"],
        "tier_id": sc_b["tier"]["id"], "patron_id": "patron-xs", "party_size": 1,
    }
    resp = api.create_reservation(payload, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_CROSS_SHOW_REFERENCE)


def test_no_show_before_doors_buffer_timing(api):
    """PRD §3.7: "A `FloorManager` marks a no-show only once the logical clock has
    reached `starts_at` plus `doors_buffer_minutes`; before that instant the
    action is rejected with `ERR_TIMING_NOT_ALLOWED`."

    Design: Corner/validations/no_show_before_doors_buffer_timing
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "NSE Night", "starts_at": "2026-05-18T03:00:00Z",
                        "ends_at": "2026-05-18T05:00:00Z", "doors_buffer_minutes": 30},
    )
    res = create_ga_reservation(sc, patron_id="patron-ns", party_size=1)
    # Clock at startup default 2026-03-01, before the 2026-05 show start+buffer.
    resp = api.no_show(res["id"], FLOOR)
    validate_error(resp, ApiErrorId.ERR_TIMING_NOT_ALLOWED)


def test_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/invalid_pagination_rejected
    """
    venue = create_venue(name="Page Venue")
    resp = api.list_shows(BOOKER, params={"venue_id": venue["id"], "limit": 500})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)


# ---------------------------------------------------------------------------
# Corner B — rbac
# ---------------------------------------------------------------------------
def test_patron_cannot_open_settlement(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/patron_cannot_open_settlement
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "RBAC Night", "starts_at": "2026-05-26T03:00:00Z",
                        "ends_at": "2026-05-26T05:00:00Z"},
    )
    set_clock("2026-05-26T06:00:00Z")
    resp = api.create_settlement({"show_id": sc["show"]["id"]}, make_patron_headers("patron-rb"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_patron_cannot_cancel_another_patrons_reservation(api):
    """PRD §2.1: "a `Patron` may act only on a `Reservation` whose `patron_id`
    equals their `X-User-ID` ... a violation of either ownership rule is rejected
    with `ERR_NOT_OWNER`."

    Design: Corner/rbac/patron_cannot_cancel_another_patrons_reservation
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "Own Night", "starts_at": "2026-05-27T03:00:00Z",
                        "ends_at": "2026-05-27T05:00:00Z"},
    )
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-A", "party_size": 1,
    }
    res = validate_success(
        api.create_reservation(payload, make_patron_headers("patron-A")), expected_status=201
    )
    resp = api.cancel_reservation(res["id"], make_patron_headers("patron-B"))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
