"""Seeded history in one call, and the row that takes over from a failed one."""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
    assert_cents,
    make_club_headers,
)
from test_helpers.factories import history_entry
from test_helpers.fixtures import (
    approve,
    assign,
    credits_for_event,
    declare_no_show,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    set_clock,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    AssignmentStatus,
    CreditReason,
    DayPart,
    ProductCategory,
    StaffingStatus,
)


def _decimal2(value):
    """Coerce a two-decimal API value into an exact Decimal for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_a_two_entry_history_seed_lands_both_rows_and_scores_once(api):
    """PRD §2.5: "It takes a `demonstrator_id`, a `demo_event_id` to hang the rows from, and an `entries` array whose members each supply `scheduled_start_utc`, `scheduled_end_utc`, `assignment_status` and `role`, optionally with `check_in_at` and `check_out_at`."

    PRD §2.5: "One assignment row is inserted per entry with the supplied status, and `hours_worked`, `billable_hours` and `late_check_in` are computed from the supplied stamps."

    PRD §3.4: "The raw score starts at 100, subtracts 12 points for each no-show, subtracts a further 4 points for each late completion, and adds half a point for each completion."

    PRD §3.4: "`completed_event_count` is likewise a plain counter: the number of the worker's assignments in `COMPLETED`, with no time filter of any kind."

    Design: Corner/endpoints/injecting_two_history_entries_creates_both_rows_in_one_call
    """
    vendor = new_manufacturer(api, legal_name="Ockridge Supply", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6035",
        name="Ockridge Club 6035",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="OS-DST-035",
        name="Duster Kit",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1000,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    worker = new_demonstrator(
        api, club["id"], full_name="Pia Rennick", hourly_rate_cents=2200
    )
    assert worker["completed_event_count"] == 0

    host_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-10-12",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )

    seeded = validate_success(
        api.inject_assignment_history(
            {
                "demonstrator_id": worker["id"],
                "demo_event_id": host_event["id"],
                "entries": [
                    history_entry(
                        "2026-07-06T08:15:00Z",
                        "2026-07-06T14:15:00Z",
                        AssignmentStatus.COMPLETED,
                        AssignmentRole.SUPPORT,
                        check_in_at="2026-07-06T08:15:00Z",
                        check_out_at="2026-07-06T13:15:00Z",
                    ),
                    history_entry(
                        "2026-07-13T08:15:00Z",
                        "2026-07-13T14:15:00Z",
                        AssignmentStatus.COMPLETED,
                        AssignmentRole.SUPPORT,
                        check_in_at="2026-07-13T08:15:00Z",
                        check_out_at="2026-07-13T13:15:00Z",
                    ),
                ],
            },
            ADMIN_HQ_HEADERS,
        ),
        201,
    )

    assert len(seeded) == 2
    assert seeded[0]["assignment_status"] == AssignmentStatus.COMPLETED
    assert seeded[1]["assignment_status"] == AssignmentStatus.COMPLETED
    assert seeded[1]["scheduled_start_utc"].startswith("2026-07-13T08:15")

    scored = validate_success(api.get_demonstrator(worker["id"], STAFF_OPS_HEADERS))
    assert scored["completed_event_count"] == 2
    assert _decimal2(scored["reliability_score_rolling_90"]) == Decimal("100.00")
    assert _decimal2(scored["reliability_score_program_to_date"]) == Decimal("100.00")
    assert scored["no_show_strike_count"] == 0

    rows, meta = validate_paginated(
        api.list_assignments(STAFF_OPS_HEADERS, {"demonstrator_id": worker["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_a_recovery_row_names_the_failed_row_it_takes_over_from(api):
    """PRD §3.4: "Recovery itself is an ordinary assignment insert that names the failed row in `replaces_assignment_id`, pointing at the `NO_SHOW` or `RELEASED` assignment the new row takes over from; an original assignment leaves that field unset."

    PRD §3.4: "Because the failed row is no longer in the held set, the single-lead rule does not stand in the way of appointing a replacement lead, and once the replacement lands the coverage recomputation restores `FULLY_STAFFED` and clears `no_show_recovery_open` to false."

    PRD §3.6: "Alongside those four hops, the no-show downgrades *this* event's `staffing_status` and sets its `no_show_recovery_open` to true, creates one cancellation credit on this event with `credit_reason` `DEMONSTRATOR_NO_SHOW` and `credit_status` `PENDING_APPROVAL`, valued by the arithmetic of §3.9, and increments the assignment's `version` by 1."

    PRD §3.9: "`credit_amount_cents` is the smaller of `billable_base_cents` and the product of `billable_base_cents`, `notice_tier_pct` and `reason_multiplier` rounded half-up to whole cents."

    Design: Corner/endpoints/replacement_assignment_links_back_to_the_no_show_it_recovers
    """
    vendor = new_manufacturer(api, legal_name="Pentreath Goods", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6036",
        name="Pentreath Club 6036",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="PG-BRS-036",
        name="Bristle Brush",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=900,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    first_worker = new_demonstrator(
        api, club["id"], full_name="Quill Marsden", hourly_rate_cents=2300
    )
    second_worker = new_demonstrator(
        api, club["id"], full_name="Rosa Idowu", hourly_rate_cents=2400
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])

    failed_assignment = assign(
        api, event["id"], first_worker["id"], AssignmentRole.LEAD
    )
    set_clock(api, "2026-09-14T08:31:00Z")
    no_show = declare_no_show(
        api, failed_assignment["id"], note="did not report to the club"
    )
    assert no_show["assignment_status"] == AssignmentStatus.NO_SHOW

    club_headers = make_club_headers(club["id"])
    open_for_recovery = validate_success(api.get_demo_event(event["id"], club_headers))
    assert open_for_recovery["staffing_status"] == StaffingStatus.UNSTAFFED
    assert open_for_recovery["no_show_recovery_open"] is True

    replacement = validate_success(
        api.create_assignment(
            event["id"],
            {
                "demonstrator_id": second_worker["id"],
                "role": AssignmentRole.LEAD,
                "replaces_assignment_id": failed_assignment["id"],
            },
            STAFF_OPS_HEADERS,
        ),
        201,
    )
    assert replacement["assignment_status"] == AssignmentStatus.ASSIGNED
    assert replacement["replaces_assignment_id"] == failed_assignment["id"]

    linked, meta = validate_paginated(
        api.list_assignments(
            STAFF_OPS_HEADERS, {"replaces_assignment_id": failed_assignment["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(linked) == 1
    assert linked[0]["id"] == replacement["id"]

    recovered = validate_success(api.get_demo_event(event["id"], club_headers))
    assert recovered["staffing_status"] == StaffingStatus.FULLY_STAFFED
    assert recovered["no_show_recovery_open"] is False

    struck = validate_success(
        api.get_demonstrator(first_worker["id"], STAFF_OPS_HEADERS)
    )
    assert struck["no_show_strike_count"] == 1

    credits = credits_for_event(api, event["id"])
    assert len(credits) == 1
    credit = credits[0]
    assert credit["credit_reason"] == CreditReason.DEMONSTRATOR_NO_SHOW
    assert credit["notice_hours"] == 0
    assert _decimal2(credit["notice_tier_pct"]) == Decimal("0.70")
    assert _decimal2(credit["reason_multiplier"]) == Decimal("1.00")
    assert_cents(credit["credit_amount_cents"], 19600, "credit_amount_cents")
