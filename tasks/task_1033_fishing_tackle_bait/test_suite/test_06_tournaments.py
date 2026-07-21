"""Tournaments: lifecycle guards, registration limits, weigh-in gating,
finalize prize cascade, registration-deadline boundary, and venue overlap."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_customer_headers,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# --- Corner: state_machines / sm_tournament_finalize_from_scheduled ---

def test_finalize_scheduled_tournament_rejected(api):
    """PRD 3.7: "IN_PROGRESS → FINALIZED` scores and settles the event, as described below."
    PRD 2.8: "6. **State** — the target resource is in a state that permits the requested transition or action, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/sm_tournament_finalize_from_scheduled_returns_invalid_state
    """
    venue = fixtures.create_venue(name="Sched Lake", water_type="LAKE")
    tournament = fixtures.create_tournament(venue["id"], name="Sched T",
                                            start_at="2026-09-20T06:00:00Z",
                                            end_at="2026-09-20T18:00:00Z",
                                            max_entries=10, prize_points=100)
    resp = api.transition_tournament(tournament["id"], {"action": "FINALIZE"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: validations / val_max_entries_reached_on_register ---

def test_registration_beyond_max_entries_rejected(api):
    """PRD 3.7: "A tournament that already holds `max_entries` registrations rejects further entries with `ERR_MAX_ENTRIES_REACHED` (HTTP 409)."

    Design: Corner/validations/val_max_entries_reached_on_register
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    c1 = fixtures.create_customer(name="Reg One", email="r1@x.com")
    c2 = fixtures.create_customer(name="Reg Two", email="r2@x.com")
    _venue, tournament = fixtures.setup_open_tournament(
        venue_kwargs={"name": "Cap Lake"},
        tournament_kwargs={"name": "Full Cup", "max_entries": 1, "prize_points": 100},
    )
    fixtures.register_entry(tournament["id"], c1["id"])
    resp = api.create_tournament_entry(tournament["id"], {"customer_id": c2["id"]},
                                       make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_MAX_ENTRIES_REACHED.value)


# --- Corner: validations / val_duplicate_entry_same_customer ---

def test_duplicate_registration_rejected(api):
    """PRD 3.7: "A customer may register only once per tournament; a second attempt is rejected with `ERR_DUPLICATE_ENTRY` (HTTP 409)."

    Design: Corner/validations/val_duplicate_entry_same_customer
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Dup Cust", email="d@x.com")
    _venue, tournament = fixtures.setup_open_tournament(
        venue_kwargs={"name": "Dup Lake"},
        tournament_kwargs={"name": "Dup Cup", "max_entries": 10, "prize_points": 100},
    )
    fixtures.register_entry(tournament["id"], customer["id"])
    resp = api.create_tournament_entry(tournament["id"], {"customer_id": customer["id"]},
                                       make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY.value)


# --- Corner: rbac / rbac_customer_cannot_finalize_tournament ---

def test_customer_cannot_drive_tournament_lifecycle(api):
    """PRD 2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_customer_cannot_finalize_tournament
    """
    customer = fixtures.create_customer(name="TD Deny", email="td@x.com")
    venue = fixtures.create_venue(name="Deny Lake", water_type="LAKE")
    tournament = fixtures.create_tournament(venue["id"], name="Deny Cup",
                                            start_at="2026-09-28T06:00:00Z",
                                            end_at="2026-09-28T18:00:00Z",
                                            max_entries=10, prize_points=100)
    resp = api.transition_tournament(tournament["id"], {"action": "OPEN"},
                                     make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --- Difficulty: transitive_cascade / tournament_finalize_prize_cascade_depth2 ---

def _setup_weighed_entry_ready_to_finalize(api):
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer, _venue, tournament, entry = fixtures.setup_in_progress_entry(
        customer_kwargs={"name": "Angler H", "email": "h@x.com"},
        venue_kwargs={"name": "Bass Basin"},
        tournament_kwargs={"name": "Summer Slam", "entry_fee_cents": 2000,
                           "start_at": "2026-09-05T06:00:00Z", "end_at": "2026-09-05T18:00:00Z",
                           "max_entries": 20, "prize_points": 500},
    )
    fixtures.add_weigh_in(entry["id"], species="LARGEMOUTH_BASS", weight_grams=5000)
    return customer, tournament, entry


def test_tournament_finalize_sets_winner_and_placement(api):
    """PRD 3.7: "Each ranked entry receives a 1-based `placement`, its status moves from `WEIGHED` to `PLACED`, and the entry ranked first becomes the tournament's `winner_entry_id`."

    Design: Difficulty/transitive_cascade/tournament_finalize_prize_cascade_depth2
    """
    _customer, tournament, entry = _setup_weighed_entry_ready_to_finalize(api)
    finalized = validate_success(
        api.transition_tournament(tournament["id"], {"action": "FINALIZE"}, DIRECTOR)
    )
    assert finalized["winner_entry_id"] == entry["id"]
    got_entry = validate_success(api.get_tournament_entry(entry["id"], DIRECTOR))
    assert got_entry["placement"] == 1
    assert got_entry["status"] == "PLACED"


def test_tournament_finalize_credits_prize_cascade(api):
    """PRD 3.7: "A ledger entry with `delta_points` equal to the tournament's `prize_points`, a `reason` of `TOURNAMENT_PRIZE`, and a reference to the tournament is appended to the winning entry's customer, and that customer's balance and tier are recomputed."
    PRD 2.9: "the tier is `BRONZE` when the balance is below 500, `SILVER` when the balance is at least 500 but below 2000".

    Design: Difficulty/transitive_cascade/tournament_finalize_prize_cascade_depth2
    """
    customer, tournament, _entry = _setup_weighed_entry_ready_to_finalize(api)
    validate_success(api.transition_tournament(tournament["id"], {"action": "FINALIZE"}, DIRECTOR))
    holder = fixtures.get_customer(customer["id"])
    assert holder["loyalty_points_balance"] == 500, "prize credited by the finalize cascade"
    assert holder["loyalty_tier"] == "SILVER"


# --- Difficulty: boundary_precision_check / tournament_registration_deadline_boundary ---

def test_registration_at_close_instant_rejected(api):
    """PRD 3.7: "Registration requires that the tournament is `REGISTRATION_OPEN` and that the logical clock is strictly before `registration_close_at` (the close instant is exclusive); a registration when the tournament is not open or when now is at or after the close instant is rejected with `ERR_REGISTRATION_CLOSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/tournament_registration_deadline_boundary
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler J", email="j@x.com")
    _venue, tournament = fixtures.setup_open_tournament(
        venue_kwargs={"name": "Clock Lake"},
        tournament_kwargs={"name": "Deadline Cup", "entry_fee_cents": 1000,
                           "registration_open_at": "2026-07-01T00:00:00Z",
                           "registration_close_at": "2026-08-01T00:00:00Z",
                           "start_at": "2026-09-10T06:00:00Z", "end_at": "2026-09-10T18:00:00Z",
                           "max_entries": 50, "prize_points": 300},
    )
    fixtures.set_clock("2026-08-01T00:00:00Z")  # now == registration_close_at
    resp = api.create_tournament_entry(tournament["id"], {"customer_id": customer["id"]},
                                       make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


def test_registration_just_before_close_succeeds(api):
    """PRD 3.7: "Registration requires that the tournament is `REGISTRATION_OPEN` and that the logical clock is strictly before `registration_close_at` (the close instant is exclusive)".

    Design: Difficulty/boundary_precision_check/tournament_registration_deadline_boundary
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler J2", email="j2@x.com")
    _venue, tournament = fixtures.setup_open_tournament(
        venue_kwargs={"name": "Clock Lake 2"},
        tournament_kwargs={"name": "Deadline Cup 2", "entry_fee_cents": 1000,
                           "registration_open_at": "2026-07-01T00:00:00Z",
                           "registration_close_at": "2026-08-01T00:00:00Z",
                           "start_at": "2026-09-10T06:00:00Z", "end_at": "2026-09-10T18:00:00Z",
                           "max_entries": 50, "prize_points": 300},
    )
    fixtures.set_clock("2026-07-31T23:59:59Z")  # strictly before close
    entry = validate_success(
        api.create_tournament_entry(tournament["id"], {"customer_id": customer["id"]},
                                    make_customer_headers(customer["id"])),
        expected_status=201,
    )
    assert entry["status"] == "REGISTERED"


# --- Difficulty: cross_entity_state_dependency / weighin_blocked_when_tournament_not_in_progress ---

def test_weighin_before_tournament_start_rejected(api):
    """PRD 3.7: "A weigh-in requires the parent tournament to be `IN_PROGRESS`, else `ERR_TOURNAMENT_NOT_IN_PROGRESS` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/weighin_blocked_when_tournament_not_in_progress
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    _customer, _venue, _tournament, entry = fixtures.setup_registered_entry(
        customer_kwargs={"name": "Angler L", "email": "l@x.com"},
        venue_kwargs={"name": "Still Water"},
        tournament_kwargs={"name": "Early Bird", "entry_fee_cents": 1500,
                           "start_at": "2026-09-12T06:00:00Z", "end_at": "2026-09-12T18:00:00Z",
                           "max_entries": 30, "prize_points": 400},
    )
    # Tournament is REGISTRATION_OPEN (not started).
    resp = api.create_weigh_in(entry["id"], {"species": "CATFISH", "weight_grams": 3000}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_TOURNAMENT_NOT_IN_PROGRESS.value)


def test_weighin_accepted_after_tournament_start(api):
    """PRD 3.7: "The first accepted weigh-in moves the entry from `REGISTERED` to `WEIGHED`; each subsequent accepted weigh-in leaves it `WEIGHED`."

    Design: Difficulty/cross_entity_state_dependency/weighin_blocked_when_tournament_not_in_progress
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    _customer, _venue, _tournament, entry = fixtures.setup_in_progress_entry(
        customer_kwargs={"name": "Angler L2", "email": "l2@x.com"},
        venue_kwargs={"name": "Still Water 2"},
        tournament_kwargs={"name": "Early Bird 2", "entry_fee_cents": 1500,
                           "start_at": "2026-09-12T06:00:00Z", "end_at": "2026-09-12T18:00:00Z",
                           "max_entries": 30, "prize_points": 400},
    )
    weighed = validate_success(
        api.create_weigh_in(entry["id"], {"species": "CATFISH", "weight_grams": 3000}, DIRECTOR),
        expected_status=201,
    )
    assert weighed["status"] == "WEIGHED"


# --- Difficulty: resource_temporal_overlap / venue_adjacency_allowed_overlap_conflict ---

def _create_venue_with_baseline_tournament(api):
    venue = fixtures.create_venue(name="Contested Cove", water_type="SALTWATER")
    fixtures.create_tournament(venue["id"], name="T1", entry_fee_cents=1000,
                               registration_open_at="2026-08-01T00:00:00Z",
                               registration_close_at="2026-09-04T00:00:00Z",
                               start_at="2026-09-05T06:00:00Z", end_at="2026-09-05T18:00:00Z",
                               max_entries=40, prize_points=200)
    return venue


def test_venue_overlapping_tournament_rejected(api):
    """PRD 3.7: "creation is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409) when that window overlaps another non-cancelled tournament at the same venue, though windows that merely abut (one ending exactly when the next begins) are allowed."

    Design: Difficulty/resource_temporal_overlap/venue_adjacency_allowed_overlap_conflict
    """
    venue = _create_venue_with_baseline_tournament(api)
    # T2 starts 17:00 — overlaps T1's [06:00, 18:00).
    resp = api.create_tournament(
        {"venue_id": venue["id"], "name": "T2 overlap", "entry_fee_cents": 1000,
         "registration_open_at": "2026-08-01T00:00:00Z", "registration_close_at": "2026-09-04T00:00:00Z",
         "start_at": "2026-09-05T17:00:00Z", "end_at": "2026-09-06T01:00:00Z",
         "max_entries": 40, "prize_points": 200}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value)


def test_venue_adjacent_tournament_allowed(api):
    """PRD 3.7: "The tournament occupies its venue for the half-open interval from `start_at` to `end_at`; creation is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409) when that window overlaps another non-cancelled tournament at the same venue, though windows that merely abut (one ending exactly when the next begins) are allowed."

    Design: Difficulty/resource_temporal_overlap/venue_adjacency_allowed_overlap_conflict
    """
    venue = _create_venue_with_baseline_tournament(api)
    # T3 starts exactly at 18:00 == T1 end — abutting, allowed.
    t3 = validate_success(api.create_tournament(
        {"venue_id": venue["id"], "name": "T3 adjacent", "entry_fee_cents": 1000,
         "registration_open_at": "2026-08-01T00:00:00Z", "registration_close_at": "2026-09-04T00:00:00Z",
         "start_at": "2026-09-05T18:00:00Z", "end_at": "2026-09-05T20:00:00Z",
         "max_entries": 40, "prize_points": 200}, DIRECTOR), expected_status=201)
    assert t3["status"] == "SCHEDULED", "adjacency (end == next start) is accepted; no buffer"
