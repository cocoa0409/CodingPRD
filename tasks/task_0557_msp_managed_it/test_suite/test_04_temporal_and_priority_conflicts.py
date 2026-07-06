"""Temporal-overlap and validation-priority rules: technician double-booking,
patch-window overlap adjacency, SLA breach at exact due instant, and the
priority-ordering pairs from PRD §2.7."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_client,
    create_site,
    create_contract,
    activate_contract,
    create_technician,
    create_asset,
    assign_asset_to_contract,
    create_ticket,
    assign_ticket,
    create_dispatch,
    create_patch_job,
    create_quote,
    send_quote,
    create_procurement_order,
    place_procurement_order,
    setup_active_contract,
    setup_active_contract_with_tech,
    setup_assigned_asset,
    setup_ticket_in_progress,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / technician_double_book_with_travel_buffer
# ---------------------------------------------------------------------------

def _setup_ticket_with_first_onsite(scheduled_start: str, scheduled_end: str):
    """Helper: build first ONSITE dispatch 08:00-09:00 for a tech, then a
    second IN_PROGRESS ticket assigned to the same tech ready for a second
    dispatch. Returns (ticket2, tech)."""
    client, contract, tech = setup_active_contract_with_tech()
    ticket1 = create_ticket(client["id"], contract["id"], priority="P2", subject="t1")
    ticket1 = assign_ticket(ticket1["id"], tech["id"])
    create_dispatch(
        ticket1["id"], tech["id"], mode="ONSITE",
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    ticket2 = create_ticket(client["id"], contract["id"], priority="P2", subject="t2")
    ticket2 = assign_ticket(ticket2["id"], tech["id"])
    return ticket2, tech


def test_technician_second_dispatch_inside_travel_buffer_is_rejected(api):
    """PRD §3.6: "the system stamps each dispatch with a read-only
    `travel_buffer_minutes` — 30 minutes for an `ONSITE` dispatch and 0 for
    a `REMOTE` one — that is applied *after* the scheduled window for conflict
    math. The technician's effective occupancy for a dispatch is therefore
    the interval from `scheduled_start` up to `scheduled_end` plus
    `travel_buffer_minutes`. When creating a dispatch, if that buffered
    interval overlaps the buffered interval of another non-cancelled dispatch
    already held by the same technician, the create is rejected with
    `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_double_book_with_travel_buffer
    """
    ticket2, tech = _setup_ticket_with_first_onsite(
        "2026-05-01T08:00:00Z", "2026-05-01T09:00:00Z",
    )
    # First dispatch's buffered end = 09:00 + 30m = 09:30; a 09:15 start collides.
    resp = api.create_dispatch(
        ticket2["id"],
        {"technician_id": tech["id"], "mode": "ONSITE",
         "scheduled_start": "2026-05-01T09:15:00Z",
         "scheduled_end": "2026-05-01T10:00:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


def test_technician_second_dispatch_after_travel_buffer_succeeds(api):
    """PRD §3.6: "the system stamps each dispatch with a read-only
    `travel_buffer_minutes` — 30 minutes for an `ONSITE` dispatch and 0 for
    a `REMOTE` one — that is applied *after* the scheduled window for conflict
    math. The technician's effective occupancy for a dispatch is therefore
    the interval from `scheduled_start` up to `scheduled_end` plus
    `travel_buffer_minutes`."

    Design: Difficulty/resource_temporal_overlap/technician_double_book_with_travel_buffer
    """
    ticket2, tech = _setup_ticket_with_first_onsite(
        "2026-05-01T08:00:00Z", "2026-05-01T09:00:00Z",
    )
    # 09:45 is after 09:30 buffered end — accepted.
    resp = api.create_dispatch(
        ticket2["id"],
        {"technician_id": tech["id"], "mode": "ONSITE",
         "scheduled_start": "2026-05-01T09:45:00Z",
         "scheduled_end": "2026-05-01T10:30:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / patch_window_overlap_adjacency_allowed
# ---------------------------------------------------------------------------

def test_patch_window_overlap_is_rejected(api):
    """PRD §3.4: "if its half-open `[window_start, window_end)` interval
    overlaps that of another patch job on the same asset that is still
    `SCHEDULED` or `RUNNING`, it is rejected with `ERR_PATCH_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/patch_window_overlap_adjacency_allowed
    """
    client, site, contract, asset = setup_assigned_asset()
    create_patch_job(
        asset["id"], "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z",
    )
    resp = api.create_patch_job(
        asset["id"],
        {"window_start": "2026-05-05T10:30:00Z",
         "window_end": "2026-05-05T11:30:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PATCH_WINDOW_CONFLICT)


def test_patch_window_adjacent_at_endpoint_is_accepted(api):
    """PRD §3.4: "Because the intervals are half-open, two windows that merely
    touch at an endpoint (one ending exactly when the next begins) do not
    conflict."

    Design: Difficulty/resource_temporal_overlap/patch_window_overlap_adjacency_allowed
    """
    client, site, contract, asset = setup_assigned_asset()
    create_patch_job(
        asset["id"], "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z",
    )
    resp = api.create_patch_job(
        asset["id"],
        {"window_start": "2026-05-05T11:00:00Z",
         "window_end": "2026-05-05T12:00:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / sla_response_breached_at_exact_due_instant
# ---------------------------------------------------------------------------

def _setup_p2_silver_ticket_at_zero():
    """Set clock to 2026-05-01T00:00:00Z, create SILVER contract & a P2 ticket
    (created_at = clock now) without assigning. SILVER + P2 response target is
    60 minutes ⇒ due at 01:00:00Z."""
    set_clock("2026-05-01T00:00:00Z")
    client, contract = setup_active_contract(
        contract_overrides={"seat_count": 5, "per_seat_rate_cents": 5000},
    )
    ticket = create_ticket(client["id"], contract["id"], priority="P2",
                           subject="slow")
    return ticket


def test_sla_response_not_breached_just_before_due(api):
    """PRD §3.5: "The response deadline is breached when either the ticket has
    no `first_response_at` and the clock now is at or past
    `sla_response_due_at`, or a `first_response_at` exists but falls strictly
    after `sla_response_due_at`."

    Design: Difficulty/boundary_precision_check/sla_response_breached_at_exact_due_instant
    """
    ticket = _setup_p2_silver_ticket_at_zero()
    set_clock("2026-05-01T00:59:00Z")
    data = validate_success(api.get_ticket(ticket["id"], TEST_USERS[SM]))
    assert data["sla_response_breached"] is False


def test_sla_response_breached_at_exact_due_instant(api):
    """PRD §3.5: "Note the boundary is inclusive on the "no response yet"
    branch: at exactly the due instant with nothing recorded, the deadline
    counts as breached."

    Design: Difficulty/boundary_precision_check/sla_response_breached_at_exact_due_instant
    """
    ticket = _setup_p2_silver_ticket_at_zero()
    set_clock("2026-05-01T01:00:00Z")
    data = validate_success(api.get_ticket(ticket["id"], TEST_USERS[SM]))
    assert data["sla_response_breached"] is True


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / patch_compliance_empty_set_default_100
# ---------------------------------------------------------------------------

def test_patch_compliance_100_when_no_completed_jobs(api):
    """PRD §3.4: "When the succeeded and failed counts together total zero
    — no completed patch jobs yet — compliance is 100.00 by default."

    Design: Difficulty/boundary_precision_check/patch_compliance_empty_set_default_100
    """
    client, site, contract, asset = setup_assigned_asset(asset_type="DESKTOP")
    data = validate_success(api.get_asset(asset["id"], TEST_USERS[SM]))
    assert data["patch_compliance_pct"] == 100.00


def test_patch_compliance_zero_after_one_failed_job(api):
    """PRD §3.4: "Otherwise it is 100 multiplied by the succeeded count,
    divided by the sum of the succeeded and failed counts, rounded half up
    to two decimal places."

    Design: Difficulty/boundary_precision_check/patch_compliance_empty_set_default_100
    """
    from test_helpers import (
        create_patch_job as fx_create_patch_job,
        start_patch_job,
        report_patch_job,
    )
    client, site, contract, asset = setup_assigned_asset(asset_type="DESKTOP")
    tech = create_technician(full_name="Ned Tech", hourly_rate_cents=8000)
    pj = fx_create_patch_job(
        asset["id"], "2026-05-05T00:00:00Z", "2026-05-05T01:00:00Z",
    )
    start_patch_job(pj["id"], tech["id"])
    report_patch_job(pj["id"], tech["id"], outcome="FAILED")
    data = validate_success(api.get_asset(asset["id"], TEST_USERS[SM]))
    assert data["patch_compliance_pct"] == 0.00


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / dispatch_state_precedes_technician_overlap
# ---------------------------------------------------------------------------

def test_dispatch_on_new_ticket_returns_ticket_not_dispatchable_before_overlap(api):
    """PRD §3.6: "the parent ticket must be dispatchable, meaning
    `IN_PROGRESS`; creating a dispatch on a ticket that is not `IN_PROGRESS`
    is rejected with `ERR_TICKET_NOT_DISPATCHABLE`."
    PRD §2.7: "(5) the target resource must be in a state that admits the
    requested transition, else a state error (`ERR_INVALID_STATE`, or the
    specific `ERR_TICKET_NOT_DISPATCHABLE` or `ERR_QUOTE_EXPIRED`); (6) any
    cross-entity reference must be in its required state, else
    `ERR_CONTRACT_NOT_ACTIVE`, `ERR_ASSET_NOT_MONITORED`, or
    `ERR_QUOTE_NOT_ACCEPTED`; (7) temporal-overlap checks, else
    `ERR_TECHNICIAN_DOUBLE_BOOKED` or `ERR_PATCH_WINDOW_CONFLICT`;"

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_precedes_technician_overlap
    """
    client, contract, tech = setup_active_contract_with_tech()
    # Ticket A → IN_PROGRESS with ONSITE dispatch 08:00-09:00 (buffered to 09:30).
    ticket_a = create_ticket(client["id"], contract["id"], priority="P2", subject="A")
    ticket_a = assign_ticket(ticket_a["id"], tech["id"])
    create_dispatch(
        ticket_a["id"], tech["id"], mode="ONSITE",
        scheduled_start="2026-05-01T08:00:00Z",
        scheduled_end="2026-05-01T09:00:00Z",
    )
    # Ticket B is still NEW: both a state violation (ticket not IN_PROGRESS)
    # AND a technician double-book would trigger. PRD §2.7 makes state (5)
    # strictly precede temporal-overlap (7).
    ticket_b = create_ticket(client["id"], contract["id"], priority="P2", subject="B")
    resp = api.create_dispatch(
        ticket_b["id"],
        {"technician_id": tech["id"], "mode": "ONSITE",
         "scheduled_start": "2026-05-01T08:30:00Z",
         "scheduled_end": "2026-05-01T09:30:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_DISPATCHABLE)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / place_order_referential_precedes_fiscal
# ---------------------------------------------------------------------------

def test_place_order_with_unaccepted_quote_and_low_credit_returns_quote_not_accepted(api):
    """PRD §3.7: "If a `quote_id` is linked, that quote must be `ACCEPTED`,
    otherwise the place is rejected with `ERR_QUOTE_NOT_ACCEPTED`. The order's
    `total_cents` must not exceed the client's `credit_available_cents` at
    place time; an order that would breach the ceiling is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED`."
    PRD §2.7: "(6) any cross-entity reference must be in its required state,
    else `ERR_CONTRACT_NOT_ACTIVE`, `ERR_ASSET_NOT_MONITORED`, or
    `ERR_QUOTE_NOT_ACCEPTED`; (7) temporal-overlap checks, else
    `ERR_TECHNICIAN_DOUBLE_BOOKED` or `ERR_PATCH_WINDOW_CONFLICT`; (8)
    constraint checks, else `ERR_EMPTY_LINE_ITEMS`, `ERR_NO_SEATS_AVAILABLE`,
    `ERR_SEAT_FLOOR_VIOLATION`, `ERR_INVALID_SEAT_DELTA`, or
    `ERR_INVALID_TIME_WINDOW`; (9) the fiscal ceiling check, else
    `ERR_CREDIT_LIMIT_EXCEEDED`;"

    Design: Difficulty/priority_pair_validation_conflict/place_order_referential_precedes_fiscal
    """
    client = create_client(
        company_name="Kappa", primary_contact_email="k@kappa.test",
        credit_limit_cents=100,
    )
    # PROCUREMENT quote SENT but not accepted.
    quote = create_quote(
        client["id"], "PROCUREMENT",
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
    )
    send_quote(quote["id"])
    # Order linked to the SENT quote, total exceeds credit_limit_cents (100).
    order = create_procurement_order(
        client["id"],
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
        quote_id=quote["id"],
    )
    resp = api.place_procurement_order(
        order["id"], TEST_USERS["account_manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED)


# ---------------------------------------------------------------------------
# Queue B: validations / patch_window_end_before_start_returns_invalid_time_window
# ---------------------------------------------------------------------------

def test_patch_window_end_at_or_before_start_returns_invalid_time_window(api):
    """PRD §3.4: "The window must be well-formed — `window_end` must be strictly
    after `window_start`, otherwise `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/patch_window_end_before_start_returns_invalid_time_window
    """
    client, site, contract, asset = setup_assigned_asset(asset_type="SERVER")
    resp = api.create_patch_job(
        asset["id"],
        {"window_start": "2026-05-05T03:00:00Z",
         "window_end": "2026-05-05T02:00:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
