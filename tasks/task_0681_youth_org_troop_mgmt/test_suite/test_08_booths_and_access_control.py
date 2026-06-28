"""Booth reservations (half-open overlap) and role-based access control."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
    make_registrar_headers,
    create_council_and_troop,
    create_member,
    setup_live_fundraiser_with_booth,
    create_council_payload,
    create_leader_credential_payload,
    create_booth_reservation_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_booth_touching_slot_allowed_half_open(api):
    """PRD §3.8: "Because the interval is half-open, two slots that merely touch
    end-to-end (a zero gap, where one ends exactly when the next begins) are allowed
    and do not conflict, in contrast to the closed, touch-rejecting rule used for a
    member's confirmed events."

    Design: Difficulty/resource_temporal_overlap/booth_half_open_overlap_same_location
    """
    council, troop, fr, booth1 = setup_live_fundraiser_with_booth(
        location_code="LOC-A", starts_at="2026-05-01T10:00:00Z", ends_at="2026-05-01T12:00:00Z"
    )
    # New slot starts exactly when booth1 ends (12:00) -> half-open, allowed.
    touch = validate_success(
        api.create_booth_reservation(
            fr["id"],
            create_booth_reservation_payload(troop["id"], "LOC-A", "2026-05-01T12:00:00Z", "2026-05-01T14:00:00Z"),
            LEAD,
        ),
        201,
    )
    assert touch["status"] == "BOOKED"


def test_booth_interior_overlap_rejected(api):
    """PRD §3.8: "within a single location, a new booked slot's half-open
    [starts_at, ends_at) interval must not overlap that of any other still-BOOKED
    reservation at the same location_code ... A reservation whose interval overlaps
    an existing booked slot at the same location is rejected with ERR_BOOTH_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/booth_half_open_overlap_same_location
    """
    council, troop, fr, booth1 = setup_live_fundraiser_with_booth(
        location_code="LOC-A", starts_at="2026-05-01T10:00:00Z", ends_at="2026-05-01T12:00:00Z"
    )
    # 11:00-13:00 overlaps the interior of 10:00-12:00.
    resp = api.create_booth_reservation(
        fr["id"],
        create_booth_reservation_payload(troop["id"], "LOC-A", "2026-05-01T11:00:00Z", "2026-05-01T13:00:00Z"),
        LEAD,
    )
    validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT.value)


def test_troopleader_cannot_recharter(api):
    """PRD §2.1: "The CouncilRegistrar exclusively owns council creation, troop
    creation, fundraiser creation, the three troop charter-lifecycle transitions
    (recharter, lapse, drop)."
    PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/troopleader_cannot_recharter
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "R1"}, troop_overrides={"unit_number": "R-1"}
    )
    troop_now = get_success_data(api.get_troop(troop["id"], REG))
    resp = api.recharter_troop(troop["id"], {"expected_troop_version": troop_now["version"]}, LEAD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_troopleader_cannot_resolve_bgcheck(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/troopleader_cannot_resolve_bgcheck
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "R2"}, troop_overrides={"unit_number": "R-2"}
    )
    adult = create_member(troop["id"], member_type="ADULT", full_name="Adult R", birthdate="1980-01-01")
    cred = get_success_data(
        api.create_leader_credential(adult["id"], create_leader_credential_payload(requested_by_user_id="leader-bob"), LEAD)
    )
    get_success_data(api.start_bgcheck(cred["id"], REG))

    resp = api.resolve_bgcheck(cred["id"], {"outcome": "CLEAR"}, LEAD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unknown_role_rejected_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a known
    role, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    resp = api.create_council(create_council_payload(name="R3"), ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
