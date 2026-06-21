"""Artists, flash designs, and the studio's standing resources.

Covers artist registration defaults, enum/required-field validation, not-found,
the flash-design FK requirement, and retiring a flash that is RESERVED.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_artist_headers,
    create_artist, setup_confirmed_flash_appointment,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]


def test_create_artist_returns_201_with_defaults(api):
    """PRD §3.1: "The `commission_pct` is the fraction of a session's gross paid
    out to the artist, with the studio keeping the remainder; it defaults to 0.70
    and must be greater than 0 and at most 1."
    PRD §3.1: "The `reliability_score` starts at 100 and is recomputed ... The
    `completed_session_count` starts at 0 and rises by one each time one of the
    artist's appointments reaches `COMPLETED`."
    PRD §3.1: "The `accepting_custom` flag declares whether the artist currently
    takes new entries into their custom queue and defaults to true."

    Design: Corner/entities/create_artist_returns_201_with_defaults
    """
    data = validate_success(
        api.create_artist(
            {"display_name": "Solo Artist", "discipline": "BOTH", "hourly_rate_cents": 15000},
            MANAGER,
        ),
        expected_status=201,
    )
    assert data["commission_pct"] == 0.70, f"commission_pct default expected 0.70, got {data['commission_pct']}"
    assert data["accepting_custom"] is True, "accepting_custom default expected true"
    assert data["reliability_score"] == 100, f"reliability_score default expected 100, got {data['reliability_score']}"
    assert data["completed_session_count"] == 0, "completed_session_count default expected 0"


def test_get_artist_not_found_returns_404(api):
    """PRD §2.6: "The first identifier that does not correspond to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_artist_not_found_returns_404
    """
    resp = api.get_artist("00000000-0000-4000-8000-000000000000", MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_artist_invalid_discipline_enum_rejected(api):
    """PRD §3.1: "The `discipline` declares the artist's specialty and must be
    one of `TATTOO`, `PIERCING`, or `BOTH`."
    PRD §2.9: "a value that is not a member of its declared enumeration is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_artist_invalid_discipline_enum_rejected
    """
    resp = api.create_artist(
        {"display_name": "Bad Disc", "discipline": "AIRBRUSH", "hourly_rate_cents": 15000},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_flash_design_requires_existing_artist_fk(api):
    """PRD §2.6: "only then are foreign keys in the request body resolved. The
    first identifier that does not correspond to an existing resource causes the
    request to be rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/flash_design_requires_existing_artist_fk
    """
    ghost = "00000000-0000-4000-8000-000000000001"
    resp = api.create_flash_design(
        factories.create_flash_design_payload(ghost, title="Ghost",
                                              piece_price_cents=30000, estimated_minutes=60),
        make_artist_headers(ghost),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_retire_flash_while_reserved_invalid_state(api):
    """PRD §3.3: "While a flash piece is `AVAILABLE`, it may be retired so that
    it can no longer be booked; retiring advances `status` from `AVAILABLE` to
    `RETIRED`, and is permitted only when the piece is not currently `RESERVED`."
    PRD §3.7: "if the appointment references a flash piece, that `FlashDesign`
    moves from `AVAILABLE` to `RESERVED`".
    PRD §3.11 (state lockdown analog) / §2.9: "an operation requested against a
    resource that is not in a state permitting the transition fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/flash_retire_while_reserved_invalid_state
    """
    ctx = setup_confirmed_flash_appointment()
    flash_id = ctx["flash_design_id"]
    artist_id = ctx["artist_id"]
    # The confirmed appointment reserved the flash; retiring must now fail.
    resp = api.retire_flash_design(flash_id, make_artist_headers(artist_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_flash_design(flash_id, MANAGER))
    assert after["status"] == "RESERVED", f"flash must stay RESERVED, got {after['status']}"
