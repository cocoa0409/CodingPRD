"""Breadth coverage: entity creation, computed fields, immutability, and the
catalog/endpoint behaviors (pagination envelope, policy activation, activity
line totals).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_farm, assert_weather_event
from test_helpers.factories import create_reservation_payload
from test_helpers.test_users import make_visitor_headers

MANAGER = fx.MANAGER


# ===========================================================================
# Queue B — entities
# ===========================================================================

def test_create_farm_open_posture_and_defaults(api):
    """PRD §3.1: "its `operational_status` starts at `OPEN`, its
    `active_weather_event_id` is null, and its `refunds_issued_cents` — the
    running total of admission cents auto-refunded by weather closures — starts
    at 0."
    PRD §3.1: "its `parking_fee_cents` (the flat per-vehicle parking charge,
    defaulting to 1000 cents — ten dollars — and never negative), and its
    `window_buffer_minutes` (the minimum cleanup gap required between two windows
    on the farm, defaulting to 30 minutes and never negative)."

    Design: Corner/entities/create_farm_returns_201_with_open_posture_and_defaults
    """
    res = api.create_farm({"name": "Default Farm"}, MANAGER)
    farm = validate_success(res, 201)
    assert_farm(farm)
    assert farm["operational_status"] == "OPEN"
    assert farm["parking_fee_cents"] == 1000
    assert farm["window_buffer_minutes"] == 30
    assert farm["version"] == 1


def test_get_nonexistent_farm_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing
    resource produces `ERR_NOT_FOUND` immediately, before any later identifier or
    any business rule is evaluated."

    Design: Corner/entities/get_farm_nonexistent_returns_not_found
    """
    resp = api.get_farm("00000000-0000-4000-8000-000000000000", MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_reservation_missing_window_id_rejected(api):
    """PRD §2.7: "every request body is first checked for structural
    well-formedness: a malformed body, a missing required field, an unrecognized
    enum value, or a numeric value that falls outside its stated range (for
    example a negative cents amount, a non-positive weight, or a discount
    percentage that is not at least 0 and strictly below 1) is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/create_reservation_missing_required_window_id_rejected
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    payload = create_reservation_payload(s["window"]["id"], s["visitor"]["id"],
                                         s["window"]["version"], adult_count=1, child_count=0)
    del payload["window_id"]
    resp = api.create_reservation(payload, make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_reservation_participant_count_computed(api):
    """PRD §3.3: "The system derives `participant_count` as the sum of
    `adult_count` and `child_count`".

    Design: Corner/entities/reservation_participant_count_computed_from_adult_plus_child
    """
    s = fx.setup_farm_with_visitor(capacity=10)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=2, child_count=3)
    assert res["participant_count"] == 5, (
        f"participant_count must be 2+3=5, got {res['participant_count']}"
    )


def test_concession_parking_cents_computed_from_farm_fee(api):
    """PRD §3.5: "the order's `parking_cents` is computed as `vehicle_count`
    multiplied by the farm's `parking_fee_cents` (snapshotted at create), its
    `total_cents` is `food_cents` plus `parking_cents`, and its `status` is
    `PAID`."

    Design: Corner/entities/concession_parking_cents_computed_from_farm_fee
    """
    s = fx.setup_farm_with_visitor(capacity=5, policy_overrides=None)
    # farm parking_fee_cents default 1000.
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=0)
    order = fx.add_concession(res["id"], s["visitor"]["id"], food_cents=500, vehicle_count=3)
    assert order["parking_cents"] == 3000, f"3 * 1000 == 3000, got {order['parking_cents']}"
    assert order["total_cents"] == 3500, f"500 + 3000 == 3500, got {order['total_cents']}"


def test_weather_event_is_immutable_log(api):
    """PRD §2.4: "A `WeatherEvent` therefore carries only `id` and `created_at` —
    it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/weather_event_is_immutable_log_no_version_field
    """
    farm = fx.create_farm(name="Log Farm")
    we = fx.declare_hold(farm["id"], note="rain")
    assert_weather_event(we)

    data, meta = validate_paginated(api.list_weather_events(farm["id"], MANAGER))
    assert any(e["id"] == we["id"] for e in data), "recorded weather event must appear in the log"
    for e in data:
        assert "version" not in e, "WeatherEvent must not expose a version field"
        assert "updated_at" not in e, "WeatherEvent must not expose an updated_at field"


# ===========================================================================
# Queue B — endpoints
# ===========================================================================

def test_list_admission_windows_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_admission_windows_paginated_envelope
    """
    farm = fx.create_farm(name="List Farm", window_buffer_minutes=0)
    fx.create_window(farm["id"], capacity=5,
                     starts_at="2026-10-11T14:00:00Z", ends_at="2026-10-11T16:00:00Z")
    fx.create_window(farm["id"], capacity=5,
                     starts_at="2026-10-12T14:00:00Z", ends_at="2026-10-12T16:00:00Z")

    data, meta = validate_paginated(
        api.list_admission_windows(farm["id"], MANAGER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_activate_policy_supersedes_prior_active(api):
    """PRD §3.1: "activation sets that policy's `status` to `ACTIVE` and, if some
    other policy on the same farm was already `ACTIVE`, demotes that prior
    policy's `status` to `SUPERSEDED` — only one policy per farm is `ACTIVE` at
    any moment."

    Design: Corner/endpoints/activate_policy_supersedes_prior_active
    """
    farm = fx.create_farm(name="Supersede Farm")
    policy1 = fx.create_active_policy(farm["id"])
    policy2 = fx.create_policy(farm["id"], adult_admission_cents=2500, child_admission_cents=1500)

    activated2 = validate_success(api.activate_pricing_policy(policy2["id"], MANAGER))
    assert activated2["status"] == "ACTIVE"

    policy1_after = validate_success(api.get_pricing_policy(policy1["id"], MANAGER))
    assert policy1_after["status"] == "SUPERSEDED", "prior ACTIVE policy must be superseded"


def test_activity_pass_line_total_computed(api):
    """PRD §3.5: "the pass's `unit_price_cents` is snapshotted from the `ACTIVE`
    policy's matching activity rate — `hayride_pass_cents`, `maze_pass_cents`, or
    `upick_pass_cents` — its `line_total_cents` is `quantity` multiplied by
    `unit_price_cents`, and its `status` is `ACTIVE`."

    Design: Corner/endpoints/activity_pass_line_total_computed
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=0)
    ap = fx.add_activity_pass(res["id"], s["visitor"]["id"], "HAYRIDE", quantity=3)
    assert ap["unit_price_cents"] == 800, f"HAYRIDE unit price snapshot 800, got {ap['unit_price_cents']}"
    assert ap["line_total_cents"] == 2400, f"3 * 800 == 2400, got {ap['line_total_cents']}"
