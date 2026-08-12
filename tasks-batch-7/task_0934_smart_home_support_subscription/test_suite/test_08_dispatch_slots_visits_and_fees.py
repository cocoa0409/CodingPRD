"""Field dispatch: slots, the travel buffer, visit outcomes and the fee variants."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    assert_slot_counts,
    assert_visit,
    book,
    escalate_by_hardware_fault,
    fetch_campaign,
    fetch_device,
    fetch_rollout,
    fetch_slot,
    fetch_subscription,
    fetch_technician,
    fetch_ticket,
    fetch_visit,
    first_response,
    make_technician_headers,
    new_technician,
    new_ticket,
    publish_slot,
    set_clock,
    setup_dispatch_world,
    setup_escalated_ticket,
    setup_ring,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# Not-found probes
# ==========================================================================
def test_technician_read_with_unknown_id_reports_technician_not_found(api):
    """PRD 2.9 rung 12: "Every `Technician` id named in the path exists — otherwise
    `ERR_TECHNICIAN_NOT_FOUND`. Applies to slot publication and the
    single-technician read."

    Design: Corner/entities/technician_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_technician("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_TECHNICIAN_NOT_FOUND.value, 404)


def test_visit_slot_read_with_unknown_id_reports_slot_not_found(api):
    """PRD 2.9 rung 13: "Every `VisitSlot` id named in the path or body exists —
    otherwise `ERR_SLOT_NOT_FOUND`. Applies to visit booking, rescheduling and the
    single-slot read."

    Design: Corner/entities/visit_slot_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_visit_slot("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_SLOT_NOT_FOUND.value, 404)


def test_visit_read_with_unknown_id_reports_visit_not_found(api):
    """PRD 2.9 rung 14: "Every `Visit` id named in the path exists — otherwise
    `ERR_VISIT_NOT_FOUND`. Applies to the visit action endpoints and the single-visit
    read."

    Design: Corner/entities/visit_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_visit("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_VISIT_NOT_FOUND.value, 404)


# ==========================================================================
# Booking rungs
# ==========================================================================
def test_booking_a_slot_outside_the_household_region_is_a_region_mismatch(api):
    """PRD 3.8: "Second, region: the slot's `region_code` must equal the ticket
    household's `region_code`, otherwise `ERR_SLOT_REGION_MISMATCH`."
    PRD 3.8: "The slot's own `region_code` is **copied from the owning technician** at
    creation and any value supplied in the request is ignored."

    Design: Corner/validations/booking_a_slot_in_the_wrong_region_returns_slot_region_mismatch
    """
    world = setup_dispatch_world(
        slots=(("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
        technician_region="SEB",
        technician_name="Far Tech",
        plan_kind="PRO",
        allow_overage=False,
        name="Region House",
        email_prefix="reg",
    )
    ticket = setup_escalated_ticket(world, severity="P1", summary="Needs a visit")

    response = api.book_visit(
        {"ticket_id": ticket["id"], "slot_id": world["slots"][0]["id"]}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_SLOT_REGION_MISMATCH.value, 422)

    slot = fetch_slot(world["slots"][0]["id"])
    assert slot["status"] == "OPEN"
    assert slot["region_code"] == "SEB"
    assert fetch_ticket(ticket["id"])["dispatch_status"] == "REQUIRED"


def test_booking_a_slot_that_is_already_booked_reports_slot_unavailable(api):
    """PRD 3.8: "Third, availability: the slot's `status` must be `OPEN`, otherwise
    `ERR_SLOT_UNAVAILABLE`. Fourth, the travel buffer."
    PRD 2.9: "Rungs are evaluated strictly in ascending priority order; **the first
    rung that fails is the error reported, and no later rung is evaluated**."

    Design: Corner/validations/booking_an_already_booked_slot_returns_slot_unavailable
    """
    world = setup_dispatch_world(
        slots=(("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="One Tech",
        name="Taken House",
        email_prefix="tak",
    )
    ticket_one = setup_escalated_ticket(world, severity="P1", summary="Fault one")
    ticket_two = setup_escalated_ticket(world, severity="P1", summary="Fault two")
    book(ticket_one["id"], world["slots"][0]["id"])

    response = api.book_visit(
        {"ticket_id": ticket_two["id"], "slot_id": world["slots"][0]["id"]}, AGENT
    )
    error = validate_error(response, ApiErrorId.ERR_SLOT_UNAVAILABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_SLOT_BUFFER_CONFLICT.value

    assert fetch_slot(world["slots"][0]["id"])["status"] == "BOOKED"
    technician = fetch_technician(world["technician"]["id"])
    assert technician["booked_slot_count"] == 1
    assert technician["open_slot_count"] == 0


def test_completing_a_visit_before_its_scheduled_start_is_refused(api):
    """PRD 3.8: "It requires the visit to be `SCHEDULED`, the acting technician's
    identity to equal the `technician_id` of the occupied slot, and the logical clock
    to be at or after `scheduled_start_at`; an early completion is refused with
    `ERR_VISIT_NOT_STARTED`."

    Design: Corner/validations/completing_a_visit_before_its_start_returns_visit_not_started
    """
    world = setup_dispatch_world(
        slots=(("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Ear Tech",
        name="Early House",
        email_prefix="ear",
    )
    ticket = setup_escalated_ticket(world, severity="P1", summary="Needs a visit")
    visit = book(ticket["id"], world["slots"][0]["id"])
    set_clock("2026-05-05T08:59:00Z")

    response = api.complete_visit(
        visit["id"], {"completion_notes": "Arrived early."}, world["technician_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VISIT_NOT_STARTED.value, 409)

    assert fetch_visit(visit["id"])["status"] == "SCHEDULED"
    current = fetch_ticket(ticket["id"])
    assert current["workflow_status"] == "ONSITE"
    assert current["dispatch_status"] == "SCHEDULED"


def test_a_technician_cannot_complete_another_technicians_visit(api):
    """PRD 2.1: "Row scope for `Technician` compares the acting technician's `id`
    against the `technician_id` of the slot behind the target visit, the target slot,
    or the rollout whose result is being reported."
    PRD 2.1: "A listed entity-backed role that addresses a row outside its scope — an
    `Owner` touching another household's device, a `Technician` completing a visit
    booked into another technician's slot — is rejected with `ERR_ROW_SCOPE_DENIED`
    (HTTP 403)."

    Design: Corner/rbac/technician_cannot_complete_another_technicians_visit
    """
    world = setup_dispatch_world(
        slots=(("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Tech One",
        name="Scope2 House",
        email_prefix="sc2",
    )
    other_technician = new_technician("Tech Two", "NWA", ["HUB"])
    ticket = setup_escalated_ticket(world, severity="P1", summary="Needs a visit")
    visit = book(ticket["id"], world["slots"][0]["id"])
    set_clock("2026-05-05T09:30:00Z")

    response = api.complete_visit(
        visit["id"],
        {"completion_notes": "Not my job."},
        make_technician_headers(other_technician["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_ROW_SCOPE_DENIED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value

    assert fetch_visit(visit["id"])["status"] == "SCHEDULED"
    assert fetch_ticket(ticket["id"])["workflow_status"] == "ONSITE"


# ==========================================================================
# Fees and rescheduling
# ==========================================================================
def test_pro_waiver_covers_a_late_cancellation_but_never_a_no_show(api):
    """PRD 3.8: "When it happens strictly after the cutoff it is a late cancellation:
    `fee_kind` becomes `LATE_CANCEL`, the base fee is 4500 cents, and the slot moves
    to `BLOCKED` because the technician's time is consumed and cannot be resold,
    lowering `booked_slot_count` and raising `blocked_slot_count` by one each."
    PRD 3.8: "**The `PRO` waiver applies here and only here**: if the household's
    in-force plan `tier` is `PRO`, `fee_waived` is set true and `fee_cents` is 0;
    otherwise `fee_waived` is false and `fee_cents` is the base fee."
    PRD 3.8: "There is no cutoff test at all: `fee_kind` becomes `NO_SHOW` and
    `fee_cents` is 9000 cents, and **the `PRO` waiver does not apply to no-shows**,
    so a `PRO` household pays nothing for a late cancellation and the full 9000
    cents for a no-show on the very same slot."

    Design: Corner/calculations/pro_waiver_applies_to_a_late_cancel_but_never_to_a_no_show
    """
    world = setup_dispatch_world(
        slots=(
            ("2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z"),
            ("2026-05-10T13:00:00Z", "2026-05-10T15:00:00Z"),
        ),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Fee Tech",
        name="Fee House",
        email_prefix="fee",
    )
    ticket_one = setup_escalated_ticket(world, severity="P1", summary="Fault one")
    ticket_two = setup_escalated_ticket(world, severity="P1", summary="Fault two")
    visit_one = book(ticket_one["id"], world["slots"][0]["id"])
    visit_two = book(ticket_two["id"], world["slots"][1]["id"])

    # The 24-hour cutoff for the 09:00 visit is 2026-05-09T09:00Z; 10:00 is after it.
    set_clock("2026-05-09T10:00:00Z")
    cancelled = validate_success(api.cancel_visit(visit_one["id"], {}, AGENT), 200)
    assert_visit(cancelled)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_kind"] == "LATE_CANCEL"
    assert cancelled["fee_waived"] is True
    assert cancelled["fee_cents"] == 0

    set_clock("2026-05-10T13:30:00Z")
    no_show = validate_success(
        api.report_no_show(visit_two["id"], {}, world["technician_headers"]), 200
    )
    assert no_show["status"] == "NO_SHOW"
    assert no_show["fee_kind"] == "NO_SHOW"
    assert no_show["fee_waived"] is False
    assert no_show["fee_cents"] == 9000

    assert fetch_slot(world["slots"][0]["id"])["status"] == "BLOCKED"
    assert fetch_slot(world["slots"][1]["id"])["status"] == "BLOCKED"
    assert_slot_counts(
        fetch_technician(world["technician"]["id"]), total=2, open_count=0, booked=0, blocked=2
    )
    assert (
        fetch_subscription(world["subscription"]["id"])["next_invoice_adjustment_cents"] == 9000
    )


def test_rescheduling_frees_the_vacated_slot_and_recopies_the_window(api):
    """PRD 3.8: "The vacated slot is released to `OPEN`, the new slot is booked,
    `scheduled_start_at` and `scheduled_end_at` are re-copied from the new slot, and
    the slot counters are recomputed on the technicians owning both slots."
    PRD 3.8: "The state-machine rule under which a booked slot returns to `OPEN` on a
    reschedule carries the precondition that the logical clock is at or before the
    visit's `scheduled_start_at` minus 24 hours."

    The clock is 2026-05-01, comfortably at or before the 2026-05-09T09:00Z
    precondition instant, so this is an early reschedule.

    Design: Corner/endpoints/reschedule_moves_the_visit_and_frees_the_vacated_slot
    """
    world = setup_dispatch_world(
        slots=(
            ("2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z"),
            ("2026-05-10T13:00:00Z", "2026-05-10T15:00:00Z"),
        ),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Res Tech",
        name="Resched House",
        email_prefix="res",
    )
    ticket = setup_escalated_ticket(world, severity="P1", summary="Needs a visit")
    visit = book(ticket["id"], world["slots"][0]["id"])

    data = validate_success(
        api.reschedule_visit(visit["id"], {"new_slot_id": world["slots"][1]["id"]}, AGENT), 200
    )

    assert data["slot_id"] == world["slots"][1]["id"]
    assert_same_instant(
        data["scheduled_start_at"], "2026-05-10T13:00:00Z", "Visit.scheduled_start_at"
    )
    assert_same_instant(
        data["scheduled_end_at"], "2026-05-10T15:00:00Z", "Visit.scheduled_end_at"
    )
    assert data["status"] == "SCHEDULED"
    assert data["fee_cents"] == 0

    assert fetch_slot(world["slots"][0]["id"])["status"] == "OPEN"
    assert fetch_slot(world["slots"][1]["id"])["status"] == "BOOKED"
    assert_slot_counts(
        fetch_technician(world["technician"]["id"]), total=2, open_count=1, booked=1, blocked=0
    )
    current = fetch_ticket(ticket["id"])
    assert current["dispatch_status"] == "SCHEDULED"
    assert current["workflow_status"] == "ONSITE"


# ==========================================================================
# Difficulty: the travel buffer at and just inside its boundary
# ==========================================================================
def _two_slot_buffer_world(second_slot_start: str, house: str, prefix: str, tech: str):
    world = setup_dispatch_world(
        slots=(
            ("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),
            (second_slot_start, "2026-05-05T13:00:00Z"),
        ),
        plan_kind="PRO",
        allow_overage=False,
        technician_name=tech,
        name=house,
        email_prefix=prefix,
    )
    world["ticket_one"] = setup_escalated_ticket(world, severity="P1", summary="First fault")
    world["ticket_two"] = setup_escalated_ticket(world, severity="P1", summary="Second fault")
    book(world["ticket_one"]["id"], world["slots"][0]["id"])
    return world


def test_candidate_slot_exactly_one_travel_buffer_later_is_accepted(api):
    """PRD 3.8: "A candidate slot conflicts with an already-`BOOKED` slot of the *same*
    technician when the booked slot's start, moved 45 minutes earlier, is strictly
    before the candidate's end **and** the candidate's start is strictly before the
    booked slot's end, moved 45 minutes later."
    PRD 3.8: "Both comparisons are strict, so exact buffer adjacency is legal: if a
    booked slot ends at 10:00, a candidate starting at exactly 10:45 is accepted
    while one starting at 10:44 is rejected."

    Design: Difficulty/boundary_precision_check/slot_starting_exactly_one_travel_buffer_after_a_booked_slot_is_accepted
    """
    world = _two_slot_buffer_world(
        "2026-05-05T11:45:00Z", "Buffer House", "buf", "Tim Tech"
    )

    data = validate_success(
        api.book_visit(
            {"ticket_id": world["ticket_two"]["id"], "slot_id": world["slots"][1]["id"]},
            AGENT,
        ),
        201,
    )

    assert_visit(data)
    assert data["status"] == "SCHEDULED"
    assert_same_instant(
        data["scheduled_start_at"], "2026-05-05T11:45:00Z", "Visit.scheduled_start_at"
    )


def test_accepting_the_adjacent_slot_moves_both_slots_into_the_booked_bucket(api):
    """PRD 3.8: "A successful booking creates a `Visit` row in `SCHEDULED` with
    `scheduled_start_at` and `scheduled_end_at` copied from the occupied slot,
    `fee_kind` `NONE`, `fee_cents` 0, `fee_waived` false and `cancelled_at` null. The
    slot moves `OPEN → BOOKED` and the technician's `open_slot_count` falls by one
    while `booked_slot_count` rises by one."
    PRD 3.8: "The ticket moves `DISPATCH_PENDING → ONSITE` on the workflow axis and
    `REQUIRED`, `RESCHEDULING` or `NO_SHOW` → `SCHEDULED` on the dispatch axis."

    Design: Difficulty/boundary_precision_check/slot_starting_exactly_one_travel_buffer_after_a_booked_slot_is_accepted
    """
    world = _two_slot_buffer_world(
        "2026-05-05T11:45:00Z", "Buffer House", "buf", "Tim Tech"
    )

    validate_success(
        api.book_visit(
            {"ticket_id": world["ticket_two"]["id"], "slot_id": world["slots"][1]["id"]},
            AGENT,
        ),
        201,
    )

    assert fetch_slot(world["slots"][1]["id"])["status"] == "BOOKED"
    assert_slot_counts(
        fetch_technician(world["technician"]["id"]), total=2, open_count=0, booked=2, blocked=0
    )
    assert fetch_ticket(world["ticket_two"]["id"])["dispatch_status"] == "SCHEDULED"


def test_candidate_slot_one_minute_inside_the_travel_buffer_is_rejected(api):
    """PRD 3.8: "Both comparisons are strict, so exact buffer adjacency is legal: if a
    booked slot ends at 10:00, a candidate starting at exactly 10:45 is accepted
    while one starting at 10:44 is rejected."
    PRD 3.8: "A conflict is reported as `ERR_SLOT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/technician_slot_one_minute_inside_travel_buffer_is_rejected
    """
    world = _two_slot_buffer_world(
        "2026-05-05T11:44:00Z", "Conflict House", "cfl", "Cora Tech"
    )

    response = api.book_visit(
        {"ticket_id": world["ticket_two"]["id"], "slot_id": world["slots"][1]["id"]}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_SLOT_BUFFER_CONFLICT.value, 409)


def test_buffer_rejection_leaves_the_candidate_slot_open_and_the_ticket_required(api):
    """PRD 2.10: "For every technician, `open_slot_count` plus `booked_slot_count` plus
    `blocked_slot_count` equals `total_slot_count`."
    PRD 3.8: "Only `BOOKED` slots of that technician participate; `OPEN` and `BLOCKED`
    slots never conflict."

    Design: Difficulty/resource_temporal_overlap/technician_slot_one_minute_inside_travel_buffer_is_rejected
    """
    world = _two_slot_buffer_world(
        "2026-05-05T11:44:00Z", "Conflict House", "cfl", "Cora Tech"
    )

    api.book_visit(
        {"ticket_id": world["ticket_two"]["id"], "slot_id": world["slots"][1]["id"]}, AGENT
    )

    assert fetch_slot(world["slots"][1]["id"])["status"] == "OPEN"
    assert_slot_counts(
        fetch_technician(world["technician"]["id"]), total=2, open_count=1, booked=1, blocked=0
    )
    assert fetch_ticket(world["ticket_two"]["id"])["dispatch_status"] == "REQUIRED"


# ==========================================================================
# Difficulty: dispatch readiness is a Ticket-side precondition
# ==========================================================================
def _triaged_only_world():
    world = setup_dispatch_world(
        slots=(("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Dan Tech",
        name="Dispatch House",
        email_prefix="disp",
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P3",
        summary="Thermostat schedule odd",
        opened_by_member_id=world["owner"]["id"],
    )
    # First response only: the ticket reaches TRIAGED and never escalates.
    first_response(ticket["id"], "Triaged.")
    world["ticket"] = ticket
    return world


def test_booking_for_a_never_escalated_ticket_reports_dispatch_not_required(api):
    """PRD 3.8: "First, dispatch readiness: the ticket's `dispatch_status` must be
    `REQUIRED`, `RESCHEDULING` or `NO_SHOW`, and a ticket that never escalated — one
    still in `NEW`, `TRIAGED` or `REMOTE_DIAG` — reports `ERR_DISPATCH_NOT_REQUIRED`
    rather than a generic state error."

    Design: Difficulty/cross_entity_state_dependency/visit_booking_rejected_when_ticket_dispatch_axis_never_escalated
    """
    world = _triaged_only_world()

    response = api.book_visit(
        {"ticket_id": world["ticket"]["id"], "slot_id": world["slots"][0]["id"]}, AGENT
    )
    error = validate_error(response, ApiErrorId.ERR_DISPATCH_NOT_REQUIRED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value


def test_dispatch_not_required_rejection_occupies_no_slot(api):
    """PRD 2.9 rung 27: "with one exemption: visit booking does **not** report this
    error for a ticket that is simply not dispatch-ready. The dispatch-readiness of a
    ticket is reported by rung 40 instead, so that rung remains reachable for tickets
    still in `NEW`, `TRIAGED` or `REMOTE_DIAG`."
    PRD 3.5: "A `SupportAgent` records the first response with a `note`, which moves
    `NEW → TRIAGED`; that transition additionally requires `first_response_at` to
    still be null."

    Design: Difficulty/cross_entity_state_dependency/visit_booking_rejected_when_ticket_dispatch_axis_never_escalated
    """
    world = _triaged_only_world()

    api.book_visit(
        {"ticket_id": world["ticket"]["id"], "slot_id": world["slots"][0]["id"]}, AGENT
    )

    assert fetch_slot(world["slots"][0]["id"])["status"] == "OPEN"
    technician = fetch_technician(world["technician"]["id"])
    assert technician["open_slot_count"] == 1
    assert technician["booked_slot_count"] == 0
    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["workflow_status"] == "TRIAGED"
    assert ticket["dispatch_status"] == "NOT_REQUIRED"


# ==========================================================================
# Difficulty: slot capacity is conserved across booking and an early cancel
# ==========================================================================
def _early_cancel_world():
    world = setup_dispatch_world(
        slots=(
            ("2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z"),
            ("2026-05-10T13:00:00Z", "2026-05-10T15:00:00Z"),
        ),
        plan_kind="PRO",
        allow_overage=False,
        technician_name="Cap Tech",
        name="Capacity House",
        email_prefix="cap2",
    )
    ticket = setup_escalated_ticket(world, severity="P1", summary="Needs a technician")
    world["ticket"] = ticket
    world["visit"] = book(ticket["id"], world["slots"][0]["id"])
    # The late-cancel cutoff is 2026-05-09T09:00Z; 2026-05-08 is before it.
    set_clock("2026-05-08T00:00:00Z")
    return world


def test_early_cancellation_books_no_fee_and_returns_the_slot_to_open(api):
    """PRD 3.8: "When the cancellation happens at or before the cutoff it is an early
    cancellation: `fee_kind` stays `NONE`, `fee_cents` stays 0, `fee_waived` stays
    false, and the slot returns to `OPEN`, raising `open_slot_count` and lowering
    `booked_slot_count` by one each."
    PRD 3.8: "In every case `cancelled_at` is stamped with the logical-clock instant,
    `Visit.status` becomes `CANCELLED`, the ticket moves `ONSITE → DISPATCH_PENDING`
    on the workflow axis and `SCHEDULED → RESCHEDULING` on the dispatch axis, and
    `Visit.version` rises by one."

    Design: Difficulty/compensating_invariant/slot_capacity_conserved_across_book_and_early_cancel
    """
    world = _early_cancel_world()

    data = validate_success(api.cancel_visit(world["visit"]["id"], {}, AGENT), 200)

    assert data["status"] == "CANCELLED"
    assert data["fee_kind"] == "NONE"
    assert data["fee_cents"] == 0
    assert data["fee_waived"] is False
    assert fetch_slot(world["slots"][0]["id"])["status"] == "OPEN"
    assert fetch_slot(world["slots"][1]["id"])["status"] == "OPEN"
    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["workflow_status"] == "DISPATCH_PENDING"
    assert ticket["dispatch_status"] == "RESCHEDULING"


def test_book_then_early_cancel_restores_every_slot_counter(api):
    """PRD 2.10: "For every technician, `open_slot_count` plus `booked_slot_count` plus
    `blocked_slot_count` equals `total_slot_count`. Booking moves a slot from open to
    booked; an early cancellation moves it back; a late cancellation or a no-show
    moves it to blocked. No path may leave a slot uncounted."
    PRD 3.2: "`next_invoice_adjustment_cents` carries the chargeable side: overage
    charges, add-on order totals, late-cancellation and no-show fees, and charged
    advance-replacement holds."

    Design: Difficulty/compensating_invariant/slot_capacity_conserved_across_book_and_early_cancel
    """
    world = _early_cancel_world()

    validate_success(api.cancel_visit(world["visit"]["id"], {}, AGENT), 200)

    assert_slot_counts(
        fetch_technician(world["technician"]["id"]), total=2, open_count=2, booked=0, blocked=0
    )
    assert (
        fetch_subscription(world["subscription"]["id"])["next_invoice_adjustment_cents"] == 0
    )


# ==========================================================================
# Difficulty: visit completion reverses the middle of the escalation cascade
# ==========================================================================
def _visit_completion_world():
    world = setup_ring(
        device_count=2,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.5,
        plan_kind="PRO",
        allow_overage=False,
        name="Unblock House",
        email_prefix="unb",
    )
    device_one = world["devices"][0]
    ticket = new_ticket(
        world["household"]["id"],
        AGENT,
        severity="P1",
        summary="Hub hardware fault",
        device_id=device_one["id"],
    )
    escalate_by_hardware_fault(ticket["id"])

    technician = new_technician("Tess Tech", "NWA", ["HUB", "CAMERA"])
    slot = publish_slot(technician["id"], "2026-05-02T09:00:00Z", "2026-05-02T11:00:00Z")
    visit = book(ticket["id"], slot["id"])
    set_clock("2026-05-02T09:30:00Z")

    world["ticket"] = ticket
    world["technician"] = technician
    world["slot"] = slot
    world["visit"] = visit
    return world


def test_visit_completion_resolves_the_ticket_without_freeing_the_slot(api):
    """PRD 3.8: "On success the visit becomes `COMPLETED` with `fee_kind` left at
    `NONE` and `fee_cents` left at 0; the occupied slot **stays `BOOKED`** — a
    completed visit does not free capacity; the ticket moves `ONSITE → RESOLVED` on
    the workflow axis and `SCHEDULED → COMPLETED` on the dispatch axis, with
    `resolved_at` stamped and `survey_solicited_at` stamped on the first resolution
    only"

    Design: Difficulty/transitive_cascade/visit_completion_cascades_four_hops_to_unblock_rollout
    """
    world = _visit_completion_world()

    data = validate_success(
        api.complete_visit(
            world["visit"]["id"],
            {"completion_notes": "Radio module replaced."},
            make_technician_headers(world["technician"]["id"]),
        ),
        200,
    )

    assert data["status"] == "COMPLETED"
    assert data["fee_cents"] == 0
    assert data["fee_kind"] == "NONE"
    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["workflow_status"] == "RESOLVED"
    assert ticket["dispatch_status"] == "COMPLETED"
    assert fetch_slot(world["slot"]["id"])["status"] == "BOOKED"


def test_visit_completion_releases_the_device_and_returns_its_rollout_to_pending(api):
    """PRD 3.8: "That release is itself a small cascade: the device moves `SERVICE_HOLD
    → ACTIVE`, and every rollout of that device sitting in `BLOCKED_BY_SERVICE` whose
    owning campaign is `RING_ACTIVE` returns to `PENDING` with the device's
    `firmware_status` returning to `UPDATE_PENDING`."
    PRD 3.9: "Whenever an operation leaves a `RING_ACTIVE` campaign's current ring with
    no rollout in `PENDING` while `ring_failure_rate` is strictly below
    `halt_failure_rate_pct`, the campaign becomes `COMPLETED`, which is terminal."

    The sibling device's rollout never left `PENDING`, so the ring is never emptied
    and the campaign stays `RING_ACTIVE` throughout.

    Design: Difficulty/transitive_cascade/visit_completion_cascades_four_hops_to_unblock_rollout
    """
    world = _visit_completion_world()

    validate_success(
        api.complete_visit(
            world["visit"]["id"],
            {"completion_notes": "Radio module replaced."},
            make_technician_headers(world["technician"]["id"]),
        ),
        200,
    )

    device = fetch_device(world["devices"][0]["id"])
    assert device["lifecycle_status"] == "ACTIVE"
    assert device["firmware_status"] == "UPDATE_PENDING"
    assert fetch_rollout(world["rollouts"][0]["id"])["status"] == "PENDING"
    assert fetch_campaign(world["campaign_id"])["status"] == "RING_ACTIVE"
