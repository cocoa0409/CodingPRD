"""Resource creation, retrieval, defaults, computed counters, listings.

Corner-design instances from sections: entities, endpoints, consistency_model.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId,
    create_tournament_payload, create_player_payload,
    assert_tournament, assert_player, assert_registration,
    TEST_USERS,
)
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_create_tournament_returns_201_draft_version1(api):
    """PRD §3.2: "A Director creates a tournament in DRAFT." PRD §2.4: "The
    version field is an integer that starts at 1 on creation and increments by
    one on every mutation."

    Design: Corner/entities/create_tournament_returns_201_with_fields
    """
    venue = F.create_venue()
    resp = api.create_tournament(create_tournament_payload(
        venue["id"], name="Cup", format="SINGLE_ELIM", max_participants=8,
        prize_pool_cents=5000), DIRECTOR)
    data = validate_success(resp, 201)
    assert_tournament(data)
    assert data["status"] == "DRAFT", data["status"]
    assert data["version"] == 1, data["version"]
    assert data["format"] == "SINGLE_ELIM"
    assert data["prize_pool_cents"] == 5000


def test_create_tournament_applies_policy_defaults(api):
    """PRD §3.2: "seeding_method (one of RATING, RANDOM_STABLE, MANUAL,
    defaulting to RATING) ... and paid_places (between 1 and 4 inclusive,
    defaulting to 2)."

    Design: Corner/entities/create_tournament_returns_201_with_fields
    """
    venue = F.create_venue()
    resp = api.create_tournament(create_tournament_payload(
        venue["id"], name="Cup", format="SINGLE_ELIM", max_participants=8,
        prize_pool_cents=5000), DIRECTOR)
    data = validate_success(resp, 201)
    assert data["seeding_method"] == "RATING", data["seeding_method"]
    assert data["paid_places"] == 2, data["paid_places"]


def test_get_tournament_unknown_id_not_found(api):
    """PRD §2.5: "If any referenced entity does not exist, the request is
    rejected with ERR_NOT_FOUND (HTTP 404) at the first unresolved identifier".

    Design: Corner/entities/get_tournament_not_found
    """
    resp = api.get_tournament(NON_EXISTENT_UUID, PUBLIC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_player_applies_default_rating_and_tax(api):
    """PRD §3.1: "rating, an integer skill number defaulting to 1000 ... and
    tax_id_provided, a boolean defaulting to false".

    Design: Corner/entities/create_player_applies_default_rating
    """
    resp = api.create_player(create_player_payload(display_name="P"), PUBLIC)
    data = validate_success(resp, 201)
    assert_player(data)
    assert data["rating"] == 1000, data["rating"]
    assert data["tax_id_provided"] is False, data["tax_id_provided"]


def test_tournament_registered_count_is_computed(api):
    """PRD §2.9: "registered_count is the number of registrations whose status is
    REGISTERED or CHECKED_IN. checked_in_count is the number of registrations
    whose status is CHECKED_IN."

    Design: Corner/entities/tournament_counters_are_computed
    """
    venue = F.create_venue()
    p1 = F.create_player()
    p2 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=8,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    F.register(t["id"], p1["id"])
    F.register(t["id"], p2["id"])
    data = F.get_tournament(t["id"])
    assert data["registered_count"] == 2, data["registered_count"]
    assert data["checked_in_count"] == 0, data["checked_in_count"]


def test_registration_immediately_visible(api):
    """PRD §2.11: "The system performs these cascades synchronously and
    immediately". PRD §3.2: "A registration is created with the tournament_id
    being entered, the player_id entering".

    Design: Corner/consistency_model/immediate_visibility_of_registration
    """
    venue = F.create_venue()
    p1 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=4,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    reg = F.register(t["id"], p1["id"])
    fetched = F.get_registration(reg["id"])
    assert fetched["id"] == reg["id"]
    assert fetched["status"] == "REGISTERED", fetched["status"]
    assert fetched["tournament_id"] == t["id"]


def test_list_registrations_paginated_envelope(api):
    """PRD §2.3: "Each list response reports limit, offset, total_count, and
    has_more in the meta object of the envelope, where total_count is the number
    of matching records before pagination and has_more indicates whether records
    remain beyond the returned page."

    Design: Corner/endpoints/list_registrations_pagination_envelope
    """
    venue = F.create_venue()
    p1 = F.create_player()
    p2 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=8,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    F.register(t["id"], p1["id"])
    F.register(t["id"], p2["id"])
    resp = api.list_registrations(PUBLIC, params={"tournament_id": t["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_venue_stations_reverse_reach(api):
    """PRD §3.1: "listing a venue's stations reverse-reaches every station whose
    venue_id points at that venue."

    Design: Corner/endpoints/reverse_reach_venue_stations
    """
    venue = F.create_venue()
    F.create_station(venue["id"], label="T1")
    F.create_station(venue["id"], label="T2")
    resp = api.list_venue_stations(venue["id"], PUBLIC)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert len(data) == 2, data
    assert all(row["venue_id"] == venue["id"] for row in data)
