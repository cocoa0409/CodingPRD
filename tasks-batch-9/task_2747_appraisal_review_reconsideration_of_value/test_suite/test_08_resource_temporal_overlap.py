"""
Resource temporal overlap under two deliberately opposite interval conventions.

An appraiser's inspection windows are half-open and the existing booking is widened by a
ninety-minute travel buffer on both sides, so a single intersection is fatal and the
widened upper edge is exclusive. A management company's dispute review slots are closed at
both ends, unbuffered, and merely counted against a concurrent capacity, so touching
endpoints do overlap and one overlap is still legal. Each convention is driven to the
instant on either side of its boundary.
"""

from test_helpers import (
    ApiErrorId,
    assert_instant,
    CHIEF_APPRAISER_HEADERS,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def _grid(prefix):
    return [
        {
            "street_address": f"1 {prefix}",
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": f"2 {prefix}",
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": f"3 {prefix}",
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def _second_order_against_a_booked_reviewer(api):
    """One reviewer already booked for 09:00 to 12:00 on 2 August, and a second
    field-review order awaiting staffing on the same panel."""
    env = fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Compass Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-8001",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-8001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-8A1",
            "risk_tier": "HIGH",
            "borrower_display_name": "Mira Borrower",
        },
        appraisal={"exhibit_count": 1},
        comparables=_grid("Aspen Street"),
    )
    env["first_order"] = fx.assign_order(
        api, env["order"]["id"], env["reviewer"]["id"],
        "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z",
    )
    assert env["first_order"]["total_cost_cents"] == 45000

    second_loan = fx.create_loan_file(
        api, loan_number="LN-2747-8A2", risk_tier="HIGH",
        borrower_display_name="Noor Borrower",
    )
    second_appraisal = fx.deliver_appraisal(
        api, second_loan["id"], env["appraiser"]["id"], env["amc"]["id"],
        exhibit_count=1,
    )
    fx.add_comparables(
        api, second_appraisal["id"], env["amc"]["id"], _grid("Birch Street"),
    )
    fx.run_rule_checks(api, second_appraisal["id"])
    fx.run_bias_screen(api, second_appraisal["id"])
    second_review = fx.open_desk_review(api, second_appraisal["id"])
    fx.submit_desk_review(
        api, second_review["id"],
        findings_note="Thin exhibit set on a high risk file.",
    )
    fx.decide_desk_review(
        api, second_review["id"], "ESCALATE",
        decision_note="Field review ordered.",
    )
    env["second_loan"] = second_loan
    env["second_appraisal"] = second_appraisal
    env["second_review"] = second_review
    env["second_order"] = fx.escalation_order_for(api, second_review["id"])
    return env


def test_a_window_one_minute_inside_the_buffered_edge_conflicts(api):
    """A 13:29 start conflicts with a 12:00 booking it never actually touches.

    The incoming window sits an hour and a half past the existing booking's raw end, so
    the two bare intervals do not intersect at all. The buffer widens the existing
    booking to a 13:30 upper edge, and a start one minute short of that edge intersects
    the widened interval, which is fatal.

    PRD: "Inspection windows are **half-open** — they run from the start instant
    inclusive to the end instant exclusive — and the **travel buffer of 90 minutes is
    applied to the existing window on both sides, while the incoming window is compared
    bare**."

    Design: Difficulty/resource_temporal_overlap/appraiser_inspection_window_travel_buffer_half_open_exclusive
    """
    env = _second_order_against_a_booked_reviewer(api)

    response = api.assign_escalation_order(
        env["second_order"]["id"],
        f.assign_payload(
            env["reviewer"]["id"], "2026-08-02T13:29:00Z", "2026-08-02T15:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT, 409)


def test_the_conflicted_assignment_charges_nothing_and_holds_the_first_booking(api):
    """The rejected second order stays unpriced and the first booking is undisturbed.

    Only the first assignment ever reached the ledger, so the company's escalation spend
    is still one charge and the reviewer still holds exactly one open assignment with the
    original window intact.

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents` to
    the management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Difficulty/resource_temporal_overlap/appraiser_inspection_window_travel_buffer_half_open_exclusive
    """
    env = _second_order_against_a_booked_reviewer(api)
    api.assign_escalation_order(
        env["second_order"]["id"],
        f.assign_payload(
            env["reviewer"]["id"], "2026-08-02T13:29:00Z", "2026-08-02T15:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )

    second = fx.read_escalation_order(api, env["second_order"]["id"])
    assert second["status"] == "PENDING_ASSIGNMENT"
    assert second["assigned_appraiser_id"] is None
    assert second["inspection_window_start"] is None
    assert second["total_cost_cents"] is None

    first = fx.read_escalation_order(api, env["first_order"]["id"])
    assert first["status"] == "ASSIGNED"
    assert_instant(
        first["inspection_window_start"], "2026-08-02T09:00:00Z", "window start",
    )
    assert_instant(
        first["inspection_window_end"], "2026-08-02T12:00:00Z", "window end",
    )

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 45000

    reviewer = fx.read_appraiser(api, env["reviewer"]["id"])
    assert reviewer["open_assignment_count"] == 1


def test_a_window_starting_exactly_on_the_buffered_edge_is_accepted(api):
    """One minute later, at 13:30 exactly, the same assignment succeeds.

    The widened upper edge is exclusive, so a window beginning exactly ninety minutes
    after the existing booking ends does not intersect it. The assignment prices
    normally, adds its charge to the company's running total and gives the reviewer a
    second open assignment.

    PRD: "Because the upper bound is exclusive, a new window that begins exactly at the
    widened upper edge — exactly 90 minutes after an existing window's end — is
    accepted."

    Design: Difficulty/resource_temporal_overlap/appraiser_inspection_window_travel_buffer_half_open_exclusive
    """
    env = _second_order_against_a_booked_reviewer(api)

    second = fx.assign_order(
        api, env["second_order"]["id"], env["reviewer"]["id"],
        "2026-08-02T13:30:00Z", "2026-08-02T15:00:00Z",
    )
    assert second["status"] == "ASSIGNED"
    assert second["assigned_appraiser_id"] == env["reviewer"]["id"]
    assert second["total_cost_cents"] == 45000

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 90000

    reviewer = fx.read_appraiser(api, env["reviewer"]["id"])
    assert reviewer["open_assignment_count"] == 2


def _company_at_its_dispute_overlap_ceiling(api):
    """A company whose concurrent dispute capacity is two, already carrying two open
    disputes whose slots overlap each other on 5 August."""
    env = fx.graded_report(
        api,
        amc={
            "name": "Narrow Bench Appraisal Management",
            "concurrent_dispute_capacity": 2,
        },
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-8002",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-8B1",
            "borrower_display_name": "Omar Borrower",
        },
        comparables=_grid("Maple Street"),
    )
    env["first_dispute"] = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="COMP_SELECTION",
        slot_start="2026-08-05T10:00:00Z", slot_end="2026-08-05T11:00:00Z",
    )
    env["second_dispute"] = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="ADJUSTMENT_SUPPORT",
        slot_start="2026-08-05T10:30:00Z", slot_end="2026-08-05T11:30:00Z",
    )
    return env


def test_a_slot_touching_an_existing_end_instant_counts_as_an_overlap(api):
    """A slot beginning exactly at 11:00 overlaps the slot that ends at 11:00.

    The third filing genuinely overlaps the 10:30 to 11:30 slot, which alone would be
    permitted. It is the closed upper end of the 10:00 to 11:00 slot that makes the
    touching instant a second overlap, and two overlaps is not strictly fewer than a
    capacity of two.

    PRD: "The interval runs from `review_slot_start` to `review_slot_end` inclusive at
    both ends, so a slot that begins at exactly the instant another slot ends *does*
    overlap it."

    Design: Difficulty/resource_temporal_overlap/amc_dispute_slot_closed_interval_aggregate_capacity
    """
    env = _company_at_its_dispute_overlap_ceiling(api)

    response = api.create_dispute_case(
        f.dispute_payload(
            env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
            "VALUE_OPINION", "2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_SLOT_CAPACITY_EXCEEDED, 409)


def test_the_rejected_filing_leaves_the_open_dispute_tally_alone(api):
    """No third dispute is persisted and the company's open tally stays at two.

    Both existing disputes remain open with their slots untouched, and because filing is
    what moves the tally, a refused filing must leave it exactly where the two successful
    ones put it.

    PRD: "Filing increments the company's `open_dispute_count`."

    Design: Difficulty/resource_temporal_overlap/amc_dispute_slot_closed_interval_aggregate_capacity
    """
    env = _company_at_its_dispute_overlap_ceiling(api)
    api.create_dispute_case(
        f.dispute_payload(
            env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
            "VALUE_OPINION", "2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["open_dispute_count"] == 2

    rows, meta = validate_paginated(
        api.list_dispute_cases(
            CHIEF_APPRAISER_HEADERS, {"amc_id": env["amc"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {"OPEN"}
    assert fx.read_dispute_case(api, env["first_dispute"]["id"])["status"] == "OPEN"
    assert fx.read_dispute_case(api, env["second_dispute"]["id"])["status"] == "OPEN"


def test_a_slot_one_second_past_the_touching_instant_is_accepted(api):
    """Moving the start to 11:00:01 drops one overlap and the filing succeeds.

    The same slot pushed a single second later no longer meets the closed upper end of
    the earliest dispute, so it overlaps only one open case. One is strictly fewer than
    the capacity of two, so the filing is admitted and the tally moves to three.

    PRD: "Count the disputes already held by the same management company whose `status`
    is `OPEN` or `APPRAISER_RESPONDED` and whose slot overlaps the incoming slot under
    those closed-interval rules, and reject the filing with
    `ERR_DISPUTE_SLOT_CAPACITY_EXCEEDED` (HTTP 409) when that count has already reached
    the company's `concurrent_dispute_capacity`; the filing succeeds only while the
    overlap count is strictly less than the capacity."

    Design: Difficulty/resource_temporal_overlap/amc_dispute_slot_closed_interval_aggregate_capacity
    """
    env = _company_at_its_dispute_overlap_ceiling(api)

    third = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="VALUE_OPINION",
        slot_start="2026-08-05T11:00:01Z", slot_end="2026-08-05T12:00:00Z",
    )
    assert third["status"] == "OPEN"
    assert third["dispute_basis"] == "VALUE_OPINION"

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["open_dispute_count"] == 3
