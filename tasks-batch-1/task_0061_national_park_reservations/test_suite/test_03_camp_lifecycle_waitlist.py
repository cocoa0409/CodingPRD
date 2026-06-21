"""Campground reservation lifecycle, half-open overlap semantics, the waitlist
cascade (cancel -> offer -> claim), waitlist position assignment, and offer
expiry advancing without renumbering.

Difficulty queue: non_linear_state_machine (camp branch), transitive_cascade
(waitlist), resource_temporal_overlap (campsite adjacency),
cross_entity_state_dependency (ranger check-in scope).
Corner queue: calculations (waitlist_position), state_machines (waitlist
cascade), endpoints/errors (offer expired).
"""
from test_helpers import assert_ok, assert_error
from test_helpers import fixtures as fx


# --- branching_camp_reservation_confirm_vs_cancel_paths ------------------
def test_camp_confirm_clears_hold(client):
    """PRD 3.5: "On success it moves `held -> confirmed`, captures the payment,
    and clears `hold_expires_at`."

    Design: Difficulty/non_linear_state_machine/branching_camp_reservation_confirm_vs_cancel_paths
    """
    park, pa = fx.base_world(client, "ACAD", park_overrides={"utc_offset_minutes": -300})
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T5")
    resv = fx.create_camp_reservation(client, site["id"], v["id"],
                                      "2026-06-20", "2026-06-22", party_size=2)
    confirmed = fx.confirm_camp_reservation(client, resv["id"], v["id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["hold_expires_at"] is None


def test_camp_cancel_held_voids_payment(client):
    """PRD 3.5: "A `held` reservation that is cancelled moves `held -> cancelled`,
    voids its still-authorized payment, releases its dates".

    Design: Difficulty/non_linear_state_machine/branching_camp_reservation_confirm_vs_cancel_paths
    """
    park, pa = fx.base_world(client, "ACA2", park_overrides={"utc_offset_minutes": -300})
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T6")
    resv = fx.create_camp_reservation(client, site["id"], v["id"],
                                      "2026-06-20", "2026-06-22", party_size=2)
    cancelled = assert_ok(
        client.post(f"/v1/camp-reservations/{resv['id']}/cancel",
                    role="visitor", user_id=v["id"]), 200)
    assert cancelled["status"] == "cancelled"
    pay = assert_ok(client.get(f"/v1/payments/{resv['payment_id']}",
                               role="visitor", user_id=v["id"]))
    assert pay["status"] == "voided"


# --- overlap_campsite_halfopen_adjacent_allowed --------------------------
def test_adjacent_reservation_confirm_allowed(client):
    """PRD 3.5: "no other reservation in `confirmed` or `checked_in` may overlap
    the half-open range from `check_in` to `check_out` on the same campsite,
    otherwise `ERR_DATE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_campsite_halfopen_adjacent_allowed
    """
    park, pa = fx.base_world(client, "MORA", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T15")
    r1 = fx.create_camp_reservation(client, site["id"], v["id"],
                                    "2026-06-10", "2026-06-12", party_size=2)
    fx.confirm_camp_reservation(client, r1["id"], v["id"])
    r2 = fx.create_camp_reservation(client, site["id"], v["id"],
                                    "2026-06-12", "2026-06-14", party_size=2)
    confirmed = fx.confirm_camp_reservation(client, r2["id"], v["id"])
    assert confirmed["status"] == "confirmed"  # adjacent, check_out exclusive


def test_overlapping_reservation_confirm_conflict(client):
    """PRD 3.5: "no other reservation in `confirmed` or `checked_in` may overlap
    the half-open range from `check_in` to `check_out` on the same campsite,
    otherwise `ERR_DATE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_campsite_halfopen_adjacent_allowed
    """
    park, pa = fx.base_world(client, "MOR2", park_overrides={"utc_offset_minutes": -480})
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T16")
    r1 = fx.create_camp_reservation(client, site["id"], a["id"],
                                    "2026-06-10", "2026-06-13", party_size=2)
    fx.confirm_camp_reservation(client, r1["id"], a["id"])
    # b's [06-12, 06-14) overlaps a's confirmed [06-10, 06-13).
    r2 = fx.create_camp_reservation(client, site["id"], b["id"],
                                    "2026-06-12", "2026-06-14", party_size=2)
    resp = client.post(f"/v1/camp-reservations/{r2['id']}/confirm",
                       role="visitor", user_id=b["id"])
    assert_error(resp, 409, "ERR_DATE_CONFLICT")


# --- transitive cascade: cancel -> offer -> claim ------------------------
def test_waitlist_cascade_cancel_offer_claim(client):
    """PRD 3.7: "Whenever a `CampReservation` on the same campsite and exact date
    range is cancelled or expires and releases its dates, the system makes an
    offer to the lowest-position entry still in `waiting` ... moving it
    `waiting -> offered`".
    PRD 3.7: "Claiming moves the entry `offered -> claimed`, creates a
    `confirmed` `CampReservation` for that campsite, range, and party size with
    its `origin_waitlist_id` set to this entry".

    Design: Difficulty/transitive_cascade/cascade_camp_cancel_offer_claim_creates_reservation
    """
    park, pa = fx.base_world(client, "ROMO", park_overrides={"utc_offset_minutes": -420})
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T7")
    r = fx.create_camp_reservation(client, site["id"], a["id"],
                                   "2026-06-25", "2026-06-27", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], a["id"])
    sv = fx.get_campsite_version(client, site["id"], b["id"])
    w = fx.join_waitlist(client, site["id"], b["id"], "2026-06-25", "2026-06-27", 2, sv)
    # Cancel A's confirmed reservation -> cascades offer to W.
    assert_ok(client.post(f"/v1/camp-reservations/{r['id']}/cancel",
                          role="visitor", user_id=a["id"]), 200)
    w_after = assert_ok(client.get(f"/v1/waitlist-entries/{w['id']}",
                                   role="visitor", user_id=b["id"]))
    assert w_after["status"] == "offered"
    claimed_resv = assert_ok(client.post(f"/v1/waitlist-entries/{w['id']}/claim",
                                         role="visitor", user_id=b["id"]), 200)
    assert claimed_resv["status"] == "confirmed"
    assert claimed_resv["origin_waitlist_id"] == w["id"]


def test_waitlist_claimed_entry_terminal(client):
    """PRD 3.7: "A visitor claims an active offer: the entry must be `offered`
    ... Claiming moves the entry `offered -> claimed`".

    Design: Difficulty/transitive_cascade/cascade_camp_cancel_offer_claim_creates_reservation
    """
    park, pa = fx.base_world(client, "ROM2", park_overrides={"utc_offset_minutes": -420})
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T8")
    r = fx.create_camp_reservation(client, site["id"], a["id"],
                                   "2026-06-25", "2026-06-27", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], a["id"])
    sv = fx.get_campsite_version(client, site["id"], b["id"])
    w = fx.join_waitlist(client, site["id"], b["id"], "2026-06-25", "2026-06-27", 2, sv)
    assert_ok(client.post(f"/v1/camp-reservations/{r['id']}/cancel",
                          role="visitor", user_id=a["id"]), 200)
    assert_ok(client.post(f"/v1/waitlist-entries/{w['id']}/claim",
                          role="visitor", user_id=b["id"]), 200)
    w_after = assert_ok(client.get(f"/v1/waitlist-entries/{w['id']}",
                                   role="visitor", user_id=b["id"]))
    assert w_after["status"] == "claimed"


# --- cross_ranger_checkin_requires_reservation_confirmed_and_home_park ----
def test_ranger_checkin_wrong_park_forbidden(client):
    """PRD 3.5: "A `ranger` checks the visitor in: the reservation must be
    `confirmed`, the park-local date of `now_utc` must equal `check_in`, and the
    ranger's `home_park_id` must equal the campsite's `park_id` (otherwise
    `ERR_FORBIDDEN`)".

    Design: Difficulty/cross_entity_state_dependency/cross_ranger_checkin_requires_reservation_confirmed_and_home_park
    """
    p1 = fx.create_park(client, "P1AA", utc_offset_minutes=0)
    p2 = fx.create_park(client, "P2BB", utc_offset_minutes=0)
    fx.set_clock(client, "2026-06-20T12:00:00Z")
    pa = fx.create_park_admin(client, p1["id"])
    rg2 = fx.create_ranger(client, p2["id"])
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, p1["id"], pa["id"], site_number="T13")
    r = fx.create_camp_reservation(client, site["id"], v["id"],
                                   "2026-06-20", "2026-06-22", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], v["id"])
    resp = client.post(f"/v1/camp-reservations/{r['id']}/check-in",
                       role="ranger", user_id=rg2["id"])
    assert_error(resp, 403, "ERR_FORBIDDEN")
    r_after = assert_ok(client.get(f"/v1/camp-reservations/{r['id']}",
                                   role="visitor", user_id=v["id"]))
    assert r_after["status"] == "confirmed"


def test_ranger_checkin_home_park_succeeds(client):
    """PRD 3.5: "A `ranger` checks the visitor in: the reservation must be
    `confirmed`, the park-local date of `now_utc` must equal `check_in`, and the
    ranger's `home_park_id` must equal the campsite's `park_id` ... on success it
    moves `confirmed -> checked_in`."

    Design: Difficulty/cross_entity_state_dependency/cross_ranger_checkin_requires_reservation_confirmed_and_home_park
    """
    park, pa = fx.base_world(client, "P1CC", now_utc="2026-06-20T12:00:00Z")
    rg = fx.create_ranger(client, park["id"])
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="T14")
    r = fx.create_camp_reservation(client, site["id"], v["id"],
                                   "2026-06-20", "2026-06-22", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], v["id"])
    checked_in = assert_ok(client.post(f"/v1/camp-reservations/{r['id']}/check-in",
                                       role="ranger", user_id=rg["id"]), 200)
    assert checked_in["status"] == "checked_in"


# --- Corner: waitlist_position_assignment_increments ---------------------
def test_waitlist_position_increments(client):
    """PRD 3.7: "It is computed as one plus the count of existing waitlist
    entries in `waiting` or `offered` status for the very same combination of
    campsite, check-in, and check-out."

    Design: Corner/calculations/waitlist_position_assignment_increments
    """
    park, pa = fx.base_world(client, "WP01")
    h = fx.create_visitor(client)
    x1 = fx.create_visitor(client)
    x2 = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TN")
    r = fx.create_camp_reservation(client, site["id"], h["id"],
                                   "2026-06-25", "2026-06-27", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], h["id"])
    sv1 = fx.get_campsite_version(client, site["id"], x1["id"])
    w1 = fx.join_waitlist(client, site["id"], x1["id"], "2026-06-25", "2026-06-27", 2, sv1)
    sv2 = fx.get_campsite_version(client, site["id"], x2["id"])
    w2 = fx.join_waitlist(client, site["id"], x2["id"], "2026-06-25", "2026-06-27", 2, sv2)
    assert w1["position"] == 1
    assert w2["position"] == 2


# --- Corner: waitlist_offer_cascade_skip_position_no_renumber ------------
def test_offer_expiry_advances_without_renumber(client):
    """PRD 3.7: "The housekeeping sweep expires an `offered` entry whose
    `offer_expires_at` has passed, moving it `offered -> expired` and advancing
    the offer to the next lowest-position `waiting` entry for the same key ...
    Positions are never renumbered when an entry leaves".

    Design: Corner/state_machines/waitlist_offer_cascade_skip_position_no_renumber
    """
    park, pa = fx.base_world(client, "SM04")
    h = fx.create_visitor(client)
    w1u = fx.create_visitor(client)
    w2u = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TJ")
    r = fx.create_camp_reservation(client, site["id"], h["id"],
                                   "2026-06-25", "2026-06-27", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], h["id"])
    sv1 = fx.get_campsite_version(client, site["id"], w1u["id"])
    wl1 = fx.join_waitlist(client, site["id"], w1u["id"], "2026-06-25", "2026-06-27", 2, sv1)
    sv2 = fx.get_campsite_version(client, site["id"], w2u["id"])
    wl2 = fx.join_waitlist(client, site["id"], w2u["id"], "2026-06-25", "2026-06-27", 2, sv2)
    # Cancel reservation -> offers wl1 (offer_expires_at = now+24h).
    assert_ok(client.post(f"/v1/camp-reservations/{r['id']}/cancel",
                          role="visitor", user_id=h["id"]), 200)
    # Advance past wl1's offer window and run ops.
    fx.set_clock(client, "2026-06-02T01:00:00Z")
    fx.run_ops(client)
    wl1_after = assert_ok(client.get(f"/v1/waitlist-entries/{wl1['id']}",
                                     role="visitor", user_id=w1u["id"]))
    wl2_after = assert_ok(client.get(f"/v1/waitlist-entries/{wl2['id']}",
                                     role="visitor", user_id=w2u["id"]))
    assert wl1_after["status"] == "expired"
    assert wl2_after["status"] == "offered"
    assert wl2_after["position"] == 2  # not renumbered


# --- Corner: error_offer_expired_claim_after_deadline --------------------
def test_claim_after_offer_expiry_rejected(client):
    """PRD 3.7: "A visitor claims an active offer: the entry must be `offered`
    and `now_utc` must be at or before `offer_expires_at`, otherwise
    `ERR_OFFER_EXPIRED`."

    Design: Corner/errors/error_offer_expired_claim_after_deadline
    """
    park, pa = fx.base_world(client, "ER01")
    h = fx.create_visitor(client)
    w = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TZ")
    r = fx.create_camp_reservation(client, site["id"], h["id"],
                                   "2026-06-25", "2026-06-27", party_size=2)
    fx.confirm_camp_reservation(client, r["id"], h["id"])
    sv = fx.get_campsite_version(client, site["id"], w["id"])
    wl = fx.join_waitlist(client, site["id"], w["id"], "2026-06-25", "2026-06-27", 2, sv)
    # Cancel at now (offer made, expires now+24h), then advance >24h.
    assert_ok(client.post(f"/v1/camp-reservations/{r['id']}/cancel",
                          role="visitor", user_id=h["id"]), 200)
    fx.set_clock(client, "2026-06-02T01:00:00Z")
    resp = client.post(f"/v1/waitlist-entries/{wl['id']}/claim",
                       role="visitor", user_id=w["id"])
    assert_error(resp, 409, "ERR_OFFER_EXPIRED")
