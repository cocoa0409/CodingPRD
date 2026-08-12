"""Moving the passport book: single-token custody, hop ordering and the attempt cap."""

from test_helpers import (
    ApiErrorId,
    add_closure,
    assert_custody_event,
    assert_custody_events_ordered,
    assert_single_open_custody,
    build_scenario,
    complete_leg,
    dispatch_leg,
    list_custody_events,
    new_applicant,
    new_catalog_item,
    new_consulate,
    new_leg,
    new_order,
    order_summary,
    read_applicant,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COURIER


# ==========================================================================
# The order's readiness gate depends on where the book physically is
# ==========================================================================
def _intake_order_with_a_dispatched_first_hop():
    """A single-applicant order at INTAKE whose traveller is already COMPLETE, with
    hop 1 (APPLICANT -> SERVICE) dispatched but not yet completed."""
    scenario = build_scenario("intake", require_passport_doc=True, visa_type="TOURIST")
    leg = new_leg(
        scenario["order_id"],
        leg_index=1,
        from_holder="APPLICANT",
        to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    dispatch_leg(leg["id"])
    scenario["leg1"] = leg
    return scenario


def test_order_stays_in_intake_while_the_book_is_with_the_courier(api):
    """PRD §3.9: "The order's move `INTAKE → READY_FOR_SUBMISSION` is a system transition,
    not a request: it fires the moment the last qualifying readiness mutation lands — a
    document review, a photo check, a form preparation or signature, an appointment
    outcome, or a courier hop completing — and it requires that every traveller of the
    order whose `readiness_status` is `PENDING` or `COMPLETE` is `COMPLETE`, and that the
    order's `custody_holder` is `SERVICE`."
    PRD §3.8: "Dispatch increments `attempt_count`, closes the open custody event by
    stamping its `released_at`, and appends a custody event with `holder_type` `COURIER`
    and `leg_index` set to this leg's index, driving the order's `custody_holder` to
    `COURIER`."

    Design: Difficulty/cross_entity_state_dependency/order_readiness_depends_on_courier_custody_position
    """
    scenario = _intake_order_with_a_dispatched_first_hop()
    applicant_id = scenario["applicant_ids"][0]

    before = read_order(scenario["order_id"])
    assert before["workflow_status"] == "INTAKE", (
        "the traveller is COMPLETE, so only the custody position holds the order back"
    )
    assert before["custody_holder"] == "COURIER"
    assert read_applicant(applicant_id)["readiness_status"] == "COMPLETE"


def test_delivering_the_book_to_service_advances_the_order_without_touching_the_traveller(api):
    """PRD §3.8: "Arriving at `SERVICE` re-evaluates every traveller's readiness and the
    order's `INTAKE → READY_FOR_SUBMISSION` gate, and — when the order's `payment_status`
    is `REFUND_PENDING` — disburses the scheduled refund as described in §3.11."
    PRD §3.9: "It raises `furthest_stage_reached` to `READY_FOR_SUBMISSION` and re-runs the
    projection and feasibility verdict."
    PRD §2.11: "For every order, exactly **one** `CustodyEvent` row has `released_at` null;
    that single open row's `holder_type` equals the order's `custody_holder`; and no two
    custody events of the same order have overlapping intervals, where an interval runs
    from `acquired_at` inclusive to `released_at` exclusive."

    Design: Difficulty/cross_entity_state_dependency/order_readiness_depends_on_courier_custody_position
    """
    scenario = _intake_order_with_a_dispatched_first_hop()
    applicant_id = scenario["applicant_ids"][0]

    delivered = validate_success(
        api.complete_courier_leg(scenario["leg1"]["id"], {"outcome": "DELIVERED"}, COURIER)
    )
    assert delivered["leg_status"] == "DELIVERED"

    after = read_order(scenario["order_id"])
    assert after["custody_holder"] == "SERVICE"
    assert after["workflow_status"] == "READY_FOR_SUBMISSION"
    assert after["furthest_stage_reached"] == "READY_FOR_SUBMISSION"
    assert read_applicant(applicant_id)["readiness_status"] == "COMPLETE", (
        "the traveller was COMPLETE before and after; nothing applicant-side changed"
    )

    events = list_custody_events(scenario["order_id"])
    assert len(events) == 3, f"created, dispatched, delivered — expected 3, got {len(events)}"
    assert_single_open_custody(events, "SERVICE")


# ==========================================================================
# Strict single-occupancy: dispatching from a party that does not hold the book
# ==========================================================================
def _service_holds_the_book_with_a_second_hop_created():
    """Hop 1 has delivered the book to SERVICE. Hop 2 is declared to leave APPLICANT,
    a party that no longer holds the book."""
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    new_applicant(order["id"], full_name="Custody Excl")
    first = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    dispatch_leg(first["id"])
    complete_leg(first["id"], "DELIVERED")
    second = new_leg(
        order["id"], leg_index=2, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-02",
    )
    return order, first, second


def test_dispatch_from_a_holder_that_does_not_hold_the_book_is_a_custody_mismatch(api):
    """PRD §3.8: "Three conditions guard it, in ladder order after the generic ones: the
    order's `custody_holder` must equal the leg's `from_holder`, or the request is
    `ERR_CUSTODY_MISMATCH`; the leg must carry the **lowest** `leg_index` among the order's
    legs whose `leg_status` is `CREATED` or `FAILED`, or the request is
    `ERR_LEG_SEQUENCE_VIOLATION`; and the leg's `scheduled_date` must be a business day
    that does not appear in the order consulate's `closure_dates`, or the request is
    `ERR_EMBASSY_CLOSED`."
    PRD §2.9.4: "`ERR_CUSTODY_MISMATCH` (HTTP 409) is checked on exactly four operations,
    each with its own required holder: on **courier-leg dispatch**, the leg's `from_holder`
    must equal the order's `custody_holder`; on **shipment creation**, `custody_holder` must
    be `SERVICE`; on the **first delivery attempt** of a shipment, `custody_holder` must be
    `SERVICE`; on **tender**, `custody_holder` must be `AGENCY`."

    Design: Difficulty/resource_temporal_overlap/custody_interval_single_occupancy_rejects_out_of_position_dispatch
    """
    order, _first, second = _service_holds_the_book_with_a_second_hop_created()

    resp = api.dispatch_courier_leg(second["id"], COURIER)
    validate_error(resp, ApiErrorId.ERR_CUSTODY_MISMATCH.value)

    legs = {leg["id"]: leg for leg in validate_paginated(
        api.list_courier_legs(order["id"], COURIER)
    )[0]}
    assert legs[second["id"]]["leg_status"] == "CREATED"
    assert legs[second["id"]]["attempt_count"] == 0, "a refused dispatch consumes no attempt"


def test_a_refused_dispatch_leaves_exactly_one_open_custody_interval(api):
    """PRD §2.7: "The passport book is a single physical token. At every instant, exactly
    one party holds it, and `Order.custody_holder` names that party: `APPLICANT`,
    `SERVICE`, `COURIER` or `AGENCY`."
    PRD §2.7: "Every handover is recorded as an append-only `CustodyEvent` carrying
    `order_id`, `holder_type`, an `acquired_at` instant, a `released_at` instant that is
    null for exactly one row per order, a `leg_index` that is populated only while a
    numbered courier leg is in flight and null otherwise, and a `reason` drawn from
    `ORDER_CREATED`, `LEG_DISPATCHED`, `LEG_DELIVERED`, `LEG_FAILED_RETURN`,
    `DECISION_RETURNED`, `SHIPMENT_DELIVERED`, `SHIPMENT_PICKED_UP`."

    Design: Difficulty/resource_temporal_overlap/custody_interval_single_occupancy_rejects_out_of_position_dispatch
    """
    order, _first, second = _service_holds_the_book_with_a_second_hop_created()

    resp = api.dispatch_courier_leg(second["id"], COURIER)
    validate_error(resp, ApiErrorId.ERR_CUSTODY_MISMATCH.value)

    assert read_order(order["id"])["custody_holder"] == "SERVICE"
    events = list_custody_events(order["id"])
    assert len(events) == 3, f"expected 3 custody rows, got {len(events)}"
    assert_single_open_custody(events, "SERVICE")


# ==========================================================================
# The compensating FAILED completion conserves custody cardinality
# ==========================================================================
def _failed_then_redispatched_hop():
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    new_applicant(order["id"], full_name="Custody Conserve")
    leg = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    dispatch_leg(leg["id"])
    return order, leg


def test_failed_completion_hands_the_book_back_to_the_sender(api):
    """PRD §3.8: "On `FAILED` the hop moves `DISPATCHED → FAILED`, the open custody event
    is closed and a new one is appended with `holder_type` equal to the leg's `from_holder`
    and `reason` `LEG_FAILED_RETURN`: the book goes back to whoever sent it."

    Design: Difficulty/compensating_invariant/failed_courier_leg_preserves_single_custody_occupancy
    """
    order, leg = _failed_then_redispatched_hop()

    failed = validate_success(
        api.complete_courier_leg(leg["id"], {"outcome": "FAILED"}, COURIER)
    )
    assert failed["leg_status"] == "FAILED"
    assert read_order(order["id"])["custody_holder"] == "APPLICANT"

    events = list_custody_events(order["id"])
    assert len(events) == 3
    assert_single_open_custody(events, "APPLICANT")
    assert events[-1]["reason"] == "LEG_FAILED_RETURN"


def test_a_failed_then_delivered_round_trip_never_holds_the_book_twice(api):
    """PRD §3.8: "A failed hop may be re-dispatched, moving `FAILED → DISPATCHED` and
    incrementing `attempt_count` again, subject to the same custody, sequence and calendar
    checks."
    PRD §2.11: "The computed summary reports `open_custody_count` (which must be 1) and
    `open_custody_holder`."

    Design: Difficulty/compensating_invariant/failed_courier_leg_preserves_single_custody_occupancy
    """
    order, leg = _failed_then_redispatched_hop()

    complete_leg(leg["id"], "FAILED")
    dispatch_leg(leg["id"])
    delivered = complete_leg(leg["id"], "DELIVERED")

    assert delivered["attempt_count"] == 2, (
        f"the first dispatch and the re-dispatch, got {delivered['attempt_count']}"
    )
    assert delivered["leg_status"] == "DELIVERED"
    assert read_order(order["id"])["custody_holder"] == "SERVICE"

    events = list_custody_events(order["id"])
    assert len(events) == 5, f"expected 5 custody rows across the round trip, got {len(events)}"
    assert_single_open_custody(events, "SERVICE")

    summary = order_summary(order["id"])
    assert summary["open_custody_count"] == 1
    assert summary["open_custody_holder"] == "SERVICE"


# ==========================================================================
# The append-only chain, hop ordering, closures and the attempt cap
# ==========================================================================
def test_custody_chain_is_append_only_and_ordered_by_acquisition(api):
    """PRD §2.4: "Four entities are **append-only records** and deliberately carry neither
    `updated_at` nor `version`: `DocumentRequirement`, `CustodyEvent`, `LedgerEntry` and
    `SlaSegment`. Rows of these four types expose only `id` and `created_at` alongside
    their own attributes."
    PRD §2.3: "An order's custody events are returned sorted by `acquired_at` ascending,
    tie-broken by `created_at` ascending and then `id` ascending."

    Design: Corner/entities/corner_custody_event_is_immutable_and_carries_no_version
    """
    set_clock("2026-06-01T09:00:00Z")
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    leg = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    # Each handover lands on its own logical instant so the acquired_at ordering
    # is decided by the clock rather than by the id tie-break.
    set_clock("2026-06-01T10:00:00Z")
    dispatch_leg(leg["id"])
    set_clock("2026-06-01T11:00:00Z")
    complete_leg(leg["id"], "DELIVERED")

    rows, meta = validate_paginated(api.list_custody_events(order["id"], COURIER))
    assert meta["total_count"] == 3, f"one row per handover, got {meta['total_count']}"
    assert_custody_events_ordered(rows)
    for row in rows:
        assert_custody_event(row)
        assert "version" not in row, "an append-only row exposes no version field"

    assert rows[0]["holder_type"] == "APPLICANT"
    assert rows[0]["released_at"] is not None
    assert rows[1]["holder_type"] == "COURIER"
    assert rows[1]["leg_index"] == 1
    assert rows[1]["released_at"] is not None
    assert rows[2]["holder_type"] == "SERVICE"
    assert rows[2]["released_at"] is None


def test_dispatching_out_of_leg_index_order_is_refused(api):
    """PRD §3.8: "the leg must carry the **lowest** `leg_index` among the order's legs
    whose `leg_status` is `CREATED` or `FAILED`, or the request is
    `ERR_LEG_SEQUENCE_VIOLATION`"
    PRD §2.9.3: "- Rung 15 (`ERR_LEG_SEQUENCE_VIOLATION`) and rung 25
    (`ERR_COURIER_ATTEMPT_CAP_EXCEEDED`) guard **dispatch** only, never completion. A leg
    may be completed regardless of ordering or attempt count once it is `DISPATCHED`."

    Design: Corner/errors/corner_error_leg_sequence_violation
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    first = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    second = new_leg(
        order["id"], leg_index=2, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-02",
    )

    resp = api.dispatch_courier_leg(second["id"], COURIER)
    validate_error(resp, ApiErrorId.ERR_LEG_SEQUENCE_VIOLATION.value)

    legs = {leg["id"]: leg for leg in validate_paginated(
        api.list_courier_legs(order["id"], COURIER)
    )[0]}
    assert legs[second["id"]]["leg_status"] == "CREATED"
    assert legs[first["id"]]["leg_status"] == "CREATED"
    assert read_order(order["id"])["custody_holder"] == "APPLICANT"


def test_dispatch_onto_a_mission_closure_date_is_refused(api):
    """PRD §2.9.5: "On **courier-leg dispatch**, the leg's `scheduled_date` must be a
    business day and must not appear in the order consulate's `closure_dates`."
    PRD §3.3: "Closure also blocks courier dispatch, because a dispatch date must be a
    business day at the order's consulate."

    Design: Corner/errors/corner_error_embassy_closed_blocks_dispatch
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    consulate = new_consulate()
    add_closure(consulate["id"], "2026-06-02")
    order = new_order(catalog["id"], consulate_id=consulate["id"])
    leg = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-02",
    )

    resp = api.dispatch_courier_leg(leg["id"], COURIER)
    validate_error(resp, ApiErrorId.ERR_EMBASSY_CLOSED.value)

    legs = {row["id"]: row for row in validate_paginated(
        api.list_courier_legs(order["id"], COURIER)
    )[0]}
    assert legs[leg["id"]]["leg_status"] == "CREATED"
    assert legs[leg["id"]]["attempt_count"] == 0
    assert read_order(order["id"])["custody_holder"] == "APPLICANT"


def test_fourth_dispatch_of_a_hop_is_refused_at_the_attempt_cap(api):
    """PRD §3.8: "A leg supports at most **2** re-dispatches after its first attempt, so
    `attempt_count` may reach 3 but a fourth dispatch is
    `ERR_COURIER_ATTEMPT_CAP_EXCEEDED`."
    PRD §2.9: "| 25 | `ERR_COURIER_ATTEMPT_CAP_EXCEEDED` | 409 | On dispatch only, the
    leg's `attempt_count` is below 3 (that is, fewer than 3 dispatch attempts so far). |"

    Design: Corner/errors/corner_error_courier_attempt_cap_exceeded
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    leg = new_leg(
        order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
        scheduled_date="2026-06-01",
    )
    for _ in range(3):
        dispatch_leg(leg["id"])
        complete_leg(leg["id"], "FAILED")

    resp = api.dispatch_courier_leg(leg["id"], COURIER)
    validate_error(resp, ApiErrorId.ERR_COURIER_ATTEMPT_CAP_EXCEEDED.value)

    legs = {row["id"]: row for row in validate_paginated(
        api.list_courier_legs(order["id"], COURIER)
    )[0]}
    assert legs[leg["id"]]["attempt_count"] == 3
    assert legs[leg["id"]]["leg_status"] == "FAILED"
    assert read_order(order["id"])["custody_holder"] == "APPLICANT"

    events = list_custody_events(order["id"])
    assert len(events) == 7, (
        f"one creation row plus a dispatch/return pair per attempt, got {len(events)}"
    )
    assert_single_open_custody(events, "APPLICANT")
