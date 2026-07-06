"""Creation, defaults, reads, listing, and immediate side-effect visibility.

Corner-design (queue B) translations: entities, endpoints, consistency_model.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    create_election_payload, create_polling_place_payload,
    create_election, create_place, create_kit_at_place,
    setup_open_place, setup_staffed_place,
    assert_election, assert_polling_place,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]


def test_create_election_initializes_stock_and_status(api):
    """PRD §3.1: "On creation the election's `status` begins at `PLANNING` and its
    `unallocated_ballot_stock` is initialized to equal `initial_ballot_stock`."
    PRD §4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/create_election_success_returns_201
    """
    resp = api.create_election(
        create_election_payload(initial_ballot_stock=10000), ADMIN
    )
    data = validate_success(resp, 201)
    assert_election(data)
    assert data["status"] == "PLANNING"
    assert data["unallocated_ballot_stock"] == 10000, (
        f"unallocated_ballot_stock should equal initial_ballot_stock 10000, "
        f"got {data['unallocated_ballot_stock']}"
    )


def test_get_missing_election_returns_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_missing_election_returns_not_found
    """
    resp = api.get_election(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_place_applies_accessibility_and_slot_defaults(api):
    """PRD §3.2: "`wheelchair_accessible` and `accessible_parking` are booleans that each
    default to false, and `ada_voting_stations` is a count of ADA-compliant ballot-marking
    stations of at least zero, defaulting to zero."
    PRD §3.2: "On creation `slots_open` is initialized to `staffing_capacity`".
    PRD §2.5: "It is one of `SETUP`, `OPEN`, `SUSPENDED`, `CLOSED`, or `RECONCILED`, starting
    at `SETUP`."

    Design: Corner/entities/create_place_defaults_applied
    """
    el = create_election(api)
    resp = api.create_polling_place(
        create_polling_place_payload(el["id"], staffing_capacity=4, station_capacity=3), ADMIN
    )
    data = validate_success(resp, 201)
    assert_polling_place(data)
    assert data["wheelchair_accessible"] is False
    assert data["ada_voting_stations"] == 0
    assert data["readiness_posture"] == "SETUP"
    assert data["slots_open"] == 4, f"slots_open should equal staffing_capacity 4, got {data['slots_open']}"


def test_list_places_returns_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/list_places_pagination_envelope
    """
    el = create_election(api)
    create_place(api, election_id=el["id"], name="P1")
    create_place(api, election_id=el["id"], name="P2")
    resp = api.list_polling_places(ADMIN, params={"election_id": el["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert len(data) == 2, f"expected 2 places, got {len(data)}"


def test_custody_event_audit_log_is_append_only_reachable(api):
    """PRD §3.6: "Every custody change is recorded by appending an immutable **CustodyEvent**,
    which captures the `supply_kit_id`, the `event_type`, the `from_state` and `to_state` of
    the kit around the transition, the `actor_role` that performed it, and an optional
    free-text `note`."

    Design: Corner/endpoints/custody_events_audit_log_reverse_reachable
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    kit = create_kit_at_place(api, election_id=el["id"], place_id=pp["id"])  # ISSUE, DISPATCH, RECEIVE
    resp = api.list_custody_events(kit["id"], CUSTODY)
    data, meta = validate_paginated(resp)
    assert len(data) == 3, f"expected 3 custody events after ISSUE/DISPATCH/RECEIVE, got {len(data)}"
    assert meta["total_count"] == 3


def test_cast_provisional_increments_cast_count_only(api):
    """PRD §3.7: "A newly cast ballot's `status` begins at `CAST`, and the place's
    `provisional_cast_count` is incremented."

    Design: Corner/endpoints/provisional_cast_increments_cast_count
    """
    ctx = setup_open_place(api)
    pp_id = ctx["place"]["id"]
    resp = api.create_provisional_ballot(
        {"polling_place_id": pp_id, "voter_name": "V1", "reason": "NO_ID"}, CAPTAIN
    )
    validate_success(resp, 201)
    place = get_success_data(api.get_polling_place(pp_id, ADMIN))
    assert place["provisional_cast_count"] == 1
    assert place["provisional_accepted_count"] == 0, (
        "provisional_accepted_count must stay 0 until adjudication"
    )


def test_activate_reflects_slot_counts_immediately(api):
    """PRD §2.10: "activating an assignment increments `slots_filled` and decrements
    `slots_open` by one; withdrawing an active assignment does the reverse."

    Design: Corner/consistency_model/immediate_consistency_slots_visible_in_response
    """
    ctx = setup_staffed_place(api, staffing_capacity=4, open_voting=False,
                              with_equipment=False, with_kit=False)
    place = get_success_data(api.get_polling_place(ctx["place"]["id"], CAPTAIN))
    assert place["slots_filled"] == 1, f"expected slots_filled 1, got {place['slots_filled']}"
    assert place["slots_open"] == 3, f"expected slots_open 3, got {place['slots_open']}"
