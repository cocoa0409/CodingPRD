"""Tasting-bar scheduling: station buffer window (exact-gap boundary + conflicts), member
cross-station overlap, past-start guard, and station-not-found."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_same_instant,
    create_member, create_station, book_session, set_clock, make_customer_headers,
)


def _session_payload(station_id, start_at, end_at):
    return {"station_id": station_id, "start_at": start_at, "end_at": end_at}


# ── Difficulty: boundary_precision_check / tasting_station_buffer_exact_gap_accepted ──

def test_session_exactly_15_minutes_after_prior_is_accepted(api):
    """PRD §3.9: "the buffer window is 15 minutes, and the collision fires when the time gap
    between the new session and an existing session on that station is strictly less than 15
    minutes, so a session that starts exactly 15 minutes after a prior session ends (a gap of
    exactly 15 minutes) is accepted."

    Design: Difficulty/boundary_precision_check/tasting_station_buffer_exact_gap_accepted
    """
    member = create_member(api)
    station = create_station(api)
    book_session(api, member, station["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z",
                 party_size=2)
    session = book_session(api, member, station["id"], "2026-08-01T11:15:00Z",
                           "2026-08-01T12:15:00Z", party_size=2)
    assert session["status"] == "BOOKED", session["status"]
    assert_same_instant(session["start_at"], "2026-08-01T11:15:00Z")


def test_session_14_minute_gap_is_rejected(api):
    """PRD §3.9: "the buffer window is 15 minutes, and the collision fires when the time gap
    between the new session and an existing session on that station is strictly less than 15
    minutes, so a session that starts exactly 15 minutes after a prior session ends (a gap of
    exactly 15 minutes) is accepted."

    Design: Difficulty/boundary_precision_check/tasting_station_buffer_exact_gap_accepted
    """
    member = create_member(api)
    station = create_station(api)
    book_session(api, member, station["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    resp = api.create_tasting_session(
        _session_payload(station["id"], "2026-08-01T11:14:00Z", "2026-08-01T12:14:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATION_UNAVAILABLE.value)


# ── Difficulty: resource_temporal_overlap / station_buffer_window_conflict ──

def test_station_buffer_conflict_10_minutes_after(api):
    """PRD §3.9: "The new session must not fall within the station's buffer window of any other
    non-cancelled session on the same station, or it is rejected with `ERR_STATION_UNAVAILABLE`;
    the buffer window is 15 minutes, and the collision fires when the time gap between the new
    session and an existing session on that station is strictly less than 15 minutes".

    Design: Difficulty/resource_temporal_overlap/station_buffer_window_conflict
    """
    member = create_member(api)
    station = create_station(api)
    book_session(api, member, station["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    resp = api.create_tasting_session(
        _session_payload(station["id"], "2026-08-01T11:10:00Z", "2026-08-01T12:10:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATION_UNAVAILABLE.value)


def test_station_buffer_conflict_10_minutes_before(api):
    """PRD §3.9: "The new session must not fall within the station's buffer window of any other
    non-cancelled session on the same station, or it is rejected with `ERR_STATION_UNAVAILABLE`;
    the buffer window is 15 minutes, and the collision fires when the time gap between the new
    session and an existing session on that station is strictly less than 15 minutes".

    Design: Difficulty/resource_temporal_overlap/station_buffer_window_conflict
    """
    member = create_member(api)
    station = create_station(api)
    book_session(api, member, station["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    resp = api.create_tasting_session(
        _session_payload(station["id"], "2026-08-01T09:00:00Z", "2026-08-01T09:50:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATION_UNAVAILABLE.value)


# ── Difficulty: resource_temporal_overlap / member_cross_station_overlap_conflict ──

def test_member_overlapping_sessions_on_different_stations_rejected(api):
    """PRD §3.9: "Its half-open interval from its start up to but not including its end must not
    overlap any other non-cancelled session held by the same member on any station, or it is
    rejected with `ERR_MEMBER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/member_cross_station_overlap_conflict
    """
    member = create_member(api)
    st1 = create_station(api, name="Bar A")
    st2 = create_station(api, name="Bar B")
    book_session(api, member, st1["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    resp = api.create_tasting_session(
        _session_payload(st2["id"], "2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)


def test_member_contained_session_on_other_station_rejected(api):
    """PRD §3.9: "Its half-open interval from its start up to but not including its end must not
    overlap any other non-cancelled session held by the same member on any station, or it is
    rejected with `ERR_MEMBER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/member_cross_station_overlap_conflict
    """
    member = create_member(api)
    st1 = create_station(api, name="Bar A")
    st2 = create_station(api, name="Bar B")
    book_session(api, member, st1["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    resp = api.create_tasting_session(
        _session_payload(st2["id"], "2026-08-01T10:15:00Z", "2026-08-01T10:45:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)


# ── Corner: validations / book_session_in_past_returns_error ──

def test_book_session_starting_in_past_rejected(api):
    """PRD §3.9: "Its start must be strictly later than the logical now, or it is rejected with
    `ERR_SESSION_IN_PAST`."

    Design: Corner/validations/book_session_in_past_returns_error
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    member = create_member(api)
    station = create_station(api)
    resp = api.create_tasting_session(
        _session_payload(station["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_IN_PAST.value)


# ── Corner: errors / station_not_found_on_booking ──

def test_book_session_unknown_station_returns_not_found(api):
    """PRD §2.8: "Body-referenced foreign keys — a `product_id`, a `wholesale_account_id`, a
    `station_id`, or a `component_product_id` — are validated for existence in the same way when
    an order, subscription, fusti, component, or tasting session is created."

    Design: Corner/errors/station_not_found_on_booking
    """
    member = create_member(api)
    resp = api.create_tasting_session(
        _session_payload("00000000-0000-0000-0000-000000000000",
                         "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_FOUND.value)
