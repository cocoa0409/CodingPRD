"""Two overlap rules with deliberately opposite conventions.

Crew windows are half-open and buffered on one side only, so a job packed immediately
before another commitment is legal while one packed immediately after it is not.
Service-bay windows are closed, so two jobs that merely touch at an endpoint collide.
"""

from __future__ import annotations

from test_helpers import (
    DeliveryOrderStatus,
    ErrorId,
    IssueCode,
    TicketStatus,
    UnitStatus,
    as_instant,
    assert_fields,
    assert_ordered_by,
    assert_total_count,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    page,
    sign_on,
)
from test_helpers.test_users import MANAGER, TECHNICIAN

EXISTING_START = "2026-08-05T09:00:00Z"
EXISTING_END = "2026-08-05T11:00:00Z"
INSIDE_THE_BUFFER_START = "2026-08-05T11:30:00Z"
AT_THE_BUFFER_EDGE_START = "2026-08-05T11:45:00Z"
AFTERNOON_END = "2026-08-05T13:00:00Z"
EARLY_START = "2026-08-05T07:00:00Z"
EARLY_END = "2026-08-05T09:00:00Z"

BAY_START = "2026-08-03T09:00:00Z"
BAY_END = "2026-08-03T11:00:00Z"
TOUCHING_START = "2026-08-03T11:00:00Z"
ONE_SECOND_CLEAR_START = "2026-08-03T11:00:01Z"
BAY_AFTERNOON_END = "2026-08-03T13:00:00Z"


def _one_crew_with_a_mid_morning_commitment(world):
    """Three signed agreements, one crew, and a nine-to-eleven job already on the books."""
    scenario = build_tx_floor(
        world, serials=("SN-TX-0001", "SN-TX-0002", "SN-TX-0003")
    )
    first = sign_on(scenario, unit_index=0).agreement
    second = world.sign(scenario.customer_id, scenario.units[1]["id"])
    third = world.sign(scenario.customer_id, scenario.units[2]["id"])

    existing = world.schedule_delivery(
        first["id"], scenario.crew_id, EXISTING_START, EXISTING_END
    )
    return scenario, second, third, existing


def test_the_buffer_extends_only_the_existing_orders_tail(world):
    """Thirty minutes after the tail is inside the buffer; forty-five minutes is clear.

    PRD: The buffer extends only the **existing** order's tail and never the candidate's head, with two consequences worth internalizing: a candidate starting exactly 45 minutes after an existing window's end is accepted, and a candidate ending exactly at an existing window's start is also accepted, so packing a job immediately before another crew commitment is legal while packing one immediately after it is not.

    Design: Difficulty/resource_temporal_overlap/crew_window_buffer_is_half_open_and_asymmetric
    """
    scenario, second, _third, _existing = _one_crew_with_a_mid_morning_commitment(world)
    second_v1 = second["version"]

    response = scenario.api.create_delivery_order(
        second["id"],
        factories.delivery_order_payload(
            scenario.crew_id, second_v1, INSIDE_THE_BUFFER_START, AFTERNOON_END
        ),
        MANAGER,
    )
    failure(response, ErrorId.CREW_WINDOW_CONFLICT)
    assert world.delivery_orders(agreement_id=second["id"]) == [], (
        "a refused schedule must not leave an order behind"
    )

    # The rejection wrote nothing, so the version captured at signing is still current.
    accepted = world.schedule_delivery(
        second["id"],
        scenario.crew_id,
        AT_THE_BUFFER_EDGE_START,
        AFTERNOON_END,
        expected_agreement_version=second_v1,
    )
    assert_fields(
        accepted,
        crew_id=scenario.crew_id,
        window_start_at=AT_THE_BUFFER_EDGE_START,
        window_end_at=AFTERNOON_END,
        status=DeliveryOrderStatus.SCHEDULED,
        attempt_count=0,
    )


def test_a_job_ending_exactly_when_the_next_one_starts_is_accepted(world):
    """The candidate's head is never buffered, so packing in just before is legal.

    PRD: A candidate window conflicts with an existing order when that order belongs to the same crew, belongs to a **different** agreement — the agreement's own prior order has already been superseded by this very create and therefore cannot block its own replacement — is still `SCHEDULED`, and both of the following hold: the candidate starts strictly before the existing order's `window_end_at` extended by 45 minutes of travel time, and the candidate ends strictly after the existing order's `window_start_at`.

    Design: Difficulty/resource_temporal_overlap/crew_window_buffer_is_half_open_and_asymmetric
    """
    scenario, second, third, _existing = _one_crew_with_a_mid_morning_commitment(world)

    world.schedule_delivery(
        second["id"],
        scenario.crew_id,
        AT_THE_BUFFER_EDGE_START,
        AFTERNOON_END,
        expected_agreement_version=second["version"],
    )
    early = world.schedule_delivery(
        third["id"], scenario.crew_id, EARLY_START, EARLY_END
    )
    assert_fields(
        early,
        window_start_at=EARLY_START,
        window_end_at=EARLY_END,
        status=DeliveryOrderStatus.SCHEDULED,
    )

    rows, _meta = page(
        scenario.api.list_delivery_orders(
            MANAGER,
            {"crew_id": scenario.crew_id, "status": DeliveryOrderStatus.SCHEDULED},
        )
    )
    assert len(rows) == 3, f"expected three booked windows on the crew, got {len(rows)}"
    assert_ordered_by(rows, "window_start_at")
    assert [as_instant(row["window_start_at"]) for row in rows] == [
        as_instant(EARLY_START),
        as_instant(EXISTING_START),
        as_instant(AT_THE_BUFFER_EDGE_START),
    ]

    for index in range(3):
        assert scenario.read_unit(index)["status"] == UnitStatus.RESERVED
    assert scenario.read_store()["units_on_rent_count"] == 0


def _one_bay_with_a_mid_morning_ticket(world):
    """A single-bay store whose only bay is booked from nine to eleven."""
    scenario = deliver_on(sign_on(build_tx_floor(world, service_bay_capacity=1)))
    ticket = world.open_ticket(
        scenario.agreement_id, IssueCode.MECHANICAL, BAY_START, BAY_END
    )
    return scenario, ticket


def test_two_bay_windows_that_touch_at_an_endpoint_collide(world):
    """Bay intervals are closed, so a window starting exactly at eleven is a collision.

    PRD: Then the requested window is counted against the store's other live tickets — those in `SCHEDULED` or `SWAP_ISSUED` status — using **closed** intervals: two windows collide when the new window starts at or before an existing window's end **and** ends at or after that window's start, so windows that merely touch at an endpoint do collide.

    Design: Difficulty/resource_temporal_overlap/service_bay_capacity_uses_closed_intervals_so_touching_windows_collide
    """
    scenario, _ticket = _one_bay_with_a_mid_morning_ticket(world)
    assert_fields(
        scenario.read_store(), units_in_service_count=0, service_intake_open=True
    )

    response = scenario.api.create_service_ticket(
        scenario.agreement_id,
        factories.service_ticket_payload(
            IssueCode.ELECTRICAL, TOUCHING_START, BAY_AFTERNOON_END
        ),
        TECHNICIAN,
    )
    failure(response, ErrorId.SERVICE_CAPACITY_EXCEEDED)

    tickets = world.tickets(agreement_id=scenario.agreement_id)
    assert len(tickets) == 1, (
        f"the colliding ticket must not have been written, got {len(tickets)}"
    )


def test_a_bay_window_one_second_clear_of_the_endpoint_is_accepted(world):
    """One second past the existing tail the intervals no longer touch.

    PRD: The number of colliding tickets must be strictly below `service_bay_capacity`, or the request fails with `ERR_SERVICE_CAPACITY_EXCEEDED`.

    Design: Difficulty/resource_temporal_overlap/service_bay_capacity_uses_closed_intervals_so_touching_windows_collide
    """
    scenario, _ticket = _one_bay_with_a_mid_morning_ticket(world)
    failure(
        scenario.api.create_service_ticket(
            scenario.agreement_id,
            factories.service_ticket_payload(
                IssueCode.ELECTRICAL, TOUCHING_START, BAY_AFTERNOON_END
            ),
            TECHNICIAN,
        ),
        ErrorId.SERVICE_CAPACITY_EXCEEDED,
    )

    accepted = world.open_ticket(
        scenario.agreement_id,
        IssueCode.ELECTRICAL,
        ONE_SECOND_CLEAR_START,
        BAY_AFTERNOON_END,
    )
    assert_fields(
        accepted,
        status=TicketStatus.SCHEDULED,
        window_start_at=ONE_SECOND_CLEAR_START,
        window_end_at=BAY_AFTERNOON_END,
    )

    rows = assert_total_count(
        scenario.api.list_service_tickets(
            MANAGER,
            {"store_id": scenario.store_id, "status": TicketStatus.SCHEDULED},
        ),
        2,
    )
    assert_ordered_by(rows, "window_start_at")
    assert_fields(
        scenario.read_store(), units_in_service_count=0, units_on_rent_count=1
    )
