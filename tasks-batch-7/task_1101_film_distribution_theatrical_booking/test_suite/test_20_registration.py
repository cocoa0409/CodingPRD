"""Registration surface: defaults, computed fields, envelopes, 404s (PRD §2, §3.1–3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_distributor_payload,
    create_film_payload,
    create_market_payload,
    create_screen_payload,
    create_booking_agreement_payload,
    setup_distributor,
    setup_film,
    setup_market,
    setup_theatre,
    setup_screen,
    setup_distributor_film_theatre_screen,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_distributor_creation_applies_system_defaults(api):
    """PRD §3.1: "A new distributor starts with `week_epoch` at 0, a `lifecycle_posture`
    of `ACTIVE`, and the shared logical clock at its startup default."
    PRD §2.5: "At server startup it reads exactly `2026-05-01T00:00:00Z`; before any
    clock call has been made it must hold this default and must never fall back to
    wall-clock time."

    Design: Corner/entities/distributor_creation_applies_system_defaults
    """
    res = api.create_distributor(create_distributor_payload(), ADMIN)
    distributor = validate_success(res, 201)
    assert distributor["week_epoch"] == 0
    assert distributor["lifecycle_posture"] == "ACTIVE"

    read = validate_success(api.get_distributor(distributor["id"], AUDITOR), 200)
    assert read["week_epoch"] == 0
    assert read["lifecycle_posture"] == "ACTIVE"
    assert str(read["logical_clock_utc"]).startswith("2026-05-01T00:00:00"), (
        f"logical clock must hold the startup default, got {read['logical_clock_utc']}"
    )


def test_film_computed_fields_derive_correctly(api):
    """PRD §3.2: "The film's `theatrical_window_end` is computed as exactly 90 days
    after `target_release_date` and defines the exclusive theatrical window."
    PRD §3.2: "New films carry `lifecycle_status` `PRE_RELEASE` and a
    `screens_committed` count of 0".
    2026-05-01 + 90 days = 2026-07-30.

    Design: Corner/entities/film_computed_fields_derive_correctly
    """
    distributor = setup_distributor()
    film = setup_film(distributor["id"], target_release_date="2026-05-01T00:00:00Z")
    assert film["screens_committed"] == 0

    read = validate_success(api.get_film(distributor["id"], film["id"], AUDITOR), 200)
    assert read["screens_committed"] == 0
    assert str(read["theatrical_window_end"]).startswith("2026-07-30T00:00:00"), (
        f"theatrical_window_end must be target_release_date + 90 days, "
        f"got {read['theatrical_window_end']}"
    )


def test_film_invalid_genre_enum_rejected(api):
    """PRD §2.4: "Independently of any business rule, a request whose payload is
    malformed, missing a required field, or carrying an invalid enum value is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400) before business validation begins."
    `genre` admits only NARRATIVE, DOCUMENTARY, ANIMATION, GENRE_HORROR (PRD §3.2).

    Design: Corner/entities/film_invalid_genre_enum_rejected
    """
    distributor = setup_distributor()
    res = api.create_film(
        distributor["id"], create_film_payload(genre="WESTERN"), BOOKER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_film_missing_required_field_rejected(api):
    """PRD §2.4: "Independently of any business rule, a request whose payload is
    malformed, missing a required field, or carrying an invalid enum value is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400) before business validation begins."
    PRD §3.2: "A `Booker` registers a film with a `title`, a `genre` of `NARRATIVE`,
    `DOCUMENTARY`, `ANIMATION`, or `GENRE_HORROR`" — the title is a required input.

    Design: Corner/entities/film_missing_required_field_rejected
    """
    distributor = setup_distributor()
    payload = create_film_payload()
    del payload["title"]
    res = api.create_film(distributor["id"], payload, BOOKER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_distributor_get_not_found_returns_404(api):
    """PRD §2.6: "each identifier must resolve to an existing resource within the scope
    established by the identifiers to its left, and the request is rejected with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to resolve."

    Design: Corner/entities/distributor_get_not_found_returns_404
    """
    res = api.get_distributor(NON_EXISTENT_UUID, AUDITOR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_market_list_pagination_respects_limit_offset(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    sets the number of items skipped and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/market_list_pagination_respects_limit_offset
    """
    distributor = setup_distributor()
    did = distributor["id"]
    setup_market(did, code="NYC")
    setup_market(did, code="LA")
    setup_market(did, code="CHI", population_tier="TIER_2")

    data, meta = validate_paginated(api.list_markets(did, AUDITOR, params={"limit": 2, "offset": 0}))
    assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    data2, meta2 = validate_paginated(api.list_markets(did, AUDITOR, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_screen_creation_under_unknown_theatre_returns_404(api):
    """PRD §2.6: "A shipment addressed under the wrong booking agreement, or a screen
    addressed under the wrong theatre, is therefore a 404 at the mismatched segment,
    never a business-rule error."

    Design: Corner/entities/screen_fk_to_theatre_enforced
    """
    distributor = setup_distributor()
    res = api.create_screen(
        distributor["id"], NON_EXISTENT_UUID, create_screen_payload(), ADMIN
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_booking_agreement_screen_theatre_mismatch_rejected(api):
    """PRD §3.3: "the named screen must belong to the named theatre
    (`ERR_SCREEN_THEATRE_MISMATCH`)".

    Design: Corner/entities/booking_agreement_screen_theatre_mismatch_rejected
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    t2 = setup_theatre(did, name="Theatre Two")
    s2 = setup_screen(did, t2["id"], auditorium_label="Auditorium B")
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            env["film"]["id"], env["theatre"]["id"], s2["id"]
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_SCREEN_THEATRE_MISMATCH)
