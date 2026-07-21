"""Events and entries: publication gating, capacity, loyalty conservation, RBAC.

Difficulty instances: event_entry_requires_event_published,
event_entry_register_cancel_conserves_loyalty_points. Corner instances:
event_full_rejects_over_capacity_entry, event_entry_double_cancel_idempotency_rejected,
benchtech_cannot_create_event_forbidden.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
BT = TEST_USERS["bench_tech_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: event entry requires the event to be PUBLISHED
# --------------------------------------------------------------------------- #
def test_entry_on_draft_event_rejected(api):
    """PRD §3.9: "Registration is subject to two gates: the event must be `PUBLISHED`, or the entry is refused with `ERR_EVENT_NOT_OPEN`; and the event's `entry_count` must be strictly below its `capacity`, or the entry is refused with `ERR_EVENT_FULL`."

    Design: Difficulty/cross_entity_state_dependency/event_entry_requires_event_published
    """
    customer = th.create_customer(api, email="ce2@x.com", full_name="Cross Two")
    event = validate_success(
        api.create_event({"name": "Winter Contest", "sponsor": "BrandY", "venue": "City Park",
                          "start_at": "2026-07-12T00:00:00Z", "capacity": 5, "entry_fee_cents": 3000}, SM),
        expected_status=201,
    )  # left in DRAFT (never published)
    resp = api.create_event_entry(
        {"event_id": event["id"], "customer_id": customer["id"]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPEN.value)
    event_read = validate_success(api.get_event(event["id"], SA))
    assert event_read["entry_count"] == 0


def test_entry_on_published_event_succeeds(api):
    """PRD §3.9: "A successful entry opens in `status` `REGISTERED` and increments the event's `entry_count` by 1."

    Design: Difficulty/cross_entity_state_dependency/event_entry_requires_event_published
    """
    customer = th.create_customer(api, email="pub@x.com", full_name="Pub Lished")
    event = th.create_published_event(api, name="Open Jam", sponsor="BrandY", venue="City Park",
                                      start_at="2026-07-12T00:00:00Z", capacity=5, entry_fee_cents=3000)
    resp = api.create_event_entry(
        {"event_id": event["id"], "customer_id": customer["id"]},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REGISTERED"
    event_read = validate_success(api.get_event(event["id"], SA))
    assert event_read["entry_count"] == 1


# --------------------------------------------------------------------------- #
# Difficulty: register/cancel conserves loyalty points (exact reversal)
# --------------------------------------------------------------------------- #
def test_entry_cancel_reverses_exact_points_from_zero(api):
    """PRD §3.9: "Cancelling an entry decrements the event's `entry_count` by 1 and reverses exactly the entry's `points_awarded` from the member's `loyalty_points`, restoring the pre-entry balance."

    Design: Difficulty/compensating_invariant/event_entry_register_cancel_conserves_loyalty_points
    """
    customer, event, entry = th.setup_registered_entry(
        api, event_overrides={"name": "Bowl Jam", "sponsor": "BrandZ", "venue": "The Bowl",
                              "start_at": "2026-07-14T00:00:00Z", "capacity": 20, "entry_fee_cents": 5000},
        entry_overrides={"role": "PUBLIC"},
    )
    assert entry["points_awarded"] == 100  # floor(50 * 1.0 * 2.0) at BRONZE
    resp = api.cancel_event_entry(entry["id"], make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CANCELLED"
    customer_read = validate_success(api.get_customer(customer["id"], SA))
    assert customer_read["loyalty_points"] == 0


def test_entry_cancel_restores_nonzero_pre_entry_balance(api):
    """PRD §3.9: "Cancelling an entry decrements the event's `entry_count` by 1 and reverses exactly the entry's `points_awarded` from the member's `loyalty_points`, restoring the pre-entry balance."

    Design: Difficulty/compensating_invariant/event_entry_register_cancel_conserves_loyalty_points
    """
    customer = th.create_customer(api, email="lp2@x.com", full_name="Loy Points 2")
    # Prime to SILVER with 500 points via EARN 50000.
    validate_success(api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 50000}, SA))
    event = th.create_published_event(api, name="Bowl Jam 2", sponsor="BrandZ", venue="The Bowl",
                                      start_at="2026-07-14T00:00:00Z", capacity=20, entry_fee_cents=5000)
    entry = th.create_registered_entry(api, event["id"], customer["id"], role="PUBLIC")
    # SILVER snapshot: floor(50 * 1.25 * 2.0) = 125 awarded on top of the pre-entry 500.
    assert entry["points_awarded"] == 125
    mid = validate_success(api.get_customer(customer["id"], SA))
    assert mid["loyalty_points"] == 625
    validate_success(api.cancel_event_entry(entry["id"], make_customer_headers(customer["id"])))
    after = validate_success(api.get_customer(customer["id"], SA))
    assert after["loyalty_points"] == 500


# --------------------------------------------------------------------------- #
# Corner: event capacity full
# --------------------------------------------------------------------------- #
def test_entry_over_capacity_rejected(api):
    """PRD §3.9: "the event's `entry_count` must be strictly below its `capacity`, or the entry is refused with `ERR_EVENT_FULL`."

    Design: Corner/validations/event_full_rejects_over_capacity_entry
    """
    c1 = th.create_customer(api, email="ef1@x.com", full_name="Full One")
    c2 = th.create_customer(api, email="ef2@x.com", full_name="Full Two")
    event = th.create_published_event(api, name="Tiny Comp", sponsor="BrandB", venue="Ramp",
                                      start_at="2026-07-13T00:00:00Z", capacity=1, entry_fee_cents=2000)
    th.create_registered_entry(api, event["id"], c1["id"])
    resp = api.create_event_entry(
        {"event_id": event["id"], "customer_id": c2["id"]}, make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)
    event_read = validate_success(api.get_event(event["id"], SA))
    assert event_read["entry_count"] == 1


# --------------------------------------------------------------------------- #
# Corner: double cancel of an entry is rejected (idempotency guard)
# --------------------------------------------------------------------------- #
def test_double_cancel_entry_rejected(api):
    """PRD §3.9: "An entry may be cancelled by a `Customer`, `SalesAssociate`, or `ShopManager` (and is also cancelled automatically when its parent event is cancelled), which requires the entry to be `REGISTERED`, else `ERR_ENTRY_INVALID_STATE`."

    Design: Corner/state_machines/event_entry_double_cancel_idempotency_rejected
    """
    customer, event, entry = th.setup_registered_entry(
        api, event_overrides={"name": "Idem Jam", "sponsor": "BrandA", "venue": "Pier",
                              "start_at": "2026-07-11T00:00:00Z", "capacity": 10, "entry_fee_cents": 4000},
    )
    hdr = make_customer_headers(customer["id"])
    validate_success(api.cancel_event_entry(entry["id"], hdr))
    resp = api.cancel_event_entry(entry["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_ENTRY_INVALID_STATE.value)
    customer_read = validate_success(api.get_customer(customer["id"], SA))
    assert customer_read["loyalty_points"] == 0  # not reversed twice


# --------------------------------------------------------------------------- #
# Corner: RBAC — BenchTech cannot create an event
# --------------------------------------------------------------------------- #
def test_benchtech_cannot_create_event(api):
    """PRD §3.9: "A `ShopManager` creates one with a `name`, a `sponsor` brand or team, a `venue`, a `start_at`, a `capacity` (the maximum number of registered entries, at least 1), and an `entry_fee_cents` per-entry fee (non-negative), which also drives the loyalty accrual for each registration."
    PRD §2.1: "If the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/benchtech_cannot_create_event_forbidden
    """
    resp = api.create_event(
        {"name": "Nope", "sponsor": "BrandC", "venue": "X",
         "start_at": "2026-07-20T00:00:00Z", "capacity": 5, "entry_fee_cents": 1000}, BT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
