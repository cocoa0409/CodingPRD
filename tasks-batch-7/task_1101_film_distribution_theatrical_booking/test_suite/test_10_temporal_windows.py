"""Temporal overlap semantics: closed zone windows vs half-open KDM windows
(PRD §2.9, §3.5, §3.9)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    is_valid_uuid,
    setup_distributor,
    setup_market,
    setup_film,
    setup_theatre,
    setup_screen,
    setup_proposed_booking,
    setup_accepted_booking,
    setup_delivered_booking,
    setup_upheld_zone_clearance,
    create_booking_agreement_payload,
    create_kdm_key_payload,
    ApiErrorId,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]


def _setup_zone_env(api):
    distributor = setup_distributor()
    did = distributor["id"]
    market = setup_market(did)
    film = setup_film(did, target_release_date="2026-06-01T00:00:00Z")
    t1 = setup_theatre(did, name="Cleared House", circuit="X")
    t2 = setup_theatre(did, name="Challenger House", circuit="Y")
    s2 = setup_screen(did, t2["id"], auditorium_label="Auditorium 1")
    zc = setup_upheld_zone_clearance(
        did, market["id"], film["id"], t1["id"],
        radius_km=5.0,
        effective_from_utc="2026-06-01T00:00:00Z",
        effective_until_utc="2026-06-30T00:00:00Z",
    )
    assert zc["status"] == "UPHELD", f"Setup failed: clearance is {zc['status']}"
    return did, film, t2, s2, zc


def test_booking_inside_upheld_closed_window_is_rejected(api):
    """PRD §3.9: "a booking that would land inside another theatre's `UPHELD` clearance
    radius during an overlapping window is rejected with `ERR_ZONE_CLEARANCE_CONFLICT`."
    PRD §2.9: "Zone clearances use a **closed interval**: both `effective_from_utc` and
    `effective_until_utc` are inclusive."

    Design: Difficulty/resource_temporal_overlap/zone_clearance_closed_interval_adjacency_conflicts
    """
    did, film, t2, s2, zc = _setup_zone_env(api)
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            film["id"], t2["id"], s2["id"], opening_date="2026-06-15T00:00:00Z"
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_ZONE_CLEARANCE_CONFLICT)


def test_booking_at_exactly_effective_until_conflicts_closed_interval(api):
    """PRD §2.9: "Because both ends are inclusive, pure adjacency is a conflict: a
    window ending at exactly the instant another begins overlaps it. A clearance
    remains in force at exactly its `effective_until_utc` and expires only once the
    logical clock has moved strictly past that instant."
    A booking whose engagement begins at exactly 2026-06-30 — the UPHELD clearance's
    inclusive end — still conflicts; a half-open reading would have allowed it.

    Design: Difficulty/resource_temporal_overlap/zone_clearance_closed_interval_adjacency_conflicts
    """
    did, film, t2, s2, zc = _setup_zone_env(api)
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            film["id"], t2["id"], s2["id"], opening_date="2026-06-30T00:00:00Z"
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_ZONE_CLEARANCE_CONFLICT)


def test_booking_after_window_end_is_allowed(api):
    """PRD §2.9: "A clearance remains in force at exactly its `effective_until_utc` and
    expires only once the logical clock has moved strictly past that instant."
    PRD §3.9: "two clearances for the same film conflict when the theatres lie within
    the clearance radius and their windows overlap, both endpoints inclusive".
    An engagement opening after 2026-06-30 does not overlap [06-01, 06-30] and is
    accepted as a proposal.

    Design: Difficulty/resource_temporal_overlap/zone_clearance_closed_interval_adjacency_conflicts
    """
    did, film, t2, s2, zc = _setup_zone_env(api)
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            film["id"], t2["id"], s2["id"], opening_date="2026-07-15T00:00:00Z"
        ),
        BOOKER,
    )
    ba = validate_success(res, 201)
    assert ba["deal_status"] == "PROPOSED"


def _setup_two_delivered_bookings_same_fingerprint(api):
    """Two accepted, DCP-delivered bookings on two screens of one theatre; the first
    carries an ISSUED key [2026-05-08, 2026-05-15) on fingerprint FP-1."""
    distributor = setup_distributor()
    did = distributor["id"]
    film = setup_film(did, target_release_date="2026-05-08T00:00:00Z")
    theatre = setup_theatre(did)
    s1 = setup_screen(did, theatre["id"], auditorium_label="Auditorium 1")
    s2 = setup_screen(did, theatre["id"], auditorium_label="Auditorium 2")
    ba1, ship1 = setup_delivered_booking(
        did, film["id"], theatre["id"], s1["id"], opening_date="2026-05-08T00:00:00Z"
    )
    k1 = get_success_data(api.create_kdm_key(
        did, ba1["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-08T00:00:00Z",
            valid_until_utc="2026-05-15T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    ))
    ba2, ship2 = setup_delivered_booking(
        did, film["id"], theatre["id"], s2["id"], opening_date="2026-05-08T00:00:00Z"
    )
    return did, ba1, ba2, k1


def test_kdm_adjacent_half_open_windows_do_not_conflict(api):
    """PRD §2.9: "Two key windows on the same screen conflict only when each window's
    start is strictly before the other window's end; adjacency — one key ending at
    exactly the instant the next begins — is not a conflict."
    K1 [05-08, 05-15) and K2 [05-15, 05-22) on the same screen: K2's start is not
    strictly before K1's end, so issuance succeeds.

    Design: Difficulty/resource_temporal_overlap/kdm_half_open_interval_adjacency_does_not_conflict
    """
    did, ba1, ba2, k1 = _setup_two_delivered_bookings_same_fingerprint(api)
    res = api.create_kdm_key(
        did, ba2["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-15T00:00:00Z",
            valid_until_utc="2026-05-22T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    )
    k2 = validate_success(res, 201)
    assert is_valid_uuid(k2["id"])
    assert k2["status"] == "ISSUED", f"adjacent half-open window must issue, got {k2['status']}"


def test_kdm_truly_overlapping_windows_conflict(api):
    """PRD §3.5: "the proposed window must not overlap another issued or live key on the
    same screen under the half-open semantics of §2.9, failing with
    `ERR_KDM_WINDOW_CONFLICT`."
    K2 [05-14, 05-22) starts strictly before K1's end 05-15, and K1 starts strictly
    before K2's end — a true overlap, rejected.

    Design: Difficulty/resource_temporal_overlap/kdm_half_open_interval_adjacency_does_not_conflict
    """
    did, ba1, ba2, k1 = _setup_two_delivered_bookings_same_fingerprint(api)
    res = api.create_kdm_key(
        did, ba2["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-14T00:00:00Z",
            valid_until_utc="2026-05-22T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_KDM_WINDOW_CONFLICT)
