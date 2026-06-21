"""League creation, input validation, listing, and team-name uniqueness.

Translates Corner-design instances in Section 1 (entities) that pin
League/Team CRUD-shape claims and pagination.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_league,
    create_league,
    create_league_payload,
    create_team,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_league_creation_returns_setup_status_and_version_one(api, commissioner_headers):
    """PRD §3.1: "On creation, the league's `status` is `SETUP`, its
    `current_week` is 0, and its `total_faab_pool_cents` is 0 — the pool
    baseline is established later, at draft start."
    PRD §2.4: "`version` is an integer that begins at 1 on insert and
    increments by 1 on every mutation of the row."

    Design: Corner/entities/league_creation_returns_full_envelope_with_system_fields
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_league_payload(
        name="L1", draft_type="SNAKE", roster_size=2, starter_slot_count=1,
        ir_slot_count=0, faab_budget_cents=5000, veto_threshold=1,
        keeper_limit=0, playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    res = api.create_league(payload, commissioner_headers)
    league = validate_success(res, expected_status=201)
    assert_league(league)
    assert league["status"] == "SETUP"
    assert league["version"] == 1
    assert league["current_week"] == 0
    assert league["total_faab_pool_cents"] == 0


def test_get_nonexistent_league_returns_not_found(api, commissioner_headers):
    """PRD §2.7: "path-id existence, validated left-to-right across the URL
    so `/leagues/{id}/finalize-trade/{trade_id}` resolves `{id}` before
    `{trade_id}` (`ERR_NOT_FOUND`)".

    Design: Corner/entities/get_nonexistent_league_returns_not_found
    """
    res = api.get_league(NON_EXISTENT_UUID, commissioner_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_missing_required_field_on_league_create_rejected(api, commissioner_headers):
    """PRD §2.7: "the catch-all well-formed-request check that covers
    missing fields, enum values out of range, and numeric ranges
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/missing_required_field_on_league_create
    """
    payload = create_league_payload()
    del payload["draft_type"]
    res = api.create_league(payload, commissioner_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_invalid_enum_draft_type_rejected(api, commissioner_headers):
    """PRD §3.1: "its `draft_type` which is one of `SNAKE` or `AUCTION`".
    PRD §2.7: "the catch-all well-formed-request check that covers missing
    fields, enum values out of range, and numeric ranges
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/invalid_enum_draft_type_rejected
    """
    payload = create_league_payload(draft_type="SALARY")
    res = api.create_league(payload, commissioner_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_computed_status_field_is_setup_after_create(api, commissioner_headers):
    """PRD §3.1: "On creation, the league's `status` is `SETUP`, its
    `current_week` is 0, and its `total_faab_pool_cents` is 0".

    Design: Corner/entities/computed_field_status_ignored_in_input
    """
    payload = create_league_payload()
    # Attempt to set a computed field — server should ignore and stamp SETUP.
    payload["status"] = "COMPLETE"
    res = api.create_league(payload, commissioner_headers)
    league = validate_success(res, expected_status=201)
    assert league["status"] == "SETUP"


def test_list_leagues_paginated_envelope(api, commissioner_headers):
    """PRD §2.3: "The `meta` block on a list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the count of all matching rows after filters but before
    slicing, and `has_more` is true when more rows exist beyond the current
    window."

    Design: Corner/entities/list_leagues_paginated_envelope
    """
    set_clock("2026-08-01T00:00:00Z")
    create_league(name="L_paginate_1", draft_type="SNAKE")
    create_league(name="L_paginate_2", draft_type="AUCTION")
    res = api.list_leagues(commissioner_headers, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_team_display_name_unique_within_league_case_insensitive(api, commissioner_headers):
    """PRD §3.1: "`display_name` (1–40 characters, unique within the league
    when compared case-insensitively, against `ERR_INVALID_REQUEST` on
    collision)".

    Design: Corner/entities/team_unique_display_name_within_league
    """
    set_clock("2026-08-01T00:00:00Z")
    league = create_league(name="Unique L")
    create_team(league["id"], display_name="Alpha", division="E")
    res = api.create_team(
        league["id"],
        {"display_name": "alpha", "division": "E"},
        commissioner_headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
