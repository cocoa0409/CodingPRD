"""Inventory creation, defaults, required fields, kind agreement, listing /
pagination, not-found, and the walk-in path.

Covers corner-design entities and endpoints claims plus the
derived-open-slot-count reconciliation claim.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_ops_manager_headers, make_cashier_headers, NON_EXISTENT_UUID,
    create_venue_payload, create_attraction_payload,
    create_venue, create_attraction, create_pricing_plan, create_heat, open_heat,
    make_signed_guest, create_heat_hold_booking, confirm_booking_heat,
    get_venue, get_heat,
)

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()


# ───────────────────────── Corner: entities ──────────────────────────────────

def test_create_venue_returns_201_open_posture(api):
    """PRD §3.1: "A newly created venue starts in posture OPEN, with open_slot_count
    at zero, version at 1, and its weather_hold_reason null."

    Design: Corner/entities/create_venue_returns_201_with_open_posture
    """
    venue = validate_success(api.create_venue(create_venue_payload(name="Fun Park"), OPS), 201)
    assert venue["posture"] == "OPEN"
    assert venue["open_slot_count"] == 0
    assert venue["version"] == 1


def test_create_attraction_missing_kind_returns_invalid_request(api):
    """PRD §3.1: "An Attraction is created with a venue_id, a name, a kind of
    GO_KART, MINI_GOLF, or ARCADE".
    PRD §3.12: "then that the request body is well-formed — required fields
    present, enums valid ... (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_attraction_missing_kind_returns_invalid_request
    """
    venue = create_venue(name="V", set_clock=None)
    res = api.create_attraction({"venue_id": venue["id"], "name": "NoKind"}, OPS)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_attraction_default_min_height_zero(api):
    """PRD §3.1: "an optional min_height_cm (the minimum guest height the attraction
    will admit, defaulting to 0 meaning no restriction)".
    PRD §3.1: "Attractions are created ACTIVE and remain ACTIVE in this version of
    the system."

    Design: Corner/entities/create_attraction_default_min_height_zero
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = validate_success(api.create_attraction(
        create_attraction_payload(venue["id"], name="Putt", kind="MINI_GOLF"), OPS), 201)
    assert attraction["min_height_cm"] == 0
    assert attraction["status"] == "ACTIVE"


def test_get_booking_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first referenced resource that does not exist causes the
    request to be rejected with ERR_NOT_FOUND before any deeper reference or
    business rule is evaluated."

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    res = api.get_booking(NON_EXISTENT_UUID, OPS)
    validate_error(res, "ERR_NOT_FOUND")


def test_heat_computed_lanes_available_snapshots_capacity(api):
    """PRD §3.2: "At creation the heat snapshots the attraction's current
    lane_count into its own lane_capacity, and it starts in SCHEDULED status with
    lanes_committed at zero and lanes_available equal to lane_capacity."

    Design: Corner/entities/heat_computed_lanes_available_ignores_input
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=6)
    heat = create_heat(venue["id"], attraction["id"])
    assert heat["lane_capacity"] == 6
    assert heat["lanes_committed"] == 0
    assert heat["lanes_available"] == 6


def test_heat_on_mini_golf_attraction_kind_mismatch(api):
    """PRD §3.2: "The named attraction must be of kind GO_KART; if it is not,
    creation is rejected with ERR_ATTRACTION_KIND_MISMATCH."

    Design: Corner/entities/heat_create_on_mini_golf_attraction_kind_mismatch
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    res = api.create_heat({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T10:00:00Z", "end_utc": "2026-06-14T10:15:00Z",
    }, OPS)
    validate_error(res, "ERR_ATTRACTION_KIND_MISMATCH")


def test_list_venues_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned ... List
    responses carry the pagination bookkeeping in the meta object of the envelope,
    specifically the limit, offset, total_count, and has_more fields."

    Design: Corner/entities/list_venues_pagination_envelope
    """
    create_venue(name="V1", set_clock=None)
    create_venue(name="V2", set_clock=None)
    data, meta = validate_paginated(api.list_venues(OPS, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True


# ───────────────────────── Corner: endpoints ─────────────────────────────────

def test_walk_in_booking_confirm_succeeds(api):
    """PRD §3.6: "A booking is created — by an OpsManager, a Cashier, or the owning
    Guest — by supplying a venue_id, a guest_id, a slot_kind ... an origin of
    RESERVATION or WALK_IN".
    PRD §3.6: "the booking moves from HOLD to CONFIRMED".

    Design: Corner/endpoints/walk_in_booking_confirm_succeeds
    """
    venue = create_venue(name="V", set_clock="2026-06-14T09:00:00Z")
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])
    heat = open_heat(heat["id"])
    guest = make_signed_guest(full_name="Walkin", height_cm=180)

    bk = create_heat_hold_booking(venue["id"], guest["id"], heat["id"], plan["id"],
                                  party_size=1, origin="WALK_IN")
    confirmed = validate_success(
        api.confirm_booking(bk["id"], {"expected_heat_version": heat["version"]}, CASHIER), 200)
    assert confirmed["origin"] == "WALK_IN"
    assert confirmed["status"] == "CONFIRMED"


# SKIPPED — Corner/endpoints/list_bookings_filtered_by_heat_id
# The only PRD mention of the heat_id list filter is the §4 endpoint TABLE row
# ("List bookings (filter by ... heat_id ...)"). Per the Mandatory PRD citation
# rule C2, an endpoint-titular / table-row citation is not rule-bearing, and no
# §3 prose states the filter's semantics (that it returns exactly the matching
# rows). The outcome is therefore not uniquely derivable from PRD prose alone —
# an implementer could faithfully treat heat_id as an unsupported/ignored param.
# Gap left intentionally per the PRD-first two-condition filter.


# ───────────────── Corner: cross_cutting (derived field) ──────────────────────

def test_open_slot_count_reconciles_with_open_heat(api):
    """PRD §3.1: "The open_slot_count is a live count of the heats and tee sessions
    on the venue currently in OPEN status."

    Design: Corner/cross_cutting_complexity_layers/derived_open_slot_count_reconciles
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    heat = create_heat(venue["id"], attraction["id"])
    open_heat(heat["id"])
    refreshed = validate_success(api.get_venue(venue["id"], OPS), 200)
    assert refreshed["open_slot_count"] == 1, (
        f"open_slot_count should be 1 while a heat is OPEN, got {refreshed['open_slot_count']}"
    )
