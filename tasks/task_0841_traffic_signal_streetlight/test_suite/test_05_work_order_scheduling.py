"""Work-order scheduling: crew conflicts, locate/excavation safety, validation
precedence, crew-labor conservation, and locate coordination."""
from test_helpers import validate_success, validate_error
from test_helpers.fixtures import (
    set_clock, new_intersection, new_device, new_crew, new_work_order,
    new_locate_request, schedule_work_order, get_crew, setup_cleared_locate,
)


# ── Difficulty: crew schedule half-open interval overlap ──────────────────────
def test_crew_schedule_overlap_rejected(api, dispatcher_headers):
    """PRD §3.4: "The crew must be free across the requested window: no other work
    order of the same crew in `SCHEDULED` or `DISPATCHED` may have a
    `[scheduled_start, scheduled_end)` interval — start inclusive, end exclusive —
    that overlaps the requested one, or the request is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_schedule_half_open_overlap
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    crew = new_crew(labor_capacity_hours=8.0)
    wo1 = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    wo2 = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    schedule_work_order(wo1["id"], crew["id"], "2026-03-02T08:00:00Z", "2026-03-02T10:00:00Z")
    res = api.schedule_work_order(
        wo2["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T09:00:00Z",
         "scheduled_end": "2026-03-02T11:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_CREW_SCHEDULE_CONFLICT", expected_status=409)
    fetched = validate_success(api.get_work_order(wo2["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


def test_crew_schedule_touching_window_allowed(api, dispatcher_headers):
    """PRD §3.4: "The crew must be free across the requested window: no other work
    order of the same crew in `SCHEDULED` or `DISPATCHED` may have a
    `[scheduled_start, scheduled_end)` interval — start inclusive, end exclusive —
    that overlaps the requested one, or the request is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_schedule_half_open_overlap
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    crew = new_crew(labor_capacity_hours=8.0)
    wo1 = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    wo2 = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    schedule_work_order(wo1["id"], crew["id"], "2026-03-02T08:00:00Z", "2026-03-02T10:00:00Z")
    # Touching at the exclusive end (10:00) does not overlap [08:00,10:00).
    res = api.schedule_work_order(
        wo2["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T10:00:00Z",
         "scheduled_end": "2026-03-02T12:00:00Z"},
        dispatcher_headers)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


# ── Difficulty: dispatch state check outranks referential check ───────────────
def test_dispatch_draft_decommissioned_device_returns_invalid_state(api, dispatcher_headers, admin_headers):
    """PRD §2.9: "State — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §2.9: "Where several of these could apply to one request, the lower-numbered
    check is decided first; for instance, an unauthenticated caller is rejected
    before any existence or state check runs, and a state violation surfaces before
    a temporal or capacity conflict."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_referential
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    validate_success(api.decommission_device(device["id"], admin_headers), 200)
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    # WorkOrder is DRAFT; dispatch is defined only from SCHEDULED -> state check wins
    # over the device-decommissioned referential check (priority 5 before 7).
    res = api.dispatch_work_order(wo["id"], dispatcher_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dispatch_decommissioned_does_not_surface_referential_error(api, dispatcher_headers, admin_headers):
    """PRD §3.4: "Dispatch moves the work order from `SCHEDULED` to `DISPATCHED`
    and requires that the device is not `DECOMMISSIONED`, else
    `ERR_DEVICE_DECOMMISSIONED`."
    PRD §2.9: "a state violation surfaces before a temporal or capacity conflict."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_referential
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    validate_success(api.decommission_device(device["id"], admin_headers), 200)
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    res = api.dispatch_work_order(wo["id"], dispatcher_headers)
    err = validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert err["error_id"] != "ERR_DEVICE_DECOMMISSIONED"
    fetched = validate_success(api.get_work_order(wo["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


# ── Difficulty: excavation safety check outranks fiscal check ────────────────
def test_excavation_schedule_locate_safety_beats_capacity(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §3.5: "These safety checks precede the crew-conflict and capacity checks
    in the precedence order."
    PRD §3.5: "When a work order's `work_type` is `EXCAVATION`, scheduling requires
    that `locate_request_id` be supplied (else `ERR_LOCATE_REQUIRED`), that the
    referenced locate be in `CLEARED` status (else `ERR_LOCATE_NOT_CLEARED`), and
    that the current clock be at or before that locate's `valid_until` (else
    `ERR_LOCATE_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/excavation_schedule_safety_beats_fiscal
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D1", replacement_cost=400.00)
    crew = new_crew(name="Crew Tiny", specialty="LOCATE", labor_capacity_hours=1.0)
    locate = new_locate_request(inter["id"])  # OPEN, un-cleared
    wo = new_work_order(device["id"], work_type="EXCAVATION",
                        estimated_labor_hours=5.0, locate_request_id=locate["id"])
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T08:00:00Z",
         "scheduled_end": "2026-03-02T13:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_LOCATE_NOT_CLEARED", expected_status=409)


def test_excavation_schedule_capacity_error_suppressed_by_safety(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §2.9: "Business safety — excavation scheduling requires a cleared,
    non-expired locate, and timing-change review or approval requires the
    intersection not be in `EMERGENCY` posture, else `ERR_LOCATE_NOT_CLEARED`,
    `ERR_LOCATE_EXPIRED`, `ERR_LOCATE_REQUIRED`, or `ERR_INTERSECTION_EMERGENCY`
    (409)."
    PRD §2.9: "Crew labor budget — else `ERR_CREW_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/excavation_schedule_safety_beats_fiscal
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D1", replacement_cost=400.00)
    crew = new_crew(name="Crew Tiny", specialty="LOCATE", labor_capacity_hours=1.0)
    locate = new_locate_request(inter["id"])
    wo = new_work_order(device["id"], work_type="EXCAVATION",
                        estimated_labor_hours=5.0, locate_request_id=locate["id"])
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T08:00:00Z",
         "scheduled_end": "2026-03-02T13:00:00Z"},
        dispatcher_headers)
    err = validate_error(res, "ERR_LOCATE_NOT_CLEARED", expected_status=409)
    assert err["error_id"] != "ERR_CREW_CAPACITY_EXCEEDED"
    fetched = validate_success(api.get_work_order(wo["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


# ── Difficulty: excavation blocked by un-cleared locate (cross-entity) ────────
def test_excavation_schedule_requires_cleared_locate(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §3.5: "Only a `CLEARED` locate that the clock has not yet passed
    unblocks excavation scheduling. When a work order's `work_type` is
    `EXCAVATION`, scheduling requires that `locate_request_id` be supplied (else
    `ERR_LOCATE_REQUIRED`), that the referenced locate be in `CLEARED` status (else
    `ERR_LOCATE_NOT_CLEARED`), and that the current clock be at or before that
    locate's `valid_until` (else `ERR_LOCATE_EXPIRED`)."

    Design: Difficulty/cross_entity_state_dependency/excavation_schedule_requires_cleared_locate
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D2", replacement_cost=400.00)
    crew = new_crew(name="Crew D", specialty="LOCATE", labor_capacity_hours=8.0)
    locate = new_locate_request(inter["id"])  # OPEN
    wo = new_work_order(device["id"], work_type="EXCAVATION",
                        estimated_labor_hours=2.0, locate_request_id=locate["id"])
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T08:00:00Z",
         "scheduled_end": "2026-03-02T10:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_LOCATE_NOT_CLEARED", expected_status=409)
    fetched = validate_success(api.get_work_order(wo["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


def test_excavation_schedule_succeeds_once_locate_cleared(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §3.5: "Only a `CLEARED` locate that the clock has not yet passed
    unblocks excavation scheduling."

    Design: Difficulty/cross_entity_state_dependency/excavation_schedule_requires_cleared_locate
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D2", replacement_cost=400.00)
    crew = new_crew(name="Crew D", specialty="LOCATE", labor_capacity_hours=8.0)
    locate = setup_cleared_locate(inter["id"])
    assert locate["status"] == "CLEARED"
    wo = new_work_order(device["id"], work_type="EXCAVATION",
                        estimated_labor_hours=2.0, locate_request_id=locate["id"])
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-02T08:00:00Z",
         "scheduled_end": "2026-03-02T10:00:00Z"},
        dispatcher_headers)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


# ── Difficulty: crew labor-hour pool conserved across schedule/cancel ─────────
def test_crew_labor_hours_conserved_after_cancel(api, dispatcher_headers):
    """PRD §3.4: "A dispatcher may cancel a work order while it is still `DRAFT` or
    `SCHEDULED`, moving it to the terminal `CANCELLED` state. Cancelling a `DRAFT`
    order has no ledger effect, but cancelling a `SCHEDULED` order performs a
    compensating release: the crew's `committed_labor_hours` is reduced by
    `estimated_labor_hours`, returning `available_labor_hours` to its pre-schedule
    value."

    Design: Difficulty/compensating_invariant/crew_labor_hours_conserved_on_cancel
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    crew = new_crew(labor_capacity_hours=8.0)
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=3.0)
    schedule_work_order(wo["id"], crew["id"])
    cancelled = validate_success(api.cancel_work_order(wo["id"], dispatcher_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    crew_after = get_crew(crew["id"])
    assert crew_after["committed_labor_hours"] == 0
    assert crew_after["available_labor_hours"] == 8.0


def test_crew_labor_hours_debited_on_schedule(api, dispatcher_headers):
    """PRD §3.4: "On a successful schedule the `crew_id`, `scheduled_start`, and
    `scheduled_end` are recorded and the crew's `committed_labor_hours` rises by
    `estimated_labor_hours`, which lowers its `available_labor_hours` by the same
    amount."
    PRD §3.1: "At all times a crew's committed and available hours sum to its
    capacity: `available_labor_hours` is always the `labor_capacity_hours` minus
    the sum of `estimated_labor_hours` over that crew's work orders currently in
    `SCHEDULED` or `DISPATCHED`."

    Design: Difficulty/compensating_invariant/crew_labor_hours_conserved_on_cancel
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    crew = new_crew(labor_capacity_hours=8.0)
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=3.0)
    schedule_work_order(wo["id"], crew["id"])
    crew_after = get_crew(crew["id"])
    assert crew_after["committed_labor_hours"] == 3.0
    assert crew_after["available_labor_hours"] == 5.0


# ── Corner: crew not found on schedule ───────────────────────────────────────
def test_crew_not_found_on_schedule(api, dispatcher_headers):
    """PRD §3.4: "Several checks guard scheduling in the precedence of §2.9. The
    referenced crew must exist."
    PRD §2.8: "the first identifier that does not resolve to an existing resource
    yields the corresponding not-found error for that resource type (for example
    `ERR_INTERSECTION_NOT_FOUND`, `ERR_POLE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, ...), each carrying HTTP 404."

    Design: Corner/errors/crew_not_found_on_schedule
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=1.0)
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": "99999999-9999-9999-9999-999999999999",
         "scheduled_start": "2026-03-02T08:00:00Z", "scheduled_end": "2026-03-02T09:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_CREW_NOT_FOUND", expected_status=404)
    fetched = validate_success(api.get_work_order(wo["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


# ── Corner: expired cleared locate blocks excavation ─────────────────────────
def test_locate_expired_blocks_excavation(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §3.5: "The clearance remains valid for `valid_days` days from creation,
    defaulting to 21 days when omitted; the system records `valid_until` as the
    creation clock plus that many days."
    PRD §3.5: "that the current clock be at or before that locate's `valid_until`
    (else `ERR_LOCATE_EXPIRED`)."

    Design: Corner/errors/locate_expired_blocks_excavation
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D9", replacement_cost=400.00)
    crew = new_crew(name="Crew I", specialty="LOCATE", labor_capacity_hours=8.0)
    locate = setup_cleared_locate(inter["id"])  # valid_until 2026-03-22 (default 21 days)
    set_clock("2026-03-23T00:00:00Z")  # past valid_until
    wo = new_work_order(device["id"], work_type="EXCAVATION",
                        estimated_labor_hours=2.0, locate_request_id=locate["id"])
    res = api.schedule_work_order(
        wo["id"],
        {"crew_id": crew["id"], "scheduled_start": "2026-03-24T08:00:00Z",
         "scheduled_end": "2026-03-24T10:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_LOCATE_EXPIRED", expected_status=409)
    fetched = validate_success(api.get_work_order(wo["id"], dispatcher_headers), 200)
    assert fetched["status"] == "DRAFT"


# ── Corner: locate OPEN -> MARKED -> CLEARED ─────────────────────────────────
def test_locate_mark_then_clear_reaches_cleared(api, utility_coordinator_headers):
    """PRD §3.5: "A locate request opens `OPEN`, is advanced to `MARKED` when the
    utility lines have been physically located, and then to `CLEARED` when the
    coordinator clears it."

    Design: Corner/state_machines/locate_mark_then_clear_valid
    """
    inter = new_intersection()
    locate = new_locate_request(inter["id"])
    assert locate["status"] == "OPEN"
    validate_success(api.mark_locate_request(locate["id"], utility_coordinator_headers), 200)
    cleared = validate_success(api.clear_locate_request(locate["id"], utility_coordinator_headers), 200)
    assert cleared["status"] == "CLEARED"
