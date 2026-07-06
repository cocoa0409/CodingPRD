"""Comic issues, new-comic-day allocation, reservation cascades, copy accounting."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_comic_issue,
    assert_issue_copy_invariant,
    create_customer,
    create_series,
    create_issue,
    create_on_sale_issue,
    create_reservation,
    get_issue,
    setup_reserved_issue,
    setup_allocated_reservation,
    setup_allocated_plus_waitlisted,
    setup_subscription_allocated_plus_waitlisted,
    create_comic_series_payload,
    create_comic_issue_payload,
    create_reservation_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: allocation grant = min(requested, remaining, cap)
# ---------------------------------------------------------------------------
def test_allocation_grant_bound_by_gold_tier_cap(api, clerk_headers):
    """PRD §3.3: "a tier cap is looked up — `BRONZE` caps at 1 copy, `SILVER` at 2, and `GOLD` at 3 — and the grant is the smallest of the reservation's `requested_qty`, the current remaining figure, and that tier cap."

    Design: Difficulty/combinatorial_formula/allocation_grant_min_of_three_inputs_tier_cap_binds
    """
    # GOLD customer (lifetime_spend 150000), issue copies_ordered=5, requested_qty=5.
    cust = create_customer()
    validate_success(
        api.checkout({"customer_id": cust["id"],
                      "line_items": [{"unit_price_cents": 150000, "quantity": 1}]}, clerk_headers),
        200,
    )
    cust = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    assert cust["loyalty_tier"] == "GOLD"
    series, issue = create_on_sale_issue(copies_ordered=5, cover_price_cents=400)
    res = create_reservation(cust["id"], issue["id"], requested_qty=5)
    validate_success(api.run_allocation(issue["id"], clerk_headers), 200)
    res = validate_success(api.get_reservation(res["id"], clerk_headers), 200)
    # grant = min(requested 5, remaining 5, GOLD cap 3) = 3
    assert res["status"] == "ALLOCATED"
    assert res["allocated_qty"] == 3


def test_allocation_grant_leaves_available_remainder(api, clerk_headers):
    """PRD §3.3: "If the grant is at least 1, the reservation's `allocated_qty` is set to the grant, the reservation moves to `ALLOCATED`, the issue's `copies_allocated` rises by the grant, and remaining falls by the grant."

    Design: Difficulty/combinatorial_formula/allocation_grant_min_of_three_inputs_tier_cap_binds
    """
    cust = create_customer()
    validate_success(
        api.checkout({"customer_id": cust["id"],
                      "line_items": [{"unit_price_cents": 150000, "quantity": 1}]}, clerk_headers),
        200,
    )
    series, issue = create_on_sale_issue(copies_ordered=5, cover_price_cents=400)
    res = create_reservation(cust["id"], issue["id"], requested_qty=5)
    validate_success(api.run_allocation(issue["id"], clerk_headers), 200)
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    # copies_allocated = 3 (the GOLD grant); copies_available = 5 - 3 = 2
    assert issue_after["copies_allocated"] == 3
    assert issue_after["copies_available"] == 2
    assert_issue_copy_invariant(issue_after)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: allocation requires ON_SALE issue
# ---------------------------------------------------------------------------
def test_allocation_requires_issue_on_sale(api, clerk_headers):
    """PRD §3.3: "Running allocation is a staff capability that may be invoked only while the issue is `ON_SALE`; invoking it against an issue not on sale is rejected with `ERR_ISSUE_NOT_ON_SALE`."

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_issue_on_sale
    """
    series = create_series()
    issue = create_issue(series["id"], copies_ordered=3)
    issue = validate_success(
        api.transition_comic_issue(issue["id"], {"to_status": "ORDERED"}, clerk_headers), 200
    )
    cust = create_customer()
    validate_success(
        api.create_reservation(
            create_reservation_payload(cust["id"], issue["id"], issue["version"],
                                       requested_qty=1),
            clerk_headers,
        ),
        201,
    )
    res = api.run_allocation(issue["id"], clerk_headers)
    validate_error(res, ApiErrorId.ERR_ISSUE_NOT_ON_SALE, expected_status=409)


def test_allocation_on_ordered_issue_rejected_before_any_run(api, clerk_headers):
    """PRD §3.3: "Running allocation is a staff capability that may be invoked only while the issue is `ON_SALE`; invoking it against an issue not on sale is rejected with `ERR_ISSUE_NOT_ON_SALE`."

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_issue_on_sale
    """
    series = create_series()
    issue = create_issue(series["id"], copies_ordered=2)
    issue = validate_success(
        api.transition_comic_issue(issue["id"], {"to_status": "ORDERED"}, clerk_headers), 200
    )
    res = api.run_allocation(issue["id"], clerk_headers)
    validate_error(res, ApiErrorId.ERR_ISSUE_NOT_ON_SALE, expected_status=409)


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: subscription cancel (depth 3)
# ---------------------------------------------------------------------------
def test_subscription_cancel_releases_frees_and_promotes(api, clerk_headers):
    """PRD §3.2: "First, every reservation linked to that subscription (that is, whose `subscription_id` equals the cancelled subscription) still in `RESERVED`, `WAITLISTED`, or `ALLOCATED` is transitioned to `RELEASED`."
    PRD §3.2: "Third, for each issue whose copies_available has risen above zero as
    a result, the earliest-created reservation on that issue currently in
    `WAITLISTED` status — ordered by `created_at` ascending — is promoted to
    `ALLOCATED`, receiving an `allocated_qty` equal to the smallest of its
    `requested_qty`, the issue's current `copies_available`, and the customer's
    tier cap; that promotion decrements the issue's `copies_available` (by
    raising `copies_allocated`)."

    Design: Difficulty/transitive_cascade/subscription_cancel_releases_then_frees_then_promotes_depth3
    """
    issue, sub_a, cust_a, res_a, cust_b, res_b = setup_subscription_allocated_plus_waitlisted()
    assert res_a["status"] == "ALLOCATED"
    assert res_b["status"] == "WAITLISTED"
    validate_success(
        api.transition_pull_subscription(sub_a["id"], {"to_status": "CANCELLED"}, clerk_headers),
        200,
    )
    res_a_after = validate_success(api.get_reservation(res_a["id"], clerk_headers), 200)
    res_b_after = validate_success(api.get_reservation(res_b["id"], clerk_headers), 200)
    assert res_a_after["status"] == "RELEASED"
    assert res_b_after["status"] == "ALLOCATED"
    assert res_b_after["allocated_qty"] == 1


def test_subscription_cancel_keeps_copies_available_zero_after_promotion(api, clerk_headers):
    """PRD §3.2: "Second, each released reservation reduces its issue's `copies_reserved` by that reservation's `requested_qty`, and if the reservation had a positive `allocated_qty`, the issue's `copies_allocated` is reduced by that `allocated_qty` (so `copies_available` rises by the same amount)."

    Design: Difficulty/transitive_cascade/subscription_cancel_releases_then_frees_then_promotes_depth3
    """
    issue, sub_a, cust_a, res_a, cust_b, res_b = setup_subscription_allocated_plus_waitlisted()
    validate_success(
        api.transition_pull_subscription(sub_a["id"], {"to_status": "CANCELLED"}, clerk_headers),
        200,
    )
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    # A released (frees the 1 copy) then B promoted (retakes it): copies_available == 0.
    assert issue_after["copies_available"] == 0
    assert_issue_copy_invariant(issue_after)


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: reservation release (depth 2)
# ---------------------------------------------------------------------------
def test_reservation_release_frees_and_promotes_waitlisted(api, clerk_headers):
    """PRD §3.3: "A permitted release reduces the issue's `copies_reserved` by the reservation's `requested_qty` and reduces `copies_allocated` by the reservation's `allocated_qty` (so `copies_available` rises by that `allocated_qty`); it then promotes the earliest-created `WAITLISTED` reservation on that issue to `ALLOCATED` if `copies_available` is now at least 1."

    Design: Difficulty/transitive_cascade/reservation_release_frees_then_promotes_depth2
    """
    issue, cust_a, res_a, cust_b, res_b = setup_allocated_plus_waitlisted()
    assert res_a["status"] == "ALLOCATED"
    assert res_b["status"] == "WAITLISTED"
    from test_helpers import make_customer_headers
    owner = make_customer_headers(cust_a["id"])
    validate_success(
        api.transition_reservation(res_a["id"], {"to_status": "RELEASED"}, owner), 200
    )
    res_a_after = validate_success(api.get_reservation(res_a["id"], clerk_headers), 200)
    res_b_after = validate_success(api.get_reservation(res_b["id"], clerk_headers), 200)
    assert res_a_after["status"] == "RELEASED"
    assert res_b_after["status"] == "ALLOCATED"
    assert res_b_after["allocated_qty"] == 1


def test_reservation_release_promotion_keeps_available_zero(api, clerk_headers):
    """PRD §2.7: "The system holds one invariant at all times: `copies_available` plus `copies_allocated` equals `copies_ordered`."

    Design: Difficulty/transitive_cascade/reservation_release_frees_then_promotes_depth2
    """
    issue, cust_a, res_a, cust_b, res_b = setup_allocated_plus_waitlisted()
    from test_helpers import make_customer_headers
    owner = make_customer_headers(cust_a["id"])
    validate_success(
        api.transition_reservation(res_a["id"], {"to_status": "RELEASED"}, owner), 200
    )
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert issue_after["copies_available"] == 0
    assert_issue_copy_invariant(issue_after)


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: copies conservation across allocate/release
# ---------------------------------------------------------------------------
def test_copies_return_to_ordered_after_release(api, clerk_headers):
    """PRD §2.7: "copies_available` is defined as `copies_ordered` minus `copies_allocated`. The system holds one invariant at all times: `copies_available` plus `copies_allocated` equals `copies_ordered`."

    Design: Difficulty/compensating_invariant/copies_conservation_across_allocate_release
    """
    cust, series, issue, res = setup_allocated_reservation(copies_ordered=3, requested_qty=1)
    assert res["status"] == "ALLOCATED"
    from test_helpers import make_customer_headers
    owner = make_customer_headers(cust["id"])
    validate_success(
        api.transition_reservation(res["id"], {"to_status": "RELEASED"}, owner), 200
    )
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert issue_after["copies_available"] == 3
    assert issue_after["copies_allocated"] == 0


def test_copies_conserved_at_each_step_no_drift(api, clerk_headers):
    """PRD §2.7: "copies_available` is defined as `copies_ordered` minus `copies_allocated`. The system holds one invariant at all times: `copies_available` plus `copies_allocated` equals `copies_ordered`."

    Design: Difficulty/compensating_invariant/copies_conservation_across_allocate_release
    """
    cust, series, issue, res = setup_allocated_reservation(copies_ordered=3, requested_qty=1)
    allocated = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert allocated["copies_available"] == 2
    assert allocated["copies_allocated"] == 1
    assert_issue_copy_invariant(allocated)
    from test_helpers import make_customer_headers
    owner = make_customer_headers(cust["id"])
    validate_success(
        api.transition_reservation(res["id"], {"to_status": "RELEASED"}, owner), 200
    )
    released = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert released["copies_available"] == 3
    assert released["copies_allocated"] == 0
    assert_issue_copy_invariant(released)


# ---------------------------------------------------------------------------
# Queue B — entities / state machines / calculations
# ---------------------------------------------------------------------------
def test_comic_issue_copies_available_computed_on_create(api, clerk_headers):
    """PRD §3.1: "A new issue opens in `SOLICITED` status with `copies_reserved` and `copies_allocated` both zero and `copies_available` equal to `copies_ordered`."

    Design: Corner/entities/comic_issue_computed_copies_available_ignores_input
    """
    series = create_series()
    issue = validate_success(
        api.create_comic_issue(create_comic_issue_payload(series["id"], copies_ordered=10),
                               clerk_headers),
        201,
    )
    assert issue["copies_available"] == 10
    assert issue["copies_allocated"] == 0


def test_comic_issue_initial_state_solicited(api, clerk_headers):
    """PRD §3.1: "A new issue opens in `SOLICITED` status with `copies_reserved` and `copies_allocated` both zero and `copies_available` equal to `copies_ordered`."

    Design: Corner/state_machines/comic_issue_initial_state_solicited
    """
    series = create_series()
    issue = validate_success(
        api.create_comic_issue(create_comic_issue_payload(series["id"]), clerk_headers), 201
    )
    assert issue["status"] == "SOLICITED"


def test_comic_issue_skip_to_on_sale_invalid(api, clerk_headers):
    """PRD §3.1: "Moving from `SOLICITED` to `ORDERED` is permitted only when the parent series is still `ACTIVE"
    PRD §2.8: "State — the target resource is in a state from which the requested
    transition or operation is defined, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/comic_issue_skip_to_on_sale_invalid
    """
    series = create_series()
    issue = validate_success(
        api.create_comic_issue(create_comic_issue_payload(series["id"]), clerk_headers), 201
    )
    res = api.transition_comic_issue(issue["id"], {"to_status": "ON_SALE"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_comic_issue_close_expires_open_reservations(api, clerk_headers):
    """PRD §3.1: "every reservation on the issue still in `RESERVED`, `WAITLISTED`, or `ALLOCATED` is transitioned to `EXPIRED`; for each such expired reservation, the issue's `copies_reserved` is reduced by that reservation's `requested_qty"

    Design: Corner/state_machines/comic_issue_close_expires_open_reservations
    """
    cust, series, issue, res = setup_reserved_issue(copies_ordered=5, requested_qty=1)
    validate_success(
        api.transition_comic_issue(issue["id"], {"to_status": "CLOSED"}, clerk_headers), 200
    )
    res_after = validate_success(api.get_reservation(res["id"], clerk_headers), 200)
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert res_after["status"] == "EXPIRED"
    assert issue_after["copies_reserved"] == 0


def test_allocation_orders_by_created_at_within_tier(api, clerk_headers):
    """PRD §3.3: "within the same tier by the reservation's `created_at` ascending (earliest first). Ordering never uses the reservation `id`."

    Design: Corner/calculations/allocation_waterfall_orders_by_tier_then_created_at
    """
    # copies_ordered=1, two BRONZE customers; earlier reservation wins.
    series, issue = create_on_sale_issue(copies_ordered=1)
    c1 = create_customer()
    c2 = create_customer()
    r1 = create_reservation(c1["id"], issue["id"], requested_qty=1)
    r2 = create_reservation(c2["id"], issue["id"], requested_qty=1)
    validate_success(api.run_allocation(issue["id"], clerk_headers), 200)
    r1_after = validate_success(api.get_reservation(r1["id"], clerk_headers), 200)
    r2_after = validate_success(api.get_reservation(r2["id"], clerk_headers), 200)
    assert r1_after["status"] == "ALLOCATED"
    assert r2_after["status"] == "WAITLISTED"


def test_list_comic_issues_paginated(api, clerk_headers):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_comic_issues_paginated
    """
    series = create_series()
    create_issue(series["id"], issue_number="1")
    create_issue(series["id"], issue_number="2")
    data, meta = validate_paginated(
        api.list_comic_issues(clerk_headers, params={"series_id": series["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
