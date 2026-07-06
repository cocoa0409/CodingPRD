"""Placing date holds: the ordered place-hold gauntlet — officiant certification,
style, optimistic concurrency, closed+buffer double-booking, and capacity
(PRD Sections 2.7, 2.9, 3.3).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
    create_booking_payload, create_date_hold_payload,
    make_couple_headers,
)


def test_officiant_double_booked_when_buffered_windows_collide(api):
    """PRD §2.9: "A conflict exists when the candidate window's start is at or
    before an existing window's end and that existing window's start is at or
    before the candidate window's end. Because the intervals are closed, windows
    that merely touch at an endpoint do collide. A conflict is rejected with
    `ERR_OFFICIANT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/officiant_double_booked_closed_buffer
    """
    ctx = fx.setup_held_booking(api, officiant_overrides={"travel_buffer_minutes": 180})
    b2 = fx.create_booking(
        api, ctx.officiant, ctx.couple, ctx.package, ctx.venue,
        ceremony_start="2026-09-01T18:30:00Z", ceremony_end="2026-09-01T19:30:00Z",
    )
    version = fx.current_officiant_version(api, ctx.officiant["id"])
    resp = api.create_date_hold(
        create_date_hold_payload(b2["id"], version), make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_DOUBLE_BOOKED.value)


def test_double_booking_rejection_leaves_officiant_hold_count_unchanged(api):
    """PRD §3.3: "The officiant's `active_hold_count` is always kept equal to the
    number of that officiant's date holds in `HELD` or `CONFIRMED`; placing a hold
    adds one, and releasing or expiring a hold subtracts one, so placing and then
    releasing a hold returns the count to its prior value."

    Design: Difficulty/resource_temporal_overlap/officiant_double_booked_closed_buffer
    """
    ctx = fx.setup_held_booking(api, officiant_overrides={"travel_buffer_minutes": 180})
    b2 = fx.create_booking(
        api, ctx.officiant, ctx.couple, ctx.package, ctx.venue,
        ceremony_start="2026-09-01T18:30:00Z", ceremony_end="2026-09-01T19:30:00Z",
    )
    version = fx.current_officiant_version(api, ctx.officiant["id"])
    api.create_date_hold(
        create_date_hold_payload(b2["id"], version), make_couple_headers(ctx.couple["id"])
    )
    officiant = fx.get_officiant(api, ctx.officiant["id"])
    assert officiant["active_hold_count"] == 1


def test_placehold_certification_gate_outranks_double_booking(api):
    """PRD §3.3: "Then the officiant must be certified for the venue's jurisdiction
    — the venue's `jurisdiction` must appear among the officiant's
    `certified_jurisdictions` — otherwise `ERR_OFFICIANT_NOT_CERTIFIED`. Then the
    booking's `required_style` must be one of the officiant's offered `styles`,
    otherwise `ERR_STYLE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/placehold_safety_outranks_constraint
    """
    ref = fx.setup_reference(api, officiant_overrides={"travel_buffer_minutes": 180})
    venue_ny = fx.create_venue(api, jurisdiction="NY")
    b1 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-01T15:00:00Z", ceremony_end="2026-09-01T16:00:00Z")
    fx.place_hold(api, b1, ref.couple, ref.officiant["version"])
    version = fx.current_officiant_version(api, ref.officiant["id"])
    b2 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, venue_ny,
                           ceremony_start="2026-09-01T15:30:00Z", ceremony_end="2026-09-01T16:30:00Z")
    resp = api.create_date_hold(
        create_date_hold_payload(b2["id"], version), make_couple_headers(ref.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_NOT_CERTIFIED.value)


def test_placehold_uncertified_venue_rejected(api):
    """PRD §3.3: "Then the officiant must be certified for the venue's jurisdiction
    — the venue's `jurisdiction` must appear among the officiant's
    `certified_jurisdictions` — otherwise `ERR_OFFICIANT_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/placehold_safety_outranks_constraint
    """
    ref = fx.setup_reference(api)  # officiant certified only ["CA"]
    venue_ny = fx.create_venue(api, jurisdiction="NY")
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, venue_ny)
    resp = api.create_date_hold(
        create_date_hold_payload(booking["id"], ref.officiant["version"]),
        make_couple_headers(ref.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_NOT_CERTIFIED.value)


def test_placehold_style_mismatch_rejected(api):
    """PRD §3.3: "Then the booking's `required_style` must be one of the officiant's
    offered `styles`, otherwise `ERR_STYLE_MISMATCH`."

    Design: Corner/validations/placehold_style_mismatch_returns_style_mismatch
    """
    ref = fx.setup_reference(
        api, officiant_overrides={"styles": ["RELIGIOUS"], "denomination": "CHRISTIAN"}
    )
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                                required_style="SECULAR")
    resp = api.create_date_hold(
        create_date_hold_payload(booking["id"], ref.officiant["version"]),
        make_couple_headers(ref.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STYLE_MISMATCH.value)


def test_placehold_capacity_exceeded_rejected(api):
    """PRD §3.3: "Finally, capacity is enforced: if the officiant's
    `active_hold_count` is already at or above `max_active_holds`, the request is
    rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/placehold_capacity_exceeded_returns_capacity_exceeded
    """
    ctx = fx.setup_held_booking(api, officiant_overrides={"max_active_holds": 1})
    b2 = fx.create_booking(
        api, ctx.officiant, ctx.couple, ctx.package, ctx.venue,
        ceremony_start="2026-11-01T15:00:00Z", ceremony_end="2026-11-01T16:00:00Z",
    )
    version = fx.current_officiant_version(api, ctx.officiant["id"])
    resp = api.create_date_hold(
        create_date_hold_payload(b2["id"], version), make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_placehold_with_stale_officiant_version_rejected(api):
    """PRD §2.7: "If another writer has advanced the officiant's version since the
    client read it — for example, another hold placement, or a release or expiry
    that adjusted the officiant's `active_hold_count` — the value is stale and the
    request is rejected with `ERR_STALE_OFFICIANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_officiant_version_rejected
    """
    ref = fx.setup_reference(api)
    stale_version = ref.officiant["version"]
    b1 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-01T15:00:00Z", ceremony_end="2026-09-01T16:00:00Z")
    fx.place_hold(api, b1, ref.couple, stale_version)  # advances officiant.version
    b2 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-12-01T15:00:00Z", ceremony_end="2026-12-01T16:00:00Z")
    resp = api.create_date_hold(
        create_date_hold_payload(b2["id"], stale_version), make_couple_headers(ref.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_OFFICIANT_VERSION.value)
