"""Quota and capacity accounting: zone aggregate party-nights, conserved
quantities on confirm+cancel and hold+cancel, trailhead exhaustion independent
of zone, and the timed-entry rolling-window boundary.

Difficulty queue: resource_temporal_overlap (zone), compensating_invariant
(zone + slot), boundary_precision_check (7-day window).
Corner queue: validations (trailhead full), endpoints (timed-entry fee
nonrefundable), consistency_model (immediate slot counts).
"""
from test_helpers import assert_ok, assert_error
from test_helpers import fixtures as fx


# --- overlap_zone_aggregate_capacity_party_nights ------------------------
def test_zone_full_on_second_confirm(client):
    """PRD 3.4: "For every itinerary element, the named zone's committed count
    for that date (`used_by_date` for that date) must be strictly less than the
    zone's `nightly_party_quota`, otherwise `ERR_ZONE_FULL`."

    Design: Difficulty/resource_temporal_overlap/overlap_zone_aggregate_capacity_party_nights
    """
    park, pa = fx.base_world(client, "DEVA", park_overrides={"utc_offset_minutes": -480})
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=10)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=1)
    pa_permit = fx.create_backcountry_permit(
        client, park["id"], a["id"], th["id"], "2026-06-10", 1, 2,
        [{"zone_id": z["id"], "date": "2026-06-10"}])
    fx.confirm_backcountry_permit(client, pa_permit["id"], a["id"])
    pb_permit = fx.create_backcountry_permit(
        client, park["id"], b["id"], th["id"], "2026-06-10", 1, 2,
        [{"zone_id": z["id"], "date": "2026-06-10"}])
    resp = client.post(f"/v1/backcountry-permits/{pb_permit['id']}/confirm",
                       role="visitor", user_id=b["id"])
    assert_error(resp, 409, "ERR_ZONE_FULL")
    z_after = assert_ok(client.get(f"/v1/wilderness-zones/{z['id']}",
                                   role="visitor", user_id=b["id"]))
    assert z_after["used_by_date"]["2026-06-10"] == 1


def test_zone_quota_counts_parties_not_persons(client):
    """PRD 2.7: "Quota for backcountry counts **parties, not persons**: each
    itinerary element consumes exactly one party-night regardless of
    `party_size`".

    Design: Difficulty/resource_temporal_overlap/overlap_zone_aggregate_capacity_party_nights
    """
    park, pa = fx.base_world(client, "DEV2", park_overrides={"utc_offset_minutes": -480})
    a = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=10)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=1)
    permit = fx.create_backcountry_permit(
        client, park["id"], a["id"], th["id"], "2026-06-10", 1, 5,
        [{"zone_id": z["id"], "date": "2026-06-10"}])
    fx.confirm_backcountry_permit(client, permit["id"], a["id"])
    z_after = assert_ok(client.get(f"/v1/wilderness-zones/{z['id']}",
                                   role="visitor", user_id=a["id"]))
    assert z_after["used_by_date"]["2026-06-10"] == 1  # one party, not 5 persons


# --- invariant_zone_party_nights_conserved_on_confirm_cancel -------------
def test_zone_party_nights_net_zero_on_confirm_cancel(client):
    """PRD 3.4: "A `confirmed` permit that is cancelled moves
    `confirmed -> cancelled`, releases every committed party-night (decrementing
    each zone's `used_by_date` for its date)".

    Design: Difficulty/compensating_invariant/invariant_zone_party_nights_conserved_on_confirm_cancel
    """
    park, pa = fx.base_world(client, "JOTR", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=10)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    permit = fx.create_backcountry_permit(
        client, park["id"], v["id"], th["id"], "2026-06-20", 1, 2,
        [{"zone_id": z["id"], "date": "2026-06-20"}])
    fx.confirm_backcountry_permit(client, permit["id"], v["id"])
    cancelled = assert_ok(client.post(f"/v1/backcountry-permits/{permit['id']}/cancel",
                                      role="visitor", user_id=v["id"]), 200)
    assert cancelled["status"] == "cancelled"
    z_after = assert_ok(client.get(f"/v1/wilderness-zones/{z['id']}",
                                   role="visitor", user_id=v["id"]))
    assert z_after["used_by_date"].get("2026-06-20", 0) == 0  # net zero


def test_backcountry_confirm_commits_then_cancel_releases_trailhead(client):
    """PRD 3.4: "On success the permit moves `held -> confirmed` ... the
    trailhead's `exit_used_by_date` for `entry_date` is incremented by one".
    PRD 3.4: "releases ... the trailhead exit (decrementing `exit_used_by_date`
    for `entry_date`)".

    Design: Difficulty/compensating_invariant/invariant_zone_party_nights_conserved_on_confirm_cancel
    """
    park, pa = fx.base_world(client, "JOT2", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=10)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    permit = fx.create_backcountry_permit(
        client, park["id"], v["id"], th["id"], "2026-06-20", 1, 2,
        [{"zone_id": z["id"], "date": "2026-06-20"}])
    fx.confirm_backcountry_permit(client, permit["id"], v["id"])
    th_mid = assert_ok(client.get(f"/v1/trailheads/{th['id']}",
                                  role="visitor", user_id=v["id"]))
    assert th_mid["exit_used_by_date"]["2026-06-20"] == 1
    assert_ok(client.post(f"/v1/backcountry-permits/{permit['id']}/cancel",
                          role="visitor", user_id=v["id"]), 200)
    th_after = assert_ok(client.get(f"/v1/trailheads/{th['id']}",
                                    role="visitor", user_id=v["id"]))
    assert th_after["exit_used_by_date"].get("2026-06-20", 0) == 0


# --- invariant_timed_entry_slot_capacity_conserved_on_hold_cancel --------
def test_slot_counts_net_zero_on_hold_cancel(client):
    """PRD 3.2: "Cancelling a `held` reservation moves `held -> cancelled`,
    decrements the slot's `held_count`, and voids the still-authorized payment."

    Design: Difficulty/compensating_invariant/invariant_timed_entry_slot_capacity_conserved_on_hold_cancel
    """
    park, pa = fx.base_world(client, "SHEN", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": -300,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=3,
                          release_at="2026-06-05T07:00:00Z")
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="CONS1")
    cancelled = assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/cancel",
                                      role="visitor", user_id=v["id"]), 200)
    assert cancelled["status"] == "cancelled"
    slot_after = assert_ok(client.get(f"/v1/timed-entry-slots/{slot['id']}",
                                      role="visitor", user_id=v["id"]))
    assert slot_after["held_count"] == 0
    assert slot_after["booked_count"] == 0


def test_slot_hold_increments_held_count(client):
    """PRD 3.2: "On a successful create, the reservation enters `held` ... the
    slot's `held_count` is incremented and its `version` advanced".

    Design: Difficulty/compensating_invariant/invariant_timed_entry_slot_capacity_conserved_on_hold_cancel
    """
    park, pa = fx.base_world(client, "SHE2", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": -300,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=3,
                          release_at="2026-06-05T07:00:00Z")
    fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="CONS2")
    slot_after = assert_ok(client.get(f"/v1/timed-entry-slots/{slot['id']}",
                                      role="visitor", user_id=v["id"]))
    assert slot_after["held_count"] == 1


# --- boundary_timed_entry_7day_window_inclusive --------------------------
def test_timed_entry_window_exactly_7_days_ok(client):
    """PRD 3.2: "The slot's `entry_date` must fall within a rolling seven-day
    window measured in park-local dates: the difference between the entry date
    and today's park-local date must be at least 0 and at most 7, otherwise
    `ERR_OUTSIDE_BOOKING_WINDOW`."

    Design: Difficulty/boundary_precision_check/boundary_timed_entry_7day_window_inclusive
    """
    park, pa = fx.base_world(client, "TETON", now_utc="2026-06-01T12:00:00Z",
                             park_overrides={"utc_offset_minutes": -360,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    # park-local now date = 2026-06-01; entry_date 2026-06-08 is exactly +7.
    slot = fx.create_slot(client, park["id"], pa["id"], entry_date="2026-06-08",
                          window_start_local="07:00", window_end_local="10:00",
                          capacity=5, release_at="2026-06-01T00:00:00Z",
                          entry_fee_cents=200)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="PLT7")
    assert resv["status"] == "held"
    assert resv["fee_cents"] == 200


def test_timed_entry_fee_equals_slot_fee(client):
    """PRD 3.2: "The reservation fee equals the slot's `entry_fee_cents`
    outright."

    Design: Difficulty/boundary_precision_check/boundary_timed_entry_7day_window_inclusive
    """
    park, pa = fx.base_world(client, "TET2", now_utc="2026-06-01T12:00:00Z",
                             park_overrides={"utc_offset_minutes": -360,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], entry_date="2026-06-08",
                          window_start_local="07:00", window_end_local="10:00",
                          capacity=5, release_at="2026-06-01T00:00:00Z",
                          entry_fee_cents=350)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="PLT9")
    assert resv["fee_cents"] == 350


# --- Corner: error_trailhead_full_independent_of_zone --------------------
def test_trailhead_full_independent_of_zone(client):
    """PRD 3.4: "The trailhead's committed exits for `entry_date`
    (`exit_used_by_date` for that date) must be strictly less than
    `daily_exit_quota`, otherwise `ERR_TRAILHEAD_FULL`."

    Design: Corner/validations/error_trailhead_full_independent_of_zone
    """
    park, pa = fx.base_world(client, "TF01")
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=1)
    z1 = fx.create_zone(client, park["id"], pa["id"], name="ZVa", nightly_party_quota=10)
    z2 = fx.create_zone(client, park["id"], pa["id"], name="ZVb", nightly_party_quota=10)
    pa_permit = fx.create_backcountry_permit(
        client, park["id"], a["id"], th["id"], "2026-06-10", 1, 2,
        [{"zone_id": z1["id"], "date": "2026-06-10"}])
    fx.confirm_backcountry_permit(client, pa_permit["id"], a["id"])
    pb_permit = fx.create_backcountry_permit(
        client, park["id"], b["id"], th["id"], "2026-06-10", 1, 2,
        [{"zone_id": z2["id"], "date": "2026-06-10"}])
    resp = client.post(f"/v1/backcountry-permits/{pb_permit['id']}/confirm",
                       role="visitor", user_id=b["id"])
    assert_error(resp, 409, "ERR_TRAILHEAD_FULL")


# --- Corner: timed_entry_fee_nonrefundable_on_confirmed_cancel -----------
def test_confirmed_timed_entry_cancel_no_refund(client):
    """PRD 3.2: "Cancelling a `confirmed` reservation moves `confirmed ->
    cancelled` and decrements the slot's `booked_count`, but because the entry
    fee is non-refundable the payment stays `captured` and `refunded_cents`
    remains 0."

    Design: Corner/endpoints/timed_entry_fee_nonrefundable_on_confirmed_cancel
    """
    park, pa = fx.base_world(client, "EP01", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=3,
                          release_at="2026-06-05T07:00:00Z", entry_fee_cents=200)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="NRF1")
    confirmed = assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                                      role="visitor", user_id=v["id"]), 200)
    cancelled = assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/cancel",
                                      role="visitor", user_id=v["id"]), 200)
    assert cancelled["status"] == "cancelled"
    pay = assert_ok(client.get(f"/v1/payments/{confirmed['payment_id']}",
                               role="visitor", user_id=v["id"]))
    assert pay["status"] == "captured"
    assert pay["refunded_cents"] == 0


# --- Corner: immediate_consistency_slot_counts_in_same_response ----------
def test_slot_held_count_immediately_visible(client):
    """PRD 2.7: "A `TimedEntrySlot` tracks `held_count` (reservations currently
    in `held`) ... the invariant is that `held_count` plus `booked_count` never
    exceeds the slot's `capacity`."

    Design: Corner/consistency_model/immediate_consistency_slot_counts_in_same_response
    """
    park, pa = fx.base_world(client, "CM01", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=5,
                          release_at="2026-06-05T07:00:00Z", entry_fee_cents=200)
    fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="IMM1")
    slot_after = assert_ok(client.get(f"/v1/timed-entry-slots/{slot['id']}",
                                      role="visitor", user_id=v["id"]))
    assert slot_after["held_count"] == 1
