"""Acceptance: the accept cascade, ordered accept-time validations, half-open
adjacency vs overlap, traveler double-booking, and the OCC stale-version guard.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_admin_headers,
    set_clock, register_member, subscribe_and_activate, verify_identity,
    create_active_listing, add_window, open_points_request, accept_request,
    refetch_listing_version, get_member, build_points_scenario,
    accept_payload, make_member_headers,
    find_ledger_entry,
)

ADMIN = make_admin_headers()


def _listing_with_two_guests(win_specs, g2_verified=True):
    """Verified host + ACTIVE listing (version 2) with the given windows, plus two
    funded PLUS guests (g1 verified; g2 verified per flag). Returns a dict of ids."""
    set_clock("2026-07-01T00:00:00Z")
    g1 = register_member(full_name="Guest One", home_city="Boston")
    g2 = register_member(full_name="Guest Two", home_city="Miami")
    host = register_member(full_name="Host", home_city="Denver")
    subscribe_and_activate(g1["id"], "PLUS")
    subscribe_and_activate(g2["id"], "PLUS")
    verify_identity(g1["id"])
    if g2_verified:
        verify_identity(g2["id"])
    verify_identity(host["id"])
    listing = create_active_listing(host["id"], points_per_night=100)   # version 2
    windows = [add_window(listing["id"], host["id"], s, e) for (s, e) in win_specs]
    return {"g1": g1, "g2": g2, "host": host, "listing": listing, "windows": windows}


# ── Difficulty 4a: accept cascades agreement -> ledger -> balances ───────────
def test_accept_creates_agreement_and_books_window(api):
    """PRD §3.5: "A new `ExchangeAgreement` is created in `PENDING_CONFIRMATION`".
    PRD §3.5: "The chosen window flips `OPEN → BOOKED`, moving the listing's night
    totals as described in §3.2."

    Design: Difficulty/transitive_cascade/accept_cascades_agreement_ledger_balances
    """
    sc = build_points_scenario("pending", points_per_night=100, guest_tier="PLUS", host_tier="PLUS")
    agreement = sc["agreement"]
    assert agreement["status"] == "PENDING_CONFIRMATION"
    window = validate_success(api.get_availability_window(sc["window"]["id"], ADMIN), 200)
    assert window["status"] == "BOOKED"


def test_accept_posts_debit_credit_and_recomputes_balances(api):
    """PRD §3.5: "For a points exchange, the `HELD` hold is voided and replaced by
    realized postings: an `EXCHANGE_DEBIT` of the negative points cost against the
    guest and an `EXCHANGE_CREDIT` of the equal positive amount to the host, after
    which both members' settled and available balances are recomputed."

    Design: Difficulty/transitive_cascade/accept_cascades_agreement_ledger_balances
    """
    sc = build_points_scenario("pending", points_per_night=100, guest_tier="PLUS", host_tier="PLUS")
    guest, host, agreement = sc["guest"], sc["host"], sc["agreement"]
    gm = get_member(guest["id"])
    hm = get_member(host["id"])
    assert gm["settled_points_balance"] == 730
    assert gm["available_points_balance"] == 730
    assert hm["settled_points_balance"] == 1270
    entries, _ = validate_paginated(api.list_agreement_ledger_entries(agreement["id"], ADMIN))
    debit = find_ledger_entry(entries, "EXCHANGE_DEBIT", amount=-270, status="POSTED")
    credit = find_ledger_entry(entries, "EXCHANGE_CREDIT", amount=270, status="POSTED")
    assert debit is not None, "expected a POSTED EXCHANGE_DEBIT of -270"
    assert credit is not None, "expected a POSTED EXCHANGE_CREDIT of +270"


# ── Difficulty 5b: verification (safety) precedes availability (temporal) ─────
def test_accept_verification_beats_availability_conflict(api):
    """PRD §3.5: "Both parties must be trustworthy in identity: the guest's and the
    host's `verification_status` must each be `VERIFIED`, otherwise the acceptance is
    refused with `ERR_MEMBER_NOT_VERIFIED`. The chosen availability window must belong
    to the target listing and be `OPEN`, and no `BOOKED` window on that listing may
    overlap the requested half-open span (windows that merely abut are fine); a
    violation is `ERR_AVAILABILITY_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_verification_beats_temporal_conflict
    """
    env = _listing_with_two_guests([("2026-07-10", "2026-07-12")], g2_verified=False)
    w = env["windows"][0]
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w["id"], env["listing"]["version"])
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    fresh = refetch_listing_version(env["listing"]["id"], env["host"]["id"])
    res = api.accept_exchange_request(
        req2["id"], accept_payload(w["id"], fresh), make_member_headers(env["host"]["id"]))
    validate_error(res, "ERR_MEMBER_NOT_VERIFIED")


def test_accept_availability_conflict_surfaces_when_guest_verified(api):
    """PRD §3.5: "The chosen availability window must belong to the target listing
    and be `OPEN`, and no `BOOKED` window on that listing may overlap the requested
    half-open span (windows that merely abut are fine); a violation is
    `ERR_AVAILABILITY_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_verification_beats_temporal_conflict
    """
    env = _listing_with_two_guests([("2026-07-10", "2026-07-12")], g2_verified=True)
    w = env["windows"][0]
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w["id"], env["listing"]["version"])
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    fresh = refetch_listing_version(env["listing"]["id"], env["host"]["id"])
    res = api.accept_exchange_request(
        req2["id"], accept_payload(w["id"], fresh), make_member_headers(env["host"]["id"]))
    validate_error(res, "ERR_AVAILABILITY_CONFLICT")


# ── Difficulty 8a: half-open adjacency is allowed ────────────────────────────
def test_adjacent_window_accept_succeeds(api):
    """PRD §3.5: "no `BOOKED` window on that listing may overlap the requested
    half-open span (windows that merely abut are fine)".

    Design: Difficulty/resource_temporal_overlap/listing_half_open_adjacency_allowed
    """
    env = _listing_with_two_guests(
        [("2026-07-10", "2026-07-12"), ("2026-07-12", "2026-07-14")], g2_verified=True)
    w1, w2 = env["windows"]
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w1["id"], env["listing"]["version"])
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-12", "2026-07-14")
    fresh = refetch_listing_version(env["listing"]["id"], env["host"]["id"])
    res = api.accept_exchange_request(
        req2["id"], accept_payload(w2["id"], fresh), make_member_headers(env["host"]["id"]))
    agreement = validate_success(res, 201)
    assert agreement["status"] == "PENDING_CONFIRMATION"


def test_adjacent_window_becomes_booked(api):
    """PRD §3.5: "The chosen window flips `OPEN → BOOKED`".

    Design: Difficulty/resource_temporal_overlap/listing_half_open_adjacency_allowed
    """
    env = _listing_with_two_guests(
        [("2026-07-10", "2026-07-12"), ("2026-07-12", "2026-07-14")], g2_verified=True)
    w1, w2 = env["windows"]
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w1["id"], env["listing"]["version"])
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-12", "2026-07-14")
    fresh = refetch_listing_version(env["listing"]["id"], env["host"]["id"])
    accept_request(req2["id"], env["host"]["id"], w2["id"], fresh)
    window = validate_success(api.get_availability_window(w2["id"], ADMIN), 200)
    assert window["status"] == "BOOKED"


# ── Corner: overlapping range is rejected ────────────────────────────────────
def test_overlapping_window_accept_rejected(api):
    """PRD §3.5: "no `BOOKED` window on that listing may overlap the requested
    half-open span (windows that merely abut are fine); a violation is
    `ERR_AVAILABILITY_CONFLICT`."

    Design: Corner/validations/listing_overlap_conflict_rejected
    """
    env = _listing_with_two_guests(
        [("2026-07-10", "2026-07-12"), ("2026-07-11", "2026-07-13")], g2_verified=True)
    w1, w3 = env["windows"]
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w1["id"], env["listing"]["version"])
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-11", "2026-07-13")
    fresh = refetch_listing_version(env["listing"]["id"], env["host"]["id"])
    res = api.accept_exchange_request(
        req2["id"], accept_payload(w3["id"], fresh), make_member_headers(env["host"]["id"]))
    validate_error(res, "ERR_AVAILABILITY_CONFLICT")


# ── Difficulty 8b: traveler buffer (closed intervals + 1-day gap) ────────────
def _two_hosts_one_guest():
    set_clock("2026-07-01T00:00:00Z")
    g = register_member(full_name="Guest", home_city="Boston")
    ha = register_member(full_name="Host A", home_city="Denver")
    hb = register_member(full_name="Host B", home_city="Austin")
    subscribe_and_activate(g["id"], "PLUS")
    verify_identity(g["id"])
    verify_identity(ha["id"])
    verify_identity(hb["id"])
    la = create_active_listing(ha["id"], points_per_night=100)
    wa = add_window(la["id"], ha["id"], "2026-07-10", "2026-07-12")
    return g, ha, hb, la, wa


def test_traveler_double_booking_within_buffer_rejected(api):
    """PRD §3.5: "they may have no other non-terminal agreement whose closed stay
    from `check_in` to `check_out` falls within `TRAVEL_BUFFER_DAYS` (a fixed travel
    buffer of exactly 1 day) of this stay — two of the same guest's closed stays must
    be separated by strictly more than one day, so stays that overlap, abut (share an
    endpoint date), or sit within a single day of each other are too close and are
    rejected with `ERR_TRAVELER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/traveler_buffer_double_booking_rejected
    """
    g, ha, hb, la, wa = _two_hosts_one_guest()
    reqA = open_points_request(g["id"], la["id"], "2026-07-10", "2026-07-12")
    accept_request(reqA["id"], ha["id"], wa["id"], la["version"])
    lb = create_active_listing(hb["id"], points_per_night=100)
    wb = add_window(lb["id"], hb["id"], "2026-07-12", "2026-07-14")   # abuts first stay's check_out
    reqB = open_points_request(g["id"], lb["id"], "2026-07-12", "2026-07-14")
    res = api.accept_exchange_request(
        reqB["id"], accept_payload(wb["id"], lb["version"]), make_member_headers(hb["id"]))
    validate_error(res, "ERR_TRAVELER_DOUBLE_BOOKED")


def test_traveler_gap_above_buffer_accepted(api):
    """PRD §3.5: "two of the same guest's closed stays must be separated by strictly
    more than one day".

    Design: Difficulty/resource_temporal_overlap/traveler_buffer_double_booking_rejected
    """
    g, ha, hb, la, wa = _two_hosts_one_guest()
    reqA = open_points_request(g["id"], la["id"], "2026-07-10", "2026-07-12")
    accept_request(reqA["id"], ha["id"], wa["id"], la["version"])
    lb = create_active_listing(hb["id"], points_per_night=100)
    wb = add_window(lb["id"], hb["id"], "2026-07-14", "2026-07-16")   # 2-day gap from 07-12
    reqB = open_points_request(g["id"], lb["id"], "2026-07-14", "2026-07-16")
    res = api.accept_exchange_request(
        reqB["id"], accept_payload(wb["id"], lb["version"]), make_member_headers(hb["id"]))
    agreement = validate_success(res, 201)
    assert agreement["status"] == "PENDING_CONFIRMATION"


# ── Corner: OCC stale listing version ────────────────────────────────────────
def test_accept_with_stale_listing_version_returns_412(api):
    """PRD §2.5: "If that value does not equal the listing's current `version`, the
    acceptance is rejected with `ERR_STALE_LISTING_VERSION` at HTTP status 412."
    PRD §2.5: "a later acceptance still carrying the pre-advance version is operating
    on an outdated picture of the listing's availability and terms, and is refused
    even if it targets a different, still-open window."

    Design: Corner/cross_cutting_complexity_layers/accept_with_stale_listing_version_returns_412
    """
    env = _listing_with_two_guests(
        [("2026-07-10", "2026-07-12"), ("2026-07-20", "2026-07-22")], g2_verified=True)
    w1, w2 = env["windows"]
    stale_version = env["listing"]["version"]   # version 2, captured at activate
    req1 = open_points_request(env["g1"]["id"], env["listing"]["id"], "2026-07-10", "2026-07-12")
    accept_request(req1["id"], env["host"]["id"], w1["id"], stale_version)   # bumps version to 3
    req2 = open_points_request(env["g2"]["id"], env["listing"]["id"], "2026-07-20", "2026-07-22")
    res = api.accept_exchange_request(
        req2["id"], accept_payload(w2["id"], stale_version), make_member_headers(env["host"]["id"]))
    validate_error(res, "ERR_STALE_LISTING_VERSION")
