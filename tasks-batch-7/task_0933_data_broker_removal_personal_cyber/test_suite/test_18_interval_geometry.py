"""Two contrasting occupancy geometries: the capacity-N, half-open,
zero-buffer seat pool and the capacity-one, closed, 24-hour-buffered
exposure removal channel."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_same_instant, assert_seat_conservation, fixtures as fx,
)


# ==========================================================================
# The seat pool: aggregate capacity, half-open interval, zero adjacency buffer
# ==========================================================================

def _addon_with_both_seats_bound():
    household = fx.open_household()
    addon = fx.buy_addon(household, addon_type="VPN", seats_total=2,
                         per_seat_fee_cents=300)
    seat_one = fx.bind_seat(household, addon["id"], device_label="Laptop")
    seat_two = fx.bind_seat(household, addon["id"], device_label="Tablet")
    return household, addon, seat_one, seat_two


def test_binding_against_a_full_seat_pool_is_refused(api):
    """PRD §3.8: "Pool occupancy is an aggregate-capacity rule with capacity equal to
    `seats_total`: a bind is admitted only while the count of seats in `BOUND` on that
    add-on is **strictly less than** `seats_total`, and is otherwise rejected with
    `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/seat_pool_capacity_half_open_zero_buffer_adjacency
    """
    household, addon, seat_one, seat_two = _addon_with_both_seats_bound()
    version_before = fx.addon_version(addon["id"], household["owner"])

    response = api.create_device_seat(
        {"addon_id": addon["id"], "member_id": household["owner_id"],
         "device_label": "Phone", "expected_addon_version": version_before},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value, 409)
    row = fx.read_addon(addon["id"])
    assert row["seats_bound"] == 2
    assert row["seats_available"] == 0
    assert row["version"] == version_before, "a refused bind must not bump the add-on"
    assert_seat_conservation(row)


def test_a_release_and_a_bind_at_the_same_instant_are_both_admitted(api):
    """PRD §3.8: "The occupied interval is **half-open** — a seat occupies the pool from
    its `bound_at` up to but not including its `released_at` — and the adjacency buffer is
    zero seconds, so releasing one seat and binding another at the very same logical
    instant is legal."
    PRD §3.8: "Releasing a seat moves it `BOUND → RELEASED`, stamps `released_at`, and
    lowers `seats_bound` while raising `seats_available` by one."

    Design: Difficulty/resource_temporal_overlap/seat_pool_capacity_half_open_zero_buffer_adjacency
    """
    household, addon, seat_one, seat_two = _addon_with_both_seats_bound()

    released = validate_success(api.release_seat(seat_one["id"], household["owner"]))
    assert released["status"] == "RELEASED"
    # The clock has not moved since the account was opened.
    assert_same_instant(released["released_at"], "2026-05-01T00:00:00Z", "released_at")
    freed = fx.read_addon(addon["id"])
    assert freed["seats_available"] == 1

    data = validate_success(api.create_device_seat(
        {"addon_id": addon["id"], "member_id": household["owner_id"],
         "device_label": "Phone",
         "expected_addon_version": fx.addon_version(addon["id"], household["owner"])},
        household["owner"]), 201)

    assert data["status"] == "BOUND"
    assert_same_instant(data["bound_at"], "2026-05-01T00:00:00Z", "bound_at")
    refilled = fx.read_addon(addon["id"])
    assert refilled["seats_bound"] == 2
    assert refilled["seats_available"] == 0
    assert_seat_conservation(refilled)


# ==========================================================================
# The exposure removal channel: capacity one, closed interval, 24-hour buffer
# ==========================================================================

def _exposure_with_one_drafted_request():
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    world["request"] = fx.draft_removal(world["exposure"]["id"])
    return world


def test_a_second_draft_on_an_occupied_exposure_is_refused(api):
    """PRD §3.5: "Capacity on an exposure is exactly one live request: if any removal
    request on that exposure currently sits in `DRAFTED`, `SUBMITTED`, `ACKNOWLEDGED` or
    `ESCALATED`, the draft is rejected with `ERR_DUPLICATE_REMOVAL_REQUEST`."

    Design: Difficulty/resource_temporal_overlap/exposure_channel_closed_interval_with_reopen_buffer
    """
    world = _exposure_with_one_drafted_request()

    response = api.create_removal_request(world["exposure"]["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_REMOVAL_REQUEST.value, 409)
    assert fx.read_removal(world["request"]["id"])["status"] == "DRAFTED"


def test_the_reopen_buffer_admits_a_successor_at_exactly_twenty_four_hours(api):
    """PRD §3.5: "The buffer boundary is inclusive on the allow side: a new request at
    exactly the incumbent's `closed_at` plus 24 hours is admitted, and one millisecond
    earlier is rejected with `ERR_EXPOSURE_CHANNEL_BUFFER`."
    PRD §3.5: "From `DRAFTED → VOIDED`, available to a `PrivacyAgent`, the `AccountOwner`
    or a `Member` and also reachable as hop 2 of an authorization revocation, it stamps
    `closed_at`; and when the request had `entitlement_units_consumed` 1 and
    `entitlement_units_released` 0, it sets `entitlement_units_released` to 1 and appends a
    `REMOVAL` `RELEASE` entry of `amount` 1 with `reason_code` `REMOVAL_VOIDED`, which
    raises the account's `removal_units_released` and `removal_units_remaining` by one and
    lowers the member's `removal_units_consumed_this_cycle` by one."

    Design: Difficulty/resource_temporal_overlap/exposure_channel_closed_interval_with_reopen_buffer
    """
    world = _exposure_with_one_drafted_request()
    exposure_id = world["exposure"]["id"]

    voided = validate_success(api.void_removal_request(world["request"]["id"], fx.AGENT))
    assert voided["status"] == "VOIDED"
    assert_same_instant(voided["closed_at"], "2026-05-01T00:00:00Z", "closed_at")

    # closed_at + 0h — the incumbent's interval is closed, so this is inside it.
    validate_error(api.create_removal_request(exposure_id, fx.AGENT),
                   ApiErrorId.ERR_EXPOSURE_CHANNEL_BUFFER.value, 409)

    # closed_at + 23h59m59s — still one second short of the buffer.
    fx.set_clock("2026-05-01T23:59:59Z")
    validate_error(api.create_removal_request(exposure_id, fx.AGENT),
                   ApiErrorId.ERR_EXPOSURE_CHANNEL_BUFFER.value, 409)

    # closed_at + exactly 24h — admitted on the inclusive side of the boundary.
    fx.set_clock("2026-05-02T00:00:00Z")
    data = validate_success(api.create_removal_request(exposure_id, fx.AGENT), 201)

    assert data["status"] == "DRAFTED"
    assert data["entitlement_units_consumed"] == 1
    account = fx.read_account(world["household"])
    # 60 granted - 2 consumed (the voided draft and this one) + 1 released = 59.
    assert account["removal_units_remaining"] == 59
