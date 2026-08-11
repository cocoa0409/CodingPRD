"""Work-order scheduling: the four gates and the two capacity geometries."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    fixtures,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _permit_versus_overlap_world():
    """A busy technician, plus a permit-needing work order booked over that window."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Hazelmere Estate", "JUR_BRAVO", "ap@hazelmere.example", "NONE"
    )
    prop = fixtures.new_property(
        account["id"], "12 Hazelmere", "JUR_BRAVO", 11.0, 4, False
    )
    well_1 = fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", 200.0, 8.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", 220.0, 8.0)
    technician = fixtures.new_technician("Bea Sandoval", "JOURNEYMAN", "JUR_BRAVO")
    part = fixtures.new_part(
        "FIL-CARB-20000", "FILTRATION", 20000, on_hand_qty=8, media_kind="CARBON"
    )

    ticket = fixtures.diagnosed_ticket(
        prop["id"], well_1["id"], account["id"], technician["id"], "CONTROL_FAILURE", 20000
    )
    work_order_1 = fixtures.new_work_order(
        prop["id"], well_1["id"], technician["id"], "REPAIR", emergency_ticket_id=ticket["id"]
    )
    fixtures.schedule_work_order(
        work_order_1["id"], "2026-06-03T09:00:00Z", "2026-06-03T11:00:00Z"
    )

    inspection = fixtures.completed_inspection(
        well_2["id"], technician["id"], "2026-06-01T10:00:00Z", 14.0, 44.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        prop["id"], well_2["id"], inspection["id"], part["id"], 1,
        "TREATMENT_INSTALL", 90, "2026-06-03T10:00:00Z", "JOURNEYMAN",
    )
    fixtures.approve_quote(staged["quote_id"], account["id"])
    work_order_2 = fixtures.new_work_order(
        prop["id"], well_2["id"], technician["id"], "TREATMENT_INSTALL",
        quote_id=staged["quote_id"],
    )
    return {"work_order_1_id": work_order_1["id"], "work_order_2_id": work_order_2["id"]}


def test_the_permit_gate_is_answered_before_the_technician_overlap(api):
    """PRD 3.9: "**Scheduling** takes `DRAFT → SCHEDULED`, and it is where four gates land
    in a fixed order. First the regulatory ones."
    PRD 3.9: "The permit prerequisite is satisfied when the scope needs no permit at all,
    **or** a permit whose `work_order_id` is this work order is `APPROVED` or
    `APPROVED_WITH_CONDITIONS`, **or** the pipeline is `EMERGENCY` — emergency work is
    permit-exempt and schedules and completes with no permit whatsoever. Failing all
    three is `ERR_PERMIT_REQUIRED_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_gate_beats_technician_overlap_on_schedule
    """
    world = _permit_versus_overlap_world()
    validate_error(
        api.schedule_work_order(
            world["work_order_2_id"],
            {
                "scheduled_start_at": "2026-06-03T10:00:00Z",
                "scheduled_end_at": "2026-06-03T12:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_PERMIT_REQUIRED_NOT_APPROVED.value,
        422,
    )


def test_the_refused_schedule_leaves_both_work_orders_where_they_were(api):
    """PRD 2.6: "A request that violates several gates is answered with the error of the
    lowest-numbered gate it violates, and no later gate is evaluated."
    PRD 3.9: "Scheduling stores `scheduled_start_at` and `scheduled_end_at`, clears
    `hold_reason` and raises `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_gate_beats_technician_overlap_on_schedule
    """
    world = _permit_versus_overlap_world()
    api.schedule_work_order(
        world["work_order_2_id"],
        {
            "scheduled_start_at": "2026-06-03T10:00:00Z",
            "scheduled_end_at": "2026-06-03T12:00:00Z",
        },
        DISPATCHER,
    )
    blocked = fixtures.get_work_order(world["work_order_2_id"])
    assert blocked["fulfillment_status"] == "DRAFT"
    assert blocked["scheduled_start_at"] is None
    assert (
        fixtures.get_work_order(world["work_order_1_id"])["fulfillment_status"]
        == "SCHEDULED"
    )


def _buffered_window_world():
    """One technician, two wells, one window already booked 09:00 to 11:00."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Twinwell Partners", "JUR_ALPHA", "ap@twinwell.example", "NONE"
    )
    prop = fixtures.new_property(account["id"], "2 Twinwell", "JUR_ALPHA", 10.0, 3, False)
    well_1 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0, 8.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 215.0, 8.0)
    technician = fixtures.new_technician("Pia Moreau", "JOURNEYMAN", "JUR_ALPHA")

    ticket_1 = fixtures.diagnosed_ticket(
        prop["id"], well_1["id"], account["id"], technician["id"], "CONTROL_FAILURE", 20000
    )
    work_order_1 = fixtures.new_work_order(
        prop["id"], well_1["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket_1["id"],
    )
    fixtures.schedule_work_order(
        work_order_1["id"], "2026-06-03T09:00:00Z", "2026-06-03T11:00:00Z"
    )
    ticket_2 = fixtures.diagnosed_ticket(
        prop["id"], well_2["id"], account["id"], technician["id"], "CONTROL_FAILURE", 20000
    )
    work_order_2 = fixtures.new_work_order(
        prop["id"], well_2["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket_2["id"],
    )
    return {"work_order_1_id": work_order_1["id"], "work_order_2_id": work_order_2["id"]}


def test_a_merely_touching_window_still_collides_through_the_travel_buffer(api):
    """PRD 3.9: "The candidate's `scheduled_start_at` is pushed back by
    `TRAVEL_BUFFER_MINUTES` (45) and its `scheduled_end_at` pushed forward by the same 45
    minutes — the buffer expands the **candidate only** — and the buffered window is
    tested against every *other* work order of the same technician whose
    `fulfillment_status` is `SCHEDULED` or `IN_PROGRESS`"
    PRD 3.9: "Because the buffer expands the candidate, two windows that merely touch
    **do** collide: against an existing window of 09:00 to 11:00 on a day, a candidate of
    11:00 to 12:00 conflicts, while a candidate of 11:45 to 12:45 does not, because its
    buffered start lands exactly on 11:00 and the strict comparison fails."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_window_collides_with_a_merely_touching_window
    """
    world = _buffered_window_world()
    validate_error(
        api.schedule_work_order(
            world["work_order_2_id"],
            {
                "scheduled_start_at": "2026-06-03T11:00:00Z",
                "scheduled_end_at": "2026-06-03T12:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT.value,
        409,
    )


def test_a_candidate_whose_buffered_edge_only_meets_the_other_is_accepted(api):
    """PRD 3.9: "The windows collide when the buffered start is strictly before the
    other's end **and** the other's start is strictly before the buffered end; a collision
    is `ERR_TECHNICIAN_SCHEDULE_CONFLICT`."
    PRD 3.9: "Because the buffer expands the candidate, two windows that merely touch
    **do** collide: against an existing window of 09:00 to 11:00 on a day, a candidate of
    11:00 to 12:00 conflicts, while a candidate of 11:45 to 12:45 does not, because its
    buffered start lands exactly on 11:00 and the strict comparison fails."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_window_collides_with_a_merely_touching_window
    """
    world = _buffered_window_world()
    api.schedule_work_order(
        world["work_order_2_id"],
        {
            "scheduled_start_at": "2026-06-03T11:00:00Z",
            "scheduled_end_at": "2026-06-03T12:00:00Z",
        },
        DISPATCHER,
    )
    accepted = validate_success(
        api.schedule_work_order(
            world["work_order_2_id"],
            {
                "scheduled_start_at": "2026-06-03T11:45:00Z",
                "scheduled_end_at": "2026-06-03T12:45:00Z",
            },
            DISPATCHER,
        )
    )
    assert accepted["fulfillment_status"] == "SCHEDULED"
    assert_instant_equals(
        accepted["scheduled_start_at"],
        "2026-06-03T11:45:00Z",
        "WorkOrder.scheduled_start_at",
    )
    assert_instant_equals(
        fixtures.get_work_order(world["work_order_1_id"])["scheduled_end_at"],
        "2026-06-03T11:00:00Z",
        "WorkOrder.scheduled_end_at",
    )


def _daily_cap_world():
    """One well, two technicians, one window already booked on 2026-06-03."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Single Well Coop", "JUR_ALPHA", "ap@singlewell.example", "NONE"
    )
    prop = fixtures.new_property(account["id"], "1 Single Well", "JUR_ALPHA", 10.0, 3, False)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 205.0, 8.0)
    tech_1 = fixtures.new_technician("Ada Kwon", "JOURNEYMAN", "JUR_ALPHA")
    tech_2 = fixtures.new_technician("Ben Sato", "JOURNEYMAN", "JUR_ALPHA")

    ticket_1 = fixtures.diagnosed_ticket(
        prop["id"], well["id"], account["id"], tech_1["id"], "CONTROL_FAILURE", 20000
    )
    work_order_1 = fixtures.new_work_order(
        prop["id"], well["id"], tech_1["id"], "REPAIR", emergency_ticket_id=ticket_1["id"]
    )
    fixtures.schedule_work_order(
        work_order_1["id"], "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z"
    )
    ticket_2 = fixtures.diagnosed_ticket(
        prop["id"], well["id"], account["id"], tech_2["id"], "CONTROL_FAILURE", 20000
    )
    work_order_2 = fixtures.new_work_order(
        prop["id"], well["id"], tech_2["id"], "REPAIR", emergency_ticket_id=ticket_2["id"]
    )
    return {"work_order_1_id": work_order_1["id"], "work_order_2_id": work_order_2["id"]}


def test_the_per_well_daily_cap_buckets_by_calendar_day(api):
    """PRD 3.9: "The candidate's `scheduled_start_at` is reduced to its UTC calendar date,
    and the count is of *other* work orders on the same well, in `SCHEDULED` or
    `IN_PROGRESS`, whose own `scheduled_start_at` falls on that same UTC date. If that
    count is at least `WELL_DAILY_WORK_ORDER_CAP` (1) the request is refused with
    `ERR_WELL_SERVICE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/well_daily_cap_collides_on_calendar_day_bucket_not_on_interval
    """
    world = _daily_cap_world()
    validate_error(
        api.schedule_work_order(
            world["work_order_2_id"],
            {
                "scheduled_start_at": "2026-06-03T20:00:00Z",
                "scheduled_end_at": "2026-06-03T21:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_WELL_SERVICE_WINDOW_CONFLICT.value,
        409,
    )


def test_the_same_duration_on_the_next_calendar_day_is_accepted(api):
    """PRD 2.10: "**The per-well daily cap buckets a work order into the UTC calendar day of
    its start instant only.** Both day boundaries belong to that day: `00:00:00.000Z` and
    `23:59:59.999Z` are the same bucket. A work order that runs across midnight counts
    only against its start date."
    PRD 3.9: "Only the start instant's date matters; a job running across midnight counts
    only against its start date."

    Design: Difficulty/resource_temporal_overlap/well_daily_cap_collides_on_calendar_day_bucket_not_on_interval
    """
    world = _daily_cap_world()
    api.schedule_work_order(
        world["work_order_2_id"],
        {
            "scheduled_start_at": "2026-06-03T20:00:00Z",
            "scheduled_end_at": "2026-06-03T21:00:00Z",
        },
        DISPATCHER,
    )
    accepted = validate_success(
        api.schedule_work_order(
            world["work_order_2_id"],
            {
                "scheduled_start_at": "2026-06-04T20:00:00Z",
                "scheduled_end_at": "2026-06-04T21:00:00Z",
            },
            DISPATCHER,
        )
    )
    assert accepted["fulfillment_status"] == "SCHEDULED"
    assert_instant_equals(
        accepted["scheduled_start_at"],
        "2026-06-04T20:00:00Z",
        "WorkOrder.scheduled_start_at",
    )
    assert_instant_equals(
        fixtures.get_work_order(world["work_order_1_id"])["scheduled_start_at"],
        "2026-06-03T09:00:00Z",
        "WorkOrder.scheduled_start_at",
    )


def test_the_technician_tier_gate_is_set_membership_not_an_ordering(api):
    """PRD 3.9: "Then the assigned technician's `tier` must satisfy the scope table below,
    failing which is `ERR_TECHNICIAN_TIER_INSUFFICIENT`"
    PRD 3.9: "| `TREATMENT_INSTALL` | `JOURNEYMAN` or `MASTER` |"
    PRD 3.9: "| `PUMP_REPLACEMENT` | `MASTER` only |"

    Design: Corner/validations/corner_validation_technician_tier_set_membership_journeyman_boundary
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Tier Gate Co", "JUR_ALPHA", "tg@corner.example")
    prop = fixtures.new_property(account["id"], "2 Tier", "JUR_ALPHA", 10.0, 3)
    well_t = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_p = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    technician = fixtures.new_technician("Journeyman Only", "JOURNEYMAN", "JUR_ALPHA")

    ticket_t = fixtures.diagnosed_ticket(
        prop["id"], well_t["id"], account["id"], technician["id"], "TREATMENT_FAILURE", 20000
    )
    ticket_p = fixtures.diagnosed_ticket(
        prop["id"], well_p["id"], account["id"], technician["id"], "PUMP_FAILURE", 20000
    )
    work_order_t = fixtures.new_work_order(
        prop["id"], well_t["id"], technician["id"], "TREATMENT_INSTALL",
        emergency_ticket_id=ticket_t["id"],
    )
    work_order_p = fixtures.new_work_order(
        prop["id"], well_p["id"], technician["id"], "PUMP_REPLACEMENT",
        emergency_ticket_id=ticket_p["id"],
    )

    scheduled = validate_success(
        api.schedule_work_order(
            work_order_t["id"],
            {
                "scheduled_start_at": "2026-06-03T08:00:00Z",
                "scheduled_end_at": "2026-06-03T10:00:00Z",
            },
            DISPATCHER,
        )
    )
    assert scheduled["fulfillment_status"] == "SCHEDULED"
    assert scheduled["pipeline"] == "EMERGENCY"

    validate_error(
        api.schedule_work_order(
            work_order_p["id"],
            {
                "scheduled_start_at": "2026-06-04T08:00:00Z",
                "scheduled_end_at": "2026-06-04T10:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_TECHNICIAN_TIER_INSUFFICIENT.value,
        403,
    )
    blocked = fixtures.get_work_order(work_order_p["id"])
    assert blocked["fulfillment_status"] == "DRAFT"
    assert blocked["scheduled_start_at"] is None


def test_an_apprentice_is_refused_a_pump_replacement_even_when_permit_exempt(api):
    """PRD 3.9: "Then the assigned technician's `tier` must satisfy the scope table below,
    failing which is `ERR_TECHNICIAN_TIER_INSUFFICIENT`"
    PRD 3.9: "The permit prerequisite is satisfied when the scope needs no permit at all,
    **or** a permit whose `work_order_id` is this work order is `APPROVED` or
    `APPROVED_WITH_CONDITIONS`, **or** the pipeline is `EMERGENCY` — emergency work is
    permit-exempt and schedules and completes with no permit whatsoever."

    Design: Corner/errors/corner_technician_tier_insufficient_on_emergency_schedule
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Tier Co",
        email="ti@corner.example",
        address_line="6 Tier",
        technician_tier="APPRENTICE",
        technician_name="Tier Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        20000,
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"],
        "PUMP_REPLACEMENT", emergency_ticket_id=ticket["id"],
    )
    validate_error(
        api.schedule_work_order(
            work_order["id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T14:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_TECHNICIAN_TIER_INSUFFICIENT.value,
        403,
    )
    assert fixtures.get_work_order(work_order["id"])["fulfillment_status"] == "DRAFT"


def test_a_zero_length_scheduled_window_is_a_payload_failure(api):
    """PRD 3.9: "`scheduled_end_at` must be strictly after `scheduled_start_at`, failing
    which is `ERR_INVALID_DATE_RANGE` at the payload gate."
    PRD 2.7: "`ERR_INVALID_DATE_RANGE` (HTTP 400) is raised on exactly two endpoints. On
    work-order scheduling it fires when `scheduled_end_at` is not strictly after
    `scheduled_start_at`."

    Design: Corner/validations/corner_validation_schedule_window_end_must_be_strictly_after_start
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Window Range Co",
        email="wr@corner.example",
        address_line="0 Window",
        technician_tier="MASTER",
        technician_name="Window Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        20000,
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    validate_error(
        api.schedule_work_order(
            work_order["id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T12:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE.value,
        400,
    )
    scheduled = validate_success(
        api.schedule_work_order(
            work_order["id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T12:01:00Z",
            },
            DISPATCHER,
        )
    )
    assert scheduled["fulfillment_status"] == "SCHEDULED"
    assert_instant_equals(
        scheduled["scheduled_start_at"],
        "2026-06-03T12:00:00Z",
        "WorkOrder.scheduled_start_at",
    )
    assert_instant_equals(
        scheduled["scheduled_end_at"],
        "2026-06-03T12:01:00Z",
        "WorkOrder.scheduled_end_at",
    )
