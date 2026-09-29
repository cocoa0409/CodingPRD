"""Two temporal-interval rules that disagree on their boundaries: the half-open
designation window and the closed test-buy cooling interval."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    assert_cents,
    assert_instant_equals,
    create_representative,
    read_brand,
    representative_payload,
    set_clock,
    setup_claim,
    setup_enrolled_brand,
    test_buy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_window_starting_at_the_incumbents_end_passes_and_one_second_earlier_fails(api):
    """PRD §3.2: "Because the end is exclusive, **adjacency is allowed**: a window ending at exactly the instant the next begins is not a conflict."
    PRD §3.2: "Two designations of the same enrolment conflict only when all three of the following hold: both are still `DESIGNATED`, their power sets intersect, and their windows overlap in the half-open sense — that is, the first window's start lies strictly before the second's end and the second's start lies strictly before the first's end."
    PRD §3.2: "A conflict is refused with `ERR_REPRESENTATIVE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/representative_windows_are_half_open_so_adjacency_passes_and_one_second_fails
    """
    ctx = setup_enrolled_brand(
        api, clock="2026-08-05T09:00:00Z",
        representative={"effective_from": "2026-08-01T00:00:00Z",
                        "effective_to": "2026-09-01T00:00:00Z",
                        "power_of_attorney_ref": "POA-INCUMBENT"})
    incumbent = ctx["representative"]

    adjacent = create_representative(
        api, ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
        power_of_attorney_ref="POA-ADJACENT")
    assert adjacent["designation_status"] == "DESIGNATED", (
        f"Adjacency is allowed, got {adjacent['designation_status']}")
    assert_instant_equals(adjacent["effective_from"], "2026-09-01T00:00:00Z", "effective_from")

    overlapping = api.create_representative(
        representative_payload(
            ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
            effective_from="2026-08-31T23:59:59Z", effective_to="2026-09-15T00:00:00Z",
            power_of_attorney_ref="POA-ONE-SECOND"),
        headers=ADMIN)
    validate_error(overlapping, ApiErrorId.REPRESENTATIVE_WINDOW_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_representatives(headers=ADMIN, enrollment_id=ctx["enrollment"]["id"]))
    assert meta["total_count"] == 2, (
        f"The refused designation persisted nothing, got {meta['total_count']}")
    assert {row["id"] for row in rows} == {incumbent["id"], adjacent["id"]}


def test_a_window_ending_at_the_incumbents_start_passes_and_one_second_later_fails(api):
    """PRD §3.2: "The designation window is **half-open**: it includes `effective_from` and excludes `effective_to`, and an omitted or null `effective_to` means the window never closes."
    PRD §3.2: "Because the end is exclusive, **adjacency is allowed**: a window ending at exactly the instant the next begins is not a conflict."
    PRD §3.2: "Revocation releases the window-and-scope occupancy the row held, so a fresh designation may then cover an overlapping window."

    Design: Difficulty/resource_temporal_overlap/representative_windows_are_half_open_so_adjacency_passes_and_one_second_fails
    """
    ctx = setup_enrolled_brand(
        api, clock="2026-08-05T09:00:00Z",
        representative={"effective_from": "2026-09-01T00:00:00Z",
                        "effective_to": "2026-10-01T00:00:00Z",
                        "power_of_attorney_ref": "POA-LATER"})
    later = ctx["representative"]

    earlier = create_representative(
        api, ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
        effective_from="2026-08-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z",
        power_of_attorney_ref="POA-EARLIER")
    assert earlier["designation_status"] == "DESIGNATED", (
        f"A window ending where the next begins is not a conflict, got {earlier}")

    one_second_over = representative_payload(
        ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
        effective_from="2026-08-15T00:00:00Z", effective_to="2026-09-01T00:00:01Z",
        power_of_attorney_ref="POA-ONE-SECOND")
    validate_error(api.create_representative(one_second_over, headers=ADMIN),
                   ApiErrorId.REPRESENTATIVE_WINDOW_OVERLAP, 409)

    validate_success(api.revoke_representative(later["id"], "REPLACED", headers=ADMIN), 200)
    validate_success(api.revoke_representative(earlier["id"], "REPLACED", headers=ADMIN), 200)

    accepted = validate_success(
        api.create_representative(one_second_over, headers=ADMIN), 201)
    assert_instant_equals(accepted["effective_to"], "2026-09-01T00:00:01Z", "effective_to")
    assert accepted["designation_status"] == "DESIGNATED"


def test_exactly_seven_days_between_orders_is_still_a_collision(api):
    """PRD §3.6: "The interval is closed and inflated on both sides: an order at some instant conflicts with an existing order whenever the gap between their order instants is seven days or less in either direction, so **exactly seven days apart is a conflict** — the boundary instant itself is refused, which is the opposite of the representative-window rule in §3.2."
    PRD §3.6: "Ordering two covert purchases from the same seller in quick succession is how brand-protection teams get detected, so a new order must be more than seven days away from every other non-cancelled test buy against the same seller."
    PRD §3.6: "A conflict is refused with `ERR_TEST_BUY_COOLING_PERIOD` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/test_buy_cooling_interval_is_closed_so_exactly_seven_days_still_collides
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z")
    first = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)
    assert_instant_equals(first["ordered_at"], "2026-08-05T08:00:00Z", "ordered_at")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 5635,
                 "enforcement_spend_cents")

    set_clock(api, "2026-08-12T08:00:00Z")
    at_boundary = api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST)
    validate_error(at_boundary, ApiErrorId.TEST_BUY_COOLING_PERIOD, 409)
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 5635,
                 "A refused order leaves the ledger alone")

    set_clock(api, "2026-08-12T08:00:01Z")
    just_outside = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)
    assert_instant_equals(just_outside["ordered_at"], "2026-08-12T08:00:01Z", "ordered_at")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 11270,
                 "enforcement_spend_cents")

    rows, meta = validate_paginated(
        api.list_test_buys(headers=ANALYST, seller_id=ctx["seller"]["id"]))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert {row["id"] for row in rows} == {first["id"], just_outside["id"]}


def test_a_cancelled_order_leaves_the_cooling_comparison_set(api):
    """PRD §3.6: "Cancelled purchases are excluded from the comparison set entirely."
    PRD §3.6: "The cancelled row also leaves the cooling-period comparison set, so the seller becomes immediately re-orderable."
    PRD §3.6: "An `ORDERED` purchase that never shipped may be cancelled by the analyst, supplying a `reason_code`; the row moves `ORDERED → CANCELLED`."

    Design: Difficulty/resource_temporal_overlap/test_buy_cooling_interval_is_closed_so_exactly_seven_days_still_collides
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z")
    first = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)

    same_instant = api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST)
    validate_error(same_instant, ApiErrorId.TEST_BUY_COOLING_PERIOD, 409)

    cancelled = validate_success(
        api.cancel_test_buy(first["id"], "NEVER_SHIPPED", headers=ANALYST), 200)
    assert cancelled["status"] == "CANCELLED", f"got {cancelled['status']}"

    replacement = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)
    assert_instant_equals(replacement["ordered_at"], "2026-08-05T08:00:00Z",
                          "ordered_at of the replacement order at the very same instant")
    assert replacement["id"] != first["id"]
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 5635,
                 "enforcement_spend_cents")
