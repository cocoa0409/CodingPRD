"""Entity creation/defaults/not-found, pagination & reverse-lookup endpoints,
RBAC denials, optimistic-concurrency on confirm, and the scheduled sweep actions.

Each test translates exactly one design-index instance.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_guest_headers,
    set_clock,
    create_venue,
    create_bay,
    create_member,
    create_member_with_wallet,
    create_hold_reservation,
    confirm_reservation,
    create_queue_ticket,
    setup_venue_bay_member,
    setup_walkin_session,
    create_venue_payload,
    create_member_payload,
    create_bay_payload,
    create_gift_card_payload,
    create_reservation_payload,
    RANDOM_UUID,
)

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
GUEST = TEST_USERS["guest_headers"]


# ===========================================================================
# Queue B — entities instances
# ===========================================================================
def test_create_venue_returns_201_with_computed_counters(api):
    """PRD §2.10: "The computed roll-ups a venue exposes — `open_queue_length`, the
    count of its waiting queue tickets, and `available_bay_count`, its `bay_count`
    minus the number of its bays that are `OCCUPIED` or `OUT_OF_SERVICE` — always
    reflect the current state of the bays and tickets beneath it."
    PRD §2.4: "The `version` field starts at 1 when the resource is created and
    increases by exactly 1 on each mutation..."

    POST /golf/venues with name+bay_count returns 201; available_bay_count == bay_count
    (no bays created yet means none OCCUPIED/OUT_OF_SERVICE), open_queue_length 0,
    version 1.

    Design: Corner/entities/create_venue_returns_201_with_computed_counters
    """
    res = validate_success(api.create_venue(create_venue_payload(bay_count=5), RM), 201)
    assert res["available_bay_count"] == 5
    assert res["open_queue_length"] == 0
    assert res["version"] == 1


def test_create_reservation_missing_time_band_returns_invalid_request(api):
    """PRD §3.3: "A malformed body — a missing required field, an invalid enum, a
    non-positive span, a span that is not a whole number of 30-minute segments, or a
    window outside venue hours — is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.3: "...and the `time_band`. The `day_type` defaults to `WEEKDAY` (the
    alternative is `WEEKEND`), the `pay_source` defaults to `CARD_ON_FILE` (the
    alternative is `WALLET`), and `time_band` must be one of `TWILIGHT`, `OFFPEAK`, or
    `PEAK`."

    time_band is a required input with no default; omitting it on POST
    /golf/reservations returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_reservation_missing_time_band_returns_invalid_request
    """
    venue, bay, member = setup_venue_bay_member()
    payload = {
        "venue_id": venue["id"], "bay_id": bay["id"], "member_id": member["id"],
        "start_utc": "2026-06-02T18:00:00Z", "end_utc": "2026-06-02T19:00:00Z",
    }
    resp = api.create_reservation(payload, make_guest_headers(member["id"]))
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_member_default_tier_is_standard(api):
    """PRD §3.2: "A member's `tier` defaults to `STANDARD` and may also be `GOLD` or
    `PLATINUM`; the tier sets both the reservation discount and the loyalty multiplier
    described later. A new member starts with `wallet_balance_cents`, `loyalty_points`,
    and `pending_loyalty_points` all at 0."

    Omitting tier applies default STANDARD; wallet and loyalty all start at 0.

    Design: Corner/entities/create_member_default_tier_is_standard
    """
    res = validate_success(
        api.create_member({"email": "default-tier@x.com", "full_name": "D"}, GUEST), 201)
    assert res["tier"] == "STANDARD"
    assert res["wallet_balance_cents"] == 0
    assert res["loyalty_points"] == 0


def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.6: "...then existence of every path and foreign-key-referenced resource,
    validated left to right (`ERR_NOT_FOUND`)..."
    PRD §2.7: "Whenever a request names resources by path segment or by foreign key in
    the body, the server validates their existence from left to right and returns
    `ERR_NOT_FOUND` for the first one that does not resolve, before evaluating any
    business rule that depends on the resource."

    GET /golf/members/{random-uuid} for a non-existent member returns ERR_NOT_FOUND
    (404).

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    resp = api.get_member(RANDOM_UUID, FD)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_create_bay_with_unknown_venue_returns_not_found(api):
    """PRD §2.7: "Whenever a request names resources by path segment or by foreign key
    in the body, the server validates their existence from left to right and returns
    `ERR_NOT_FOUND` for the first one that does not resolve, before evaluating any
    business rule that depends on the resource."

    POST /golf/bays whose venue_id FK does not resolve returns ERR_NOT_FOUND (404).

    Design: Corner/entities/create_bay_with_unknown_venue_returns_not_found
    """
    resp = api.create_bay(create_bay_payload(RANDOM_UUID), RM)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_duplicate_member_email_returns_conflict(api):
    """PRD §3.2: "Anyone may register a **member** by supplying an `email`, which must
    be unique among members, and a `full_name`; a duplicate email is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Registering a second member with an email already in use returns
    ERR_DUPLICATE_EMAIL (409).

    Design: Corner/entities/duplicate_member_email_returns_conflict
    """
    validate_success(api.create_member({"email": "dup@x.com", "full_name": "First"}, RM), 201)
    resp = api.create_member({"email": "dup@x.com", "full_name": "Second"}, RM)
    validate_error(resp, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_gift_card_immutable_no_version_field(api):
    """PRD §2.4: "The `GiftCard` and the `Charge` are immutable after creation in the
    sense that they carry only `id` and `created_at` — they have no `updated_at` field
    and no `version` field at all. A gift card's stored value still changes as it is
    redeemed, but those changes are recorded on its value fields rather than via a
    version counter."

    A GiftCard read carries id/created_at but no version field; it is ISSUED with
    remaining_cents equal to its face value.

    Design: Corner/entities/gift_card_immutable_no_version_field
    """
    gift = validate_success(api.create_gift_card(create_gift_card_payload(5000), RM), 201)
    fetched = validate_success(api.get_gift_card(gift["id"], FD), 200)
    assert fetched["status"] == "ISSUED"
    assert fetched["remaining_cents"] == 5000
    assert "version" not in fetched
    assert "updated_at" not in fetched


# ===========================================================================
# Queue B — endpoints instances
# ===========================================================================
def test_list_venues_pagination_envelope_fields(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted
    it defaults to 10, and it is accepted only in the inclusive range from a minimum of
    1 to a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    With two venues, GET /golf/venues?limit=1 returns total_count 2 and has_more true.

    Design: Corner/endpoints/list_venues_pagination_envelope_fields
    """
    create_venue(name="VA", bay_count=1)
    create_venue(name="VB", bay_count=1)
    data, meta = validate_paginated(api.list_venues(FD, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_above_max_returns_pagination_invalid(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted
    it defaults to 10, and it is accepted only in the inclusive range from a minimum of
    1 to a maximum of 100. The `offset` parameter is the number of leading items to
    skip; when omitted it defaults to 0, and its minimum value is 0. A request whose
    `limit` or `offset` falls outside these bounds is rejected with
    `ERR_PAGINATION_INVALID`."

    GET /golf/venues?limit=500 (above max 100) returns ERR_PAGINATION_INVALID (400).

    Design: Corner/endpoints/pagination_limit_above_max_returns_pagination_invalid
    """
    resp = api.list_venues(FD, params={"limit": 500})
    validate_error(resp, "ERR_PAGINATION_INVALID", expected_status=400)


def test_reverse_lookup_bays_by_venue_id_returns_children(api):
    """PRD §2.7: "The entity graph is flat: resources are peers linked by foreign keys
    rather than nested under one another in the URL. A relationship is discovered by
    filtering a list endpoint on the relevant foreign-key query parameter. Bays may be
    filtered by `venue_id` or by `current_session_id`, where the `current_session_id`
    filter is the reverse lookup that finds the bay currently occupied by a given
    session."

    GET /golf/bays?venue_id={vid} returns the two Bay children of that venue.

    Design: Corner/endpoints/reverse_lookup_bays_by_venue_id_returns_children
    """
    venue = create_venue(bay_count=2)
    create_bay(venue["id"], label="B1")
    create_bay(venue["id"], label="B2")
    data, meta = validate_paginated(api.list_bays(FD, params={"venue_id": venue["id"]}))
    assert meta["total_count"] == 2


# ===========================================================================
# Queue B — rbac instances
# ===========================================================================
def test_guest_cannot_create_venue_forbidden_role(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation (per the authorization column of the endpoint table in §4)
    is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /golf/venues is RangeManager-only; a Guest attempt returns ERR_FORBIDDEN_ROLE
    (403).

    Design: Corner/rbac/guest_cannot_create_venue_forbidden_role
    """
    resp = api.create_venue(create_venue_payload(bay_count=1), GUEST)
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, or supplies a value that is not
    one of these three, is rejected with `ERR_UNAUTHENTICATED`."

    A request with no recognized X-User-Role returns ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.list_venues({})
    validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)


def test_guest_cannot_cancel_other_members_reservation(api):
    """PRD §2.1: "A `Guest` who attempts to mutate a reservation, queue ticket, lesson,
    or event package that they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    A Guest whose X-User-ID is not the reservation's member_id cannot cancel it;
    returns ERR_NOT_RESOURCE_OWNER (403).

    Design: Corner/rbac/guest_cannot_cancel_other_members_reservation
    """
    venue, bay, member_a = setup_venue_bay_member()
    member_b = create_member()
    res = create_hold_reservation(
        venue["id"], bay["id"], member_a["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK")
    resp = api.cancel_reservation(res["id"], make_guest_headers(member_b["id"]))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_front_desk_cannot_void_session_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation (per the authorization column of the endpoint table in §4)
    is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /golf/sessions/{id}/void is RangeManager-exclusive (per §4); FrontDesk
    attempting it returns ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/front_desk_cannot_void_session_forbidden
    """
    venue, bay, member, session = setup_walkin_session()
    resp = api.void_session(session["id"], FD)
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers instances
# ===========================================================================
def test_occ_stale_bay_version_on_confirm_returns_stale_version(api):
    """PRD §2.5: "Confirming a reservation is guarded against the reserved `Bay`. The
    confirm request must carry `expected_bay_version`, which is the client's last
    observed `version` of the bay being reserved. If the bay's current `version` has
    advanced since the client last read it — for example because another confirmation
    has just claimed an overlapping window on that bay and bumped the bay's `version`
    — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), so the writer cannot
    act on a stale view of the bay."

    Confirming with expected_bay_version one behind the bay's current version returns
    ERR_STALE_VERSION (412). (Bay version 1 at create; we send 0.)

    Design: Corner/cross_cutting_complexity_layers/occ_stale_bay_version_on_confirm_returns_stale_version
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue()
    bay = create_bay(venue["id"])
    member = create_member_with_wallet(50000)
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
    stale = bay["version"] - 1
    resp = api.confirm_reservation(
        res["id"], {"expected_bay_version": stale}, make_guest_headers(member["id"]))
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


def test_occ_correct_bay_version_on_confirm_succeeds_and_bumps(api):
    """PRD §2.4: "The `version` field starts at 1 when the resource is created and
    increases by exactly 1 on each mutation; it is the basis for optimistic concurrency
    control."
    PRD §3.4: "The reservation's `version` is incremented by 1, and the bay's `version`
    is incremented by 1 (this is the bump that the OCC guard of a competing confirmation
    observes)."

    Confirming with the correct expected_bay_version (1) succeeds, sets the reservation
    CONFIRMED, and bumps Bay.version to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_bay_version_on_confirm_succeeds_and_bumps
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue()
    bay = create_bay(venue["id"])
    member = create_member_with_wallet(50000)
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_bay_version": bay["version"]},
        make_guest_headers(member["id"])), 200)
    assert confirmed["status"] == "CONFIRMED"
    bay_after = validate_success(api.get_bay(bay["id"], RM), 200)
    assert bay_after["version"] == 2


def test_sweep_marks_confirmed_unplayed_reservation_no_show(api):
    """PRD §3.4: "A confirmed reservation that is never played becomes a **no-show**
    through the sweep. When the sweep runs and finds a `CONFIRMED` reservation whose
    `end_utc` is at or before the current clock and for which no `GameSession` carries
    that reservation's identifier, it moves the reservation to `NO_SHOW`. The no-show
    path sets `no_show_fee_cents` to `quoted_price_cents` times 0.50 rounded half up,
    but unlike the late cancel it does not create an additional `NO_SHOW_FEE` charge —
    the original retained bay charge is itself the penalty. The provisional loyalty
    never confirms and is reversed, and the reservation's `version` is incremented by
    1."

    After the clock passes a CONFIRMED reservation's end_utc with no realizing session,
    sweep_holds marks it NO_SHOW with no_show_fee_cents = round(6800*0.50) = 3400 and
    pending loyalty reversed to 0.

    Design: Corner/cross_cutting_complexity_layers/sweep_marks_confirmed_unplayed_reservation_no_show
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue(base_rate_cents_per_half_hour=2500)
    bay = create_bay(venue["id"])
    member = create_member_with_wallet(50000, tier="PLATINUM")
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK",
        day_type="WEEKDAY", pay_source="WALLET")
    confirmed = confirm_reservation(res["id"], member["id"], bay["version"])
    assert confirmed["quoted_price_cents"] == 6800
    set_clock("2026-06-02T20:00:00Z")
    validate_success(api.sweep_holds(venue["id"], RM), 200)
    res_after = validate_success(api.get_reservation(res["id"], RM), 200)
    assert res_after["status"] == "NO_SHOW"
    assert res_after["no_show_fee_cents"] == 3400
    member_after = validate_success(api.get_member(member["id"], RM), 200)
    assert member_after["pending_loyalty_points"] == 0


def test_queue_ticket_expires_after_ttl_on_sweep(api):
    """PRD §3.5: "A waiting ticket that grows stale is expired by the sweep: when a
    ticket's `created_at` plus the queue time-to-live of 60 minutes is at or before the
    current clock, the sweep moves it to `EXPIRED` and increments its `version` by 1."
    PRD §2.10: "The computed roll-ups a venue exposes — `open_queue_length`, the count
    of its waiting queue tickets..."

    A WAITING ticket older than the 60-min queue TTL is moved to EXPIRED by sweep_holds
    and no longer counts in open_queue_length.

    Design: Corner/cross_cutting_complexity_layers/queue_ticket_expires_after_ttl_on_sweep
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue()
    member = create_member()
    ticket = create_queue_ticket(venue["id"], member["id"])
    set_clock("2026-06-01T20:00:00Z")
    validate_success(api.sweep_holds(venue["id"], RM), 200)
    ticket_after = validate_success(api.get_queue_ticket(ticket["id"], FD), 200)
    assert ticket_after["status"] == "EXPIRED"
    venue_after = validate_success(api.get_venue(venue["id"], RM), 200)
    assert venue_after["open_queue_length"] == 0
