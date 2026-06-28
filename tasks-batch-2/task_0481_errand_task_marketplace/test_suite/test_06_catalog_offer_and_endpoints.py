"""Catalog creation, offer-time temporal gates, recurring series, listing, rebook, RBAC.

Translates corner queue (entities, validations temporal, calculations.series, endpoints
listing/rebook/series-end, rbac, cross_cutting clock-default).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_category_payload, create_booking_payload, create_claim_payload,
    create_rebook_payload, create_message_payload, NON_EXISTENT_UUID,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, setup_series, create_offered_booking, create_booking,
    create_claimed_booking, create_completed_booking, create_in_progress_booking,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


def test_create_tasker_returns_201_with_defaults(api):
    """PRD §3.1: "A new tasker opens in ACTIVE status with a trust_score of 100."
    PRD §3.7: "reported as 0.0 when the tasker has no published reviews."

    Design: Corner/entities/create_tasker_returns_201_with_defaults
    """
    tk = validate_success(api.create_tasker(
        {"full_name": "Fresh Tasker", "hourly_rate_cents": 4500}, DISP), 201)
    assert tk["status"] == "ACTIVE"
    assert tk["trust_score"] == 100
    assert tk["avg_rating"] == 0.0


def test_get_nonexistent_booking_returns_not_found(api):
    """PRD §2.8: "returning the typed not-found error for that resource: ERR_BOOKING_NOT_FOUND".

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    res = api.get_booking(NON_EXISTENT_UUID, DISP)
    validate_error(res, "ERR_BOOKING_NOT_FOUND")


def test_create_category_missing_pricing_model_rejected(api):
    """PRD §2.9: "field-domain validation — enum membership, numeric ranges, and the like —
    failing with ERR_INVALID_REQUEST."
    PRD §3.1: "A Dispatcher creates a category by supplying its display name, a pricing_model,
    a default_duration_minutes that fixes the scheduled window length for fixed-price work and
    must be at least 15 minutes, and an optional requires_vetting flag that defaults to not
    requiring vetting."

    Design: Corner/entities/create_category_missing_required_field_returns_invalid_request
    """
    res = api.create_category({"name": "No Model", "default_duration_minutes": 60}, DISP)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_booking_default_tip_zero(api):
    """PRD §3.2: "an optional tip_cents that defaults to 0 and must be at least 0."
    PRD §3.2: "A new booking is born in DRAFT status with no tasker attached".

    Design: Corner/entities/create_booking_default_tip_zero
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Def Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    payload = create_booking_payload(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z")
    payload.pop("tip_cents", None)
    bk = validate_success(api.create_booking(payload, make_client_headers(cl)), 201)
    assert bk["tip_cents"] == 0
    assert bk["status"] == "DRAFT"


def test_chat_message_is_append_only_no_version(api):
    """PRD §3.8: "The server stamps each message with its created_at and derives its
    sender_role — either CLIENT or TASKER — from the authenticated caller rather than from the
    payload."
    PRD §2.4: "a ChatMessage is an append-only record that carries only id and created_at — it
    has neither an updated_at nor a version field, because a chat message is never modified
    after it is posted."

    Design: Corner/entities/chat_message_immutable_append_only_no_version
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Chat Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Chat Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)
    msg = validate_success(api.post_message(
        bk["id"], create_message_payload("On my way"), make_tasker_headers(tk)), 201)
    assert msg["sender_role"] == "TASKER"
    assert "version" not in msg
    assert "updated_at" not in msg

    listed = validate_success(api.list_messages(bk["id"], make_client_headers(cl)), 200)
    assert any(m["id"] == msg["id"] and m.get("created_at") for m in listed)


def test_offer_same_day_date_mismatch_rejected(api):
    """PRD §3.2: "if the booking's dispatch_mode is SAME_DAY, the calendar date of
    scheduled_start (in UTC) must equal the current clock's UTC date, and a mismatch is rejected
    with ERR_SAME_DAY_DATE_MISMATCH".

    Design: Corner/validations/offer_same_day_date_mismatch_returns_temporal_error
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "SameDay Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    bk = create_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                        dispatch_mode="SAME_DAY", estimated_hours=1.0)
    res = api.offer_booking(bk["id"], make_client_headers(cl))
    validate_error(res, "ERR_SAME_DAY_DATE_MISMATCH")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "DRAFT"


def test_offer_start_in_past_rejected(api):
    """PRD §3.2: "the scheduled_start must be strictly later than the current clock instant, a
    past start being rejected with ERR_START_IN_PAST."

    Design: Corner/validations/offer_start_in_past_returns_temporal_error
    """
    ctx = setup_catalog(
        clock="2026-06-25T12:00:00Z",
        category_overrides={"name": "Past Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    bk = create_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                        dispatch_mode="SCHEDULED", estimated_hours=1.0)
    res = api.offer_booking(bk["id"], make_client_headers(cl))
    validate_error(res, "ERR_START_IN_PAST")


def test_recurring_series_generates_weekly_occurrences(api):
    """PRD §3.6: "On creation the series opens ACTIVE and immediately generates exactly
    occurrence_count bookings: for each index from zero upward in ascending order, an occurrence
    is created whose scheduled_start is the first_start advanced by that index times the
    day-step, carrying the series's category, tasker, and estimated_hours, with its series_id set
    to the owning series, a dispatch_mode of SCHEDULED, and published directly into OFFERED status
    with its window and quote computed exactly as a one-off offer would be."
    PRD §3.6: "WEEKLY or BIWEEKLY, which spaces occurrences 7 or 14 days apart respectively."

    Design: Corner/calculations/recurring_series_generates_weekly_occurrences
    """
    scn = setup_series(clock="2026-06-25T08:00:00Z", occurrence_count=3, frequency="WEEKLY",
                       first_start="2026-07-01T10:00:00Z")
    series = scn["series"]
    assert series["generated_count"] == 3

    bookings = validate_success(
        api.list_bookings(DISP, params={"series_id": series["id"]}), 200)
    assert len(bookings) == 3
    assert all(b["status"] == "OFFERED" for b in bookings)
    date_prefixes = sorted(b["scheduled_start"][:10] for b in bookings)
    assert date_prefixes == ["2026-07-01", "2026-07-08", "2026-07-15"]


def test_list_bookings_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to 10 when
    omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response carries limit, offset, total_count, and has_more inside the
    meta object of the envelope."

    Design: Corner/endpoints/list_bookings_pagination_envelope
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Page Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    for hour in ("10", "12", "14"):
        create_booking(cl, ctx["category"]["id"], f"2026-06-26T{hour}:00:00Z",
                       estimated_hours=1.0)

    data, meta = validate_paginated(
        api.list_bookings(DISP, params={"client_id": cl, "limit": 2, "offset": 0}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_rebook_completed_booking_creates_new_draft(api):
    """PRD §3.7: "a satisfied client may re-book a completed job: this creates a fresh DRAFT
    booking copying the original booking's client and category, accepting a new scheduled_start,
    dispatch_mode, optional estimated_hours, and optional tip_cents, and leaving the new
    booking's tasker_id empty so it is claimed afresh."

    Design: Corner/endpoints/rebook_completed_booking_creates_new_draft
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Rebook Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Rebook Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl = ctx["client"]["id"]
    bk = create_completed_booking(cl, ctx["category"]["id"], ctx["tasker"]["id"],
                                  "2026-06-25T10:00:00Z", estimated_hours=1.0)

    new_bk = validate_success(api.rebook(
        bk["id"], create_rebook_payload("2026-06-27T10:00:00Z"), make_client_headers(cl)), 201)
    assert new_bk["status"] == "DRAFT"
    assert new_bk["client_id"] == cl
    assert new_bk["category_id"] == ctx["category"]["id"]


def test_series_end_cascade_cancels_future_occurrences(api):
    """PRD §3.6: "ending it cascades a cancellation over every future not-yet-started
    occurrence — each child booking still in DRAFT or OFFERED is moved to CANCELLED with the
    booking's cancelled_by set to SYSTEM and no fee charged. A SYSTEM cancellation produces no
    cancellation record."

    Design: Corner/endpoints/series_end_cascade_cancels_future_occurrences
    """
    scn = setup_series(clock="2026-06-25T08:00:00Z", occurrence_count=2, frequency="WEEKLY",
                       first_start="2026-07-01T10:00:00Z")
    series, cl = scn["series"], scn["client"]["id"]

    ended = validate_success(api.end_series(series["id"], make_client_headers(cl)), 200)
    assert ended["status"] == "ENDED"

    bookings = validate_success(
        api.list_bookings(DISP, params={"series_id": series["id"]}), 200)
    assert len(bookings) == 2
    for b in bookings:
        assert b["status"] == "CANCELLED"
        assert b["cancelled_by"] == "SYSTEM"
        cancellations = validate_success(api.get_cancellation(b["id"], DISP), 200)
        assert cancellations == []


def test_client_cannot_claim_booking_forbidden_role(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not permitted
    to perform, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/client_cannot_claim_booking_forbidden_role
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Rbac Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Rbac Tasker", "hourly_rate_cents": 4000},
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=1.0)
    ver = get_success_data(api.get_tasker(tk, DISP))["version"]
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), make_client_headers(cl))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_tasker_cannot_complete_other_taskers_booking(api):
    """PRD §2.1: "When an entity-backed caller targets a resource they do not own, the request
    is rejected with ERR_NOT_RESOURCE_OWNER."
    PRD §3.3: "Completing the work advances it from IN_PROGRESS to COMPLETED; completion is the
    tasker's to perform".

    Design: Corner/rbac/tasker_cannot_complete_other_taskers_booking_not_owner
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Owner Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Owner A", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tka = ctx["client"]["id"], ctx["tasker"]["id"]
    tkb = get_success_data(api.create_tasker({"full_name": "Owner B", "hourly_rate_cents": 4000}, DISP))
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tka, "2026-06-25T10:00:00Z",
                                    estimated_hours=1.0)
    res = api.complete_booking(bk["id"], {"actual_hours": 1.0}, make_tasker_headers(tkb["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "IN_PROGRESS"


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    res = api.list_taskers(headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT")


def test_clock_default_is_2026_01_01_before_any_set(api):
    """PRD §2.4: "On server startup the clock reads exactly 2026-01-01T00:00:00Z, and before any
    clock-setting call it stays at precisely that default and never falls back to the host's real
    time."

    Design: Corner/cross_cutting_complexity_layers/clock_default_is_2026_01_01_before_any_set
    """
    # No /_clock/set_current_utc call: clock is at its 2026-01-01 default.
    cat = get_success_data(api.create_category(
        create_category_payload(name="Default Clock Cat"), DISP))
    cl = get_success_data(api.create_client({"full_name": "DefClock Client"}, DISP))
    bk = get_success_data(api.create_booking(
        create_booking_payload(cl["id"], cat["id"], "2026-01-02T10:00:00Z",
                               estimated_hours=1.0), make_client_headers(cl["id"])))
    offered = validate_success(api.offer_booking(bk["id"], make_client_headers(cl["id"])), 200)
    assert offered["status"] == "OFFERED"
