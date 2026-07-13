"""Missed stops: the cascade into specimens and exceptions, and the revision cycle."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# The missed-stop cascade
# ---------------------------------------------------------------------------
def test_missing_a_pickup_stop_cascades_to_specimen_and_opens_an_exception(api):
    """PRD §3.6: "First, every specimen whose `pickup_stop_id` or `dropoff_stop_id` is
    this stop and whose `custody_status` is `AWAITING_PICKUP` or `IN_TRANSIT` is moved to
    custody `EXCEPTION`, removing it from the deliverable set."
    PRD §3.6: "Second, each such implicated specimen opens one route exception of type
    `MISSED_STOP`, in `OPEN` status, carrying the `route_id`, the `stop_id`, and that
    `specimen_id`."

    Design: Difficulty/transitive_cascade/miss_stop_depth3_specimen_exception_chain
    """
    ctx = fixtures.setup_dispatched_route()
    stop = ctx["stops"][0]
    spec = ctx["specimens"][0]

    missed = validate_success(api.miss_stop(stop["id"], DISPATCHER))
    assert missed["status"] == "MISSED"

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["custody_status"] == "EXCEPTION"

    rows, _meta = validate_paginated(api.list_exceptions(DISPATCHER, params={"stop_id": stop["id"]}))
    assert len(rows) == 1, f"Expected exactly one exception for the missed stop, got {len(rows)}"
    assert rows[0]["exception_type"] == "MISSED_STOP"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["specimen_id"] == spec["id"]
    assert rows[0]["route_id"] == ctx["route"]["id"]


def test_missing_a_dropoff_stop_cascades_an_in_transit_specimen_to_exception(api):
    """PRD §3.6: "First, every specimen whose `pickup_stop_id` or `dropoff_stop_id` is
    this stop and whose `custody_status` is `AWAITING_PICKUP` or `IN_TRANSIT` is moved to
    custody `EXCEPTION`, removing it from the deliverable set."
    PRD §3.6: "Second, each such implicated specimen opens one route exception of type
    `MISSED_STOP`, in `OPEN` status, carrying the `route_id`, the `stop_id`, and that
    `specimen_id`."

    Design: Difficulty/transitive_cascade/miss_stop_depth3_specimen_exception_chain
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    dropoff_stop = ctx["stops"][1]
    fixtures.scan(ctx["stops"][0]["id"], spec["id"], "PICKUP", 5.0, 2.5, ctx["driver"]["id"])

    missed = validate_success(api.miss_stop(dropoff_stop["id"], DISPATCHER))
    assert missed["status"] == "MISSED"

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    assert specimen["custody_status"] == "EXCEPTION", (
        "An IN_TRANSIT specimen whose dropoff stop is missed moves to custody EXCEPTION"
    )

    rows, _meta = validate_paginated(
        api.list_exceptions(DISPATCHER, params={"stop_id": dropoff_stop["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["exception_type"] == "MISSED_STOP"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["specimen_id"] == spec["id"]


# ---------------------------------------------------------------------------
# The stop revision cycle: SCHEDULED -> MISSED -> SCHEDULED
# ---------------------------------------------------------------------------
def test_missed_stop_can_be_rescheduled_back_to_scheduled(api):
    """PRD §3.6: "A missed stop may be rescheduled by a dispatcher, moving it
    `MISSED → SCHEDULED`; the stop must currently be `MISSED`, else
    `ERR_STOP_INVALID_STATE`."
    PRD §3.6: "Rescheduling clears the stop's `arrived_at` so the revision cycle can
    begin cleanly."

    Design: Difficulty/non_linear_state_machine/stop_cyclic_miss_then_reschedule
    """
    ctx = fixtures.setup_dispatched_route()
    stop_id = ctx["stops"][0]["id"]
    fixtures.miss_stop(stop_id)

    rescheduled = validate_success(api.reschedule_stop(stop_id, DISPATCHER))
    assert rescheduled["status"] == "SCHEDULED", (
        f"A rescheduled stop returns to SCHEDULED, got {rescheduled['status']}"
    )
    assert rescheduled["arrived_at"] is None, "Rescheduling clears arrived_at"


def test_rescheduling_a_stop_missed_after_arrival_clears_arrived_at(api):
    """PRD §3.6: "The parent route must be `DISPATCHED` (else `ERR_ROUTE_INVALID_STATE`);
    a stop may be missed from either `SCHEDULED` or `ARRIVED`, and any other stop state is
    rejected with `ERR_STOP_INVALID_STATE`."
    PRD §3.6: "Rescheduling clears the stop's `arrived_at` so the revision cycle can
    begin cleanly."

    The dropoff stop is driven to ARRIVED by a scan, then missed, then rescheduled: the
    cycle returns it to SCHEDULED with its arrival stamp erased.

    Design: Difficulty/non_linear_state_machine/stop_cyclic_miss_then_reschedule
    """
    ctx = fixtures.setup_two_specimen_route()
    spec_1, spec_2 = ctx["specimens"]
    dropoff_stop = ctx["stops"][2]

    # Pick up only the first specimen, then arrive at the shared dropoff stop with it.
    fixtures.scan(ctx["stops"][0]["id"], spec_1["id"], "PICKUP", 20.0, 2.0, ctx["driver"]["id"])
    fixtures.scan(dropoff_stop["id"], spec_1["id"], "DROPOFF", 20.0, 2.0, ctx["driver"]["id"])

    arrived = validate_success(api.get_stop(dropoff_stop["id"], DISPATCHER))
    assert arrived["status"] == "ARRIVED", (
        "The stop stays ARRIVED while the second specimen is still undelivered"
    )
    assert arrived["arrived_at"] is not None

    fixtures.miss_stop(dropoff_stop["id"])
    rescheduled = validate_success(api.reschedule_stop(dropoff_stop["id"], DISPATCHER))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["arrived_at"] is None, "Rescheduling clears arrived_at"


def test_rescheduling_a_stop_that_was_never_missed_is_rejected(api):
    """PRD §3.6: "A missed stop may be rescheduled by a dispatcher, moving it
    `MISSED → SCHEDULED`; the stop must currently be `MISSED`, else
    `ERR_STOP_INVALID_STATE`."

    Design: Corner/state_machines/reschedule_non_missed_stop_returns_409
    """
    ctx = fixtures.setup_dispatched_route()
    resp = api.reschedule_stop(ctx["stops"][0]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Custody buckets conserve the registered specimen count
# ---------------------------------------------------------------------------
def test_pickup_moves_one_specimen_without_changing_the_registered_total(api):
    """PRD §3.5: "A pickup scan advances the specimen's custody dimension
    `AWAITING_PICKUP → IN_TRANSIT`."
    PRD §3.2: "Its `custody_status` starts `AWAITING_PICKUP` and its `integrity_status`
    starts `INTACT`; these two dimensions evolve independently."

    Two specimens are registered; picking one up leaves one IN_TRANSIT and one
    AWAITING_PICKUP — the buckets still sum to the two registered specimens.

    Design: Difficulty/compensating_invariant/specimen_custody_count_conserved
    """
    ctx = fixtures.setup_two_specimen_route()
    spec_1, spec_2 = ctx["specimens"]
    fixtures.scan(ctx["stops"][0]["id"], spec_1["id"], "PICKUP", 20.0, 2.0, ctx["driver"]["id"])

    first = validate_success(api.get_specimen(spec_1["id"], DISPATCHER))
    second = validate_success(api.get_specimen(spec_2["id"], DISPATCHER))
    assert first["custody_status"] == "IN_TRANSIT"
    assert second["custody_status"] == "AWAITING_PICKUP"

    rows, meta = validate_paginated(
        api.list_specimens(DISPATCHER, params={"route_id": ctx["route"]["id"]})
    )
    assert meta["total_count"] == 2, f"Two specimens were registered, got {meta['total_count']}"
    assert len(rows) == 2


def test_custody_buckets_still_sum_to_the_registered_total_after_a_missed_stop(api):
    """PRD §3.6: "First, every specimen whose `pickup_stop_id` or `dropoff_stop_id` is
    this stop and whose `custody_status` is `AWAITING_PICKUP` or `IN_TRANSIT` is moved to
    custody `EXCEPTION`, removing it from the deliverable set."
    PRD §3.5: "A pickup scan advances the specimen's custody dimension
    `AWAITING_PICKUP → IN_TRANSIT`."

    After the forward pickup of one specimen and the compensating miss of the other's
    pickup stop, the custody buckets (IN_TRANSIT + EXCEPTION) still account for exactly
    the two registered specimens.

    Design: Difficulty/compensating_invariant/specimen_custody_count_conserved
    """
    ctx = fixtures.setup_two_specimen_route()
    spec_1, spec_2 = ctx["specimens"]
    fixtures.scan(ctx["stops"][0]["id"], spec_1["id"], "PICKUP", 20.0, 2.0, ctx["driver"]["id"])

    fixtures.miss_stop(ctx["stops"][1]["id"])

    first = validate_success(api.get_specimen(spec_1["id"], DISPATCHER))
    second = validate_success(api.get_specimen(spec_2["id"], DISPATCHER))
    assert first["custody_status"] == "IN_TRANSIT"
    assert second["custody_status"] == "EXCEPTION"

    rows, meta = validate_paginated(
        api.list_specimens(DISPATCHER, params={"route_id": ctx["route"]["id"]})
    )
    assert meta["total_count"] == 2, "No specimen may be lost or duplicated by the cascade"
    buckets = sorted(row["custody_status"] for row in rows)
    assert buckets == ["EXCEPTION", "IN_TRANSIT"]


# ---------------------------------------------------------------------------
# Exception resolution is the compliance officer's surface
# ---------------------------------------------------------------------------
def test_dispatcher_cannot_resolve_an_exception(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation — or an ownership-scoped role reaches for a resource it does
    not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.6: "A compliance officer resolves an open exception, moving it
    `OPEN → RESOLVED`; the exception must be `OPEN`, else `ERR_EXCEPTION_INVALID_STATE`."

    Design: Corner/rbac/exception_resolve_requires_compliance_officer_returns_unauthorized
    """
    ctx = fixtures.setup_missed_stop()
    exception_id = ctx["exceptions"][0]["id"]

    resp = api.resolve_exception(exception_id, {}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    # The compliance officer, by contrast, may resolve it.
    resolved = validate_success(
        api.resolve_exception(exception_id, {"resolution_note": "Re-run scheduled"}, COMPLIANCE)
    )
    assert resolved["status"] == "RESOLVED"
