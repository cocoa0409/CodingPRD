"""Crew referral and scheduling: zone matching, the one-crew-per-date slot,
deactivation cascade depth 2 (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    create_batch,
    create_config,
    create_crew,
    create_customer,
    create_field,
    create_quote,
    create_variety,
    factories,
    get_order,
    get_success_data,
    mini_chain,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _referral_of(api, order_id, referral_id):
    data, _meta = validate_paginated(api.list_order_crew_referrals(order_id, SALES))
    matches = [r for r in data if r["id"] == referral_id]
    assert len(matches) == 1, f"referral {referral_id} not found on order {order_id}"
    return matches[0]


def _confirmed_order_with_referral(api):
    """CONFIRMED order for a zone-2 customer with a REFERRED crew referral."""
    bundle = mini_chain(api, stage="confirmed")
    crew = create_crew(api, name="Alpha Install", service_zones=[2])
    ref = get_success_data(api.create_crew_referral(
        bundle["o"]["id"], factories.create_crew_referral_payload(crew["id"]), SALES
    ))
    bundle["crew"] = crew
    bundle["ref"] = ref
    return bundle


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / crew_deactivate_cascade_depth2
# ---------------------------------------------------------------------------

def test_deactivate_crew_replaces_live_referrals(api):
    """PRD §3.8: "Deactivation ripples outward two hops. When a `FarmManager` deactivates a crew, its `active` flag drops to false, every referral of that crew in `REFERRED` or `SCHEDULED` moves to `REPLACED`, and each affected order's `crew_referral_status` resets to `NONE` — the orders are left uncrewed but otherwise untouched, free to receive a fresh referral."

    Design: Difficulty/transitive_cascade/crew_deactivate_cascade_depth2
    """
    bundle = _confirmed_order_with_referral(api)
    crew, ref, o = bundle["crew"], bundle["ref"], bundle["o"]

    deactivated = get_success_data(api.deactivate_crew(crew["id"], FARM))
    assert deactivated["active"] is False

    assert _referral_of(api, o["id"], ref["id"])["status"] == "REPLACED", (
        "hop 1: the crew's live referral is replaced"
    )


def test_deactivate_crew_clears_order_referral_marker(api):
    """PRD §3.8: "Deactivation ripples outward two hops. When a `FarmManager` deactivates a crew, its `active` flag drops to false, every referral of that crew in `REFERRED` or `SCHEDULED` moves to `REPLACED`, and each affected order's `crew_referral_status` resets to `NONE` — the orders are left uncrewed but otherwise untouched, free to receive a fresh referral."

    Design: Difficulty/transitive_cascade/crew_deactivate_cascade_depth2
    """
    bundle = _confirmed_order_with_referral(api)
    crew, o = bundle["crew"], bundle["o"]
    assert get_order(api, o["id"])["crew_referral_status"] == "CREW_REFERRED"

    get_success_data(api.deactivate_crew(crew["id"], FARM))

    order = get_order(api, o["id"])
    assert order["crew_referral_status"] == "NONE", (
        "hop 2: the order's referral marker resets"
    )
    assert order["status"] == "CONFIRMED", "the order is otherwise untouched"

    # The order is free to receive a fresh referral from another active crew.
    crew2 = create_crew(api, name="Beta Install", service_zones=[2])
    fresh = get_success_data(api.create_crew_referral(
        o["id"], factories.create_crew_referral_payload(crew2["id"]), SALES
    ))
    assert fresh["status"] == "REFERRED"
    assert get_order(api, o["id"])["crew_referral_status"] == "CREW_REFERRED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / crew_single_date_slot_conflict
# ---------------------------------------------------------------------------

def _two_confirmed_orders_one_crew(api):
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b1 = create_batch(api, f["id"], pallet_count=10, scheduled_date="2026-08-03")
    b2 = create_batch(api, f["id"], pallet_count=10, scheduled_date="2026-08-04")
    crew = create_crew(api, name="Alpha Install", service_zones=[2])
    c1 = create_customer(api)
    c2 = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                         phone="555-0102", freight_zone=2, address="4 Pine Ave")
    set_clock(api, "2026-08-01T09:00:00Z")
    q1 = create_quote(api, c1["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0)
    o1 = accept_quote(api, q1["id"])
    get_success_data(api.confirm_order(
        o1["id"], factories.confirm_order_payload(), SALES
    ))
    q2 = create_quote(api, c2["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0,
                      delivery_date="2026-08-04")
    o2 = accept_quote(api, q2["id"])
    get_success_data(api.confirm_order(
        o2["id"],
        factories.confirm_order_payload(
            delivery_window_start="2026-08-04T08:00:00Z"
        ),
        SALES,
    ))
    get_success_data(api.create_crew_referral(
        o1["id"], factories.create_crew_referral_payload(crew["id"]), SALES
    ))
    ref1 = get_success_data(api.schedule_crew(
        o1["id"], factories.schedule_crew_payload("2026-08-05"), SALES
    ))
    get_success_data(api.create_crew_referral(
        o2["id"], factories.create_crew_referral_payload(crew["id"]), SALES
    ))
    return {"crew": crew, "o1": o1, "o2": o2, "ref1": ref1}


def test_crew_already_scheduled_that_date_conflicts(api):
    """PRD §3.8: "A `SalesRep` schedules the order's live `REFERRED` referral with a `scheduled_date` that must not be earlier than the order's `delivery_date` (otherwise `ERR_INVALID_REQUEST`), and one crew serves at most one date across the entire book: if the same crew already holds a `SCHEDULED` referral for that calendar date on another order, the request is rejected with `ERR_CREW_DATE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_single_date_slot_conflict
    """
    s = _two_confirmed_orders_one_crew(api)
    assert s["ref1"]["status"] == "SCHEDULED"
    resp = api.schedule_crew(
        s["o2"]["id"], factories.schedule_crew_payload("2026-08-05"), SALES
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DATE_CONFLICT, 409)


def test_same_crew_on_a_different_date_succeeds(api):
    """PRD §3.8: "A successful scheduling moves the referral from `REFERRED` to `SCHEDULED`, records the `scheduled_date`, and moves the order's `crew_referral_status` to `CREW_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/crew_single_date_slot_conflict
    """
    s = _two_confirmed_orders_one_crew(api)
    ref2 = get_success_data(api.schedule_crew(
        s["o2"]["id"], factories.schedule_crew_payload("2026-08-06"), SALES
    ))
    assert ref2["status"] == "SCHEDULED"
    assert ref2["scheduled_date"] == "2026-08-06"
    assert get_order(api, s["o2"]["id"])["crew_referral_status"] == "CREW_SCHEDULED"
    # The first booking is untouched.
    assert _referral_of(api, s["o1"]["id"], s["ref1"]["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: errors / crew_zone_mismatch_returns_error
# ---------------------------------------------------------------------------

def test_crew_zone_mismatch_returns_error(api):
    """PRD §3.8: "The referred crew must be `active` — an inactive crew is rejected with `ERR_INVALID_REQUEST` — and its `service_zones` must include the customer's `freight_zone`, otherwise `ERR_CREW_ZONE_MISMATCH`."

    Design: Corner/errors/crew_zone_mismatch_returns_error
    """
    bundle = mini_chain(api, stage="confirmed")  # customer freight_zone 2
    crew = create_crew(api, name="Zone1 Only", service_zones=[1])
    resp = api.create_crew_referral(
        bundle["o"]["id"], factories.create_crew_referral_payload(crew["id"]), SALES
    )
    validate_error(resp, ApiErrorId.ERR_CREW_ZONE_MISMATCH, 422)
