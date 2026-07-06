"""White-glove pickup scheduling: the fiscal-beats-temporal check order, the
concierge travel buffer, and the buffer-free vehicle half-open overlap rule.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_pickup_payload,
    make_seller_headers, TEST_USERS,
    # fixtures
    setup_pickup_resources, create_pickup_item, schedule_pickup,
)

_ADMIN = TEST_USERS["ops_admin_headers"]


def _pickups_for_item(api, item_id):
    data, _meta = validate_paginated(api.list_pickups(_ADMIN, params={"item_id": item_id}))
    return data


# --- priority_pair_validation_conflict: fiscal (insurance) beats temporal -----
def test_pickup_over_cap_and_concierge_busy_reports_insurance_error(api):
    """PRD §3.2: "Scheduling a pickup runs three domain checks after existence and
    ownership have passed, in this order. First, the item's `declared_value_cents` must be
    at most the `pickup_insurance_cap_cents` of the item's category; a declared value above
    the cap is rejected with `ERR_PICKUP_VALUE_EXCEEDS_INSURANCE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/pickup_fiscal_beats_temporal
    """
    ctx = setup_pickup_resources(policy_overrides={"pickup_insurance_cap_cents": 5000000},
                                 concierge_names=("C1",), vehicle_plates=("V1", "V2"))
    seller_id, c1 = ctx["seller_id"], ctx["concierges"][0]["id"]
    v1, v2 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    hi = create_pickup_item(seller_id, declared_value_cents=6000000)
    # C1 is busy within buffer AND the value exceeds the cap; the fiscal check fires first.
    res = api.create_pickup(
        create_pickup_payload(hi["id"], c1, v2, "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"),
        make_seller_headers(seller_id))
    validate_error(res, "ERR_PICKUP_VALUE_EXCEEDS_INSURANCE", expected_status=422)


def test_pickup_over_cap_and_concierge_busy_persists_no_appointment(api):
    """PRD §3.2: "a declared value above the cap is rejected with
    `ERR_PICKUP_VALUE_EXCEEDS_INSURANCE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/pickup_fiscal_beats_temporal
    """
    ctx = setup_pickup_resources(policy_overrides={"pickup_insurance_cap_cents": 5000000},
                                 concierge_names=("C1",), vehicle_plates=("V1", "V2"))
    seller_id, c1 = ctx["seller_id"], ctx["concierges"][0]["id"]
    v1, v2 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    hi = create_pickup_item(seller_id, declared_value_cents=6000000)
    api.create_pickup(
        create_pickup_payload(hi["id"], c1, v2, "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"),
        make_seller_headers(seller_id))
    assert _pickups_for_item(api, hi["id"]) == [], "rejected pickup must not be persisted"


# --- resource_temporal_overlap: concierge 60-minute travel buffer ------------
def test_concierge_within_buffer_rejected(api):
    """PRD §3.2: "A concierge requires a one-hour travel buffer — sixty minutes — around
    every appointment: extend the requested window by sixty minutes before `window_start`
    and sixty minutes after `window_end`, and if that extended interval overlaps the window
    of any other appointment already `SCHEDULED` for the same concierge, the request is
    rejected with `ERR_CONCIERGE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/concierge_buffer_overlap_rejected
    """
    ctx = setup_pickup_resources(concierge_names=("C1",), vehicle_plates=("V1", "V2"))
    seller_id, c1 = ctx["seller_id"], ctx["concierges"][0]["id"]
    v1, v2 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    item2 = create_pickup_item(seller_id, declared_value_cents=100000)
    # Starts only 30 minutes after C1's prior job ends — inside the 60-minute buffer.
    res = api.create_pickup(
        create_pickup_payload(item2["id"], c1, v2, "2026-03-05T11:30:00Z", "2026-03-05T12:30:00Z"),
        make_seller_headers(seller_id))
    validate_error(res, "ERR_CONCIERGE_UNAVAILABLE", expected_status=409)


def test_concierge_within_buffer_persists_no_appointment(api):
    """PRD §3.2: "Equivalently, two of one concierge's appointments must be separated by at
    least sixty minutes."

    Design: Difficulty/resource_temporal_overlap/concierge_buffer_overlap_rejected
    """
    ctx = setup_pickup_resources(concierge_names=("C1",), vehicle_plates=("V1", "V2"))
    seller_id, c1 = ctx["seller_id"], ctx["concierges"][0]["id"]
    v1, v2 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    item2 = create_pickup_item(seller_id, declared_value_cents=100000)
    api.create_pickup(
        create_pickup_payload(item2["id"], c1, v2, "2026-03-05T11:30:00Z", "2026-03-05T12:30:00Z"),
        make_seller_headers(seller_id))
    assert _pickups_for_item(api, item2["id"]) == []


# --- resource_temporal_overlap: vehicle strict half-open overlap -------------
def test_vehicle_strict_overlap_rejected(api):
    """PRD §3.2: "Third, the assigned vehicle must be free, but a vehicle carries no travel
    buffer: its requested half-open window from `window_start` inclusive to `window_end`
    exclusive must not overlap any other window `SCHEDULED` for the same vehicle."

    Design: Difficulty/resource_temporal_overlap/vehicle_strict_overlap_rejected_no_buffer
    """
    ctx = setup_pickup_resources(concierge_names=("C1", "C2"), vehicle_plates=("V1",))
    seller_id = ctx["seller_id"]
    c1, c2 = ctx["concierges"][0]["id"], ctx["concierges"][1]["id"]
    v1 = ctx["vehicles"][0]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    item2 = create_pickup_item(seller_id, declared_value_cents=100000)
    # C2 is free, but [10:30,11:30) strictly overlaps V1's prior [10:00,11:00).
    res = api.create_pickup(
        create_pickup_payload(item2["id"], c2, v1, "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"),
        make_seller_headers(seller_id))
    validate_error(res, "ERR_VEHICLE_UNAVAILABLE", expected_status=409)


def test_vehicle_strict_overlap_persists_no_appointment(api):
    """PRD §3.2: "any true overlap is rejected with `ERR_VEHICLE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vehicle_strict_overlap_rejected_no_buffer
    """
    ctx = setup_pickup_resources(concierge_names=("C1", "C2"), vehicle_plates=("V1",))
    seller_id = ctx["seller_id"]
    c1, c2 = ctx["concierges"][0]["id"], ctx["concierges"][1]["id"]
    v1 = ctx["vehicles"][0]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    item2 = create_pickup_item(seller_id, declared_value_cents=100000)
    api.create_pickup(
        create_pickup_payload(item2["id"], c2, v1, "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"),
        make_seller_headers(seller_id))
    assert _pickups_for_item(api, item2["id"]) == []


# --- Corner: adjacent vehicle window allowed (no buffer) ---------------------
def test_vehicle_adjacent_window_allowed(api):
    """PRD §3.2: "Because the window is half-open, two appointments that merely touch at a
    boundary — one ending at the exact instant the next begins — do not overlap and are
    both allowed;"

    Design: Corner/state_machines/vehicle_adjacent_window_allowed_no_buffer
    """
    ctx = setup_pickup_resources(concierge_names=("C1", "C2"), vehicle_plates=("V1",))
    seller_id = ctx["seller_id"]
    c1, c2 = ctx["concierges"][0]["id"], ctx["concierges"][1]["id"]
    v1 = ctx["vehicles"][0]["id"]
    prior = create_pickup_item(seller_id, declared_value_cents=100000)
    schedule_pickup(prior["id"], c1, v1, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", seller_id)
    item2 = create_pickup_item(seller_id, declared_value_cents=100000)
    # [11:00,12:00) begins exactly when V1's prior [10:00,11:00) ends — adjacency allowed.
    res = api.create_pickup(
        create_pickup_payload(item2["id"], c2, v1, "2026-03-05T11:00:00Z", "2026-03-05T12:00:00Z"),
        make_seller_headers(seller_id))
    appt = validate_success(res, 201)
    assert appt["status"] == "SCHEDULED", appt["status"]
