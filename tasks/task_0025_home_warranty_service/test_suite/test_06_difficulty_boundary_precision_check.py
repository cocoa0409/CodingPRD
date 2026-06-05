"""Difficulty Rule 6 — boundary_precision_check.

Two boundaries with strict less-than semantics PRD calls out verbatim:
- return-visit window: exact equality between clock and L + W days closes the window
- max_covered_items: count == max permitted, count > max rejected
"""
from test_helpers import (
    validate_error,
    get_success_data,
    set_clock,
    setup_active_contract_with_item,
    file_claim,
    assess_claim,
    dispatch_claim,
    resolve_claim,
    get_dispatch_for_claim,
    start_dispatch,
    complete_dispatch,
    make_customer_headers,
    create_covered_item_payload,
)


class TestReturnVisitWindowExactBoundaryClosed:
    """At T = L + W*86400 EXACTLY, the window has just closed → is_return_visit=false.
    PRD §3.5."""

    def test_clock_at_exact_window_boundary_is_not_return_visit(self, api):
        """PRD §3.5: "The boundary is exclusive on the right: an exact equality
        between the current clock and `last_dispatch_completed_utc` plus
        `return_visit_window_days` days evaluates as **not** within the window
        (the window has just closed)."

        Design: Difficulty/boundary_precision_check/return_visit_window_exact_boundary_closed
        """
        # First dispatch completes at 2026-02-01T10:00:00Z; window = 30 days; therefore
        # the boundary is 2026-03-03T10:00:00Z.
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        c1 = file_claim(contract, customer, item, issue="First")
        assess_claim(c1, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "tech-A", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        resolve_claim(c1, 10_000)

        # Second claim with dispatch happening EXACTLY at the boundary
        # (2026-02-01T10:00:00Z + 30 days = 2026-03-03T10:00:00Z).
        set_clock("2026-03-03T10:00:00Z")
        c2 = file_claim(contract, customer, item, issue="Same again")
        assess_claim(c2, 10_000)
        dispatched = dispatch_claim(c2, "tech-B", "2026-03-03T11:00:00Z")
        # Window is closed at the exact boundary → is_return_visit = false.
        assert dispatched["is_return_visit"] is False
        # SF pinned to package.service_fee_cents because not a return visit.
        assert dispatched["service_fee_charged_cents"] == 7500

    def test_clock_strictly_before_boundary_is_return_visit(self, api):
        """PRD §3.5: "If the current clock is strictly earlier than that boundary,
        `is_return_visit` is pinned to true and `prior_dispatch_id` is pinned to
        the covered item's current `last_dispatch_id` — the dispatch that began the window."

        Design: Difficulty/boundary_precision_check/return_visit_window_exact_boundary_closed
        """
        # One second BEFORE the boundary → strictly less than → is_return_visit = true.
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        c1 = file_claim(contract, customer, item)
        assess_claim(c1, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "tech-A", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        resolve_claim(c1, 10_000)
        # Second claim — clock at 2026-03-03T09:59:59Z, 1 second before the boundary.
        set_clock("2026-03-03T09:59:59Z")
        c2 = file_claim(contract, customer, item)
        assess_claim(c2, 10_000)
        dispatched = dispatch_claim(c2, "tech-B", "2026-03-03T11:00:00Z")
        # Strict less-than: still inside window → return visit.
        assert dispatched["is_return_visit"] is True
        assert dispatched["service_fee_charged_cents"] == 0


class TestMaxCoveredItemsBoundaryExactCount:
    """count == max permitted; count > max rejected with ERR_ITEM_LIMIT_EXCEEDED.
    PRD §3.3."""

    def test_fourth_registration_against_max_3_is_rejected(self, api):
        """PRD §3.3: "Attempting to register a new covered item that would push
        the contract's total past the package's `max_covered_items` is rejected
        with `ERR_ITEM_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/max_covered_items_boundary_exact_count
        """
        # max=3; register 3 successfully; 4th must be rejected.
        package, customer, contract, _first_item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            code="MINI", max_covered_items=3,
            category="HVAC",
        )
        cust_h = make_customer_headers(customer["id"])
        # Two more registrations to hit count = 3 (the floor, which equals max).
        get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="WATER_HEATER",
                                         brand="B", model="M2"), cust_h))
        get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="REFRIGERATOR",
                                         brand="B", model="M3"), cust_h))
        # Fourth would push count past max=3.
        res = api.create_covered_item(
            create_covered_item_payload(contract["id"], category="DISHWASHER",
                                         brand="B", model="M4"),
            cust_h,
        )
        validate_error(res, "ERR_ITEM_LIMIT_EXCEEDED")

    def test_registration_at_exact_max_count_permitted(self, api):
        """PRD §3.3: "Attempting to register a new covered item that would push
        the contract's total past the package's `max_covered_items` is rejected
        with `ERR_ITEM_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/max_covered_items_boundary_exact_count
        """
        # max=3; the third registration brings count to 3 → must succeed (≤ max).
        package, customer, contract, _first = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            code="MINII", max_covered_items=3,
            category="HVAC",
        )
        cust_h = make_customer_headers(customer["id"])
        get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="DRYER",
                                         brand="B", model="M2"), cust_h))
        # Third registration — count would become 3, which is == max (not past).
        res = api.create_covered_item(
            create_covered_item_payload(contract["id"], category="OVEN",
                                         brand="B", model="M3"),
            cust_h,
        )
        from test_helpers import validate_success
        item3 = validate_success(res, 201)
        assert item3["contract_id"] == contract["id"]
